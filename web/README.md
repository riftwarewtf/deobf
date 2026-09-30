# web front end

Two pieces: a FastAPI server (`server.py` + `jobs.py`) and a static page
(`static/`) that talks to it. The page has no build step and no dependencies,
so it also runs straight from GitHub Pages against a server you host.

```bash
pip install -r web/requirements.txt
python web/server.py                        # http://127.0.0.1:8000
uvicorn web.server:app --port 8000          # same, with uvicorn's own flags
python web/smoke.py                         # end-to-end check against samples/
python web/detect_check.py                  # the page's detector vs the pipeline's
```

The server needs `deobf/bin/luau` and `deobf/bin/luau-ast`
(`python deobf/build_luau.py --portable`). `/api/health` reports `luau: false`
until they exist, and the page says so instead of failing per job.

## Naming the obfuscator twice

`static/detect.js` is a JavaScript copy of the plugins' `detect()` (and, for
Luraph, of `obfuscators/luraph_v15/versions.py`), so that pasting a script can
label it without starting Pyodide and the Luau runtime - about 16 MB, which on
a phone is most of what the tab is allowed. The run detects again in Python,
and that is the one that decides which plugin executes.

Two implementations of one decision drift silently: the page keeps labelling
scripts, just wrongly. `python web/detect_check.py` runs both over the samples,
every Luraph version seen in the wild and the near misses (a header quoted in
code, an `LPH|` string too short to be a payload) and diffs the answers. Run it
after touching either side. It needs node.

## How a job runs

Every upload becomes one `deob.py` subprocess in its own temp folder. The
pipeline keeps module-level state (the Path2D cache, the last raw run), so it
must not be imported into a long-lived process — `jobs.py` shells out on
purpose. Jobs run on a small thread pool with a bounded queue; the process
group is killed on timeout or cancel, the temp folder is removed either way,
and the result is held in memory until its TTL expires.

Progress is the pipeline's own `[*]`/`[+]`/`[!]` output, streamed to the
browser as server-sent events and mapped to five stages (detect, trace, lift,
polish, done). Temp paths are stripped from the lines before they leave the
server.

## Configuration

All environment variables, all optional:

| Variable | Default | What it does |
|---|---|---|
| `PORT` | `8000` | port to listen on |
| `DEOB_HOST` | `127.0.0.1` | bind address (the Docker image sets `0.0.0.0`) |
| `DEOB_CONCURRENCY` | `2` | jobs running at the same time |
| `DEOB_MAX_QUEUE` | `16` | jobs allowed to wait; further submissions get 503 |
| `DEOB_JOB_TIMEOUT` | `900` | hard wall-clock cap per job, seconds |
| `DEOB_MAX_UPLOAD` | `12582912` | biggest accepted script, bytes |
| `DEOB_RESULT_TTL` | `3600` | how long a finished result stays fetchable, seconds |
| `DEOB_MAX_LOG_LINES` | `4000` | log lines kept per job |
| `DEOB_RATE_LIMIT` | `20` | submissions per IP per minute |
| `DEOB_ALLOW_ADVANCED` | `1` | `0` rejects `--cfg` runtime options from the browser |
| `DEOB_CORS_ORIGINS` | `*` | comma-separated origins; set this if the page is on Pages |
| `DEOB_LOG` | `info` | uvicorn log level |
| `DEOB_DISCORD_WEBHOOK` | (unset) | report every finished job to this Discord webhook |
| `DEOB_DISCORD_MAX_ATTACHMENT` | `3145728` | cap per attached file, bytes |
| `DEOB_DISCORD_MAX_TOTAL` | `6291456` | cap for all attachments in one report, bytes |

A job's own `--timeout` and `--budget` come from the request and are clamped
(10–1800 s and 5–900 s). `DEOB_JOB_TIMEOUT` is the outer cap and always wins.

## API

`POST` bodies are either `multipart/form-data` (`file`, `options`) or JSON
(`source`, `name`, `options`).

| Route | What you get |
|---|---|
| `GET /api/health` | plugins, limits, queue depth, whether Luau is present |
| `POST /api/detect` | `{obfuscator, confidence, label}` — no VM run, fast |
| `POST /api/jobs` | `202` + the job, which starts immediately |
| `GET /api/jobs/{id}` | status, stage, detected obfuscator, sizes, elapsed |
| `GET /api/jobs/{id}/events` | SSE: `log`, `state`, `end` |
| `GET /api/jobs/{id}/log?since=N` | the same lines, for polling |
| `GET /api/jobs/{id}/result` | the deobfuscated Luau as text |
| `GET /api/jobs/{id}/download` | the same, as a `.deobf.luau` attachment |
| `DELETE /api/jobs/{id}` | cancel; kills the subprocess |

Interactive docs are at `/api/docs`.

### Options

Everything the CLI takes that makes sense over HTTP:

```json
{
  "obfuscator": null,          // null = auto-detect, else a plugin name
  "no_devirt": false,          // true = behaviour trace only (fast)
  "timeout": 90,               // seconds per pipeline run
  "budget": 30,                // seconds of traced script time
  "executor": "Wave",          // what identifyexecutor() returns
  "input_text": null,          // what TextBoxes contain when handlers are traced
  "strings": false,            // also dump every string the script builds
  "no_fold": false,            // don't fold repeats into helpers and loops
  "keep_preamble": false,      // keep the obfuscator's anti-tamper probes
  "no_tidy": false,            // raw trace, skip the readability pass
  "cfg": ["falsy=isPremium"]   // --cfg KEY=VALUE runtime options
}
```

`cfg` values are capped in count and length, `@file:` is rejected, and the
whole field can be turned off with `DEOB_ALLOW_ADVANCED=0`.

### Example

```bash
JOB=$(curl -sF file=@script.lua -F 'options={"no_devirt":true}' \
        http://localhost:8000/api/jobs | jq -r .id)
curl -N http://localhost:8000/api/jobs/$JOB/events
curl -s http://localhost:8000/api/jobs/$JOB/result
```

## Reporting runs to Discord

With `DEOB_DISCORD_WEBHOOK` set, each finished job is posted to that webhook:
an embed with the obfuscator, mode, sizes, line counts and how long it took
(the error instead, when it failed), plus the script that went in and the Luau
that came out as attachments. It runs on a daemon thread and swallows its own
failures - a revoked webhook or a rate limit never affects a job.

Set this way the URL stays on the server. The page has an equivalent reporter
for runs that happen in the browser (`static/discord-log.js`, configured in
`static/config.js`), but a webhook that the page can use is necessarily public:
anyone reading the page source can post to that channel or delete the webhook.
`static/config.js` ships empty for that reason; it explains the options.

To avoid reporting a run twice, the page skips jobs it sent to a server - the
server reports those itself.

Attachments are capped (`DEOB_DISCORD_MAX_*`) because Discord takes 8 MB per
request on an unboosted server; anything larger is truncated and the embed says
so.

## The page

`static/index.html`, `style.css`, `app.js` and `luau.js` (a small Luau
highlighter). On load the page probes `/api/health` on its own origin; if that
fails it asks for a backend URL and keeps it in `localStorage`. Serving
`static/` from anywhere else — Pages, a CDN, a file:// path — works the same,
as long as the server's `DEOB_CORS_ORIGINS` lets that origin in.

One browser rule to know about: a page served over **HTTPS** (Pages is) may
only call an HTTPS backend. `http://localhost` and `http://127.0.0.1` are
exempt — browsers count them as trustworthy — so running the server on your own
machine works from the Pages site as is. A server on another host needs TLS
(a reverse proxy, a tunnel, or whatever your host gives you).
