"""Radio tab back end: the station directory, the stream player and the globe page.

Stations come from Radio Browser (https://www.radio-browser.info), a free,
community-run open directory of ~60 000 internet radio stations with an open API
and no key. Most stations carry a latitude / longitude, which the globe uses.
The app asks it for: the most-listened stations that have a location (the globe,
cached for a day in radio_dir()), searches you type, and a "click" when you
start a station (the directory's own popularity count, which it asks clients to
send). Nothing else about you is sent.

The player is Qt Multimedia (FFmpeg): it opens the stream (MP3, AAC, Ogg, HLS…)
and decodes it, but never plays it itself. A QAudioBufferOutput hands the decoded
audio to the UI thread as 48 kHz stereo float, which goes into the engine
(`Engine.feed_radio`) like the Browser tab's audio, so it can go out through
your mic.

The globe is globe.gl (MIT licence, three.js) in a web view, loaded from
jsDelivr at a pinned version with a subresource-integrity hash. The page is ours;
station names from the directory are escaped before they're shown, the page
can't navigate anywhere, and it reports clicks back over QWebChannel.
"""
from __future__ import annotations

import html
import ipaddress
import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import quote

import numpy as np
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QMediaMetaData, QMediaPlayer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from soundboard import __version__, library
from soundboard.engine import SR

log = logging.getLogger(__name__)

# Radio Browser mirrors. `all.` round-robins across them; the rest are fallbacks.
API_BASES = ("https://all.api.radio-browser.info", "https://de1.api.radio-browser.info",
             "https://de2.api.radio-browser.info")
GLOBE_LIMIT = 3000         # stations pinned on the globe (the most listened-to)
GLOBE_LIGHT = 1000         # ...of which the light (default) globe shows this many
SEARCH_LIMIT = 150
SEARCH_MAX_CHARS = 80
CACHE_S = 24 * 3600        # how long the globe's station list is reused
TIMEOUT_MS = 15000
USER_AGENT = f"OnionBoard/{__version__}"
RETRIES = 3                # a dropped stream is reopened this many times in a row
CONNECT_S = 20.0           # a station that sends no audio this long after opening is dead
STALL_S = 8.0              # ...and one that goes quiet this long while playing is reopened

GLOBE_JS = "https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/dist/globe.gl.min.js"
GLOBE_SRI = "sha384-1uolMBZ25k3zJcNwCLEv49+L+m2dZudqAzsoSAJfQTzDCSBxJzrMuZ2dkp/5JKiT"
_IMG = "https://cdn.jsdelivr.net/npm/three-globe@2.45.2/example/img/"
EARTH_DAY = _IMG + "earth-blue-marble.jpg"     # NASA Blue Marble (public domain)
EARTH_NIGHT = _IMG + "earth-night.jpg"         # NASA Black Marble: city lights
EARTH_BUMP = _IMG + "earth-topology.png"
SKY = _IMG + "night-sky.png"


def radio_dir():
    """Where the station cache and the globe's web cache live (read when used, so
    tests that move APP_DIR move this too)."""
    return library.APP_DIR / "radio"


def _http(url: str) -> str:
    """A station's web address, or "" if it isn't http(s) or points into this PC / the
    home network (the directory is community-edited: a listing must not be able to make
    the app send requests to the user's router or local services)."""
    url = str(url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return ""
    # the host as Qt / FFmpeg will really connect to it: 127.1, 2130706433 and
    # 0x7f000001 all become 127.0.0.1 there, which ipaddress wouldn't recognise
    q = QUrl(url)
    host = q.host().rstrip(".").lower() if q.isValid() else ""
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".lan")):
        return ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url   # a name, not an address
    ip = getattr(ip, "ipv4_mapped", None) or ip   # ::ffff:127.0.0.1
    return "" if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified
                  or ip.is_multicast or ip.is_reserved) else url


def _num(v, lo: float, hi: float) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if lo <= f <= hi and f == f else None


@dataclass
class Station:
    uuid: str
    name: str
    url: str
    country: str = ""
    cc: str = ""               # ISO country code
    tags: list[str] = field(default_factory=list)
    codec: str = ""
    bitrate: int = 0
    lat: float | None = None
    lon: float | None = None
    homepage: str = ""
    clicks: int = 0            # plays in the last 24 h (Radio Browser's clickcount)
    votes: int = 0
    trend: int = 0             # change in plays against the day before
    state: str = ""            # region / city
    language: str = ""
    hls: bool = False
    checked: str = ""          # last time the directory found it working (ISO date)
    changed: str = ""          # last time its listing was edited (ISO date)

    @classmethod
    def from_api(cls, d: dict) -> Station | None:
        """A station from Radio Browser's JSON, or None if it's unusable. Everything
        is cleaned here: it's community-edited data."""
        if not isinstance(d, dict):
            return None
        uuid = str(d.get("stationuuid") or "").strip()
        url = _http(d.get("url_resolved")) or _http(d.get("url"))
        name = " ".join(str(d.get("name") or "").split())[:120]
        if not uuid or not url or not name:
            return None
        lat, lon = _num(d.get("geo_lat"), -90, 90), _num(d.get("geo_long"), -180, 180)
        if lat is None or lon is None or (lat == 0 and lon == 0):
            lat = lon = None   # 0,0 is "unknown" more often than a ship in the Atlantic
        tags = [t.strip()[:30] for t in str(d.get("tags") or "").split(",") if t.strip()]
        cc = str(d.get("countrycode") or "").strip().upper()
        def num(key, lo=0):
            try:
                return max(lo, int(d.get(key) or 0))
            except (TypeError, ValueError):
                return 0

        def text(key, n=60):
            return " ".join(str(d.get(key) or "").split())[:n]

        def iso(key):
            v = text(key, 20)
            return v if len(v) >= 10 and v[:4].isdigit() and v[4] == "-" else ""
        bitrate, clicks, votes = num("bitrate"), num("clickcount"), num("votes")
        return cls(uuid=uuid[:64], name=name, url=url,
                   country=" ".join(str(d.get("country") or "").split())[:60],
                   cc=cc if len(cc) == 2 and cc.isalpha() else "",
                   tags=tags[:8], codec=str(d.get("codec") or "")[:12], bitrate=bitrate,
                   lat=lat, lon=lon, homepage=_http(d.get("homepage")), clicks=clicks,
                   votes=votes, trend=num("clicktrend", lo=-10**9),
                   state=text("state"), language=text("language"),
                   hls=str(d.get("hls")) in ("1", "True", "true"),
                   checked=iso("lastcheckoktime_iso8601"),
                   changed=iso("lastchangetime_iso8601"))

    @classmethod
    def from_saved(cls, d: dict) -> Station | None:
        """A station stored by `to_saved` (favourites, the cache)."""
        if not isinstance(d, dict):
            return None
        try:
            s = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except TypeError:
            return None
        return s if s.uuid and _http(s.url) and s.name else None

    def to_saved(self) -> dict:
        return asdict(self)

    def subtitle(self) -> str:
        bits = [self.country or self.cc]
        if self.tags:
            bits.append(", ".join(self.tags[:3]))
        if self.bitrate or self.codec:
            bits.append(" ".join(b for b in (f"{self.bitrate} kbps" if self.bitrate else "",
                                             self.codec) if b))
        return " · ".join(b for b in bits if b)

    def matches(self, words: list[str]) -> bool:
        hay = " ".join((self.name, self.country, self.cc, " ".join(self.tags))).lower()
        return all(w in hay for w in words)


def search_text(text: str) -> str:
    """What a search for `text` actually asks for (and hands back with its results)."""
    return " ".join(text.split())[:SEARCH_MAX_CHARS]


def parse_stations(raw: bytes | str) -> list[Station]:
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    seen, out = set(), []
    for d in data:
        s = Station.from_api(d)
        if s is not None and s.uuid not in seen:
            seen.add(s.uuid)
            out.append(s)
    return out


# --------------------------------------------------------------------------- directory

class RadioDirectory(QObject):
    """Talks to Radio Browser. Every call answers with a signal on the UI thread."""
    globe_ready = Signal(list)          # [Station] with a location, most listened first
    results = Signal(str, list)         # query, [Station]
    failed = Signal(str, str)           # "globe" | "search", message

    def __init__(self, cache_dir=None, bases=API_BASES, parent=None):
        super().__init__(parent)
        self.cache_dir = cache_dir or radio_dir()
        self.bases = list(bases)
        self.nam = QNetworkAccessManager(self)
        self._search_gen = 0
        self._pending: dict[int, list] = {}

    @property
    def cache_path(self):
        return self.cache_dir / "stations.json"

    # -- plumbing
    def _get(self, path: str, done, fail, attempt: int = 0):
        """GET `path` from a mirror; on a network error or a reply that isn't JSON,
        try the next mirror."""
        base = self.bases[attempt % len(self.bases)]
        req = QNetworkRequest(QUrl(base + path))
        req.setHeader(QNetworkRequest.UserAgentHeader, USER_AGENT)
        req.setTransferTimeout(TIMEOUT_MS)
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                         QNetworkRequest.NoLessSafeRedirectPolicy)
        reply = self.nam.get(req)

        def finished():
            reply.deleteLater()
            err = reply.errorString()
            if reply.error() == QNetworkReply.NoError:
                raw = bytes(reply.readAll())
                try:
                    json.loads(raw)
                except ValueError:   # a maintenance page or a captive portal, say
                    err = "the directory sent something that isn't station data"
                else:
                    done(raw)
                    return
            if attempt + 1 < len(self.bases):
                log.info("radio directory %s failed (%s); trying another mirror", base, err)
                self._get(path, done, fail, attempt + 1)
            else:
                fail(err)
        reply.finished.connect(finished)
        return reply

    # -- the globe's stations
    def load_globe(self, force: bool = False):
        cached = self._read_cache()
        if cached is not None and not force and time.time() - cached[0] < CACHE_S:
            QTimer.singleShot(0, lambda: self.globe_ready.emit(cached[1]))
            return
        path = ("/json/stations/search?has_geo_info=true&hidebroken=true"
                f"&order=clickcount&reverse=true&limit={GLOBE_LIMIT}")

        def done(raw):
            stations = [s for s in parse_stations(raw) if s.lat is not None]
            if not stations:
                fail("the directory sent no stations")
                return
            self._write_cache(stations)
            self.globe_ready.emit(stations)

        def fail(msg):
            log.warning("radio directory unavailable: %s", msg)
            if cached is not None:   # an old list beats none
                self.globe_ready.emit(cached[1])
            else:
                self.failed.emit("globe", msg)
        self._get(path, done, fail)

    def _read_cache(self) -> tuple[float, list[Station]] | None:
        try:
            p = self.cache_path
            raw = json.loads(p.read_text(encoding="utf-8"))
            stations = [s for s in map(Station.from_saved, raw.get("stations", [])) if s]
            return (float(raw.get("time", 0)), stations) if stations else None
        except (OSError, ValueError, AttributeError, TypeError):
            return None

    def _write_cache(self, stations: list[Station]):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"time": time.time(),
                                       "stations": [s.to_saved() for s in stations]}),
                           encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError:
            log.warning("can't cache the radio station list", exc_info=True)

    # -- search
    def search(self, text: str):
        """Stations whose name or tags contain `text`, most listened first. A newer
        search makes an older one's results be dropped."""
        text = search_text(text)
        self._search_gen += 1
        gen = self._search_gen
        if not text:
            return
        q = quote(text)
        common = f"&hidebroken=true&order=clickcount&reverse=true&limit={SEARCH_LIMIT}"
        paths = (f"/json/stations/search?name={q}{common}",
                 f"/json/stations/search?tag={q}{common}")
        self._pending[gen] = [len(paths), [], ""]

        def part(raw=b"", err=""):
            st = self._pending.get(gen)
            if st is None:
                return
            st[0] -= 1
            st[1].extend(parse_stations(raw) if raw else [])
            st[2] = st[2] or err
            if st[0]:
                return
            del self._pending[gen]
            if gen != self._search_gen:
                return   # superseded
            if not st[1] and st[2]:
                self.failed.emit("search", st[2])
                return
            seen, merged = set(), []
            for s in sorted(st[1], key=lambda s: -s.clicks):
                if s.uuid not in seen:
                    seen.add(s.uuid)
                    merged.append(s)
            self.results.emit(text, merged)
        for path in paths:
            self._get(path, lambda raw: part(raw), lambda err: part(err=err))

    def count_click(self, uuid: str):
        """Tell the directory a station was started (its popularity ranking)."""
        self._get(f"/json/url/{quote(uuid)}", lambda _raw: None,
                  lambda err: log.debug("radio click not counted: %s", err))


# --------------------------------------------------------------------------- player

def buffer_to_array(buf) -> np.ndarray:
    """A QAudioBuffer as (n, 2) float32 at whatever rate it has. Always a copy: the
    buffer's memory is reused once the slot returns."""
    fmt = buf.format()
    ch = max(1, fmt.channelCount())
    raw = buf.constData()
    if raw is None:
        return np.zeros((0, 2), np.float32)
    kind = fmt.sampleFormat()
    if kind == QAudioFormat.Float:
        x = np.frombuffer(raw, np.float32).copy()
    elif kind == QAudioFormat.Int16:
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    elif kind == QAudioFormat.Int32:
        x = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
    elif kind == QAudioFormat.UInt8:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        return np.zeros((0, 2), np.float32)
    x = x[: len(x) // ch * ch].reshape(-1, ch)
    if ch == 1:
        x = np.repeat(x, 2, axis=1)
    elif ch > 2:
        x = x[:, :2]
    return np.ascontiguousarray(x, np.float32)


class RadioPlayer(QObject):
    """Plays one stream at a time into `audio` (48 kHz stereo float32 chunks)."""
    audio = Signal(object)
    state = Signal(str)          # connecting | playing | stopped | error
    error = Signal(str)
    now_playing = Signal(str)    # the stream's own title (song / show), when it sends one

    def __init__(self, parent=None):
        super().__init__(parent)
        self.station: Station | None = None
        self._player: QMediaPlayer | None = None
        self._out: QAudioBufferOutput | None = None
        self._retries = 0
        self._got_audio = False
        self._reconnecting = False   # a stream that played dropped: reopen until it's back
        self._reopen_pending = False  # a reopen is scheduled: ignore further trouble till then
        self._gen = 0                # bumped by play/stop so a stale reopen does nothing
        self._state = "stopped"
        self._opened = self._last_audio = 0.0
        # FFmpeg can sit on a station that never answers (or stops sending) for
        # minutes, so the player keeps its own watch
        self._watch = QTimer(self)
        self._watch.setInterval(1000)
        self._watch.timeout.connect(self._check)

    def _make(self):
        fmt = QAudioFormat()
        fmt.setSampleRate(SR)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Float)
        self._player = QMediaPlayer(self)
        self._out = QAudioBufferOutput(fmt, self)
        # no QAudioOutput: Qt decodes (at real-time pace) but never plays it itself
        self._player.setAudioBufferOutput(self._out)
        self._out.audioBufferReceived.connect(self._on_buffer)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.metaDataChanged.connect(self._on_meta)

    @property
    def playing(self) -> bool:
        return self.station is not None

    @property
    def status(self) -> str:
        return self._state

    def play(self, station: Station):
        if self._player is None:
            self._make()
        self.station = station
        self._retries = 0
        self._reconnecting = self._reopen_pending = False
        self._gen += 1
        self._open()

    def _open(self):
        self._got_audio = False
        self._opened = time.monotonic()
        self._watch.start()
        self._set_state("connecting")
        self._player.stop()
        self._player.setSource(QUrl(self.station.url))
        self._player.play()

    def stop(self):
        self.station = None
        self._reconnecting = self._reopen_pending = False
        self._gen += 1
        self._watch.stop()
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())
        self._set_state("stopped")

    def _set_state(self, st: str):
        if st != self._state:
            self._state = st
            self.state.emit(st)

    def _on_buffer(self, buf):
        if self.station is None:
            return
        x = buffer_to_array(buf)
        if not len(x):
            return
        if buf.format().sampleRate() != SR:   # Qt was asked for SR; this shouldn't happen
            return
        self._last_audio = time.monotonic()
        if not self._got_audio:
            self._got_audio = True
            self._retries = 0
            self._reconnecting = False
            self._set_state("playing")
        self.audio.emit(x)

    def _check(self):
        if self.station is None:
            self._watch.stop()
            return
        if self._reopen_pending:
            return
        now = time.monotonic()
        if not self._got_audio and now - self._opened > CONNECT_S:
            self._retry("the station didn't answer")
        elif self._got_audio and now - self._last_audio > STALL_S:
            self._retry("the station stopped sending")

    def _on_error(self, _err, msg: str):
        if self.station is None:
            return
        log.info("radio stream error for %s: %s", self.station.url, msg)
        self._retry(msg or "the stream failed")

    def _on_status(self, st):
        if self.station is None:
            return
        if st == QMediaPlayer.EndOfMedia:        # the server hung up: live radio never ends
            self._retry("the station stopped sending")
        elif st == QMediaPlayer.InvalidMedia:
            self._retry("the stream can't be played")

    def _retry(self, msg: str):
        if self._reopen_pending:   # one reopen at a time: the error/status/watchdog all fire
            return
        if (self._got_audio or self._reconnecting) and self._retries < RETRIES:
            self._retries += 1
            self._reconnecting = self._reopen_pending = True
            delay = 500 * self._retries + random.randint(0, 300)
            log.info("reopening the radio stream in %d ms (%s)", delay, msg)
            self._set_state("connecting")
            gen = self._gen
            QTimer.singleShot(delay, lambda: self._reopen(gen))
            return
        self.station = None
        self._reconnecting = False
        self._watch.stop()
        if self._player is not None:
            self._player.stop()
        self._set_state("error")
        self.error.emit(msg)

    def _reopen(self, gen: int):
        if gen != self._gen or self.station is None:
            return
        self._reopen_pending = False
        self._open()

    def _on_meta(self):
        if self._player is None:
            return
        title = self._player.metaData().stringValue(QMediaMetaData.Title)
        title = " ".join(str(title or "").split())[:160]
        if title:
            self.now_playing.emit(title)

    def shutdown(self):
        self.stop()


# --------------------------------------------------------------------------- globe page

def globe_points(stations: list[Station]) -> list[dict]:
    """What the globe needs per station (short keys: this is sent as one JSON blob)."""
    return [{"id": s.uuid, "n": s.name, "c": s.country, "cc": s.cc, "s": s.state,
             "l": s.language, "t": s.tags[:6], "co": s.codec, "b": s.bitrate,
             "v": s.votes, "tr": s.trend, "h": s.hls, "ck": s.checked, "ch": s.changed,
             "la": round(s.lat, 4), "lo": round(s.lon, 4), "k": s.clicks}
            for s in stations if s.lat is not None and s.lon is not None]


def globe_html(qwebchannel_js: str, bg: str, accent: str, hot: str, text: str,
               hd: bool = False) -> str:
    """The globe page. Colours are theme tokens (validated hex), scripts are pinned.

    The light globe (the default) only draws while it's being used: no auto-spin, no
    stars or terrain relief, one pixel per screen pixel. A web view that redraws 60+
    times a second makes the whole app stutter. HD is the full show, opted into with
    the page's HD button. Either one stops drawing while the app is in the background."""
    def hexcol(c: str, fallback: str) -> str:
        c = str(c)
        return c if len(c) == 7 and c[0] == "#" and all(ch in "0123456789abcdefABCDEF"
                                                         for ch in c[1:]) else fallback
    bg, accent = hexcol(bg, "#15171f"), hexcol(accent, "#7c5cff")
    hot, text = hexcol(hot, "#ff4d8d"), hexcol(text, "#e6e8f0")
    csp = ("default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
           "img-src https://cdn.jsdelivr.net data: blob:; style-src 'unsafe-inline'; "
           "connect-src https://cdn.jsdelivr.net data: blob:; worker-src blob:")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{html.escape(csp)}">
<style>
:root{{--accent:{accent};--hot:{hot}}}
html,body{{margin:0;height:100%;overflow:hidden;background:{bg};color:{text};
  font-family:'Segoe UI',sans-serif;user-select:none}}
#g{{position:absolute;inset:0}}
#msg{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  text-align:center;padding:24px;font-size:13px;opacity:.75;pointer-events:none}}
.card{{background:rgba(12,14,22,.94);color:#e9ecf5;border:1px solid var(--accent);
  border-radius:10px;padding:10px 12px;font:12px 'Segoe UI',sans-serif;width:260px;
  box-shadow:0 6px 24px rgba(0,0,0,.5)}}
.card h3{{margin:0 0 2px;font-size:14px;font-weight:600;line-height:1.25}}
.card .where{{opacity:.8;margin-bottom:6px}}
.card .cc{{display:inline-block;background:var(--accent);color:#fff;border-radius:4px;
  padding:0 4px;margin-right:5px;font-size:10px;font-weight:700}}
.card .tags{{margin:4px 0 6px}}
.card .tag{{display:inline-block;background:rgba(255,255,255,.1);border-radius:9px;
  padding:1px 7px;margin:0 3px 3px 0;font-size:11px}}
.card table{{border-collapse:collapse;width:100%}}
.card td{{padding:1px 0;vertical-align:top}}
.card td:first-child{{opacity:.6;padding-right:8px;white-space:nowrap}}
.card .up{{color:#13ce66}} .card .down{{color:#ff8fa3}}
.card .go{{margin-top:7px;color:var(--hot);font-weight:600}}
#zoom{{position:absolute;right:10px;bottom:10px;display:flex;flex-direction:column;gap:4px}}
#zoom button{{width:30px;height:30px;border-radius:8px;border:1px solid rgba(255,255,255,.18);
  background:rgba(12,14,22,.75);color:#fff;font:600 17px 'Segoe UI',sans-serif;cursor:pointer}}
#zoom button:hover{{border-color:var(--accent)}}
#zoom #hd{{font-size:10px;opacity:.6}} #zoom #hd.on{{opacity:1;border-color:var(--accent)}}
#hint{{position:absolute;left:10px;bottom:10px;font-size:11px;opacity:.55;pointer-events:none}}
</style></head><body><div id="g"></div><div id="msg">Loading the globe…</div>
<div id="zoom"><button id="zin" title="Zoom in (Ctrl +)">+</button>
<button id="zout" title="Zoom out (Ctrl −)">−</button>
<button id="look" title="Day / night Earth">☾</button>
<button id="hd" title="">HD</button></div>
<div id="hint">Drag to spin · scroll or Ctrl +/− to zoom · click a dot to play</div>
<script>{qwebchannel_js}</script>
<script src="{GLOBE_JS}" integrity="{GLOBE_SRI}" crossorigin="anonymous"></script>
<script>
"use strict";
let ACCENT = "{accent}", HOT = "{hot}";
const ring = () => t => HOT + Math.round(255 * (1 - t)).toString(16).padStart(2, "0");
let W = null, bridge = null, stations = [], current = null, maxK = 1;
let night = false, HD = {'true' if hd else 'false'};
let asleep = false, idleT = 0, appActive = true;
try {{ night = localStorage.getItem("earth") === "night"; }} catch (e) {{}}
const msg = t => {{ const m = document.getElementById("msg"); m.textContent = t || "";
                   m.style.display = t ? "flex" : "none"; }};
// Draw only while something moves: input, a camera flight, a texture arriving. HD with
// the app in front spins forever, so it never sleeps.
function wake(ms) {{
  if (!W) return;
  if (asleep) {{ W.resumeAnimation(); asleep = false; }}
  clearTimeout(idleT);
  if (!(HD && appActive && W.controls().autoRotate))
    idleT = setTimeout(() => {{ if (W) {{ W.pauseAnimation(); asleep = true; }} }},
                       appActive ? (ms || 1500) : 0);
}}
for (const ev of ["pointerdown", "pointermove", "wheel", "keydown"])
  addEventListener(ev, () => wake(), {{passive: true, capture: true}});
const esc = s => String(s).replace(/[&<>"']/g,
  c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}})[c]);
const ago = iso => {{
  const t = Date.parse(iso.length <= 10 ? iso : iso.replace(" ", "T"));
  if (!t) return "";
  const d = Math.max(0, (Date.now() - t) / 864e5);
  return d < 1 ? "today" : d < 2 ? "yesterday" : d < 60 ? Math.round(d) + " days ago" :
         d < 730 ? Math.round(d / 30.4) + " months ago" : Math.round(d / 365) + " years ago";
}};
const fmtN = n => Number(n || 0).toLocaleString();
function card(d) {{
  // everything from the directory is escaped: it's community-edited
  const rows = [];
  const row = (k, v) => {{ if (v) rows.push("<tr><td>" + k + "</td><td>" + v + "</td></tr>"); }};
  row("Language", esc(d.l || ""));
  row("Audio", esc([d.b ? d.b + " kbps" : "", d.co || "", d.h ? "HLS" : ""]
                   .filter(Boolean).join(" · ")));
  const tr = d.tr || 0;
  row("Plays today", fmtN(d.k) + (tr ? ' <span class="' + (tr > 0 ? "up" : "down") + '">' +
      (tr > 0 ? "▲ " : "▼ ") + fmtN(Math.abs(tr)) + "</span>" : ""));
  row("Votes", d.v ? "♥ " + fmtN(d.v) : "");
  row("Working", d.ck ? "checked " + esc(ago(d.ck)) : "");
  row("Listed info", d.ch ? "updated " + esc(ago(d.ch)) : "");
  const where = [d.s, d.c].filter(Boolean).map(esc).join(", ");
  const tags = (d.t || []).map(t => '<span class="tag">' + esc(t) + "</span>").join("");
  return '<div class="card"><h3>' + esc(d.n) + "</h3>" +
    '<div class="where">' + (d.cc ? '<span class="cc">' + esc(d.cc) + "</span>" : "") +
    where + "</div>" + (tags ? '<div class="tags">' + tags + "</div>" : "") +
    "<table>" + rows.join("") + "</table>" +
    '<div class="go">' + (d.id === current ? "▶ Playing now" : "▶ Click to play") +
    "</div></div>";
}}

// zoom: the wheel (with or without Ctrl), Ctrl +/−/0 and the buttons. Ctrl+wheel and
// Ctrl +/− would otherwise zoom the whole page instead of the globe.
function zoom(f, ms) {{
  if (!W) return;
  const p = W.pointOfView();
  W.controls().autoRotate = false;
  W.pointOfView({{altitude: Math.min(5, Math.max(0.12, p.altitude * f))}}, ms);
  wake(ms + 1500);
}}
function fly(lat, lng, altitude, ms) {{
  if (!W) return;
  W.controls().autoRotate = false;
  W.pointOfView({{lat, lng, altitude}}, ms);
  wake(ms + 1500);
}}
addEventListener("wheel", e => {{
  e.preventDefault();
  zoom(Math.exp(Math.max(-60, Math.min(60, e.deltaY)) * (e.ctrlKey ? 0.006 : 0.003)), 0);
}}, {{passive: false, capture: true}});
addEventListener("keydown", e => {{
  const k = e.key;
  if (k === "+" || k === "=" || k === "-" || k === "_" || (e.ctrlKey && k === "0")) {{
    e.preventDefault();
    if (k === "0") {{ if (W) {{ W.pointOfView({{altitude: 2.4}}, 600); wake(2100); }} }}
    else zoom(k === "-" || k === "_" ? 1.35 : 1 / 1.35, 250);
  }}
}}, true);
const look = document.getElementById("look");
const setLook = () => {{
  look.textContent = night ? "☀" : "☾";
  if (W) {{ W.globeImageUrl(night ? "{EARTH_NIGHT}" : "{EARTH_DAY}"); wake(4000); }}
}};
look.onclick = () => {{
  night = !night;
  try {{ localStorage.setItem("earth", night ? "night" : "day"); }} catch (e) {{}}
  setLook();
}};
setLook();
const hdBtn = document.getElementById("hd");
function applyHd() {{
  hdBtn.classList.toggle("on", HD);
  hdBtn.title = HD ? "High detail is on: stars, terrain, a spinning globe and every " +
    "station. Click for the light globe (smoother on slower PCs)."
    : "Light globe: smoother for the rest of the app. Click for high detail " +
    "(stars, terrain, a spinning globe, more stations; uses more graphics power).";
  if (!W) return;
  W.renderer().setPixelRatio(HD ? devicePixelRatio : 1);
  W.backgroundImageUrl(HD ? "{SKY}" : null).bumpImageUrl(HD ? "{EARTH_BUMP}" : null)
   .pointResolution(HD ? 6 : 4);
  W.controls().autoRotate = HD;
  wake(4000);
}}
hdBtn.onclick = () => {{
  HD = !HD; applyHd();
  if (bridge) bridge.setHd(HD);   // remembered, and the app sends the right number of dots
}};
applyHd();
function setActive(on) {{
  // the app went to the background (a game, another window): stop drawing
  appActive = !!on;
  wake();
}}
document.getElementById("zin").onclick = () => zoom(1 / 1.35, 250);
document.getElementById("zout").onclick = () => zoom(1.35, 250);
try {{ new QWebChannel(qt.webChannelTransport, ch => {{ bridge = ch.objects.radio; }}); }}
catch (e) {{ /* no app to talk to (a plain browser): the globe still works */ }}

function build() {{
  if (typeof Globe !== "function") {{
    msg("The globe couldn't load (it needs the internet the first time). " +
        "Search and the station list still work.");
    return;
  }}
  try {{
    W = Globe({{animateIn: true}})(document.getElementById("g"))
      .backgroundColor("{bg}")
      .globeImageUrl(night ? "{EARTH_NIGHT}" : "{EARTH_DAY}")
      .onGlobeReady(() => wake(2500))
      .showAtmosphere(true).atmosphereColor("#7fb8ff").atmosphereAltitude(0.16)
      .pointLat("la").pointLng("lo")
      .pointAltitude(d => d.id === current ? 0.08 : 0.004 + 0.03 * Math.sqrt(d.k / maxK))
      .pointRadius(d => d.id === current ? 0.55 : 0.33)
      .pointColor(d => d.id === current ? HOT : ACCENT)
      .pointLabel(card)
      .onPointClick(d => {{ if (bridge) bridge.play(d.id); }})
      .ringLat("la").ringLng("lo").ringColor(ring)
      .ringMaxRadius(3).ringPropagationSpeed(2).ringRepeatPeriod(900);
    const c = W.controls();
    c.autoRotateSpeed = 0.35;
    c.enableZoom = false;   // our own wheel handler zooms (see zoom above)
    const m = W.globeMaterial();
    if (m.specular) {{ m.specular.setStyle("#222a38"); m.shininess = 12; }}   // a soft sheen
    W.renderer().domElement.addEventListener("pointerdown", () => {{ c.autoRotate = false; }});
    const fit = () => W.width(innerWidth).height(innerHeight);
    addEventListener("resize", fit); fit();
    W.pointOfView({{lat: 25, lng: 10, altitude: 2.4}});
    applyHd();
    msg(stations.length ? "" : "Finding stations…");
    if (stations.length) W.pointsData(stations);
  }} catch (e) {{
    W = null;
    msg("The globe can't be shown here (" + e.message + "). Search and the list still work.");
  }}
}}

function setStations(list) {{
  stations = list; maxK = Math.max(1, ...list.map(d => d.k));
  if (W) {{ W.pointsData(stations); msg(""); wake(); }}
}}
function select(p, go) {{
  // p: the playing station's point (or null); one found by search is added to the globe
  current = p ? p.id : null;
  if (p && !stations.some(d => d.id === p.id)) stations = stations.concat([p]);
  if (!W) return;
  W.pointsData(stations);
  const s = stations.find(d => d.id === current);
  W.ringsData(s ? [s] : []);
  if (s && go) fly(s.la, s.lo, 1.5, 1200); else wake();
}}
function showMessage(t) {{ msg(t); }}
function setTheme(bg, accent, hot, text) {{
  // a live theme switch in the app: recolour without reloading the globe
  ACCENT = accent; HOT = hot;
  const r = document.documentElement.style;
  r.setProperty("--accent", accent); r.setProperty("--hot", hot);
  document.body.style.background = bg; document.body.style.color = text;
  if (!W) return;
  W.backgroundColor(bg);   // setting the accessors again makes the globe redraw with them
  W.pointColor(d => d.id === current ? HOT : ACCENT);
  W.ringColor(ring);
  wake();
}}
build();
</script></body></html>"""
