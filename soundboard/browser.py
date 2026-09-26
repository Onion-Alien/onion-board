"""Browser tab: a built-in web browser whose audio goes out through your mic.

Every <audio>/<video> a page plays is tapped with WebAudio (an AudioWorklet on
the audio thread; ScriptProcessor as a fallback) and streamed to Python as raw
16-bit PCM at 48 kHz over a WebSocket on 127.0.0.1 with a per-launch secret in
its URL. Binary frames go straight into numpy: no base64, no JSON, no
QWebChannel. The tap runs in an isolated JS world in every frame (embedded
players too), so pages can't see it, break it, or push audio into the mic
themselves. Chromium's own output stays silent. The engine plays the audio in
your headphones and, while you're live, into the virtual cable, which makes it
come out of your mic. Nothing has to be downloaded first.

When two frames play at once, the one that started first owns the mic until it
goes quiet for a moment; the other is heard by nobody (it's reported, not mixed).

The same stream feeds a recorder. ⏺ records until you stop it, and ⏪ saves the
last CLIP_S seconds, so you can grab a moment after it happened. Clips are
added to the Sounds tab as ordinary pads.

"Add as sound" downloads the audio of the page itself (a YouTube video, a
SoundCloud track…) with yt-dlp and adds it whole; see ytdl.py.

The browser only goes to the sites in ALLOWED_SITES (YouTube, SoundCloud and the
big sound-clip sites): QtWebEngine has no Safe Browsing, so instead of guarding
the whole web it doesn't go there. Pages on those sites still load their images,
scripts and videos from wherever they like; only the page itself is limited. File
downloads are never accepted (nothing handles `downloadRequested`).
"""
from __future__ import annotations

import html
import json
import logging
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable

import numpy as np
import soundfile as sf
from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QHostAddress, QNetworkAccessManager, QNetworkRequest
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                     QWebEngineSettings)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebSockets import QWebSocket, QWebSocketServer
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QStyle, QVBoxLayout, QWidget)
from shiboken6 import delete as qt_delete
from shiboken6 import isValid as qt_valid

from soundboard.adblocker import YOUTUBE_JS, AdBlocker, hide_css_js
from soundboard.engine import SR
from soundboard import thumbs, ytdl
from soundboard.library import (APP_DIR, MAX_SECONDS, PAD_COLORS, fingerprint, import_file,
                                trim_silence)
from soundboard.ui import icons
from soundboard.ui.panel import VolumeControl, bar, icon_label, vsep
from soundboard.ui.speedpitch import SpeedPitchButton

log = logging.getLogger(__name__)

CLIP_S = 15            # "clip the last N seconds" length
SPOOL_PATH = APP_DIR / "recording.tmp.wav"
LIVE_TEXT = {True: "LIVE — others hear it", False: "Only me — click to go live"}
LIVE_SHORT = {True: "LIVE", False: "Only me"}   # a narrow window
WORLD = QWebEngineScript.ApplicationWorld
BLOCK = 1024           # frames per chunk (~21 ms): the same for worklet and fallback
HANDOVER_S = 0.3       # a frame keeps the mic until it's been quiet this long

QUICK_LINKS = (("YouTube", "https://www.youtube.com/"),
               ("SoundCloud", "https://soundcloud.com/"),
               ("MyInstants", "https://www.myinstants.com/"))

# Sites the browser will open, subdomains included. Links anywhere else are refused.
ALLOWED_SITES = (
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "soundcloud.com", "tiktok.com",
    "myinstants.com", "101soundboards.com", "voicy.network", "tuna.voicemod.net",
    "freesound.org", "zapsplat.com", "soundbible.com", "pixabay.com", "mixkit.co",
    "orangefreesounds.com", "bandcamp.com",
)
# single hosts rather than whole sites: signing in to YouTube goes through these
ALLOWED_HOSTS = ("accounts.google.com", "accounts.youtube.com", "consent.google.com")


def site_allowed(url: QUrl) -> bool:
    """Whether the browser may open `url` as a page: one of ALLOWED_SITES over http(s),
    or something local (about:blank, a file already on this PC)."""
    if url.scheme() in ("about", "file"):
        return True
    if url.scheme() not in ("http", "https"):
        return False
    host = url.host().lower().rstrip(".")
    return host in ALLOWED_HOSTS or any(host == d or host.endswith("." + d)
                                        for d in ALLOWED_SITES)

# Runs on the audio rendering thread. Collects BLOCK stereo frames as int16 and
# posts them (transferred, no copy) to the page thread, which sends them over the
# socket. Its output is left silent: the soundboard plays this audio, not Chromium.
# While tapped media plays, quiet passages are sent too, so the stream stays
# continuous (no re-buffering delay after a pause in the audio); nothing is sent
# while everything is paused.
WORKLET_JS = r"""
class SbTap extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Int16Array(BLOCK * 2); this.n = 0; this.loud = false; this.playing = 0;
    this.port.onmessage = e => { this.playing = e.data; };
  }
  process(inputs) {
    const inp = inputs[0];
    if (!inp || !inp.length) return true;
    const L = inp[0], R = inp.length > 1 ? inp[1] : inp[0];
    for (let i = 0; i < L.length; i++) {
      const l = Math.max(-1, Math.min(1, L[i])), r = Math.max(-1, Math.min(1, R[i]));
      if (l !== 0 || r !== 0) this.loud = true;
      this.buf[this.n++] = l * 32767;
      this.buf[this.n++] = r * 32767;
      if (this.n === this.buf.length) {
        if (this.loud || this.playing) {
          const out = this.buf.slice();
          this.port.postMessage(out.buffer, [out.buffer]);
        }
        this.n = 0; this.loud = false;
      }
    }
    return true;
  }
}
registerProcessor('sb-tap', SbTap);
""".replace("BLOCK", str(BLOCK))

# Runs in every frame of every page (isolated world). Taps media elements and ships
# their audio to the sink. %(url)s is the sink's ws://127.0.0.1:port/secret.
TAP_JS = r"""
(function () {
  if (window.__sbTap) return;
  window.__sbTap = true;
  const SR = 48000, BLOCK = %(block)d, WS_URL = %(url)s;
  const WORKLET = %(worklet)s;
  let ws = null, ctx = null, input = null, node = null, sp = null;
  let lastOn = -1, lastOff = -1, lastVideo = -1, playing = 0;
  let rate = 1, keep = true, forced = false;   // live speed from the soundboard
  const tapped = new WeakSet();

  function connect() {
    try { ws = new WebSocket(WS_URL); } catch (e) { ws = null; setTimeout(connect, 3000); return; }
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => { lastOn = lastOff = lastVideo = -1; scan(); };
    ws.onmessage = e => {
      if (e.data === 'pause') document.querySelectorAll('audio,video').forEach(el => el.pause());
      else if (typeof e.data === 'string' && e.data.startsWith('rate ')) {
        const p = e.data.split(' ');
        rate = Math.min(4, Math.max(0.25, parseFloat(p[1]) || 1));
        keep = p[2] !== '0';
        forced = true;   // apply once even when it's back to normal
        applyRate();
      }
    };
    ws.onclose = () => { ws = null; setTimeout(connect, 2000); };
    ws.onerror = () => {};
  }
  const ready = () => ws !== null && ws.readyState === 1;
  function send(data) { if (ready()) ws.send(data); }
  connect();

  let making = null;
  function context() {
    if (making) return making;
    making = (async () => {
      ctx = new AudioContext({ sampleRate: SR, latencyHint: 'interactive' });
      input = ctx.createGain();
      try {
        const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
        await ctx.audioWorklet.addModule(url);
        node = new AudioWorkletNode(ctx, 'sb-tap', {
          numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2],
          channelCount: 2, channelCountMode: 'explicit', channelInterpretation: 'speakers' });
        node.port.onmessage = e => send(e.data);
        node.port.postMessage(playing);
        input.connect(node);
        node.connect(ctx.destination);
      } catch (e) {
        // no worklet (a page CSP forbids blob: scripts, say): ScriptProcessor on the
        // page thread does the same job, a little less smoothly
        node = null;
        sp = ctx.createScriptProcessor(BLOCK, 2, 2);
        sp.onaudioprocess = ev => {
          for (let c = 0; c < ev.outputBuffer.numberOfChannels; c++)
            ev.outputBuffer.getChannelData(c).fill(0);
          const L = ev.inputBuffer.getChannelData(0), R = ev.inputBuffer.getChannelData(1);
          const out = new Int16Array(L.length * 2);
          let loud = false;
          for (let i = 0; i < L.length; i++) {
            const l = Math.max(-1, Math.min(1, L[i])), r = Math.max(-1, Math.min(1, R[i]));
            if (l !== 0 || r !== 0) loud = true;
            out[2 * i] = l * 32767;
            out[2 * i + 1] = r * 32767;
          }
          if (loud || playing) send(out.buffer);
        };
        input.connect(sp);
        sp.connect(ctx.destination);
      }
      return ctx;
    })();
    return making;
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

  async function tap(el) {
    if (!ready() || tapped.has(el) || !capturable(el)) return;
    tapped.add(el);   // createMediaElementSource may only ever be called once per element
    try {
      const c = await context();
      c.createMediaElementSource(el).connect(input);
    } catch (e) { tapped.delete(el); }
  }

  // Only forced while it isn't normal speed, so the site's own speed menu still
  // works the rest of the time. Re-applied on every scan: new videos pick it up.
  function applyRate() {
    if (!forced && rate === 1 && keep) return;
    forced = false;
    document.querySelectorAll('audio,video').forEach(el => {
      try {
        if (el.playbackRate !== rate) el.defaultPlaybackRate = el.playbackRate = rate;
        if (el.preservesPitch !== keep) el.preservesPitch = keep;
      } catch (e) {}
    });
  }

  function scan() {
    applyRate();
    let on = 0, off = 0, live = 0, video = 0;
    document.querySelectorAll('audio,video').forEach(el => {
      if (el.paused) return;
      tap(el);
      if (tapped.has(el)) live++;
      if (!el.muted) tapped.has(el) ? on++ : off++;
      if (el.tagName === 'VIDEO') video++;
    });
    playing = live;
    if (node) node.port.postMessage(playing);
    if (ctx && ctx.state !== 'running' && on) ctx.resume();
    if (ready() && (on !== lastOn || off !== lastOff || video !== lastVideo)) {
      lastOn = on; lastOff = off; lastVideo = video;
      send(JSON.stringify({ on: on, off: off, video: video }));
    }
  }

  for (const ev of ['play', 'playing', 'pause', 'ended', 'loadedmetadata'])
    document.addEventListener(ev, () => setTimeout(scan, 0), true);
  setInterval(scan, 1000);
})();
"""


# Runs in every frame's own JS world. Sound-button sites (MyInstants…) play through
# `new Audio()` elements that are never put in the page, so the tap can't find them.
# Just before one plays, it's moved into a hidden holder in the page (that doesn't
# interrupt it), and taken out again when it ends so they don't pile up.
ADOPT_JS = r"""
(function () {
  if (window.__sbAdopt) return;
  window.__sbAdopt = true;
  const P = HTMLMediaElement.prototype, play = P.play;
  let box = null;
  function done() { if (this.parentNode === box) box.removeChild(this); }
  P.play = function () {
    try {
      if (!this.isConnected) {
        if (!box || !box.isConnected) {
          box = document.createElement('div');
          box.hidden = true;
          (document.body || document.documentElement).appendChild(box);
        }
        box.appendChild(this);
        this.addEventListener('ended', done, { once: true });
      }
    } catch (e) {}
    return play.apply(this, arguments);
  };
})();
"""


def tap_script(url: str) -> str:
    return TAP_JS % {"block": BLOCK, "url": json.dumps(url), "worklet": json.dumps(WORKLET_JS)}


PAUSE_JS = "document.querySelectorAll('audio,video').forEach(e => e.pause());"


def rate_message(speed: float, keep_pitch: bool) -> str:
    """The tap script's live-speed command: 'rate <speed> <keep pitch 1/0>'."""
    return f"rate {min(max(speed, 0.25), 4.0):g} {1 if keep_pitch else 0}"

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
# [position, duration, paused, title, channel]. On YouTube the document title is
# used: the <h1> can still hold the previous video's title after an in-page navigation.
MINI_STATE_JS = ("(()=>{" + _MEDIA + "if(!m)return '';"
                 "const yt=/(^|\\.)youtube\\.com$/.test(location.hostname);"
                 "const t=yt?null:document.querySelector('h1');"
                 "const c=document.querySelector('#owner ytd-channel-name a, "
                 "ytd-video-owner-renderer #channel-name a');"
                 "return JSON.stringify([m.currentTime||0, isFinite(m.duration)?m.duration:0, "
                 "m.paused, (t&&t.textContent.trim())||document.title, "
                 "(c&&c.textContent.trim())||'']);})()")
MINI_TOGGLE_JS = "(()=>{" + _MEDIA + "if(m){m.paused?m.play():m.pause()}})()"
MINI_SEEK_JS = "(()=>{" + _MEDIA + "if(m)m.currentTime=Math.max(0,m.currentTime+(%d))})()"
MINI_SEEK_TO_JS = ("(()=>{" + _MEDIA + "if(m&&isFinite(m.duration))"
                   "m.currentTime=m.duration*%f})()")
# Restarts playback that has stalled: presses YouTube's own play button if its player
# thinks it's paused, otherwise re-seeks in place (makes the player fetch again) and plays.
MINI_KICK_JS = ("(()=>{" + _MEDIA + "if(!m)return;"
                "const p=document.getElementById('movie_player');"
                "const b=p&&p.querySelector('.ytp-play-button');"
                "if(b&&p.classList.contains('paused-mode')){b.click();return}"
                "m.currentTime=m.currentTime;m.play()})()")
STALL_S = 3.0          # Lite: "playing" but the position hasn't moved this long -> unstick
PEEK_WAIT_S = 5.0      # Lite, opening a video: show the page if it hasn't started this long
                       # after loading
MINI_NEXT_JS = ("(()=>{const b=document.querySelector('.ytp-next-button');"
                "if(b&&b.offsetParent!==null){b.click();return true}"
                "const n=document.querySelector('a.ytp-next-button');if(n){n.click();return true}"
                "return false})()")


class AudioSink(QObject):
    """WebSocket server the tap scripts stream to (one connection per frame).

    Binary messages are int16 stereo PCM at SR; text messages are JSON status
    ({"on": tapped-and-playing, "off": playing-but-can't-tap, "video": how many of
    those playing are videos}). Only connections
    that present the per-launch secret path are accepted. Everything runs on the UI
    thread (Qt sockets), so `audio` is emitted there, like the old bridge."""
    audio = Signal(object)        # (n, 2) float32 at SR
    status = Signal(int, int)     # totals across frames: tapped, can't-tap (`video` too)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = secrets.token_urlsafe(18)
        self.server = QWebSocketServer("soundboard", QWebSocketServer.NonSecureMode, self)
        self.port = self.server.serverPort() if self.server.listen(QHostAddress.LocalHost, 0) \
            else 0
        if not self.port:
            log.error("browser audio sink can't listen: %s", self.server.errorString())
        self.server.newConnection.connect(self._on_connection)
        self._conns: dict[QWebSocket, tuple[int, int, int]] = {}
        self._shown = (0, 0, 0)
        self._active: QWebSocket | None = None   # the frame that currently owns the mic
        self._active_t = 0.0
        self._rate_msg = ""   # live speed, also sent to frames that connect later
        # called with each chunk instead of emitting `audio` (ThreadedSink: on its thread)
        self.feed: Callable[[np.ndarray], None] | None = None

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/{self.token}"

    def _on_connection(self):
        s = self.server.nextPendingConnection()
        if s is None:
            return
        if s.requestUrl().path() != "/" + self.token:
            log.warning("browser sink: rejected a connection without the secret")
            s.close()
            s.deleteLater()
            return
        self._conns[s] = (0, 0, 0)
        s.binaryMessageReceived.connect(lambda data, s=s: self._on_binary(s, data))
        s.textMessageReceived.connect(lambda text, s=s: self._on_text(s, text))
        s.disconnected.connect(lambda s=s: self._on_closed(s))
        if self._rate_msg:
            self._send(s, self._rate_msg)

    def _send(self, s: QWebSocket, text: str) -> bool:
        """Send to one frame; a socket Qt has already destroyed (its frame went away
        and the `disconnected` handler didn't get to run first) is forgotten instead."""
        if qt_valid(s):
            try:
                s.sendTextMessage(text)
                return True
            except RuntimeError:   # deleted between the check and the call
                pass
        self._forget(s)
        return False

    def _forget(self, s: QWebSocket):
        self._conns.pop(s, None)
        if self._active is s:
            self._active = None

    def _on_binary(self, s: QWebSocket, data):
        now = time.monotonic()
        if self._active is not s:
            if self._active is not None and now - self._active_t < HANDOVER_S:
                return   # another frame owns the mic right now
            self._active = s
        self._active_t = now
        x = np.frombuffer(bytes(data), np.int16)
        if len(x) % 2:
            return
        y = x.reshape(-1, 2).astype(np.float32) * np.float32(1 / 32768)
        if self.feed is None:
            self.audio.emit(y)
            return
        try:
            self.feed(y)
        except Exception:  # noqa: BLE001 - one bad chunk mustn't take the stream down
            log.exception("browser audio feed failed")

    def _on_text(self, s: QWebSocket, text: str):
        try:
            d = json.loads(text)
            st = (int(d["on"]), int(d["off"]), int(d.get("video", 0)))
        except (ValueError, KeyError, TypeError):
            return
        if not qt_valid(s):
            return
        self._conns[s] = st
        if self._rate_msg:   # repeated here: a message sent the moment a frame connects can
            self._send(s, self._rate_msg)   # arrive before its page is listening
        self._emit_status()

    def _on_closed(self, s: QWebSocket):
        if not qt_valid(self):   # a socket outliving the sink at shutdown: nothing to update
            return
        self._forget(s)
        if qt_valid(s):   # `disconnected` is also emitted from the socket's destructor
            s.deleteLater()
        self._emit_status()

    @property
    def video(self) -> int:
        """How many videos are playing (tapped or not), across frames."""
        return self._shown[2]

    def _emit_status(self):
        tot = tuple(sum(c[i] for c in self._conns.values()) for i in range(3))
        if tot != self._shown:
            self._shown = tot
            self.status.emit(tot[0], tot[1])

    @Slot(float, bool)
    def set_rate(self, speed: float, keep_pitch: bool):
        """Playback speed of every media element in every frame (the page's own
        playbackRate; with keep_pitch the browser keeps the pitch while it does)."""
        normal = abs(speed - 1) < 1e-3 and keep_pitch
        msg = rate_message(speed, keep_pitch)
        if normal and not self._rate_msg:
            return
        self._rate_msg = "" if normal else msg
        self.broadcast(msg)

    @Slot(str)
    def broadcast(self, text: str):
        n = len(self._conns)
        for s in list(self._conns):
            self._send(s, text)
        if len(self._conns) != n:
            self._emit_status()   # dead frames no longer count as playing

    def close(self):
        conns, self._conns = list(self._conns), {}
        for s in conns:
            if qt_valid(s):
                s.close()
        self.server.close()


class ThreadedSink(QObject):
    """An AudioSink on its own thread. The page audio then goes socket -> engine
    (and the replay recorder) without waiting for the UI thread, which can be busy
    for a long time: resizing the window re-lays out the whole page on every mouse
    move, and the browser rings used to run dry meanwhile (a stutter). `feed` is
    called on that thread; `status` arrives on the UI thread as usual."""
    status = Signal(int, int)
    _rate = Signal(float, bool)
    _broadcast = Signal(str)
    _close = Signal()

    def __init__(self, feed: Callable[[np.ndarray], None], parent=None):
        super().__init__(parent)
        self.sink = AudioSink()               # listens now, so port / url are known
        self.sink.feed = feed
        self.thread = QThread()
        self.thread.setObjectName("browser-audio")
        self.sink.moveToThread(self.thread)   # the server (and its sockets) go with it
        self.sink.status.connect(self.status)
        self._rate.connect(self.sink.set_rate)
        self._broadcast.connect(self.sink.broadcast)
        self._close.connect(self.sink.close, Qt.BlockingQueuedConnection)
        self.thread.finished.connect(self.sink.deleteLater)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.sink.port

    @property
    def url(self) -> str:
        return self.sink.url

    @property
    def video(self) -> int:
        return self.sink.video

    def set_rate(self, speed: float, keep_pitch: bool):
        self._rate.emit(speed, keep_pitch)

    def broadcast(self, text: str):
        self._broadcast.emit(text)

    def close(self):
        if not self.thread.isRunning():
            return
        self._close.emit()                    # runs there; returns once it's done
        self.thread.quit()
        if not self.thread.wait(3000):
            log.warning("browser audio thread didn't stop")


class SeekBar(QSlider):
    """A seek bar that jumps to where you click (a plain slider pages by steps)."""
    seek = Signal(float)   # 0..1

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setObjectName("seek")
        self.setRange(0, 1000)
        self.setCursor(Qt.PointingHandCursor)
        self.sliderReleased.connect(lambda: self.seek.emit(self.value() / 1000))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setValue(QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(e.position().x()), self.width()))
        super().mousePressEvent(e)   # the handle is under the cursor now: drags work too

    def wheelEvent(self, e):
        e.ignore()   # scrolling the tab must not scrub the video


def rounded(pm: QPixmap, w: int, h: int, r: int = 10) -> QPixmap:
    """`pm` cropped to fill w x h, with rounded corners."""
    pm = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(w, h)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, w, h, r, r)
    p.setClipPath(path)
    p.drawPixmap((w - pm.width()) // 2, (h - pm.height()) // 2, pm)
    p.end()
    return out


def youtube_id(url: QUrl) -> str:
    host = url.host()
    if host == "youtu.be":
        return url.path().strip("/")
    if not re.search(r"(^|\.)youtube\.com$", host):
        return ""
    path = url.path()
    if path.startswith(("/shorts/", "/embed/", "/live/")):
        return path.split("/")[2]
    if path == "/watch":
        for kv in url.query().split("&"):
            k, _, val = kv.partition("=")
            if k == "v":
                return val
    return ""


def fmt_time(s: float) -> str:
    s = int(s)
    if s >= 3600:
        return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


class _Page(QWebEnginePage):
    refused = Signal(QUrl)   # a page outside ALLOWED_SITES wasn't opened

    def createWindow(self, _type):
        return self   # pop-ups and target=_blank links open in the same tab

    def acceptNavigationRequest(self, url, _type, is_main_frame):
        # redirects come through here too, so a link that bounces off an allowed site
        # (youtube.com/redirect?q=…) is still stopped
        if is_main_frame and not site_allowed(url):
            self.refused.emit(QUrl(url))
            return False
        return True


class Recorder:
    """Keeps a rolling CLIP_S-second replay buffer, plus a manual recording.

    The manual recording is spooled to a 16-bit WAV on disk as it happens instead
    of being held in RAM: at the 15-minute cap that is 172 MB on disk versus
    345 MB of float32 chunks *plus* another 345 MB to concatenate them. If the
    spool file can't be opened it falls back to memory."""

    def __init__(self, spool_path=SPOOL_PATH):
        self.replay = np.zeros((CLIP_S * SR, 2), np.float32)
        self.w = 0
        self.filled = 0
        self.spool_path = spool_path
        self._spool: sf.SoundFile | None = None
        self._mem: list[np.ndarray] | None = None
        self._recording = False
        self.rec_frames = 0
        self._lock = threading.RLock()   # push() runs on the browser audio thread

    def push(self, x: np.ndarray):
        with self._lock:
            self._push(x)

    def _push(self, x: np.ndarray):
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
        if self._recording and self.rec_frames < MAX_SECONDS * SR:
            if self._spool is not None:
                try:
                    self._spool.write(x)
                except Exception:  # noqa: BLE001 - disk full etc.: keep the rest in memory
                    log.warning("recording spool failed; continuing in memory", exc_info=True)
                    self._close_spool()
                    self._mem = [self._read_spool()]
                    self._mem.append(x.copy())
            else:
                self._mem.append(x.copy())
            self.rec_frames += n

    def last(self) -> np.ndarray:
        with self._lock:
            return self._last()

    def _last(self) -> np.ndarray:
        if self.filled < len(self.replay):
            return self.replay[:self.filled].copy()
        return np.concatenate([self.replay[self.w:], self.replay[:self.w]])

    def start(self):
        with self._lock:
            self._start()

    def _start(self):
        self._stop()
        self.rec_frames = 0
        self._recording = True
        try:
            self.spool_path.parent.mkdir(parents=True, exist_ok=True)
            self._spool = sf.SoundFile(str(self.spool_path), "w", SR, 2, subtype="PCM_16")
        except Exception:  # noqa: BLE001
            log.warning("can't open recording spool %s; recording in memory", self.spool_path,
                        exc_info=True)
            self._spool = None
            self._mem = []

    def stop(self) -> np.ndarray:
        """End the recording and return it as (n, 2) float32 (empty if nothing recorded)."""
        with self._lock:
            return self._stop()

    def _stop(self) -> np.ndarray:
        if not self._recording:
            return np.zeros((0, 2), np.float32)
        self._recording = False
        if self._spool is not None:
            self._close_spool()
            data = self._read_spool()
        else:
            mem, self._mem = self._mem or [], None
            data = np.concatenate(mem) if mem else np.zeros((0, 2), np.float32)
        return data

    def _close_spool(self):
        try:
            self._spool.close()
        except Exception:  # noqa: BLE001
            log.debug("closing the spool raised", exc_info=True)
        self._spool = None

    def _read_spool(self) -> np.ndarray:
        try:
            data, _ = sf.read(str(self.spool_path), dtype="float32", always_2d=True)
        except Exception:  # noqa: BLE001
            log.warning("can't read back the recording spool", exc_info=True)
            data = np.zeros((0, 2), np.float32)
        try:
            self.spool_path.unlink(missing_ok=True)
        except OSError:
            pass
        return data

    @property
    def recording(self) -> bool:
        return self._recording


class BrowserTab(QWidget):
    clip_ready = Signal(object, str)     # audio, suggested name
    sound_ready = Signal(object, object)  # SoundMeta, int16 audio: "Add as sound" finished
    _dl_msg = Signal(str, str)           # download thread -> UI: (progress | ok | error, text)

    def __init__(self, engine, cfg, save_cb, meter_cls):
        super().__init__()
        self.engine, self.cfg, self._save = engine, cfg, save_cb
        self.recorder = Recorder()
        self.view: QWebEngineView | None = None
        self.profile: QWebEngineProfile | None = None
        self._status = (0, 0)
        self._video = 0            # videos playing
        self._flash_until = 0.0
        self._collapsed = False    # Lite: page hidden, mini-player shown
        self._peeking = False      # ...with the page 2 px tall while a video starts
        self._expect_until = 0.0   # the navigation just asked for opens a video (Lite)
        self._peek_gen = 0
        self._peek_url = QUrl()
        self._mini_poll = 0.0
        self._thumb_id = None      # YouTube video whose thumbnail is shown
        self._stall = (-1.0, 0.0)  # (position, when it last moved): the Lite watchdog
        self._unsticking = False
        self._rate = (1.0, True)   # live speed, keep pitch (not saved)
        self.sink: ThreadedSink | None = None
        self.net = QNetworkAccessManager(self)
        self._downloading = False
        self._dl_msg.connect(self._on_dl_msg)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # Same shape as every tab: toolbar on top, the page, then the control bar.
        # ---- toolbar: navigation
        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.btn_back = QPushButton()
        self.btn_fwd = QPushButton()
        self.btn_reload = QPushButton()
        for b, ic, tip in ((self.btn_back, "back", "Back"), (self.btn_fwd, "forward", "Forward"),
                           (self.btn_reload, "reload", "Reload")):
            b.setObjectName("round")
            b.setFixedSize(36, 32)
            b.setToolTip(tip)
            icons.set_icon(b, ic, size=16)
            nav.addWidget(b)
        self.url = QLineEdit()
        self.url.setPlaceholderText("Search YouTube or type a web address…")
        self.url.returnPressed.connect(self._go)
        nav.addWidget(self.url, 1)
        self.btn_add = QPushButton("Add as sound")
        self.btn_add.setObjectName("primary")
        self.btn_add.setToolTip("Download this video's audio and add it to your Sounds "
                                "(YouTube, SoundCloud and most video sites)")
        icons.set_icon(self.btn_add, "plus", "on_accent", size=14)
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self.add_as_sound)
        nav.addWidget(self.btn_add)
        self._quick = []
        for label, link in QUICK_LINKS:
            b = QPushButton(label)
            b.setObjectName("small")
            b.clicked.connect(lambda _=False, u=link: self.load(u))
            nav.addWidget(b)
            self._quick.append(b)
        v.addLayout(nav)

        # ---- Lite mini-player (replaces the page while something plays)
        # [thumbnail]  title                                   [Lite] [Show page]
        #              channel
        #              0:42 ━━━━━━━━━━━●──────────── 3:15
        #                     (-10)  ( ▶ )  (+10)  (⏭)
        self.mini = QFrame()
        self.mini.setObjectName("transport")
        mh = QHBoxLayout(self.mini)
        mh.setContentsMargins(14, 14, 18, 14)
        mh.setSpacing(16)
        self.mini_thumb = QLabel()
        self.mini_thumb.setFixedSize(192, 108)
        self.mini_thumb.setAlignment(Qt.AlignCenter)
        self.mini_thumb.setStyleSheet("background:rgba(127,127,127,0.12); border-radius:10px;")
        mh.addWidget(self.mini_thumb, 0, Qt.AlignTop)

        mv = QVBoxLayout()
        mv.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.mini_title = QLabel("—")
        self.mini_title.setStyleSheet("font-size:13pt; font-weight:700;")
        self.mini_title.setWordWrap(True)
        titles.addWidget(self.mini_title)
        self.mini_sub = QLabel("")
        self.mini_sub.setObjectName("muted")
        titles.addWidget(self.mini_sub)
        top.addLayout(titles, 1)
        lite = QLabel("LITE")
        lite.setToolTip("Lite mode: the page is hidden while it plays, so it isn't drawing "
                        "or decoding video. Easy on your game; the audio keeps going.")
        lite.setStyleSheet("color:#13ce66; border:1px solid #1c6b45; border-radius:9px; "
                           "padding:1px 8px; font-size:8pt; font-weight:700;")
        top.addWidget(lite, 0, Qt.AlignTop)
        show = QPushButton("Show page")
        show.setObjectName("small")
        show.setToolTip("Bring the page back to pick something else. "
                        "It hides again when the next thing starts playing.")
        show.clicked.connect(lambda: self._set_collapsed(False))
        top.addWidget(show, 0, Qt.AlignTop)
        mv.addLayout(top)
        mv.addStretch(1)

        seek = QHBoxLayout()
        seek.setSpacing(10)
        self.mini_pos = QLabel("0:00")
        self.mini_pos.setObjectName("muted")
        self.mini_seek = SeekBar()
        self.mini_seek.seek.connect(self._mini_seek_to)
        self.mini_dur = QLabel("0:00")
        self.mini_dur.setObjectName("muted")
        for w in (self.mini_pos, self.mini_dur):
            w.setMinimumWidth(QFontMetrics(w.font()).horizontalAdvance("0:00:00"))
        self.mini_pos.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        seek.addWidget(self.mini_pos)
        seek.addWidget(self.mini_seek, 1)
        seek.addWidget(self.mini_dur)
        mv.addLayout(seek)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self.mini_btns = {}
        for key, ic, tip, size in (("back", "", "Back 10 seconds", 38),
                                   ("play", "pause", "Play / pause", 48),
                                   ("fwd", "", "Forward 10 seconds", 38),
                                   ("next", "next", "Next video (YouTube)", 38)):
            b = QPushButton({"back": "−10", "fwd": "+10"}.get(key, ""))
            b.setFixedSize(size, size)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"border-radius:{size // 2}px; padding:0; font-weight:700;")
            if key == "play":
                b.setObjectName("primary")
                icons.set_icon(b, ic, "on_accent", size=20)
            elif ic:
                icons.set_icon(b, ic, size=16)
            row.addWidget(b)
            self.mini_btns[key] = b
        row.addStretch(1)
        self.mini_btns["back"].clicked.connect(lambda: self._mini_js(MINI_SEEK_JS % -10))
        self.mini_btns["fwd"].clicked.connect(lambda: self._mini_js(MINI_SEEK_JS % 10))
        self.mini_btns["play"].clicked.connect(lambda: self._mini_js(MINI_TOGGLE_JS))
        self.mini_btns["next"].clicked.connect(lambda: self._mini_js(MINI_NEXT_JS))
        mv.addLayout(row)
        mh.addLayout(mv, 1)
        self.mini.hide()
        v.addWidget(self.mini)
        self.mini_spacer = QWidget()   # fills the space the page used
        self.mini_spacer.hide()
        v.addWidget(self.mini_spacer, 1)

        self.holder = QVBoxLayout()   # the web view goes here once the tab is first opened
        v.addLayout(self.holder, 1)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setObjectName("muted")
        v.addWidget(self.info)

        # ---- control bar: live | record | volume | hear it myself
        bar_, bh = bar()
        self.btn_live = QPushButton()
        self.btn_live.setObjectName("live")
        self.btn_live.setCheckable(True)
        icons.set_icon(self.btn_live, "live", checked_color="#ffffff")
        self._live_labels = LIVE_TEXT
        self._size_live()
        self.btn_live.toggled.connect(self._on_live)
        bh.addWidget(self.btn_live)
        self.meter = meter_cls()
        self.meter.setMinimumWidth(50)
        self.meter.setToolTip("Browser audio level")
        bh.addWidget(self.meter, 1)
        sep1 = vsep()
        bh.addWidget(sep1)

        self.btn_rec = QPushButton("Record")
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip("Record what's playing in the browser. Click again to stop — "
                                "the clip is added to your Sounds.")
        icons.set_icon(self.btn_rec, "record", "#ff4d4f", "#ffffff", size=14)
        self.btn_rec.toggled.connect(self._on_rec)
        bh.addWidget(self.btn_rec)
        self.btn_last = QPushButton(f"Last {CLIP_S}s")
        self.btn_last.setToolTip(f"Save the last {CLIP_S} seconds the browser played as a sound")
        icons.set_icon(self.btn_last, "history")
        self.btn_last.clicked.connect(self.clip_last)
        bh.addWidget(self.btn_last)
        self.btn_lite = QPushButton("Lite")
        self.btn_lite.setObjectName("lite")
        self.btn_lite.setCheckable(True)
        self.btn_lite.setToolTip("Lite mode — easy on your game: while something plays, the page "
                                 "is hidden (no video drawn or decoded) and YouTube drops to 144p. "
                                 "Audio is unaffected.")
        icons.set_icon(self.btn_lite, "leaf", checked_color="#ffffff")
        self.btn_lite.toggled.connect(self._on_lite)
        bh.addWidget(self.btn_lite)
        self.btn_speed = SpeedPitchButton("browser", "Only while you listen; not saved.",
                                          redline=(0.25, 4.0))   # the page's playbackRate limits
        self.btn_speed.changed.connect(self._on_speed)
        bh.addWidget(self.btn_speed)
        sep2 = vsep()
        bh.addWidget(sep2)

        vol_icon = icon_label("volume", "Browser volume (for them and for you)")
        bh.addWidget(vol_icon)
        self.vol = VolumeControl(cfg.browser_vol, tip="Browser volume (for them and for you)")
        self.vol.changed.connect(self._on_vol)
        bh.addWidget(self.vol)
        self._clip_group = (self.btn_rec, self.btn_last, self.btn_lite, sep1)
        self._vol_group = (sep2, vol_icon, self.vol)
        self.chk_hear = QCheckBox("Hear it myself")
        self.chk_hear.setToolTip("Also play the browser into your headphones")
        self.chk_hear.toggled.connect(self._on_hear)
        bh.addWidget(self.chk_hear)
        v.addWidget(bar_)

        # initial state (sets the engine too). LIVE always starts off: a page left
        # playing, or one that autoplays, mustn't go out to others the moment the app opens.
        cfg.browser_live = False
        self.btn_live.setChecked(False)
        self._on_live(False)
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
            last = self.cfg.browser_url
            self.load(last if last and site_allowed(QUrl(last)) else QUICK_LINKS[0][1])

    def _make_view(self):
        store = APP_DIR / "browser"
        self.profile = QWebEngineProfile("soundboard")   # named = logins/cookies persist
        self.profile.setPersistentStoragePath(str(store))
        self.profile.setCachePath(str(store / "cache"))
        self.adblock = AdBlocker(store / "adblock", self)
        self.profile.setUrlRequestInterceptor(self.adblock)

        self.view = QWebEngineView()
        page = _Page(self.profile, self.view)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
        s.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, False)

        self.sink = ThreadedSink(self._on_audio, self)   # _on_audio runs on its thread
        self.sink.status.connect(self._on_status)
        self.sink.set_rate(*self._rate)   # a speed picked before the tab was first opened
        if not self.sink.port:
            self._refresh_info("<span style='color:#ff4d4f'>Browser audio is unavailable "
                               "(couldn't open a local socket) — see the log.</span>")

        sc = QWebEngineScript()
        sc.setName("sb-tap")
        sc.setSourceCode(tap_script(self.sink.url))
        sc.setWorldId(WORLD)
        sc.setInjectionPoint(QWebEngineScript.DocumentCreation)
        sc.setRunsOnSubFrames(True)   # embedded players (iframes) are tapped too
        page.scripts().insert(sc)
        sc = QWebEngineScript()
        sc.setName("sb-adopt")
        sc.setSourceCode(ADOPT_JS)
        sc.setWorldId(QWebEngineScript.MainWorld)   # the page's own `new Audio()`s
        sc.setInjectionPoint(QWebEngineScript.DocumentCreation)
        sc.setRunsOnSubFrames(True)
        page.scripts().insert(sc)
        sc = QWebEngineScript()
        sc.setName("sb-lite")
        sc.setSourceCode(LITE_JS)
        sc.setWorldId(QWebEngineScript.MainWorld)
        sc.setInjectionPoint(QWebEngineScript.DocumentReady)
        sc.setRunsOnSubFrames(False)
        page.scripts().insert(sc)
        sc = QWebEngineScript()
        sc.setName("sb-youtube-ads")
        sc.setSourceCode(YOUTUBE_JS)
        sc.setWorldId(QWebEngineScript.MainWorld)   # has to patch the page's own JSON.parse
        sc.setInjectionPoint(QWebEngineScript.DocumentCreation)
        sc.setRunsOnSubFrames(True)   # embedded YouTube players too
        page.scripts().insert(sc)
        page.loadFinished.connect(lambda _ok: self._push_lite())
        page.loadFinished.connect(lambda _ok: self._hide_ads())
        page.loadFinished.connect(lambda _ok: self._arm_peek())

        page.loadStarted.connect(self._on_load_started)
        page.refused.connect(self._on_refused)

        self.view.setPage(page)
        self.btn_back.clicked.connect(self._back)
        self.btn_fwd.clicked.connect(self._forward)
        self.btn_reload.clicked.connect(self._reload)
        self.view.urlChanged.connect(self._on_url)
        self.holder.addWidget(self.view)

    def load(self, url: str):
        self._open(QUrl(url))

    def _open(self, url: QUrl):
        if self.view is not None:
            self._expect(url)
            self.view.setUrl(url)

    def _back(self):
        h = self.view.history()
        if h.canGoBack():
            self._expect(h.backItem().url())
            self.view.back()

    def _forward(self):
        h = self.view.history()
        if h.canGoForward():
            self._expect(h.forwardItem().url())
            self.view.forward()

    def _reload(self):
        self._expect(self.view.url())
        self.view.reload()

    def _expect(self, url: QUrl):
        """About to navigate to `url`. In Lite, a YouTube video then opens straight
        into the mini-player instead of flashing the page up until it plays."""
        # (a deadline: YouTube's own back / forward never fires loadStarted)
        self._expect_until = (time.monotonic() + 2.0
                              if self.cfg.browser_lite and youtube_id(url) else 0.0)
        self._peek_url = QUrl(url)

    @staticmethod
    def url_for(text: str) -> QUrl:
        """What the address bar means: an address (scheme optional, ports and paths
        fine, 'localhost' too) or, failing that, a YouTube search."""
        t = text.strip()
        looks_like_address = " " not in t and ("." in t or "://" in t
                                               or t.split("/")[0].split(":")[0] == "localhost")
        if looks_like_address:
            if "://" not in t:   # fromUserInput would pick http; the web is https now
                t = ("http://" if t.startswith("localhost") else "https://") + t
            url = QUrl.fromUserInput(t)
            if url.isValid() and url.host():
                return url
        url = QUrl("https://www.youtube.com/results")
        url.setQuery("search_query=" + QUrl.toPercentEncoding(t).data().decode())
        return url

    def _go(self):
        t = self.url.text().strip()
        if not t:
            return
        if self.view is not None:
            self._open(self.url_for(t))
            self.view.setFocus()

    def _on_load_started(self):
        """A new document is loading (a quick link, the address bar, back / forward, a
        link on the page). Whatever Lite was hiding is gone, so show the page again;
        it collapses once the new page starts playing. A video opened from here in
        Lite goes to the mini-player right away instead (see _set_collapsed)."""
        self._unsticking = False   # a pending _end_unstick must not hide the new page
        expect, self._expect_until = time.monotonic() < self._expect_until, 0.0
        if expect:
            self._set_collapsed(True, peek=True)
        elif self._collapsed:
            self._set_collapsed(False)
        self._stall = (-1.0, time.monotonic())

    def _arm_peek(self):
        """The page has loaded; if the video still hasn't started a moment later
        (autoplay off, a consent page…), show the page after all."""
        if self._peeking:
            self._peek_gen += 1
            QTimer.singleShot(int(PEEK_WAIT_S * 1000),
                              lambda g=self._peek_gen: self._peek_timeout(g))

    def _peek_timeout(self, gen: int):
        if gen == self._peek_gen and self._peeking:
            self._set_collapsed(False)

    def _on_url(self, url: QUrl):
        s = url.toString()
        if not self._downloading:
            self.btn_add.setEnabled(ytdl.downloadable(s))
        self.url.setText(s)
        self.url.setCursorPosition(0)
        if url.scheme() in ("http", "https"):
            self.cfg.browser_url = s
            self._save()

    def _on_refused(self, url: QUrl):
        self.url.setText(self.view.url().toString())   # not the address that was refused
        self.url.setCursorPosition(0)
        self._refresh_info("<span style='color:#ffb020'>⛔ "
                           f"{html.escape(url.host() or url.toString())} isn't one of the "
                           "sites this browser opens (YouTube, SoundCloud and sound-clip "
                           "sites), to keep you away from scam and virus pages.</span>")

    def _hide_ads(self):
        css = self.adblock.hide_css(self.view.url().toString()) if self.view else ""
        if css:
            self.view.page().runJavaScript(hide_css_js(css), WORLD)

    def pause_media(self):
        if self.view is not None:
            self.view.page().runJavaScript(PAUSE_JS, WORLD)   # main frame, immediately
            self.sink.broadcast("pause")                       # every frame with a socket

    def shutdown(self):
        self.timer.stop()
        if self.recorder.recording:
            self.recorder.stop()   # closes and deletes the spool file
        if self.view is not None:
            page = self.view.page()
            self.view.setParent(None)
            qt_delete(page)   # pages must go before their profile
            self.profile.setUrlRequestInterceptor(None)
            self.view = None
            self.sink.close()

    # ------------------------------------------------------------------ audio
    def _on_audio(self, x: np.ndarray):
        """A chunk of page audio, on the sink's thread (see ThreadedSink)."""
        y = self.engine.feed_browser(x)   # the pitched chunk, if the engine returns it
        self.recorder.push(x if y is None else y)

    def _on_speed(self, speed: float, semitones: float, keep_pitch: bool):
        """Live speed / pitch of whatever the browser plays: speed is the page's own
        playbackRate (every frame, and videos that start later); pitch is shifted
        in the engine, so recordings and the mic get it too."""
        self._rate = (speed, keep_pitch)
        self.engine.browser_pitch = semitones
        if self.sink is not None:
            self.sink.set_rate(speed, keep_pitch)

    def _on_status(self, on: int, off: int):
        # Lite only hides the page for video: a sound-button site has to stay usable
        video = self.sink.video if self.sink is not None else 0
        started = video > 0 and self._video == 0
        self._status, self._video = (on, off), video
        self._refresh_info()
        if video and self.cfg.browser_lite and (started or self._peeking):
            self._set_collapsed(True)   # a video started playing: hide the page
        elif on == 0 and self._collapsed:
            self._poll_mini()   # paused, or the player went away? (see _on_mini_state)

    # ------------------------------------------------------------------ lite mode
    def _on_lite(self, on: bool):
        self.cfg.browser_lite = on
        self._save()
        self._push_lite()
        self._set_collapsed(on and self._video > 0)

    def _push_lite(self):
        if self.view is not None:
            self.view.page().runJavaScript(set_lite_js(self.cfg.browser_lite), WORLD)

    def _set_collapsed(self, on: bool, peek: bool = False):
        """Lite: swap the page for the mini-player. A hidden page isn't drawn, and
        Chromium stops decoding the video track of hidden players, so the browser
        costs little more than its audio. It stays that way while paused.

        peek: a video is opening. The page stays visible but 2 px tall (a hidden page
        wouldn't autoplay) until it starts playing, so it never flashes up first."""
        self._peeking = on and peek
        self._peek_gen += 1   # any pending peek timeout is stale now
        if self.view is not None:
            self.view.setMaximumHeight(2 if self._peeking else 16777215)
            self.view.setVisible(not on or self._peeking)
        self.mini.setVisible(on)
        self.mini_spacer.setVisible(on)
        self._stall = (-1.0, time.monotonic())
        if on and (peek or not self._collapsed):
            self.mini_title.setText("Loading…" if peek else "—")
            self.mini_sub.setText("")
            self.mini_pos.setText("0:00")
            self.mini_dur.setText("0:00")
            self.mini_seek.setValue(0)
        self._collapsed = on
        if on:
            self._mini_poll = 0.0
            self._update_thumb()
            self._poll_mini()

    def _mini_js(self, js: str):
        if self.view is not None:
            self.view.page().runJavaScript(js, WORLD)
            QTimer.singleShot(150, self._poll_mini)

    def _poll_mini(self):
        if self.view is not None and self._collapsed and self.isVisible():
            self.view.page().runJavaScript(MINI_STATE_JS, WORLD, self._on_mini_state)

    def _mini_seek_to(self, frac: float):
        self._mini_js(MINI_SEEK_TO_JS % max(0.0, min(1.0, frac)))

    def _on_mini_state(self, st):
        try:
            pos, dur, paused, title, channel = json.loads(st)
        except (TypeError, ValueError):
            # no media on the page. While nothing plays either, the player has gone
            # (closed, or a page without one): never leave a blank tab.
            if (self._collapsed and not self._peeking and not self._unsticking
                    and not self._status[0]):
                self._set_collapsed(False)
            return
        if self._peeking:
            return   # the video hasn't started yet: keep showing "Loading…"
        title = re.sub(r"^\(\d+\)\s*", "", str(title or ""))
        title = re.sub(r"\s*[-–|]\s*(YouTube|SoundCloud)$", "", title).strip()
        self.mini_title.setText(title or "Playing")
        host = self.view.url().host().removeprefix("www.") if self.view is not None else ""
        self.mini_sub.setText("  ·  ".join(x for x in (str(channel or ""), host) if x))
        self.mini_pos.setText(fmt_time(pos))
        self.mini_dur.setText(fmt_time(dur) if dur else "live")
        self.mini_seek.setEnabled(bool(dur))
        if not self.mini_seek.isSliderDown():
            self.mini_seek.setValue(int(1000 * pos / dur) if dur else 0)
        # set every time (the icon is cached): a theme change re-applies the initial one
        self.mini_btns["play"].setIcon(icons.icon("play" if paused else "pause", "on_accent"))
        self._update_thumb()
        self._watch_stall(pos, bool(paused) or not dur)

    # Lite watchdog. Now and then a hidden YouTube player stops fetching: it still says
    # it's playing, but the position stops moving (it used to take "Show page" and a
    # click on play to get it going). When that happens the page is shown for a moment,
    # 2 px tall so nothing jumps, and playback is kicked; then it's hidden again.
    def _watch_stall(self, pos: float, paused: bool):
        now = time.monotonic()
        last, since = self._stall
        # (a player with no duration yet hasn't loaded anything, so there's nothing
        # to kick: treated like paused)
        if (paused or abs(pos - last) > 0.05 or self._unsticking or self._peeking
                or not self._status[0]):
            self._stall = (pos, now)
            return
        if now - since < STALL_S or self.view is None:
            return
        log.info("lite: playback stalled at %.1fs, waking the page", pos)
        self._unsticking = True
        self.view.setMaximumHeight(2)
        self.view.setVisible(True)
        QTimer.singleShot(600, lambda: self._mini_js(MINI_KICK_JS))
        QTimer.singleShot(2500, self._end_unstick)

    def _end_unstick(self):
        self._unsticking = False
        self._stall = (-1.0, time.monotonic())
        if self.view is not None and self._collapsed and not self._peeking:
            self.view.setVisible(False)
            self.view.setMaximumHeight(16777215)

    def _update_thumb(self):
        url = self._peek_url if self._peeking else self.view.url() if self.view else QUrl()
        vid = youtube_id(url)
        if vid == self._thumb_id:
            return
        self._thumb_id = vid
        if not vid:
            self.mini_thumb.setPixmap(icons.icon("wave", "muted").pixmap(40, 40))
            return
        reply = self.net.get(QNetworkRequest(QUrl(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg")))
        reply.finished.connect(lambda r=reply, v=vid: self._on_thumb(r, v))

    def _on_thumb(self, reply, vid: str):
        data = reply.readAll()
        reply.deleteLater()
        pm = QPixmap()
        if vid == self._thumb_id and pm.loadFromData(data):
            self.mini_thumb.setPixmap(rounded(pm, self.mini_thumb.width(),
                                              self.mini_thumb.height()))

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

    # ------------------------------------------------------------------ small windows
    def _size_live(self):
        """Wide enough for both labels (bold), so the bar doesn't jump when it toggles."""
        self.btn_live.ensurePolished()   # pick up the stylesheet font first
        f = self.btn_live.font()
        f.setBold(True)
        fm = QFontMetrics(f)
        self.btn_live.setMinimumWidth(
            max(fm.horizontalAdvance(t) for t in self._live_labels.values()) + 56)
        self.btn_live.setText(self._live_labels[self.btn_live.isChecked()])

    def _short_live(self, short: bool):
        from soundboard.ui import responsive as r
        labels = LIVE_SHORT if short else LIVE_TEXT
        if labels is not self._live_labels:
            self._live_labels = labels
            self._size_live()
            r.touch(self.btn_live)

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r
        return [(10, "w", r.hide(*self._quick)),
                (12, "w", r.icon_only(self.btn_add)),
                (14, "w", r.hide(self.mini_thumb)),
                (30, "w", r.hide(self.chk_hear)),
                (36, "w", r.icon_only(self.btn_rec)),
                (36, "w", r.icon_only(self.btn_last)),
                (36, "w", r.icon_only(self.btn_lite)),
                (38, "w", r.hide(self.btn_speed)),
                (40, "w", r.hide(*self._vol_group)),
                (44, "w", self._short_live),
                (50, "w", r.hide(*self._clip_group)),
                (20, "h", r.hide(self.info))]

    # ------------------------------------------------------------------ controls
    def _on_live(self, on: bool):
        self.cfg.browser_live = on
        self.engine.browser_live = on
        self.btn_live.setText(self._live_labels[on])
        self._refresh_info()
        self._save()

    def _on_vol(self, gain: float):
        self.cfg.browser_vol = gain
        self.engine.browser_vol = gain
        self._save()

    def _on_hear(self, on: bool):
        self.cfg.browser_monitor = on
        self.engine.browser_monitor = on
        self._save()

    def _on_rec(self, on: bool):
        if on:
            self.recorder.start()
            return
        self.btn_rec.setText("Record")
        self._emit_clip(self.recorder.stop(), "Nothing was playing while you recorded.")

    def clip_last(self) -> bool:
        return self._emit_clip(self.recorder.last(),
                               f"Nothing has played in the last {CLIP_S} seconds.")

    def toggle_play(self):
        """Play / pause whatever the page is playing (the last thing played if paused)."""
        self._mini_js(MINI_TOGGLE_JS)

    def _emit_clip(self, data: np.ndarray, empty_msg: str) -> bool:
        data = trim_silence(data)
        if len(data) < int(0.2 * SR):
            self._refresh_info(f"<span style='color:#ffb020'>{empty_msg}</span>")
            return False
        self.clip_ready.emit(data, self._clip_name())
        self._refresh_info(f"<span style='color:#13ce66'>✓ Saved a {len(data) / SR:.1f}s clip "
                           "to your Sounds.</span>")
        return True

    def _clip_name(self) -> str:
        title = self.view.title() if self.view is not None else ""
        title = re.sub(r"^\(\d+\)\s*", "", title)                       # "(3) " unread counts
        title = re.sub(r"\s*[-–|]\s*(YouTube|SoundCloud)$", "", title).strip()
        return f"{title[:30] or 'Clip'} {time.strftime('%H.%M.%S')}"

    # ------------------------------------------------------------------ add as sound
    def add_as_sound(self) -> bool:
        """Download the open page's audio (yt-dlp) and add it to the Sounds tab."""
        url = self.view.url().toString() if self.view is not None else ""
        if self._downloading or not ytdl.downloadable(url):
            return False
        self._downloading = True
        self.btn_add.setEnabled(False)
        self.btn_add.setText("Adding…")
        color = PAD_COLORS[len(self.cfg.sounds) % len(PAD_COLORS)]
        known = {m.fingerprint: m.name for m in self.cfg.sounds if m.fingerprint}
        self._refresh_info("Downloading the audio…")
        threading.Thread(target=self._download, args=(url, color, known), daemon=True,
                         name="ytdl").start()
        return True

    def _download(self, url: str, color: str, known: dict):
        """Runs on its own thread; reports back through _dl_msg / sound_ready."""
        tmp = None
        try:
            path, title = ytdl.download_audio(
                url, progress=lambda f: self._dl_msg.emit("progress", f"{f:.0%}"),
                auto_update=self.cfg.ytdlp_auto_optin)
            tmp = path.parent
            self._dl_msg.emit("progress", "decoding")
            fp = fingerprint(str(path))
            if fp and fp in known:
                raise ytdl.DownloadError(f"It's already in your Sounds as “{known[fp]}”.")
            meta, data = import_file(str(path), color)
            meta.name = title[:40]
            if (pic := thumbs.find_in(path.parent)) is not None:
                meta.image = thumbs.store(pic, meta.id)   # the video's thumbnail
            self.engine.prepare(meta.id, data)
            self.sound_ready.emit(meta, data)
            self._dl_msg.emit("ok", f"✓ Added “{meta.name}” ({meta.duration:.0f}s) "
                                    "to your Sounds.")
        except Exception as e:  # noqa: BLE001 - shown in the info line, logged
            log.warning("add as sound failed for %s: %s", url, e)
            hint = ("" if not isinstance(e, ytdl.FetchError) or self.cfg.ytdlp_auto_optin else
                    " A newer yt-dlp may fix this: Settings → General → Update now.")
            self._dl_msg.emit("error", f"Couldn't add it: {e}{hint}")
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)

    def _on_dl_msg(self, kind: str, text: str):
        if kind == "progress":
            self.btn_add.setText("Adding…" if text == "decoding" else f"Adding… {text}")
            return
        self._downloading = False
        self.btn_add.setText("Add as sound")
        self.btn_add.setEnabled(self.view is not None
                                and ytdl.downloadable(self.view.url().toString()))
        color = "#13ce66" if kind == "ok" else "#ff4d4f"
        self._refresh_info(f"<span style='color:{color}'>{html.escape(text)}</span>")

    def _tick(self):
        e = self.engine
        if self.recorder.recording:
            secs = self.recorder.rec_frames / SR
            if secs >= MAX_SECONDS:
                self.btn_rec.setChecked(False)   # the cap applies even while the tab is hidden
        if not self.isVisible():
            e.level_browser *= 0.8
            return   # nothing below is visible: don't repaint meters or poll the page
        self.meter.set_level(e.level_browser)
        e.level_browser *= 0.8
        if self._collapsed and time.monotonic() - self._mini_poll >= 0.5:
            self._mini_poll = time.monotonic()
            self._poll_mini()
        if self.recorder.recording:
            secs = self.recorder.rec_frames / SR
            self.btn_rec.setText(f"Stop  {int(secs // 60)}:{int(secs % 60):02d}")
        elif time.monotonic() >= self._flash_until and self._flash_until:
            self._flash_until = 0.0
            self._refresh_info()
