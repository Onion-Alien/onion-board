"""Stations whose server turns the listener away, for soundboard.online.radio.

The directory checks its stations from its own servers, so a station can be listed as
working while its server answers "not found" or "forbidden" to everyone else (some
networks only serve their own region). Picking one just failed, and the map kept a
dot for it and for every other station on the same server.

So when a station won't play, its server is asked once more, through the same
connection as the stream (`_the_nam`), and so are the other stations listed on that
server. Each one that answers with a refusal (`refused`) is left off the map, the
Popular list and searches for a day (`DEAD_S`), remembered across restarts in
radio_dir(). Favourites and Recent keep them: those are the user's own lists. A station
that plays again is taken off the list at once (`forget`).
"""
from __future__ import annotations

import json
import logging
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest

from soundboard.online import net
from soundboard.online.radiostation import FEATURE, Station, radio_dir

log = logging.getLogger("soundboard.online.radio")

DEAD_S = 24 * 3600     # how long a refused station stays off the map
SIBLINGS_MAX = 40      # other stations on the same server asked about, at most
AT_ONCE = 4            # servers asked at the same time
ASK_MS = 10000         # an answer this slow says nothing either way
FILE = "dead.json"
# asked as the player's own FFmpeg asks (Qt bundles FFmpeg 7, "Lavf/61"): a server that
# turns unknown programs away must answer this the way it answered the stream
AGENT = "Lavf/61.7.100"

_dead: dict[str, float] = {}   # station id -> when its server refused it
_loaded_from = None            # the radio_dir() _dead was read from


def refused(status: int) -> bool:
    """An HTTP status saying the stream isn't there for this listener: 4xx, except
    "too slow" (408) and "too many requests" (429), which pass."""
    return 400 <= status < 500 and status not in (408, 429)


def _load():
    global _loaded_from
    where = radio_dir()
    if where == _loaded_from:
        return
    _loaded_from = where
    _dead.clear()
    try:
        raw = json.loads((where / FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return
    now = time.time()
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, (int, float)) and 0 <= now - v < DEAD_S:
                _dead[k[:64]] = float(v)


def _save():
    try:
        d = radio_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (FILE + ".tmp")
        tmp.write_text(json.dumps(_dead), "utf-8")
        tmp.replace(d / FILE)
    except OSError as e:
        log.debug("radio: couldn't save the refused stations: %s", e)


def is_dead(uuid: str) -> bool:
    _load()
    at = _dead.get(uuid)
    if at is None:
        return False
    if time.time() - at >= DEAD_S:
        del _dead[uuid]
        return False
    return True


def alive(stations: list[Station]) -> list[Station]:
    """`stations` without the refused ones (the same list when none is)."""
    _load()
    if not _dead:
        return stations
    kept = [s for s in stations if not is_dead(s.uuid)]
    return stations if len(kept) == len(stations) else kept


def mark(uuids) -> None:
    _load()
    now = time.time()
    for u in uuids:
        _dead[u] = now
    _save()


def forget(uuid: str) -> None:
    """It played after all."""
    _load()
    if _dead.pop(uuid, None) is not None:
        _save()


def server(s: Station) -> str:
    return QUrl(s.url).host().lower()


def same_server(failed: Station, stations) -> list[Station]:
    """`failed` and up to SIBLINGS_MAX other stations listed on its server."""
    host, out, seen = server(failed), [failed], {failed.uuid}
    for s in stations:
        if len(out) > SIBLINGS_MAX:
            break
        if s.uuid not in seen and server(s) == host and not is_dead(s.uuid):
            seen.add(s.uuid)
            out.append(s)
    return out


class DeadCheck(QObject):
    """Asks a station that wouldn't play whether its server refuses it (`check`); only
    if it does, asks the other stations on that server too. `found` says which were
    refused, once all have answered."""
    found = Signal(list)   # the refused stations' ids

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: list[Station] = []
        self._busy: dict[QNetworkReply, Station] = {}
        self._refused: list[str] = []
        self._asked: set[str] = set()
        self._then: dict[str, list[Station]] = {}   # a failed station -> its server's others

    def check(self, failed: Station, others: list[Station] | None = None):
        if not net.allowed(FEATURE) or failed.uuid in self._asked:
            return
        self._then[failed.uuid] = [s for s in others or () if s.uuid != failed.uuid]
        self._ask([failed])

    def _ask(self, stations: list[Station]):
        for s in stations:
            if s.uuid not in self._asked:
                self._asked.add(s.uuid)
                self._queue.append(s)
        self._next()

    def _next(self):
        from soundboard.online.radiodir import _the_nam
        while self._queue and len(self._busy) < AT_ONCE:
            s = self._queue.pop(0)
            req = QNetworkRequest(QUrl(s.url))
            req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, AGENT)
            req.setTransferTimeout(ASK_MS)
            reply = _the_nam().get(req)
            self._busy[reply] = s
            # a live stream never finishes: its first bytes are the answer
            reply.readyRead.connect(lambda r=reply: self._answer(r))
            reply.finished.connect(lambda r=reply: self._answer(r))
            QTimer.singleShot(ASK_MS + 1000, reply, lambda r=reply: self._answer(r, gave_up=True))
        if not self._queue and not self._busy:
            self._asked.clear()
            if self._refused:
                got, self._refused = self._refused, []
                log.info("radio: %d station(s) refused by their server, left off the map",
                         len(got))
                self.found.emit(got)

    def _answer(self, reply: QNetworkReply, gave_up: bool = False):
        s = self._busy.get(reply)
        if s is None:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = status if isinstance(status, int) else 0
        if 300 <= status < 400 and not reply.isFinished() and not gave_up:
            return   # a redirect being followed: the next server answers
        del self._busy[reply]
        others = self._then.pop(s.uuid, [])
        if refused(status):
            log.info("radio: %s answered %d", s.url, status)
            self._refused.append(s.uuid)
            self._queue.extend(o for o in others if o.uuid not in self._asked)
            self._asked.update(o.uuid for o in others)
        reply.abort()
        reply.deleteLater()
        self._next()
