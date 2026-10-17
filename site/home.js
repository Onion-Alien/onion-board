// The home page's moving parts: the Board / Watch tabs, the try-it pads (real CC0 recordings
// in sounds/, see CREDITS.txt; made-up Web Audio stand-ins play until they load), Bun and Hoot, the Watch demo,
// and the small stuff (reveal on scroll, counters, the copy button).
(function () {
  "use strict";
  var root = document.documentElement;
  // Less motion asked for: no slide-ins or smooth scrolling. Bun and Hoot still play.
  var still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function $(s, el) { return (el || document).querySelector(s); }
  function $$(s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); }
  function rand(a, b) { return a + Math.random() * (b - a); }
  function pick(list) { return list[Math.floor(Math.random() * list.length)]; }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } }
  var waiting = [];
  function count(path) {         // GoatCounter's script loads async: hold early ones until it's there
    if (window.goatcounter && goatcounter.count) goatcounter.count({ path: path, event: true });
    else if (waiting.push(path) === 1) (function retry(n) {
      setTimeout(function () {
        if (window.goatcounter && goatcounter.count) waiting.splice(0).forEach(count);
        else if (n < 20) retry(n + 1);
        else waiting.length = 0;  // blocked or offline: give up quietly
      }, 500);
    })(0);
  }
  // What visitors do on the page: site-<what>, each counted once a visit, so a few clicks
  // never turn into a flood of hits.
  var counted = {};
  function countOnce(path) { if (!counted[path]) { counted[path] = 1; count(path); } }
  function did(what) { countOnce("site-" + what); }

  // ------------------------------------------------------------------ tabs
  var TITLES = {
    board: "Onion Board: free soundboard for Discord and games (Windows)",
    watch: "Onion Watch: a sound when your game needs you (free, Windows)"
  };
  var NAV_DL = {
    board: ["https://github.com/Onion-Alien/onion-board/releases/latest/download/OnionBoardSetup.exe", "download-home-nav"],
    watch: ["https://github.com/Onion-Alien/onion-watch/releases/latest/download/OnionWatch-Installer.exe", "download-watch-board-site-nav"]
  };
  var tabs = $$(".switch [role=tab]"), pill = $(".switch .pill"), panels = $$(".panel");
  var brandImg = $(".brand img"), brandName = $("[data-name]"), miniDl = $(".mini-dl");
  var favicons = $$("link[rel=icon]");
  favicons.forEach(function (l) { l.setAttribute("data-board-href", l.getAttribute("href")); });

  function current() { return root.dataset.product === "watch" ? "watch" : "board"; }
  function placePill() {
    var t = tabs.filter(function (b) { return b.dataset.tab === current(); })[0];
    if (!t || !t.offsetWidth) return;
    pill.style.width = t.offsetWidth + "px";
    pill.style.transform = "translateX(" + (t.offsetLeft - 4) + "px)";
    if (!pill.parentNode.classList.contains("ready")) {
      void pill.offsetWidth;
      requestAnimationFrame(function () { pill.parentNode.classList.add("ready"); });
    }
  }
  function apply(name) {
    root.dataset.product = name;
    tabs.forEach(function (t) {
      var on = t.dataset.tab === name;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
    });
    panels.forEach(function (p) { p.classList.toggle("on", p.dataset.panel === name); });
    brandImg.src = brandImg.getAttribute("data-" + name + "-src");
    brandName.textContent = name === "watch" ? "Onion Watch" : "Onion Board";
    miniDl.href = NAV_DL[name][0];
    miniDl.setAttribute("data-goatcounter-click", NAV_DL[name][1]);
    document.title = TITLES[name];
    favicons.forEach(function (l) {       // the browser tab shows Bun or Hoot too
      l.href = name === "watch" ? brandImg.getAttribute("data-watch-src") : l.getAttribute("data-board-href");
    });
    placePill();
    onScroll();
    if (name === "watch") watchShown(); else bunShown();
  }
  function select(name, scrollUp) {
    if (name === current()) { if (scrollUp) window.scrollTo({ top: 0, behavior: still ? "auto" : "smooth" }); return; }
    history.replaceState(null, "", name === "watch" ? "#watch" : location.pathname + location.search);
    did("tab-" + name);
    apply(name);
    if (scrollUp) window.scrollTo(0, 0);
    var p = $(".panel.on");     // drop its mascot in (CSS)
    p.classList.remove("enter"); void p.offsetWidth; p.classList.add("enter");
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { select(t.dataset.tab, false); });
    t.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      var next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      select(next.dataset.tab, false);
    });
  });
  $$("[data-tab-link]").forEach(function (a) {
    a.addEventListener("click", function (e) { e.preventDefault(); select(a.getAttribute("data-tab-link"), true); });
  });
  window.addEventListener("hashchange", function () {
    if (location.hash === "#watch") select("watch", true);
    else if (location.hash === "#board") select("board", true);
  });
  panels.forEach(function (p) {
    p.addEventListener("animationend", function (e) {
      if (e.target.classList.contains("mascot")) p.classList.remove("enter");
    });
  });
  new Image().src = brandImg.getAttribute("data-watch-src");   // no blank logo on the first switch
  window.addEventListener("resize", placePill);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(placePill);

  // Onion Watch's version line comes from its own site (same origin), so it's never stale.
  fetch("../onion-watch/release.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; })
    .then(function (r) {
      if (!r || !/^[\w.\-]+$/.test(r.version || "")) return;
      var p = $("#watch-meta");
      p.textContent = "Version " + r.version + " · Windows 10 / 11 · free, no account, no internet needed";
      p.appendChild(document.createElement("br"));
      if (/^[0-9a-f]{64}$/.test(r.vt_sha256 || "") && r.vt_total) {
        var vt = document.createElement("a");
        vt.href = "https://www.virustotal.com/gui/file/" + r.vt_sha256;
        vt.textContent = "VirusTotal: " + (+r.vt_clean) + " of " + (+r.vt_total) + " clean";
        p.appendChild(vt);
        p.appendChild(document.createTextNode(" · "));
      }
      var wn = document.createElement("a");
      wn.href = "https://github.com/Onion-Alien/onion-watch/releases/latest";
      wn.textContent = "what's new";
      p.appendChild(wn);
    }).catch(function () { /* offline or blocked: the plain line stays */ });

  // ------------------------------------------------------------------ sound
  // Made on the spot, only after a click or a key press (browsers allow nothing sooner).
  var VOL = 0.45;                // the page plays quietly: it's a demo, not the app
  var ac = null, bus = null, comp = null, an = null, master = null, noise = null, levels = null;
  var muted = load("onion-site-muted") === "1";
  var muteBtn = $("#mute");
  // A headset that sleeps, wakes or gets unplugged leaves the old context playing into
  // nothing (or stuck, its clock frozen) until a reload: start a fresh one instead.
  var stale = false, lastClock = -1, lastSeen = 0;
  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener)
    navigator.mediaDevices.addEventListener("devicechange", function () { stale = true; });
  function broken() {
    if (stale || ac.state === "closed" || ac.state === "interrupted") return true;
    var now = performance.now(), frozen = ac.state === "running" && ac.currentTime === lastClock && now - lastSeen > 400;
    if (ac.currentTime !== lastClock) { lastClock = ac.currentTime; lastSeen = now; }
    return frozen;
  }
  function audio() {
    if (ac && broken()) {
      try { ac.close(); } catch (e) { /* already closed */ }
      ac = null; an = null; roomIR = null;
      stale = false; lastClock = -1;
    }
    if (!ac) {
      var C = window.AudioContext || window.webkitAudioContext;
      if (!C) return null;
      ac = new C();
      bus = ac.createGain();
      comp = ac.createDynamicsCompressor();
      comp.threshold.value = -16; comp.ratio.value = 6; comp.attack.value = 0.003; comp.release.value = 0.2;
      an = ac.createAnalyser(); an.fftSize = 1024;
      levels = new Uint8Array(an.fftSize);
      master = ac.createGain(); master.gain.value = muted ? 0 : VOL;
      bus.connect(comp); comp.connect(an); an.connect(master); master.connect(ac.destination);
      noise = ac.createBuffer(1, ac.sampleRate * 2, ac.sampleRate);
      var d = noise.getChannelData(0);
      for (var i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    if (ac.state === "suspended") ac.resume();
    return ac;
  }
  function showMute() {
    muteBtn.textContent = muted ? "🔇" : "🔊";
    muteBtn.setAttribute("aria-pressed", muted ? "true" : "false");
    muteBtn.setAttribute("aria-label", muted ? "Sound off: click to turn the page's sounds on" : "Sound on: click to mute the page");
    muteBtn.title = muted ? "Sound off" : "Sound on";
  }
  showMute();
  muteBtn.addEventListener("click", function () {
    muted = !muted;
    save("onion-site-muted", muted ? "1" : "0");
    if (master) master.gain.setTargetAtTime(muted ? 0 : VOL, ac.currentTime, 0.02);
    showMute();
    did(muted ? "mute-on" : "mute-off");
    if (!muted) { audio(); play("coin"); }
  });

  // Recorded clips, fetched and decoded soon after the page loads, so even the first press
  // plays the real one. An offline context decodes without asking to play (no autoplay
  // block), and its buffers work in any context, so a rebuilt one keeps them.
  var clips = {};
  var PADS = ["horn", "boom", "buzzer", "rimshot", "laser", "trombone", "clap", "coin", "drop"];
  function loadClips() {
    var O = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!O) return;
    var dec = new O(1, 1, 44100);
    PADS.concat("hoot").forEach(function (name) {
      fetch("sounds/" + name + ".mp3").then(function (r) { return r.arrayBuffer(); })
        .then(function (b) { return new Promise(function (ok, no) { dec.decodeAudioData(b, ok, no); }); })
        .then(function (buf) { clips[name] = buf; })
        .catch(function () { /* offline or blocked: the made-up one plays instead */ });
    });
  }
  if (document.readyState === "complete") setTimeout(loadClips, 300);
  else addEventListener("load", function () { setTimeout(loadClips, 300); });
  function clip(name, t, vol) {
    var buf = clips[name];
    if (!buf) return 0;
    var s = ac.createBufferSource(), g = ac.createGain();
    s.buffer = buf; g.gain.value = vol;
    s.connect(g); g.connect(bus);
    s.start(t);
    return buf.duration;
  }
  // A dark, booming room for the vine boom: decaying noise, made once.
  var roomIR = null;
  function room(to) {
    if (!roomIR) {
      var n = Math.floor(ac.sampleRate * 1.8), ch = [0, 1];
      roomIR = ac.createBuffer(2, n, ac.sampleRate);
      ch.forEach(function (c) {
        var d = roomIR.getChannelData(c), lp = 0;
        for (var i = 0; i < n; i++) {
          lp += 0.08 * ((Math.random() * 2 - 1) - lp);       // dark: low-passed noise
          d[i] = lp * Math.exp(-i / (ac.sampleRate * 0.38));
        }
      });
    }
    var cv = ac.createConvolver();
    cv.buffer = roomIR;
    cv.connect(to);
    return cv;
  }

  function env(g, t, a, peak, d) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(peak, t + a);
    g.gain.exponentialRampToValueAtTime(0.0001, t + d);
  }
  function tone(type, f0, f1, t, d, peak, a, to) {
    var o = ac.createOscillator(), g = ac.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    if (f1 && f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + d * 0.9);
    env(g, t, a || 0.005, peak, d);
    o.connect(g); g.connect(to || bus);
    o.start(t); o.stop(t + d + 0.05);
    return o;
  }
  function hiss(t, d, peak, type, freq, q, a) {
    var s = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
    s.buffer = noise; s.loop = true;
    f.type = type; f.frequency.value = freq; f.Q.value = q || 0.7;
    env(g, t, a || 0.002, peak, d);
    s.connect(f); f.connect(g); g.connect(bus);
    s.start(t, Math.random()); s.stop(t + d + 0.05);
    return f;
  }
  function crunch(amount) {
    var ws = ac.createWaveShaper(), n = 1024, c = new Float32Array(n);
    for (var i = 0; i < n; i++) { var x = i * 2 / n - 1; c[i] = Math.tanh(x * amount); }
    ws.curve = c;
    ws.connect(bus);
    return ws;
  }
  function vibrato(o, t, rate, depth, d) {
    var l = ac.createOscillator(), lg = ac.createGain();
    l.frequency.value = rate; lg.gain.value = depth;
    l.connect(lg); lg.connect(o.frequency);
    l.start(t); l.stop(t + d);
  }

  // Each returns how long it lasts, in seconds.
  var SFX = {
    horn: function (t) {
      var lp = ac.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 2600; lp.connect(bus);
      [[0, 0.13], [0.17, 0.13], [0.34, 0.75]].forEach(function (b) {
        [415, 419, 622, 831].forEach(function (f, k) {
          var o = tone("sawtooth", f, f * (b[1] > 0.5 ? 0.97 : 1), t + b[0], b[1], k > 1 ? 0.06 : 0.11, 0.01, lp);
          vibrato(o, t + b[0], 6, 3, b[1]);
        });
      });
      return 1.15;
    },
    boom: function (t) {               // a deep, round "bwomm" that hangs in a big room
      var ws = crunch(3.5), wet = ac.createGain();
      wet.gain.value = 0.55; wet.connect(room(bus));
      ws.connect(wet);
      var o = ac.createOscillator(), g = ac.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(190, t);
      o.frequency.exponentialRampToValueAtTime(60, t + 0.06);
      o.frequency.exponentialRampToValueAtTime(47, t + 1.3);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(0.3, t + 0.004);
      g.gain.setValueAtTime(0.3, t + 0.12);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 1.4);
      o.connect(g); g.connect(ws);
      o.start(t); o.stop(t + 1.45);
      tone("triangle", 120, 94, t, 0.5, 0.1, 0.004, ws);        // the "wom" in it
      hiss(t, 0.03, 0.22, "lowpass", 2400);                      // the hit
      return 2.1;
    },
    buzzer: function (t) {             // the game-show "wrong answer"
      var lp = ac.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 1700; lp.connect(bus);
      [[146, "sawtooth", 0.11], [151, "sawtooth", 0.11], [73, "square", 0.055]].forEach(function (v) {
        var o = ac.createOscillator(), g = ac.createGain();
        o.type = v[1]; o.frequency.value = v[0];
        g.gain.setValueAtTime(0.0001, t);
        g.gain.linearRampToValueAtTime(v[2], t + 0.01);
        g.gain.setValueAtTime(v[2], t + 0.78);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.86);
        o.connect(g); g.connect(lp);
        o.start(t); o.stop(t + 0.9);
      });
      return 0.86;
    },
    rimshot: function (t) {
      tone("sine", 210, 110, t, 0.2, 0.5);
      hiss(t, 0.05, 0.3, "bandpass", 1800, 1);
      tone("sine", 150, 80, t + 0.17, 0.26, 0.5);
      hiss(t + 0.17, 0.05, 0.3, "bandpass", 1500, 1);
      tone("sine", 190, 100, t + 0.38, 0.2, 0.4);
      hiss(t + 0.38, 1.2, 0.35, "highpass", 6500);
      hiss(t + 0.38, 0.9, 0.2, "bandpass", 9500, 2);
      return 1.6;
    },
    laser: function (t) {
      tone("square", 1900, 140, t, 0.3, 0.16);
      tone("square", 1600, 120, t + 0.24, 0.32, 0.14);
      return 0.6;
    },
    trombone: function (t) {
      var notes = [[293.7, 0, 0.42], [277.2, 0.45, 0.42], [261.6, 0.9, 0.42], [246.9, 1.35, 1.25]];
      notes.forEach(function (n, i) {
        var lp = ac.createBiquadFilter(); lp.type = "lowpass"; lp.Q.value = 4; lp.connect(bus);
        lp.frequency.setValueAtTime(350, t + n[1]);
        lp.frequency.linearRampToValueAtTime(1500, t + n[1] + 0.18);
        lp.frequency.linearRampToValueAtTime(700, t + n[1] + n[2]);
        var o = tone("sawtooth", n[0], i === 3 ? n[0] * 0.97 : n[0], t + n[1], n[2], 0.3, 0.04, lp);
        if (i === 3) vibrato(o, t + n[1] + 0.2, 6, 7, n[2]);
      });
      return 2.6;
    },
    clap: function (t) {
      hiss(t, 2.6, 0.12, "bandpass", 1400, 0.5, 0.5);
      for (var i = 0; i < 70; i++) {
        var at = t + Math.pow(Math.random(), 1.3) * 2.2;
        hiss(at, rand(0.03, 0.07), rand(0.08, 0.32), "bandpass", rand(900, 2400), 1.2);
      }
      return 2.6;
    },
    coin: function (t) {
      tone("square", 988, 988, t, 0.09, 0.14);
      tone("square", 1319, 1319, t + 0.08, 0.5, 0.14);
      return 0.6;
    },
    drop: function (t) {
      var f = hiss(t, 0.55, 0.25, "bandpass", 400, 2, 0.5);
      f.frequency.setValueAtTime(400, t);
      f.frequency.exponentialRampToValueAtTime(6000, t + 0.5);
      tone("sine", 200, 900, t, 0.5, 0.15, 0.4);
      var ws = crunch(3);
      tone("sine", 160, 34, t + 0.55, 1.8, 0.24, 0.004, ws);
      tone("sawtooth", 80, 30, t + 0.55, 1.2, 0.07, 0.004, ws);
      hiss(t + 0.55, 0.1, 0.35, "lowpass", 1200);
      return 2.35;
    },
    // Bun and Hoot's own noises: small and quiet, so poking them never gets loud.
    squeak: function (t) { tone("sine", 800, 1400, t, 0.12, 0.12, 0.01); return 0.13; },
    grumble: function (t) {
      var o = tone("triangle", 130, 100, t, 0.45, 0.12, 0.03);
      vibrato(o, t, 14, 12, 0.45);
      return 0.45;
    },
    hoot: function (t) {               // a real owl's "hoo… hoo" (CC0), softly
      var d = clip("hoot", t, 0.5);
      if (d) return d;
      var o = tone("sine", 330, 300, t, 0.5, 0.07, 0.08);      // not loaded yet: a low hum
      vibrato(o, t, 5, 3, 0.5);
      return 0.5;
    },
    ring: function (t) {               // a gentle two-note chime
      [[0, 1046.5], [0.18, 784]].forEach(function (n) {
        tone("sine", n[1], n[1], t + n[0], 0.55, 0.12, 0.01);
        tone("sine", n[1] * 2, n[1] * 2, t + n[0], 0.2, 0.015, 0.01);
      });
      return 0.75;
    }
  };

  var talkUntil = 0, looping = false;
  function play(name) {
    if (!audio() || !SFX[name]) return 0;
    var t = ac.currentTime + 0.01;
    var d = (PADS.indexOf(name) >= 0 && clip(name, t, 0.7)) || SFX[name](t);
    talkUntil = Math.max(talkUntil, performance.now() + d * 1000 + 80);
    if (!looping) { looping = true; requestAnimationFrame(levelLoop); }
    return d;
  }

  // The clickable app demo (board-demo.js) shares these sounds, the mute button and the
  // visit count. stop() cuts whatever is playing: every sound goes through `bus`, so a
  // fresh bus leaves the old sounds talking to nothing.
  window.onionSite = {
    play: play,
    clip: function (name) { return clips[name] || null; },
    audio: function () { return audio() ? { ac: ac, out: bus } : null; },
    stop: function () {
      if (!ac) return;
      var old = bus;
      bus = ac.createGain(); bus.connect(comp); old.disconnect();
      talkUntil = 0;
    },
    talk: function (seconds) {    // keeps the level meter going for the demo's own sounds
      talkUntil = Math.max(talkUntil, performance.now() + seconds * 1000 + 80);
      if (!looping) { looping = true; requestAnimationFrame(levelLoop); }
    },
    level: function () { return smooth; },
    did: did
  };

  // The level meter and Bun's mouth follow what's playing, like he does in the app.
  // The level is smoothed (opens fast, closes slowly) and Bun keeps talking until the
  // sound ends, so his mouth doesn't flicker between open and smiling on quiet bits.
  var meter = $("#meter"), mouths = $$("#bun .mo, #mouth-clip .mo"), tongue = $("#bun .tongue"), bunSvg = $("#bun");
  function mouthD(m) {             // bunny.py's open mouth, `m` 0..1 open (site_mascots.py: mouth_d)
    var oh = 2.5 + 6.5 * Math.min(1, m), hw = 4.2 + 1.3 * m, b = (75.5 + oh * 1.25).toFixed(2);
    var l = (50 - hw).toFixed(2), r = (50 + hw).toFixed(2);
    return "M" + l + " 75.2Q" + (50 - hw / 2).toFixed(2) + " 77 50 75.4Q" + (50 + hw / 2).toFixed(2) +
      " 77 " + r + " 75.2C" + r + " " + b + " " + l + " " + b + " " + l + " 75.2Z";
  }
  var smooth = 0;
  function levelLoop() {
    var lvl = 0;
    if (an) {
      an.getByteTimeDomainData(levels);
      var sum = 0;
      for (var i = 0; i < levels.length; i += 2) { var v = (levels[i] - 128) / 128; sum += v * v; }
      lvl = Math.min(1, Math.sqrt(sum / (levels.length / 2)) * 3.4);
    }
    smooth += (lvl - smooth) * (lvl > smooth ? 0.45 : 0.12);
    lvl = smooth;
    meter.style.transform = "scaleX(" + lvl.toFixed(3) + ")";
    var m = Math.min(1, lvl * 1.4), oh = 2.5 + 6.5 * m, d = mouthD(m);
    mouths.forEach(function (el) { el.setAttribute("d", d); });
    tongue.setAttribute("cy", (75.5 + oh * 0.95).toFixed(2));
    tongue.setAttribute("rx", ((4.2 + 1.3 * m) * 0.65).toFixed(2));
    tongue.setAttribute("ry", (oh * 0.3).toFixed(2));
    bunSvg.classList.add("talking");
    if (performance.now() < talkUntil) requestAnimationFrame(levelLoop);
    else { looping = false; smooth = 0; meter.style.transform = "scaleX(0)"; bunSvg.classList.remove("talking"); }
  }

  // ------------------------------------------------------------------ helpers for both
  function say(el, text, ms) {
    clearTimeout(el._t);
    el.textContent = text;
    el.classList.add("on");
    el._t = setTimeout(function () { el.classList.remove("on"); }, ms || 2600);
  }
  function floaty(stage, text, opts) {
    opts = opts || {};
    var s = document.createElement("span");
    s.className = "floaty";
    s.textContent = text;
    s.style.left = "calc(50% + " + (opts.x != null ? opts.x : rand(-40, 50)) + "px)";
    s.style.top = (opts.top || 14) + "%";
    s.style.setProperty("--dx", rand(-40, 60) + "px");
    s.style.setProperty("--rot", rand(-30, 30) + "deg");
    if (opts.color) s.style.color = opts.color;
    stage.appendChild(s);
    setTimeout(function () { s.remove(); }, 1500);
  }
  function blinker(svg, panel) {
    (function next() {
      setTimeout(function () {
        if (current() === panel && !svg.classList.contains("asleep")) {
          svg.classList.add("blink");
          setTimeout(function () { svg.classList.remove("blink"); }, 130);
          if (Math.random() < 0.25) setTimeout(function () {
            svg.classList.add("blink");
            setTimeout(function () { svg.classList.remove("blink"); }, 120);
          }, 260);
        }
        next();
      }, rand(2200, 5600));
    })();
  }
  function boing(btn) {
    btn.classList.remove("boing"); void btn.offsetWidth; btn.classList.add("boing");
  }
  function pokes(list) {           // how many pokes in the last 2.5 s
    var now = performance.now();
    list.push(now);
    while (list.length && now - list[0] > 2500) list.shift();
    return list.length;
  }

  // ------------------------------------------------------------------ Bun
  var bunBtn = $("#bun-btn"), bunSay = $("#bun-say"), bunStage = bunBtn.parentNode, bunEyes = $("#bun .eyes");
  var bunPokes = [], angryT = 0, idleAt = performance.now(), zzz = 0;
  blinker(bunSvg, "board");
  (function flick() {
    setTimeout(function () {
      if (current() === "board" && !bunSvg.classList.contains("asleep")) {
        bunSvg.classList.add("flick");
        setTimeout(function () { bunSvg.classList.remove("flick"); }, 320);
      }
      flick();
    }, rand(6000, 13000));
  })();
  bunBtn.addEventListener("pointerenter", function () { bunSvg.classList.add("perk"); });
  bunBtn.addEventListener("pointerleave", function () { bunSvg.classList.remove("perk"); });
  bunBtn.addEventListener("animationend", function (e) { if (e.animationName === "boing") bunBtn.classList.remove("boing"); });
  bunBtn.addEventListener("click", function () {
    wake();
    boing(bunBtn);
    did("poke-bun");
    if (pokes(bunPokes) >= 6) {
      bunSvg.classList.add("angry");
      clearTimeout(angryT);
      angryT = setTimeout(function () { bunSvg.classList.remove("angry"); }, 3200);
      play("grumble");
      did("bun-angry");
      say(bunSay, pick(["Hey! Press the pads, not me.", "I bite, you know.", "Okay, that's enough poking."]), 2800);
      bunPokes.length = 0;
      return;
    }
    play("squeak");
    floaty(bunStage, pick(["♪", "♫", "♥", "✦"]));
    if (!bunSvg.classList.contains("angry") && Math.random() < 0.5)
      say(bunSay, pick(["Hehe.", "Boop!", "That tickles.", "Try the pads!", "Hi!"]), 1500);
  });
  function wake() {
    idleAt = performance.now();
    if (bunSvg.classList.contains("asleep")) {
      bunSvg.classList.remove("asleep");
      clearInterval(zzz);
      say(bunSay, "I'm up! I'm up!", 1600);
      did("bun-woke");
    }
  }
  function bunShown() { idleAt = performance.now(); }
  ["pointermove", "pointerdown", "keydown", "scroll"].forEach(function (ev) {
    window.addEventListener(ev, wake, { passive: true });
  });
  setInterval(function () {      // nothing happening for a while: Bun naps, Hoot doesn't
    if (document.hidden || performance.now() - idleAt < 22000) return;
    if (current() === "board" && !bunSvg.classList.contains("asleep") && !looping) {
      bunSvg.classList.add("asleep");
      say(bunSay, "Zzz… (wiggle the mouse to wake me)", 3000);
      zzz = setInterval(function () { floaty(bunStage, "z", { x: 30, top: 10, color: "var(--muted)" }); }, 1300);
    } else if (current() === "watch" && !hootSvg._toldIdle) {
      hootSvg._toldIdle = true;
      say(hootSay, "Bun's asleep again. I don't sleep. I watch.", 3600);
    }
  }, 2000);
  setTimeout(function () {
    if (current() === "board") say(bunSay, "Hi, I'm Bun! Press a pad, or 1 to 9.", 4200);
  }, 900);

  // the pads
  var padEls = $$("#pads .pad");
  function hitPad(btn, how) {
    wake();
    var d = play(btn.dataset.sfx);
    did("pads"); did("pad-" + btn.dataset.sfx);
    if (how) did("pad-" + how);
    if (!d) return;
    btn.classList.add("on");
    btn.classList.remove("hit"); void btn.offsetWidth; btn.classList.add("hit");
    setTimeout(function () { btn.classList.remove("hit"); }, 120);
    var t0 = performance.now();
    if (btn._raf) cancelAnimationFrame(btn._raf);
    (function step() {
      var p = (performance.now() - t0) / (d * 1000);
      btn.style.setProperty("--p", Math.min(1, p).toFixed(3));
      if (p < 1) btn._raf = requestAnimationFrame(step);
      else { btn.classList.remove("on"); btn.style.setProperty("--p", 0); }
    })();
    if (Math.random() < 0.6) floaty(bunStage, pick(["♪", "♫"]), { x: rand(10, 60), top: 22 });
  }
  padEls.forEach(function (b) { b.addEventListener("click", function () { hitPad(b); }); });
  document.addEventListener("keydown", function (e) {
    if (current() !== "board" || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
    if (e.target.closest && e.target.closest(".ob")) return;   // the app demo has its own keys
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || e.target.isContentEditable) return;
    var n = parseInt(e.key, 10);
    if (n >= 1 && n <= 9) { e.preventDefault(); hitPad(padEls[n - 1], "key"); }
  });

  // ------------------------------------------------------------------ Hoot
  var hootBtn = $("#hoot-btn"), hootSvg = $("#hoot"), hootSay = $("#hoot-say"), hootStage = hootBtn.parentNode;
  var hootPupils = $$("#hoot .pupils"), hootTurn = $("#hoot .body-turn"), hootPokes = [];
  blinker(hootSvg, "watch");
  hootBtn.addEventListener("animationend", function (e) { if (e.animationName === "boing") hootBtn.classList.remove("boing"); });
  hootBtn.addEventListener("click", function () {
    boing(hootBtn);
    did("poke-hoot");
    if (pokes(hootPokes) >= 6) {
      hootPokes.length = 0;
      did("hoot-shh");
      say(hootSay, "Shh! I'm working here.", 2400);
      return;
    }
    play("hoot");
    floaty(hootStage, pick(["Hoo!", "✦", "👀"]), { color: "var(--a3)" });
    if (Math.random() < 0.5) say(hootSay, pick(["Hoo!", "Still watching.", "Nothing yet.", "Try “Make it show up”."]), 1600);
  });

  // ------------------------------------------------------------------ the Watch demo
  var win = $("#gamewin"), spawnBtn = $("#spawn-btn"), status = $("#watch-status");
  var ringing = false, ringT = 0, rings = 0, autoT = 0, demoTouched = false;
  var SPAWNS = ["RARE SPAWN!", "QUEUE POPPED!", "WHISPER!", "YOU DIED"];
  var SCENE = { "RARE SPAWN!": "rare", "QUEUE POPPED!": "queue", "WHISPER!": "whisper", "YOU DIED": "died" };
  function setStatus(html) { status.innerHTML = "<i></i>" + html; }
  function fire(loud) {
    if (ringing) return;
    ringing = true; rings = 0;
    var what = pick(SPAWNS);
    $(".spawn", win).textContent = what;
    win.dataset.what = SCENE[what];       // the scene reacts too: the rare one pops out, you fall over
    win.classList.add("fired");
    hootSvg.classList.add("alert");
    setStatus("<b>" + what.replace("!", "") + "</b> · ringing until you're back");
    spawnBtn.textContent = "I'm back";
    spawnBtn.classList.add("back");
    if (loud) say(hootSay, "HOO! It showed up!", 2200);
    (function ring() {
      if (!ringing) return;
      if (loud) play("ring");
      {
        var p = document.createElement("div");
        p.className = "pulse";
        hootStage.appendChild(p);
        setTimeout(function () { p.remove(); }, 1150);
      }
      rings++;
      if ((!loud && rings >= 3) || rings >= 8) { setTimeout(back, 900); return; }
      ringT = setTimeout(ring, 1100);
    })();
  }
  function back() {
    if (!ringing) return;
    ringing = false;
    clearTimeout(ringT);
    win.classList.remove("fired");
    delete win.dataset.what;
    hootSvg.classList.remove("alert");
    setStatus("Hoot is watching…");
    spawnBtn.textContent = "Make it show up";
    spawnBtn.classList.remove("back");
  }
  spawnBtn.addEventListener("click", function () {
    demoTouched = true;
    clearTimeout(autoT);
    did("watch-demo");
    if (ringing) { back(); say(hootSay, "Welcome back.", 1600); did("watch-back"); }
    else fire(true);
  });
  function watchShown() {        // show the trick once by itself, silently, then leave it to them
    hootSvg._toldIdle = false;
    idleAt = performance.now();
    if (demoTouched) return;
    clearTimeout(autoT);
    autoT = setTimeout(function () { if (current() === "watch" && !demoTouched) fire(false); }, 2600);
    setTimeout(function () {
      if (current() === "watch") say(hootSay, "Hi, I'm Hoot. I watch your game for you.", 3400);
    }, 600);
  }

  // ------------------------------------------------------------------ eyes follow the pointer
  var px = -1, py = -1, raf = 0;
  function look() {
    raf = 0;
    var svg = current() === "watch" ? hootSvg : bunSvg, r = svg.getBoundingClientRect();
    if (!r.width || r.bottom < 0 || r.top > innerHeight) return;
    var cx = r.left + r.width / 2, cy = r.top + r.height * 0.45;
    var dx = px - cx, dy = py - cy, dist = Math.max(1, Math.hypot(dx, dy));
    var k = Math.min(1, dist / 260), lx = dx / dist * k, ly = dy / dist * k;
    if (svg === bunSvg) {
      if (!bunSvg.classList.contains("asleep"))
        bunEyes.style.transform = "translate(" + (lx * 2.4).toFixed(2) + "px," + (ly * 1.8).toFixed(2) + "px)";
    } else {
      hootPupils.forEach(function (p) {
        p.style.transform = "translate(" + (lx * 3.5).toFixed(2) + "px," + (ly * 3).toFixed(2) + "px)";
      });
      hootTurn.style.transform = "rotate(" + (lx * 5).toFixed(2) + "deg)";
    }
  }
  window.addEventListener("pointermove", function (e) {
    px = e.clientX; py = e.clientY;
    if (!raf) raf = requestAnimationFrame(look);
  }, { passive: true });

  // ------------------------------------------------------------------ page bits
  var top = $("#top");
  function onScroll() {
    top.classList.toggle("stuck", scrollY > 8);
    var dl = $(".panel.on .hero .dl");
    top.classList.toggle("past", !!dl && dl.getBoundingClientRect().bottom < 60);
  }
  window.addEventListener("scroll", onScroll, { passive: true });

  // Fade sections up as they come into view; count the stats up.
  function countUp(b) {
    var n = +b.dataset.count, t0 = performance.now();
    (function step() {
      var p = Math.min(1, (performance.now() - t0) / 900);
      b.textContent = Math.round(n * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    })();
  }
  var rv = $$(".rv");
  if ("IntersectionObserver" in window && !still) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add("in");
        var c = $("[data-count]", e.target);
        if (c) countUp(c);
        io.unobserve(e.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    rv.forEach(function (el) { io.observe(el); });
  } else rv.forEach(function (el) { el.classList.add("in"); });

  // The search tile types a few searches.
  var typer = $("#typer");
  if (typer) {
    var words = ["air horn", "vine boom", "sad violin", "bruh"], wi = 0, ci = typer.textContent.length, dir = -1;
    (function type() {
      var w = words[wi];
      ci += dir;
      typer.textContent = w.slice(0, ci);
      var wait = dir > 0 ? 90 : 45;
      if (dir > 0 && ci >= w.length) { dir = -1; wait = 2200; }
      else if (dir < 0 && ci <= 0) { dir = 1; wi = (wi + 1) % words.length; wait = 300; }
      setTimeout(type, wait);
    })();
  }

  // "what to set": open that question, then go to it.
  $$("[data-open]").forEach(function (a) {
    a.addEventListener("click", function () {
      var d = $(a.getAttribute("href"));
      if (d) d.open = true;
    });
  });

  // Copy the winget line.
  $$("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      var text = $("#" + b.getAttribute("data-copy")).textContent;
      did("copy-" + b.getAttribute("data-copy"));
      var done = function () { b.textContent = "Copied ✓"; setTimeout(function () { b.textContent = "Copy"; }, 1600); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () {});
    });
  });

  // Which questions get opened, which links get followed (downloads count themselves:
  // data-goatcounter-click), and how far down each tab people read.
  panels.forEach(function (p) {
    $$(".faq details", p).forEach(function (d, i) {
      d.addEventListener("toggle", function () { if (d.open) did("faq-" + p.dataset.panel + "-" + (i + 1)); });
    });
  });
  var LINKS = [[/virustotal\.com/, "virustotal"], [/releases\/latest$/, "whats-new"], [/releases$/, "releases"],
    [/\/issues/, "issues"], [/FEATURES\.md/, "features"], [/SECURITY\.md/, "security"], [/discord\.gg/, "discord"],
    [/tally\.so/, "feedback"], [/github\.com\/Onion-Alien\/onion-watch$/, "watch-source"],
    [/github\.com\/Onion-Alien\/onion-board$/, "source"], [/onion-alien\.github\.io\/onion-watch/, "watch-site"]];
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || a.hasAttribute("data-goatcounter-click")) return;
    var h = a.getAttribute("href"), name = "";
    if (a.hasAttribute("data-tab-link")) name = "cross-" + a.getAttribute("data-tab-link");
    else if (h.charAt(0) === "#") name = "jump-" + (h.slice(1) || "top");
    else if (/^[\w-]+\/$/.test(h)) name = "guide-" + h.slice(0, -1);
    else for (var i = 0; i < LINKS.length && !name; i++) if (LINKS[i][0].test(h)) name = LINKS[i][1];
    did("link-" + (name || "other"));
  });
  var deepest = {};
  window.addEventListener("scroll", function () {
    var tab = current(), max = document.documentElement.scrollHeight - innerHeight;
    if (max < 200) return;
    var p = Math.floor(scrollY / max * 4) * 25;      // 25, 50, 75, 100 (%)
    for (var q = (deepest[tab] || 0) + 25; q <= p; q += 25) did("scroll-" + tab + "-" + q);
    deepest[tab] = Math.max(deepest[tab] || 0, p);
  }, { passive: true });

  // ------------------------------------------------------------------ the look
  // The apps' own themes: each swaps every screenshot for the same one in that theme
  // (screenshots/themes/<theme>/, made by scripts/pictures/site_themes.py) and tints the
  // page to match. The default pictures stay the plain .png ones search engines index.
  var lookBtn = $("#look"), lookMenu = $("#look-menu");
  var looks = $$("#look-menu button");
  var SHOT = /screenshots\/(watch\/)?(sounds|voice|triggers|apps|setup|main|window-picker|cut-picture|health-bar|categories)\.png/;
  var shots = $$("img").filter(function (img) {
    var m = SHOT.exec(img.getAttribute("src") || "");
    if (m) { img.dataset.base = img.getAttribute("src"); img.dataset.pic = (m[1] || "") + m[2]; }
    return !!m;
  });
  var VARS = ["--bg", "--bg2", "--a1", "--a2", "--link", "--tex", "--tex-size"];
  function lookMenuOpen(open) {
    lookMenu.hidden = !open;
    lookBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  function setLook(btn, quiet) {
    var name = btn.dataset.theme, v = btn.dataset.v, vars = btn.dataset.vars || "";
    VARS.forEach(function (k) { root.style.removeProperty(k); });
    vars.split(";").forEach(function (kv) { if (kv) { kv = kv.split(":"); root.style.setProperty(kv[0], kv[1]); } });
    root.classList.toggle("textured", vars.indexOf("--tex:") >= 0);
    root.dataset.look = name;      // Bun and Hoot wear its outfit (home.css .fit)
    looks.forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
    lookBtn.title = "Change the look: " + btn.textContent;
    lookBtn.setAttribute("aria-label", lookBtn.title);
    shots.forEach(function (img) {
      var src = v ? "screenshots/themes/" + name + "/" + img.dataset.pic + ".webp?v=" + v : img.dataset.base;
      img.dataset.want = src;     // the newest pick wins, however the downloads finish
      if (img.getAttribute("src") === src) return;
      var next = new Image();     // swap once it's loaded, so the old one shows until then
      next.onload = function () { if (img.dataset.want === src) img.src = src; };
      next.onerror = function () { if (img.dataset.want === src) img.src = img.dataset.base; };
      next.src = src;
    });
    save("onion-site-look", v ? JSON.stringify({ name: name, vars: vars }) : "");
    if (!quiet) did("look-" + name);
  }
  if (lookBtn && looks.length) {
    var saved = null;
    try { saved = JSON.parse(load("onion-site-look") || "null"); } catch (e) { /* an old value */ }
    setLook(looks.filter(function (b) { return saved && b.dataset.theme === saved.name; })[0] || looks[0], true);
    lookBtn.addEventListener("click", function () { lookMenuOpen(lookMenu.hidden); });
    looks.forEach(function (b) {
      b.addEventListener("click", function () { setLook(b); lookMenuOpen(false); lookBtn.focus(); });
    });
    document.addEventListener("click", function (e) {
      if (!lookMenu.hidden && !e.target.closest(".looks")) lookMenuOpen(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !lookMenu.hidden) { lookMenuOpen(false); lookBtn.focus(); }
    });
  }

  // ------------------------------------------------------------------ the app demo
  // The big Board screenshot becomes a clickable copy of the app. Its files (data, code,
  // look) load only when the showcase comes near; if they can't load, the screenshot stays.
  $$(".showcase[data-demo]").forEach(function (box) {
    var v = box.getAttribute("data-v") || "";
    function go() {
      var files = ["board-demo-data.js", "board-demo.js"], css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "board-demo.css?v=" + v;
      function next() {
        var f = files.shift();
        if (!f) { if (window.OnionBoardDemo) window.OnionBoardDemo.mount(box); return; }
        var js = document.createElement("script");
        js.src = f + "?v=" + v;
        js.onload = next;
        document.body.appendChild(js);
      }
      css.onload = next;
      document.head.appendChild(css);
    }
    if (!("IntersectionObserver" in window)) return go();
    var io = new IntersectionObserver(function (es) {
      if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); go(); }
    }, { rootMargin: "900px 0px" });
    io.observe(box);
  });

  apply(location.hash === "#watch" ? "watch" : "board");
  did("open-" + current());       // which tab they landed on
})();
