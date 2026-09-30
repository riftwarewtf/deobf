# deobf

**Protected Roblox Luau in, readable Luau out — in your browser.**

deobf is a *dynamic* deobfuscator. It does not pattern-match the protection
away: it runs the protected script in a real Luau VM against a fake
Roblox/executor environment, watches what it does, and rebuilds source from
that. For the obfuscators it knows it goes further and lifts the VM bytecode
back to real Luau — with control flow, locals, closures, and the branches that
never ran.

This repository is the pipeline plus a web front end for it.

| Obfuscator | Detection | Output |
|---|---|---|
| Luraph v14, v15 and newer | automatic, with the version | devirtualized Luau (falls back to a trace) |
| Luraph up to v13 (the legacy Lua 5.1 VM) | automatic, with the version | behaviour trace, rendered as Luau |
| IronBrew 1 | automatic | devirtualized Luau (falls back to a trace) |
| anything else | fallback | behaviour trace, rendered as Luau |

Luraph writes its version into a comment at the top of every script it makes,
and the page reports it (`Luraph v14.4.2`). Up to v13 the VM is a different
machine - a Lua 5.1 interpreter with its bytecode in an `LPH|...` literal - and
there is no lifter for it yet, so those get the trace and the page says so
instead of letting a run find out.

---

## Use it

**<https://riftwarewtf.github.io/deobf/>** — paste a script, press Deobfuscate,
read the Luau. Nothing to install and no server: Luau is compiled to
WebAssembly and the pipeline runs on Python (Pyodide) inside the page. The
first run downloads about 16 MB, then it is cached.

The same repo also runs as a normal web service, which is worth it for big
scripts: the browser does the identical work, but Python in the page is
several times slower than native, and a large Luraph script can take minutes
either way. The page has a switch for pointing at a server you run.

### As a server — Docker (one command)

```bash
git clone https://github.com/riftwarewtf/deobf
cd deobf
docker compose up --build        # http://localhost:8000
```

The first build takes a few minutes — it compiles a patched Luau from source
(see [Why a patched Luau](#why-a-patched-luau)). After that it starts instantly.

### As a server — without Docker

```bash
git clone https://github.com/riftwarewtf/deobf
cd deobf
python deobf/build_luau.py --portable    # once: needs git, cmake, a C++ compiler
pip install -r web/requirements.txt
python web/server.py                     # http://127.0.0.1:8000
```

Open the address, drop in a `.lua`/`.luau` file, hit **Deobfuscate**. The
obfuscator is detected as soon as the script is loaded; the log tab streams
what the pipeline is doing while it works.

### How the browser build works

`web/static/` has no build step and no third-party CDN, so GitHub Pages serves
it as is. Two pieces make the pipeline run there:

- **`web/wasm/`** builds Luau to WebAssembly (`build_wasm.py`), mirroring the
  native CLI closely enough that the output is byte-identical — same compile
  options, same sandboxing, and `loadstring`, which is a CLI addition rather
  than part of Luau and which protected scripts use constantly.
- **`web/browser/bootstrap.py`** patches the two places the pipeline reaches
  for those binaries — `subprocess.run` and `harness._communicate` — and
  routes them into that WebAssembly module. Everything above that seam is the
  same code the CLI runs, unmodified.

Your script never leaves the tab: there is nothing to upload to.

`.github/workflows/pages.yml` publishes on every push. Enable it once under
**Settings → Pages → Source: GitHub Actions**.

---

## Use it from the command line

The web front end is a wrapper around the CLI, which is still the fastest path
for one-off work:

```bash
python deobf/deob.py script.lua               # -> script's folder/output/script.lua
python deobf/deob.py script.lua --detect      # NAME<tab>confidence<tab>label
python deobf/deob.py script.lua --no-devirt   # fast: behaviour trace only
python deobf/deob.py script.lua --debug       # keep every intermediate file
python deobf/deob.py --help                   # everything else
```

Scripts that read their settings from `_G`/`getgenv()` stop early on their own
("you didn't set a webhook"). Drive them further with runtime options, on the
command line or in the page's **Advanced** box:

```bash
--cfg "prelude=rawset(G,'webhook','x') setprop(game,'PlaceId',123)"
--cfg falsy=isPremium,hasGamepass
```

## HTTP API

Everything the page does is available directly. Full reference in
[`web/README.md`](web/README.md).

```bash
curl -F file=@script.lua http://localhost:8000/api/detect

JOB=$(curl -sF file=@script.lua http://localhost:8000/api/jobs | jq -r .id)
curl -N  http://localhost:8000/api/jobs/$JOB/events     # live progress (SSE)
curl -sO http://localhost:8000/api/jobs/$JOB/download   # the result
```

---

## How it works

1. **Detect** — each plugin scores the source (header comments, signature
   strings, VM shape). The best score above 0.5 wins; below that the generic
   trace runs.
2. **Trace** — the script runs in the real Luau VM. Every Roblox object is a
   proxy, so every property set, method call and event connection is recorded
   and rendered back as Luau. Nothing touches the network or Roblox.
3. **Lift** (known VM obfuscators) — the VM's bytecode and captured closures
   are walked into an IR, then structured back into real Luau: control flow,
   loops, locals, closures, and branches the trace never took.
4. **Polish** — repeated statement runs fold back into helper functions and
   loops, locals get names inferred from how they are used (the originals are
   not in the bytecode), and the text is spaced like normal Luau.

`CLAUDE.md` documents the architecture; `LURAPH.md` and `IRONBREW1.md` cover
the two VM front ends.

### Why a patched Luau

In Roblox, `Vector3` *is* the native vector type and the engine hangs the
Vector3 members off its metatable. Stock Luau freezes that metatable, so
`v.Magnitude` and `v:Dot(w)` fail and scripts that use them die mid-trace.
`deobf/build_luau.py` builds Luau 0.739 with that one freeze removed. This is
why the binaries are built rather than downloaded, and why they are not
committed.

## Layout

```
deobf/            the pipeline (pure Python, standard library only)
  deob.py         CLI entry point
  harness.py      builds and runs the Luau harnesses
  envlog.luau     the fake Roblox/executor environment
  obfuscators/    one plugin per obfuscator
  bin/            luau, luau-ast (built, git-ignored)
web/
  server.py       FastAPI app: upload, progress, result
  jobs.py         job queue; one deob.py subprocess per job
  smoke.py        end-to-end check against samples/
  wasm/           Luau -> WebAssembly for the browser build
  browser/        the Pyodide shim + the pipeline packer
  static/         the page: engine.js picks browser or server
samples/          test scripts + their expected output
```

## Notes

- **It executes the script you give it.** That is the whole method — there is
  no static mode. The Luau VM it runs in has no `io` library and no network
  and the Roblox side is a fake, so in the browser the script is confined to
  the tab's WebAssembly sandbox. If you run the server instead, treat it as
  something that runs untrusted code and keep it isolated; the container runs
  as a non-root user. Only feed it scripts you are allowed to inspect.
- **Devirtualizing is heavy.** A 947 KB Luraph script measured 321 MB and two
  minutes natively; the same script traces in 87 MB and six seconds. A phone
  tab gets far less than that, so on iOS or Android the browser usually kills
  the page mid-lift - the page warns before starting such a run and offers
  Trace only, which is much lighter and still readable. For the full lift on a
  big script, use a computer, or run the server.
- Results over 500 lines are download-only (with a "show it anyway" button). The viewer draws just the lines on
  screen and copes with far more, but a result that big means the run was near
  what a tab can hold, and drawing it is the last thing that should spend
  memory. The downloaded file is the whole result either way.
- **Runs can be reported to Discord.** Off by default. On a server, set
  `DEOB_DISCORD_WEBHOOK` and the URL stays there; in the page, fill in
  `web/static/config.js` and accept that the webhook is then public to every
  visitor. Either way the report is an embed plus the input and output as
  attachments, and the page says so in its footer when it is on.
- A trace only contains the branches that actually ran. Devirtualized output
  includes untaken branches; trace output notes conditions in comments.
- Local names are inferred from use. The original names are not in the
  bytecode and cannot be recovered.
- Large Luraph scripts take minutes, and the pipeline re-runs the script when
  it trips an anti-tamper trap. The log tab shows each round.
