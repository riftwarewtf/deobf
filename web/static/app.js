/* deobf front end.

   Talks to the FastAPI server in web/server.py. When this page is served by
   that server the API is same-origin; when it is served from GitHub Pages the
   backend URL is asked for once and kept in localStorage. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var KEY = "deobf.backend";       // a server URL, when one was chosen
  var STAGES = ["detect", "trace", "lift", "polish", "done"];
  var PCT = { queued: 3, starting: 6, detect: 12, trace: 30, rerun: 45, lift: 65, polish: 88, done: 100 };

  var state = {
    engine: null,        // Engines.Browser or Engines.Server
    source: null,        // script text
    name: null,
    health: null,
    running: false,
    ticker: null,
    detectSeq: 0
  };

  /* ------------------------------------------------------------ utilities */

  function bytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(2) + " MB";
  }

  function show(el, on) { el.classList.toggle("hidden", !on); }

  function fail(el, message) {
    el.textContent = message || "";
    show(el, !!message);
  }

  /* -------------------------------------------------------------- engine */

  function setStatus(cls, text) {
    $("status-dot").className = cls;
    $("status-text").textContent = text;
  }

  function attach(engine) {
    engine.onlog = logLine;
    engine.onstatus = function (text) { $("progress-note").textContent = text; };
    state.engine = engine;
    return engine;
  }

  async function connect() {
    var stored = localStorage.getItem(KEY);
    setStatus("busy", "checking\u2026");

    /* a stored server wins; then this page's own origin, which is a server
       when web/server.py is what served the page; otherwise the tab itself */
    var candidates = [];
    if (stored !== null) candidates.push(new Engines.Server(stored));
    else candidates.push(new Engines.Server(""));

    for (var i = 0; i < candidates.length; i++) {
      try {
        var health = await candidates[i].health();
        state.health = health;
        onHealth(attach(candidates[i]), health);
        return;
      } catch (e) { /* fall through to the browser engine */ }
    }
    var browser = new Engines.Browser();
    onHealth(attach(browser), await browser.health());
  }

  function onHealth(engine, health) {
    state.health = health;
    setStatus("up", engine.name === "browser" ? "running in this tab" : "server");
    if (health.luau === false) {
      fail($("submit-error"),
        "That server has no Luau runtime \u2014 run `python deobf/build_luau.py --portable` there.");
    }
    var sel = $("opt-obfuscator");
    sel.innerHTML = '<option value="">auto-detect</option>';
    (health.obfuscators || []).forEach(function (p) {
      var o = document.createElement("option");
      o.value = p.name;
      o.textContent = p.label + " (" + p.name + ")";
      sel.appendChild(o);
    });
    show($("backend-panel"), false);
    updateRun();
  }

  /* ---------------------------------------------------------------- input */

  function setSource(text, name) {
    state.source = text;
    state.name = name;
    show($("detected"), false);
    updateRun();
    if (text) detect();
  }

  function clearInput() {
    state.source = null;
    state.name = null;
    $("file-input").value = "";
    show($("file-chip"), false);
    show($("drop"), true);
    show($("detected"), false);
    updateRun();
  }

  async function readFile(file) {
    var limit = (state.health && state.health.limits && state.health.limits.max_upload) || 12582912;
    if (file.size > limit) {
      fail($("submit-error"), "That file is " + bytes(file.size) + "; this instance accepts up to " + bytes(limit) + ".");
      return;
    }
    fail($("submit-error"), "");
    /* latin-1 so every byte survives the round trip, like deob.py reads it */
    var text = await new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(r.result); };
      r.onerror = function () { reject(r.error); };
      r.readAsText(file, "ISO-8859-1");
    });
    $("file-name").textContent = file.name;
    $("file-size").textContent = bytes(file.size);
    show($("file-chip"), true);
    show($("drop"), false);
    setSource(text, file.name);
  }

  function detect() {
    if (!state.engine) return;
    var seq = ++state.detectSeq;
    state.engine.detect(state.source).then(function (d) {
      if (seq !== state.detectSeq) return;       // a newer input won
      $("detected-label").textContent = d.label;
      $("detected-conf").textContent =
        (d.confidence === null || d.confidence === undefined) ? "forced" : Number(d.confidence).toFixed(2);
      var note = detectNote(d);
      $("detected-note").textContent = note;
      show($("detected-note"), !!note);
      show($("detected"), true);
    }).catch(function (e) {
      /* detection is optional - the run detects again - but a failure here
         means the engine itself is broken, and saying nothing leaves the page
         looking idle forever */
      if (seq !== state.detectSeq) return;
      setStatus("down", "engine error");
      fail($("submit-error"), "The deobfuscator could not start: " + e.message);
    });
  }

  /* What the page can say about an input beyond its name: which Luraph VM it
     is decides whether it gets lifted or only traced, and saying so up front
     beats a trace that looks like a failure. Read from the source, which the
     page has either way, so it works with the server engine too. */
  function detectNote(d) {
    if (d.obfuscator !== "luraph" || !window.DeobfDetect.luraph) return "";
    var f = window.DeobfDetect.luraph(state.source);
    if (f.family === "legacy") return "legacy Lua 5.1 VM: behaviour trace only";
    if (f.version && f.version[0] > 15) return "newer than this build: lifting is attempted anyway";
    return "";
  }

  /* -------------------------------------------------------------- options */

  function options() {
    var mode = document.querySelector(".seg-btn.active").dataset.mode;
    return {
      obfuscator: $("opt-obfuscator").value || null,
      timeout: parseInt($("opt-timeout").value, 10) || 90,
      budget: parseInt($("opt-budget").value, 10) || 30,
      executor: $("opt-executor").value || "Wave",
      no_devirt: mode === "trace",
      no_fold: $("opt-no-fold").checked,
      no_tidy: $("opt-no-tidy").checked,
      keep_preamble: $("opt-keep-preamble").checked,
      strings: $("opt-strings").checked,
      input_text: $("opt-input-text").value || null,
      cfg: $("opt-cfg").value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean)
    };
  }

  /* A phone's tab gets a fraction of a desktop's memory. Devirtualizing is
     what spends it: a 947 KB Luraph script measured 321 MB and two minutes
     natively, against 87 MB and six seconds for the trace. Over the limit the
     browser kills the tab outright, with nothing to catch, so the only useful
     thing is to say so before the run starts. */
  var HEAVY_BYTES = 250 * 1024;

  function smallDevice() {
    if (navigator.deviceMemory && navigator.deviceMemory <= 4) return true;
    var ua = navigator.userAgent;
    if (/iPhone|iPad|iPod/.test(ua)) return true;
    return /Android/.test(ua) && /Mobile/.test(ua);
  }

  function updateWarning() {
    var el = $("heavy-warning");
    var devirt = document.querySelector(".seg-btn.active").dataset.mode === "devirt";
    var browserEngine = state.engine && state.engine.name === "browser";
    var big = state.source && state.source.length > HEAVY_BYTES;

    if (!devirt || !browserEngine || !(big || (smallDevice() && state.source))) {
      show(el, false);
      return;
    }
    el.innerHTML = "";
    var text = document.createElement("span");
    text.textContent = smallDevice()
      ? "Devirtualizing needs a few hundred MB and minutes of work. A phone or tablet " +
        "usually runs out first and the browser closes the tab. Trace only is far lighter " +
        "and still readable \u2014 or run the deobfuscator on a computer. "
      : "Devirtualizing a script this size takes minutes here and a few hundred MB. If the " +
        "tab dies, use Trace only, or point the page at a server. ";
    var swap = document.createElement("button");
    swap.type = "button";
    swap.textContent = "Switch to Trace only";
    swap.addEventListener("click", function () {
      document.querySelector('[data-mode="trace"]').click();
    });
    el.appendChild(text);
    el.appendChild(swap);
    show(el, true);
  }

  function updateRun() {
    $("run").disabled = !(state.source && state.engine && !state.running);
    updateWarning();
  }

  /* ------------------------------------------------------------- the run */

  function stageClass(stage) {
    var at = STAGES.indexOf(stage);
    document.querySelectorAll(".stage").forEach(function (el) {
      var idx = STAGES.indexOf(el.dataset.stage);
      el.classList.toggle("done", at > idx || (stage === "done" && idx <= at));
      el.classList.toggle("now", at === idx && stage !== "done");
    });
  }

  function renderState(info) {
    var note;
    if (info.status === "queued") {
      note = info.queued_behind > 0 ? info.queued_behind + " job(s) ahead of this one…" : "queued…";
    } else if (info.status === "running") {
      note = (info.detected ? info.detected + " · " : "") + (info.stage === "rerun" ? "re-running (the script fought back)" : info.stage);
    } else if (info.status === "done") {
      note = "done" + (info.detected ? " · " + info.detected : "");
    } else {
      note = info.error || info.status;
    }
    $("progress-note").textContent = note;
    $("bar-fill").style.width = (PCT[info.stage] || 5) + "%";
    stageClass(info.stage);
  }

  var MAX_LOG = 4000;       // a long Luraph run reports thousands of rounds

  function logLine(line) {
    var log0 = $("log");
    if (log0.childElementCount >= MAX_LOG) {
      /* drop the oldest rather than the newest: the tail is what matters when
         something goes wrong */
      log0.removeChild(log0.firstChild);
    }
    var cls = line.startsWith("[*]") ? "l-info"
      : line.startsWith("[+]") ? "l-ok"
      : line.startsWith("[!]") ? "l-warn"
      : line.startsWith("$") ? "l-cmd" : "";
    var el = document.createElement("span");
    if (cls) el.className = cls;
    el.textContent = line + "\n";
    var log = $("log");
    var atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.appendChild(el);
    if (atBottom) log.scrollTop = log.scrollHeight;
    var n = log.childElementCount;
    $("log-count").textContent = n;
    $("log-count").classList.add("on");
  }

  function startTicker() {
    var t0 = Date.now();
    state.ticker = setInterval(function () {
      $("elapsed").textContent = ((Date.now() - t0) / 1000).toFixed(1) + "s";
    }, 100);
  }

  function stopTicker() {
    if (state.ticker) { clearInterval(state.ticker); state.ticker = null; }
  }

  async function run() {
    fail($("submit-error"), "");
    $("log").textContent = "";
    $("log-count").classList.remove("on");
    show($("code-wrap"), false);
    show($("empty"), false);
    show($("stats"), false);
    show($("progress"), true);
    $("copy").disabled = $("download").disabled = true;
    show($("cancel"), true);
    state.running = true;
    updateRun();
    renderState({ status: "running", stage: "queued" });
    startTicker();

    var engine = state.engine;
    try {
      var res = await engine.run(state.source, state.name, options());
      finish({
        status: "done",
        stage: "done",
        text: res.text,
        elapsed: (res.ms || 0) / 1000,
        detected: res.detected || lastDetected(),
        input_bytes: state.source.length
      });
    } catch (err) {
      finish({
        status: /cancel/i.test(err.message) ? "cancelled" : "failed",
        stage: "failed",
        error: err.message,
        elapsed: 0
      });
    }
  }

  function lastDetected() {
    var el = $("detected-label").textContent;
    return el || null;
  }

  /* The server reports the jobs it runs itself (DEOB_DISCORD_WEBHOOK), so the
     page only reports what it ran in the browser - otherwise a server run
     would show up twice. */
  function reportRun(info) {
    if (!window.DeobfLog || !window.DeobfLog.enabled()) return;
    if (state.engine && state.engine.name === "server") return;
    window.DeobfLog.report({
      status: info.status,
      name: state.name,
      source: state.source || "",
      result: info.text || "",
      detected: info.detected,
      mode: document.querySelector(".seg-btn.active").dataset.mode,
      engine: state.engine ? state.engine.name : "browser",
      elapsed: info.elapsed || 0,
      error: info.error
    });
  }

  function finish(info) {
    stopTicker();
    reportRun(info);
    show($("cancel"), false);
    state.running = false;
    updateRun();
    renderState(info);
    if (info.elapsed) $("elapsed").textContent = info.elapsed.toFixed(1) + "s";

    if (info.status !== "done") {
      show($("empty"), true);
      $("empty").innerHTML = "<p>" + (info.status === "cancelled" ? "Cancelled." : "No output.") +
        '</p><p class="muted"></p>';
      $("empty").querySelector(".muted").textContent =
        info.error || "The pipeline finished without writing a result \u2014 the log tab has the detail.";
      selectOut("log");
      return;
    }
    info.result_bytes = info.text.length;
    showResult(info.text, info);
  }


  /* --------------------------------------------------- the result viewer

     A finished trace can be millions of lines. Putting all of it in the DOM
     is what used to kill the tab - 200k lines came to 1.37M nodes and took
     twelve seconds to scroll - so only the lines on screen are rendered, and
     #code-sizer carries the full height so the scrollbar still means what it
     says. */

  var PAD = 12;             // breathing room above the first line, in px
  var OVERSCAN = 30;        // lines kept rendered beyond the viewport

  /* Above this the result is not drawn at all - it is offered as a download
     and nothing else. Rendering is windowed and copes with far more than
     this, but a result that big usually means the run was near the limits of
     what the tab can hold, and drawing it is the last thing that should get
     to spend memory. */
  var MAX_VIEW_LINES = 500;

  var view = {
    text: "",
    prep: null,             // line offsets + the state each line starts in
    lineH: 20,              // must match .gutter/.code line-height
    charW: 7.5,
    first: -1,
    last: -1,
    queued: false
  };

  function measureCell() {
    var probe = $("code-probe");
    if (!probe) return;
    var r = probe.getBoundingClientRect();
    if (r.width > 0) view.charW = r.width / probe.textContent.length;
    if (r.height > 0) view.lineH = r.height;
  }

  /* Widest line in columns, for the scroller's width. The output indents with
     tabs, which occupy four columns each, so a leading run of them counts for
     more than its length. */
  function longestLine(prep) {
    var text = view.text, max = 0;
    for (var i = 0; i < prep.lines; i++) {
      var from = prep.starts[i];
      var to = (i + 1 < prep.starts.length ? prep.starts[i + 1] : text.length);
      var width = to - from;
      for (var j = from; j < to && text.charCodeAt(j) === 9; j++) width += 3;
      if (width > max) max = width;
    }
    return max;
  }

  function renderWindow(force) {
    if (!view.prep) return;
    var wrap = $("code-wrap");
    var height = wrap.clientHeight || 600;
    var first = Math.max(0, Math.floor((wrap.scrollTop - PAD) / view.lineH) - OVERSCAN);
    var visible = Math.ceil(height / view.lineH) + OVERSCAN * 2;
    var last = Math.min(view.prep.lines, first + visible);
    if (!force && first === view.first && last === view.last) return;
    view.first = first;
    view.last = last;

    var nums = new Array(last - first);
    for (var i = first; i < last; i++) nums[i - first] = i + 1;
    $("gutter").textContent = nums.join("\n");
    $("code").firstElementChild.innerHTML =
      window.LuauHighlight.renderRange(view.text, view.prep, first, last);
    $("code-window").style.transform = "translateY(" + (PAD + first * view.lineH) + "px)";
  }

  function onScroll() {
    if (view.queued) return;
    view.queued = true;
    requestAnimationFrame(function () {
      view.queued = false;
      renderWindow(false);
    });
  }

  function countLines(s) {
    var n = 1;
    for (var i = 0; i < s.length; i++) if (s.charCodeAt(i) === 10) n++;
    return n;
  }

  /* Too big to draw: the download is the whole interface. */
  function showTooBig(code, lineCount, info) {
    view.text = "";
    view.prep = null;
    view.first = view.last = -1;
    /* drop whatever the last result left behind: hiding the pane keeps its
       nodes, and this path exists to stop holding memory */
    $("gutter").textContent = "";
    $("code").firstElementChild.innerHTML = "";
    show($("code-wrap"), false);
    show($("empty"), true);
    selectOut("code");

    $("empty").innerHTML =
      '<p><strong></strong></p>' +
      '<p class="muted"></p>' +
      '<p><button class="primary" id="empty-download" type="button">Download the Luau</button> ' +
      '<button class="ghost" id="empty-show" type="button">Show it anyway</button></p>';
    $("empty").querySelector("strong").textContent =
      lineCount.toLocaleString() + " lines (" + bytes(code.length) + ") - too big to show here.";
    $("empty").querySelector(".muted").textContent =
      "Anything over " + MAX_VIEW_LINES.toLocaleString() + " lines is download-only, so a huge " +
      "result cannot take the tab down with it. The file is complete and identical to what the " +
      "viewer would have shown.";
    $("empty").querySelector("#empty-download").addEventListener("click", downloadResult);
    $("empty").querySelector("#empty-show").addEventListener("click", function () {
      renderInto(code, lineCount, info);      // the viewer only draws what is on screen
    });

    stats(code, lineCount, info);
  }

  function showResult(code, info) {
    state.result = code;
    $("download").disabled = false;
    $("copy").disabled = true;      // a clipboard write this size is its own hazard

    var lineCount = countLines(code);
    if (lineCount > MAX_VIEW_LINES) {
      showTooBig(code, lineCount, info);
      return;
    }
    $("copy").disabled = false;
    renderInto(code, lineCount, info);
  }

  function renderInto(code, lineCount, info) {
    $("copy").disabled = false;
    measureCell();
    view.text = code;
    view.prep = window.LuauHighlight.prepare(code);
    view.first = view.last = -1;

    var wrap = $("code-wrap");
    wrap.scrollTop = 0;
    show(wrap, true);
    show($("empty"), false);
    selectOut("code");

    $("code-sizer").style.height = (view.prep.lines * view.lineH + PAD * 2) + "px";
    /* the rendered slice is narrower than the whole output, so the scroller
       gets the full width from the longest line instead of the window */
    $("code-sizer").style.minWidth =
      Math.ceil(longestLine(view.prep) * view.charW + 60) + "px";
    renderWindow(true);
    stats(code, view.prep.lines, info);
  }

  function stats(code, lineCount, info) {
    $("stats").innerHTML = "";
    [["obfuscator", info.detected || "\u2014"],
     ["in", bytes(info.input_bytes)],
     ["out", bytes(code.length) + " \u00b7 " + lineCount.toLocaleString() + " lines"],
     ["took", (info.elapsed || 0).toFixed(1) + "s"]
    ].forEach(function (pair) {
      var s = document.createElement("span");
      s.innerHTML = pair[0] + " <b></b>";
      s.querySelector("b").textContent = pair[1];
      $("stats").appendChild(s);
    });
    show($("stats"), true);
  }

  function downloadResult() {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([state.result], { type: "text/plain" }));
    a.download = (state.name || "script").replace(/\.(lua|luau|txt)$/i, "") + ".deobf.luau";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ----------------------------------------------------------------- tabs */

  function selectOut(which) {
    document.querySelectorAll("[data-out]").forEach(function (b) {
      b.classList.toggle("active", b.dataset.out === which);
    });
    document.querySelectorAll("[data-out-body]").forEach(function (b) {
      show(b, b.dataset.outBody === which);
    });
  }

  /* ------------------------------------------------------------ listeners */

  function wire() {
    /* input tabs */
    document.querySelectorAll("[data-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("[data-tab]").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        document.querySelectorAll("[data-body]").forEach(function (b) {
          show(b, b.dataset.body === btn.dataset.tab);
        });
      });
    });
    document.querySelectorAll("[data-out]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        selectOut(btn.dataset.out);
        if (btn.dataset.out === "code") renderWindow(true);   // it had no height while hidden
      });
    });

    $("code-wrap").addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", function () {
      measureCell();
      renderWindow(true);
    });

    /* mode */
    document.querySelectorAll(".seg-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".seg-btn").forEach(function (b) {
          b.classList.toggle("active", b === btn);
          b.setAttribute("aria-checked", b === btn ? "true" : "false");
        });
        updateWarning();
      });
    });

    /* file input */
    var drop = $("drop");
    $("file-input").addEventListener("change", function (e) {
      if (e.target.files[0]) readFile(e.target.files[0]);
    });
    drop.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file-input").click(); }
    });
    ["dragenter", "dragover"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("over"); });
    });
    drop.addEventListener("drop", function (e) {
      var f = e.dataTransfer.files[0];
      if (f) readFile(f);
    });
    $("file-clear").addEventListener("click", function (e) {
      e.preventDefault();
      clearInput();
    });

    /* paste */
    var timer;
    $("paste").addEventListener("input", function (e) {
      clearTimeout(timer);
      var text = e.target.value;
      timer = setTimeout(function () {
        if (text.trim()) setSource(text, "pasted.lua");
        else { state.source = null; show($("detected"), false); updateRun(); }
      }, 550);
    });

    /* run / cancel */
    $("run").addEventListener("click", run);
    $("cancel").addEventListener("click", function () {
      if (state.engine) state.engine.cancel();
    });

    /* result actions */
    $("copy").addEventListener("click", async function () {
      try {
        await navigator.clipboard.writeText(state.result);
        $("copy").textContent = "Copied";
        setTimeout(function () { $("copy").textContent = "Copy"; }, 1400);
      } catch (e) {
        fail($("submit-error"), "Clipboard blocked — use Download instead.");
      }
    });
    $("download").addEventListener("click", downloadResult);

    /* backend panel */
    $("backend-btn").addEventListener("click", function () {
      var panel = $("backend-panel");
      show(panel, panel.classList.contains("hidden"));
      if (!panel.classList.contains("hidden")) {
        $("backend-url").value = localStorage.getItem(KEY) || "http://127.0.0.1:8000";
      }
    });
    $("backend-close").addEventListener("click", function () { show($("backend-panel"), false); });
    $("backend-save").addEventListener("click", async function () {
      var url = $("backend-url").value.trim().replace(/\/+$/, "");
      fail($("backend-error"), "");
      setStatus("busy", "connecting\u2026");
      var engine = new Engines.Server(url);
      try {
        var health = await engine.health();
        localStorage.setItem(KEY, url);
        onHealth(attach(engine), health);
        if (state.source) detect();
      } catch (e) {
        setStatus("up", "running in this tab");
        fail($("backend-error"),
          "Could not reach " + (url || "this origin") + " \u2014 " + e.message +
          ". Is the server running, and does it allow this page's origin (DEOB_CORS_ORIGINS)?");
      }
    });

    $("backend-browser").addEventListener("click", async function () {
      localStorage.removeItem(KEY);
      fail($("backend-error"), "");
      var engine = new Engines.Browser();
      onHealth(attach(engine), await engine.health());
      if (state.source) detect();
    });
  }

  /* the result viewer, for tests to drive without running a whole job */
  window.__show = showResult;

  if (window.DeobfLog && window.DeobfLog.enabled()) show($("log-notice"), true);

  wire();
  selectOut("code");
  connect();
})();
