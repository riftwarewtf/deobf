"""Which Luraph generation an input is, and what this plugin can do with it.

Luraph has had two very different designs, and telling them apart decides
whether devirtualizing is worth a run at all:

- **The modern VM (v14, v15, and whatever comes next).** A custom register
  machine whose entry point is a VM *object*: `return setmetatable({[30]=(0),
  [85]=error, R=function(...) ... end}, ...)`, with library functions parked in
  numeric slots (`[104]=string.char`). `devirt.py` lifts this one.

- **The legacy VM (up to v13).** A Lua 5.1 interpreter with its bytecode in one
  string literal, `"LPH|"` followed by hex digits, where the letter `G` is a
  run-length marker: a pair `<n>G` means "repeat the next byte n times"
  (PhoenixZeng/LuraphDeobfuscator, `luraphDecodeString`). Its VM preamble is
  ten local functions in a fixed order - vm_run, get_byte, get_dword,
  get_bits, get_float64, get_instruction, get_string, decode_chunk,
  create_wrapper, vm_run_func - and the instruction fields come out of
  `get_bits` at widths 6/8/9/18, which is Lua 5.1's layout. Nothing in
  `devirt.py` fits that, so an input like this goes straight to the trace
  instead of spending a run finding out.

The version comment is what Luraph itself writes at the top, and it is a
certain fingerprint - every generation gets one. It is not a promise that the
devirtualizer understands that generation, which is why the family and the
version are kept apart here.
"""
import re

# `-- This file was protected using Luraph Obfuscator v14.4.2 [https://lura.ph/]`
# Anchored to a comment line so that a script merely mentioning the string
# (another deobfuscator's source, a bundle) is not mistaken for the real thing.
HEADER = re.compile(r"^[ \t]*--[^\n]*?This file was protected using Luraph Obfuscator "
                    r"v(\d+)(?:\.(\d+))?(?:\.(\d+))?", re.M)
HEADER_SCAN = 2000              # bytes of the head the comment has to be in

# The modern VM object: `return setmetatable({ ... })` with library functions
# in numeric slots.
VM_OBJECT_HEAD = "return setmetatable({"
LIB_SLOT = re.compile(r"\[\d+\]=(bit32|buffer|string|table|math)\.\w+")
MACRO_SCAN = 200_000            # how far to look for Luraph's LPH_ macros

# The legacy bytecode blob. 64 characters is far shorter than any real
# payload and still far too long to turn up by accident.
LEGACY_MARK = "LPH|"
LEGACY_PAYLOAD = re.compile(r"""["']LPH\|[0-9A-Fa-fG]{64,}""")

# The oldest generation devirt.py is built for. Below this the VM is the
# legacy Lua 5.1 interpreter, which it cannot lift.
DEVIRT_FROM = 14


class Flavour:
    """What an input looks like: its version, its VM family, what to try.

    version   (major, minor, patch) from the header comment, missing parts
              left out; None when the header is gone
    text      the version as written, e.g. "14.4.2", or None
    family    "modern" (v14+, the register VM devirt.py lifts), "legacy"
              (up to v13, the Lua 5.1 interpreter), or "unknown"
    confidence how sure we are this is Luraph at all
    """

    def __init__(self, version=None, family="unknown", confidence=0.0):
        self.version = version
        self.text = ".".join(str(n) for n in version) if version else None
        self.family = family
        self.confidence = confidence

    @property
    def can_devirt(self):
        """Is lifting worth a run? Only the modern VM has a front end."""
        return self.family != "legacy"

    @property
    def label(self):
        """What to call it in the output and on the page."""
        if self.text:
            name = "Luraph v" + self.text
        elif self.family == "modern":
            name = "Luraph v15"          # the shape devirt.py was built on
        else:
            name = "Luraph"
        return name + " (legacy VM)" if self.family == "legacy" else name

    def __repr__(self):
        return "Flavour(%r, %r, %.2f)" % (self.text, self.family, self.confidence)


def header_version(source):
    """(major, minor, patch) from Luraph's own comment, or None."""
    m = HEADER.search(source[:HEADER_SCAN])
    if not m:
        return None
    return tuple(int(g) for g in m.groups() if g is not None)


def looks_legacy(source):
    """Does the bytecode sit in a `"LPH|<hex>"` literal (v13 and older)?"""
    # a plain substring search first: the regex would otherwise scan whole
    # megabytes of every input that is not Luraph at all
    if LEGACY_MARK not in source:
        return False
    return LEGACY_PAYLOAD.search(source) is not None


def code_head(source, limit=4000):
    """The start of the actual code: leading blank and `--` comment lines gone.

    Luraph's own version comment sits in front of the VM, so a check on what
    the file starts with has to look past it.
    """
    out = []
    for line in source[:limit].split("\n"):
        if not out and (not line.strip() or line.lstrip().startswith("--")):
            continue
        out.append(line)
    return "\n".join(out).lstrip()


def looks_modern(source):
    """Does the file start with the v14/v15 VM object?"""
    head = code_head(source)[:2000]
    if not head.startswith(VM_OBJECT_HEAD):
        return False
    return bool(LIB_SLOT.search(head)) or "LPH" in source[:MACRO_SCAN]


def classify(source):
    """What kind of Luraph `source` is, if any (see Flavour)."""
    version = header_version(source)
    if version:
        # The comment is Luraph's own and unambiguous, whatever the version, so
        # this is Luraph for certain. Which VM it is decides what can be done
        # with it, and the shape is direct evidence where the version is only a
        # convention: take the shape when it is recognizable, the version when
        # the file has been rewrapped past recognition.
        if looks_modern(source):
            family = "modern"
        elif looks_legacy(source):
            family = "legacy"
        else:
            family = "modern" if version[0] >= DEVIRT_FROM else "legacy"
        return Flavour(version, family, 1.0)
    if looks_legacy(source):
        return Flavour(None, "legacy", 0.9)
    if looks_modern(source):
        return Flavour(None, "modern", 0.8)
    return Flavour()
