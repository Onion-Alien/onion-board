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

import base64
import hashlib
import html
import ipaddress
import json
import logging
import random
import socket
import threading
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
GLOBE_LIMIT = 3000         # stations fetched for the map (the most listened-to)
GLOBE_LIGHT = 1000         # ...of which the 3D globe pins this many (the flat map: all)
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
# Natural Earth country outlines (public domain), where the globe's country names go
COUNTRIES = ("https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/example/datasets/"
             "ne_110m_admin_0_countries.geojson")
COUNTRIES_SRI = "sha384-hAVr+/g2HDlVDeHrAVqTIQV3tH1JE5AbtuvCSCcoeG+ZDteCU2XGaE5yLDiLP9m5"
# The outlines are coarse and leave out small countries and islands. These are named
# too: (name, lat, lon, width in degrees, which decides how far in you zoom to see it).
PLACES = (
    ("Hawaii", 20.5, -157.0, 5), ("Tasmania", -42.0, 146.6, 4), ("Svalbard", 78.5, 17.0, 4),
    ("Sicily", 37.6, 14.1, 2.5), ("Sardinia", 40.1, 9.0, 1.5), ("Corsica", 42.15, 9.1, 1),
    ("Crete", 35.25, 24.9, 2), ("Mallorca", 39.6, 2.95, 1), ("Faroe Islands", 62.0, -6.9, 1),
    ("Canary Islands", 28.3, -15.9, 3), ("Azores", 38.5, -28.2, 3), ("Madeira", 32.75, -17.0, 1),
    ("Cape Verde", 15.1, -23.6, 2), ("Sao Tome and Principe", 0.25, 6.6, 1),
    ("Galapagos", -0.7, -90.5, 2), ("Bermuda", 32.3, -64.75, 1), ("Singapore", 1.35, 103.82, 1),
    ("Hong Kong", 22.32, 114.17, 1), ("Bali", -8.4, 115.2, 1.5), ("Malta", 35.9, 14.45, 1),
    ("Bahrain", 26.05, 50.55, 1), ("Maldives", 3.2, 73.2, 2), ("Mauritius", -20.25, 57.55, 1),
    ("Reunion", -21.1, 55.5, 1), ("Seychelles", -4.6, 55.45, 1), ("Comoros", -11.9, 43.9, 1),
    ("Zanzibar", -6.1, 39.3, 0.8), ("Barbados", 13.17, -59.55, 0.6),
    ("Saint Lucia", 13.9, -60.97, 0.5), ("Grenada", 12.11, -61.68, 0.5),
    ("Saint Vincent", 13.25, -61.2, 0.5), ("Dominica", 15.42, -61.35, 0.5),
    ("Antigua", 17.07, -61.8, 0.5), ("Saint Kitts", 17.3, -62.73, 0.5),
    ("Guadeloupe", 16.2, -61.55, 0.6), ("Martinique", 14.64, -61.02, 0.5),
    ("Aruba", 12.52, -69.97, 0.5), ("Curacao", 12.17, -68.99, 0.5), ("Samoa", -13.75, -172.1, 1.5),
    ("American Samoa", -14.3, -170.7, 0.6), ("Tonga", -21.18, -175.2, 1.5),
    ("Tahiti", -17.65, -149.43, 1), ("Cook Islands", -21.23, -159.78, 0.8),
    ("Guam", 13.44, 144.79, 0.8), ("Northern Mariana Islands", 15.2, 145.75, 0.6),
    ("Palau", 7.5, 134.6, 1), ("Micronesia", 6.9, 158.2, 1.5),
    ("Marshall Islands", 7.1, 171.2, 1.5),
    ("Nauru", -0.53, 166.93, 0.5), ("Kiribati", 1.42, 172.98, 1), ("Tuvalu", -8.52, 179.2, 0.8),
)
# how the outlines' short names read on the globe; None leaves one unnamed
COUNTRY_NAMES = {
    "United States of America": "United States", "Dem. Rep. Congo": "DR Congo",
    "Central African Rep.": "Central African Republic", "Bosnia and Herz.": "Bosnia",
    "Dominican Rep.": "Dominican Republic", "Eq. Guinea": "Equatorial Guinea",
    "S. Sudan": "South Sudan", "W. Sahara": "Western Sahara", "Falkland Is.": "Falkland Islands",
    "Solomon Is.": "Solomon Islands", "Macedonia": "North Macedonia", "Swaziland": "Eswatini",
    "Côte d'Ivoire": "Ivory Coast", "Fr. S. Antarctic Lands": None, "N. Cyprus": None,
    "Somaliland": None,
}


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
        return url   # a name, not an address: RadioPlayer looks up where it points
    return "" if _local_ip(ip) else url


def _local_ip(ip) -> bool:
    """Is this address this PC or the home network (or nowhere real)?"""
    ip = getattr(ip, "ipv4_mapped", None) or ip   # ::ffff:127.0.0.1
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified
            or ip.is_multicast or ip.is_reserved)


def _name_is_local(host: str) -> bool:
    """Does the station's host name lead into this PC / the home network? A name that
    doesn't resolve isn't refused here: the stream just fails to connect, as it would."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    for info in infos:
        try:
            if _local_ip(ipaddress.ip_address(info[4][0].split("%")[0])):
                return True
        except ValueError:
            continue
    return False


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


def _outline_features(raw: bytes) -> list[tuple[dict, list[list[tuple[float, float]]]]]:
    """(properties, outer rings as (lon, lat)) per country, or [] unless `raw` is
    exactly the pinned outline file (checked like the globe's SRI)."""
    if not isinstance(raw, bytes | bytearray):
        return []
    digest = "sha384-" + base64.b64encode(hashlib.sha384(raw).digest()).decode()
    if digest != COUNTRIES_SRI:
        return []
    try:
        features = json.loads(raw)["features"]
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for f in features:
        g = f.get("geometry") or {}
        polys = ([g.get("coordinates")] if g.get("type") == "Polygon"
                 else g.get("coordinates") if g.get("type") == "MultiPolygon" else [])
        rings = [[(float(x), float(y)) for x, y, *_ in poly[0]]
                 for poly in polys or [] if poly and len(poly[0]) >= 3]
        if rings:
            out.append((f.get("properties") or {}, rings))
    return out


def outline_rings(raw: bytes) -> list[list[tuple[float, float]]]:
    """The land outlines for the flat map: each country's outer rings as (lon, lat), or
    [] unless `raw` is exactly the pinned outline file."""
    return [r for _props, rings in _outline_features(raw) for r in rings]


def _centre(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    """A ring's centroid (lon, lat) and its area (shoelace, in square degrees)."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        k = x0 * y1 - x1 * y0
        a += k
        cx += (x0 + x1) * k
        cy += (y0 + y1) * k
    if abs(a) < 1e-9:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys), 0.0
    return cx / (3 * a), cy / (3 * a), abs(a) / 2


def outline_labels(raw: bytes) -> list[tuple[str, float, float, float]]:
    """Names for the flat map: (name, lon, lat, width in degrees) per country, on its
    biggest piece of land, plus the small places the outlines leave out (PLACES).
    [] unless `raw` is the pinned outline file."""
    out = []
    for props, rings in _outline_features(raw):
        name = str(props.get("NAME") or props.get("ADMIN") or "")
        name = COUNTRY_NAMES.get(name, name)
        if not name:
            continue
        ring = max(rings, key=lambda r: _centre(r)[2])
        lon, lat, _a = _centre(ring)
        xs = [p[0] for p in ring]
        out.append((name, lon, lat, max(xs) - min(xs)))
    if out:
        out += [(name, lon, lat, w) for name, lat, lon, w in PLACES]
    return out


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
    # outline_rings() and outline_labels(): the flat map's land and names ([] offline)
    outlines_ready = Signal(list, list)
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

    @property
    def outlines_path(self):
        return self.cache_dir / "countries.geojson"

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
        self.globe_stale = ""   # set when a refresh failed and the saved list stands in
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
            self.globe_stale = ""
            self.globe_ready.emit(stations)

        def fail(msg):
            log.warning("radio directory unavailable: %s", msg)
            if cached is not None:   # an old list beats none
                self.globe_stale = msg or "no answer"
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

    # -- the flat map's land
    def load_outlines(self):
        """The country outlines, from the cache (they're pinned, so it never goes stale)
        or jsDelivr. Answers [] when neither has them: the map shows just its dots."""
        try:
            raw = self.outlines_path.read_bytes()
        except OSError:
            raw = b""
        rings = outline_rings(raw)
        if rings:
            labels = outline_labels(raw)
            QTimer.singleShot(0, lambda: self.outlines_ready.emit(rings, labels))
            return
        req = QNetworkRequest(QUrl(COUNTRIES))
        req.setHeader(QNetworkRequest.UserAgentHeader, USER_AGENT)
        req.setTransferTimeout(TIMEOUT_MS)
        reply = self.nam.get(req)

        def finished():
            reply.deleteLater()
            raw = bytes(reply.readAll()) if reply.error() == QNetworkReply.NoError else b""
            rings = outline_rings(raw)
            if rings:
                try:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    tmp = self.outlines_path.with_suffix(".tmp")
                    tmp.write_bytes(raw)
                    tmp.replace(self.outlines_path)
                except OSError:
                    log.warning("can't cache the map outlines", exc_info=True)
            else:
                log.info("map outlines unavailable: %s", reply.errorString() if not raw
                         else "the file didn't match its pinned hash")
            self.outlines_ready.emit(rings, outline_labels(raw) if rings else [])
        reply.finished.connect(finished)

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
    _looked_up = Signal(int, bool)   # (play generation, the host is local): lookup thread

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
        self._looked_up.connect(self._on_looked_up)

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
        host = QUrl(station.url).host()
        try:
            ipaddress.ip_address(host)   # an address was already checked (_http)
        except ValueError:   # a name: where it leads is looked up first, off the UI thread
            self._set_state("connecting")
            gen = self._gen
            threading.Thread(target=lambda: self._looked_up.emit(gen, _name_is_local(host)),
                             daemon=True, name="radio-lookup").start()
            return
        self._open()

    def _on_looked_up(self, gen: int, local: bool):
        if gen != self._gen or self.station is None:
            return
        if not local:
            self._open()
            return
        log.warning("radio: refused %s, its address is on this PC / home network",
                    self.station.url)
        self.station = None
        self._set_state("error")
        self.error.emit("this station points into your home network, so it isn't played")

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


def globe_html(qwebchannel_js: str, bg: str, accent: str, hot: str, text: str) -> str:
    """The 3D globe page (the Radio tab's HD view; the flat map is the default). Colours
    are theme tokens (validated hex), scripts are pinned.

    It only draws while it's being used: no auto-spin, no stars or terrain relief, one
    pixel per screen pixel. A web view that redraws 60+ times a second makes the whole
    app stutter. It stops drawing at once while the app is in the background."""
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
#zoom #flat,#zoom #names{{font-size:10px;opacity:.6}}
#zoom #names.on{{opacity:1;border-color:var(--accent)}}
.place{{font:600 11px 'Segoe UI',sans-serif;color:#fff;white-space:nowrap;pointer-events:none;
  text-shadow:0 0 3px #000,0 0 2px #000,0 1px 2px #000;opacity:.9;letter-spacing:.2px}}
body.nogl .place{{visibility:hidden!important}}
.place.big{{font-size:13px}} .place.isle{{font-weight:400;font-style:italic;opacity:.8}}
#hint{{position:absolute;left:10px;bottom:10px;font-size:11px;opacity:.55;pointer-events:none}}
</style></head><body><div id="g"></div><div id="msg">Loading the globe…</div>
<div id="zoom"><button id="zin" title="Zoom in (Ctrl +)">+</button>
<button id="zout" title="Zoom out (Ctrl −)">−</button>
<button id="look" title="Day / night Earth">☾</button>
<button id="names" title="Country and island names on / off">Aa</button>
<button id="flat" title="Back to the flat map (lighter on your PC)">2D</button></div>
<div id="hint">Drag to spin · scroll or Ctrl +/− to zoom · click a dot to play</div>
<script>{qwebchannel_js}</script>
<script src="{GLOBE_JS}" integrity="{GLOBE_SRI}" crossorigin="anonymous"></script>
<script>
"use strict";
let ACCENT = "{accent}", HOT = "{hot}";
const ring = () => t => HOT + Math.round(255 * (1 - t)).toString(16).padStart(2, "0");
let W = null, bridge = null, stations = [], current = null, maxK = 1;
let night = false;
let asleep = false, idleT = 0, appActive = true, fitting = false;
try {{ night = localStorage.getItem("earth") === "night"; }} catch (e) {{}}
const msg = t => {{ const m = document.getElementById("msg"); m.textContent = t || "";
                   m.style.display = t ? "flex" : "none"; }};
// Draw only while something moves: input, a camera flight, a texture arriving, the
// window being moved or resized. In the background it still draws a moment, so a resize
// or a move to another screen (which blanks the picture) is redrawn before it sleeps.
function wake(ms) {{
  if (!W) return;
  if (asleep) {{ W.resumeAnimation(); asleep = false; }}
  if (!fitting) {{ fitting = true; requestAnimationFrame(fitLoop); }}
  clearTimeout(idleT);
  idleT = setTimeout(() => {{ if (W) {{ W.pauseAnimation(); asleep = true; }} }},
                     appActive ? (ms || 1500) : 250);
}}
function fitLoop() {{
  // the names are re-placed on every frame the globe draws (so, not while it sleeps)
  if (asleep || !W) {{ fitting = false; return; }}
  fitNames();
  requestAnimationFrame(fitLoop);
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
  W.pointOfView({{altitude: Math.min(5, Math.max(0.12, p.altitude * f))}}, ms);
  wake(ms + 1500);
}}
function fly(lat, lng, altitude, ms) {{
  if (!W) return;
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
document.getElementById("flat").onclick = () => {{ if (bridge) bridge.setHd(false); }};
function setActive(on) {{
  // the app went to the background (a game, another window): stop drawing
  appActive = !!on;
  wake();
}}

// Country and island names. They're HTML on top of the globe, so they stay the same
// readable size at any zoom; a name only shows once its country is wider on screen
// than the name, so zoomed out you see the big countries and zooming in adds the rest.
let places = [], showNames = true;
try {{ showNames = localStorage.getItem("names") !== "off"; }} catch (e) {{}}
const namesBtn = document.getElementById("names");
function labelPoint(ring) {{
  // the point deepest inside the outline (a centre can fall outside: Vietnam, Croatia)
  let x0 = 180, x1 = -180, y0 = 90, y1 = -90;
  for (const [x, y] of ring) {{ x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y);
                               y1 = Math.max(y1, y); }}
  const k = Math.cos((y0 + y1) / 2 * Math.PI / 180);   // a degree of longitude is shorter
  const inside = (x, y) => {{
    let n = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {{
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) n = !n;
    }}
    return n;
  }};
  const depth = (x, y) => {{
    let best = Infinity;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {{
      const ax = ring[j][0] * k, ay = ring[j][1], bx = ring[i][0] * k, by = ring[i][1];
      const dx = bx - ax, dy = by - ay, px = x * k - ax, py = y - ay;
      const t = Math.max(0, Math.min(1, (px * dx + py * dy) / (dx * dx + dy * dy || 1)));
      best = Math.min(best, Math.hypot(px - t * dx, py - t * dy));
    }}
    return best;
  }};
  let bx = (x0 + x1) / 2, by = (y0 + y1) / 2, bd = -1;
  let sx = (x1 - x0) / 24, sy = (y1 - y0) / 24, cx = bx, cy = by;
  for (let pass = 0; pass < 2; pass++) {{   // a coarse grid, then a finer one around the best
    for (let i = -12; i <= 12; i++) for (let j = -12; j <= 12; j++) {{
      const x = cx + i * sx, y = cy + j * sy;
      if (!inside(x, y)) continue;
      const d = depth(x, y);
      if (d > bd) {{ bd = d; bx = x; by = y; }}
    }}
    cx = bx; cy = by; sx /= 10; sy /= 10;
  }}
  return {{la: by, lo: bx, w: (x1 - x0) * k}};
}}
const area = ring => {{
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++)
    a += (ring[j][0] - ring[i][0]) * (ring[j][1] + ring[i][1]);
  return Math.abs(a / 2) * Math.cos(ring[0][1] * Math.PI / 180);
}};
const RENAME = {json.dumps(COUNTRY_NAMES)};
function loadPlaces() {{
  const extra = {json.dumps([{"n": n, "la": la, "lo": lo, "w": w, "isle": 1}
                             for n, la, lo, w in PLACES])};
  fetch("{COUNTRIES}", {{integrity: "{COUNTRIES_SRI}"}}).then(r => r.json()).then(geo => {{
    const list = [];
    for (const f of geo.features) {{
      const p = f.properties, g = f.geometry;
      let n = RENAME.hasOwnProperty(p.NAME) ? RENAME[p.NAME] : p.NAME;
      if (!n || !g) continue;
      const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
      const main = polys.map(q => q[0]).reduce((a, b) => area(b) > area(a) ? b : a);
      list.push(Object.assign({{n}}, labelPoint(main)));
    }}
    setPlaces(list.concat(extra));
  }}).catch(() => setPlaces(extra));   // offline: the islands still get their names
}}
function setPlaces(list) {{
  places = list.sort((a, b) => b.w - a.w);   // the biggest get first claim on the space
  if (W) {{ W.htmlElementsData(places); wake(3000); }}
  setTimeout(fitNames, 50);   // the globe makes the name elements on its next update
}}
function placeEl(d) {{
  const el = document.createElement("div");
  el.className = "place" + (d.isle ? " isle" : d.w > 25 ? " big" : "");
  el.style.visibility = "hidden";   // until fitNames decides
  el.textContent = d.n;
  d.el = el;
  return el;
}}
function fitNames() {{
  // Runs on every frame drawn. A name shows when its country is about as wide on screen
  // as the name (an island: once it's a speck you can see, as the sea around it is free),
  // it isn't near the globe's edge, and it doesn't cover a bigger one's.
  if (!W) return;
  const pov = W.pointOfView(), R = Math.PI / 180;
  // px per degree in the middle of the view: the camera is alt globe radii up, 50° fov
  const pxDeg = innerHeight / (2 * pov.altitude * Math.tan(25 * R) * 57.3);
  const s0 = Math.sin(pov.lat * R), c0 = Math.cos(pov.lat * R), kept = [];
  for (const d of places) {{
    if (!d.el) continue;
    // cosine of the angle from the middle of the view: 1 facing us, 0 at the edge
    const facing = s0 * Math.sin(d.la * R) +
                   c0 * Math.cos(d.la * R) * Math.cos((d.lo - pov.lng) * R);
    let show = showNames && facing > 0.45 &&
               d.w * pxDeg * facing >= (d.isle ? 12 : d.n.length * 5.2);
    if (show) {{
      if (!d.pw) {{ d.pw = d.el.offsetWidth; d.ph = d.el.offsetHeight; }}
      const p = W.getScreenCoords(d.la, d.lo, 0.01);
      const box = [p.x - d.pw / 2 - 3, p.y - d.ph / 2, p.x + d.pw / 2 + 3, p.y + d.ph / 2];
      show = !kept.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1]);
      if (show) kept.push(box);
    }}
    d.el.style.visibility = show ? "" : "hidden";
  }}
}}
function applyNames() {{
  namesBtn.classList.toggle("on", showNames);
  fitNames(); wake();
}}
namesBtn.onclick = () => {{
  showNames = !showNames;
  try {{ localStorage.setItem("names", showNames ? "on" : "off"); }} catch (e) {{}}
  applyNames();
}};
namesBtn.classList.toggle("on", showNames);
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
      .pointResolution(4)
      .pointLat("la").pointLng("lo")
      .pointAltitude(d => d.id === current ? 0.08 : 0.004 + 0.03 * Math.sqrt(d.k / maxK))
      .pointRadius(d => d.id === current ? 0.55 : 0.33)
      .pointColor(d => d.id === current ? HOT : ACCENT)
      .pointLabel(card)
      .onPointClick(d => {{ if (bridge) bridge.play(d.id); }})
      .ringLat("la").ringLng("lo").ringColor(ring)
      .ringMaxRadius(3).ringPropagationSpeed(2).ringRepeatPeriod(900)
      .htmlLat("la").htmlLng("lo").htmlAltitude(0.01).htmlElement(placeEl)
      .htmlTransitionDuration(0).htmlElementsData(places);
    const c = W.controls();
    c.enableZoom = false;   // our own wheel handler zooms (see zoom above)
    const m = W.globeMaterial();
    if (m.specular) {{ m.specular.setStyle("#222a38"); m.shininess = 12; }}   // a soft sheen
    const cv = W.renderer().domElement;
    // The names are page text, the globe a WebGL picture. Moving the window to another
    // screen can lose the picture (a lost context, or a resize that clears it while the
    // globe sleeps) while the text stays, so the names hide until the globe is back.
    cv.addEventListener("webglcontextlost", () => {{ document.body.classList.add("nogl"); }});
    cv.addEventListener("webglcontextrestored", () => {{
      document.body.classList.remove("nogl"); wake(3000);
    }});
    const fit = () => {{
      W.renderer().setPixelRatio(1);
      W.width(innerWidth).height(innerHeight); fitNames(); wake();   // resizing clears it
    }};
    const onDpr = () => {{   // a screen with another scale: no resize event for that alone
      fit();
      matchMedia("(resolution: " + devicePixelRatio + "dppx)")
        .addEventListener("change", onDpr, {{once: true}});
    }};
    W.pointOfView({{lat: 25, lng: 10, altitude: 2.4}});
    addEventListener("resize", fit); fit();
    matchMedia("(resolution: " + devicePixelRatio + "dppx)")
      .addEventListener("change", onDpr, {{once: true}});
    document.addEventListener("visibilitychange", () => {{ if (!document.hidden) wake(); }});
    msg(stations.length ? "" : "Finding stations…");
    if (stations.length) W.pointsData(stations);
    loadPlaces();
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
