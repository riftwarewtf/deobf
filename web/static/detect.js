/* The plugin detectors, in JavaScript.

   Same checks as detect() in deobf/obfuscators/* - cheap ones, over the head of
   the file. They live here so naming the obfuscator costs nothing: otherwise
   merely pasting a script has to start Pyodide and the Luau runtime, about
   16 MB, which on a phone is most of what the tab is allowed.

   The Luraph part mirrors deobf/obfuscators/luraph_v15/versions.py, including
   the two VM generations: the modern register VM (v14, v15, newer) that the
   devirtualizer lifts, and the legacy Lua 5.1 interpreter (up to v13) whose
   bytecode sits in an "LPH|<hex>" literal, which only gets a trace. Keep the
   two files in step.

   This only labels the input. The run detects again in Python, and that is the
   one that decides which plugin executes. */
(function (global) {
  "use strict";

  /* `-- This file was protected using Luraph Obfuscator v14.4.2 [https://lura.ph/]`,
     anchored to a comment line so a script that merely mentions the string is
     not mistaken for the real thing. */
  var LURAPH_HEADER = /^[ \t]*--[^\n]*?This file was protected using Luraph Obfuscator v(\d+)(?:\.(\d+))?(?:\.(\d+))?/m;
  var LURAPH_HEADER_SCAN = 2000;
  var LURAPH_VM_OBJECT = "return setmetatable({";
  var LURAPH_SLOT = /\[\d+\]=(bit32|buffer|string|table|math)\.\w+/;
  var LURAPH_MACRO_SCAN = 200000;
  var LURAPH_LEGACY = /["']LPH\|[0-9A-Fa-fG]{64,}/;
  var LURAPH_DEVIRT_FROM = 14;          // oldest generation devirt.py fits

  var IRONBREW_HEADER = /--\s*this file was generated using ironbrew1\b/i;
  var IRONBREW_SHAPE = /^return\s*\(\s*function\s*\((?:[a-z]{1,2},){20,}\.\.\.\)\s*local [a-z]{1,3}(?:=\{-?\d+,|(?:,[a-z]{1,3}){10,})/;

  var MIN_CONFIDENCE = 0.5;     // obfuscators/__init__.py

  /* The start of the actual code, with leading blank and `--` comment lines
     dropped: Luraph's version comment sits in front of the VM. */
  function codeHead(source) {
    var lines = source.slice(0, 4000).split("\n");
    var i = 0;
    while (i < lines.length && (!lines[i].trim() || lines[i].replace(/^\s+/, "").indexOf("--") === 0)) i++;
    return lines.slice(i).join("\n").replace(/^\s+/, "");
  }

  function luraphVersion(source) {
    var m = LURAPH_HEADER.exec(source.slice(0, LURAPH_HEADER_SCAN));
    if (!m) return null;
    var parts = [];
    for (var i = 1; i < m.length; i++) if (m[i] !== undefined) parts.push(parseInt(m[i], 10));
    return parts;
  }

  function luraphModern(source) {
    var head = codeHead(source).slice(0, 2000);
    if (head.indexOf(LURAPH_VM_OBJECT) !== 0) return false;
    return LURAPH_SLOT.test(head) || source.slice(0, LURAPH_MACRO_SCAN).indexOf("LPH") !== -1;
  }

  function luraphLegacy(source) {
    /* the substring first: the regex would otherwise scan whole megabytes of
       every input that is not Luraph at all */
    if (source.indexOf("LPH|") === -1) return false;
    return LURAPH_LEGACY.test(source);
  }

  /* { version: [14,4,2] | null, text: "14.4.2" | null, family, confidence } */
  function luraphFlavour(source) {
    var version = luraphVersion(source);
    if (version) {
      /* the shape is direct evidence of which VM this is; the version is only
         the convention, and decides when the shape is unrecognizable */
      var family;
      if (luraphModern(source)) family = "modern";
      else if (luraphLegacy(source)) family = "legacy";
      else family = version[0] >= LURAPH_DEVIRT_FROM ? "modern" : "legacy";
      return { version: version, text: version.join("."), family: family, confidence: 1.0 };
    }
    if (luraphLegacy(source)) {
      return { version: null, text: null, family: "legacy", confidence: 0.9 };
    }
    if (luraphModern(source)) {
      return { version: null, text: null, family: "modern", confidence: 0.8 };
    }
    return { version: null, text: null, family: "unknown", confidence: 0.0 };
  }

  function luraphLabel(source) {
    var f = luraphFlavour(source);
    var name = f.text ? "Luraph v" + f.text : (f.family === "modern" ? "Luraph v15" : "Luraph");
    return f.family === "legacy" ? name + " (legacy VM)" : name;
  }

  function luraph(source) {
    return luraphFlavour(source).confidence;
  }

  function ironbrew(source) {
    if (IRONBREW_HEADER.test(source.slice(0, 300))) return 1.0;
    if (IRONBREW_SHAPE.test(source.replace(/^\s+/, "").slice(0, 600))) return 0.8;
    return 0.0;
  }

  var PLUGINS = [
    { name: "luraph", label: "Luraph", detect: luraph, describe: luraphLabel },
    { name: "ironbrew1", label: "ironbrew1", detect: ironbrew },
    { name: "generic", label: "unknown obfuscator (behaviour trace only)",
      detect: function () { return 0.01; } }
  ];

  function describe(plugin, source) {
    return plugin.describe ? plugin.describe(source) : plugin.label;
  }

  function detect(source) {
    var best = null;
    PLUGINS.forEach(function (p) {
      var c = p.detect(source);
      if (best === null || c > best.confidence) best = { plugin: p, confidence: c };
    });
    var generic = PLUGINS[PLUGINS.length - 1];
    if (best.confidence < MIN_CONFIDENCE) {
      return { obfuscator: generic.name, label: generic.label,
               confidence: best.plugin === generic ? best.confidence : 0.0 };
    }
    return { obfuscator: best.plugin.name, label: describe(best.plugin, source),
             confidence: best.confidence };
  }

  detect.plugins = PLUGINS.map(function (p) { return { name: p.name, label: p.label }; });
  /* the pipeline's own view of one input, for the page to explain itself */
  detect.luraph = luraphFlavour;
  global.DeobfDetect = detect;
})(window);
