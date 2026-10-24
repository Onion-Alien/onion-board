"""The Radio Browser directory client for soundboard.online.radio (`RadioDirectory`):
the map's station list (a day's cache), searches and the click a station start
sends, on threads, plus the bitrate cap and patience from Settings > Data & quality."""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from soundboard.online import quality
from soundboard.online import net, netlog
from soundboard.online.radiostation import (API_BASES, ASSET_DIR, CACHE_S, COUNTRIES, FEATURE,
    GLOBE_FIRST, GLOBE_LIMIT, SEARCH_LIMIT, Station, TIMEOUT_MS, USER_AGENT, _refused,
    _server_down, _stations, directory_down, directory_unreachable, loads_gently, radio_dir,
    search_text)
from soundboard.online.radiomap import outline_labels, outline_rings

log = logging.getLogger("soundboard.online.radio")


# Directory instances can overlap while a Radio tab is replaced. On Windows even
# a reader holding stations.json open can prevent its atomic replacement.
_cache_lock = threading.Lock()

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
        self._searching = ""   # the text of the newest search
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
            from soundboard.ui.kit import busy
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
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        req.setTransferTimeout(TIMEOUT_MS)
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        started = time.monotonic()
        reply = _the_nam().get(req)
        reply.setParent(self)   # this directory going (its tab switched off) aborts it

        def finished():
            # freed later, and freeing it lets go of this function, which holds the
            # directory: when that was the last hold, the directory went mid-way through
            # and freed the reply a second time (Qt aborted). So it's the network
            # manager's to free now, not the directory's.
            reply.setParent(_the_nam())
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                # the relay's own 502 is "couldn't connect", not the directory being down
                ours = reply.hasRawHeader(net.RELAY_HEADER)
                retry(f"{reply.errorString()} (HTTP {status}{', relay' if ours else ''})",
                      net.last_failure(started) or (
                          directory_down() if _server_down(status) and not ours
                          else directory_unreachable()))
                return
            raw = reply.readAll().data()
            # a maintenance page or a captive portal, say, raises in parse
            self._off_thread(lambda: parse(raw), done, lambda: retry(
                "the directory sent something that isn't station data", directory_down()))

        def retry(err, words):
            """`err` for the log (Qt's words, with the address); `words` for people."""
            if attempt + 1 < len(self.bases):
                log.info("radio directory %s failed (%s); trying another mirror", base, err)
                self._get(path, done, fail, attempt + 1, parse)
            else:
                log.warning("radio directory %s failed (%s), the last mirror", base, err)
                fail(words)
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
        got: dict = {"full": False, "first": []}   # first: the first few's ids, once shown

        def path(n):
            return ("/json/stations/search?has_geo_info=true&hidebroken=true"
                    f"&order=clickcount&reverse=true&limit={n}{_kbps_query()}")

        def fresh(raw):   # on a thread
            stations = [s for s in _stations(raw) if s.lat is not None]
            if stations:
                self._write_cache(stations)
            return stations

        def done(stations):
            if not stations:
                fail("the directory sent no stations")
                return
            got["full"] = True
            self.globe_stale = ""
            if got["first"] and [s.uuid for s in stations] == got["first"]:
                return   # the first few were all there is: nothing new to show
            self.globe_ready.emit(stations)

        def fail(msg):
            log.warning("radio directory unavailable: %s", msg)
            if quiet or got["first"]:   # the old list (or the first few) is up already
                self.globe_stale = msg or "no answer"
            elif cached is not None:   # an old list beats none
                self.globe_stale = msg or "no answer"
                self.globe_ready.emit(fits(cached[1]))
            else:
                self.failed.emit("globe", msg)
        self._get(path(limit), done, fail, parse=fresh)
        if force or cached is not None or limit <= GLOBE_FIRST:
            return   # (Refresh: the list showing stays till the full one is in)

        # nothing to show meanwhile (a first start, a reset): the first few, asked for
        # alongside, fill the list and the map in a second or two instead of Bun
        # waiting on the whole list. Never saved: the full list replaces them.
        def first(stations):
            if stations and not got["full"]:
                got["first"] = [s.uuid for s in stations]
                self.globe_ready.emit(stations)
        self._get(path(GLOBE_FIRST), first, lambda _msg: None,
                  parse=lambda raw: [s for s in _stations(raw) if s.lat is not None])

    def _read_cache(self) -> tuple[float, list[Station]] | None:
        try:
            p = self.cache_path
            with _cache_lock:
                text = p.read_text(encoding="utf-8")
            raw = loads_gently(text)
            if not isinstance(raw, dict):
                return None
            stations = [s for s in map(Station.from_saved, raw.get("stations", [])) if s]
            return (float(raw.get("time", 0)), stations) if stations else None
        except (OSError, ValueError, AttributeError, TypeError):
            return None

    def _write_cache(self, stations: list[Station]):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # the same JSON as one json.dumps, made a station at a time (see loads_gently)
            body = ", ".join(json.dumps(s.to_saved()) for s in stations)
            with _cache_lock:
                tmp = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                                     dir=self.cache_dir, prefix="stations-",
                                                     suffix=".tmp") as out:
                        tmp = Path(out.name)
                        out.write(f'{{"time": {json.dumps(time.time())}, "stations": [{body}]}}')
                    # Windows requires the source file to be closed before replacing.
                    tmp.replace(self.cache_path)
                finally:
                    if tmp is not None:
                        tmp.unlink(missing_ok=True)
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
        if text and text == self._searching and self._search_gen in self._pending:
            return   # Enter spammed: the same search is still on its way
        self._searching = text
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
