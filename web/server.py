"""
deobf web front end: upload a protected Roblox script, get readable Luau back.

    pip install -r web/requirements.txt
    python web/server.py                 # http://127.0.0.1:8000
    uvicorn web.server:app --port 8000   # same thing

The HTTP layer only validates input and streams progress; every job is a
`deob.py` subprocess (jobs.py). `web/static/` is served at `/`, and the same
files work unchanged from GitHub Pages against a remote instance of this
server (CORS is open by default, see DEOB_CORS_ORIGINS).
"""
import asyncio
import json
import os
import subprocess
import sys
import time

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

RATE_WINDOW = 60.0
RATE_LIMIT = jobs._env_int("DEOB_RATE_LIMIT", 20)       # submissions per IP per minute
MAX_CFG = 8
MAX_CFG_LEN = 8192

app = FastAPI(title="deobf", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("DEOB_CORS_ORIGINS", "*").split(",") if o.strip()],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

_hits = {}


def rate_check(request, bucket="jobs", limit=RATE_LIMIT):
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    now = time.time()
    key = (bucket, ip)
    seen = [t for t in _hits.get(key, []) if now - t < RATE_WINDOW]
    if len(seen) >= limit:
        raise HTTPException(429, "too many requests: %d per minute" % limit)
    seen.append(now)
    _hits[key] = seen
    if len(_hits) > 4096:                       # keep the table from growing forever
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
            _hits.pop(k, None)


def size_check(request):
    """Refuse an oversized body before it is buffered into memory."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        return
    # JSON escaping can inflate the script a little, so allow some headroom
    if declared > jobs.MAX_UPLOAD * 2:
        raise HTTPException(413, "request too large: %d bytes (script limit %d)"
                            % (declared, jobs.MAX_UPLOAD))


# --------------------------------------------------------------------------
# plugin registry (a subprocess: the pipeline keeps global state, see CLAUDE.md)

_plugins = None


def plugins():
    global _plugins
    if _plugins is None:
        code = ("import json, sys; sys.path.insert(0, %r); import obfuscators; "
                "print(json.dumps([{'name': p.name, 'label': p.label, 'aliases': list(p.aliases)} "
                "for p in obfuscators.PLUGINS]))"
                % os.path.join(jobs.ROOT, "deobf"))
        try:
            out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                 text=True, timeout=60, cwd=jobs.ROOT)
            _plugins = json.loads(out.stdout)
        except Exception:                       # noqa: BLE001 - the UI falls back to "auto" only
            _plugins = []
    return _plugins


def luau_ready():
    exe = os.path.join(jobs.ROOT, "deobf", "bin", "luau")
    return os.path.exists(exe) and os.path.exists(exe + "-ast")


# --------------------------------------------------------------------------
# input handling

async def read_source(file, source):
    """The script text from either a multipart file or a JSON/form field."""
    if file is not None:
        data = await file.read(jobs.MAX_UPLOAD + 1)
        name = file.filename or "script.lua"
    elif source is not None:
        data = source.encode("latin-1", "replace") if isinstance(source, str) else source
        name = "pasted.lua"
    else:
        raise HTTPException(400, "send a file or a `source` field")
    if not data.strip():
        raise HTTPException(400, "the script is empty")
    if len(data) > jobs.MAX_UPLOAD:
        raise HTTPException(413, "script too large: %d bytes (limit %d)"
                            % (len(data), jobs.MAX_UPLOAD))
    return data.decode("latin-1"), name


def clamp(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def clean_options(raw):
    """Validate the options a browser sent into what build_argv() accepts."""
    raw = raw or {}
    if not isinstance(raw, dict):
        raise HTTPException(400, "options must be an object")
    # a plugin's old name still works, as it does on the command line
    names = {p["name"] for p in plugins()} | {a for p in plugins() for a in p.get("aliases", ())}
    obf = raw.get("obfuscator") or ""
    if obf and names and obf not in names:
        raise HTTPException(400, "unknown obfuscator %r" % obf[:40])
    opt = {
        "obfuscator": obf or None,
        "timeout": clamp(raw.get("timeout"), 10, 1800, 90),
        "budget": clamp(raw.get("budget"), 5, 900, 30),
        "executor": str(raw.get("executor") or "Wave")[:40],
        "no_devirt": bool(raw.get("no_devirt")),
        "no_fold": bool(raw.get("no_fold")),
        "no_tidy": bool(raw.get("no_tidy")),
        "keep_preamble": bool(raw.get("keep_preamble")),
        "strings": bool(raw.get("strings")),
        "input_text": (str(raw.get("input_text"))[:512] if raw.get("input_text") else None),
        "cfg": [],
    }
    cfg = raw.get("cfg") or []
    if isinstance(cfg, str):
        cfg = [line for line in cfg.splitlines() if line.strip()]
    if cfg and not jobs.ALLOW_ADVANCED:
        raise HTTPException(403, "runtime options are disabled on this instance")
    for line in cfg[:MAX_CFG]:
        line = str(line).strip()
        if not line:
            continue
        if "=" not in line:
            raise HTTPException(400, "runtime options are KEY=VALUE: %r" % line[:60])
        if len(line) > MAX_CFG_LEN:
            raise HTTPException(400, "runtime option too long (limit %d)" % MAX_CFG_LEN)
        if line.startswith("@file:") or "=@file:" in line:
            raise HTTPException(400, "@file: values are not allowed over HTTP")
        opt["cfg"].append(line)
    return opt


def parse_options(options):
    if options is None or options == "":
        return {}
    if isinstance(options, dict):
        return options
    try:
        return json.loads(options)
    except ValueError:
        raise HTTPException(400, "options is not valid JSON")


# --------------------------------------------------------------------------
# API

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "luau": luau_ready(),
        "obfuscators": plugins(),
        "advanced": jobs.ALLOW_ADVANCED,
        "limits": {
            "max_upload": jobs.MAX_UPLOAD,
            "job_timeout": jobs.JOB_TIMEOUT,
            "result_ttl": jobs.RESULT_TTL,
            "rate_limit": RATE_LIMIT,
        },
        "queue": jobs.RUNNER.stats(),
    }


@app.post("/api/detect")
async def api_detect(request: Request, file: UploadFile = File(None), source: str = Form(None)):
    size_check(request)
    rate_check(request, "detect", RATE_LIMIT * 3)
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        source = body.get("source")
    text, name = await read_source(file, source)
    try:
        return jobs.detect(text, name)
    except jobs.JobError as e:
        raise HTTPException(e.status, e.message)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "detection timed out")


@app.post("/api/jobs")
async def api_submit(request: Request, file: UploadFile = File(None),
                     source: str = Form(None), options: str = Form(None)):
    size_check(request)
    rate_check(request)
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        source, options = body.get("source"), body.get("options")
        name_hint = body.get("name")
    else:
        name_hint = None
    text, name = await read_source(file, source)
    opt = clean_options(parse_options(options))
    job = jobs.Job(name_hint or name, text, opt)
    try:
        jobs.RUNNER.submit(job)
    except jobs.JobError as e:
        raise HTTPException(e.status, e.message)
    return JSONResponse(job.info(), status_code=202)


def need(jid):
    job = jobs.RUNNER.get(jid)
    if job is None:
        raise HTTPException(404, "unknown job (results are kept for %d seconds)" % jobs.RESULT_TTL)
    return job


@app.get("/api/jobs/{jid}")
def api_job(jid: str):
    return need(jid).info()


@app.get("/api/jobs/{jid}/log")
def api_log(jid: str, since: int = 0):
    job = need(jid)
    return {"since": since, "lines": job.tail(max(0, since)), "status": job.status}


@app.get("/api/jobs/{jid}/events")
async def api_events(jid: str):
    """Server-sent events: `log` lines as they appear, then `state` and `end`."""
    job = need(jid)

    async def stream():
        sent, last = 0, None
        while True:
            lines = job.tail(sent)
            if lines:
                sent += len(lines)
                yield "event: log\ndata: %s\n\n" % json.dumps(lines)
            state = job.info()
            if state != last:
                last = state
                yield "event: state\ndata: %s\n\n" % json.dumps(state)
            if job.status in ("done", "failed", "cancelled") and not job.tail(sent):
                yield "event: end\ndata: %s\n\n" % json.dumps(state)
                return
            await asyncio.sleep(0.3)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/jobs/{jid}/result")
def api_result(jid: str):
    job = need(jid)
    if job.result is None:
        raise HTTPException(409, job.error or "no result yet (status: %s)" % job.status)
    return PlainTextResponse(job.result, media_type="text/plain; charset=utf-8")


@app.get("/api/jobs/{jid}/download")
def api_download(jid: str):
    job = need(jid)
    if job.result is None:
        raise HTTPException(409, job.error or "no result yet (status: %s)" % job.status)
    name = jobs.safe_name(job.name).rsplit(".", 1)[0] + ".deobf.luau"
    return PlainTextResponse(
        job.result, media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@app.delete("/api/jobs/{jid}")
def api_cancel(jid: str):
    job = need(jid)
    job.cancel()
    return job.info()


# --------------------------------------------------------------------------
# the front end

if os.path.isdir(STATIC):
    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"))

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


def main():
    import uvicorn
    host = os.environ.get("DEOB_HOST", "127.0.0.1")
    port = jobs._env_int("PORT", 8000)
    if not luau_ready():
        print("[!] deobf/bin/luau and deobf/bin/luau-ast are missing: build them with\n"
              "    python deobf/build_luau.py --portable\n"
              "    (jobs will fail until then)", file=sys.stderr)
    print("[*] deobf web on http://%s:%d" % (host, port), file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level=os.environ.get("DEOB_LOG", "info"))


if __name__ == "__main__":
    main()
