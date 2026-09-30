"""
Runs the deobf pipeline inside Pyodide, with no processes and no real files
for the Luau binaries.

The pipeline shells out to `luau` and `luau-ast` from five places (harness,
luauast, names, localfuncs, vmmap). Rather than edit any of them, this module
patches the two seams they all go through - subprocess.run and
harness._communicate - and routes them into the WebAssembly Luau the page
already has. Everything above that seam is the same code the CLI runs.

The page calls install() once, then deobfuscate() per job.
"""
import os
import subprocess
import sys

import js       # the worker's global scope: deobfLuauRun / deobfLuauAst

ROOT = "/deobf"
FAKE_LUAU = os.path.join(ROOT, "bin", "luau")        # never executed, only matched


# --------------------------------------------------------------------- shims

def _read_latin1(path):
    with open(path, encoding="latin-1") as f:
        return f.read()


def _call_luau(path):
    """`luau <file>`: run the harness, give back (stdout, stderr, status)."""
    res = js.deobfLuauRun(_read_latin1(path), "@" + path)
    return res.output, res.error, (0 if res.ok else 1)


def _call_luau_ast(path):
    """`luau-ast <file>`: the AST as JSON on stdout, parse errors on stderr."""
    res = js.deobfLuauAst(_read_latin1(path))
    return res.output, res.error, res.code


def _which(cmd):
    """Which of the two binaries a command line means, if either."""
    if not isinstance(cmd, (list, tuple)) or not cmd:
        return None
    name = os.path.basename(str(cmd[0])).lower()
    for suffix in (".exe", ""):
        if name == "luau-ast" + suffix:
            return _call_luau_ast
        if name == "luau" + suffix:
            return _call_luau
    return None


_real_run = subprocess.run
_real_popen = subprocess.Popen


def _run(cmd, *args, **kwargs):
    handler = _which(cmd)
    if handler is None:
        return _real_run(cmd, *args, **kwargs)

    out, err, code = handler(cmd[1])
    if kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding"):
        stdout, stderr = out, err
    else:
        stdout = out.encode("latin-1", "replace")
        stderr = err.encode("latin-1", "replace")
    if kwargs.get("check") and code != 0:
        raise subprocess.CalledProcessError(code, cmd, stdout, stderr)
    return subprocess.CompletedProcess(cmd, code, stdout, stderr)


class _NoProcess(RuntimeError):
    """Raised where the pipeline would start a long-lived process. Its callers
    already handle this: the Luraph driver falls back to running the script
    once per round ("the long-lived harness failed: ...")."""


def _popen(*args, **kwargs):
    raise _NoProcess("no subprocesses in the browser")


def install():
    """Patch the seams. The caller has already unpacked deobf/ into the virtual
    file system (it holds this module, so it cannot unpack itself)."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    subprocess.run = _run
    subprocess.Popen = _popen

    import harness

    # find_luau() would exit: there is no binary to find, and the fake path is
    # only ever matched by _which()
    harness.find_luau = lambda: FAKE_LUAU
    harness.luau_ast = lambda: os.path.join(ROOT, "bin", "luau-ast")

    # run_once() calls this instead of spawning; the timeout and the stall
    # watchdog are the worker's job, since a WebAssembly call cannot be killed
    # from inside Python
    def _communicate(cmd, timeout, stall):
        out, err, _code = _call_luau(cmd[1])
        return out.encode("latin-1", "replace"), err.encode("latin-1", "replace")
    harness._communicate = _communicate

    # The Luraph driver answers its constant rounds from one long-lived
    # harness process, which needs stdin and require(). DEOB_NO_SERVE is its
    # own switch for that: the driver then does a fresh run per round, which
    # is what a browser can do. (Patching HarnessServer to raise is not enough
    # - driver.lift() constructs it outside any try.)
    os.environ["DEOB_NO_SERVE"] = "1"
    harness.HarnessServer = _popen

    # backend.run_big_stack() runs the lifter in a thread with a 256 MB stack
    # because deeply nested scripts recurse hard. There are no threads here, so
    # call it directly - the worker asks Pyodide for a large stack instead.
    import backend
    def _big_stack(fn, *a):
        sys.setrecursionlimit(200000)
        return fn(*a)
    backend.run_big_stack = _big_stack

    return len(os.listdir(ROOT))


# ---------------------------------------------------------------- the job

def detect(source):
    """(name, confidence, label) without running anything."""
    import obfuscators
    plugin, conf = obfuscators.detect(source)
    # describe(): the version where the plugin knows one ("Luraph v14.4.2")
    return {"obfuscator": plugin.name, "confidence": conf, "label": plugin.describe(source)}


def deobfuscate(source, name="script.lua", options=None):
    """Run the pipeline over `source`; returns the result text.

    Mirrors deob.main() minus the parts that need a real machine (the PyPy
    re-exec, the output folder, --studio).
    """
    import deob
    import obfuscators
    from obfuscators.base import Job

    options = dict(options or {})
    workdir = "/work"
    os.makedirs(workdir, exist_ok=True)
    in_path = os.path.join(workdir, os.path.basename(name) or "script.lua")
    with open(in_path, "w", encoding="latin-1", newline="") as f:
        f.write(source)

    argv = [in_path, "--no-pypy"]
    if options.get("obfuscator"):
        argv += ["--obfuscator", options["obfuscator"]]
    if options.get("no_devirt"):
        argv.append("--no-devirt")
    if options.get("no_fold"):
        argv.append("--no-fold")
    if options.get("no_tidy"):
        argv.append("--no-tidy")
    if options.get("keep_preamble"):
        argv.append("--keep-preamble")
    if options.get("strings"):
        argv.append("--strings")
    if options.get("input_text"):
        argv += ["--input-text", str(options["input_text"])]
    argv += ["--timeout", str(options.get("timeout", 90))]
    argv += ["--budget", str(options.get("budget", 30))]
    argv += ["--executor", str(options.get("executor", "Wave"))]
    for kv in options.get("cfg", []):
        argv += ["--cfg", kv]

    args = deob.parser().parse_args(argv)

    if options.get("obfuscator"):
        plugin, conf = obfuscators.by_name(options["obfuscator"]), None
    else:
        plugin, conf = obfuscators.detect(source)
    label = plugin.describe(source)
    print("[*] obfuscator: %s%s" % (label, "" if conf is None else " (detected, %.2f)" % conf),
          file=sys.stderr)

    trace_path = os.path.join(workdir, os.path.basename(in_path) + ".deobf.luau")
    job = Job(in_path, source, args, trace_path, False, label)
    result = plugin.deobfuscate(job)
    if not result or not os.path.exists(result):
        raise RuntimeError("the pipeline produced no result")
    with open(result, encoding="utf-8", errors="replace") as f:
        return f.read()
