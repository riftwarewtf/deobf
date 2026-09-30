"""Luraph plugin: devirtualizer + behaviour trace (notes: LURAPH.md).

Every Luraph generation lands here. `versions.py` says which one an input is
and whether lifting is worth a run; the version goes into the result's
"Detected obfuscation" line and onto the web page.
"""
import re
import sys

from obfuscators.base import Obfuscator
from obfuscators.luraph_v15 import versions

HEADER_LINE = re.compile(r"\s*--[ \t]*This file was protected using Luraph Obfuscator v[\d.]+[ \t]*"
                         r"\[https?://lura\.ph/?\]")


class LuraphV15(Obfuscator):
    name = "luraph"
    aliases = ("luraph_v15",)       # what this plugin used to be called
    label = "Luraph"
    doc = "LURAPH.md"

    def detect(self, source):
        return versions.classify(source).confidence

    def describe(self, source):
        return versions.classify(source).label

    def add_arguments(self, ap):
        g = ap.add_argument_group("Luraph")
        g.add_argument("--no-hooks", action="store_true",
                       help="do not instrument VM functions (no anti-tamper trap attribution, no lifting)")
        g.add_argument("--max-runs", type=int, default=12, help="maximum number of trace runs (trap reruns)")
        g.add_argument("--devirt-rounds", type=int, default=200,
                       help="max lift + constant-request rounds (default 200; stops early when no new "
                            "constants turn up)")

    def deobfuscate(self, job):
        from obfuscators.luraph_v15 import driver
        fixed = restore_header_newline(job.source)
        if fixed != job.source:
            # the copy keeps the input's name (Path2D cache, messages use job.input)
            print("[*] header comment ran into the code (lost newline): split it", file=sys.stderr)
            job.source = fixed
            job.source_path = job.write(job.path(".src.lua"), fixed, encoding="latin-1")
        return driver.run(job)


def restore_header_newline(source):
    """Pasted copies (e.g. Discord's message.txt) can lose the newline after
    the `-- This file was protected ... [https://lura.ph/]` line, which turns
    the whole script into that comment. Put it back."""
    m = HEADER_LINE.match(source)
    if m and source[m.end():m.end() + 1] not in ("", "\n", "\r"):
        return source[:m.end()] + "\n" + source[m.end():].lstrip(" \t")
    return source
