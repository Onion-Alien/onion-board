"""Radio tab back end: the station directory, the stream player and the map's data.

Stations come from Radio Browser (https://www.radio-browser.info), a free,
community-run open directory of ~60 000 internet radio stations with an open API
and no key. Most stations carry a latitude / longitude, which the map uses.
The app asks it for: the most-listened stations that have a location (the map,
cached for a day in radio_dir()), searches you type, and a "click" when you
start a station (the directory's own popularity count, which it asks clients to
send; Settings > Privacy & security turns it off). Nothing else about you is sent. With Radio
switched off in Settings > Privacy & security none of it goes online (FEATURE): the
tab shows an "off" panel instead and the relay refuses the directory and the streams.

The player is Qt Multimedia (FFmpeg): it opens the stream (MP3, AAC, Ogg, HLS…)
and decodes it, but never plays it itself. A QAudioBufferOutput hands the decoded
audio to the UI thread as 48 kHz stereo float, which goes into the engine
(`Engine.feed_radio`) like an app's captured audio (Apps tab), so it can go out
with your sounds.

The map is painted by Qt (ui/flatmap.py). Its country outlines ship with the app
(ASSET_DIR), so opening it contacts nobody: no CDN learns who opened the Radio tab.
(Up to 1.9.7 an "HD" button swapped in a 3D globe, globe.gl in a web view. It went:
the web engine cost ~200 MB of the install, forced GPU drawing on every window and
kept Chromium in the app once opened.)
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import random
import re
import socket
import threading
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path
from urllib.parse import quote

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QMediaMetaData, QMediaPlayer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from soundboard import library, net, netlog, quality
from soundboard.engine import SR

log = logging.getLogger(__name__)

# Radio Browser mirrors. `all.` round-robins across them; the rest are fallbacks.
API_BASES = ("https://all.api.radio-browser.info", "https://de1.api.radio-browser.info",
             "https://de2.api.radio-browser.info")
GLOBE_LIMIT = 3000         # stations fetched for the map (the most listened-to)
SEARCH_LIMIT = 150
SEARCH_MAX_CHARS = 80
CACHE_S = 24 * 3600        # how long the map's station list is reused
TIMEOUT_MS = 15000
USER_AGENT = "OnionBoard"   # Radio Browser asks apps to name themselves; no version
FEATURE = "radio"           # its switch in Settings > Privacy & security (soundboard.net)
RETRIES = 3                # a dropped stream is reopened this many times in a row
CONNECT_S = 20.0           # a station that sends no audio this long after opening is dead
STALL_S = 8.0              # ...and one that goes quiet this long while playing is reopened
# Over Tor a stream's circuit can break (a relay in it goes away, or Tor restarts) and a
# new one takes longer to open: more reopens, more time, and no giving up while Tor
# itself is still connecting (its own wait fails the stream if it never does)
TOR_RETRIES = 6
TOR_CONNECT_S = 60.0

# The map's outlines ship with the app: assets/radio in a source checkout, radio/ in the
# frozen app (build.ps1 bundles it). Nothing is fetched from a CDN.
ASSET_DIR = (Path(sys._MEIPASS) / "radio" if hasattr(sys, "_MEIPASS")
             else Path(__file__).resolve().parent.parent / "assets" / "radio")
# Natural Earth country outlines (public domain): the map's land, where its names go
COUNTRIES = "ne_110m_admin_0_countries.geojson"
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
# how the outlines' short names read on the map; None leaves one unnamed
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
    """Where the station cache lives (read when used, so tests that move APP_DIR move
    this too)."""
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


PLAYLIST_EXTS = (".pls", ".m3u", ".asx", ".xspf")   # `url` is often one; FFmpeg can't play it


def _stream_url(d: dict) -> str:
    """The station's stream: `url_resolved` (the directory follows playlists for it),
    but its listed `url` when only that one is https and it's a stream, not a playlist,
    so the network in between sees a station host and not which station it is."""
    resolved, listed = _http(d.get("url_resolved")), _http(d.get("url"))
    if (resolved.lower().startswith("http://") and listed.lower().startswith("https://")
            and not QUrl(listed).path().lower().endswith(PLAYLIST_EXTS)):
        return listed
    return resolved or listed


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
        url = _stream_url(d)
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
        """Every one of `words` (folded with fold()) is in its name, place or tags."""
        hay = self.search_hay
        return all(w in hay for w in words)

    # Worked out once per station, not on every keystroke or filter change (folding
    # 3000 stations' text took ~20 ms a pass). Setting any field drops them, so they
    # are worked out again from the new data.
    _DERIVED = ("search_hay", "genre_hay", "map_point")

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        d = self.__dict__
        for k in Station._DERIVED:
            d.pop(k, None)

    @cached_property
    def search_hay(self) -> str:
        """Its name, place and tags folded with fold(): what a search looks in."""
        return fold(" ".join((self.name, self.country, self.cc, self.state,
                              " ".join(self.tags))))

    @cached_property
    def genre_hay(self) -> str:
        """Its tags in lower case, one per line (a genre word never spans two)."""
        return "\n".join(t.lower() for t in self.tags)

    @cached_property
    def map_point(self) -> dict:
        """globe_points()'s dict for it (it must have lat and lon). Shared: don't change it."""
        return {"id": self.uuid, "n": self.name, "c": self.country, "cc": self.cc,
                "s": self.state, "l": self.language, "t": self.tags[:6], "co": self.codec,
                "b": self.bitrate, "v": self.votes, "tr": self.trend, "h": self.hls,
                "ck": self.checked, "ch": self.changed, "la": round(self.lat, 4),
                "lo": round(self.lon, 4), "k": self.clicks}


def fold(text: str) -> str:
    """Text to search in, or for: lower case without accents, so "zurich" finds
    "Zürich" and "istanbul" finds "İstanbul"."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(ch))


def search_text(text: str) -> str:
    """What a search for `text` actually asks for (and hands back with its results)."""
    return " ".join(text.split())[:SEARCH_MAX_CHARS]


def _outline_features(raw: bytes) -> list[tuple[dict, list[list[tuple[float, float]]]]]:
    """(properties, outer rings as (lon, lat)) per country, or [] unless `raw` is
    exactly the pinned outline file (checked by its hash)."""
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


_DECODER = json.JSONDecoder()
_SPACE = re.compile(r"[ \t\n\r]*")


def _array(s: str, i: int) -> tuple[list, int]:
    """The JSON array at s[i] (its "["), decoded one element at a time; returns it and
    the index just after its "]"."""
    out = []
    i = _SPACE.match(s, i + 1).end()
    if s.startswith("]", i):
        return out, i + 1
    while True:
        v, i = _DECODER.raw_decode(s, i)
        out.append(v)
        i = _SPACE.match(s, i).end()
        if s.startswith(",", i):
            i = _SPACE.match(s, i + 1).end()
        elif s.startswith("]", i):
            return out, i + 1
        else:
            raise ValueError(f"expected ',' or ']' at {i}")


def loads_gently(raw: bytes | str):
    """json.loads for the directory's answers and the saved list, without holding the
    GIL for long. One json.loads of the station list (~3 MB) is a single C call of
    tens of ms, and the audio callbacks can't run until it's over: the sounds, the
    radio and your mic all stuttered. Here a top-level array (or the arrays in a
    top-level object) is decoded one element at a time."""
    s = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    i = _SPACE.match(s).end()
    if s.startswith("[", i):
        value, i = _array(s, i)
    elif s.startswith("{", i):
        value = {}
        i = _SPACE.match(s, i + 1).end()
        if s.startswith("}", i):
            i += 1
        else:
            while True:
                key, i = _DECODER.raw_decode(s, i)
                i = _SPACE.match(s, i).end()
                if not isinstance(key, str) or not s.startswith(":", i):
                    raise ValueError(f"expected a key at {i}")
                i = _SPACE.match(s, i + 1).end()
                if s.startswith("[", i):
                    value[key], i = _array(s, i)
                else:
                    value[key], i = _DECODER.raw_decode(s, i)
                i = _SPACE.match(s, i).end()
                if s.startswith(",", i):
                    i = _SPACE.match(s, i + 1).end()
                elif s.startswith("}", i):
                    i += 1
                    break
                else:
                    raise ValueError(f"expected ',' or '}}' at {i}")
    else:
        value, i = _DECODER.raw_decode(s, i)
    if _SPACE.match(s, i).end() != len(s):
        raise ValueError("extra data after the JSON")
    return value


def _stations(raw: bytes | str) -> list[Station]:
    """parse_stations, but an answer that isn't JSON raises ValueError."""
    data = loads_gently(raw)
    if not isinstance(data, list):
        return []
    seen, out = set(), []
    for d in data:
        s = Station.from_api(d)
        if s is not None and s.uuid not in seen:
            seen.add(s.uuid)
            out.append(s)
    return out


def parse_stations(raw: bytes | str) -> list[Station]:
    try:
        return _stations(raw)
    except ValueError:
        return []


# --------------------------------------------------------------------------- directory

def _refused(url: str) -> str:
    """Radio switched off (or Offline mode): `url` listed as blocked in Network
    activity (netlog), as a connection refused before anything was looked up. The
    message, for the user."""
    q = QUrl(url)
    why = net.off_message(FEATURE)
    netlog.blocked(FEATURE, q.host(), q.port(443 if q.scheme() == "https" else 80), why)
    return why


_kept: list[tuple[threading.Thread, QObject]] = []   # UI thread only (see _start_for)


def _start_for(owner: QObject, target, name: str):
    """Run `target` on a thread that works for `owner`. The thread holds `owner`
    (through `target`), and a QObject must be destroyed on the UI thread: if every
    other reference went while the thread was finishing (a closed tab, under load),
    the thread's was the last one and `owner` was destroyed there, network manager
    and all. So `owner` is also held here until the thread has ended, and let go of
    on the UI thread."""
    t = threading.Thread(target=target, daemon=True, name=name)
    t.start()
    if not _kept:
        QTimer.singleShot(100, _let_go)
    _kept.append((t, owner))


def _let_go():
    _kept[:] = [(t, o) for t, o in _kept if t.is_alive()]
    if _kept:
        QTimer.singleShot(100, _let_go)


_nam: QNetworkAccessManager | None = None


def _the_nam() -> QNetworkAccessManager:
    """The one network manager every RadioDirectory asks through, made on first use and
    kept as long as the app. One per directory was made and freed with every Radio
    tab: switching the tab off and on, making the next one crashed Windows now and
    then (an access violation in QNetworkAccessManager's constructor, issue #339)."""
    global _nam
    if _nam is None:
        from PySide6.QtCore import QCoreApplication
        _nam = QNetworkAccessManager(QCoreApplication.instance())
        net.apply_qt(_nam, FEATURE)   # Settings > Connection and Privacy & security
    return _nam


class RadioDirectory(QObject):
    """Talks to Radio Browser. Every call answers with a signal on the UI thread."""
    globe_ready = Signal(list)          # [Station] with a location, most listened first
    # outline_rings() and outline_labels(): the flat map's land and names ([] offline)
    outlines_ready = Signal(list, list)
    results = Signal(str, list)         # query, [Station]
    failed = Signal(str, str)           # "globe" | "search", message
    _call = Signal(object)              # a function to run on the UI thread (_off_thread)

    def __init__(self, cache_dir=None, bases=API_BASES, parent=None):
        super().__init__(parent)
        self.cache_dir = cache_dir or radio_dir()
        self.bases = list(bases)
        self._search_gen = 0
        self._pending: dict[int, list] = {}
        self._call.connect(self._run_call)

    def _run_call(self, f):
        f()

    def _off_thread(self, work, then, bad):
        """work() on a thread, then then(its result) back on the UI thread, or bad()
        if it raised. Reading and checking the station list takes about half a
        second: on the UI thread it froze the window, and the sounds with it."""
        def run():
            try:
                r = work()
                after = lambda: then(r)   # noqa: E731
            except Exception as e:  # noqa: BLE001 - an answer that isn't station data
                if not isinstance(e, ValueError):
                    log.warning("radio directory: reading the answer failed", exc_info=True)
                after = bad
            # emitted on the UI thread: the Radio tab switched off during an emit from
            # here freed this mid-emit (an access violation, issue #339)
            from soundboard.ui import busy
            busy.emit(self._call, after)
        _start_for(self, run, "radio-directory")

    @property
    def cache_path(self):
        return self.cache_dir / "stations.json"

    # -- plumbing
    def _get(self, path: str, done, fail, attempt: int = 0, parse=loads_gently):
        """GET `path` from a mirror; on a network error or a reply that isn't JSON,
        try the next mirror. done() gets parse(the answer), worked out on a thread
        (parse raises ValueError for a reply that isn't what was asked for)."""
        base = self.bases[attempt % len(self.bases)]
        if not net.allowed(FEATURE):   # switched off: nothing is asked
            why = _refused(base + path)
            QTimer.singleShot(0, lambda: fail(why))
            return None
        req = QNetworkRequest(QUrl(base + path))
        req.setHeader(QNetworkRequest.UserAgentHeader, USER_AGENT)
        req.setTransferTimeout(TIMEOUT_MS)
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                         QNetworkRequest.NoLessSafeRedirectPolicy)
        started = time.monotonic()
        reply = _the_nam().get(req)
        reply.setParent(self)   # this directory going (its tab switched off) aborts it

        def finished():
            reply.deleteLater()
            if reply.error() != QNetworkReply.NoError:
                retry(net.explain(reply.errorString(), started))
                return
            raw = bytes(reply.readAll())
            # a maintenance page or a captive portal, say, raises in parse
            self._off_thread(lambda: parse(raw), done, lambda: retry(
                "the directory sent something that isn't station data"))

        def retry(err):
            if attempt + 1 < len(self.bases):
                log.info("radio directory %s failed (%s); trying another mirror", base, err)
                self._get(path, done, fail, attempt + 1, parse)
            else:
                fail(err)
        reply.finished.connect(finished)
        return reply

    # -- the map's stations ("globe": the name is from the old 3D globe)
    def load_globe(self, force: bool = False):
        self.globe_stale = ""   # set when a refresh failed and the saved list stands in
        # the saved list is read on a thread as well (a full one takes ~0.3 s)
        self._off_thread(self._read_cache, lambda cached: self._load_globe(cached, force),
                         lambda: self._load_globe(None, force))

    def _load_globe(self, cached, force: bool):
        quiet = False   # the saved list is showing: the fresh one just replaces it
        if cached is not None and not force:
            # a saved list from before a lower bitrate cap: trimmed here, not refetched
            self.globe_ready.emit(fits(cached[1]))
            if time.time() - cached[0] < CACHE_S:
                return
            # over a day old: shown straight away all the same (waiting a few seconds
            # on an empty map for the directory was worse), and fetched afresh
            quiet = True
        netlog.cause(FEATURE, "You refreshed the radio station list" if force else
                     "Radio tab: fetching the station list (saved for a day)")
        # Settings > Data & quality: low data mode asks for a third of the list
        limit = quality.GLOBE_LOW if quality.current.low_data else GLOBE_LIMIT
        path = ("/json/stations/search?has_geo_info=true&hidebroken=true"
                f"&order=clickcount&reverse=true&limit={limit}{_kbps_query()}")

        def fresh(raw):   # on a thread
            stations = [s for s in _stations(raw) if s.lat is not None]
            if stations:
                self._write_cache(stations)
            return stations

        def done(stations):
            if not stations:
                fail("the directory sent no stations")
                return
            self.globe_stale = ""
            self.globe_ready.emit(stations)

        def fail(msg):
            log.warning("radio directory unavailable: %s", msg)
            if quiet:   # the old list is up already
                self.globe_stale = msg or "no answer"
            elif cached is not None:   # an old list beats none
                self.globe_stale = msg or "no answer"
                self.globe_ready.emit(fits(cached[1]))
            else:
                self.failed.emit("globe", msg)
        self._get(path, done, fail, parse=fresh)

    def _read_cache(self) -> tuple[float, list[Station]] | None:
        try:
            p = self.cache_path
            raw = loads_gently(p.read_text(encoding="utf-8"))
            stations = [s for s in map(Station.from_saved, raw.get("stations", [])) if s]
            return (float(raw.get("time", 0)), stations) if stations else None
        except (OSError, ValueError, AttributeError, TypeError):
            return None

    def _write_cache(self, stations: list[Station]):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            # the same JSON as one json.dumps, made a station at a time (see loads_gently)
            body = ", ".join(json.dumps(s.to_saved()) for s in stations)
            tmp.write_text(f'{{"time": {json.dumps(time.time())}, "stations": [{body}]}}',
                           encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError:
            log.warning("can't cache the radio station list", exc_info=True)

    # -- the flat map's land
    def load_outlines(self):
        """The country outlines, from the copy that ships with the app. Answers [] when
        it's missing or altered: the map shows just its dots. Read and parsed on a
        thread: on the UI thread a busy disk froze the window for 5 s (1.8.0)."""
        def work():
            try:
                raw = (ASSET_DIR / COUNTRIES).read_bytes()
            except OSError:
                raw = b""
            rings = outline_rings(raw)
            if not rings:
                log.warning("map outlines unavailable: %s missing or altered", COUNTRIES)
            return rings, (outline_labels(raw) if rings else [])
        self._off_thread(work, lambda r: self.outlines_ready.emit(*r),
                         lambda: self.outlines_ready.emit([], []))

    # -- search
    def search(self, text: str):
        """Stations whose name, tags or place (city / region) contain `text`, most
        listened first. A newer search makes an older one's results be dropped."""
        text = search_text(text)
        self._search_gen += 1
        gen = self._search_gen
        if not text:
            return
        netlog.cause(FEATURE, f"You searched radio stations for {netlog.quoted(text)}")
        q = quote(text)
        common = (f"&hidebroken=true&order=clickcount&reverse=true&limit={SEARCH_LIMIT}"
                  + _kbps_query())
        paths = (f"/json/stations/search?name={q}{common}",
                 f"/json/stations/search?tag={q}{common}",
                 f"/json/stations/search?state={q}{common}")
        self._pending[gen] = [len(paths), [], ""]

        def part(stations=(), err=""):
            st = self._pending.get(gen)
            if st is None:
                return
            st[0] -= 1
            st[1].extend(stations)
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
            for s in sorted(fits(st[1]), key=lambda s: -s.clicks):
                if s.uuid not in seen:
                    seen.add(s.uuid)
                    merged.append(s)
            self.results.emit(text, merged)
        for path in paths:
            self._get(path, lambda found: part(found), lambda err: part(err=err),
                      parse=_stations)

    def count_click(self, uuid: str):
        """Tell the directory a station was started (its popularity ranking)."""
        self._get(f"/json/url/{quote(uuid)}", lambda _raw: None,
                  lambda err: log.debug("radio click not counted: %s", err))


def fits(stations: list[Station]) -> list[Station]:
    """The stations within Settings > Data & quality's bitrate cap."""
    return [s for s in stations if quality.radio_fits(s.bitrate)]


def _kbps_query() -> str:
    cap = quality.current.radio_kbps
    return f"&bitrateMax={cap}" if cap else ""


def _patience() -> float:
    """Settings > Data & quality > slow connection: a station gets this many times
    longer to start or come back, and twice the reopens."""
    return 2.5 if quality.current.patient else 1.0


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


_preloaded = False


def _decoder_files() -> list[Path]:
    """Qt's FFmpeg libraries and its media plugin, in the order they need each other."""
    import PySide6
    base = Path(PySide6.__file__).parent
    found = [f for pat in ("avutil-*.dll", "swresample-*.dll", "avcodec-*.dll",
                           "avformat-*.dll", "swscale-*.dll") for f in sorted(base.glob(pat))]
    return found + sorted((base / "plugins" / "multimedia").glob("ffmpeg*.dll"))


def preload_decoder():
    """Load Qt's FFmpeg libraries on a thread, once. Qt loads them when the first
    player is made, on the UI thread and holding Python's lock: 10-60 ms (the files
    are big), long enough to hold up the audio threads, so a sound playing skipped as
    the first station started. Loaded here, that player is made in ~4 ms."""
    global _preloaded
    if _preloaded or sys.platform != "win32":
        return
    _preloaded = True

    def load():
        import ctypes
        try:
            for f in _decoder_files():
                ctypes.WinDLL(str(f))   # (ctypes lets go of the lock while it loads)
        except OSError as e:   # Qt finds them itself later, as before
            log.debug("radio: preloading the decoder failed: %s", e)
    threading.Thread(target=load, daemon=True, name="radio-preload").start()


class RadioPlayer(QObject):
    """Plays one stream at a time into `audio` (48 kHz stereo float32 chunks).
    `audio` is emitted on Qt's decoding thread, so a busy window can't hold the sound
    up: connect it with Qt.DirectConnection to something thread-safe (the engine's
    feed, the recorder), or Qt queues it to the window like any other signal."""
    audio = Signal(object)
    state = Signal(str)          # connecting | playing | stopped | error
    error = Signal(str)
    now_playing = Signal(str)    # the stream's own title (song / show), when it sends one
    _looked_up = Signal(int, bool)   # (play generation, the host is local): lookup thread
    _first_audio = Signal(int)       # play generation: decoding thread -> UI thread

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
        self._first_sent = -1        # the generation _first_audio was last sent for
        self._state = "stopped"
        self._opened = self._last_audio = 0.0
        # FFmpeg can sit on a station that never answers (or stops sending) for
        # minutes, so the player keeps its own watch
        self._watch = QTimer(self)
        self._watch.setInterval(1000)
        self._watch.timeout.connect(self._check)
        self._looked_up.connect(self._on_looked_up)
        self._first_audio.connect(self._on_first_audio)
        self._conn = 0               # net.generation() when the stream was opened
        # held by _on_buffer (decoding thread) while it runs; shutdown() takes it to know
        # none is running before the player can be freed
        self._buffer_lock = threading.Lock()
        self._closed = False
        net.on_change(self._on_connection)

    def _make(self):
        fmt = QAudioFormat()
        fmt.setSampleRate(SR)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Float)
        self._player = QMediaPlayer(self)
        self._out = QAudioBufferOutput(fmt, self)
        # no QAudioOutput: Qt decodes (at real-time pace) but never plays it itself
        self._player.setAudioBufferOutput(self._out)
        # straight on the decoding thread: queued to the window, the chunks waited out
        # every busy moment there and the radio ran dry (it skipped)
        self._out.audioBufferReceived.connect(self._on_buffer, Qt.DirectConnection)
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
        netlog.cause(FEATURE, f"Playing the radio station {netlog.quoted(station.name)}")
        if not net.allowed(FEATURE):   # switched off: no lookup, no stream
            why = _refused(station.url)
            self.stop()
            self._set_state("error")
            self.error.emit(why)
            return
        if self._player is None:
            self._make()
        self.station = station
        self._retries = 0
        self._reconnecting = self._reopen_pending = False
        self._gen += 1
        self._conn = net.generation()
        host = QUrl(station.url).host()
        if net.active():
            # a lookup here would tell this PC's DNS server which station it is; the
            # proxy resolves the name, and the relay refuses local addresses itself
            self._open()
            return
        try:
            ipaddress.ip_address(host)   # an address was already checked (_http)
        except ValueError:   # a name: where it leads is looked up first, off the UI thread
            self._set_state("connecting")
            gen = self._gen
            from soundboard.ui import busy   # (emitted on the UI thread, as above)
            _start_for(self, lambda: busy.emit(self._looked_up, gen, _name_is_local(host)),
                       "radio-lookup")
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
        self._first_sent = -1   # a reopen keeps the generation: say so again
        self._opened = time.monotonic()
        self._watch.start()
        self._set_state("connecting")
        self._player.stop()
        self._player.setSource(QUrl())   # the same URL again is ignored: really reopen it
        self._player.setSource(QUrl(self.station.url))
        self._player.play()

    def _on_connection(self):
        """The Connection setting changed: a playing station reconnects the new way at
        once (FFmpeg reads the relay's address each time it opens a stream). Radio
        switched off stops it."""
        if self.station is None or self._player is None:
            return
        if not net.allowed(FEATURE):
            log.info("radio: stopped, it was switched off")
            self.stop()
            self._set_state("error")
            self.error.emit(net.off_message(FEATURE) if net.offline() else
                            "Radio was switched off in Settings > Privacy & security.")
            return
        if net.generation() != self._conn:   # the connection itself changed, not a switch
            self._conn = net.generation()
            log.info("radio: reconnecting after a connection setting change")
            self._gen += 1            # a reopen already scheduled does nothing
            self._retries = 0
            # the old stream's own error / end arrives after this: as a reconnect it
            # only schedules another try instead of giving up
            self._reconnecting, self._reopen_pending = True, False
            self._open()

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
        """On Qt's decoding thread. The player's own state changes on the UI thread
        (_on_first_audio)."""
        with self._buffer_lock:
            if not self._closed:
                self._take_buffer(buf)

    def _take_buffer(self, buf):
        if self.station is None:
            return
        gen = self._gen
        x = buffer_to_array(buf)
        if not len(x):
            return
        if buf.format().sampleRate() != SR:   # Qt was asked for SR; this shouldn't happen
            return
        self._last_audio = time.monotonic()
        if not self._got_audio and self._first_sent != gen:
            self._first_sent = gen   # once: every buffer until the UI thread got it sent it
            self._first_audio.emit(gen)
        self.audio.emit(x)

    def _on_first_audio(self, gen: int):
        if gen != self._gen or self.station is None or self._got_audio:
            return
        self._last_audio = time.monotonic()
        self._got_audio = True
        self._retries = 0
        self._reconnecting = False
        self._set_state("playing")

    def _check(self):
        if self.station is None:
            self._watch.stop()
            return
        if self._reopen_pending:
            return
        now = time.monotonic()
        over_tor = net.mode() == net.TOR
        if not self._got_audio and over_tor and not _tor_ready():
            self._opened = now   # Tor is still connecting: the station's time starts after
        elif not self._got_audio and now - self._opened > (
                TOR_CONNECT_S if over_tor else CONNECT_S) * _patience():
            self._retry("the station didn't answer")
        elif self._got_audio and now - self._last_audio > STALL_S * _patience():
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
        over_tor = net.mode() == net.TOR
        if (self._got_audio or self._reconnecting) and self._retries < (
                TOR_RETRIES if over_tor else RETRIES) * (2 if quality.current.patient else 1):
            self._retries += 1
            self._reconnecting = self._reopen_pending = True
            delay = (1000 if over_tor else 500) * self._retries + random.randint(0, 300)
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
        self.error.emit(net.explain(msg, self._opened))

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
        """Stop for good, before the player is freed (its tab going, the app closing):
        Qt's decoding thread is cut off and any buffer it's still handing over is
        waited out, so it never calls into a freed player (a crash)."""
        if self._closed:
            return
        self.stop()
        if self._out is not None:
            try:
                self._out.audioBufferReceived.disconnect(self._on_buffer)
            except (RuntimeError, TypeError):   # never connected / already gone
                pass
        with self._buffer_lock:
            self._closed = True


def _tor_ready() -> bool:
    from soundboard import tor
    return tor.manager().state == tor.READY


# --------------------------------------------------------------------------- the map

def globe_points(stations: list[Station]) -> list[dict]:
    """What the map needs per station (short keys; the name is from the old globe).
    The dicts are each station's own, made once: read them, don't change them."""
    return [s.map_point for s in stations if s.lat is not None and s.lon is not None]


TOWNS_MAX = 600            # city and town names the maps get (each shows only zoomed in)
TOWN_SPREAD = 3.0          # a place's stations this far (degrees) from its middle are strays


def _median(values) -> float:
    """statistics.median, without its overhead: town_labels takes thousands of them."""
    v = sorted(values)
    i = len(v) // 2
    return v[i] if len(v) % 2 else (v[i - 1] + v[i]) / 2


def town_labels(points: list[dict], limit: int = TOWNS_MAX) -> list[dict]:
    """Cities, towns and regions to name on the maps when zoomed in, from the stations'
    own place field ("s"): {"n": name, "la", "lo": where its stations are (median),
    "k": how many}, the places with the most stations first. Only places that have
    stations are named, so a name always has dots to click around it."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for d in points:
        name = " ".join(str(d.get("s") or "").split())
        if not 2 <= len(name) <= 40 or not any(ch.isalpha() for ch in name):
            continue
        country = str(d.get("c") or "").strip().casefold()
        if name.casefold() in (country, str(d.get("cc") or "").casefold()):
            continue   # "France, France": the map already names the country
        groups.setdefault((name.casefold(), str(d.get("cc") or "")), []).append(d)
    out = []
    for members in groups.values():
        # a place on the 180° line (Fiji, Chukotka) has stations at 179.9 and -179.9:
        # take its middle with the west side moved round, so they're neighbours
        lons = [d["lo"] for d in members]
        wrap = max(lons) - min(lons) > 180
        lon = (lambda d: d["lo"] + 360 if d["lo"] < 0 else d["lo"]) if wrap else \
            (lambda d: d["lo"])
        la = _median(d["la"] for d in members)
        lo = _median(lon(d) for d in members)
        near = [d for d in members
                if abs(d["la"] - la) <= TOWN_SPREAD and abs(lon(d) - lo) <= TOWN_SPREAD]
        if len(near) < max(1, len(members) / 2):
            continue   # scattered all over: the name doesn't belong to one spot
        spellings: dict[str, int] = {}
        for d in near:
            n = " ".join(str(d["s"]).split())
            spellings[n] = spellings.get(n, 0) + 1
        # the most used spelling; on a tie, a capitalised one ("Accra" over "accra")
        name = max(spellings, key=lambda n: (spellings[n], n[:1].isupper(), n))
        mid = _median(lon(d) for d in near)
        out.append({"n": name, "la": round(_median(d["la"] for d in near), 4),
                    "lo": round(mid - 360 if mid > 180 else mid, 4), "k": len(near)})
    out.sort(key=lambda t: (-t["k"], t["n"]))
    return out[:limit]
