// The clickable Onion Board on the home page: the app's own layout, icons, themes and
// Settings texts (board-demo-data.js), styled by board-demo.css. Pads, tabs, search,
// hotkeys, sorting, pad size, the player and the themes all work. Whatever needs Windows
// (your mic, links, radio, the voice changer...) says so and points to the download.
(function () {
  "use strict";
  var D = window.ONION_BOARD_DATA, site = window.onionSite || {};
  if (!D) return;
  // a few line icons the app paints that the data has no copy of yet
  var EXTRA = {
    globe: '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/></g>',
    chev: '<path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
    chevd: '<path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
    grid: '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/></g>'
  };
  Object.keys(EXTRA).forEach(function (k) { if (!D.icons[k]) D.icons[k] = EXTRA[k]; });
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
  function recBtn(cls, onclick) {
    var b = btn("rec " + (cls || ""), "Record", null, onclick);
    b.insertBefore(h("span", { class: "dotr" }), b.firstChild);
    return b;
  }
  function dd(b) { b.appendChild(icon("chevd", "dd")); return b; }
  // the app's mark (ui/kit/logo.py paint_logo): a gradient squircle, a soft highlight on
  // top, the white onion with its sprout, one layer in the gradient, and roots
  function logoMark() {
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 100 100"); s.setAttribute("class", "i"); s.setAttribute("aria-hidden", "true");
    s.innerHTML = '<defs><linearGradient id="ob-lg1" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="100" y2="100">' +
      '<stop offset="0" style="stop-color:var(--accent)"/><stop offset="1" style="stop-color:var(--accent2)"/></linearGradient>' +
      '<linearGradient id="ob-lg2" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="60"><stop offset="0" stop-color="#fff" stop-opacity=".235"/>' +
      '<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>' +
      '<rect x="4" y="4" width="92" height="92" rx="26" fill="url(#ob-lg1)"/><rect x="4" y="4" width="92" height="92" rx="26" fill="url(#ob-lg2)"/>' +
      '<g style="color:var(--logo_fg)"><path d="M50,29 C50,20 46,15 38,12 M50,27 C51,19 55,14 60,10" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>' +
      '<path d="M50,27 C57.25,36 79,42 79,59 C79,74 65.95,81 50,81 C34.05,81 21,74 21,59 C21,42 42.75,36 50,27 Z" fill="currentColor"/>' +
      '<path d="M50,27 C53.25,36 63,42 63,59 C63,74 57.15,81 50,81 C42.85,81 37,74 37,59 C37,42 46.75,36 50,27 Z" fill="none" stroke="url(#ob-lg1)" stroke-width="3.2" stroke-linecap="round"/>' +
      '<path d="M46.4,81 L44,87 M50,81 L50,87 M53.6,81 L56,87" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></g>';
    return h("span", { class: "logo mark" }, [s]);
  }
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
    live: true, mic: 1, theme: "Dark", textured: true, rail: false, src: "youtube", removed: [], last: null,
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
    R.seek.classList.toggle("idle", !it);
  }

  // ------------------------------------------------------------------ the root
  var R = {}, root;
  function theme(name) {
    var t = D.themes[name] || D.themes.Dark;
    S.theme = D.themes[name] ? name : "Dark";
    Object.keys(t).forEach(function (k) { root.style.setProperty("--" + k, t[k]); });
    // Textured, as in the app: the theme's own pattern on the bars and cards (tiles from
    // scripts/pictures/demo_textures.py) and a soft glow of its accents behind them
    root.style.setProperty("--tex", t.tex || "none");
    var k = light(t.bg) ? 0.55 : 1;
    root.style.setProperty("--glow1", rgba(t.accent, 0.22 * k));
    root.style.setProperty("--glow2", rgba(t.accent2, 0.14 * k));
    root.style.setProperty("--glow3", rgba(t.accent, 0.07 * k));
    var lum = (luma(t.accent) + luma(t.accent2)) / 2;
    root.style.setProperty("--logo_fg", lum > 165 ? "#0b1a10" : "#fff");
    root.classList.toggle("tex", S.textured);
    if (S.page === "sounds" && R.grid) drawGrid();   // (the pads' text follows the theme)
    root.classList.toggle("lantern", t.logo === "lantern");   // Halloween carves the logo into a jack-o'-lantern
    Array.prototype.forEach.call(root.querySelectorAll(".ob-theme"), function (b) { b.setAttribute("aria-pressed", b.dataset.name === S.theme ? "true" : "false"); });
    if (R.repaint) R.repaint();
  }

  function rgb(c) { c = c.replace("#", ""); return [0, 2, 4].map(function (i) { return parseInt(c.substr(i, 2), 16); }); }
  function rgba(c, a) { return "rgba(" + rgb(c).join(",") + "," + a.toFixed(3) + ")"; }
  function luma(c) { var v = rgb(c); return 0.299 * v[0] + 0.587 * v[1] + 0.114 * v[2]; }
  function light(c) { var v = rgb(c); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2] > 128; }

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
  var SETUPS = [{ name: "Deep demon", voice: "Demon" }, { name: "Tiny robot", voice: "Robot" }];   // the Voice tab's My voice combos
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
    s += '<text x="' + cx + '" y="' + (cy + 24) + '" text-anchor="middle" style="font-size:15px;font-weight:600;fill:var(--text_hi)">' +
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
      // My voice combos: the Voice tab's saved voices, on everything here
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
      el.appendChild(h("div", { class: "lsetups" }, [h("b", { text: "My voice combos" }), chips]));
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
  // a pad fades from its colour to the theme's tile colour: its name (at the top) and
  // its key and length (at the foot) each take white or near-black, whichever reads
  // better there, so they pass 4.5:1 on every colour in every theme
  function mixHex(a, b, t) { var x = rgb(a), y = rgb(b); return "#" + x.map(function (v, i) { return ("0" + Math.round(v + (y[i] - v) * t).toString(16)).slice(-2); }).join(""); }
  function relLum(c) { return rgb(c).map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }).reduce(function (s, v, i) { return s + v * [0.2126, 0.7152, 0.0722][i]; }, 0); }
  function contrast(a, b) { var x = relLum(a), y = relLum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function inkOn(bg) { return contrast("#ffffff", bg) >= contrast("#000000", bg) ? "#ffffff" : "#000000"; }
  function padInk(c) {
    var t = (D.themes[S.theme] || D.themes.Dark).tile || "#1e1e24";
    var foot = mixHex(t, c, 0.28), top = mixHex(c, foot, 0.15);
    var nm = inkOn(top), sub = inkOn(foot);
    var badge = sub === "#ffffff" ? mixHex(foot, "#000000", 0.45) : mixHex(foot, "#ffffff", 0.6);
    return "--nm:" + nm + ";--sub:" + sub + ";--badge:" + badge + ";--sh:" + (nm === "#ffffff" ? "rgba(0,0,0,.55)" : "rgba(255,255,255,.35)") +
      ";--subsh:" + (sub === "#ffffff" ? "rgba(0,0,0,.7)" : "rgba(255,255,255,.4)");
  }
  function drawGrid() {
    var g = R.grid;
    g.replaceChildren();
    g.classList.toggle("list", S.view === "list");
    g.style.setProperty("--pad", S.pad + "px");
    var list = shown();
    list.forEach(function (p) {
      var el = h("button", {
        type: "button", class: "ob-pad", "data-id": p.id, style: "--c:" + p.c + ";" + padInk(p.c), draggable: S.sort === "mine" && !S.q ? "true" : null,
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
        h("span", { class: "len" }, [p.linked ? icon("link") : null, fmt(p.len || 1)]),
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

  // Cards or a list: two icon buttons side by side, the one in use lit (panel.ViewToggle)
  function viewToggle(isList, set) {
    var box = h("div", { class: "ob-views" });
    function paint() { box.children[0].setAttribute("aria-pressed", isList() ? "false" : "true"); box.children[1].setAttribute("aria-pressed", isList() ? "true" : "false"); }
    box.append(h("button", { type: "button", "aria-label": "Show as cards", title: "Show as cards", onclick: function () { set(false); paint(); } }, [icon("sounds", "s")]),
      h("button", { type: "button", "aria-label": "Show as a list", title: "Show as a list", onclick: function () { set(true); paint(); } }, [icon("list", "s")]));
    paint();
    return box;
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
    var srcBtn = dd(h("button", { type: "button", class: "btn flat", "aria-label": "Search online", title: "Where to search" }, [icon(S.src, "s"), h("span", { class: "t srcw", text: "Search online" })]));
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
      h("div", { class: "ob-bar" }, [add, h("label", { class: "field ob-find" }, [icon("search", "s"), search]), srcBtn,
        h("span", { class: "ob-sep ob-hide-m" }), lib, h("span", { class: "ob-sep ob-hide-s" }), sort,
        viewToggle(function () { return S.view === "list"; }, function (l) { S.view = l ? "list" : "pads"; drawGrid(); }),
        h("span", { class: "hint ob-hide-m ob-cslbl", style: "white-space:nowrap;color:var(--text)", text: "Card size" }), h("div", { class: "ob-hide-m ob-csz" }, [size])]),
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
    R.seek = h("input", { type: "range", min: "0", max: "1000", value: "0", class: "ob-seek idle", "aria-label": "Position" });
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
    var vol = h("input", { type: "range", min: "0", max: "300", value: String(S.vol * 100), "aria-label": "Sounds for others" });
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
      h("span", { class: "ob-hide-s", text: "Sounds for others", style: "white-space:nowrap" }), h("div", { class: "ob-hide-s", style: "width:90px;display:flex" }, [vol]), h("span", { class: "ob-hide-s" }, [volPct]),
      h("label", { class: "chk ob-hide-m" }, [hear, h("span", { text: "Hear it myself" })])]);

    var others = h("input", { type: "checkbox", checked: S.live });
    others.addEventListener("change", function () { setLive(others.checked); });
    R.othersChk = others;
    var mic = h("input", { type: "range", min: "0", max: "300", value: "100", "aria-label": "Mic volume" });
    var micPct = h("span", { class: "pct", text: "100%" });
    setRange(mic);
    mic.addEventListener("input", function () { micPct.textContent = mic.value + "%"; setRange(mic); });
    R.meter = h("i");
    var phones = h("input", { type: "range", min: "0", max: "300", value: String(S.phones * 100), "aria-label": "Headphones volume" });
    var phPct = h("span", { class: "pct", text: Math.round(S.phones * 100) + "%" });
    setRange(phones);
    phones.addEventListener("input", function () { S.phones = phones.value / 100; phPct.textContent = phones.value + "%"; setRange(phones); regain(); });
    var mbar = h("div", { class: "ob-bar ob-mic" }, [
      h("div", { class: "grp vol" }, [icon("mic", "s"), h("span", { class: "ob-hide-s", text: "My mic" }), h("label", { class: "chk", title: "Others hear it" }, [others, h("span", { class: "ob-hide-m", text: "Others hear it" })]), h("i", { class: "ob-lvdot" }), mic, micPct]),
      h("span", { class: "ob-sep sep2" }),
      h("div", { class: "grp lv" }, [icon("live", "s"), h("span", { class: "lbl2", text: "What others hear" }), h("span", { class: "ob-meter" }, [R.meter]),
        (function () { var b = btn("hear ob-hide-m", "Hear what they hear", "ear", function () { tryIt("Listening to what your friends hear"); }); b.appendChild(h("span", { class: "ts", text: "Listen" })); return b; })()]),
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
    R.live.lastChild.textContent = on ? "On" : "Muted";
    R.live.title = on ? "Others hear your sounds and mic: click to mute both" : "Muted for others: click to send again";
    if (!toldLive) { toldLive = true; toast(on ? "Others hear you again" : "Muted for others", "In the app this cuts your sounds and mic from Discord or your game at once. The meter shows what they'd hear."); }
    tick();
  }

  // ------------------------------------------------------------------ Radio
  // The Radio tab (ui/radiopanel.py): the app's flat world map (ui/flatmap.py, the same
  // outlines) with a dot per station, and the list beside it. Made-up stations: nothing
  // streams here, clicking one shows what the app does and points to the download.
  var CITIES = [
    ["US", "United States", "New York", 40.7, -74, ["Pop", "Hip-hop", "News & Talk"]], ["US", "United States", "Los Angeles", 34.1, -118.2, ["Hip-hop", "Pop", "Chill"]],
    ["US", "United States", "Nashville", 36.2, -86.8, ["Country & Folk", "Rock"]], ["US", "United States", "Chicago", 41.9, -87.6, ["Jazz & Soul", "Dance"]],
    ["US", "United States", "Seattle", 47.6, -122.3, ["Rock", "Chill"]], ["US", "United States", "Miami", 25.8, -80.2, ["Latin", "Dance"]],
    ["US", "United States", "New Orleans", 30, -90.1, ["Jazz & Soul"]], ["US", "United States", "Denver", 39.7, -105, ["Chill", "Rock"]],
    ["CA", "Canada", "Toronto", 43.7, -79.4, ["Pop", "Classical"]], ["CA", "Canada", "Montréal", 45.5, -73.6, ["Jazz & Soul", "News & Talk"]],
    ["CA", "Canada", "Vancouver", 49.3, -123.1, ["Chill", "Rock"]], ["MX", "Mexico", "Mexico City", 19.4, -99.1, ["Latin", "Pop"]],
    ["JM", "Jamaica", "Kingston", 18, -76.8, ["Reggae"]], ["CU", "Cuba", "Havana", 23.1, -82.4, ["Latin", "Jazz & Soul"]],
    ["BR", "Brazil", "São Paulo", -23.6, -46.6, ["Dance", "Latin"]], ["BR", "Brazil", "Rio de Janeiro", -22.9, -43.2, ["Latin", "Chill"]],
    ["AR", "Argentina", "Buenos Aires", -34.6, -58.4, ["Latin", "Rock"]], ["CO", "Colombia", "Bogotá", 4.7, -74.1, ["Latin", "Pop"]],
    ["CL", "Chile", "Santiago", -33.4, -70.7, ["Rock", "News & Talk"]], ["PE", "Peru", "Lima", -12, -77, ["Latin"]],
    ["GB", "United Kingdom", "London", 51.5, -0.1, ["Pop", "Dance", "News & Talk"]], ["GB", "United Kingdom", "Manchester", 53.5, -2.2, ["Rock", "Dance"]],
    ["IE", "Ireland", "Dublin", 53.3, -6.3, ["Oldies", "Country & Folk"]], ["FR", "France", "Paris", 48.9, 2.4, ["Jazz & Soul", "Pop", "News & Talk"]],
    ["FR", "France", "Marseille", 43.3, 5.4, ["Hip-hop"]], ["ES", "Spain", "Madrid", 40.4, -3.7, ["Pop", "Latin"]],
    ["ES", "Spain", "Barcelona", 41.4, 2.2, ["Dance", "Chill"]], ["PT", "Portugal", "Lisbon", 38.7, -9.1, ["Country & Folk", "Chill"]],
    ["DE", "Germany", "Berlin", 52.5, 13.4, ["Dance", "Rock"]], ["DE", "Germany", "Munich", 48.1, 11.6, ["Rock", "Classical"]],
    ["NL", "Netherlands", "Amsterdam", 52.4, 4.9, ["Dance", "Pop"]], ["BE", "Belgium", "Brussels", 50.8, 4.4, ["News & Talk", "Pop"]],
    ["IT", "Italy", "Rome", 41.9, 12.5, ["Pop", "Oldies"]], ["IT", "Italy", "Milan", 45.5, 9.2, ["Jazz & Soul", "Dance"]],
    ["AT", "Austria", "Vienna", 48.2, 16.4, ["Classical"]], ["CH", "Switzerland", "Zürich", 47.4, 8.5, ["Chill", "Classical"]],
    ["SE", "Sweden", "Stockholm", 59.3, 18.1, ["Pop", "Dance"]], ["NO", "Norway", "Oslo", 59.9, 10.8, ["Rock"]],
    ["FI", "Finland", "Helsinki", 60.2, 24.9, ["Rock", "Classical"]], ["DK", "Denmark", "Copenhagen", 55.7, 12.6, ["Chill"]],
    ["PL", "Poland", "Warsaw", 52.2, 21, ["Pop", "Rock"]], ["CZ", "Czechia", "Prague", 50.1, 14.4, ["Classical", "Oldies"]],
    ["GR", "Greece", "Athens", 38, 23.7, ["Pop", "Country & Folk"]], ["TR", "Turkey", "Istanbul", 41, 29, ["Pop", "Country & Folk"]],
    ["UA", "Ukraine", "Kyiv", 50.5, 30.5, ["Pop", "News & Talk"]], ["RU", "Russia", "Moscow", 55.8, 37.6, ["Dance", "Rock"]],
    ["EG", "Egypt", "Cairo", 30, 31.2, ["Pop", "Country & Folk"]], ["MA", "Morocco", "Casablanca", 33.6, -7.6, ["Country & Folk"]],
    ["NG", "Nigeria", "Lagos", 6.5, 3.4, ["Hip-hop", "Dance"]], ["GH", "Ghana", "Accra", 5.6, -0.2, ["Hip-hop", "Reggae"]],
    ["KE", "Kenya", "Nairobi", -1.3, 36.8, ["Pop", "News & Talk"]], ["ZA", "South Africa", "Johannesburg", -26.2, 28, ["Dance", "Jazz & Soul"]],
    ["ZA", "South Africa", "Cape Town", -33.9, 18.4, ["Chill", "Rock"]], ["AE", "United Arab Emirates", "Dubai", 25.2, 55.3, ["Pop", "Chill"]],
    ["IN", "India", "Mumbai", 19.1, 72.9, ["Pop", "Dance"]], ["IN", "India", "Delhi", 28.6, 77.2, ["Pop", "News & Talk"]],
    ["TH", "Thailand", "Bangkok", 13.8, 100.5, ["Pop", "Chill"]], ["SG", "Singapore", "Singapore", 1.3, 103.8, ["Pop", "Jazz & Soul"]],
    ["ID", "Indonesia", "Jakarta", -6.2, 106.8, ["Pop", "Dance"]], ["PH", "Philippines", "Manila", 14.6, 121, ["Pop", "Oldies"]],
    ["VN", "Vietnam", "Hanoi", 21, 105.8, ["Pop"]], ["CN", "China", "Shanghai", 31.2, 121.5, ["Pop", "Classical"]],
    ["HK", "Hong Kong", "Hong Kong", 22.3, 114.2, ["Pop", "Jazz & Soul"]], ["TW", "Taiwan", "Taipei", 25, 121.6, ["Pop", "Chill"]],
    ["KR", "South Korea", "Seoul", 37.6, 127, ["Pop", "Hip-hop"]], ["JP", "Japan", "Tokyo", 35.7, 139.7, ["Pop", "Chill", "Rock"]],
    ["JP", "Japan", "Osaka", 34.7, 135.5, ["Jazz & Soul", "Dance"]], ["AU", "Australia", "Sydney", -33.9, 151.2, ["Rock", "Pop"]],
    ["AU", "Australia", "Melbourne", -37.8, 145, ["Dance", "Jazz & Soul"]], ["AU", "Australia", "Perth", -31.9, 115.9, ["Chill"]],
    ["NZ", "New Zealand", "Auckland", -36.8, 174.8, ["Reggae", "Rock"]], ["IS", "Iceland", "Reykjavík", 64.1, -21.9, ["Chill", "Rock"]]
  ];
  var KINDS = { "Pop": ["Hits", "Pop FM", "Top 40"], "Rock": ["Rock", "Classic Rock", "Alt Rock"], "Dance": ["Dance", "House Nation", "Club FM"],
    "Hip-hop": ["Hip-Hop", "Beats", "Rap Radio"], "Jazz & Soul": ["Jazz", "Soul Café", "Blue Note"], "Classical": ["Classical", "Symphony", "Opera"],
    "Chill": ["Lo-fi", "Chill", "Ambient"], "Oldies": ["Gold", "Oldies", "Retro"], "Country & Folk": ["Folk", "Country", "Roots"],
    "Latin": ["Latina", "Salsa", "Ritmo"], "Reggae": ["Reggae", "Roots Rock", "Dub"], "News & Talk": ["News", "Talk", "Info"] };
  var GENRES = ["Pop", "Rock", "Dance", "Hip-hop", "Jazz & Soul", "Classical", "Chill", "Oldies", "Country & Folk", "Latin", "Reggae", "News & Talk"];
  var STATIONS = [];
  CITIES.forEach(function (c, ci) {
    c[5].forEach(function (g, gi) {
      var k = KINDS[g][(ci + gi) % 3], city = c[2];
      STATIONS.push({ cc: c[0], country: c[1], city: city, lat: c[3] + (gi ? (gi % 2 ? 0.7 : -0.8) : 0), lon: c[4] + (gi ? (gi % 2 ? -0.9 : 1) : 0),
        genre: g, name: (ci + gi) % 2 ? city + " " + k : k + " " + city, kbps: [128, 320, 192, 128, 256][(ci * 3 + gi) % 5],
        tags: [g.toLowerCase().replace(" & ", ", "), city.toLowerCase()].join(", "), votes: (ci * 7919 + gi * 3571) % 9000 + (gi ? 0 : 2000) });
    });
  });
  STATIONS.sort(function (a, b) { return b.votes - a.votes; });
  // dot sizes, as the app works them out (flatmap._sizes): the most played tenth (with
  // enough plays) big on a log scale up to the most played, the rest all one small size
  var QUIET_R = 1.8, HOT_R = [3, 6], GLOW = 2.8, ROOM = 14, ROOM_GAP = 0.8;
  (function () {
    var floor = STATIONS[Math.floor(STATIONS.length * 0.1)].votes, top = STATIONS[0].votes;
    var lo = Math.log1p(floor), hi = Math.log1p(Math.max(floor, top));
    STATIONS.forEach(function (st) {
      st.hot = st.votes > floor;
      var q = Math.min(1, Math.max(0, (Math.log1p(st.votes) - lo) / Math.max(1e-9, hi - lo)));
      st.r = st.hot ? HOT_R[0] + (HOT_R[1] - HOT_R[0]) * Math.sqrt(q) : QUIET_R;
    });
  })();
  var radio = { list: "popular", genre: "All", q: "", country: "", quality: "", order: "", on: null, playing: false, stars: {}, recent: [],
                view: null, toldPlay: false };

  function hex2rgb(c) {
    c = String(c).trim();
    var m = /^#([0-9a-f]{3,8})$/i.exec(c);
    if (m) {
      var x = m[1].length < 6 ? m[1].replace(/./g, "$&$&") : m[1];
      return [parseInt(x.slice(0, 2), 16), parseInt(x.slice(2, 4), 16), parseInt(x.slice(4, 6), 16)];
    }
    m = /rgba?\(([^)]+)\)/.exec(c);
    return m ? m[1].split(",").slice(0, 3).map(Number) : [128, 128, 128];
  }
  function mix(a, b, t, alpha) {
    var x = hex2rgb(a), y = hex2rgb(b);
    return "rgba(" + [0, 1, 2].map(function (i) { return Math.round(x[i] + (y[i] - x[i]) * t); }).join(",") + "," + (alpha === undefined ? 1 : alpha) + ")";
  }
  function themeVar(n) { return root.style.getPropertyValue("--" + n) || "#888"; }

  // The flat map: drag (mouse or finger) moves it round the world, pinch or + / − zoom,
  // a dot is a station. Drawn on a canvas only when something changes.
  var LAT_TOP = 84, LAT_BOTTOM = -58;
  var landPath = null;
  function worldMap(onPick) {
    var box = h("div", { class: "ob-map", role: "application", "aria-label": "World map of radio stations: drag to move, + and − to zoom" });
    var cv = h("canvas", { "aria-hidden": "true" });
    var tip = h("div", { class: "ob-maptip", hidden: true });
    var V = radio.view || (radio.view = { cx: 12, cy: 22, zoom: 1 });
    var W = 0, H = 0, dpr = 1, want = 0, shown = [], hover = null, fly = 0;
    if (!landPath && D.map) landPath = new Path2D(D.map.d);
    function scale() { return Math.max(W / 360, H / (LAT_TOP - LAT_BOTTOM)) * V.zoom; }
    function clamp() {
      V.zoom = Math.min(40, Math.max(1, V.zoom));
      var s = scale(), half = H / s / 2;
      V.cx = ((V.cx + 180) % 360 + 360) % 360 - 180;
      var lo = LAT_BOTTOM + half, hi = LAT_TOP - half;
      V.cy = lo <= hi ? Math.min(hi, Math.max(lo, V.cy)) : (LAT_TOP + LAT_BOTTOM) / 2;
    }
    function at(st) {   // a dot's spot: its copy of the world nearest the middle
      var s = scale();
      return [W / 2 + ((st.lon - V.cx + 540) % 360 - 180) * s, H / 2 - (st.lat - V.cy) * s];
    }
    // each dot's place on screen: from the most played down, the first free spot on a
    // sunflower spiral round its own (up to ROOM px away), so none covers another
    function place() {
      var grow = Math.min(2, 1 + Math.log2(V.zoom) * 0.25), room = ROOM * grow, done = [];
      var step = 2 * QUIET_R * grow + ROOM_GAP;
      shown.slice().sort(function (a, b) { return b.votes - a.votes; }).forEach(function (st) {
        var o = at(st), r = st.r * grow, best = o;
        for (var j = 0, d = 0; d <= room; j++, d = step * Math.sqrt(j)) {
          var a = j * Math.PI * (3 - Math.sqrt(5)), x = o[0] + d * Math.cos(a), y = o[1] + d * Math.sin(a);
          if (done.every(function (q) { var lim = r + q.r * grow + ROOM_GAP; return (x - q._p[0]) * (x - q._p[0]) + (y - q._p[1]) * (y - q._p[1]) >= lim * lim; })) { best = [x, y]; break; }
        }
        st._p = best;
        done.push(st);
      });
    }
    function draw() {
      want = 0;
      if (!W || !H) return;
      clamp();
      var c = cv.getContext("2d"), s = scale(), bg = themeVar("bg"), text = themeVar("text"), accent = themeVar("accent");
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.fillStyle = mix(bg, accent, 0.06);
      c.fillRect(0, 0, W, H);
      if (landPath) {
        c.fillStyle = mix(bg, text, 0.14);
        c.strokeStyle = mix(bg, text, 0.3);
        c.lineWidth = 0.8 / (s / 10);
        c.lineJoin = "round";
        [-360, 0, 360].forEach(function (k) {
          var left = W / 2 + (k - 180 - V.cx) * s;
          if (left > W || left + 360 * s < 0) return;
          c.setTransform(dpr * s / 10, 0, 0, dpr * s / 10, dpr * (W / 2 + (k - V.cx) * s), dpr * (H / 2 + V.cy * s));
          c.fill(landPath, "evenodd");
          c.stroke(landPath);
        });
        c.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      // the stations, like the app: the most played tenth big and glowing (bigger the
      // more they're played), the rest small plain dots; crowded dots move apart
      var grow = Math.min(2, 1 + Math.log2(V.zoom) * 0.25);
      place();
      var vis = shown.filter(function (st) { var p = st._p; return p[0] > -24 && p[0] < W + 24 && p[1] > -24 && p[1] < H + 24; });
      var hotC = mix(accent, themeVar("text_hi"), 0.3);
      vis.forEach(function (st) {
        if (!st.hot) return;
        var g = st.r * grow * GLOW, rg = c.createRadialGradient(st._p[0], st._p[1], 0, st._p[0], st._p[1], g);
        rg.addColorStop(0, rgba(accent, 0.95)); rg.addColorStop(0.3, rgba(accent, 0.6));
        rg.addColorStop(0.6, rgba(accent, 0.2)); rg.addColorStop(1, rgba(accent, 0));
        c.fillStyle = rg;
        c.beginPath(); c.arc(st._p[0], st._p[1], g, 0, 7); c.fill();
      });
      [false, true].forEach(function (lit) {
        c.fillStyle = lit ? hotC : rgba(accent, 0.8);
        vis.forEach(function (st) {
          if (!!st.hot !== lit) return;
          c.beginPath();
          c.arc(st._p[0], st._p[1], st.r * grow * (st === hover ? 1.4 : 1), 0, 7);
          c.fill();
        });
      });
      if (radio.on && shown.indexOf(radio.on) >= 0) {
        var q = radio.on._p || at(radio.on);
        c.beginPath(); c.arc(q[0], q[1], 5.5 * grow, 0, 7); c.fillStyle = accent; c.fill();
        c.beginPath(); c.arc(q[0], q[1], 9.5 * grow, 0, 7); c.strokeStyle = mix(accent, "#ffffff", 0.3); c.lineWidth = 2; c.stroke();
      }
      // the country names last, haloed in the land's colour, where they fit
      var fs = Math.min(2.2, Math.max(1, 1 + 0.4 * Math.log2(Math.max(V.zoom, 1) / 1.5))) * 10.5;
      c.font = "600 " + fs.toFixed(1) + "px " + getComputedStyle(root).fontFamily;
      c.textAlign = "center"; c.textBaseline = "middle";
      c.lineJoin = "round"; c.lineWidth = 3;
      c.strokeStyle = mix(bg, text, 0.14); c.fillStyle = themeVar("text_hi");
      var taken = [];
      (D.map ? D.map.labels : []).slice().sort(function (a, b) { return b[3] - a[3]; }).forEach(function (l) {
        var x = W / 2 + ((l[1] - V.cx + 540) % 360 - 180) * s, y = H / 2 - (l[2] - V.cy) * s;
        if (x < -80 || x > W + 80 || y < -20 || y > H + 20) return;
        var w = c.measureText(l[0]).width;
        if (w > Math.max(l[3] * s * 1.25, 18)) return;
        var b = [x - w / 2 - 3, y - fs / 2 - 2, x + w / 2 + 3, y + fs / 2 + 2];
        if (taken.some(function (t) { return b[0] < t[2] && b[2] > t[0] && b[1] < t[3] && b[3] > t[1]; })) return;
        taken.push(b);
        c.strokeText(l[0], x, y);
        c.fillText(l[0], x, y);
      });
    }
    function redraw() { if (!want) want = requestAnimationFrame(draw); }
    function size() {
      var r = box.getBoundingClientRect();
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = Math.max(1, Math.round(r.width)); H = Math.max(1, Math.round(r.height));
      cv.width = W * dpr; cv.height = H * dpr;
      draw();
    }
    function nearest(x, y) {
      var best = null, bd = 12 * 12;
      shown.forEach(function (st) {
        var p = st._p || at(st), d = (p[0] - x) * (p[0] - x) + (p[1] - y) * (p[1] - y);
        if (d < bd) { bd = d; best = st; }
      });
      return best;
    }
    function zoomAt(f, x, y) {
      var s0 = scale();
      if (x === undefined) { x = W / 2; y = H / 2; }
      var lon = V.cx + (x - W / 2) / s0, lat = V.cy - (y - H / 2) / s0;
      V.zoom *= f; clamp();
      var s1 = scale();
      V.cx = lon - (x - W / 2) / s1; V.cy = lat + (y - H / 2) / s1;
      redraw();
    }
    function flyTo(st) {
      cancelAnimationFrame(fly);
      var a = { cx: V.cx, cy: V.cy, zoom: V.zoom }, z = Math.max(V.zoom, 3), t0 = performance.now();
      var dx = ((st.lon - a.cx + 540) % 360) - 180;
      (function step(now) {
        var t = Math.min(1, (now - t0) / 550), e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        V.cx = a.cx + dx * e; V.cy = a.cy + (st.lat - a.cy) * e; V.zoom = a.zoom + (z - a.zoom) * e;
        draw();
        if (t < 1) fly = requestAnimationFrame(step);
      })(t0);
    }
    // pointers: one drags, two pinch; a tap without moving picks the dot under it
    var pts = {}, moved = false, pinch = 0;
    function local(e) { var r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
    cv.addEventListener("pointerdown", function (e) {
      cv.setPointerCapture(e.pointerId);
      pts[e.pointerId] = local(e);
      moved = false; pinch = 0;
      cancelAnimationFrame(fly);
      box.classList.add("drag");
    });
    cv.addEventListener("pointermove", function (e) {
      var p = local(e), ids = Object.keys(pts);
      if (!pts[e.pointerId]) {      // hovering: the dot under the mouse, and its name
        var st = nearest(p[0], p[1]);
        if (st !== hover) { hover = st; redraw(); }
        cv.style.cursor = st ? "pointer" : "";
        if (st) {
          tip.hidden = false;
          tip.replaceChildren(h("b", { text: st.name }), h("span", { text: st.city + ", " + st.country + " · " + st.genre }));
          tip.style.left = Math.min(p[0] + 12, W - tip.offsetWidth - 6) + "px";
          tip.style.top = Math.max(6, p[1] - tip.offsetHeight - 10) + "px";
        } else tip.hidden = true;
        return;
      }
      tip.hidden = true;
      var o = pts[e.pointerId];
      if (ids.length >= 2) {
        var other = pts[ids[0] === String(e.pointerId) ? ids[1] : ids[0]];
        var d0 = Math.hypot(o[0] - other[0], o[1] - other[1]), d1 = Math.hypot(p[0] - other[0], p[1] - other[1]);
        if (d0 > 4) zoomAt(d1 / d0, (p[0] + other[0]) / 2, (p[1] + other[1]) / 2);
        pinch = 1; moved = true;
      } else {
        if (Math.abs(p[0] - o[0]) + Math.abs(p[1] - o[1]) > 1) moved = moved || Math.hypot(p[0] - o[0], p[1] - o[1]) > 4;
        var s = scale();
        V.cx -= (p[0] - o[0]) / s; V.cy += (p[1] - o[1]) / s;
        redraw();
      }
      pts[e.pointerId] = p;
    });
    function up(e) {
      if (!pts[e.pointerId]) return;
      var p = local(e);
      delete pts[e.pointerId];
      if (!Object.keys(pts).length) box.classList.remove("drag");
      if (!moved && !pinch && e.type === "pointerup") {
        var st = nearest(p[0], p[1]);
        if (st) { did("radio-dot"); onPick(st); }
      }
    }
    cv.addEventListener("pointerup", up);
    cv.addEventListener("pointercancel", up);
    cv.addEventListener("pointerleave", function () { if (hover) { hover = null; redraw(); } tip.hidden = true; });
    cv.addEventListener("dblclick", function (e) { var p = local(e); zoomAt(2, p[0], p[1]); });
    // the wheel zooms only with Ctrl: on the page it scrolls the page
    cv.addEventListener("wheel", function (e) {
      if (!e.ctrlKey) return;
      e.preventDefault();
      var p = local(e);
      zoomAt(e.deltaY < 0 ? 1.25 : 0.8, p[0], p[1]);
    }, { passive: false });
    var zin = h("button", { type: "button", class: "mapbtn", "aria-label": "Zoom in", title: "Zoom in", text: "+", onclick: function () { zoomAt(1.6); } });
    var zout = h("button", { type: "button", class: "mapbtn", "aria-label": "Zoom out", title: "Zoom out", text: "−", onclick: function () { zoomAt(1 / 1.6); } });
    box.append(cv, tip, h("div", { class: "zoom" }, [zin, zout]));
    if ("ResizeObserver" in window) new ResizeObserver(size).observe(box);
    else setTimeout(size, 0);
    return { el: box, redraw: redraw, flyTo: flyTo, setShown: function (list) { shown = list; redraw(); } };
  }

  function ccColour(cc) {
    var n = (cc.charCodeAt(0) * 31 + cc.charCodeAt(1) * 7) % 360;
    return "hsl(" + n + ",38%,42%)";
  }
  function radioPage() {
    var map, list = h("div", { class: "ob-list ob-scroll" }), count = h("div", { class: "cnt" }), help = h("div", { class: "hint ob-rhelp" });
    function matches(s) {
      var q = radio.q.trim().toLowerCase();
      if (radio.list === "favs" && !radio.stars[s.name]) return false;
      if (radio.list === "recent" && radio.recent.indexOf(s) < 0) return false;
      if (radio.genre !== "All" && s.genre !== radio.genre) return false;
      if (radio.country && s.country !== radio.country) return false;
      if (radio.quality && s.kbps < +radio.quality) return false;
      return !q || (s.name + " " + s.city + " " + s.country + " " + s.tags).toLowerCase().indexOf(q) >= 0;
    }
    function rows() {
      var r = STATIONS.filter(matches);
      if (radio.list === "recent") r.sort(function (a, b) { return radio.recent.indexOf(a) - radio.recent.indexOf(b); });
      if (radio.order === "az") r.sort(function (a, b) { return a.name.localeCompare(b.name); });
      if (radio.order === "kbps") r.sort(function (a, b) { return b.kbps - a.kbps; });
      return r;
    }
    function draw() {
      var r = rows();
      list.replaceChildren();
      r.forEach(function (s) {
        var row = h("button", { type: "button", class: "ob-st" + (radio.on === s ? " on" : ""), title: s.name + "\n" + s.city + ", " + s.country, onclick: function () { pick(s, false); } },
          [h("span", { class: "fl", style: "--cc:" + ccColour(s.cc), text: s.cc }),
           h("span", { class: "tx" }, [h("b", { text: s.name }), h("small", { text: s.country + " · " + s.tags })]),
           h("span", { class: "kbps" + (s.kbps >= 320 ? " hi" : ""), text: s.kbps + "k" })]);
        list.appendChild(row);
      });
      if (!r.length) list.appendChild(h("div", { class: "ob-none", text: radio.list === "favs" ? "Star a station (the star by Play) to keep it here." :
        radio.list === "recent" ? "Stations you play show up here." : "No stations match. Try other words." }));
      count.textContent = r.length + (r.length === 1 ? " station" : " stations");
      help.textContent = radio.list === "popular" && !radio.q ? r.length + " popular stations: click a dot on the map, or search. Click a station to play it."
        : r.length + " stations: click one to play it.";
      if (map) map.setShown(r);
    }
    function pick(s, fromMap) {
      radio.on = s; radio.playing = true;
      radio.recent = [s].concat(radio.recent.filter(function (x) { return x !== s; })).slice(0, 12);
      if (!fromMap) map.flyTo(s); else map.redraw();
      draw(); bar();
      var row = list.querySelector(".ob-st.on");
      if (row) row.scrollIntoView({ block: "nearest" });
      if (!radio.toldPlay) { radio.toldPlay = true; tryIt("Live radio from 30,000 stations round the world"); }
    }
    map = worldMap(function (s) { pick(s, true); });
    R.repaint = map.redraw;

    // the list's own controls: Popular / Favorites / Recent, the genres, the filters
    var seg = h("div", { class: "ob-seg" });
    seg._i = { popular: 0, favs: 1, recent: 2 };
    [["popular", "Popular", null], ["favs", "Favorites", "star"], ["recent", "Recent", null]].forEach(function (t) {
      seg.appendChild(btn("", t[1], t[2], function () {
        radio.list = t[0];
        Array.prototype.forEach.call(seg.children, function (b, i) { b.setAttribute("aria-pressed", i === seg._i[t[0]] ? "true" : "false"); });
        draw();
      }, { "aria-pressed": radio.list === t[0] ? "true" : "false" }));
    });
    var chips = h("div", { class: "chips" });
    ["All"].concat(GENRES).forEach(function (g) {
      chips.appendChild(h("button", { type: "button", class: "chip", "data-g": g, "aria-pressed": radio.genre === g ? "true" : "false", text: g, onclick: function () {
        radio.genre = g; Array.prototype.forEach.call(chips.children, function (c) { c.setAttribute("aria-pressed", c.dataset.g === g ? "true" : "false"); }); draw();
      } }));
    });
    function sel(label, opts, cur, fn) {
      var s = h("select", { "aria-label": label, onchange: function () { fn(s.value); draw(); } });
      opts.forEach(function (o) { s.appendChild(h("option", { value: o[0], text: o[1], selected: o[0] === cur })); });
      return h("span", { class: "sel" }, [s]);
    }
    var countries = STATIONS.map(function (s) { return s.country; }).filter(function (c, i, a) { return a.indexOf(c) === i; }).sort();
    var filters = h("div", { class: "filters" }, [
      sel("Country", [["", "All countries"]].concat(countries.map(function (c) { return [c, c]; })), radio.country, function (v) { radio.country = v; }),
      sel("Quality", [["", "Any quality"], ["192", "192k and up"], ["320", "320k only"]], radio.quality, function (v) { radio.quality = v; }),
      sel("Order", [["", "Default order"], ["az", "A to Z"], ["kbps", "Best quality first"]], radio.order, function (v) { radio.order = v; })]);
    var find = h("input", { type: "search", placeholder: "Search radio stations, genres, countries or cities…  (or click a dot on the map)", "aria-label": "Search stations", value: radio.q });
    find.addEventListener("input", function () { radio.q = find.value; draw(); });

    // the radio's own player bar
    var playB = btn("", "Play", "play", function () {
      if (!radio.on) return pick(rows()[0] || STATIONS[0], false);
      radio.playing = !radio.playing; bar();
      if (radio.playing) tryIt("Live radio from 30,000 stations round the world");
    });
    var shuffle = btn("icon", null, "shuffle", function () { var r = rows(); if (r.length) pick(r[Math.floor(Math.random() * r.length)], false); },
      { "aria-label": "A random station", title: "A random station" });
    var star = btn("icon", null, "star", function () {
      if (!radio.on) return toast("Pick a station first", "Then star it to keep it under Favorites.");
      radio.stars[radio.on.name] = !radio.stars[radio.on.name]; bar(); draw();
    }, { "aria-label": "Favorite", title: "Add to Favorites" });
    var now = h("div", { class: "rnow" });
    var vol = h("input", { type: "range", min: "0", max: "300", value: "100", "aria-label": "Radio volume" });
    var volPct = h("span", { class: "pct", text: "100%" });
    setRange(vol);
    vol.addEventListener("input", function () { volPct.textContent = vol.value + "%"; setRange(vol); });
    var hear = h("input", { type: "checkbox", checked: true });
    function bar() {
      playB.replaceChildren(icon(radio.playing ? "pause" : "play", "s"), h("span", { class: "t", text: radio.playing ? "Pause" : "Play" }));
      star.replaceChildren(icon(radio.on && radio.stars[radio.on.name] ? "star_filled" : "star", "s"));
      star.classList.toggle("lit", !!(radio.on && radio.stars[radio.on.name]));
      now.replaceChildren();
      if (!radio.on) now.appendChild(h("span", { class: "hint", text: "Nothing playing: click a station" }));
      else now.append(h("span", { class: "eq" + (radio.playing ? " on" : "") }, [h("i"), h("i"), h("i"), h("i")]),
        h("span", { class: "tx" }, [h("b", { text: radio.on.name }), h("small", { text: radio.on.city + ", " + radio.on.country + " · " + radio.on.kbps + "k" })]));
    }
    bar();
    draw();
    return h("div", { class: "ob-page" }, [
      h("div", { class: "ob-bar" }, [h("label", { class: "field", style: "flex:1" }, [icon("search", "s"), find]),
        btn("icon", null, "reload", function () { draw(); }, { "aria-label": "Load the stations again", title: "Load the stations again" })]),
      h("div", { class: "ob-radio" }, [map.el, h("div", { class: "ob-stations" }, [seg, chips, filters, count, list])]),
      help,
      h("div", { class: "ob-bar ob-rplayer" }, [playB, shuffle, star, btn("ob-hide-s", "Send to others", "live", function () { tryIt("Playing the radio into your call"); }),
        now, recBtn("ob-hide-s", function () { tryIt("Recording the radio into a pad"); }), liveBtn("radio"),
        h("span", { class: "ob-hide-m rvol" }, [icon("volume", "s"), vol, volPct]),
        h("label", { class: "chk ob-hide-m" }, [hear, h("span", { text: "Hear it myself" })])])
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
    var asize = h("input", { type: "range", min: "260", max: "460", value: String(S.appW || 340), "aria-label": "Card size" });
    setRange(asize);
    asize.addEventListener("input", function () { S.appW = +asize.value; setRange(asize); body.style.setProperty("--appw", S.appW + "px"); });
    if (S.appW) body.style.setProperty("--appw", S.appW + "px");
    body.classList.toggle("listed", !!S.appsList);
    body.appendChild(h("div", { class: "ob-apps-top" }, [liveBtn("apps"),
      btn("small", "Category", "plus", function () { tryIt("Sorting apps into your own categories"); }), h("span", { style: "flex:1" }),
      h("span", { class: "hint ob-hide-m", style: "white-space:nowrap;color:var(--text)", text: "Card size" }), h("div", { class: "ob-hide-m", style: "width:110px;display:flex" }, [asize]),
      viewToggle(function () { return !!S.appsList; }, function (l) { S.appsList = l; body.classList.toggle("listed", l); })]));
    Object.keys(grps).forEach(function (g) {
      body.appendChild(h("div", { class: "ob-sect", text: g }));
      var grid = h("div", { class: "ob-appgrid" });
      grps[g].forEach(function (a) {
        var lvl = h("i"); bars.push([lvl, a]);
        var vol = h("input", { type: "range", min: "0", max: "300", value: String(a.vol), "aria-label": a.name + " volume" });
        var pct = h("span", { class: "pct", text: a.vol + "%" });
        setRange(vol);
        vol.addEventListener("input", function () { a.vol = +vol.value; pct.textContent = a.vol + "%"; setRange(vol); });
        var card = h("div", { class: "ob-app" }, [
          h("div", { class: "atop" }, [icon("apps"), h("div", { class: "tx" }, [h("b", { text: a.name }), h("small", { text: a.sub })]),
            btn("icon ob-x", null, "close", function () { card.remove(); }, { "aria-label": "Hide " + a.name, title: "Hide " + a.name })]),
          h("div", { class: "lvl" }, [lvl]),
          h("div", { class: "row" }, [btn("", "Send", "live", function () { tryIt("Sending " + a.name + "'s sound to your friends"); }),
            btn("rec", "Record", null, function () { tryIt("Recording " + a.name + " into a pad"); }, { html: null }),
            btn("flat icon", null, "eye", function () { tryIt("Watching " + a.name + " for a picture"); }, { "aria-label": "Watch it" }),
            btn("flat icon", null, "scissors", function () { tryIt("Cutting a clip of " + a.name + "'s last 30 seconds"); }, { "aria-label": "Save a clip", title: "Save a clip" })]),
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
  // The Triggers tab is Onion Watch inside the board (onionwatch/board.py): its own
  // Triggers / Log / Settings tabs, the trigger cards on the left and the one picked in
  // the editor. Start watching pretends a game showed a picture a moment later, so the
  // sound plays like it would.
  var TRIG = [
    { name: "Died", what: "YOU DIED", col: "#c0392b", on: true, when: "the picture shows up", pad: 3, keep: false, cat: "Boss fights", match: 80 },
    { name: "Boss beaten", what: "VICTORY", col: "#d4a017", on: true, when: "the picture shows up", pad: 6, keep: false, cat: "Boss fights", match: 80 },
    { name: "Headshot", what: "HEADSHOT", col: "#e67e22", on: false, when: "the picture shows up", pad: 2, keep: false, cat: "Uncategorised", match: 75 },
    { name: "Queue popped", what: "MATCH FOUND", col: "#2ecc71", on: true, when: "the picture shows up", pad: 10, keep: true, cat: "Uncategorised", match: 85 }
  ];
  var WHENS = ["the picture shows up", "the picture goes away", "an area changes", "an area stops changing", "a bar drops below"];
  var trig = { sel: 0, tab: "triggers", q: "", watching: false, timer: 0, log: [], more: false };
  function trigStatus(t) {
    var p = PADS.filter(function (x) { return x.id === t.pad; })[0];
    if (!p) return ["warn", "Pick the sound to play"];
    if (!t.on) return ["off", "Off"];
    return trig.watching ? ["ok", "Watching"] : ["", "Ready"];
  }
  function triggersPage() {
    var body = h("div", { class: "ob-wbody" });
    var tabs = h("div", { class: "ob-wtabs", role: "tablist" });
    function thumb(t, big) { return h("span", { class: "ob-tpic" + (big ? " big" : ""), style: "--tc:" + t.col, text: t.what }); }
    function drawTabs() {
      tabs.replaceChildren(h("img", { class: "wlogo", src: "demo/watch-logo.png", alt: "Onion Watch", width: "22", height: "22" }));
      [["triggers", "Triggers", "eye"], ["log", "Log", "history"], ["settings", "Settings", "settings"]].forEach(function (x) {
        var b = h("button", { type: "button", role: "tab", "aria-selected": trig.tab === x[0] ? "true" : "false", onclick: function () { trig.tab = x[0]; drawTabs(); drawBody(); } },
          [icon(x[2], "s"), h("span", { text: x[1] })]);
        tabs.appendChild(b);
      });
    }
    var list, detail;
    function drawList() {
      list.replaceChildren();
      var q = trig.q.trim().toLowerCase();
      TRIG.forEach(function (t, i) {
        if (q && t.name.toLowerCase().indexOf(q) < 0) return;
        var st = trigStatus(t);
        var sw = h("button", { type: "button", class: "sw", role: "switch", "aria-checked": t.on ? "true" : "false", "aria-label": t.name + " on", onclick: function (e) {
          e.stopPropagation(); t.on = !t.on; drawList(); if (i === trig.sel) drawDetail();
        } });
        list.appendChild(h("div", { class: "ob-trow" + (i === trig.sel ? " on" : "") + (t.fired ? " fired" : ""), role: "button", tabindex: "0",
          onclick: function () { trig.sel = i; drawList(); drawDetail(); },
          onkeydown: function (e) { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); trig.sel = i; drawList(); drawDetail(); } } },
          [thumb(t), h("span", { class: "tx" }, [h("b", { text: t.name }), h("small", null, [h("span", { class: "st " + st[0] }, [h("i"), h("span", { text: st[1] })]),
             h("span", { class: "snd", text: "♪ " + ((PADS.filter(function (p) { return p.id === t.pad; })[0] || { name: "Choose a sound" }).name) })])]),
           trig.more ? h("span", { class: "hint ob-hide-s", text: t.match + "%" }) : null, sw]));
      });
      if (!list.children.length) list.appendChild(h("div", { class: "ob-none", text: "No triggers called “" + trig.q + "”." }));
    }
    function sel(items, cur, fn, cls) {
      var s = h("select", { onchange: function () { fn(s.value); } });
      items.forEach(function (o) { s.appendChild(h("option", { text: o, value: o, selected: o === cur })); });
      return h("span", { class: "sel " + (cls || "") }, [s]);
    }
    function drawDetail() {
      var t = TRIG[trig.sel];
      if (!t) return detail.replaceChildren(h("div", { class: "ob-none", text: "Make a trigger: New trigger, then cut a picture out of your game." }));
      var st = trigStatus(t), pad = PADS.filter(function (p) { return p.id === t.pad; })[0];
      var sw = h("button", { type: "button", class: "sw", role: "switch", "aria-checked": t.on ? "true" : "false", "aria-label": "On", onclick: function () {
        t.on = !t.on; drawList(); drawDetail();
      } });
      var chip = pad ? h("span", { class: "ob-schip" }, [icon("volume", "s"), h("span", { text: pad.name }),
        h("button", { type: "button", "aria-label": "Take it off", title: "Take it off", onclick: function () { t.pad = 0; drawList(); drawDetail(); } }, [icon("close", "s")])])
        : h("span", { class: "hint warn", text: "No sound yet" });
      var addSound = btn("icon small", null, "plus", function (e) {
        menuAt(addSound, PADS.map(function (p) { return { t: p.name, tick: p.id === t.pad, fn: function () { t.pad = p.id; drawList(); drawDetail(); } }; }));
      }, { "aria-label": "Pick the sound", title: "Pick the sound" });
      var keep = h("input", { type: "checkbox", checked: t.keep });
      keep.addEventListener("change", function () { t.keep = keep.checked; });
      detail.replaceChildren(
        h("div", { class: "ob-thead" }, [thumb(t, true),
          h("button", { type: "button", class: "ob-tmore", "aria-label": "Add another picture", title: "Add another picture (it plays when any of them shows up)", onclick: function () { tryIt("Cutting another picture out of your game"); } }, [icon("plus", "s")]),
          h("div", { class: "tx" }, [
          h("input", { class: "tname", value: t.name, maxlength: "40", "aria-label": "Trigger's name", oninput: function (e) { t.name = e.target.value || "Trigger"; drawList(); } })]),
          h("span", { class: "rdy" }, [h("i", { class: st[0] }), h("span", { text: st[1] }), sw])]),
        h("hr"),
        h("div", { class: "wrow" }, [h("b", { text: "When" }), sel(WHENS, t.when, function (v) { t.when = v; drawDetail(); }, "acc"),
          h("b", { text: "in" }), sel(["Default (Screen 1)", "Screen 2", "Your game's window"], "Default (Screen 1)", function () {}, "acc")]),
        h("div", { class: "wrow" }, [h("b", { text: "Play" }), chip, addSound]),
        h("label", { class: "chk" }, [keep, h("span", { text: "Keep playing" })]),
        h("div", null, [btn("small", "Extra settings", "sliders", function () { tryIt("A trigger's extra settings (cooldown, hotkey, how often it looks)"); })]),
        h("div", { class: "ob-wfoot" }, [
          btn("acc", "Test", "play", function () { if (pad) start(pad); else toast("Pick the sound first", "Then Test plays it, like the trigger will."); }),
          icon("folder", "s"), sel(["Uncategorised", "Boss fights", "Ranked"], t.cat, function (v) { t.cat = v; }),
          btn("flat", "Duplicate", "copy", function () {
            var c = Object.assign({}, t, { name: t.name + " copy", fired: false });
            TRIG.splice(trig.sel + 1, 0, c); trig.sel++; drawList(); drawDetail();
          }),
          btn("flat", "Delete", "trash", function () { TRIG.splice(trig.sel, 1); trig.sel = Math.max(0, Math.min(trig.sel, TRIG.length - 1)); drawList(); drawDetail(); })])
      );
    }
    function drawTriggers() {
      list = h("div", { class: "ob-tlist ob-scroll" });
      detail = h("div", { class: "ob-tdetail ob-scroll" });
      var find = h("input", { type: "search", placeholder: "Search triggers", "aria-label": "Search triggers", value: trig.q });
      find.addEventListener("input", function () { trig.q = find.value; drawList(); });
      var more = h("input", { type: "checkbox", checked: trig.more });
      more.addEventListener("change", function () { trig.more = more.checked; drawList(); });
      body.append(
        h("div", { class: "ob-wtool" }, [
          btn("ob-newt", "New trigger", "plus", function () {
            TRIG.push({ name: "Trigger " + (TRIG.length + 1), what: "NEW", col: "#7f8c8d", on: false, when: "the picture shows up", pad: 0, keep: false, cat: "Uncategorised", match: 80 });
            trig.sel = TRIG.length - 1; drawList(); drawDetail();
            toast("Now cut its picture", "In the app you drag a box round the thing in your game to watch for: a word, a health bar, a pop-up.");
          }),
          h("label", { class: "field ob-wfind" }, [icon("search", "s"), find]),
          h("span", { class: "sp" }),
          sel(["List and editor", "Just the list", "Big pictures"], "List and editor", function () { tryIt("The other views of your triggers"); }, "ob-hide-s"),
          h("label", { class: "chk ob-hide-m" }, [more, h("span", { text: "Show more info" })])]),
        h("div", { class: "ob-trig" }, [list, detail]));
      drawList(); drawDetail();
    }
    function drawLog() {
      var box = h("div", { class: "ob-wlog ob-scroll" });
      if (!trig.log.length) box.appendChild(h("div", { class: "ob-none", text: "Nothing yet. Start watching, and what it saw and played shows up here." }));
      trig.log.forEach(function (l) {
        box.appendChild(h("div", { class: "ln" }, [h("span", { class: "tm", text: l[0] }), h("b", { text: l[1] }), h("span", { class: "hint", text: l[2] })]));
      });
      body.append(h("div", { class: "ob-wtool" }, [h("b", { text: "What it saw" }), h("span", { class: "sp" }),
        btn("small", "Clear", "trash", function () { trig.log = []; drawBody(); })]), box);
    }
    function drawSettings() {
      function chk(t, on) { var c = h("input", { type: "checkbox", checked: on, onchange: function () { tryIt("Onion Watch's settings"); } }); return h("label", { class: "chk" }, [c, h("span", { text: t })]); }
      body.append(h("div", { class: "ob-wset ob-scroll" }, [
        h("div", { class: "ob-scard2" }, [h("div", { class: "head" }, [icon("eye", "s"), h("span", { class: "t", text: "Watching" })]),
          chk("Start watching when Onion Board starts", false), chk("Only while a game is open", true), chk("Pause while I'm typing", true)]),
        h("div", { class: "ob-scard2" }, [h("div", { class: "head" }, [icon("volume", "s"), h("span", { class: "t", text: "Sounds" })]),
          chk("Play trigger sounds to my friends too", false), chk("One sound at a time", true)]),
        h("div", { class: "ob-scard2" }, [h("div", { class: "head" }, [icon("shield", "s"), h("span", { class: "t", text: "Only looks" })]),
          h("div", { class: "h", text: "Onion Watch only looks at your screen: it never clicks, types or reads your game's memory." })])]));
    }
    function drawBody() {
      body.replaceChildren();
      if (trig.tab === "log") drawLog(); else if (trig.tab === "settings") drawSettings(); else drawTriggers();
    }
    var watchB = btn("", "Start watching", "eye", toggleWatch);
    var nowP = h("span", { class: "ob-wnow" }, [icon("volume", "s"), h("span", { text: "Nothing playing" })]);
    function toggleWatch() {
      trig.watching = !trig.watching;
      clearTimeout(trig.timer);
      watchB.replaceChildren(icon(trig.watching ? "stop" : "eye", "s"), h("span", { class: "t", text: trig.watching ? "Stop watching" : "Start watching" }));
      watchB.classList.toggle("acc", trig.watching);
      if (trig.watching) {
        did("watch");
        toast("Watching… (pretend)", "Here a game “shows” one of your pictures in a moment. In the app Onion Watch looks at your real game.");
        var ready = TRIG.filter(function (t) { return t.on && PADS.some(function (p) { return p.id === t.pad; }); });
        trig.timer = setTimeout(function fire() {
          if (!trig.watching || !ready.length || !watchB.isConnected) { trig.watching = false; return; }
          var t = ready[Math.floor(Math.random() * ready.length)], p = PADS.filter(function (x) { return x.id === t.pad; })[0];
          if (!p) return;
          start(p);
          var d = new Date();
          trig.log.unshift([("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2) + ":" + ("0" + d.getSeconds()).slice(-2), t.name, "seen (" + (t.match + 12) + "% alike), played " + p.name]);
          nowP.replaceChildren(icon("volume", "s"), h("span", { text: p.name + " · " + t.name }));
          t.fired = true;
          if (trig.tab === "triggers" && list && list.isConnected) drawList(); else if (trig.tab === "log") drawBody();
          setTimeout(function () { t.fired = false; if (list && list.isConnected) drawList(); }, 1600);
          trig.timer = setTimeout(fire, 6000 + Math.random() * 4000);
        }, 2600);
      } else nowP.replaceChildren(icon("volume", "s"), h("span", { text: "Nothing playing" }));
      if (list && list.isConnected) { drawList(); drawDetail(); }
    }
    if (trig.watching) { trig.watching = false; clearTimeout(trig.timer); }
    drawTabs(); drawBody();
    return h("div", { class: "ob-page ob-watch" }, [tabs, body,
      h("div", { class: "ob-bar ob-wbar" }, [watchB, dd(btn("ob-hide-s", "More", "history", function () { trig.tab = "log"; drawTabs(); drawBody(); })),
        h("span", { class: "hint ob-hide-m", style: "color:var(--text)", text: "Look in" }), h("span", { class: "ob-hide-m" }, [sel(["Screen 1", "Screen 2", "Your game's window"], "Screen 1", function () {})]),
        btn("flat icon ob-hide-m", null, "settings", function () { tryIt("Onion Watch's settings: how often it looks, and how sure it must be"); }, { "aria-label": "Watch settings", title: "Watch settings" })]),
      h("div", { class: "ob-bar ob-wbar" }, [nowP, h("span", { class: "sp" }),
        btn("", "Chances", "sliders", function () { tryIt("Chances: how likely each trigger is to fire"); }),
        btn("", "Stop all", "stop", stopAll)])
    ]);
  }

  // ------------------------------------------------------------------ Voice
  // The Voice tab (ui/voicepanel.py): Say, its four parts (Voice changer, AI voices,
  // Languages, Add-ons), My voice combos over them, and the voice changer's cards in the app's
  // groups (ui/voicefxpanel.py VOICE_GROUPS). The voice picked shows in a bar under the
  // cards with Effects (what goes on top of any voice) and Edit voice (the full editor).
  var VGROUPS = [["funny", "Funny", ["Chipmunk", "High voice", "Hothead", "Singing monk", "Underwater", "Drunk", "Choir", "Goblin", "Fairy"]],
    ["scary", "Scary", ["Demon", "Dark lord", "Ghost", "Masked caller", "Haunted radio", "Zombie", "Evil twin", "Giant"]],
    ["scifi", "Robots & sci-fi", ["Robot", "Dalek", "Alien", "Talkbox", "Autotune", "Mecha", "Ship computer"]],
    ["disguise", "Disguise", ["Deep voice", "Male voice", "Anonymous", "Secret detective"]],
    ["places", "Radio & places", ["Walkie-talkie", "Old telephone", "Megaphone", "Stadium announcer", "Cave", "Podcast voice", "Pilot",
      "Drive-thru speaker", "Old film", "Cathedral"]],
    ["mine", "Mine", ["My own mix"]]];
  var AI_VOICES = [["bear", "Bear", "A big, deep voice."], ["duke", "Duke", "Older and gravelly."], ["brick", "Brick", "Gruff and grounded."],
    ["max", "Max", "An everyday guy."], ["riley", "Riley", "A young guy."], ["atlas", "Atlas", "A smooth, deep storyteller."],
    ["sarge", "Sarge", "Loud and barking."], ["river", "River", "Somewhere in between."], ["ivy", "Ivy", "A husky woman's voice."],
    ["sage", "Sage", "A calm, low woman's voice."], ["nova", "Nova", "A clear, soft woman's voice."], ["pixie", "Pixie", "Light and young-sounding."],
    ["nana", "Nana", "An older woman's voice."], ["zoe", "Zoe", "A young woman's voice."], ["onyx", "Onyx", "A very low woman's voice."],
    ["squeak", "Squeak", "A tiny cartoon voice."], ["bean", "Bean", "A little kid."], ["titan", "Titan", "A huge, rumbling voice."]];
  var ON_TOP = ["Rain", "Wind", "Engine hum", "Crowd", "Spaceship hum", "Crackling fire", "Robot", "Radio", "Echo", "Reverb"];
  var LANGS = ["English", "Spanish", "French", "German", "Japanese", "Korean", "Portuguese (Brazil)", "Italian", "Dutch", "Polish", "Turkish", "Chinese"];
  function voicePic(name) { return name === "My own mix" ? "custom" : name.toLowerCase().replace(/ /g, "-"); }
  var voiceTab = "changer", pickedVoice = null, voiceGroup = "", voiceFavs = { "Demon": true, "Robot": true }, voiceList = false,
      voiceOnTop = {}, voiceFold = {}, voiceSaid = [], voiceLang = "Spanish",
      cleanOn = false, cleanCog = false, cleanPreset = "normal", cleanLevel = "normal", voiceFind = "", voiceLight = false, voicesOn = false;
  var GROUP_ICONS = { "": "sounds", favs: "star_filled", funny: "laugh", scary: "ghost", scifi: "robot", disguise: "voice", places: "radio", mine: "mic" };
  // a card's big on/off, next to its name (voicetiles.py BigSwitch): ON or OFF written in it
  function bigSwitch(on, label, fn, words) {
    return h("button", { type: "button", class: "ob-big", role: "switch", "aria-checked": on ? "true" : "false", "aria-label": label, onclick: fn },
      [h("i"), words === false ? null : h("span", { text: on ? "ON" : "OFF" })]);
  }
  function voiceCount() { return pickedVoice ? 4 + Object.keys(voiceOnTop).length : Object.keys(voiceOnTop).length; }
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
      voiceSaid.unshift(v);
      say.value = "";
      if (voiceTab === "lang") drawBody();
      toast("Said it to you", "The app says it into your call, in 100+ voices and languages.");
    }
    say.addEventListener("keydown", function (e) { if (e.key === "Enter") speak(); });
    var tabs = h("div", { class: "ob-vtabs" });
    var setups = h("div", { class: "ob-setups" });
    var body = h("div", { class: "ob-vcard" });
    var picked = h("div", { class: "ob-picked" });
    var strip = h("div", { class: "ob-bar ob-vstrip" });
    function chipBtn(t, ic, fn) { return h("button", { type: "button", class: "chip ghost", onclick: fn }, [icon(ic, "s"), t]); }
    function drawAll() { drawTabs(); drawSetups(); drawBody(); drawPicked(); drawStrip(); }
    function drawTabs() {
      tabs.replaceChildren();
      [["clean", "Clean mic", "mic"], ["changer", "Voice changer", "voice"], ["ai", "AI voices", "wave"], ["lang", "Languages", "globe"], ["addons", "Add-ons", "puzzle"]].forEach(function (t) {
        var on = t[0] === "changer" ? !!pickedVoice : t[0] === "clean" && cleanOn;
        var b = btn(on && voiceTab !== t[0] ? "lit" : "", t[1], t[2], function () { voiceTab = t[0]; closeLive(); drawAll(); },
          { "aria-pressed": voiceTab === t[0] ? "true" : "false" });
        tabs.appendChild(b);
      });
    }
    function drawSetups() {     // My voice combos: under the tabs, whichever part is showing
      setups.replaceChildren(h("b", { text: "My voice combos" }));
      SETUPS.forEach(function (s) {
        setups.appendChild(h("button", { type: "button", class: "chip", "aria-pressed": pickedVoice === s.voice ? "true" : "false", title: s.voice + "\nRight-click for more",
          onclick: function () { pickedVoice = pickedVoice === s.voice ? null : s.voice; drawAll(); if (pickedVoice) tryIt("Turning on your “" + s.name + "” setup"); },
          oncontextmenu: function (e) {
            e.preventDefault();
            menu(e.clientX, e.clientY, [
              { t: "Use on my sounds", icon: "sounds", fn: function () { LIVE.sounds.setup = s.name; paintLive("sounds"); tryIt("Playing your sounds in your “" + s.name + "” voice"); } },
              { t: "Set a hotkey…", icon: "keyboard", fn: function () { tryIt("A hotkey for a setup"); } },
              { t: "Copy share code", icon: "copy", fn: function () { tryIt("Sharing a setup with a code"); } },
              "-",
              { t: "Delete", icon: "trash", fn: function () {
                SETUPS.splice(SETUPS.indexOf(s), 1);
                Object.keys(LIVE).forEach(function (k) { if (LIVE[k].setup === s.name) { LIVE[k].setup = ""; paintLive(k); } });
                drawSetups();
              } }]);
          } }, [h("img", { src: "demo/voices/" + voicePic(s.voice) + ".webp", alt: "" }), s.name]));
      });
      setups.appendChild(chipBtn("Save what's on", "plus", function () {
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
      setups.appendChild(chipBtn("Import a code", "download", function () { tryIt("Importing a voice someone shared as a code"); }));
      setups.appendChild(chipBtn("Share", "upload", function () { tryIt("Sharing a voice combo: to the store for everyone, or as a code for a friend"); }));
    }
    function head(ic, title, extra) {
      return h("div", { class: "hd" }, [h("span", { class: "ic" }, [icon(ic)]), h("b", { text: title })].concat(extra || [], [h("span", { class: "sp" })]));
    }
    function fold(key, label, kids) {
      var open = !!voiceFold[key];
      var b = h("button", { type: "button", class: "ob-fold", "aria-expanded": open ? "true" : "false", onclick: function () { voiceFold[key] = !open; drawBody(); } },
        [icon("chev"), h("span", { text: label })]);
      return [b].concat(open ? kids : []);
    }
    function pick(v) {
      pickedVoice = pickedVoice === v ? null : v;
      closeLive();
      drawAll();
      if (pickedVoice) toast("Voice changer: " + v, "In the app your mic sounds like this, live. Save it as a setup and Live controls plays your sounds in it too.", true);
    }
    function card(v) {
      var star = h("button", { type: "button", class: "star" + (voiceFavs[v] ? " on" : ""), "aria-label": voiceFavs[v] ? "Remove from favorites" : "Add to favorites",
        title: voiceFavs[v] ? "Remove from favorites" : "Add to favorites",
        onclick: function (e) { e.stopPropagation(); voiceFavs[v] = !voiceFavs[v]; drawBody(); } }, [icon(voiceFavs[v] ? "star_filled" : "star", "s")]);
      return h("div", { class: "ob-voice", role: "button", tabindex: "0", "aria-pressed": pickedVoice === v ? "true" : "false", onclick: function () { pick(v); },
        onkeydown: function (e) { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pick(v); } } },
        [h("img", { src: "demo/voices/" + voicePic(v) + ".webp", alt: "", loading: "lazy" }), h("span", { text: v }), star]);
    }
    function drawChanger() {
      var sw = bigSwitch(!!pickedVoice, "Voice changer on", function () { if (pickedVoice) { pickedVoice = null; drawAll(); } else pick("Demon"); });
      // which voices show (voice/groupbar.py): a dropdown of the groups and a search box
      var names = [["", "All"], ["favs", "Favorites"]].concat(VGROUPS.map(function (g) { return [g[0], g[1]]; }));
      var cur = names.filter(function (g) { return g[0] === voiceGroup; })[0] || names[0];
      var pickBtn = dd(btn("ob-vpick", cur[1], GROUP_ICONS[cur[0]], null, { title: "Which voices show", "aria-haspopup": "menu" }));
      pickBtn.addEventListener("click", function () {
        menuAt(pickBtn, names.map(function (g) {
          var n = g[0] === "" ? VGROUPS.reduce(function (s, x) { return s + x[2].length; }, 0) : g[0] === "favs" ? Object.keys(voiceFavs).filter(function (v) { return voiceFavs[v]; }).length
            : VGROUPS.filter(function (x) { return x[0] === g[0]; })[0][2].length;
          return { t: g[1] + "  ·  " + n, icon: GROUP_ICONS[g[0]], tick: voiceGroup === g[0], fn: function () { voiceGroup = g[0]; drawBody(); } };
        }));
      });
      var find = h("input", { type: "search", placeholder: "Search voices", "aria-label": "Search voices", value: voiceFind, maxlength: "40" });
      find.addEventListener("input", function () {
        voiceFind = find.value;
        var at = find.selectionStart;
        drawBody();
        var f2 = body.querySelector(".ob-vfind input");
        if (f2) { f2.focus(); f2.setSelectionRange(at, at); }
      });
      var views = h("div", { class: "ob-views" }, [
        h("button", { type: "button", "aria-pressed": voiceList ? "false" : "true", "aria-label": "Show as cards", title: "Show as cards", onclick: function () { voiceList = false; drawBody(); } }, [icon("sounds", "s")]),
        h("button", { type: "button", "aria-pressed": voiceList ? "true" : "false", "aria-label": "Show as a list", title: "Show as a list", onclick: function () { voiceList = true; drawBody(); } }, [icon("list", "s")])]);
      body.append(head("voice", "Voice changer", [sw]),
        h("p", { class: "hint", text: "Change your mic live for whoever you send sounds to (Discord, a game, OBS). Pick a voice to turn it on, then use Hear what they hear at the bottom to try it." }));
      body.appendChild(h("div", { class: "ob-vchips" }, [pickBtn, h("label", { class: "field ob-vfind" }, [icon("search", "s"), find]), views]));
      var q = voiceFind.trim().toLowerCase();
      function hit(v) { return !q || v.toLowerCase().indexOf(q) >= 0; }
      var grids = h("div", { class: "ob-vgroups" + (voiceList ? " list" : "") }), any = false;
      if (voiceGroup === "favs") {
        var favs = Object.keys(voiceFavs).filter(function (v) { return voiceFavs[v] && hit(v); });
        any = favs.length > 0;
        grids.appendChild(favs.length ? h("div", { class: "ob-voices" }, favs.map(card))
          : h("div", { class: "ob-none", text: q ? "No favorite voices match “" + voiceFind.trim() + "”." : "No favorites yet. Click the star in a voice's corner to keep it here." }));
      } else {
        VGROUPS.forEach(function (g) {
          if (voiceGroup && voiceGroup !== g[0]) return;
          var vs = g[2].filter(hit);
          if (!vs.length) return;
          any = true;
          if (!voiceGroup) grids.appendChild(h("div", { class: "ob-vgroup", text: g[1] }));
          grids.appendChild(h("div", { class: "ob-voices" }, vs.map(card)));
        });
        if (!any) grids.appendChild(h("div", { class: "ob-none", text: "No voices match “" + voiceFind.trim() + "”." }));
      }
      body.appendChild(grids);
    }
    function installBox(pic, text, label, what, folder) {
      return h("div", { class: "ob-install" }, [pic, h("div", null, [h("p", { class: "hint", text: text }),
        h("div", { class: "r" }, [btn("acc ob-glow", label, "plus", function () { tryIt(what); }),
          folder ? btn("flat icon", null, "folder", function () { tryIt(what); }, { "aria-label": "Open the folder", title: "Open the folder" }) : null])])]);
    }
    function drawAi() {
      body.append(head("wave", "AI voices", [bigSwitch(false, "AI voices on", function () { tryIt("AI voices: a one-time install first"); })]),
        h("p", { class: "hint", text: "Your words and tone, a different voice. Live on this PC." }),
        installBox(h("img", { class: "bun", src: "demo/ai/bun-robot.webp", alt: "" }), "AI voices need a one-time install first: about 90 MB (the voice model and its runtime).",
          "Install AI voices", "AI voices"));
      body.append.apply(body, fold("ai", "More options", [h("div", { class: "ob-aivs" }, AI_VOICES.map(function (v) {
        return h("button", { type: "button", onclick: function () { tryIt("Talking in " + v[1] + "'s voice"); } },
          [h("img", { src: "demo/ai/" + v[0] + ".webp", alt: "", loading: "lazy" }), h("span", null, [h("b", { text: v[1] }), h("small", { text: v[2] })])]);
      }))]));
    }
    function drawLang() {
      var s = h("select", { "aria-label": "Speak in", onchange: function () { voiceLang = s.value; tryIt("Speaking " + s.value + " in your call"); } });
      LANGS.forEach(function (l) { s.appendChild(h("option", { text: l, selected: l === voiceLang })); });
      body.append(head("globe", "Speak another language"),
        installBox(h("img", { class: "globe", src: "demo/globe.webp", alt: "" }), "Speaking another language needs speech recognition installed first (runs on this PC; what you say never leaves it).",
          "Install speech recognition", "Speaking another language", true));
      body.append.apply(body, fold("lang", "More options", [h("div", { class: "r" }, [h("span", { text: "Speak in" }), h("span", { class: "sel" }, [s])])]));
      body.append(h("b", { text: "What the voice said" }),
        voiceSaid.length ? h("div", { class: "ob-lines" }, voiceSaid.slice(0, 6).map(function (l) { return h("div", null, [h("small", { text: "You typed" }), l]); }))
          : h("div", { class: "hint", style: "padding:6px 12px", text: "Nothing yet. Lines show up here as they're spoken." }));
    }
    var ADDON_LANGS = ["Arabic", "Bulgarian", "Catalan", "Czech", "Danish", "German", "Greek", "Spanish", "Finnish", "Filipino", "French", "Hebrew", "Hindi",
      "Hungarian", "Indonesian", "Italian", "Japanese", "Korean", "Malay", "Norwegian", "Dutch", "Polish", "Portuguese (Brazil)", "Portuguese (Portugal)",
      "Romanian", "Russian", "Slovak", "Slovenian", "Swedish", "Thai", "Turkish", "Ukrainian", "Vietnamese", "Chinese", "Traditional Chinese"];
    function drawAddons() {
      function ln(name, ver, st) { return h("div", { class: "ln" }, [h("b", { text: name }), h("span", { class: "hint", text: " " + ver + " · " + st })]); }
      body.append(head("puzzle", "Add-ons"),
        h("div", { class: "ob-addons" }, [ln("AI voices", "0.2.0", "not set up yet"), ln("Live voice-to-speech", "0.4.0", "not set up yet: press Install speech recognition above"),
          ln("Retro effects", "0.2.0", "on"), h("div", { class: "ln" }, [h("b", { text: "Languages" }), h("span", { class: "hint", text: " · " + ADDON_LANGS.join(", ") + " can be downloaded under Speak in" })])]),
        h("div", { class: "r" }, [btn("", "Refresh", null, function () { tryIt("Add-ons"); }), btn("flat icon", null, "folder", function () { tryIt("Add-ons"); }, { "aria-label": "Open the folder" })]),
        h("b", { text: "Custom voices" }),
        h("p", { class: "hint", text: "Use a TTS server running on your PC (Kokoro, AllTalk, any OpenAI-style one) or drop voice packs (Piper) into the voices folder. They join the Voice list above." }),
        h("div", { class: "r" }, [btn("", "Add a voice server", "plus", function () { tryIt("Your own voice server"); }), btn("", "Open voices folder", null, function () { tryIt("Your own voice packs"); })]));
    }
    // Clean mic: noise out of your mic before your sounds are added (the app's cleanmicpanel.py)
    var CLEAN_PRESETS = { normal: ["Normal", "normal", "Normal: noise cleaned, and the sensitivity set by itself."],
      loud: ["Loud room", "strong", "Loud room: Strong cleaning and a stricter sensitivity, for loud fans, a TV or people talking nearby."],
      voice: ["Just my voice", "strong", "Just my voice: Strong cleaning, a strict sensitivity and your voice kept at one loudness. Quiet words can be cut: speak up."],
      quiet: ["Quiet room", "light", "Quiet room: Light cleaning, and your voice stays most natural."] };
    var CLEAN_LEVELS = { off: ["Off", "Off: no noise is taken out. Input volume, sensitivity and gain control still work."],
      light: ["Light", "Light: noise is turned well down, and your voice stays most natural."],
      normal: ["Normal", "Normal: fans, keyboards and a TV go. Uses about 5% of one CPU core."],
      strong: ["Strong", "Strong: nearly everything but your voice goes, even loud noise. Uses about twice Normal's CPU."] };
    function setClean(on) {
      cleanOn = on;
      drawTabs(); drawBody(); drawStrip();
      if (on) toast("Clean mic on", "In the app, fans, keyboards and other noise come out of your voice here, before your sounds are added. Discord's own noise suppression can stay off.", true);
    }
    function drawClean() {
      var sw = bigSwitch(cleanOn, "Clean mic on", function () { setClean(!cleanOn); });
      body.append(head("mic", "Clean mic", [sw]),
        h("p", { class: "hint", text: "Takes fans, keyboards and other background noise out of your mic while you talk. It runs on this PC and works with every app and every voice." }),
        h("div", { class: "r" }, [btn("", "Mic settings", "settings", function () { cleanCog = !cleanCog; drawBody(); },
          { "aria-pressed": cleanCog ? "true" : "false", title: "Input volume, sensitivity, noise suppression and gain control" })]));
      if (cleanCog) {
        function chips(list, cur, fn) {
          return h("div", { class: "chips" }, Object.keys(list).map(function (k) {
            return h("button", { type: "button", class: "chip", "aria-pressed": cur === k ? "true" : "false", text: list[k][0], onclick: function () { fn(k); } });
          }));
        }
        var vol = h("input", { type: "range", min: "0", max: "200", value: "100", "aria-label": "Input volume" });
        setRange(vol);
        vol.addEventListener("input", function () { setRange(vol); cleanPreset = "custom"; });
        body.appendChild(h("div", { class: "ob-cleanset" }, [
          h("b", { text: "Preset" }),
          chips(CLEAN_PRESETS, cleanPreset, function (k) { cleanPreset = k; cleanLevel = CLEAN_PRESETS[k][1]; drawBody(); }),
          h("p", { class: "hint", text: cleanPreset === "custom" ? "Custom: your own settings. Pick a preset to start from one again." : CLEAN_PRESETS[cleanPreset][2] }),
          h("b", { text: "Input volume" }), vol,
          h("b", { text: "Noise suppression" }),
          chips(CLEAN_LEVELS, cleanLevel, function (k) {
            cleanLevel = k; cleanPreset = "custom";
            Object.keys(CLEAN_PRESETS).forEach(function (p) { if (CLEAN_PRESETS[p][1] === k && p !== "loud" && p !== "voice") cleanPreset = p; });
            drawBody();
            if (k === "strong") tryIt("Strong cleaning: a one-time 50 MB download");
          }),
          h("p", { class: "hint", text: CLEAN_LEVELS[cleanLevel][1] })]));
      }
      var mic = h("span", { class: "ob-meter" }, [h("i")]), clean = h("span", { class: "ob-meter" }, [h("i")]);
      body.append(h("b", { text: "Right now" }),
        h("div", { class: "ob-cleanm" }, [h("span", { text: "Your mic" }), mic, h("span", { text: "Cleaned" }), clean]),
        h("b", { text: "Hear the difference" }),
        h("div", { class: "r" }, [btn("", "Record 5 seconds", "mic", function () { tryIt("Hear the difference: 5 seconds of your mic, as it was and cleaned"); },
            { title: "Talk with your usual noise around, then hear it as it was and cleaned." }),
          btn("", "Before", "play", null, { disabled: true, title: "Your mic as it was" }),
          btn("", "After", "play", null, { disabled: true, title: "Your mic cleaned" })]),
        h("p", { class: "hint", text: "Talk with your usual noise around, then play both." }));
      // a pretend mic: a fan's steady hiss, words on top; the cleaned bar keeps only the words
      var t = 0, tick = setInterval(function () {
        if (!mic.isConnected) return clearInterval(tick);
        t++;
        var talk = Math.max(0, Math.sin(t / 7) * Math.sin(t / 3.1)), noise = 0.28 + Math.random() * 0.06;
        mic.firstChild.style.transform = "scaleX(" + Math.min(1, noise + talk * 0.6).toFixed(3) + ")";
        var left = !cleanOn || cleanLevel === "off" ? 1 : cleanLevel === "light" ? 0.25 : 0;   // of the noise
        clean.firstChild.style.transform = "scaleX(" + Math.min(1, noise * left + talk * 0.6).toFixed(3) + ")";
      }, 60);
    }
    function drawBody() {
      body.replaceChildren();
      if (voiceTab === "clean") drawClean(); else if (voiceTab === "changer") drawChanger(); else if (voiceTab === "ai") drawAi(); else if (voiceTab === "lang") drawLang(); else drawAddons();
    }
    // the voice picked, pinned under the cards: Effects, Edit voice, Hear it
    function drawPicked() {
      picked.hidden = !pickedVoice || voiceTab !== "changer";
      if (picked.hidden) return picked.replaceChildren();
      var fx = btn("", "Effects", "sounds", function () { openEffects(fx); }, { "aria-haspopup": "dialog" });
      var n = voiceCount();
      picked.replaceChildren(h("img", { src: "demo/voices/" + voicePic(pickedVoice) + ".webp", alt: "" }), h("b", { text: pickedVoice }),
        h("div", { class: "pb" }, [fx, btn("", "Edit voice" + (n ? "  ·  " + n + " on" : ""), "sliders", editVoice),
          btn("", "Hear it", "headphones", function () { tryIt("Hearing a line said in " + pickedVoice); })]));
    }
    function openEffects(anchor) {
      if (R.pop && R.pop.anchor === anchor) return closeLive();
      closeLive(); closeMenu();
      var el = h("div", { class: "ob-lpop ob-fxpop", role: "dialog", "aria-label": "Effects" });
      function draw() {
        el.replaceChildren(h("b", { class: "tt", text: "Effects" }), h("div", { class: "hint", text: "On top of any voice: they stay when you pick another one." }),
          h("b", { text: "Add an effect" }),
          h("div", { class: "fxchips" }, ON_TOP.concat(["A sound from my board"]).map(function (n) {
            var on = !!voiceOnTop[n];
            return btn("", n, on ? "check" : "plus", function () {
              if (on) delete voiceOnTop[n]; else { voiceOnTop[n] = 1; tryIt("“" + n + "” on top of your voice"); }
              draw(); drawPicked();
            }, { "aria-pressed": on ? "true" : "false" });
          })),
          btn("flat", "Advanced: Edit voice", "sliders", function () { closeLive(); editVoice(); }));
        var box = root.getBoundingClientRect(), a = anchor.getBoundingClientRect();
        var x = Math.max(8, Math.min(a.left - box.left, box.width - el.offsetWidth - 8));
        var y = a.top - box.top - el.offsetHeight - 6;
        if (y < 8) y = a.bottom - box.top + 6;
        el.style.left = x + "px"; el.style.top = Math.max(8, y) + "px";
      }
      root.appendChild(el);
      R.pop = { el: el, anchor: anchor };
      anchor.setAttribute("aria-expanded", "true");
      draw();
      did("voice-effects");
    }
    // Edit voice: the full editor, in a window of its own in the app
    function editVoice() {
      function sl(name, v, lo, hi, unit, ends) {
        var r = h("input", { type: "range", min: String(lo), max: String(hi), value: String(v), "aria-label": name });
        var val = h("b", { class: "v" });
        function show() { val.textContent = (unit === " st" || unit === "" ) && +r.value > 0 ? "+" + r.value + unit : r.value + unit; setRange(r); }
        r.addEventListener("input", show);
        r.addEventListener("change", function () { tryIt("Building your own voice"); });
        show();
        return h("div", { class: "sl" }, [h("div", { class: "t" }, [h("span", { text: name }), val]), r, h("div", { class: "ends" }, [h("span", { text: ends[0] }), h("span", { text: ends[1] })])]);
      }
      function fxcard(ic, name, on, hint, sliders) {
        var sw = h("button", { type: "button", class: "sw", role: "switch", "aria-checked": on ? "true" : "false", "aria-label": name + " on",
          onclick: function () { sw.setAttribute("aria-checked", sw.getAttribute("aria-checked") === "true" ? "false" : "true"); c.classList.toggle("on"); } });
        var c = h("div", { class: "ob-fxcard" + (on ? " on" : "") }, [h("div", { class: "hd2" }, [icon(ic, "s"), h("b", { text: name }),
          on && sliders ? btn("flat small", "Reset", "reload", function () {}) : null, sw]), hint ? h("div", { class: "hint", text: hint }) : null,
          sliders ? h("div", { class: "sls" }, sliders) : null]);
        return c;
      }
      var deep = /Demon|Dark lord|Giant|Deep|Zombie|Monster/.test(pickedVoice || "");
      dialog("Edit voice", [
        h("div", { class: "ob-evtop" }, [btn("", "Randomize", "reload", function () { tryIt("Randomize: a new voice every click"); }),
          btn("", "Save as a voice", "plus", function () { tryIt("Saving your own voice"); }),
          btn("", "Copy share code", "copy", function () { tryIt("Sharing a voice as a code"); }),
          btn("", "Import a code", "plus", function () { tryIt("Importing a voice someone shared"); })]),
        h("div", { class: "hint", text: "71 ms delay" }),
        fxcard("mic", "Pitch & voice", true, "Higher or lower; a cartoon or a real-sounding person; a bigger or smaller throat; autotune.", [
          sl("Pitch", deep ? -6 : 4, -12, 12, " st", ["lower", "higher"]), sl("Natural sound", 100, 0, 100, "%", ["cartoon", "real person"]),
          sl("Voice size", deep ? 5 : -3, -10, 10, "", ["smaller", "bigger"]), sl("Autotune", 0, 0, 100, "%", ["off", "robotic"]),
          sl("Mix", 100, 0, 100, "%", ["", ""]), sl("Gap between voices", 100, 0, 100, "%", ["together", "echo"])]),
        h("b", { text: "All effects" }),
        h("div", { class: "hint", text: "Switch effects on and drag their sliders to build your own voice. Changing anything switches to “My own mix”; like it? Save it as a voice and it gets a button of its own." }),
        h("div", { class: "ob-fxgrid" }, [fxcard("music", "Harmony", false), fxcard("wave", "Monster growl", deep), fxcard("headphones", "Echo", !!voiceOnTop.Echo),
          fxcard("sliders", "Distortion", false), fxcard("phone", "Old phone", false), fxcard("live", "Radio", !!voiceOnTop.Radio)])
      ], [{ t: "Done", acc: true, fn: function () {} }]).el.classList.add("wide", "ob-editv");
      did("voice-edit");
    }
    function drawStrip() {      // the Voice tab's own bar: what's changing your mic, the Voices switch, your mic
      var items = [];
      if (cleanOn) items.push(h("button", { type: "button", class: "ob-vchip", title: "Clean mic takes background noise out of your mic. Click to turn it off.", onclick: function () { setClean(false); } }, [icon("mic", "s"), "Clean mic"]));
      if (pickedVoice) items.push(h("button", { type: "button", class: "ob-vchip", title: "Voice changer: " + pickedVoice + ". Click to turn it off.", onclick: function () { pickedVoice = null; voiceOnTop = {}; drawAll(); } },
        [h("img", { src: "demo/voices/" + voicePic(pickedVoice) + ".webp", alt: "" }), "Voice changer: " + pickedVoice]));
      if (!items.length) items.push(h("span", { class: "hint st", title: "Nothing is changing your mic voice." }, [icon("ear", "s"), h("span", { text: "Mic unchanged" })]));
      var on = !!(pickedVoice || cleanOn);
      strip.replaceChildren(h("div", { class: "row1" }, items),
        h("div", { class: "row2" }, [h("span", { class: "vlbl", text: "Voices" }),
          bigSwitch(on, "Voices on or off", function () {
            if (on) { pickedVoice = null; voiceOnTop = {}; cleanOn = false; drawAll(); } else tryIt("Voices ON: the voices you had on come back");
          }, false),
          btn("ob-recv", "Record", "record", function () { tryIt("Recording your voice as others hear it"); }, { title: "Record your voice as others hear it" }),
          btn("", "Reset", "reload", function () { pickedVoice = null; voiceOnTop = {}; cleanOn = false; drawAll(); }, { title: "Turn every voice off and forget them, for a fresh start" }),
          icon("mic", "s mic"), h("span", { class: "hint ob-hide-s", text: "No mic open" }), h("span", { class: "ob-meter" }, [h("i")])]));
    }
    drawAll();
    return h("div", { class: "ob-page" }, [
      h("div", { class: "ob-scroll ob-vscroll" }, [
        h("div", { class: "ob-bar ob-say" }, [icon("speech", "s"), h("label", { class: "field" }, [say]), btn("", "Say", null, speak),
          btn("ob-hide-s", "Save as sound", "plus", function () { tryIt("Saving a spoken line as a pad"); }),
          btn("", "Stop", null, function () { if (window.speechSynthesis) speechSynthesis.cancel(); })]),
        h("div", { class: "ob-vtabrow" }, [tabs, h("label", { class: "chk ob-light", title: "For slower PCs: the voices use less CPU. The voice changer skips hiss removal and its robot voices and echoes are a little simpler." },
          [h("input", { type: "checkbox", checked: voiceLight, onchange: function (e) { voiceLight = e.target.checked; } }), h("span", { text: "Use less CPU" })])]),
        h("hr", { class: "ob-vline" }), setups, body]),
      picked, strip
    ]);
  }

  // ------------------------------------------------------------------ Community (the store)
  // The Community tab (ui/storetab.py): sounds and voices people share, voted on. Bun in
  // his headphones over it, then a row per sound: its picture (an emoji on its category's
  // colour), play, who shared it, its category, when, the votes, add, report. Hear one or
  // add it to your pads for real; sharing and reporting need the app.
  var CATS = ["memes", "reactions", "games", "movies", "tv", "music", "sports", "viral", "pranks", "politics", "streamer", "esports", "podcast", "spooky"];
  var CAT_NAMES = { memes: "Memes", reactions: "Reactions", games: "Games", movies: "Movies", tv: "TV", music: "Music", sports: "Sports", viral: "Viral",
    pranks: "Pranks", politics: "Politics", streamer: "Streaming", esports: "Esports", podcast: "Podcast", spooky: "Spooky" };
  var STORE = [
    { sfx: "boom", name: "Vine boom (extra bass)", by: "by bassboi", tags: "meme, boom", up: 4210, down: 38, cat: "memes", art: "💥", days: 3 },
    { sfx: "horn", name: "MLG air horn", by: "by Onion Board", tags: "meme, horn", up: 3870, down: 52, cat: "memes", art: "📯", days: 41 },
    { sfx: "buzzer", name: "Wrong answer", by: "Shared by a player", tags: "game show", up: 2950, down: 21, cat: "reactions", art: "❌", days: 12 },
    { sfx: "trombone", name: "Sad trombone", by: "by Onion Board", tags: "fail, comedy", up: 2410, down: 17, cat: "reactions", art: "😢", days: 60 },
    { sfx: "rimshot", name: "Ba dum tss", by: "by jokester", tags: "drum, joke", up: 1980, down: 30, cat: "reactions", art: "🥁", days: 8 },
    { sfx: "coin", name: "Coin pickup", by: "Shared by a player", tags: "retro, game", up: 1630, down: 9, cat: "games", art: "🪙", days: 1 },
    { sfx: "laser", name: "Laser zap", by: "by pewpew", tags: "sci-fi", up: 1120, down: 14, cat: "games", art: "⚡", days: 19 },
    { sfx: "drop", name: "Bass drop", by: "by dj_onion", tags: "music, drop", up: 980, down: 22, cat: "music", art: "🔊", days: 5 },
    { sfx: "clap", name: "Crowd applause", by: "Shared by a player", tags: "crowd", up: 870, down: 4, cat: "sports", art: "👏", days: 27 },
    { sfx: "ring", name: "Stream alert ding", by: "by Onion Board", tags: "alert, stream", up: 640, down: 3, cat: "streamer", art: "🔔", days: 2 },
    { sfx: "squeak", name: "Tiny squeak", by: "Shared by a player", tags: "prank, mouse", up: 520, down: 11, cat: "pranks", art: "🐭", days: 6 },
    { sfx: "hoot", name: "Owl at night", by: "by Hoot", tags: "animal, spooky", up: 410, down: 2, cat: "spooky", art: "🦉", days: 14 }
  ];
  var SHARED_VOICES = [
    { name: "Raid boss", by: "by bassboi", kind: "Voice changer", pic: "dark-lord", up: 1320, down: 12, days: 4 },
    { name: "Space station AI", by: "Shared by a player", kind: "Voice changer", pic: "ship-computer", up: 990, down: 8, days: 9 },
    { name: "Radio DJ at 3am", by: "by dj_onion", kind: "A setup", pic: "podcast-voice", up: 760, down: 5, days: 2 },
    { name: "Grumpy goblin", by: "Shared by a player", kind: "Voice changer", pic: "goblin", up: 540, down: 9, days: 17 },
    { name: "Cathedral choir", by: "by Onion Board", kind: "A setup", pic: "choir", up: 380, down: 1, days: 30 }
  ];
  var store = { tab: "sounds", pick: "trending", kind: "", q: "", voted: {}, told: false, playing: "" };
  function catHue(cat) { return Math.round(CATS.indexOf(cat) * 360 / CATS.length + 12) % 360; }
  function ago(d) { return d <= 0 ? "today" : d === 1 ? "yesterday" : d < 14 ? d + " days ago" : d < 60 ? Math.round(d / 7) + " weeks ago" : Math.round(d / 30) + " months ago"; }
  function count(n) { return n >= 1000 ? (n / 1000).toFixed(1).replace(".0", "") + "k" : String(n); }
  function storePage() {
    var list = h("div", { class: "ob-store" });
    function vote(s, way) {
      var was = store.voted[s.name] || 0;
      store.voted[s.name] = was === way ? 0 : way;
      if (!store.told) { store.told = true; toast("Thanks for voting", "Here your vote stays on this page. In the app it counts for everyone, so the best sounds rise to the top."); }
      draw();
    }
    function voteBtns(s) {
      var v = store.voted[s.name] || 0;
      return [btn("vote", count(s.up + (v === 1 ? 1 : 0)), "like", function () { vote(s, 1); }, { title: "I like it", "aria-pressed": v === 1 ? "true" : "false" }),
        btn("vote", count(s.down + (v === -1 ? 1 : 0)), "dislike", function () { vote(s, -1); }, { title: "Not for me", "aria-pressed": v === -1 ? "true" : "false" })];
    }
    // one card: its picture, name and votes, who shared it, its category and when, then Play, Add and Report
    function cardEl(pic, name, meta, where, s, acts, report) {
      return h("div", { class: "ob-scard3" }, [pic,
        h("div", { class: "ob-ct" }, [h("b", { text: name, title: name })].concat(voteBtns(s))),
        h("div", { class: "ob-cm" }, [h("small", { class: "ob-meta", text: meta, title: meta }), h("small", { class: "ob-where", text: where })]),
        h("div", { class: "ob-ca" }, acts.concat([h("span", { class: "sp" }), report]))]);
    }
    function hot(s) { return s.up / Math.pow(s.days + 2, 0.8); }   // popular right now: votes, newer ones weighed up
    function trending(a, b) { return hot(b) - hot(a); }
    function order(rows) {
      if (store.pick === "new") rows.sort(function (a, b) { return a.days - b.days; });
      else if (store.pick === "top") rows.sort(function (a, b) { return b.up - a.up; });
      else rows.sort(trending);
      return rows;
    }
    function draw() {
      list.replaceChildren();
      var q = store.q.trim().toLowerCase();
      if (store.tab === "voices") {
        var vs = SHARED_VOICES.filter(function (v) { return (!store.kind || v.kind === store.kind) && (!q || (v.name + " " + v.kind).toLowerCase().indexOf(q) >= 0); });
        vs.sort(function (a, b) { return b.up - a.up; });
        vs.forEach(function (v) {
          list.appendChild(cardEl(h("img", { class: "tile", src: "demo/voices/" + v.pic + ".webp", alt: "" }), v.name, v.by, v.kind + " · " + ago(v.days), v,
            [btn("", "Hear", "headphones", function () { tryIt("Hearing a shared voice"); }, { title: "Hear a line in it (only you)" }),
              btn("", "Add", "plus", function () { tryIt("Adding a shared voice to your Voice tab"); }, { title: "Add it to your voices" })],
            btn("flat icon", null, "flag", function () { tryIt("Reporting a voice"); }, { "aria-label": "Report it", title: "Report it" })));
        });
        if (!vs.length) list.appendChild(h("div", { class: "ob-none", text: "Nothing matches. Try other words." }));
        return;
      }
      var cat = CATS.indexOf(store.pick) >= 0 ? store.pick : "";
      var rows = order(STORE.filter(function (s) { return (!cat || s.cat === cat) && (!q || (s.name + " " + s.tags).toLowerCase().indexOf(q) >= 0); }));
      rows.forEach(function (s) {
        var added = PADS.some(function (p) { return p.fromStore === s.name; });
        var on = store.playing === s.name;
        function hear() {
          if (site.play) site.play(s.sfx);
          did("store-play");
          store.playing = s.name; draw();
          setTimeout(function () { if (store.playing === s.name) { store.playing = ""; if (list.isConnected) draw(); } }, (LENS[s.sfx] || 1) * 1000 + 200);
        }
        var add = btn(added ? "done" : "", added ? "Added" : "Add", added ? "check" : "plus", function () {
          if (added) return go("sounds");
          PADS.push({ sfx: s.sfx, name: s.name, art: s.art, c: COLOURS[nextId % COLOURS.length], key: "", tabs: [], id: nextId++, len: LENS[s.sfx] || 1, plays: 0, fromStore: s.name });
          did("store-add");
          draw();
          toast("Added “" + s.name + "”", "It's on your Sounds tab now. Shared sounds are free for anyone to use (CC0).");
        }, { title: added ? "On your Sounds tab" : "Add it to your Sounds" });
        list.appendChild(cardEl(h("button", { type: "button", class: "tile", style: "--h:" + catHue(s.cat), "aria-label": "Hear " + s.name, title: "Hear it (only you)", onclick: hear }, [h("span", { text: s.art })]),
          s.name, s.by + " · " + s.tags, CAT_NAMES[s.cat] + " · " + ago(s.days), s,
          [btn(on ? "on" : "", "Play", "play", hear, { title: "Hear it (only you)" }), add],
          btn("flat icon", null, "flag", function () { tryIt("Reporting a sound"); }, { "aria-label": "Report this sound", title: "Report this sound" })));
      });
      if (!rows.length) list.appendChild(h("div", { class: "ob-none", text: "Nothing matches. Try other words." }));
    }
    var seg = h("div", { class: "ob-seg" });
    function drawSeg() {
      seg.replaceChildren();
      [["sounds", "Sounds", "sounds"], ["voices", "Voices", "voice"]].forEach(function (t) {
        seg.appendChild(btn("", t[1], t[2], function () {
          store.tab = t[0]; drawSeg(); drawPick();
          find.placeholder = t[0] === "voices" ? "Search voices" : "Search sounds";
          share.querySelector(".t").textContent = t[0] === "voices" ? "Share a voice" : "Share a sound"; draw();
        }, { "aria-pressed": store.tab === t[0] ? "true" : "false" }));
      });
    }
    var find = h("input", { type: "search", placeholder: store.tab === "voices" ? "Search voices" : "Search sounds", "aria-label": "Search the store", value: store.q });
    find.addEventListener("input", function () { store.q = find.value; draw(); });
    // the sounds: Trending, Most liked, Newest, then each category; the voices: each kind
    var cs = h("select", { "aria-label": "Order and category" });
    var pickIc = h("span", { class: "pic" });
    var catSel = h("span", { class: "sel withic" }, [pickIc, cs]);
    function drawPick() {
      cs.replaceChildren();
      if (store.tab === "voices") {
        [["", "All categories"], ["Voice changer", "Voice changer"], ["A setup", "A setup"]].forEach(function (c) { cs.appendChild(h("option", { value: c[0], text: c[1], selected: store.kind === c[0] })); });
        pickIc.replaceChildren(icon("grid", "s"));
        return;
      }
      [["trending", "Trending"], ["top", "Most liked"], ["new", "Newest"]].forEach(function (c) { cs.appendChild(h("option", { value: c[0], text: c[1], selected: store.pick === c[0] })); });
      cs.appendChild(h("option", { disabled: true, text: "──────────" }));
      CATS.forEach(function (c) { cs.appendChild(h("option", { value: c, text: CAT_NAMES[c], selected: store.pick === c })); });
      pickIc.replaceChildren(icon({ trending: "flame", top: "like", "new": "history" }[store.pick] || "grid", "s"));
    }
    cs.addEventListener("change", function () { if (store.tab === "voices") store.kind = cs.value; else store.pick = cs.value; drawPick(); draw(); });
    var share = btn("acc", store.tab === "voices" ? "Share a voice" : "Share a sound", "upload", function () { tryIt("Sharing your own " + (store.tab === "voices" ? "voice" : "sound") + " with everyone"); });
    drawSeg();
    drawPick();
    draw();
    var bun = document.getElementById("bun-icon") ? (function () {
      var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      s.setAttribute("viewBox", "-6 -10 112 140"); s.setAttribute("class", "bun"); s.setAttribute("aria-hidden", "true");
      s.innerHTML = '<use href="#bun-icon"/>';
      return s;
    })() : h("img", { class: "bun", src: "demo/ai/bun-robot.webp", alt: "" });
    return h("div", { class: "ob-page ob-scroll ob-storepg" }, [
      h("div", { class: "ob-shero" }, [
        h("div", { class: "top" }, [bun, h("div", { class: "tt" }, [
          h("div", { class: "ln1" }, [h("b", { text: "Community" }), h("span", { class: "ob-beta", text: "Beta", title: "The Community tab is new and still changing." })]),
          h("span", { class: "hint", text: "Sounds and voices players share, voted on by everyone: add them to your board or share your own" })])]),
        h("div", { class: "row" }, [seg, h("label", { class: "field" }, [icon("search", "s"), find]), catSel, share,
          btn("flat icon", null, "reload", function () { draw(); }, { "aria-label": "Refresh", title: "Refresh" })])]),
      list
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
    var lower = h("span", { class: "sel" }, [h("select", { "aria-label": "Lower my sounds" }, ["Off", "A little (-6 dB)", "Half (-12 dB)", "A lot (-20 dB)"].map(function (o) { return h("option", { text: o, selected: o === "Half (-12 dB)" }); }))]);
    return h("div", { class: "ob-page ob-scroll" }, [h("div", { class: "ob-setup" }, [
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("mic"), h("span", { text: "Your mic" }), h("span", { class: "ob-pill", text: "Connected" })]),
        h("div", { class: "ob-okbox" }, [h("div", { class: "l1" }, [h("span", { class: "ok", style: "display:flex;gap:8px;align-items:center;font-weight:500" }, [icon("check", "s"), "Your sounds go into your mic"]),
          h("span", { class: "hint", text: "Microphone (USB Audio Device)" })]),
          h("div", { class: "l1" }, [btn("flat small", "Change mic", null, function () { tryIt("Picking another mic"); }), btn("flat small", "Reinstall", null, function () { tryIt("Setting up your mic"); }), btn("flat small danger", "Remove", null, function () { tryIt("Setting up your mic"); })])]),
        h("b", { text: "Optional: other ways to send your sounds" }),
        h("div", { class: "ob-twocol" }, [
          h("div", null, [h("div", { class: "head" }, [icon("cable", "s"), h("span", { text: "Virtual cable" })]), h("p", { text: "No mic, or you'd rather Onion Board didn't touch yours? Use a free virtual cable instead: you pick it as the mic in Discord and games." }),
            btn("small", "Use the cable", "cable", function () { tryIt("Sending through a virtual cable"); })]),
          h("div", null, [h("div", { class: "head" }, [icon("sliders", "s"), h("span", { text: "Another device" })]), h("p", { text: "For streamers and mixers: send your sounds to Voicemeeter, OBS, a mixer or a capture card, or to nobody." }),
            btn("small", "Pick a device", "sliders", function () { tryIt("Sending to another device"); })])
        ])
      ]),
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("ear"), h("span", { text: "Who's listening" })]),
        h("div", { class: "hint", text: "Where people hear you: a game, a voice chat app, or a stream. Your sounds are shaped to come through clearly." }),
        modes, hint, chk("Send in mono (recommended)", true), chk("Keep my voice at one volume", true),
        h("div", { class: "r", style: "display:flex;align-items:center;gap:10px" }, [h("span", { text: "While I talk, lower my sounds:" }), lower]),
        chk("Mute my mic while a sound plays", false), chk("Put Discord back for talking on close", true)
      ]),
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("headphones"), h("span", { text: "Devices" })]),
        h("div", { class: "hint", text: "Already set up for you, only change these if something's wrong." }),
        h("div", { class: "ob-dev" }, [icon("headphones", "s"), h("span", { class: "lbl", text: "My headphones" }), devSel(1),
          icon("mic", "s"), h("span", { class: "lbl", text: "My mic" }), devSel(0),
          icon("live", "s"), h("span", { class: "lbl", text: "Send my sounds to" }), devSel(2),
          icon("live", "s"), h("span", { class: "lbl", text: "Also play on" }), h("div", null, [btn("small", "Add a device", "plus", function () { tryIt("Sending your sounds to a second device too"); })])]),
        h("div", { class: "hint" }, [h("span", { text: "Your sounds go straight into " }), h("b", { text: "My mic" }), h("span", { text: ", so Discord and games hear them through the mic they already use." })]),
        h("div", null, [btn("", "Re-scan devices", "reload", function () { tryIt("Finding your real devices"); })])
      ]),
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("sliders"), h("span", { text: "Equalizer and volume" })]),
        h("div", { class: "r", style: "display:flex;align-items:center;gap:10px" }, [chk("EQ on", false), h("span", { text: "for" }),
          h("span", { class: "sel" }, [h("select", { "aria-label": "EQ on" }, ["My voice", "My sounds", "Both"].map(function (o) { return h("option", { text: o }); }))])]),
        chk("Level volumes (all sounds equally loud)", true)
      ]),
      h("div", { class: "ob-scard" }, [
        h("div", { class: "head" }, [icon("speech"), h("span", { text: "Connect your chat" })]),
        h("div", { class: "hint", text: "Choose your app for the recommended microphone settings." }),
        h("div", { class: "ob-chatbtns" }, [btn("small", "Make it sound clean in Discord", "headphones", function () { tryIt("Bun showing you Discord's settings, step by step"); }),
          btn("small", "Set up game voice chat", null, function () { tryIt("Setting up a game's voice chat"); }),
          btn("small", "Zoom, Teams or a browser call", null, function () { tryIt("The settings for Zoom, Teams and browser calls"); }),
          btn("small", "Step-by-step guide", "check", function () { tryIt("The step-by-step setup guide"); })])
      ])
    ])]);
  }

  // ------------------------------------------------------------------ Settings
  // (the app's own pages and icons: settings.py SettingsDialog)
  var SET_PAGES = [["Audio", "audio", "volume"], ["Appearance", "appearance", "palette"], ["Hotkeys", "hotkeys", "keyboard"], ["Tabs", "tabs", "sounds"],
    ["General", "general", "settings"], ["About", "about", "star"]];
  var SET_ADV = [["Overlay", "overlay", "gamepad"], ["Privacy & security", "privacy", "shield"], ["Connection", "connection", "radio"],
    ["Data & quality", "data", "wave"], ["Updates", "updates", "reload"], ["Add-ons", "help", "plus"], ["Remote", "remote", "cable"],
    ["Achievements", "achievements", "trophy"]];
  function tellSettings() {
    if (S.toldSettings) return;
    S.toldSettings = true;
    toast("Just for show", "Settings change here, but they only change things in the app.");
  }
  // A Settings card from the app's own layout (board-demo-data.js, dumped from its
  // Settings pages): parts that overlap top to bottom make one row; in a row, the names
  // and hints stacked on the left stay together and the controls sit to their right.
  // Label texts are the app's, already escaped, with only b, i, br, ul and li kept.
  var HEAD_ICONS = { "Mic effect": "mic", "Theme style": "image" };
  function cardEl(card) {
    var rows = [], items = card.items.slice().sort(function (a, b) { return a.y - b.y || a.x - b.x; });
    items.forEach(function (it) {
      var row = rows[rows.length - 1];
      if (row && it.y < row.bot - 2) { row.items.push(it); row.bot = Math.max(row.bot, it.y + it.h); }
      else rows.push({ items: [it], bot: it.y + it.h });
    });
    var el = h("div", { class: "ob-scard2" });
    function part(it, ri) {
      if (it.k === "label") {
        if (it.on === "section") return h("div", { class: "head" }, [ri === 0 ? icon(card.icon || HEAD_ICONS[card.title] || "settings", "s") : null, h("span", { class: "t", html: it.t })]);
        var t = /^Version [\d.]+$/.test(it.t) ? "Version " + S.version : it.t;
        if (it.on === "pill") return h("span", { class: "ob-pill2", html: t });
        return h("div", { class: (it.on === "hint" || it.on === "muted" ? "h " : "") + "lb", html: t });
      }
      if (it.k === "check" && it.dis && card.title === "Tabs") return h("div", { class: "chk lb ob-always", title: it.tip || null }, [h("span", { class: "tk" }), h("span", { text: it.t })]);
      if (it.k === "check") return h("label", { class: "chk lb", title: it.tip || null }, [h("input", { type: "checkbox", checked: it.on, onchange: tellSettings }), h("span", { text: it.t })]);
      if (it.k === "radio") return h("label", { class: "chk lb" }, [h("input", { type: "radio", name: "ob-r" + card.title.length + "-" + it.y, checked: it.on, onchange: tellSettings }), h("span", { text: it.t })]);
      if (it.k === "combo") {
        var s = h("select", { "aria-label": "Choice", onchange: tellSettings });
        it.items.forEach(function (o) { s.appendChild(h("option", { text: o, selected: o === it.cur })); });
        return h("span", { class: "sel" }, [s]);
      }
      if (it.k === "slider") {
        var sl = h("input", { type: "range", min: String(it.v[0]), max: String(it.v[2]), value: String(it.v[1]), "aria-label": "Amount" });
        setRange(sl);
        sl.addEventListener("input", function () { setRange(sl); tellSettings(); });
        return sl;
      }
      if (it.k === "edit") return h("label", { class: "field", style: "max-width:" + Math.max(it.w, 160) + "px" }, [h("input", { value: it.t || "", placeholder: it.ph || "", "aria-label": it.ph || "Value", oninput: tellSettings })]);
      if (it.k === "btn") {
        if (card.title === "Language") {   // the app's language picker: "Aa", the language, its arrow
          return dd(h("button", { type: "button", class: "btn ob-langbtn", title: "32 languages", onclick: function () { tryIt("Onion Board in 32 languages"); } },
            [h("span", { class: "aa", text: "Aa" }), h("span", { class: "t", text: it.t.replace(/\s*▾$/, "") })]));
        }
        if (it.only) return btn("icon ob-x", null, it.ic || "close", function () { tellSettings(); }, { "aria-label": it.t, title: it.t });
        var key = /hotkey|^Click to set$|^Off$|^(Ctrl|Alt|Shift|F\d)|^.$/.test(it.t) && it.w >= 150;
        return btn("small" + (it.prim ? " acc" : "") + (key ? " ob-key" : ""), it.t, it.ic || null, function () { tryIt("“" + it.t + "”"); },
          { title: it.tip ? it.tip.replace(/<[^>]+>/g, "") : null, "aria-pressed": it.checked === true ? "true" : null });
      }
      if (it.k === "icon") return null;
      return null;
    }
    rows.forEach(function (row, ri) {
      row.items.sort(function (a, b) { return a.x - b.x || a.y - b.y; });
      // names and hints stacked on the left with controls beside them (a hotkey's name,
      // what it does, then its key and ✕)
      var labels = row.items.filter(function (it) { return it.k === "label" && it.on !== "section" && it.on !== "pill"; });
      var others = row.items.filter(function (it) { return labels.indexOf(it) < 0; });
      var stacked = labels.length > 1 && others.length && others.every(function (o) { return labels.every(function (l) { return o.x >= l.x + l.w - 4; }); });
      var r = h("div", { class: "r" });
      if (stacked) {
        labels.sort(function (a, b) { return a.y - b.y; });
        r.classList.add("stk");
        r.appendChild(h("div", { class: "lbs" }, labels.map(function (l) { return part(l, ri); })));
        others.forEach(function (it) { var p = part(it, ri); if (p) r.appendChild(p); });
      } else {
        row.items.forEach(function (it) {
          var p = part(it, ri);
          if (!p) return;
          // a name with its control after it: the name keeps the app's width, the control sits right by it
          if (it.k === "label" && it.on !== "section" && it.on !== "hint" && row.items.some(function (o) { return o !== it && o.x > it.x + it.w - 4 && o.k !== "label"; })) {
            p.style.flex = "0 0 auto"; p.style.width = Math.min(it.w + 4, 260) + "px";
          }
          r.appendChild(p);
        });
      }
      if (r.childNodes.length) el.appendChild(r);
    });
    if (card.title === "A note from me") el.appendChild(alienNote());
    return el;
  }
  // "A note from me" (bun/onionalien.py AlienNote): the Onion Alien and his pixel speech bubble
  function alienNote() {
    return h("div", { class: "ob-note" }, [h("img", { src: "demo/alien.webp", alt: "", width: "80", height: "96" }),
      h("div", { class: "bub", text: "No ads, no account, no spying, free forever. Found a bug? Tell me. Have fun.\n\nOnionAlien" })]);
  }
  // Appearance's look box, as the app has it: two tabs, Themes (Textured or Plain, then
  // the theme cards, the app's own previews with Bun dressed for each) and Look
  function themesCard() {
    var wrap = h("div", { class: "ob-scard2" });
    var tabs = h("div", { class: "ob-seg ob-looktabs" }), page = h("div", { class: "ob-lookpage" });
    function slugOf(n) { return n.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
    function drawThemes() {
      page.replaceChildren();
      var style = h("div", { class: "r" }, [h("div", { class: "head" }, [icon("image", "s"), h("span", { class: "t", text: "Theme style" })])]);
      var radios = h("div", { class: "r ob-radios" });
      [[true, "Textured"], [false, "Plain"]].forEach(function (o) {
        var r = h("input", { type: "radio", name: "ob-texture", checked: S.textured === o[0] });
        r.addEventListener("change", function () { S.textured = o[0]; theme(S.theme); did("texture"); drawThemes(); });
        radios.appendChild(h("label", { class: "chk" }, [r, h("span", { text: o[1] })]));
      });
      page.append(style, h("div", { class: "h", text: "Textured gives each theme its own pattern on the panels: scanlines, carbon fibre, waves and more. Plain keeps them flat." }), radios);
      var gicons = { Classic: "star", Colourful: "palette", Wild: "shuffle", Meme: "like" };
      var hints = { Classic: "Changes the whole app instantly.", Meme: "For when you want your soundboard to be a bit." };
      D.groups.forEach(function (g) {
        page.appendChild(h("div", { class: "r", style: "margin-top:10px" }, [h("div", { class: "head" }, [icon(gicons[g[0]] || "palette", "s"), h("span", { class: "t", text: g[0] })])]));
        if (hints[g[0]]) page.appendChild(h("div", { class: "h", text: hints[g[0]] }));
        var grid = h("div", { class: "ob-themes" });
        g[1].forEach(function (name) {
          var t = D.themes[name]; if (!t) return;
          var limited = (D.limited || []).indexOf(name) >= 0;
          grid.appendChild(h("button", {
            type: "button", class: "ob-theme", "data-name": name, "aria-pressed": S.theme === name ? "true" : "false",
            title: limited ? name + ": a limited edition, here for the season" : name,
            onclick: function () { theme(name); did("theme"); drawThemes(); }
          }, [h("img", { class: "pv2", src: "demo/themes/" + slugOf(name) + (S.textured ? "" : "-plain") + ".webp", alt: "", loading: "lazy", width: "154", height: "74" }),
              h("span", { text: name, style: t.font ? "font-family:" + t.font : null })]));
        });
        page.appendChild(grid);
      });
    }
    function drawLook() {
      page.replaceChildren();
      (D.settings.appearance_look || []).forEach(function (c) {
        if (c.title === "Language") return;
        var el = cardEl(c);
        el.classList.add("flat");
        page.appendChild(el);
      });
    }
    function drawTabs() {
      tabs.replaceChildren();
      [["themes", "Themes"], ["look", "Look"]].forEach(function (x) {
        tabs.appendChild(btn("", x[1], null, function () { S.lookTab = x[0]; drawTabs(); }, { "aria-pressed": (S.lookTab || "themes") === x[0] ? "true" : "false" }));
      });
      if ((S.lookTab || "themes") === "look") drawLook(); else drawThemes();
    }
    drawTabs();
    wrap.append(tabs, page);
    return wrap;
  }
  function settingsPage() {
    var body = h("div", { class: "ob-spage ob-scroll" });
    var nav = h("div", { class: "ob-snav" });
    var find = h("input", { type: "search", placeholder: "Search", "aria-label": "Search settings" });
    function show(key) {
      S.setPage = key;
      body.replaceChildren();
      var cards = D.settings[key] || [];
      cards.forEach(function (c) {
        if (key === "appearance" && c.title !== "Language") return;
        if (c.adv && !S.advanced) return;
        body.appendChild(cardEl(c));
      });
      if (key === "appearance") body.appendChild(themesCard());
      if (key === "audio" && !S.advanced) body.appendChild(h("div", null, [btn("", "More audio settings", "sliders", function () {
        var m = nav.querySelector("[aria-expanded]"); if (m) m.click();
      }, { title: "Speech voices, buffering and your mic switch (Show advanced)" })]));
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
          if (k === "appearance" && c.title !== "Language") return;   // (the theme cards' box: its parts are in Look)
          var txt = c.items.map(function (i) { return (i.t || "") + " " + (i.items || []).join(" "); }).join(" ").toLowerCase();
          if (txt.indexOf(q) >= 0 || c.title.toLowerCase().indexOf(q) >= 0) { body.appendChild(cardEl(c)); hits++; }
        });
      });
      if (!hits) body.appendChild(h("div", { class: "ob-none", text: "No settings match “" + q + "”." }));
    }
    find.addEventListener("input", function () { search(find.value); });
    nav.appendChild(h("button", { type: "button", class: "back", onclick: function () { go("sounds"); } }, [icon("nav_back", "g"), h("span", { class: "t", text: "Settings" }), icon("settings", "cog")]));
    nav.appendChild(h("label", { class: "field" }, [icon("search", "s"), find]));
    function navBtn(p) {
      return h("button", { type: "button", class: "pg", "data-k": p[1], title: p[0], onclick: function () { find.value = ""; show(p[1]); } }, [icon(p[2], "s"), h("span", { class: "t", text: p[0] })]);
    }
    SET_PAGES.forEach(function (p) { nav.appendChild(navBtn(p)); });
    nav.appendChild(h("hr"));
    var adv = h("div", { style: "display:contents" });
    var more = h("button", { type: "button", class: "pg", "aria-expanded": S.advanced ? "true" : "false", onclick: function () {
      S.advanced = !S.advanced; more.setAttribute("aria-expanded", S.advanced ? "true" : "false"); adv.hidden = !S.advanced;
      more.querySelector(".t").textContent = S.advanced ? "Hide advanced" : "Show advanced"; more.querySelector(".arr").textContent = S.advanced ? "▾" : "▸";
      show(S.setPage);
    } }, [icon("sliders", "s"), h("span", { class: "t", text: S.advanced ? "Hide advanced" : "Show advanced" }), h("span", { class: "arr", text: S.advanced ? "▾" : "▸" })]);
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
    R.repaint = null;
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
    S.version = version;
    root = h("div", { class: "ob", tabindex: "-1", role: "application", "aria-label": "A working copy of Onion Board" });
    R.lc = {};
    theme(S.theme);
    var brand = h("button", { type: "button", class: "ob-brand", title: "Onion Board", onclick: function () {
      brand.classList.remove("wob"); void brand.offsetWidth; brand.classList.add("wob");
      if (site.play) site.play("squeak");
    } }, [logoMark(), h("div", null, [h("b", { text: "Onion Board" }), h("small", { text: "by Onion Alien · v" + version })])]);
    R.nav = h("nav", { class: "ob-nav" });
    [["sounds", "Sounds"], ["radio", "Radio"], ["apps", "Apps"], ["triggers", "Triggers"], ["voice", "Voice"], ["store", "Community"], ["setup", "Setup"]].forEach(function (n) {
      R.nav.appendChild(h("button", { type: "button", "data-p": n[0], title: n[1], "aria-current": n[0] === "sounds" ? "page" : "false", onclick: function () { go(n[0]); } },
        [icon(n[0] === "voice" ? "voice" : n[0]), h("span", { class: "t", text: n[1] }), n[0] === "store" ? h("span", { class: "ob-new", text: "New" }) : null]));
    });
    R.live = h("button", { type: "button", class: "ob-live", title: "Others hear your sounds and mic: click to mute both", "aria-label": "Others hear me", onclick: function () { setLive(!S.live); } }, [icon("live"), h("span", { class: "t", text: "On" })]);
    var stopB = h("button", { type: "button", class: "ob-stopall", title: "Stop all sounds", "aria-label": "Stop all sounds", onclick: stopAll }, [h("span", { class: "sq" }), h("span", { class: "t", text: "Stop all" })]);
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
      if (e.key === "Escape") { if (R.pop && !R.menu && !root.querySelector(".ob-veil")) { var a = R.pop.anchor; closeLive(); a.focus({ preventScroll: true }); e.stopPropagation(); } else if (R.menu) { closeMenu(); e.stopPropagation(); } return; }
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
  // The site's look switcher picks the same theme in the demo.
  var lookToTheme = { dark: "Dark", light: "Light", ocean: "Ocean", hacker: "Hacker", synthwave: "Synthwave", "blood-moon": "Blood Moon", halloween: "Halloween" };
  window.OnionBoardDemo = {
    look: function (name) {
      var t = lookToTheme[name] || "Dark";
      if (root) theme(t); else S.theme = t;
    },
    mount: function (box) {
      var frame = box.querySelector(".frame");
      if (!frame || frame.classList.contains("live")) return;
      S.theme = lookToTheme[document.documentElement.dataset.look] || "Dark";
      fetch("release.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }).then(function (r) {
        var v = /^[\w.\-]+$/.test(r.version || "") ? r.version : "2";
        var el = build(v);
        var chrome = h("div", { class: "ob-chrome" }, [
          h("span", { text: "A working copy of the app, right here. Click, right-click, drop in your own sounds." })
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
