// The clickable Onion Board on the home page: the app's own layout, icons, themes and
// Settings texts (board-demo-data.js), styled by board-demo.css. Pads, tabs, search,
// hotkeys, sorting, pad size, the player and the themes all work. Whatever needs Windows
// (your mic, links, radio, the voice changer...) says so and points to the download.
(function () {
  "use strict";
  var D = window.ONION_BOARD_DATA, site = window.onionSite || {};
  if (!D) return;
  var DL = "https://github.com/Onion-Alien/onion-board/releases/latest/download/OnionBoardSetup.exe";

  // ------------------------------------------------------------------ helpers
  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    });
    (kids || []).forEach(function (c) { if (c) el.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return el;
  }
  function icon(name, cls) {
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "i" + (cls ? " " + cls : ""));
    s.setAttribute("aria-hidden", "true");
    s.innerHTML = D.icons[name] || "";
    return s;
  }
  function btn(cls, label, iconName, onclick, attrs) {
    var b = h("button", Object.assign({ type: "button", class: "btn " + (cls || ""), onclick: onclick }, attrs || {}));
    if (iconName) b.appendChild(icon(iconName, "s"));
    if (label) b.appendChild(h("span", { class: "t", text: label }));
    return b;
  }
  function dd(b) { b.appendChild(icon("next", "dd")); b.lastChild.style.transform = "rotate(90deg)"; return b; }
  function fmt(s) { return s.toFixed(1) + "s"; }
  function did(what) { if (site.did) site.did("demo-" + what); }
  function setRange(r) { r.style.setProperty("--p", ((r.value - r.min) / (r.max - r.min) * 100) + "%"); }

  // ------------------------------------------------------------------ the sounds
  // Real CC0 recordings from sounds/ (the try-it pads' own), or the page's made-up
  // stand-ins for the few that have no recording.
  var PADS = [
    { sfx: "horn", name: "Air Horn", art: "📯", c: "#d9771e", key: "1", tabs: ["Memes"] },
    { sfx: "boom", name: "Vine Boom", art: "💥", c: "#6a3d34", key: "2", tabs: ["Memes", "Reactions"] },
    { sfx: "trombone", name: "Sad Trombone", art: "🎺", c: "#2b5cc4", key: "3", tabs: ["Memes", "Music"] },
    { sfx: "buzzer", name: "Wrong Buzzer", art: "❌", c: "#8a2c4c", key: "4", tabs: ["Reactions"] },
    { sfx: "rimshot", name: "Ba Dum Tss", art: "🥁", c: "#1f6b5f", key: "5", tabs: ["Memes", "Reactions"] },
    { sfx: "clap", name: "Applause", art: "👏", c: "#b98a1c", key: "6", tabs: ["Reactions"] },
    { sfx: "laser", name: "Laser", art: "⚡", c: "#6b3fd1", key: "7", tabs: [] },
    { sfx: "coin", name: "Coin", art: "🪙", c: "#a37b12", key: "8", tabs: ["Reactions"] },
    { sfx: "drop", name: "Bass Drop", art: "🔊", c: "#23395b", key: "9", tabs: ["Music"] },
    { sfx: "ring", name: "Ding", art: "🔔", c: "#2d6a4f", key: "", tabs: ["Reactions"] },
    { sfx: "hoot", name: "Owl", art: "🦉", c: "#4a5a2a", key: "", tabs: [] },
    { sfx: "squeak", name: "Squeak", art: "🐭", c: "#7a3b6b", key: "", tabs: ["Memes"] }
  ];
  var LENS = { horn: 1.2, boom: 2.1, trombone: 2.6, buzzer: 0.9, rimshot: 1.6, clap: 2.6, laser: 0.6, coin: 0.6, drop: 2.4, ring: 0.8, hoot: 1.4, squeak: 0.1 };
  var COLOURS = ["#d9771e", "#c2334d", "#8a2c4c", "#6b3fd1", "#2b5cc4", "#1f6b5f", "#2d6a4f", "#b98a1c", "#6a3d34", "#3a3f4b"];
  var EMOJI = ["🎵", "📯", "💥", "🎺", "🥁", "👏", "⚡", "🪙", "🔊", "🔔", "🦉", "😂", "💀", "🐐", "🔥", "🤡", "👻", "🚨"];

  PADS.forEach(function (p, i) { p.id = i + 1; p.len = LENS[p.sfx]; p.plays = 0; });
  var nextId = PADS.length + 1;

  var S = {                       // everything the demo remembers (only for this visit)
    page: "sounds", tab: "All", tabs: ["All", "Memes", "Reactions", "Music"], q: "",
    sort: "mine", view: "pads", pad: 150, speed: 1, vol: 1, phones: 0.7, hear: true,
    live: true, mic: 1, theme: "Dark", rail: false, src: "youtube", removed: [], last: null,
    setPage: "audio", advanced: false, toldSettings: false
  };

  // ------------------------------------------------------------------ playing
  var playing = [];               // { pad, src, t0, dur, buf, off }
  function gainNow() { return S.vol * S.phones * (S.hear ? 1 : 0) / 0.7; }
  function start(p, offset) {
    var a = site.audio && site.audio();
    if (!a) return;
    did("pad");
    var buf = p.buf || (site.clip && site.clip(p.sfx)), item = { pad: p, t0: performance.now() };
    if (buf) {
      var src = a.ac.createBufferSource(), g = a.ac.createGain();
      src.buffer = buf; src.playbackRate.value = S.speed;
      g.gain.value = gainNow() * 0.7;
      src.connect(g); g.connect(a.out);
      offset = offset || 0;
      src.start(a.ac.currentTime + 0.01, offset);
      item.src = src; item.g = g; item.buf = buf; item.off = offset;
      item.dur = (buf.duration - offset) / S.speed;
      p.len = buf.duration;
      src.onended = function () { end(item); };
      if (site.talk) site.talk(item.dur);
    } else {
      item.dur = (site.play ? site.play(p.sfx) : 0) || p.len || 1;
      item.timer = setTimeout(function () { end(item); }, item.dur * 1000);
    }
    p.plays++;
    S.last = p;
    playing.push(item);
    tick();
  }
  function end(item) {
    var i = playing.indexOf(item);
    if (i >= 0) playing.splice(i, 1);
    clearTimeout(item.timer);
    var el = padEl(item.pad);
    if (el && !playing.some(function (x) { return x.pad === item.pad; })) {
      el.classList.remove("on");
      el.querySelector(".prog").style.transform = "scaleX(0)";
    }
    showNow();
  }
  function stopAll() {
    playing.slice().forEach(function (it) {
      if (it.src) { it.src.onended = null; try { it.src.stop(); } catch (e) { /* already done */ } }
      end(it);
    });
    if (site.stop) site.stop();
  }
  var ticking = false;
  function tick() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function loop() {
      var now = performance.now();
      playing.forEach(function (it) {
        var el = padEl(it.pad);
        if (!el) return;
        el.classList.add("on");
        el.querySelector(".prog").style.transform = "scaleX(" + Math.min(1, (now - it.t0) / (it.dur * 1000)).toFixed(3) + ")";
      });
      showNow();
      var lvl = S.live && site.level ? site.level() : 0;
      if (R.meter) R.meter.style.transform = "scaleX(" + Math.min(1, lvl * 1.2).toFixed(3) + ")";
      if (playing.length || lvl > 0.01) requestAnimationFrame(loop);
      else { ticking = false; if (R.meter) R.meter.style.transform = "scaleX(0)"; }
    });
  }
  function showNow() {
    if (!R.now) return;
    var it = playing[playing.length - 1];
    R.nowName.textContent = it ? it.pad.name : (S.last ? S.last.name : "Pick a sound");
    R.playBtn.replaceChildren(icon(it ? "pause" : "play"));
    R.playBtn.setAttribute("aria-label", it ? "Pause" : "Play");
    var f = it ? Math.min(1, (performance.now() - it.t0) / (it.dur * 1000)) : 0;
    if (it && it.buf) f = (it.off + (performance.now() - it.t0) / 1000 * S.speed) / it.buf.duration;
    if (!R.seek._drag) { R.seek.value = Math.round(Math.min(1, f) * 1000); setRange(R.seek); }
  }

  // ------------------------------------------------------------------ the root
  var R = {}, root;
  function theme(name) {
    var t = D.themes[name] || D.themes.Dark;
    S.theme = D.themes[name] ? name : "Dark";
    Object.keys(t).forEach(function (k) { root.style.setProperty("--" + k, t[k]); });
  }

  // One way of saying "the real app does this": the same toast everywhere.
  var toastT = 0;
  function toast(title, text, withDl) {
    var t = R.toast;
    t.replaceChildren(h("div", { class: "tx" }, [h("b", { text: title }), h("span", { text: text })]));
    if (withDl) t.appendChild(h("a", { class: "btn small acc", href: DL, "data-goatcounter-click": "download-demo" }, [icon("download", "s"), "Download free"]));
    t.classList.toggle("withdl", !!withDl);
    t.classList.add("on");
    clearTimeout(toastT);
    toastT = setTimeout(function () { t.classList.remove("on"); }, withDl ? 6000 : 3800);
  }
  // Something the browser can't do (your mic, other apps, the internet's sounds...):
  // the same short note every time, with the download right there.
  function tryIt(what) {
    did("app-only");
    toast("Download it to try this", what + " works in the free app.", true);
  }

  // ------------------------------------------------------------------ menus and dialogs
  function closeMenu() { if (R.menu) { R.menu.remove(); R.menu = null; } }
  function menu(x, y, items) {
    closeMenu();
    var m = h("div", { class: "ob-menu", role: "menu" });
    items.forEach(function (it) {
      if (it === "-") return m.appendChild(h("hr"));
      if (it.el) return m.appendChild(it.el);
      if (it.note) return m.appendChild(h("div", { class: "note", text: it.note }));
      var b = h("button", { type: "button", role: "menuitem", disabled: it.off, onclick: function () { closeMenu(); it.fn(); } });
      b.appendChild(it.tick !== undefined ? (it.tick ? icon("check", "tick") : h("span", { class: "tick" })) : icon(it.icon || "more", "tick"));
      b.appendChild(h("span", { text: it.t }));
      m.appendChild(b);
    });
    root.appendChild(m);
    var box = root.getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight;
    m.style.left = Math.max(4, Math.min(x - box.left, box.width - mw - 4)) + "px";
    m.style.top = Math.max(4, Math.min(y - box.top, box.height - mh - 4)) + "px";
    R.menu = m;
    var first = m.querySelector("button:not(:disabled)");
    if (first) first.focus({ preventScroll: true });
  }
  function menuAt(el, items) { var r = el.getBoundingClientRect(); menu(r.left, r.bottom + 4, items); }
  function dialog(title, body, actions) {
    var veil = h("div", { class: "ob-veil", onclick: function (e) { if (e.target === veil) close(); } });
    var foot = h("div", { class: "foot" });
    var dlg = h("div", { class: "ob-dlg", role: "dialog", "aria-label": title }, [h("h3", { text: title }), h("div", { class: "body" }, body), foot]);
    function close() { veil.remove(); document.removeEventListener("keydown", esc, true); }
    function esc(e) { if (e.key === "Escape") { e.stopPropagation(); close(); } }
    actions.forEach(function (a) { foot.appendChild(btn(a.acc ? "acc" : "", a.t, null, function () { if (a.fn() !== false) close(); })); });
    document.addEventListener("keydown", esc, true);
    veil.appendChild(dlg);
    root.appendChild(veil);
    return { close: close, el: dlg };
  }

  // ------------------------------------------------------------------ Live controls
  // The app's Live controls pop-up (ui/speedpitch.py) from the 1x button on the player and
  // Effects on Radio and Apps: a click outside, Escape or its button closes it. The speed
  // works here; the rest shows what's there and points to the download.
  var FX_PARAMS = [["bass", "Bass", -12, 18, 1, " dB"], ["treble", "Treble", -12, 12, 1, " dB"], ["muffle", "Muffle", 0, 1, 0.01, "%"],
    ["reverb", "Reverb", 0, 1, 0.01, "%"], ["echo", "Echo", 0, 1, 0.01, "%"], ["crunch", "Distortion", 0, 1, 0.01, "%"]];
  var FX_PRESETS = [["Bass boosted", { bass: 12 }], ["Blown out", { bass: 15, crunch: 0.7 }], ["Concert hall", { reverb: 0.55 }],
    ["Canyon", { echo: 0.6, reverb: 0.2 }], ["Underwater", { muffle: 0.8, reverb: 0.3, bass: 4 }],
    ["Phone call", { bass: -12, treble: -4, muffle: 0.45, crunch: 0.15 }]];
  var SETUPS = [{ name: "Deep demon", voice: "Demon" }, { name: "Tiny robot", voice: "Robot" }];   // the Voice tab's My setups
  function liveState() { return { pitch: 0, keep: true, red: false, fx: {}, preset: "", setup: "" }; }
  var LIVE = { sounds: liveState(), radio: liveState(), apps: liveState() };
  function xs(v) { return (+v.toFixed(2)) + "x"; }
  function shortName(n) { return n.length <= 14 ? n : n.slice(0, 13).trim() + "…"; }
  function liveLabel(what) {
    var L = LIVE[what], parts = [];
    if (what === "sounds") parts.push(xs(S.speed) + (L.pitch ? " " + (L.pitch > 0 ? "+" : "") + L.pitch : ""));
    else if (L.pitch) parts.push((L.pitch > 0 ? "+" : "") + L.pitch + " st");
    if (L.preset || Object.keys(L.fx).length) parts.push("FX");
    if (L.setup) parts.push(shortName(L.setup));
    return parts.join(" · ") || "Effects";
  }
  function paintLive(what) {
    var b = R.lc && R.lc[what], L = LIVE[what];
    if (!b) return;
    b.replaceChildren();
    if (what !== "sounds") b.appendChild(icon("wave", "s"));
    b.appendChild(h("span", { class: "t", text: liveLabel(what) }));
    var hot = S.speed >= 8 && what === "sounds" || Math.abs(L.pitch) > 12;
    b.classList.toggle("set", hot || (what === "sounds" && S.speed !== 1) || !!L.pitch || !!L.setup || !!L.preset || Object.keys(L.fx).length > 0);
    b.classList.toggle("hot", hot);
  }
  function liveBtn(what) {
    var b = h("button", { type: "button", class: "btn small ob-lc", "aria-haspopup": "dialog", "aria-expanded": "false",
      title: { radio: "Pitch and effects of the radio", apps: "Pitch and effects of the programs you send" }[what] || "Speed, pitch and effects of the sounds playing now" });
    b.addEventListener("click", function () { openLive(what, b); });
    R.lc[what] = b;
    paintLive(what);
    return b;
  }
  function setSpeed(v) {
    S.speed = Math.round(v * 100) / 100;
    playing.forEach(function (it) { if (it.src) it.src.playbackRate.value = S.speed; });
    paintLive("sounds");
  }
  // The Redline rev meter: 0-10x for the speed (red from 8x), or a stream's pitch (red past ±24 st)
  function gauge(v, pitch) {
    var lo = pitch ? -36 : 0, hi = pitch ? 36 : 10, cx = 100, cy = 84, r = 66, s = "";
    function ang(x) { return (135 + (Math.max(lo, Math.min(hi, x)) - lo) / (hi - lo) * 270) * Math.PI / 180; }
    function pt(x, rad) { var a = ang(x); return (cx + rad * Math.cos(a)).toFixed(1) + " " + (cy + rad * Math.sin(a)).toFixed(1); }
    function arc(a, b, col) {
      return '<path d="M' + pt(a, r) + " A" + r + " " + r + " 0 " + ((b - a) / (hi - lo) * 270 > 180 ? 1 : 0) + " 1 " + pt(b, r) +
        '" style="fill:none;stroke:' + col + ';stroke-width:8"/>';
    }
    var zones = pitch ? [[-36, -24, "#ff4d4f"], [-24, 24, "var(--accent)"], [24, 36, "#ff4d4f"]]
                      : [[0, 6, "var(--accent)"], [6, 8, "#f5a623"], [8, 10, "#ff4d4f"]];
    zones.forEach(function (z) { s += arc(z[0], z[1], z[2]); });
    for (var t = lo; t <= hi; t += pitch ? 12 : 1) {
      var red = pitch ? Math.abs(t) > 24 : t >= 8, a = ang(t);
      s += '<line x1="' + (cx + (r - 13) * Math.cos(a)).toFixed(1) + '" y1="' + (cy + (r - 13) * Math.sin(a)).toFixed(1) + '" x2="' + (cx + (r - 8) * Math.cos(a)).toFixed(1) +
        '" y2="' + (cy + (r - 8) * Math.sin(a)).toFixed(1) + '" style="stroke:var(--muted);stroke-width:1.5"/>';
      s += '<text x="' + (cx + (r - 22) * Math.cos(a)).toFixed(1) + '" y="' + (cy + (r - 22) * Math.sin(a) + 3).toFixed(1) +
        '" text-anchor="middle" style="font-size:9px;fill:' + (red ? "#ff4d4f" : "var(--muted)") + '">' + (pitch && t > 0 ? "+" : "") + t + "</text>";
    }
    s += '<line x1="' + cx + '" y1="' + cy + '" x2="' + pt(v, r - 16).replace(" ", '" y2="') + '" style="stroke:var(--text_hi);stroke-width:2.5;stroke-linecap:round"/>';
    s += '<circle cx="' + cx + '" cy="' + cy + '" r="4" style="fill:var(--text_hi)"/>';
    s += '<text x="' + cx + '" y="' + (cy + 24) + '" text-anchor="middle" style="font-size:15px;font-weight:700;fill:var(--text_hi)">' +
      (pitch ? (v > 0 ? "+" : "") + v + " st" : xs(v)) + "</text>";
    return '<svg viewBox="0 0 200 140" aria-hidden="true">' + s + "</svg>";
  }
  function closeLive() {
    if (!R.pop) return;
    R.pop.anchor.setAttribute("aria-expanded", "false");
    R.pop.el.remove();
    R.pop = null;
  }
  function openLive(what, anchor) {
    if (R.pop && R.pop.anchor === anchor) return closeLive();
    closeLive(); closeMenu();
    var L = LIVE[what], hasSpeed = what === "sounds";
    var el = h("div", { class: "ob-lpop", role: "dialog", "aria-label": "Live controls" });
    var meter = h("div", { class: "ob-gauge" });
    function showMeter() { meter.innerHTML = gauge(hasSpeed ? S.speed : L.pitch, !hasSpeed); }
    function app(what2) { tryIt(what2); }
    function row(name, lo, hi, step, val, unit, oninput, onset) {
      var r = h("input", { type: "range", min: String(lo), max: String(hi), step: String(step), value: String(val), "aria-label": name });
      var v = h("span", { class: "v" });
      function show() {
        var x = +r.value;
        v.textContent = unit === "x" ? xs(x) : unit === "%" ? Math.round(x * 100) + "%" : (x > 0 ? "+" : x < 0 ? "−" : "+") + Math.abs(x) + unit;
        setRange(r);
      }
      r.addEventListener("input", function () { oninput(+r.value); show(); });
      r.addEventListener("change", function () { if (onset) onset(+r.value); });
      show();
      return h("div", { class: "ob-lrow" }, [h("span", { class: "n", text: name }), r, v]);
    }
    function quick(vals, fmt, fn) {
      return h("div", { class: "ob-lquick" }, vals.map(function (x) { return btn("small", fmt(x), null, function () { fn(x); }); }));
    }
    function draw() {
      el.replaceChildren();
      var reset = btn("flat small", "Reset", "reload", function () {
        if (hasSpeed) setSpeed(1);
        L.pitch = 0; L.fx = {}; L.preset = ""; L.setup = "";
        draw(); paintLive(what);
      }, { title: hasSpeed ? "Back to 1x, no pitch change and no effects" : "Back to no pitch change and no effects" });
      el.appendChild(h("div", { class: "lhead" }, [h("b", { text: "Live controls" }),
        h("span", { class: "lsub", text: { radio: "The radio", apps: "All programs" }[what] || "All sounds" }), reset]));
      el.appendChild(h("hr"));
      // My setups: the Voice tab's saved voices, on everything here
      var chips = h("div", { class: "lchips" });
      [{ name: "" }].concat(SETUPS).forEach(function (s) {
        chips.appendChild(h("button", { type: "button", class: "chip", "aria-pressed": L.setup === s.name ? "true" : "false", text: s.name || "No voice",
          title: s.voice ? "Voice changer: " + s.voice : null, onclick: function () {
            L.setup = s.name; draw(); paintLive(what);
            if (s.name) app((hasSpeed ? "Your sounds" : what === "radio" ? "The radio" : "Your programs") + " in your “" + s.name + "” voice");
          } }));
      });
      chips.appendChild(h("button", { type: "button", class: "chip ghost", onclick: function () { closeLive(); voiceTab = "changer"; go("voice"); } },
        [icon("plus", "s"), "Make one on the Voice tab"]));
      el.appendChild(h("div", { class: "lsetups" }, [h("b", { text: "My setups" }), chips]));
      el.appendChild(h("hr"));
      // left: speed & pitch, then Redline; right: the effects
      var left = h("div", { class: "lcol" }), right = h("div", { class: "lcol fx" });
      left.appendChild(h("b", { text: hasSpeed ? "Speed & pitch" : "Pitch" }));
      if (hasSpeed) {
        left.appendChild(row("Speed", L.red ? 0.1 : 0.25, L.red ? 10 : 2, 0.05, S.speed, "x", function (v) { setSpeed(v); showMeter(); }));
        left.appendChild(quick([0.5, 0.75, 1, 1.25, 1.5, 2], xs, function (x) { setSpeed(x); draw(); }));
      }
      left.appendChild(row("Pitch", L.red ? -36 : -12, L.red ? 36 : 12, 1, L.pitch, " st", function (v) { L.pitch = v; paintLive(what); showMeter(); },
        function () { app("Changing the pitch" + (hasSpeed ? " without the speed" : "")); }));
      if (hasSpeed) {
        var keep = h("input", { type: "checkbox", checked: L.keep });
        keep.addEventListener("change", function () { L.keep = keep.checked; app("Keeping the pitch while the speed changes"); });
        left.appendChild(h("label", { class: "chk", title: "Off: slower is also deeper and faster is higher, like a tape" }, [keep, h("span", { text: "Keep pitch when changing speed" })]));
      }
      left.appendChild(h("hr"));
      left.appendChild(h("div", { class: "lred" }, [h("div", null, [h("b", { text: "Redline" }),
        h("span", { class: "hint", text: hasSpeed ? "Up to 10x speed and ±36 st pitch" : "Up to ±36 st pitch" })]),
        btn(L.red ? "small acc" : "small", L.red ? "On" : "Unlock", L.red ? "wave" : "shield", function () {
          L.red = !L.red;
          if (!L.red) { if (hasSpeed) setSpeed(Math.max(0.25, Math.min(2, S.speed))); L.pitch = Math.max(-12, Math.min(12, L.pitch)); paintLive(what); }
          draw();
        }, { title: hasSpeed ? "Unlock silly speeds (up to 10x) and pitch (±36 st)" : "Unlock silly pitch (±36 st)" })]));
      if (L.red) {
        showMeter();
        left.appendChild(meter);
        left.appendChild(hasSpeed ? quick([3, 4, 6, 8, 10], xs, function (x) { setSpeed(x); draw(); })
          : quick([-24, -12, 12, 24, 36], function (x) { return (x > 0 ? "+" : "") + x; }, function (x) { L.pitch = x; paintLive(what); draw(); app("Changing the pitch"); }));
      }
      right.appendChild(h("b", { text: "Effects" }));
      FX_PARAMS.forEach(function (q) {
        right.appendChild(row(q[1], q[2], q[3], q[4], L.fx[q[0]] || 0, q[5], function (v) {
          if (v) L.fx[q[0]] = v; else delete L.fx[q[0]];
          L.preset = ""; paintLive(what);
        }, function () { app(q[1] + " on " + (hasSpeed ? "your sounds" : what === "radio" ? "the radio" : "other apps' sound") + ", live"); }));
      });
      right.appendChild(h("div", { class: "ob-lpresets" }, FX_PRESETS.map(function (p) {
        return h("button", { type: "button", class: "btn small", "aria-pressed": L.preset === p[0] ? "true" : "false", text: p[0], onclick: function () {
          var on = L.preset !== p[0];
          L.preset = on ? p[0] : ""; L.fx = on ? Object.assign({}, p[1]) : {};
          draw(); paintLive(what);
          if (on) app("“" + p[0] + "” on " + (hasSpeed ? "your sounds" : what === "radio" ? "the radio" : "other apps' sound"));
        } });
      })));
      el.appendChild(h("div", { class: "lcols" }, [left, h("i"), right]));
      el.appendChild(h("hr"));
      el.appendChild(h("div", { class: "hint", text: hasSpeed ? "Changes every sound while it plays. To save a version, right-click a pad → Effects."
        : what === "radio" ? "Changes the radio while it plays, and what your friends hear of it."
        : "Changes the programs you send while they play, and what your friends hear of them." }));
      place();
    }
    function place() {   // above its button, its right edge on the button's; by the sidebar it opens to the right
      var box = root.getBoundingClientRect(), a = anchor.getBoundingClientRect(), main = R.main.getBoundingClientRect();
      var w = el.offsetWidth, ht = el.offsetHeight;
      var x = a.right - box.left - w;
      if (x < main.left - box.left) x = a.left - box.left;
      x = Math.max(8, Math.min(x, box.width - w - 8));
      var y = a.top - box.top - ht - 6;
      if (y < 8) y = a.bottom - box.top + 6;
      y = Math.max(8, Math.min(y, box.height - ht - 8));
      el.style.left = x + "px"; el.style.top = y + "px";
    }
    root.appendChild(el);
    R.pop = { el: el, anchor: anchor };
    anchor.setAttribute("aria-expanded", "true");
    draw();
    did("live-" + what);
    var first = el.querySelector("input, button");
    if (first) first.focus({ preventScroll: true });
  }

  // ------------------------------------------------------------------ Sounds page
  function shown() {
    var q = S.q.trim().toLowerCase();
    var list = PADS.filter(function (p) {
      return (S.tab === "All" || p.tabs.indexOf(S.tab) >= 0) && (!q || p.name.toLowerCase().indexOf(q) >= 0);
    });
    if (S.sort === "az") list.sort(function (a, b) { return a.name.localeCompare(b.name); });
    if (S.sort === "long") list.sort(function (a, b) { return b.len - a.len; });
    if (S.sort === "most") list.sort(function (a, b) { return b.plays - a.plays; });
    return list;
  }
  function padEl(p) { return R.grid && R.grid.querySelector('[data-id="' + p.id + '"]'); }
  var dragging = null;
  function drawGrid() {
    var g = R.grid;
    g.replaceChildren();
    g.classList.toggle("list", S.view === "list");
    g.style.setProperty("--pad", S.pad + "px");
    var list = shown();
    list.forEach(function (p) {
      var el = h("button", {
        type: "button", class: "ob-pad", "data-id": p.id, style: "--c:" + p.c, draggable: S.sort === "mine" && !S.q ? "true" : null,
        title: p.name + (p.key ? " (hotkey " + p.key + ")" : "") + "\nRight-click for more",
        onclick: function () { start(p); },
        oncontextmenu: function (e) { e.preventDefault(); padMenu(p, e.clientX, e.clientY); },
        onkeydown: function (e) { if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) { e.preventDefault(); var r = el.getBoundingClientRect(); padMenu(p, r.left + 20, r.top + 20); } },
        ondragstart: function (e) { dragging = p; el.classList.add("drag"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", p.name); },
        ondragend: function () { dragging = null; el.classList.remove("drag"); },
        ondragover: function (e) { if (dragging && dragging !== p) { e.preventDefault(); el.classList.add("over"); } },
        ondragleave: function () { el.classList.remove("over"); },
        ondrop: function (e) {
          el.classList.remove("over");
          if (!dragging || dragging === p) return;
          e.preventDefault(); e.stopPropagation();
          PADS.splice(PADS.indexOf(dragging), 1);
          PADS.splice(PADS.indexOf(p), 0, dragging);
          did("reorder");
          drawGrid();
        }
      }, [
        h("span", { class: "nm", text: p.name }),
        h("span", { class: "art", text: p.art, "aria-hidden": "true" }),
        p.key ? h("span", { class: "key", text: p.key }) : null,
        h("span", { class: "len" }, [icon("link"), fmt(p.len || 1)]),
        h("i", { class: "prog" })
      ]);
      g.appendChild(el);
    });
    if (!list.length) g.appendChild(h("div", { class: "ob-none", text: S.q ? "No sounds called “" + S.q + "”. Press Enter to search the web for it." : "Nothing in " + S.tab + " yet. Right-click a sound and add it here." }));
    g.appendChild(R.drop);
    playing.forEach(function (it) { var el = padEl(it.pad); if (el) el.classList.add("on"); });
  }
  function drawTabs() {
    var t = R.tabs;
    t.replaceChildren();
    S.tabs.forEach(function (name) {
      t.appendChild(h("button", {
        type: "button", class: "tab", role: "tab", "aria-selected": S.tab === name ? "true" : "false", text: name,
        onclick: function () { S.tab = name; drawTabs(); drawGrid(); },
        oncontextmenu: function (e) {
          e.preventDefault();
          if (name === "All") return;
          menu(e.clientX, e.clientY, [
            { t: "Rename", icon: "rename", fn: function () { renameTab(name); } },
            { t: "Remove tab (keeps its sounds)", icon: "trash", fn: function () {
              S.tabs.splice(S.tabs.indexOf(name), 1);
              PADS.forEach(function (p) { var i = p.tabs.indexOf(name); if (i >= 0) p.tabs.splice(i, 1); });
              if (S.tab === name) S.tab = "All";
              drawTabs(); drawGrid();
            } }
          ]);
        }
      }));
    });
    var plus = h("button", { type: "button", class: "plus", "aria-label": "Add a tab", title: "Add a tab", onclick: function () {
      var input = h("input", { class: "tabedit", "aria-label": "New tab's name", placeholder: "New tab", maxlength: "24" });
      function done(keep) {
        var v = input.value.trim();
        if (keep && v && S.tabs.indexOf(v) < 0) { S.tabs.push(v); S.tab = v; did("tab"); }
        drawTabs(); drawGrid();
      }
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") done(true); if (e.key === "Escape") { e.stopPropagation(); done(false); } });
      input.addEventListener("blur", function () { done(true); });
      t.replaceChild(input, plus);
      input.focus();
    } }, [icon("plus", "s")]);
    t.appendChild(plus);
  }
  function renameTab(name) {
    var input = h("input", { class: "ob-field", value: name, maxlength: "24", style: "width:100%" });
    var f = h("div", { class: "field" }, [input]);
    dialog("Rename tab", [f], [{ t: "Cancel", fn: function () {} }, { t: "Rename", acc: true, fn: function () {
      var v = input.value.trim();
      if (!v || (v !== name && S.tabs.indexOf(v) >= 0)) return false;
      S.tabs[S.tabs.indexOf(name)] = v;
      PADS.forEach(function (p) { var i = p.tabs.indexOf(name); if (i >= 0) p.tabs[i] = v; });
      if (S.tab === name) S.tab = v;
      drawTabs(); drawGrid();
    } }]);
    setTimeout(function () { input.focus(); input.select(); }, 0);
  }
  function padMenu(p, x, y) {
    var sw = h("div", { class: "vol" }, [h("div", { class: "ob-swatches" }, COLOURS.map(function (c) {
      return h("button", { type: "button", style: "--c:" + c, "aria-label": "Colour " + c, "aria-pressed": p.c === c ? "true" : "false",
        onclick: function () { p.c = c; closeMenu(); drawGrid(); } });
    }))]);
    var items = [
      { t: "Play", icon: "play", fn: function () { start(p); } },
      { t: "Rename…", icon: "rename", fn: function () { renamePad(p); } },
      { t: p.key ? "Change hotkey (" + p.key + ")…" : "Set a hotkey…", icon: "keyboard", fn: function () { hotkey(p); } },
      { t: "Picture…", icon: "image", fn: function () { pickEmoji(p); } },
      "-", { note: "Colour" }, { el: sw }, "-"
    ];
    S.tabs.slice(1).forEach(function (t) {
      items.push({ t: "In " + t, tick: p.tabs.indexOf(t) >= 0, fn: function () {
        var i = p.tabs.indexOf(t);
        if (i >= 0) p.tabs.splice(i, 1); else p.tabs.push(t);
        drawGrid();
      } });
    });
    items.push("-",
      { t: "Effects, trim and speed…", icon: "sliders", fn: function () { tryIt("Changing one sound's effects, trimming it and saving it"); } },
      { t: "Show on the overlay", icon: "eye", fn: function () { tryIt("The in-game overlay"); } },
      "-",
      { t: "Remove", icon: "trash", fn: function () { removePad(p); } });
    menu(x, y, items);
  }
  function renamePad(p) {
    var input = h("input", { value: p.name, maxlength: "40", "aria-label": "Sound's name" });
    dialog("Rename sound", [h("div", { class: "field" }, [input])], [{ t: "Cancel", fn: function () {} }, { t: "Rename", acc: true, fn: function () {
      var v = input.value.trim();
      if (!v) return false;
      p.name = v; drawGrid();
    } }]);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") { var v = input.value.trim(); if (v) { p.name = v; drawGrid(); input.closest(".ob-veil").remove(); } } });
    setTimeout(function () { input.focus(); input.select(); }, 0);
  }
  function pickEmoji(p) {
    var d;
    var grid = h("div", { class: "ob-emoji" }, EMOJI.map(function (e) {
      return h("button", { type: "button", text: e, "aria-pressed": p.art === e ? "true" : "false", onclick: function () { p.art = e; drawGrid(); d.close(); } });
    }));
    d = dialog("Pick a picture", [grid, h("p", { class: "hint", text: "The app also takes your own pictures and GIFs." })], [{ t: "Close", fn: function () {} }]);
  }
  function hotkey(p) {
    var cap = h("div", { class: "btn ob-keycap wait", text: "Press a key…" });
    var d = dialog("Hotkey for " + p.name, [cap, h("p", { class: "hint", text: "Here it works while the demo has focus. In the app it works everywhere, even in a game." })],
      [{ t: "No hotkey", fn: function () { p.key = ""; drawGrid(); } }, { t: "Cancel", fn: function () {} }]);
    function grab(e) {
      if (e.key === "Escape" || e.key === "Tab") return;
      e.preventDefault(); e.stopPropagation();
      if (/^(Shift|Control|Alt|Meta)$/.test(e.key)) return;
      var k = (e.ctrlKey ? "Ctrl+" : "") + (e.altKey ? "Alt+" : "") + (e.shiftKey ? "Shift+" : "") + (e.key.length === 1 ? e.key.toUpperCase() : e.key);
      PADS.forEach(function (o) { if (o !== p && o.key === k) o.key = ""; });
      p.key = k;
      cap.textContent = k;
      document.removeEventListener("keydown", grab, true);
      did("hotkey");
      drawGrid();
      setTimeout(d.close, 450);
    }
    document.addEventListener("keydown", grab, true);
    var oldClose = d.close;
    d.close = function () { document.removeEventListener("keydown", grab, true); oldClose(); };
  }
  function removePad(p) {
    var i = PADS.indexOf(p);
    PADS.splice(i, 1);
    S.removed.unshift({ pad: p, at: i });
    drawGrid();
    clearTimeout(R.undoT);
    var u = h("div", { class: "ob-undo", role: "status" }, [h("span", { text: "Removed “" + p.name + "”" }),
      btn("small", "Undo", null, function () { restore(S.removed[0]); })]);
    if (R.undo) R.undo.remove();
    R.undo = u;
    root.appendChild(u);
    R.undoT = setTimeout(function () { u.remove(); }, 6000);
  }
  function restore(r) {
    if (!r) return;
    S.removed.splice(S.removed.indexOf(r), 1);
    PADS.splice(Math.min(r.at, PADS.length), 0, r.pad);
    if (R.undo) R.undo.remove();
    drawGrid();
  }
  function addFiles(files) {
    var a = site.audio && site.audio();
    if (!a) return;
    var n = 0;
    Array.prototype.forEach.call(files, function (f) {
      if (!/^audio\/|\.(mp3|wav|ogg|m4a|flac|opus|webm)$/i.test(f.type + " " + f.name)) return;
      n++;
      f.arrayBuffer().then(function (b) {
        return new Promise(function (ok, no) { a.ac.decodeAudioData(b, ok, no); });
      }).then(function (buf) {
        PADS.push({ id: nextId++, name: f.name.replace(/\.[^.]+$/, "").slice(0, 40), art: "🎵", c: COLOURS[nextId % COLOURS.length],
                    key: "", tabs: S.tab === "All" ? [] : [S.tab], buf: buf, len: buf.duration, plays: 0 });
        drawGrid();
      }).catch(function () { toast("Can't read that one", "“" + f.name + "” didn't open in your browser. The app opens far more kinds of files."); });
    });
    if (n) { did("add-file"); toast("Added for this visit", "Your sounds stay on your computer: nothing is uploaded. The app keeps them for good."); }
    else toast("Those aren't sounds", "Drop audio files: MP3, WAV, OGG, M4A...");
  }
  function pickFiles() {
    var inp = h("input", { type: "file", accept: "audio/*", multiple: true, style: "display:none" });
    inp.addEventListener("change", function () { addFiles(inp.files); inp.remove(); });
    root.appendChild(inp);
    inp.click();
  }

  function soundsPage() {
    var search = h("input", { type: "search", placeholder: "Search sounds or paste a link", "aria-label": "Search sounds or paste a link", value: S.q });
    search.addEventListener("input", function () { S.q = search.value; drawGrid(); });
    search.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      var v = search.value.trim();
      if (/^https?:\/\/|www\.|\.com\//i.test(v)) tryIt("Downloading a sound from a YouTube, TikTok or other link");
      else if (v && !shown().length) tryIt("Searching YouTube, SoundCloud and Myinstants for “" + v + "”");
    });
    var srcBtn = dd(h("button", { type: "button", class: "btn flat", "aria-label": "Where to search", title: "Where to search" }, [icon(S.src, "s")]));
    srcBtn.addEventListener("click", function () {
      menuAt(srcBtn, [["youtube", "YouTube"], ["ytmusic", "YouTube Music"], ["soundcloud", "SoundCloud"], ["tiktok", "TikTok"], ["myinstants", "Myinstants"]].map(function (s) {
        return { t: s[1], tick: S.src === s[0], fn: function () { S.src = s[0]; srcBtn.replaceChild(icon(s[0], "s"), srcBtn.firstChild); } };
      }));
    });
    var add = dd(btn("flat ob-add", "Add", "music"));
    add.addEventListener("click", function () {
      menuAt(add, [
        { t: "Sound files from your PC…", icon: "folder", fn: pickFiles },
        { t: "Record from your mic", icon: "record", fn: function () { tryIt("Recording a sound"); } },
        { t: "Instant replay (the last 30 seconds)", icon: "history", fn: function () { tryIt("Instant replay"); } },
        { t: "Free sound packs", icon: "download", fn: function () { tryIt("Getting free sound packs"); } },
        { t: "Import from Soundpad, Resanance…", icon: "archive", fn: function () { tryIt("Importing from another soundboard"); } }
      ]);
    });
    var lib = dd(btn("flat ob-hide-m", "Library", "archive"));
    lib.addEventListener("click", function () {
      var items = [{ note: "Recently removed" }];
      if (!S.removed.length) items.push({ note: "Nothing yet" });
      S.removed.slice(0, 6).forEach(function (r) { items.push({ t: "Bring back “" + r.pad.name + "”", icon: "history", fn: function () { restore(r); } }); });
      items.push("-", { t: "Saved clips", icon: "scissors", fn: function () { tryIt("Saved clips"); } },
        { t: "Back up or restore", icon: "download", fn: function () { tryIt("Backing up your sounds"); } });
      menuAt(lib, items);
    });
    var sortNames = { mine: "My order", az: "A to Z", long: "Longest", most: "Most played" };
    var sort = dd(btn("flat ob-hide-s", sortNames[S.sort], "sort"));
    sort.addEventListener("click", function () {
      var items = Object.keys(sortNames).map(function (k) {
        return { t: sortNames[k], tick: S.sort === k, fn: function () { S.sort = k; sort.querySelector(".t").textContent = sortNames[k]; drawGrid(); } };
      });
      items.push("-", { t: "Pads", tick: S.view === "pads", fn: function () { S.view = "pads"; drawGrid(); } },
        { t: "List", tick: S.view === "list", fn: function () { S.view = "list"; drawGrid(); } });
      menuAt(sort, items);
    });
    var size = h("input", { type: "range", min: "110", max: "230", value: String(S.pad), "aria-label": "Pad size" });
    setRange(size);
    size.addEventListener("input", function () { S.pad = +size.value; setRange(size); R.grid.style.setProperty("--pad", S.pad + "px"); });

    R.tabs = h("div", { class: "ob-tabs", role: "tablist" });
    R.grid = h("div", { class: "ob-grid ob-scroll" });
    R.drop = h("div", { class: "ob-drop", text: "Drop sound files here" });
    R.grid.addEventListener("dragover", function (e) { if (!dragging && e.dataTransfer.types.indexOf("Files") >= 0) { e.preventDefault(); R.drop.classList.add("hot"); } });
    R.grid.addEventListener("dragleave", function (e) { if (!R.grid.contains(e.relatedTarget)) R.drop.classList.remove("hot"); });
    R.grid.addEventListener("drop", function (e) { if (dragging) return; e.preventDefault(); R.drop.classList.remove("hot"); addFiles(e.dataTransfer.files); });
    R.drop.addEventListener("click", pickFiles);
    var page = h("div", { class: "ob-page" }, [
      h("div", { class: "ob-bar" }, [add, h("label", { class: "field", style: "flex:1" }, [icon("search", "s"), search]), srcBtn,
        h("span", { class: "ob-sep ob-hide-m" }), lib, h("span", { class: "ob-sep ob-hide-s" }), sort,
        h("span", { class: "hint ob-hide-m", style: "white-space:nowrap;color:var(--text)", text: "Pad size" }), h("div", { class: "ob-hide-m", style: "width:120px;display:flex" }, [size])]),
      R.tabs, R.grid
    ]);
    drawTabs(); drawGrid();
    return page;
  }

  // ------------------------------------------------------------------ the bars at the bottom
  function bars() {
    R.playBtn = h("button", { type: "button", class: "btn icon play", "aria-label": "Play", onclick: function () {
      if (playing.length) stopAll(); else start(S.last || shown()[0] || PADS[0]);
    } }, [icon("play")]);
    var stop = btn("icon", null, "stop", stopAll, { "aria-label": "Stop", title: "Stop" });
    var next = btn("icon", null, "next", function () {
      var list = shown(); if (!list.length) return;
      var i = S.last ? list.indexOf(S.last) : -1;
      start(list[(i + 1) % list.length]);
    }, { "aria-label": "Next sound", title: "Next sound" });
    R.nowName = h("span", { text: "Pick a sound" });
    R.seek = h("input", { type: "range", min: "0", max: "1000", value: "0", class: "ob-seek", "aria-label": "Position" });
    setRange(R.seek);
    R.seek.addEventListener("pointerdown", function () { R.seek._drag = true; });
    R.seek.addEventListener("change", function () {
      R.seek._drag = false;
      var it = playing[playing.length - 1];
      if (!it || !it.buf) return;
      var at = R.seek.value / 1000 * it.buf.duration;
      it.src.onended = null; try { it.src.stop(); } catch (e) { /* done */ }
      end(it); start(it.pad, at);
    });
    var speed = liveBtn("sounds");
    var vol = h("input", { type: "range", min: "0", max: "100", value: String(S.vol * 100), "aria-label": "Sounds volume" });
    var volPct = h("span", { class: "pct", text: Math.round(S.vol * 100) + "%" });
    setRange(vol);
    vol.addEventListener("input", function () { S.vol = vol.value / 100; volPct.textContent = vol.value + "%"; setRange(vol); regain(); });
    var hear = h("input", { type: "checkbox", checked: S.hear });
    hear.addEventListener("change", function () {
      S.hear = hear.checked; regain();
      if (!S.hear) toast("Hear it myself: off", "In the app your friends still hear your sounds, you just don't. Here nobody else is listening, so it goes quiet.");
    });
    R.now = h("div", { class: "now" }, [R.nowName, R.seek, speed]);
    var player = h("div", { class: "ob-bar ob-player" }, [R.playBtn, stop, next, R.now, h("span", { class: "ob-sep ob-hide-s" }),
      h("span", { class: "ob-hide-s", text: "Sounds", style: "font-weight:600" }), h("div", { class: "ob-hide-s", style: "width:90px;display:flex" }, [vol]), h("span", { class: "ob-hide-s" }, [volPct]),
      h("label", { class: "chk ob-hide-m" }, [hear, h("span", { text: "Hear it myself" })])]);

    var others = h("input", { type: "checkbox", checked: S.live });
    others.addEventListener("change", function () { setLive(others.checked); });
    R.othersChk = others;
    var mic = h("input", { type: "range", min: "0", max: "100", value: "100", "aria-label": "Mic volume" });
    var micPct = h("span", { class: "pct", text: "100%" });
    setRange(mic);
    mic.addEventListener("input", function () { micPct.textContent = mic.value + "%"; setRange(mic); });
    R.meter = h("i");
    var phones = h("input", { type: "range", min: "0", max: "100", value: String(S.phones * 100), "aria-label": "Headphones volume" });
    var phPct = h("span", { class: "pct", text: Math.round(S.phones * 100) + "%" });
    setRange(phones);
    phones.addEventListener("input", function () { S.phones = phones.value / 100; phPct.textContent = phones.value + "%"; setRange(phones); regain(); });
    var mbar = h("div", { class: "ob-bar ob-mic" }, [
      h("div", { class: "grp vol" }, [icon("mic", "s"), h("span", { class: "ob-hide-s", text: "My mic" }), h("label", { class: "chk", title: "Others hear it" }, [others, h("span", { class: "ob-hide-m", text: "Others hear it" })]), mic, micPct]),
      h("span", { class: "ob-sep sep2" }),
      h("div", { class: "grp lv" }, [icon("live", "s"), h("span", { class: "lbl2", text: "What others hear" }), h("span", { class: "ob-meter" }, [R.meter]),
        btn("hear ob-hide-m", "Hear what they hear", "ear", function () { tryIt("Listening to what your friends hear"); })]),
      h("span", { class: "ob-sep sep2" }),
      h("div", { class: "grp vol hp" }, [icon("headphones", "s"), h("span", { class: "ob-hide-m", text: "My headphones" }), phones, phPct])
    ]);
    R.player = player;
    return [player, mbar];
  }
  function regain() { playing.forEach(function (it) { if (it.g) it.g.gain.value = gainNow() * 0.7; }); }
  var toldLive = false;
  function setLive(on) {
    S.live = on;
    if (R.othersChk) R.othersChk.checked = on;
    R.live.classList.toggle("muted", !on);
    R.live.replaceChild(icon(on ? "live" : "live_off"), R.live.firstChild);
    R.live.title = on ? "Others hear your sounds and mic: click to mute both" : "Muted for others: click to send again";
    if (!toldLive) { toldLive = true; toast(on ? "Others hear you again" : "Muted for others", "In the app this cuts your sounds and mic from Discord or your game at once. The meter shows what they'd hear."); }
    tick();
  }

  // ------------------------------------------------------------------ Radio
  var STATIONS = [
    ["🇺🇸", "Lofi Hip Hop Radio", "Lo-fi · United States", "Lo-fi"], ["🇬🇧", "BBC Radio 1", "Pop · United Kingdom", "Pop"],
    ["🇫🇷", "FIP", "Jazz · France", "Jazz"], ["🇯🇵", "J-Pop Powerplay", "Pop · Japan", "Pop"],
    ["🇩🇪", "Rock Antenne", "Rock · Germany", "Rock"], ["🇧🇷", "Rádio Funk", "Dance · Brazil", "Dance"],
    ["🇳🇱", "Radio 538", "Dance · Netherlands", "Dance"], ["🇨🇦", "CBC Music", "Classical · Canada", "Classical"],
    ["🇦🇺", "triple j", "Rock · Australia", "Rock"], ["🇮🇹", "Radio Monte Carlo", "Jazz · Italy", "Jazz"],
    ["🇺🇸", "NPR News", "News · United States", "News"], ["🇰🇷", "K-Pop Hits", "Pop · South Korea", "Pop"],
    ["🇸🇪", "Synthwave Sverige", "Electronic · Sweden", "Electronic"], ["🇮🇪", "RTÉ Gold", "Oldies · Ireland", "Oldies"]
  ];
  var radio = { genre: "All", q: "", on: null, stars: {} };
  function radioPage() {
    var list = h("div", { class: "ob-list ob-scroll" });
    function draw() {
      list.replaceChildren();
      var q = radio.q.toLowerCase();
      var rows = STATIONS.filter(function (s) {
        return (radio.genre === "All" || (radio.genre === "★" ? radio.stars[s[1]] : s[3] === radio.genre)) &&
               (!q || (s[1] + " " + s[2]).toLowerCase().indexOf(q) >= 0);
      });
      rows.forEach(function (s) {
        var star = h("button", { type: "button", class: "btn flat icon small star" + (radio.stars[s[1]] ? " on" : ""), "aria-label": "Favourite", onclick: function (e) {
          e.stopPropagation(); radio.stars[s[1]] = !radio.stars[s[1]]; draw();
        } }, [icon(radio.stars[s[1]] ? "star_filled" : "star", "s")]);
        list.appendChild(h("div", { class: "ob-st" + (radio.on === s[1] ? " on" : ""), onclick: function () {
          radio.on = s[1]; draw(); tryIt("Live radio from around the world");
        } }, [h("span", { class: "fl", text: s[0] }), h("span", { class: "tx" }, [h("b", { text: s[1] }), h("small", { text: s[2] })]), star]));
      });
      if (!rows.length) list.appendChild(h("div", { class: "ob-none", text: radio.genre === "★" ? "Star a station to keep it here." : "No stations match." }));
    }
    var chips = h("div", { class: "chips" });
    ["All", "★", "Pop", "Rock", "Lo-fi", "Jazz", "Dance", "Electronic", "News", "Classical", "Oldies"].forEach(function (g) {
      chips.appendChild(h("button", { type: "button", class: "chip", "data-g": g, "aria-pressed": radio.genre === g ? "true" : "false", text: g === "★" ? "★ Favourites" : g, onclick: function () {
        radio.genre = g; Array.prototype.forEach.call(chips.children, function (c) { c.setAttribute("aria-pressed", c.dataset.g === g ? "true" : "false"); }); draw();
      } }));
    });
    var find = h("input", { type: "search", placeholder: "Search 30,000 stations", "aria-label": "Search stations", value: radio.q });
    find.addEventListener("input", function () { radio.q = find.value; draw(); });
    draw();
    return h("div", { class: "ob-page" }, [
      h("div", { class: "ob-bar" }, [h("label", { class: "field", style: "flex:1" }, [icon("search", "s"), find]),
        liveBtn("radio"),
        btn("rec", "Record", null, function () { tryIt("Recording the radio into a pad"); }),
        btn("", "Send to others", "live", function () { tryIt("Playing the radio into your call"); })]),
      h("div", { class: "ob-stations", style: "flex:1;min-height:0" }, [chips, list])
    ]);
  }

  // ------------------------------------------------------------------ Apps
  var APPS = [
    { grp: "Browsers", name: "Chrome", sub: "Lo-fi beats to relax to - YouTube · playing on Headphones", lvl: 0.8, vol: 100 },
    { grp: "Music & media", name: "Spotify", sub: "Spotify Premium · playing on Headphones", lvl: 0.85, vol: 100 },
    { grp: "Music & media", name: "VLC", sub: "movie-night.mkv · quiet", lvl: 0, vol: 100 },
    { grp: "Games", name: "Your game", sub: "Game audio · playing on Headphones", lvl: 0.6, vol: 80 }
  ];
  var appsAnim = 0;
  function appsPage() {
    var body = h("div", { class: "ob-page ob-scroll" });
    var bars = [];
    var grps = {};
    APPS.forEach(function (a) { (grps[a.grp] = grps[a.grp] || []).push(a); });
    body.appendChild(h("div", { class: "ob-apps-top" }, [liveBtn("apps"),
      btn("small", "Category", "plus", function () { tryIt("Sorting apps into your own categories"); })]));
    Object.keys(grps).forEach(function (g) {
      body.appendChild(h("div", { class: "ob-sect", text: g }));
      var grid = h("div", { class: "ob-appgrid" });
      grps[g].forEach(function (a) {
        var lvl = h("i"); bars.push([lvl, a]);
        var vol = h("input", { type: "range", min: "0", max: "100", value: String(a.vol), "aria-label": a.name + " volume" });
        var pct = h("span", { class: "pct", text: a.vol + "%" });
        setRange(vol);
        vol.addEventListener("input", function () { a.vol = +vol.value; pct.textContent = a.vol + "%"; setRange(vol); });
        var card = h("div", { class: "ob-app" }, [
          h("div", { class: "atop" }, [icon("apps"), h("div", { class: "tx" }, [h("b", { text: a.name }), h("small", { text: a.sub })]),
            btn("flat icon small", null, "close", function () { card.remove(); }, { "aria-label": "Hide " + a.name })]),
          h("div", { class: "lvl" }, [lvl]),
          h("div", { class: "row" }, [btn("", "Send", "live", function () { tryIt("Sending " + a.name + "'s sound to your friends"); }),
            btn("rec", "Record", null, function () { tryIt("Recording " + a.name + " into a pad"); }, { html: null }),
            btn("flat icon", null, "eye", function () { tryIt("Watching " + a.name + " for a picture"); }, { "aria-label": "Watch it" })]),
          h("div", { class: "row" }, [vol, pct])
        ]);
        card.querySelector(".rec").insertBefore(h("span", { class: "dotr" }), card.querySelector(".rec").firstChild);
        grid.appendChild(card);
      });
      body.appendChild(grid);
    });
    cancelAnimationFrame(appsAnim);
    (function loop(t) {           // the level bars wobble like a real app playing
      if (!body.isConnected && t) return;
      bars.forEach(function (b, i) {
        var v = b[1].lvl ? b[1].lvl * (b[1].vol / 100) * (0.75 + 0.25 * Math.sin((t || 0) / (170 + i * 37) + i)) : 0;
        b[0].style.transform = "scaleX(" + v.toFixed(3) + ")";
      });
      appsAnim = requestAnimationFrame(loop);
    })(0);
    return body;
  }

  // ------------------------------------------------------------------ Triggers
  var TRIG = [
    { name: "Died", what: "YOU DIED", col: "#c0392b", on: true, when: "The picture shows up", pad: 3 },
    { name: "Boss beaten", what: "VICTORY", col: "#d4a017", on: true, when: "The picture shows up", pad: 6 },
    { name: "Headshot", what: "HEADSHOT", col: "#e67e22", on: false, when: "The picture shows up", pad: 2 }
  ];
  var trigSel = 0;
  function triggersPage() {
    var list = h("div", { class: "ob-tlist" }), detail = h("div", { class: "ob-tdetail ob-scroll" });
    function thumb(t, big) { return h("span", { class: "ob-tpic" + (big ? " big" : ""), style: "--tc:" + t.col, text: t.what }); }
    function drawList() {
      list.replaceChildren(btn("small", "New trigger", "plus", function () { tryIt("Cutting a new picture out of your game"); }));
      TRIG.forEach(function (t, i) {
        var sw = h("button", { type: "button", class: "sw", role: "switch", "aria-checked": t.on ? "true" : "false", "aria-label": "On", onclick: function (e) {
          e.stopPropagation(); t.on = !t.on; sw.setAttribute("aria-checked", t.on ? "true" : "false");
        } });
        list.appendChild(h("div", { class: "ob-trow" + (i === trigSel ? " on" : ""), onclick: function () { trigSel = i; drawList(); drawDetail(); } },
          [thumb(t), h("span", { class: "tx" }, [h("b", { text: t.name }), h("small", { text: t.on ? "Ready" : "Paused" })]), sw]));
      });
    }
    function drawDetail() {
      var t = TRIG[trigSel];
      function sel(items, cur, fn) {
        var s = h("select", { onchange: function () { fn(s.value); } });
        items.forEach(function (o) { s.appendChild(h("option", { text: o, value: o, selected: o === cur })); });
        return h("span", { class: "sel" }, [s]);
      }
      var padNames = PADS.map(function (p) { return p.name; });
      var cur = PADS.filter(function (p) { return p.id === t.pad; })[0] || PADS[0];
      detail.replaceChildren(
        h("div", { class: "ob-thead" }, [thumb(t, true), h("div", { class: "tx" }, [h("b", { text: t.name }), h("small", { class: "hint", text: "Plays " + cur.name + " when this shows up in your game." })])]),
        h("div", { class: "ob-dlg", style: "width:auto;border:0;box-shadow:none;padding:0;background:none" }, [
          h("div", { class: "row" }, [h("span", { class: "lbl", text: "When" }), sel(["The picture shows up", "The picture goes away", "The picture changes"], t.when, function (v) { t.when = v; })]),
          h("div", { class: "row" }, [h("span", { class: "lbl", text: "Look in" }), sel(["Default (Screen 1)", "Screen 2", "Your game's window"], "Default (Screen 1)", function () {})]),
          h("div", { class: "row" }, [h("span", { class: "lbl", text: "Then play" }), sel(padNames, cur.name, function (v) {
            t.pad = PADS.filter(function (p) { return p.name === v; })[0].id; drawDetail();
          })])
        ]),
        h("div", { class: "row", style: "display:flex;gap:8px;flex-wrap:wrap" }, [
          btn("", "Test", "play", function () { start(cur); }),
          btn("", "Duplicate", "copy", function () { var c = Object.assign({}, t, { name: t.name + " copy" }); TRIG.splice(trigSel + 1, 0, c); trigSel++; drawList(); drawDetail(); }),
          btn("danger", "Delete", "trash", function () { if (TRIG.length > 1) { TRIG.splice(trigSel, 1); trigSel = Math.max(0, trigSel - 1); drawList(); drawDetail(); } })
        ])
      );
    }
    drawList(); drawDetail();
    return h("div", { class: "ob-page" }, [
      h("div", { class: "ob-trig" }, [list, detail]),
      h("div", { class: "ob-bar" }, [btn("acc", "Start watching", "eye", function () { tryIt("Watching your game's screen"); }),
        btn("", "Set picture", "image", function () { tryIt("Cutting a picture out of your game"); }),
        h("span", { class: "hint ob-hide-s", text: "Test plays the sound. In the app it plays by itself when your game shows the picture." })])
    ]);
  }

  // ------------------------------------------------------------------ Voice
  // The voice changer's cards in the app's groups (ui/voicefxpanel.py VOICE_GROUPS), My setups
  // over the tabs (they show up in Live controls too) and the AI voices with their pictures.
  var VGROUPS = [["funny", "Funny", ["Chipmunk", "High voice", "Hothead", "Singing monk", "Underwater"]],
    ["scary", "Scary", ["Demon", "Masked caller", "Dark lord", "Ghost", "Haunted radio"]],
    ["scifi", "Robots & sci-fi", ["Robot", "Talkbox", "Autotune", "Alien", "Dalek"]],
    ["disguise", "Disguise", ["Deep voice", "Male voice", "Anonymous", "Secret detective"]],
    ["places", "Radio & places", ["Walkie-talkie", "Old telephone", "Megaphone", "Stadium announcer", "Cave", "Podcast voice"]],
    ["mine", "Mine", ["My own mix"]]];
  var AI_VOICES = [["bear", "Bear", "A big, deep voice."], ["duke", "Duke", "Older and gravelly."], ["brick", "Brick", "Gruff and grounded."],
    ["max", "Max", "An everyday guy."], ["riley", "Riley", "A young guy."], ["atlas", "Atlas", "A smooth, deep storyteller."],
    ["sarge", "Sarge", "Loud and barking."], ["river", "River", "Somewhere in between."], ["ivy", "Ivy", "A husky woman's voice."],
    ["sage", "Sage", "A calm, low woman's voice."], ["nova", "Nova", "A clear, soft woman's voice."], ["pixie", "Pixie", "Light and young-sounding."],
    ["nana", "Nana", "An older woman's voice."], ["zoe", "Zoe", "A young woman's voice."], ["onyx", "Onyx", "A very low woman's voice."],
    ["squeak", "Squeak", "A tiny cartoon voice."], ["bean", "Bean", "A little kid."], ["titan", "Titan", "A huge, rumbling voice."]];
  function voicePic(name) { return name === "My own mix" ? "custom" : name.toLowerCase().replace(/ /g, "-"); }
  var voiceTab = "changer", pickedVoice = null, voiceGroup = "", voiceFavs = { "Demon": true };
  function voicePage() {
    var say = h("input", { placeholder: "Type a line and press Enter", "aria-label": "Text to say" });
    function speak() {
      var v = say.value.trim();
      if (!v) return say.focus();
      if (!window.speechSynthesis) return tryIt("Text-to-speech");
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(v);
      u.volume = (document.getElementById("mute") || {}).getAttribute && document.getElementById("mute").getAttribute("aria-pressed") === "true" ? 0 : 0.8;
      speechSynthesis.speak(u);
      did("say");
      toast("Said it to you", "The app says it into your call, in 100+ voices and languages.");
    }
    say.addEventListener("keydown", function (e) { if (e.key === "Enter") speak(); });
    var tabs = h("div", { class: "ob-vtabs" });
    var setups = h("div", { class: "ob-setups" });
    var body = h("div", { class: "ob-vcard" });
    var strip = h("div", { class: "ob-bar ob-vstrip" });
    function drawAll() { drawTabs(); drawSetups(); drawBody(); drawStrip(); }
    function drawTabs() {
      tabs.replaceChildren();
      [["changer", "Voice changer", "voice"], ["ai", "AI voices", "wave"], ["lang", "Languages", "speech"], ["addons", "Add-ons", "puzzle"]].forEach(function (t) {
        tabs.appendChild(btn("", t[1], t[2], function () { voiceTab = t[0]; drawAll(); }, { "aria-pressed": voiceTab === t[0] ? "true" : "false" }));
      });
    }
    function drawSetups() {     // My setups: under the tabs, whichever part is showing
      setups.replaceChildren(h("b", { text: "My setups" }));
      SETUPS.forEach(function (s) {
        setups.appendChild(h("button", { type: "button", class: "chip", "aria-pressed": pickedVoice === s.voice ? "true" : "false", title: s.voice + "\nRight-click for more",
          onclick: function () { pickedVoice = pickedVoice === s.voice ? null : s.voice; drawAll(); if (pickedVoice) tryIt("Turning on your “" + s.name + "” setup"); },
          oncontextmenu: function (e) {
            e.preventDefault();
            menu(e.clientX, e.clientY, [
              { t: "Use on my sounds", icon: "sounds", fn: function () { LIVE.sounds.setup = s.name; paintLive("sounds"); tryIt("Playing your sounds in your “" + s.name + "” voice"); } },
              { t: "Set a hotkey…", icon: "keyboard", fn: function () { tryIt("A hotkey for a setup"); } },
              "-",
              { t: "Delete", icon: "trash", fn: function () {
                SETUPS.splice(SETUPS.indexOf(s), 1);
                Object.keys(LIVE).forEach(function (k) { if (LIVE[k].setup === s.name) { LIVE[k].setup = ""; paintLive(k); } });
                drawSetups();
              } }]);
          } }, [icon("voice", "s"), s.name]));
      });
      setups.appendChild(btn("small", "Save what's on", "plus", function () {
        if (!pickedVoice) return toast("Nothing's on yet", "Pick a voice first, then save it here. Your setups show up in Live controls, to play your sounds in them.");
        var name = h("input", { value: pickedVoice, maxlength: "32", "aria-label": "Name" });
        dialog("Save what's on", [h("p", { class: "hint", text: "A voice, an AI voice and a language, saved under a name. One click turns it all on, and Live controls puts it on your sounds, the radio or other apps." }),
          h("label", { class: "field" }, [name])], [{ t: "Cancel", fn: function () {} }, { t: "Save", acc: true, fn: function () {
            var n = name.value.trim().slice(0, 32);
            if (!n) return false;
            SETUPS = SETUPS.filter(function (s) { return s.name !== n; }).concat([{ name: n, voice: pickedVoice }]);
            drawSetups();
            toast("Saved “" + n + "”", "It's in Live controls now too: the 1x button by the player puts it on your sounds.");
          } }]);
        setTimeout(function () { name.focus(); name.select(); }, 0);
      }));
    }
    function card(v) {
      var star = h("button", { type: "button", class: "star" + (voiceFavs[v] ? " on" : ""), "aria-label": voiceFavs[v] ? "Remove from favourites" : "Add to favourites",
        onclick: function (e) { e.stopPropagation(); voiceFavs[v] = !voiceFavs[v]; drawBody(); } }, [icon(voiceFavs[v] ? "star_filled" : "star", "s")]);
      function pick() {
        pickedVoice = pickedVoice === v ? null : v;
        drawAll();
        if (pickedVoice) toast("Voice changer: " + v, "In the app your mic sounds like this, live. Save it as a setup and Live controls plays your sounds in it too.", true);
      }
      return h("div", { class: "ob-voice", role: "button", tabindex: "0", "aria-pressed": pickedVoice === v ? "true" : "false", onclick: pick,
        onkeydown: function (e) { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pick(); } } },
        [h("img", { src: "demo/voices/" + voicePic(v) + ".webp", alt: "", loading: "lazy" }), h("span", { text: v }), star]);
    }
    function drawChanger() {
      var sw = h("button", { type: "button", class: "sw", role: "switch", "aria-checked": pickedVoice ? "true" : "false", "aria-label": "Voice changer on" });
      sw.addEventListener("click", function () { if (pickedVoice) { pickedVoice = null; drawAll(); } else tryIt("Changing your voice live"); });
      var chips = h("div", { class: "chips" });
      [["", "All"], ["favs", "Favorites"]].concat(VGROUPS.map(function (g) { return [g[0], g[1]]; })).forEach(function (g) {
        var c = h("button", { type: "button", class: "chip", "aria-pressed": voiceGroup === g[0] ? "true" : "false", onclick: function () { voiceGroup = g[0]; drawBody(); } });
        if (g[0] === "favs") c.appendChild(icon("star_filled", "s"));
        c.appendChild(document.createTextNode(g[1]));
        chips.appendChild(c);
      });
      body.append(h("div", { class: "hd" }, [h("span", { class: "ic" }, [icon("voice")]), h("b", { text: "Voice changer" }), sw, h("span", { text: pickedVoice ? "On" : "Off" })]),
        h("p", { class: "hint", text: "Change your mic live for whoever you send sounds to (Discord, a game, OBS). Pick a voice to turn it on, then use Hear what they hear at the bottom to try it." }),
        chips);
      if (voiceGroup === "favs") {
        var favs = Object.keys(voiceFavs).filter(function (v) { return voiceFavs[v]; });
        body.appendChild(favs.length ? h("div", { class: "ob-voices" }, favs.map(card)) : h("div", { class: "ob-none", text: "Star a voice to keep it here." }));
        return;
      }
      VGROUPS.forEach(function (g) {
        if (voiceGroup && voiceGroup !== g[0]) return;
        if (!voiceGroup) body.appendChild(h("div", { class: "ob-vgroup", text: g[1] }));
        body.appendChild(h("div", { class: "ob-voices" }, g[2].map(card)));
      });
    }
    function drawAi() {
      body.append(h("div", { class: "hd" }, [h("span", { class: "ic" }, [icon("wave")]), h("b", { text: "AI voices" })]),
        h("p", { class: "hint", text: "Your words and tone, a different voice. Live on this PC." }),
        h("div", { class: "ob-install" }, [h("span", { class: "bun" }, [icon("bun")]), h("div", null, [
          h("p", { class: "hint", text: "AI voices need a one-time install first: about 90 MB (the voice model and its runtime)." }),
          btn("", "Install AI voices", "plus", function () { tryIt("AI voices"); })])]),
        h("div", { class: "ob-vgroup", text: "The voices you get" }),
        h("div", { class: "ob-aivs" }, AI_VOICES.map(function (v) {
          return h("button", { type: "button", onclick: function () { tryIt("Talking in " + v[1] + "'s voice"); } },
            [h("img", { src: "demo/ai/" + v[0] + ".webp", alt: "", loading: "lazy" }), h("span", null, [h("b", { text: v[1] }), h("small", { text: v[2] })])]);
        })));
    }
    function drawBody() {
      body.replaceChildren();
      if (voiceTab === "changer") return drawChanger();
      if (voiceTab === "ai") return drawAi();
      var names = { lang: ["Languages", "Type in one language and it's said in another, in your call."],
                    addons: ["Add-ons", "Extra voice packs and engines, one click each."] }[voiceTab];
      body.append(h("div", { class: "hd" }, [h("span", { class: "ic" }, [icon(voiceTab === "lang" ? "speech" : "puzzle")]), h("b", { text: names[0] })]),
        h("p", { class: "hint", text: names[1] }),
        h("div", null, [btn("acc", "Download free to try these", "download", function () { location.href = DL; })]));
    }
    function drawStrip() {      // the Voice tab's own bar: your mic and what's changing it
      strip.replaceChildren(btn("danger small", "Stop", "stop", function () { pickedVoice = null; drawAll(); }, { title: "Turn the voice changer off" }),
        icon("mic", "s"), h("span", { class: "hint ob-hide-s", text: "No mic open" }), h("span", { class: "ob-meter" }, [h("i")]),
        h("span", { class: "hint st" }, [icon("ear", "s"), pickedVoice ? "Voice changer: " + pickedVoice : "Voice effects off: mic unchanged"]));
    }
    drawAll();
    return h("div", { class: "ob-page" }, [
      h("div", { class: "ob-scroll ob-vscroll" }, [
        h("div", { class: "ob-bar ob-say" }, [icon("speech", "s"), h("label", { class: "field" }, [say]), btn("", "Say", null, speak),
          btn("ob-hide-s", "Save as sound", "plus", function () { tryIt("Saving a spoken line as a pad"); }),
          btn("", "Stop", null, function () { if (window.speechSynthesis) speechSynthesis.cancel(); })]),
        tabs, setups, body]),
      strip
    ]);
  }

  // ------------------------------------------------------------------ Community (the store)
  // The sound store (ui/storetab.py): sounds people share, voted on. Hear one, or add it to
  // your pads for real; voting, sharing and reporting need the app.
  var STORE = [
    { sfx: "boom", name: "Vine boom (extra bass)", by: "by bassboi", tags: "meme, boom", up: 4210, cat: "memes" },
    { sfx: "horn", name: "MLG air horn", by: "by Onion Board", tags: "meme, horn", up: 3870, cat: "memes" },
    { sfx: "buzzer", name: "Wrong answer", by: "Shared by a player", tags: "game show", up: 2950, cat: "reactions" },
    { sfx: "trombone", name: "Sad trombone", by: "by Onion Board", tags: "fail", up: 2410, cat: "reactions" },
    { sfx: "rimshot", name: "Ba dum tss", by: "by jokester", tags: "drum, joke", up: 1980, cat: "reactions" },
    { sfx: "coin", name: "Coin pickup", by: "Shared by a player", tags: "retro, game", up: 1630, cat: "games" },
    { sfx: "laser", name: "Laser zap", by: "by pewpew", tags: "sci-fi", up: 1120, cat: "games" },
    { sfx: "drop", name: "Bass drop", by: "by dj_onion", tags: "music, drop", up: 980, cat: "music" },
    { sfx: "clap", name: "Crowd applause", by: "Shared by a player", tags: "crowd", up: 870, cat: "reactions" },
    { sfx: "hoot", name: "Owl at night", by: "by Hoot", tags: "animal, spooky", up: 410, cat: "pranks" }
  ];
  var store = { sort: "top", cat: "", q: "" };
  function storePage() {
    var list = h("div", { class: "ob-store" });
    function count(n) { return n >= 1000 ? (n / 1000).toFixed(1).replace(".0", "") + "k" : String(n); }
    function draw() {
      list.replaceChildren();
      var q = store.q.trim().toLowerCase();
      var rows = STORE.filter(function (s) { return (!store.cat || s.cat === store.cat) && (!q || (s.name + " " + s.tags).toLowerCase().indexOf(q) >= 0); });
      if (store.sort === "new") rows = rows.slice().reverse();
      if (store.sort === "trending") rows = rows.slice(2).concat(rows.slice(0, 2));
      rows.forEach(function (s) {
        var added = PADS.some(function (p) { return p.fromStore === s.name; });
        var play = btn("flat icon", null, "play", function () { if (site.play) site.play(s.sfx); did("store-play"); }, { "aria-label": "Hear it (only you)", title: "Hear it (only you)" });
        var up = btn("flat small", count(s.up), "like", function () { tryIt("Voting on shared sounds"); }, { title: "I like it" });
        var down = btn("flat small", null, "dislike", function () { tryIt("Voting on shared sounds"); }, { title: "Not for me", "aria-label": "Not for me" });
        var add = btn(added ? "small" : "small acc", added ? "Added" : null, added ? "check" : "plus", function () {
          if (added) return go("sounds");
          PADS.push({ sfx: s.sfx, name: s.name, art: "🎵", c: COLOURS[nextId % COLOURS.length], key: "", tabs: [], id: nextId++, len: LENS[s.sfx] || 1, plays: 0, fromStore: s.name });
          did("store-add");
          draw();
          toast("Added “" + s.name + "”", "It's on your Sounds tab now. Shared sounds are free for anyone to use (CC0).");
        }, { title: added ? "On your Sounds tab" : "Add it to your Sounds", "aria-label": added ? "Added" : "Add it to your Sounds" });
        var flag = btn("flat icon", null, "flag", function () { tryIt("Reporting a sound"); }, { "aria-label": "Report this sound", title: "Report this sound" });
        list.appendChild(h("div", { class: "ob-srow" }, [play, h("div", { class: "tx" }, [h("b", { text: s.name }), h("small", { text: s.by + " · " + s.tags })]), up, down, add, flag]));
      });
      if (!rows.length) list.appendChild(h("div", { class: "ob-none", text: "Nothing matches. Try other words." }));
    }
    var SORTS = [["top", "Top", "The best voted first"], ["new", "New", "The newest first"],
      ["trending", "Trending", "What's hot on Myinstants right now, and the sounds people here liked this week"]];
    var sorts = h("div", { class: "ob-sorts" });
    SORTS.forEach(function (s) {
      sorts.appendChild(btn("", s[1], null, function () {
        store.sort = s[0];
        Array.prototype.forEach.call(sorts.children, function (b, i) { b.setAttribute("aria-pressed", SORTS[i][0] === s[0] ? "true" : "false"); });
        draw();
      }, { title: s[2], "aria-pressed": store.sort === s[0] ? "true" : "false" }));
    });
    var find = h("input", { type: "search", placeholder: "Search the store", "aria-label": "Search the store", value: store.q });
    find.addEventListener("input", function () { store.q = find.value; draw(); });
    var cats = h("div", { class: "chips" });
    [["", "All"], ["memes", "Memes"], ["reactions", "Reactions"], ["games", "Games"], ["music", "Music"], ["pranks", "Pranks"]].forEach(function (c) {
      cats.appendChild(h("button", { type: "button", class: "chip", "data-c": c[0], "aria-pressed": store.cat === c[0] ? "true" : "false", text: c[1], onclick: function () {
        store.cat = c[0];
        Array.prototype.forEach.call(cats.children, function (b) { b.setAttribute("aria-pressed", b.dataset.c === c[0] ? "true" : "false"); });
        draw();
      } }));
    });
    draw();
    return h("div", { class: "ob-page ob-scroll" }, [
      h("div", { class: "ob-vcard ob-storehead" }, [
        h("div", { class: "hd" }, [icon("store", "s"), h("b", { text: "Sound store" }), h("span", { class: "ob-beta", text: "Beta", title: "The sound store is new and still changing." }),
          btn("flat icon small", null, "info", function () { toast("Free to use", "Sounds people share here are CC0: free for anyone to use for anything. Each one is checked before it shows."); }, { "aria-label": "About the store" })]),
        h("div", { class: "row" }, [btn("acc", "Share a sound", "upload", function () { tryIt("Sharing your own sound with everyone"); }), sorts]),
        h("div", { class: "row" }, [h("label", { class: "field", style: "flex:1" }, [icon("search", "s"), find]),
          btn("flat icon", null, "reload", function () { draw(); }, { "aria-label": "Refresh", title: "Refresh" })])]),
      cats, list
    ]);
  }

  // ------------------------------------------------------------------ Setup
  var MODES = [["game", "Game", "gamepad", "Game: shaping for your game's voice chat, so your sounds come through it clearly."],
    ["chat", "Voice chat", "headphones", "Voice chat: shaping for Discord, so its noise filter leaves your sounds alone."],
    ["clean", "Clean", "wave", "Clean: your sounds go out exactly as mixed."],
    ["adv", "Advanced", "sliders", "Advanced: pick the shaping yourself, for each app."]];
  var mode = "chat";
  function setupPage() {
    var devs = (D.settings.audio[0] || { items: [] }).items.filter(function (i) { return i.k === "combo"; });
    function devSel(i) {
      var c = devs[i] || { items: ["(none)"], cur: "(none)" };
      var s = h("select", { "aria-label": "Device" });
      c.items.forEach(function (o) { s.appendChild(h("option", { text: o, selected: o === c.cur })); });
      return h("span", { class: "sel" }, [s]);
    }
    var hint = h("div", { class: "hint" });
    var modes = h("div", { class: "ob-modes" });
    function drawModes() {
      modes.replaceChildren();
      MODES.forEach(function (m) { modes.appendChild(btn("", m[1], m[2], function () { mode = m[0]; drawModes(); }, { "aria-pressed": mode === m[0] ? "true" : "false" })); });
      hint.textContent = MODES.filter(function (m) { return m[0] === mode; })[0][3];
    }
    drawModes();
    function chk(t, on) { return h("label", { class: "chk" }, [h("input", { type: "checkbox", checked: on }), h("span", { text: t })]); }
    var lower = h("span", { class: "sel" }, [h("select", { "aria-label": "Lower my sounds" }, ["Off", "A little", "A lot"].map(function (o) { return h("option", { text: o }); }))]);
    return h("div", { class: "ob-page ob-scroll" }, [h("div", { class: "ob-setup" }, [
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("mic"), h("span", { text: "Your mic" }), h("span", { class: "ob-pill", text: "Connected" })]),
        h("div", { class: "ob-okbox" }, [h("div", { class: "l1" }, [h("span", { class: "ok", style: "display:flex;gap:8px;align-items:center;font-weight:600" }, [icon("check", "s"), "Your sounds go into your mic"]),
          h("span", { class: "hint", text: "Microphone (USB Audio Device)" })]),
          h("div", { class: "l1" }, [btn("flat small", "Reinstall", null, function () { tryIt("Setting up your mic"); }), btn("flat small danger", "Remove", null, function () { tryIt("Setting up your mic"); })])]),
        h("b", { text: "Optional: other ways to send your sounds" }),
        h("div", { class: "ob-twocol" }, [
          h("div", null, [h("div", { class: "head" }, [icon("cable", "s"), h("span", { text: "Virtual cable" })]), h("p", { text: "For a game that skips your mic: your sounds go out on a cable it can pick." }),
            btn("small", "Use a cable", "cable", function () { tryIt("Sending through a virtual cable"); })]),
          h("div", null, [h("div", { class: "head" }, [icon("sliders", "s"), h("span", { text: "Another device" })]), h("p", { text: "For streamers and mixers: send your sounds to Voicemeeter, OBS, a mixer, or to nobody." }),
            btn("small", "Pick a device", "sliders", function () { tryIt("Sending to another device"); })])
        ])
      ]),
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("ear"), h("span", { text: "Who's listening" })]),
        h("div", { class: "hint", text: "Where people hear you: a game, a voice chat app, or a stream. Your sounds are shaped to come through clearly." }),
        modes, hint, chk("Send in mono (recommended)", true),
        h("div", { class: "r", style: "display:flex;align-items:center;gap:10px" }, [h("span", { text: "While I talk, lower my sounds:" }), lower]),
        chk("Mute my mic while a sound plays", false)
      ]),
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("headphones"), h("span", { text: "Devices" })]),
        h("div", { class: "hint", text: "Already set up for you, only change these if something's wrong." }),
        h("div", { class: "ob-dev" }, [icon("headphones", "s"), h("span", { class: "lbl", text: "My headphones" }), devSel(1),
          icon("mic", "s"), h("span", { class: "lbl", text: "My mic" }), devSel(0),
          icon("live", "s"), h("span", { class: "lbl", text: "Send my sounds to" }), devSel(2)]),
        h("div", null, [btn("", "Re-scan devices", "reload", function () { tryIt("Finding your real devices"); })])
      ]),
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("sliders"), h("span", { text: "Equalizer and volume" })]),
        chk("EQ on for my voice", false), chk("Level volumes (all sounds equally loud)", true),
        h("div", { class: "head", style: "margin-top:8px" }, [icon("bun"), h("span", { text: "Bun's check" })]),
        h("div", { class: "hint", text: "Bun checks your mic, Discord and your game, and fixes what would stop your friends hearing you." }),
        h("div", null, [btn("acc", "Check my setup", "check", function () { tryIt("Bun's setup check"); })])
      ])
    ])]);
  }

  // ------------------------------------------------------------------ Settings
  var SET_PAGES = [["Audio", "audio", "headphones"], ["Appearance", "appearance", "palette"], ["Hotkeys", "hotkeys", "keyboard"], ["Tabs", "tabs", "list"],
    ["General", "general", "settings"], ["About", "about", "info"]];
  var SET_ADV = [["Overlay", "overlay", "eye"], ["Privacy & security", "privacy", "shield"], ["Connection", "connection", "link"],
    ["Data & quality", "data", "download"], ["Updates", "updates", "reload"], ["Add-ons", "help", "puzzle"], ["Remote", "remote", "phone"]];
  function tellSettings() {
    if (S.toldSettings) return;
    S.toldSettings = true;
    toast("Just for show", "Settings change here, but they only change things in the app.");
  }
  function cardEl(card) {
    var rows = [], items = card.items.slice().sort(function (a, b) { return (a.y + a.h / 2) - (b.y + b.h / 2) || a.x - b.x; });
    items.forEach(function (it) {
      var mid = it.y + it.h / 2, row = rows[rows.length - 1];
      if (row && Math.abs(row.mid - mid) < 12) row.items.push(it); else rows.push({ mid: mid, items: [it] });
    });
    var el = h("div", { class: "ob-scard2" });
    rows.forEach(function (row, ri) {
      row.items.sort(function (a, b) { return a.x - b.x; });
      var r = h("div", { class: "r" });
      row.items.forEach(function (it) {
        if (it.k === "label") {
          if (it.on === "section") r.appendChild(h("div", { class: "head" }, [ri === 0 ? icon(card.icon || "settings", "s") : null, h("span", { class: "t", text: it.t })]));
          else if (it.on === "hint") r.appendChild(h("div", { class: "h lb", text: it.t }));
          else r.appendChild(h("div", { class: "lb", text: it.t }));
        } else if (it.k === "check") {
          var c = h("input", { type: "checkbox", checked: it.on, onchange: tellSettings });
          r.appendChild(h("label", { class: "chk lb" }, [c, h("span", { text: it.t })]));
        } else if (it.k === "combo") {
          var s = h("select", { "aria-label": "Choice", onchange: tellSettings });
          it.items.forEach(function (o) { s.appendChild(h("option", { text: o, selected: o === it.cur })); });
          r.appendChild(h("span", { class: "sel" }, [s]));
        } else if (it.k === "slider") {
          var sl = h("input", { type: "range", min: String(it.v[0]), max: String(it.v[2]), value: String(it.v[1]), "aria-label": "Amount" });
          setRange(sl);
          sl.addEventListener("input", function () { setRange(sl); tellSettings(); });
          r.appendChild(sl);
        } else if (it.k === "edit") {
          r.appendChild(h("label", { class: "field" }, [h("input", { value: it.t || "", placeholder: it.ph || "", "aria-label": "Value", oninput: tellSettings })]));
        } else if (it.k === "btn") {
          r.appendChild(btn("small", it.t, null, function () { tryIt("“" + it.t + "”"); }, { title: it.tip || null }));
        }
      });
      if (r.childNodes.length) el.appendChild(r);
    });
    return el;
  }
  function themesCard() {
    var wrap = h("div", { class: "ob-scard2" }, [h("div", { class: "r" }, [h("div", { class: "head" }, [icon("palette", "s"), h("span", { class: "t", text: "Theme" })])]),
      h("div", { class: "h", text: "31 looks, from plain Dark to Deep Fried. The whole demo switches when you pick one." })]);
    D.groups.forEach(function (g) {
      wrap.appendChild(h("b", { text: g[0], style: "margin-top:6px" }));
      var grid = h("div", { class: "ob-themes" });
      g[1].forEach(function (name) {
        var t = D.themes[name]; if (!t) return;
        grid.appendChild(h("button", {
          type: "button", class: "ob-theme", "aria-pressed": S.theme === name ? "true" : "false",
          style: "--pbg:" + t.bg + ";--pcard:" + t.card + ";--pc:" + t.text + ";--ppanel:" + t.panel + ";--pa:" + t.accent + ";--pg:" + t.groove,
          onclick: function () {
            theme(name); did("theme");
            Array.prototype.forEach.call(root.querySelectorAll(".ob-theme"), function (b) { b.setAttribute("aria-pressed", b === this ? "true" : "false"); }, this);
          }
        }, [h("span", { class: "pv" }, [h("i"), h("i"), h("i", { class: "side" }), h("i"), h("i")]), h("span", { text: name })]));
      });
      wrap.appendChild(grid);
    });
    return wrap;
  }
  function settingsPage() {
    var body = h("div", { class: "ob-spage ob-scroll" });
    var nav = h("div", { class: "ob-snav" });
    var find = h("input", { type: "search", placeholder: "Search settings", "aria-label": "Search settings" });
    function show(key) {
      S.setPage = key;
      body.replaceChildren();
      var cards = D.settings[key] || [];
      cards.forEach(function (c) {
        if (key === "appearance" && c.title !== "Language") return;
        body.appendChild(cardEl(c));
      });
      if (key === "appearance") body.appendChild(themesCard());
      body.scrollTop = 0;
      Array.prototype.forEach.call(nav.querySelectorAll("button.pg[data-k]"), function (b) { b.setAttribute("aria-current", b.dataset.k === key ? "page" : "false"); });
    }
    function search(q) {
      q = q.trim().toLowerCase();
      if (!q) return show(S.setPage);
      body.replaceChildren();
      var hits = 0;
      Object.keys(D.settings).forEach(function (k) {
        D.settings[k].forEach(function (c) {
          var txt = c.items.map(function (i) { return (i.t || "") + " " + (i.items || []).join(" "); }).join(" ").toLowerCase();
          if (txt.indexOf(q) >= 0 || c.title.toLowerCase().indexOf(q) >= 0) { body.appendChild(cardEl(c)); hits++; }
        });
      });
      if (!hits) body.appendChild(h("div", { class: "ob-none", text: "No settings match “" + q + "”." }));
    }
    find.addEventListener("input", function () { search(find.value); });
    nav.appendChild(h("button", { type: "button", class: "back", onclick: function () { go("sounds"); } }, [icon("nav_back", "g"), h("span", { class: "t", text: "Settings" })]));
    nav.appendChild(h("label", { class: "field" }, [icon("search", "s"), find]));
    function navBtn(p) {
      return h("button", { type: "button", class: "pg", "data-k": p[1], title: p[0], onclick: function () { find.value = ""; show(p[1]); } }, [icon(p[2], "s"), h("span", { class: "t", text: p[0] })]);
    }
    SET_PAGES.forEach(function (p) { nav.appendChild(navBtn(p)); });
    nav.appendChild(h("hr"));
    var adv = h("div", { style: "display:contents" });
    var more = h("button", { type: "button", class: "pg", "aria-expanded": S.advanced ? "true" : "false", onclick: function () {
      S.advanced = !S.advanced; more.setAttribute("aria-expanded", S.advanced ? "true" : "false"); adv.hidden = !S.advanced;
    } }, [icon("next", "more"), h("span", { class: "t", text: "Show advanced" })]);
    nav.appendChild(more);
    SET_ADV.forEach(function (p) { adv.appendChild(navBtn(p)); });
    adv.hidden = !S.advanced;
    nav.appendChild(adv);
    show(S.setPage);
    return h("div", { class: "ob-page" }, [h("div", { class: "ob-settings" }, [nav, body])]);
  }

  // ------------------------------------------------------------------ frame and pages
  function go(page) {
    closeMenu(); closeLive();
    S.page = page;
    did("page-" + page);
    var p = page === "sounds" ? soundsPage() : page === "voice" ? voicePage() : page === "settings" ? settingsPage() : page === "radio" ? radioPage() : page === "apps" ? appsPage() :
            page === "triggers" ? triggersPage() : page === "store" ? storePage() : setupPage();
    R.page.replaceWith(p);
    R.page = p;
    Array.prototype.forEach.call(R.nav.children, function (b) { b.setAttribute("aria-current", b.dataset.p === page ? "page" : "false"); });
    R.setBtn.setAttribute("aria-pressed", page === "settings" ? "true" : "false");
    R.player.hidden = page !== "sounds";        // like the app: the player belongs to Sounds
  }
  function build(version) {
    root = h("div", { class: "ob", tabindex: "-1", role: "application", "aria-label": "A working copy of Onion Board" });
    R.lc = {};
    theme(S.theme);
    var brand = h("button", { type: "button", class: "ob-brand", title: "Onion Board", onclick: function () {
      brand.classList.remove("wob"); void brand.offsetWidth; brand.classList.add("wob");
      if (site.play) site.play("squeak");
    } }, [h("span", { class: "logo mark" }, [icon("onion")]), h("div", null, [h("b", { text: "Onion Board" }), h("small", { text: "v" + version })])]);
    R.nav = h("nav", { class: "ob-nav" });
    [["sounds", "Sounds"], ["radio", "Radio"], ["apps", "Apps"], ["triggers", "Triggers"], ["voice", "Voice"], ["store", "Community"], ["setup", "Setup"]].forEach(function (n) {
      R.nav.appendChild(h("button", { type: "button", "data-p": n[0], title: n[1], "aria-current": n[0] === "sounds" ? "page" : "false", onclick: function () { go(n[0]); } },
        [icon(n[0] === "voice" ? "voice" : n[0]), h("span", { class: "t", text: n[1] })]));
    });
    R.live = h("button", { type: "button", class: "ob-live", title: "Others hear your sounds and mic: click to mute both", "aria-label": "Others hear me", onclick: function () { setLive(!S.live); } }, [icon("live")]);
    var stopB = h("button", { type: "button", class: "ob-stopall", title: "Stop all sounds", "aria-label": "Stop all sounds", onclick: stopAll }, [h("span", { class: "sq" })]);
    R.setBtn = h("button", { type: "button", title: "Settings", "aria-label": "Settings", "aria-pressed": "false", onclick: function () { go(S.page === "settings" ? "sounds" : "settings"); } }, [icon("settings")]);
    var fold = h("button", { type: "button", title: "Fold the sidebar", "aria-label": "Fold the sidebar", onclick: function () {
      S.rail = !S.rail; root.classList.toggle("rail", S.rail);
      fold.replaceChildren(icon(S.rail ? "panel_open" : "panel_close"));
    } }, [icon("panel_close")]);
    var side = h("aside", { class: "ob-side" }, [brand, R.nav,
      h("div", { class: "ob-dock" }, [h("div", { class: "ob-pair" }, [R.live, stopB])]),
      h("div", { class: "ob-bottom" }, [R.setBtn, h("button", { type: "button", title: "Bun's setup check", "aria-label": "Bun's setup check", onclick: function () { go("setup"); } }, [icon("bun")]), fold])]);
    R.toast = h("div", { class: "ob-toast", role: "status", "aria-live": "polite" });
    R.page = h("div", { class: "ob-page" });
    var main = R.main = h("div", { class: "ob-main" }, [R.page].concat(bars()));
    root.appendChild(side);
    root.appendChild(main);
    root.appendChild(R.toast);
    go("sounds");

    // its own hotkeys, while it has focus (in the app they work everywhere)
    root.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { if (R.pop && !R.menu && !root.querySelector(".ob-veil")) { var a = R.pop.anchor; closeLive(); a.focus({ preventScroll: true }); e.stopPropagation(); } else if (R.menu) { closeMenu(); e.stopPropagation(); } else if (root.classList.contains("full")) full(false); return; }
      var tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "select" || tag === "textarea" || e.repeat || root.querySelector(".ob-veil")) return;
      var k = (e.ctrlKey ? "Ctrl+" : "") + (e.altKey ? "Alt+" : "") + (e.shiftKey ? "Shift+" : "") + (e.key.length === 1 ? e.key.toUpperCase() : e.key);
      var p = PADS.filter(function (x) { return x.key && x.key === k; })[0];
      if (p) { e.preventDefault(); start(p); }
    });
    document.addEventListener("pointerdown", function (e) {
      if (R.menu && !R.menu.contains(e.target)) closeMenu();
      // Live controls: a click outside closes it (its own button toggles it)
      if (R.pop && !R.pop.el.contains(e.target) && !R.pop.anchor.contains(e.target) && !(R.toast && R.toast.contains(e.target))) closeLive();
    }, true);
    root.addEventListener("scroll", closeMenu, true);
    // Escape with the focus outside the board (a button Live controls just redrew): still closes it
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && R.pop && !R.menu && !root.querySelector(".ob-veil")) closeLive(); });
    if ("ResizeObserver" in window) new ResizeObserver(function () {
      root.classList.toggle("narrow", root.offsetWidth <= 600);
    }).observe(root);
    return root;
  }
  function full(on) {
    root.classList.toggle("full", on);
    document.body.classList.toggle("ob-locked", on);
    if (on) {
      R.unfull = h("button", { type: "button", class: "ob-unfull", text: "Exit full screen (Esc)", onclick: function () { full(false); } });
      document.body.appendChild(R.unfull);
      did("full");
    } else if (R.unfull) { R.unfull.remove(); R.unfull = null; }
    root.focus({ preventScroll: true });
  }

  window.OnionBoardDemo = {
    mount: function (box) {
      var frame = box.querySelector(".frame");
      if (!frame || frame.classList.contains("live")) return;
      var lookToTheme = { dark: "Dark", light: "Light", ocean: "Ocean", hacker: "Hacker", synthwave: "Synthwave", "blood-moon": "Blood Moon" };
      S.theme = lookToTheme[document.documentElement.dataset.look] || "Dark";
      fetch("release.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }).then(function (r) {
        var v = /^[\w.\-]+$/.test(r.version || "") ? r.version : "2";
        var el = build(v);
        var chrome = h("div", { class: "ob-chrome" }, [
          h("span", { text: "A working copy of the app, right here. Click, right-click, drop in your own sounds." }),
          h("button", { type: "button", onclick: function () { full(true); } }, ["⛶ Full screen"])
        ]);
        frame.classList.add("live");
        box.classList.add("live");
        frame.insertBefore(el, frame.firstChild);
        box.insertBefore(chrome, frame);
        var sub = box.parentNode.querySelector(".sub");
        if (sub) sub.textContent = "Click a pad, or hit its key. The bits that need Windows tell you so.";
      });
    }
  };
})();
