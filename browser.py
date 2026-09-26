"""Browser tab: a built-in web browser whose audio goes out through your mic.

Every <audio>/<video> a page plays is tapped with WebAudio and streamed to
Python over QWebChannel as 16-bit PCM at 48 kHz. The tap runs in an isolated
JS world, so pages can't see it, break it, or push audio into the mic
themselves. Chromium's own output stays silent. The engine plays the audio in
your headphones and, while you're live, into the virtual cable, which makes it
come out of your mic. Nothing has to be downloaded first.

The same stream feeds a recorder. ⏺ records until you stop it, and ⏪ saves the
last CLIP_S seconds, so you can grab a moment after it happened. Clips are
added to the Sounds tab as ordinary pads.
"""
from __future__ import annotations

import base64
import json
import re
import time

import numpy as np
from PySide6.QtCore import QFile, QIODevice, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QFontMetrics
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                     QWebEngineSettings)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QVBoxLayout, QWidget)
from shiboken6 import delete as qt_delete

from engine import SR
from library import APP_DIR, MAX_SECONDS, trim_silence

CLIP_S = 15            # "clip the last N seconds" length
LIVE_TEXT = {True: "🔴  LIVE — others hear it", False: "🎧  Only me — click to go live"}
WORLD = QWebEngineScript.ApplicationWorld

QUICK_LINKS = (("YouTube", "https://www.youtube.com/"),
               ("SoundCloud", "https://soundcloud.com/"),
               ("MyInstants", "https://www.myinstants.com/"))

# Runs in every page (isolated world). Taps media elements and ships their audio out.
TAP_JS = r"""
(function () {
  if (window.__sbTap) return;
  window.__sbTap = true;
  const SR = 48000, BLOCK = 1024;           // ~21 ms per chunk
  let bridge = null, ctx = null, input = null, lastOn = -1, lastOff = -1, playing = 0;
  const tapped = new WeakSet();

  new QWebChannel(qt.webChannelTransport, ch => { bridge = ch.objects.sb; scan(); });

  function b64(i16) {
    const u8 = new Uint8Array(i16.buffer);
    let s = '';
    for (let i = 0; i < u8.length; i += 0x8000)
      s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(s);
  }

  function context() {
    if (ctx) return ctx;
    ctx = new AudioContext({ sampleRate: SR, latencyHint: 'interactive' });
    input = ctx.createGain();
    const sp = ctx.createScriptProcessor(BLOCK, 2, 2);
    sp.onaudioprocess = e => {
      // leave the output silent: the soundboard plays this audio, not Chromium
      for (let c = 0; c < e.outputBuffer.numberOfChannels; c++)
        e.outputBuffer.getChannelData(c).fill(0);
      const L = e.inputBuffer.getChannelData(0), R = e.inputBuffer.getChannelData(1);
      const out = new Int16Array(L.length * 2);
      let loud = false;
      for (let i = 0; i < L.length; i++) {
        const l = Math.max(-1, Math.min(1, L[i])), r = Math.max(-1, Math.min(1, R[i]));
        if (l !== 0 || r !== 0) loud = true;
        out[2 * i] = l * 32767;
        out[2 * i + 1] = r * 32767;
      }
      // while tapped media plays, quiet passages are sent too, so the stream stays
      // continuous (no re-buffering delay after a pause in the audio); nothing is
      // sent while everything is paused
      if (bridge && (loud || playing)) bridge.pcm(b64(out));
    };
    input.connect(sp);
    sp.connect(ctx.destination);
    return ctx;
  }

  // Media from another site without CORS would come out of WebAudio as silence,
  // so those are left alone (they play normally, just not into the mic).
  function capturable(el) {
    if (el.srcObject) return false;
    const src = el.currentSrc || el.src || '';
    if (!src) return false;
    if (/^(blob|data):/.test(src)) return true;
    try { if (new URL(src, location.href).origin === location.origin) return true; } catch (e) {}
    return el.crossOrigin !== null;
  }

  function tap(el) {
    if (!bridge || tapped.has(el) || !capturable(el)) return;
    try {
      context().createMediaElementSource(el).connect(input);
      tapped.add(el);
    } catch (e) {}
  }

  function scan() {
    let on = 0, off = 0, live = 0;
    document.querySelectorAll('audio,video').forEach(el => {
      if (el.paused) return;
      tap(el);
      if (tapped.has(el)) live++;
      if (!el.muted) tapped.has(el) ? on++ : off++;
    });
    playing = live;
    if (ctx && ctx.state !== 'running' && on) ctx.resume();
    if (bridge && (on !== lastOn || off !== lastOff)) {
      lastOn = on; lastOff = off;
      bridge.report(on, off);
    }
  }

  for (const ev of ['play', 'playing', 'pause', 'ended', 'loadedmetadata'])
    document.addEventListener(ev, () => setTimeout(scan, 0), true);
  setInterval(scan, 1000);
})();
"""

PAUSE_JS = "document.querySelectorAll('audio,video').forEach(e => e.pause());"

# ---- Lite mode
# YouTube's quality API only exists in the page's own JS world, so this small script
# runs there. It only calls the player's own setPlaybackQualityRange, and only while
# <html data-sb-lite="1"> (set from Python, since the two JS worlds share the DOM).
LITE_JS = r"""
(function () {
  if (window.__sbLite) return;
  window.__sbLite = true;
  let forced = false;
  function apply() {
    const p = document.getElementById('movie_player');
    if (!p || !p.setPlaybackQualityRange) return;
    const want = document.documentElement.dataset.sbLite === '1';
    try {
      if (want) { p.setPlaybackQualityRange('tiny', 'tiny'); forced = true; }
      else if (forced) { p.setPlaybackQualityRange('auto', 'auto'); forced = false; }
    } catch (e) {}
  }
  setInterval(apply, 1500);
  document.addEventListener('yt-navigate-finish', () => setTimeout(apply, 300));
})();
"""


def set_lite_js(on: bool) -> str:
    return f"document.documentElement.dataset.sbLite = '{1 if on else 0}';"


# the element the mini-player controls: whatever is playing, else the last one played
_MEDIA = ("const a=[...document.querySelectorAll('video,audio')];"
          "const m=a.find(e=>!e.paused)||a.find(e=>e.currentTime>0)||a[0];")
# returned as JSON text: PySide6 can't hand JS arrays/objects back to Python (they arrive as '')
MINI_STATE_JS = ("(()=>{" + _MEDIA + "if(!m)return '';"
                 "const t=document.querySelector('h1.ytd-watch-metadata, #title h1');"
                 "return JSON.stringify([m.currentTime||0, isFinite(m.duration)?m.duration:0, m.paused,"
                 "(t&&t.textContent.trim())||document.title]);})()")
MINI_TOGGLE_JS = "(()=>{" + _MEDIA + "if(m){m.paused?m.play():m.pause()}})()"
MINI_SEEK_JS = "(()=>{" + _MEDIA + "if(m)m.currentTime=Math.max(0,m.currentTime+(%d))})()"
MINI_NEXT_JS = ("(()=>{const b=document.querySelector('.ytp-next-button');"
                "if(b&&b.offsetParent!==null){b.click();return true}"
                "const n=document.querySelector('a.ytp-next-button');if(n){n.click();return true}"
                "return false})()")


def _qrc_text(path: str) -> str:
    f = QFile(path)
    if not f.open(QIODevice.ReadOnly):
        raise RuntimeError(f"can't open {path}")
    try:
        return bytes(f.readAll()).decode("utf-8")
    finally:
        f.close()


class _Bridge(QObject):
    """The object pages talk to (as `sb`). Slots run on the UI thread."""
    audio = Signal(object)        # (n, 2) float32 at SR
    status = Signal(int, int)     # playing media: tapped, can't-tap

    @Slot(str)
    def pcm(self, b64: str):
        try:
            raw = base64.b64decode(b64)
        except ValueError:
            return
        x = np.frombuffer(raw, np.int16)
        if len(x) % 2:
            return
        self.audio.emit(x.reshape(-1, 2).astype(np.float32) / 32768.0)

    @Slot(int, int)
    def report(self, on: int, off: int):
        self.status.emit(on, off)


class _Page(QWebEnginePage):
    def createWindow(self, _type):
        return self   # pop-ups and target=_blank links open in the same tab


class Recorder:
    """Keeps a rolling CLIP_S-second replay buffer, plus a manual recording."""

    def __init__(self):
        self.replay = np.zeros((CLIP_S * SR, 2), np.float32)
        self.w = 0
        self.filled = 0
        self.rec: list[np.ndarray] | None = None
        self.rec_frames = 0

    def push(self, x: np.ndarray):
        n = len(x)
        cap = len(self.replay)
        if n >= cap:
            x, n = x[-cap:], cap
        end = self.w + n
        if end <= cap:
            self.replay[self.w:end] = x
        else:
            k = cap - self.w
            self.replay[self.w:] = x[:k]
            self.replay[:n - k] = x[k:]
        self.w = end % cap
        self.filled = min(self.filled + n, cap)
        if self.rec is not None and self.rec_frames < MAX_SECONDS * SR:
            self.rec.append(x.copy())
            self.rec_frames += n

    def last(self) -> np.ndarray:
        if self.filled < len(self.replay):
            return self.replay[:self.filled].copy()
        return np.concatenate([self.replay[self.w:], self.replay[:self.w]])

    def start(self):
        self.rec, self.rec_frames = [], 0

    def stop(self) -> np.ndarray:
        rec, self.rec = self.rec or [], None
        return np.concatenate(rec) if rec else np.zeros((0, 2), np.float32)

    @property
    def recording(self) -> bool:
        return self.rec is not None


class BrowserTab(QWidget):
    clip_ready = Signal(object, str)     # audio, suggested name

    def __init__(self, engine, cfg, save_cb, meter_cls):
        super().__init__()
        self.engine, self.cfg, self._save = engine, cfg, save_cb
        self.recorder = Recorder()
        self.view: QWebEngineView | None = None
        self.profile: QWebEngineProfile | None = None
        self._status = (0, 0)
        self._flash_until = 0.0
        self._collapsed = False    # Lite: page hidden, mini-player shown
        self._mini_poll = 0.0

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # ---- navigation
        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.btn_back = QPushButton("◀")
        self.btn_fwd = QPushButton("▶")
        self.btn_reload = QPushButton("⟳")
        for b, tip in ((self.btn_back, "Back"), (self.btn_fwd, "Forward"),
                       (self.btn_reload, "Reload")):
            b.setObjectName("round")
            b.setFixedSize(36, 32)
            b.setToolTip(tip)
            nav.addWidget(b)
        self.url = QLineEdit()
        self.url.setPlaceholderText("Search or type a web address…")
        self.url.returnPressed.connect(self._go)
        nav.addWidget(self.url, 1)
        for label, link in QUICK_LINKS:
            b = QPushButton(label)
            b.setObjectName("small")
            b.clicked.connect(lambda _=False, u=link: self.load(u))
            nav.addWidget(b)
        v.addLayout(nav)

        # ---- live / volume / record bar
        bar = QFrame()
        bar.setObjectName("transport")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(10, 8, 12, 8)
        bh.setSpacing(10)
        self.btn_live = QPushButton()
        self.btn_live.setObjectName("live")
        self.btn_live.setCheckable(True)
        # wide enough for both labels (bold), so the bar doesn't jump when it toggles
        self.btn_live.ensurePolished()   # pick up the stylesheet font first
        f = self.btn_live.font()
        f.setBold(True)
        fm = QFontMetrics(f)
        self.btn_live.setMinimumWidth(max(fm.horizontalAdvance(t) for t in LIVE_TEXT.values()) + 40)
        self.btn_live.toggled.connect(self._on_live)
        bh.addWidget(self.btn_live)

        bh.addWidget(QLabel("Volume"))
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 300)
        self.vol.setFixedWidth(110)
        self.vol.setToolTip("Browser volume (for them and for you)")
        self.vol_lbl = QLabel()
        self.vol_lbl.setFixedWidth(42)
        self.vol.valueChanged.connect(self._on_vol)
        bh.addWidget(self.vol)
        bh.addWidget(self.vol_lbl)

        self.chk_hear = QCheckBox("Hear it myself")
        self.chk_hear.toggled.connect(self._on_hear)
        bh.addWidget(self.chk_hear)

        self.meter = meter_cls()
        self.meter.setToolTip("Browser audio level")
        bh.addWidget(self.meter, 1)

        self.btn_rec = QPushButton("⏺  Record clip")
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip("Record what's playing in the browser. Click again to stop — "
                                "the clip is added to your Sounds.")
        self.btn_rec.toggled.connect(self._on_rec)
        bh.addWidget(self.btn_rec)
        self.btn_last = QPushButton(f"⏪  Clip last {CLIP_S}s")
        self.btn_last.setToolTip(f"Save the last {CLIP_S} seconds the browser played as a sound")
        self.btn_last.clicked.connect(self.clip_last)
        bh.addWidget(self.btn_last)
        self.btn_lite = QPushButton("🍃  Lite")
        self.btn_lite.setObjectName("lite")
        self.btn_lite.setCheckable(True)
        self.btn_lite.setToolTip("Lite mode — easy on your game: while something plays, the page "
                                 "is hidden (no video drawn or decoded) and YouTube drops to 144p. "
                                 "Audio is unaffected.")
        self.btn_lite.toggled.connect(self._on_lite)
        bh.addWidget(self.btn_lite)
        v.addWidget(bar)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setStyleSheet("color:#8a90a6;")
        v.addWidget(self.info)

        # ---- Lite mini-player (replaces the page while something plays)
        self.mini = QFrame()
        self.mini.setObjectName("transport")
        mv = QVBoxLayout(self.mini)
        mv.setContentsMargins(16, 14, 16, 14)
        mv.setSpacing(10)
        self.mini_title = QLabel("—")
        self.mini_title.setStyleSheet("font-size:12pt; font-weight:600;")
        self.mini_title.setWordWrap(True)
        mv.addWidget(self.mini_title)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.mini_btns = {}
        for key, text, tip in (("back", "⏪ 10s", "Back 10 seconds"),
                               ("play", "⏯", "Play / pause"),
                               ("fwd", "10s ⏩", "Forward 10 seconds"),
                               ("next", "⏭", "Next video (YouTube)")):
            b = QPushButton(text)
            b.setObjectName("round")
            b.setMinimumSize(56, 36)
            b.setToolTip(tip)
            row.addWidget(b)
            self.mini_btns[key] = b
        self.mini_btns["back"].clicked.connect(lambda: self._mini_js(MINI_SEEK_JS % -10))
        self.mini_btns["fwd"].clicked.connect(lambda: self._mini_js(MINI_SEEK_JS % 10))
        self.mini_btns["play"].clicked.connect(lambda: self._mini_js(MINI_TOGGLE_JS))
        self.mini_btns["next"].clicked.connect(lambda: self._mini_js(MINI_NEXT_JS))
        self.mini_time = QLabel("0:00 / 0:00")
        self.mini_time.setStyleSheet("color:#8a90a6;")
        row.addWidget(self.mini_time)
        row.addStretch(1)
        show = QPushButton("🔎  Show page")
        show.setToolTip("Bring the page back to pick something else. "
                        "It hides again when the next thing starts playing.")
        show.clicked.connect(lambda: self._set_collapsed(False))
        row.addWidget(show)
        mv.addLayout(row)
        hint = QLabel("🍃 Lite mode: the page is hidden while it plays, so it isn't drawing "
                      "or decoding video — easy on your game. Audio keeps going.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        mv.addWidget(hint)
        self.mini.hide()
        v.addWidget(self.mini)
        self.mini_spacer = QWidget()   # fills the space the page used
        self.mini_spacer.hide()
        v.addWidget(self.mini_spacer, 1)

        self.holder = QVBoxLayout()   # the web view goes here once the tab is first opened
        v.addLayout(self.holder, 1)

        # initial state (sets the engine too)
        self.btn_live.setChecked(cfg.browser_live)
        self._on_live(cfg.browser_live)
        self.vol.setValue(int(round(cfg.browser_vol * 100)))
        self._on_vol(self.vol.value())
        self.chk_hear.setChecked(cfg.browser_monitor)
        self._on_hear(cfg.browser_monitor)
        self.btn_lite.setChecked(cfg.browser_lite)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

    # ------------------------------------------------------------------ web view
    def showEvent(self, e):
        # created on first open, so the browser costs nothing until it's used
        # (main.py sets QT_WIDGETS_RHI so this doesn't rebuild the main window)
        super().showEvent(e)
        if self.view is None:
            self._make_view()
            self.load(self.cfg.browser_url or QUICK_LINKS[0][1])

    def _make_view(self):
        store = APP_DIR / "browser"
        self.profile = QWebEngineProfile("soundboard")   # named = logins/cookies persist
        self.profile.setPersistentStoragePath(str(store))
        self.profile.setCachePath(str(store / "cache"))

        self.view = QWebEngineView()
        page = _Page(self.profile, self.view)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
        s.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, False)

        self.bridge = _Bridge()
        self.bridge.audio.connect(self._on_audio)
        self.bridge.status.connect(self._on_status)
        self.channel = QWebChannel(page)
        self.channel.registerObject("sb", self.bridge)
        page.setWebChannel(self.channel, WORLD)

        for name, src in (("qwebchannel", _qrc_text(":/qtwebchannel/qwebchannel.js")),
                          ("sb-tap", TAP_JS)):
            sc = QWebEngineScript()
            sc.setName(name)
            sc.setSourceCode(src)
            sc.setWorldId(WORLD)
            sc.setInjectionPoint(QWebEngineScript.DocumentCreation)
            sc.setRunsOnSubFrames(False)
            page.scripts().insert(sc)
        sc = QWebEngineScript()
        sc.setName("sb-lite")
        sc.setSourceCode(LITE_JS)
        sc.setWorldId(QWebEngineScript.MainWorld)
        sc.setInjectionPoint(QWebEngineScript.DocumentReady)
        sc.setRunsOnSubFrames(False)
        page.scripts().insert(sc)
        page.loadFinished.connect(lambda _ok: self._push_lite())

        self.view.setPage(page)
        self.btn_back.clicked.connect(self.view.back)
        self.btn_fwd.clicked.connect(self.view.forward)
        self.btn_reload.clicked.connect(self.view.reload)
        self.view.urlChanged.connect(self._on_url)
        self.holder.addWidget(self.view)

    def load(self, url: str):
        if self.view is not None:
            self.view.setUrl(QUrl(url))

    def _go(self):
        t = self.url.text().strip()
        if not t:
            return
        if re.match(r"^[a-z]+://", t, re.I):
            url = QUrl(t)
        elif "." in t and " " not in t:
            url = QUrl("https://" + t)
        else:
            url = QUrl("https://www.youtube.com/results")
            url.setQuery("search_query=" + QUrl.toPercentEncoding(t).data().decode())
        if self.view is not None:
            self.view.setUrl(url)
            self.view.setFocus()

    def _on_url(self, url: QUrl):
        s = url.toString()
        self.url.setText(s)
        self.url.setCursorPosition(0)
        if url.scheme() in ("http", "https"):
            self.cfg.browser_url = s
            self._save()

    def pause_media(self):
        if self.view is not None:
            self.view.page().runJavaScript(PAUSE_JS, WORLD)

    def shutdown(self):
        if self.view is not None:
            page = self.view.page()
            self.view.setParent(None)
            qt_delete(page)   # pages must go before their profile
            self.view = None

    # ------------------------------------------------------------------ audio
    def _on_audio(self, x: np.ndarray):
        self.engine.feed_browser(x)
        self.recorder.push(x)

    def _on_status(self, on: int, off: int):
        started = on > 0 and self._status[0] == 0
        self._status = (on, off)
        self._refresh_info()
        if started and self.cfg.browser_lite:
            self._set_collapsed(True)   # something started playing: hide the page

    # ------------------------------------------------------------------ lite mode
    def _on_lite(self, on: bool):
        self.cfg.browser_lite = on
        self._save()
        self._push_lite()
        self._set_collapsed(on and self._status[0] > 0)

    def _push_lite(self):
        if self.view is not None:
            self.view.page().runJavaScript(set_lite_js(self.cfg.browser_lite), WORLD)

    def _set_collapsed(self, on: bool):
        """Lite: swap the page for the mini-player. A hidden page isn't drawn, and
        Chromium stops decoding the video track of hidden players, so the browser
        costs little more than its audio."""
        self._collapsed = on
        if self.view is not None:
            self.view.setVisible(not on)
        self.mini.setVisible(on)
        self.mini_spacer.setVisible(on)
        if on:
            self._mini_poll = 0.0
            self._poll_mini()

    def _mini_js(self, js: str):
        if self.view is not None:
            self.view.page().runJavaScript(js, WORLD)
            QTimer.singleShot(150, self._poll_mini)

    def _poll_mini(self):
        if self.view is not None and self._collapsed:
            self.view.page().runJavaScript(MINI_STATE_JS, WORLD, self._on_mini_state)

    def _on_mini_state(self, st):
        try:
            pos, dur, paused, title = json.loads(st)
        except (TypeError, ValueError):
            return   # nothing playing / page not ready
        title = re.sub(r"^\(\d+\)\s*", "", str(title or ""))
        title = re.sub(r"\s*[-–|]\s*(YouTube|SoundCloud)$", "", title).strip()
        self.mini_title.setText(title or "Playing")
        fmt = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"   # noqa: E731
        self.mini_time.setText(f"{fmt(pos)} / {fmt(dur)}" if dur else fmt(pos))
        self.mini_btns["play"].setText("▶" if paused else "⏸")

    def _refresh_info(self, msg: str = ""):
        if msg:
            self._flash_until = time.monotonic() + 5
            self.info.setText(msg)
            return
        if time.monotonic() < self._flash_until:
            return
        on, off = self._status
        live = self.cfg.browser_live
        if off and not on:
            self.info.setText("<span style='color:#ffb020'>⚠ This page's audio can't be "
                              "routed (it's served from another site). You hear it, but it "
                              "won't go through your mic or into recordings.</span>")
        elif on:
            self.info.setText("<span style='color:#ff4d4f'>● Others can hear this page.</span>"
                              if live else
                              "Playing to <b>your headphones only</b>. Turn on LIVE to send "
                              "it through your mic.")
        else:
            self.info.setText("Play anything (YouTube, SoundCloud, a clip site…) and it goes "
                              "straight out through your mic. "
                              + ("<b style='color:#ff4d4f'>LIVE is on.</b>" if live else
                                 "LIVE is off: only you hear it."))

    # ------------------------------------------------------------------ controls
    def _on_live(self, on: bool):
        self.cfg.browser_live = on
        self.engine.browser_live = on
        self.btn_live.setText(LIVE_TEXT[on])
        self._refresh_info()
        self._save()

    def _on_vol(self, pct: int):
        self.vol_lbl.setText(f"{pct}%")
        self.cfg.browser_vol = pct / 100
        self.engine.browser_vol = pct / 100
        self._save()

    def _on_hear(self, on: bool):
        self.cfg.browser_monitor = on
        self.engine.browser_monitor = on
        self._save()

    def _on_rec(self, on: bool):
        if on:
            self.recorder.start()
            return
        self.btn_rec.setText("⏺  Record clip")
        self._emit_clip(self.recorder.stop(), "Nothing was playing while you recorded.")

    def clip_last(self):
        self._emit_clip(self.recorder.last(),
                        f"Nothing has played in the last {CLIP_S} seconds.")

    def _emit_clip(self, data: np.ndarray, empty_msg: str):
        data = trim_silence(data)
        if len(data) < int(0.2 * SR):
            self._refresh_info(f"<span style='color:#ffb020'>{empty_msg}</span>")
            return
        self.clip_ready.emit(data, self._clip_name())
        self._refresh_info(f"<span style='color:#13ce66'>✓ Saved a {len(data) / SR:.1f}s clip "
                           "to your Sounds.</span>")

    def _clip_name(self) -> str:
        title = self.view.title() if self.view is not None else ""
        title = re.sub(r"^\(\d+\)\s*", "", title)                       # "(3) " unread counts
        title = re.sub(r"\s*[-–|]\s*(YouTube|SoundCloud)$", "", title).strip()
        return f"{title[:30] or 'Clip'} {time.strftime('%H.%M.%S')}"

    def _tick(self):
        e = self.engine
        self.meter.set_level(e.level_browser)
        e.level_browser *= 0.8
        if self._collapsed and time.monotonic() - self._mini_poll >= 1.0:
            self._mini_poll = time.monotonic()
            self._poll_mini()
        if self.recorder.recording:
            secs = self.recorder.rec_frames / SR
            self.btn_rec.setText(f"⏹  Stop  ({int(secs // 60)}:{int(secs % 60):02d})")
            if secs >= MAX_SECONDS:
                self.btn_rec.setChecked(False)
        elif time.monotonic() >= self._flash_until and self._flash_until:
            self._flash_until = 0.0
            self._refresh_info()
