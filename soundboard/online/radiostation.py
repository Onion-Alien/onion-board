"""Radio Browser's stations for soundboard.online.radio: the directory's addresses, a
station (`Station`) and what may be played from it, searching text, reading the
directory's answers gently, and what to say when it can't be reached."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path

from PySide6.QtCore import QUrl

from soundboard.sounds import library
from soundboard.online import net, netlog
from soundboard.i18n import _


# Radio Browser mirrors. `all.` round-robins across them; the rest are fallbacks.
API_BASES = ("https://all.api.radio-browser.info", "https://de1.api.radio-browser.info",
             "https://de2.api.radio-browser.info")
GLOBE_LIMIT = 3000         # stations fetched for the map (the most listened-to)
# With no saved list the most listened-to few come first: the directory takes 5-15 s
# to send all 3000 (~3.8 MB, never compressed), and ~1-2 s for these
GLOBE_FIRST = 300
SEARCH_LIMIT = 150
SEARCH_MAX_CHARS = 80
CACHE_S = 24 * 3600        # how long the map's station list is reused
TIMEOUT_MS = 15000
USER_AGENT = "OnionBoard"   # Radio Browser asks apps to name themselves; no version
FEATURE = "radio"           # its switch in Settings > Privacy & security (soundboard.online.net)
RETRIES = 3                # a dropped stream is reopened this many times in a row
CONNECT_S = 20.0           # a station that sends no audio this long after opening is dead
STALL_S = 8.0              # ...and one that goes quiet this long while playing is reopened
# A reopen only counts as having worked once the station plays this long without
# dropping: one that sends a few seconds and dies each time is given up on, not
# reopened forever while the tab still says it's playing
STEADY_S = 30.0
# Over Tor a stream's circuit can break (a relay in it goes away, or Tor restarts) and a
# new one takes longer to open: more reopens, more time, and no giving up while Tor
# itself is still connecting (its own wait fails the stream if it never does)
TOR_RETRIES = 6
TOR_CONNECT_S = 60.0

# The map's outlines ship with the app: assets/radio in a source checkout, radio/ in the
# frozen app (build.ps1 bundles it). Nothing is fetched from a CDN.
ASSET_DIR = (Path(sys._MEIPASS) / "radio" if hasattr(sys, "_MEIPASS")   # pyright: ignore[reportAttributeAccessIssue]
             else Path(__file__).resolve().parents[2] / "assets" / "radio")
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


def _http(url: object) -> str:
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
    doesn't resolve isn't refused here: the stream just fails to connect, as it would.

    Only an early, readable refusal: FFmpeg looks the name up again when it opens the
    stream, and a name can answer differently the second time (DNS rebinding). That
    lookup isn't FFmpeg's own: the stream goes through the relay (http_proxy), which
    looks the name up once, checks it and connects to the address it checked
    (net._connect_away)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    for info in infos:
        try:
            if _local_ip(ipaddress.ip_address(str(info[4][0]).split("%")[0])):
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
        lat, lon = self.lat, self.lon
        assert lat is not None and lon is not None
        return {"id": self.uuid, "n": self.name, "c": self.country, "cc": self.cc,
                "s": self.state, "l": self.language, "t": self.tags[:6], "co": self.codec,
                "b": self.bitrate, "v": self.votes, "tr": self.trend, "h": self.hls,
                "ck": self.checked, "ch": self.changed, "la": round(lat, 4),
                "lo": round(lon, 4), "k": self.clicks}


def fold(text: str) -> str:
    """Text to search in, or for: lower case without accents, so "zurich" finds
    "Zürich" and "istanbul" finds "İstanbul"."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(ch))


def search_text(text: str) -> str:
    """What a search for `text` actually asks for (and hands back with its results)."""
    return " ".join(text.split())[:SEARCH_MAX_CHARS]


_DECODER = json.JSONDecoder()
_SPACE = re.compile(r"[ \t\n\r]*")


def _skip(s: str, i: int) -> int:
    """The index after the whitespace at s[i] (i when there's none)."""
    return _SPACE.match(s, i).end()   # pyright: ignore[reportOptionalMemberAccess]  # * always matches


def _array(s: str, i: int) -> tuple[list, int]:
    """The JSON array at s[i] (its "["), decoded one element at a time; returns it and
    the index just after its "]"."""
    out = []
    i = _skip(s, i + 1)
    if s.startswith("]", i):
        return out, i + 1
    while True:
        v, i = _DECODER.raw_decode(s, i)
        out.append(v)
        i = _skip(s, i)
        if s.startswith(",", i):
            i = _skip(s, i + 1)
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
    i = _skip(s, 0)
    if s.startswith("[", i):
        value, i = _array(s, i)
    elif s.startswith("{", i):
        value = {}
        i = _skip(s, i + 1)
        if s.startswith("}", i):
            i += 1
        else:
            while True:
                key, i = _DECODER.raw_decode(s, i)
                i = _skip(s, i)
                if not isinstance(key, str) or not s.startswith(":", i):
                    raise ValueError(f"expected a key at {i}")
                i = _skip(s, i + 1)
                if s.startswith("[", i):
                    value[key], i = _array(s, i)
                else:
                    value[key], i = _DECODER.raw_decode(s, i)
                i = _skip(s, i)
                if s.startswith(",", i):
                    i = _skip(s, i + 1)
                elif s.startswith("}", i):
                    i += 1
                    break
                else:
                    raise ValueError(f"expected ',' or '}}' at {i}")
    else:
        value, i = _DECODER.raw_decode(s, i)
    if _skip(s, i) != len(s):
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

def _server_down(status) -> bool:
    """An HTTP answer saying the directory itself is down or overloaded (not you)."""
    return isinstance(status, int) and (status >= 500 or status == 429)


# What the Radio tab says when something isn't working: plain words, never Qt's or
# FFmpeg's (those name the whole address and are logged instead). Functions: the
# language is picked after this module is imported.
def directory_down() -> str:
    return _("The radio is down right now. It's not you: the station list's server "
             "isn't working. Try again in a little while.")


def directory_unreachable() -> str:
    return _("Can't reach the radio station list. Check your internet, or try again in "
             "a little while.")


def station_off_air() -> str:
    return _("That station isn't on the air right now. Try another one.")


def _refused(url: str) -> str:
    """Radio switched off (or Offline mode): `url` listed as blocked in Network
    activity (netlog), as a connection refused before anything was looked up. The
    message, for the user."""
    q = QUrl(url)
    why = net.off_message(FEATURE)
    netlog.blocked(FEATURE, q.host(), q.port(443 if q.scheme() == "https" else 80), why)
    return why
