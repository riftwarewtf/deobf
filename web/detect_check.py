"""
The page's detector and the pipeline's must agree, case for case.

`web/static/detect.js` exists so that pasting a script can name the obfuscator
without starting Pyodide and the Luau runtime (about 16 MB, most of what a
phone's tab is allowed). That means there are two implementations of the same
decision - the JavaScript one and `deobf/obfuscators/*` - and they drift
silently: the page keeps labelling scripts, just wrongly.

This runs every case through both and diffs the answers. Needs node.

    python web/detect_check.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "deobf"))

import obfuscators  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")
DETECT_JS = os.path.join(ROOT, "web", "static", "detect.js")

HEADER = "-- This file was protected using Luraph Obfuscator v%s [https://lura.ph/]\n"
# a legacy body: the "LPH|<hex, G = repeat>" bytecode literal (LURAPH.md)
LEGACY_BODY = ('local a, b = 0, "LPH|' + "4A3F" * 40 + '2G5B"\n'
               "local function f1() end local function f2() end\nreturn f1(f2())\n")
# every version seen in the wild, plus the legacy range and one from the future
VERSIONS = ("11", "11.8.1", "12.4", "13.0", "14", "14.3", "14.4.1", "14.4.2",
            "14.5.2", "14.7", "15", "15.0", "16.1", "20.0.3")

NODE_DRIVER = r"""
const fs = require("fs");
global.window = global;
require(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = {};
for (const [name, src] of Object.entries(cases)) {
  const d = window.DeobfDetect(src);
  out[name] = { obfuscator: d.obfuscator, label: d.label,
                confidence: Math.round(d.confidence * 10000) / 10000 };
}
fs.writeFileSync(process.argv[4], JSON.stringify(out));
"""


def sample(name):
    with open(os.path.join(SAMPLES, name), encoding="latin-1") as f:
        return f.read()


def build_cases():
    luraph = sample("001_vm_like_dispatch-obfuscated.lua")
    modern_body = luraph.split("\n", 1)[1]           # the VM without its header
    cases = {
        "the Luraph sample": luraph,
        "the Luraph sample, header cut": modern_body,
        "the ironbrew1 sample": sample("001_vm_like_dispatch-ib1.lua"),
        "a plain script": sample("001_vm_like_dispatch.lua"),
        "empty": "",
        "one line": "print(1)",
        "a legacy body, no header": LEGACY_BODY,
        "LPH| too short to be a payload": 'local s = "LPH|4A3F"',
        "the header quoted in running code":
            'local s = "This file was protected using Luraph Obfuscator v11.8"\nreturn s\n',
        "the header not at a line start":
            "  x = 1 -- This file was protected using Luraph Obfuscator v15.0\n",
    }
    for v in VERSIONS:
        cases["v%s header, legacy body" % v] = HEADER % v + LEGACY_BODY
        cases["v%s header, modern body" % v] = HEADER % v + modern_body
    return cases


def python_answers(cases):
    out = {}
    for name, src in cases.items():
        plugin, conf = obfuscators.detect(src)
        out[name] = {"obfuscator": plugin.name, "label": plugin.describe(src),
                     "confidence": round(conf, 4)}
    return out


def js_answers(cases):
    tmp = tempfile.mkdtemp(prefix="detect_check_")
    cpath = os.path.join(tmp, "cases.json")
    opath = os.path.join(tmp, "out.json")
    dpath = os.path.join(tmp, "driver.js")
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(cases, f)
    with open(dpath, "w", encoding="utf-8") as f:
        f.write(NODE_DRIVER)
    try:
        subprocess.run(["node", dpath, DETECT_JS, cpath, opath], check=True)
    except FileNotFoundError:
        sys.exit("[!] node is not installed: it runs web/static/detect.js")
    with open(opath, encoding="utf-8") as f:
        return json.load(f)


def main():
    cases = build_cases()
    py, js = python_answers(cases), js_answers(cases)
    bad = 0
    for name in cases:
        a, b = py[name], js[name]
        if a == b:
            print("  %-38s %s / %s / %.2f" % (name[:38], a["obfuscator"], a["label"], a["confidence"]))
            continue
        bad += 1
        print("  %-38s python: %s / %s / %.2f" % (name[:38], a["obfuscator"], a["label"], a["confidence"]))
        print("  %-38s     js: %s / %s / %.2f" % ("", b["obfuscator"], b["label"], b["confidence"]))
    print("\n%d case(s): %s" % (len(cases), "all agree" if not bad else "%d DISAGREE" % bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
