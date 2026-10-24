"""Part of the Radio tab (ui/radio/radiopanel.py `RadioTab`): searching for stations, as you type
and when you stop, the matches already known, and the phone remote's station lists."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from soundboard.i18n import _
from soundboard.online import radio
from soundboard.online.radio import RadioDirectory, Station
from soundboard.ui.radio.radiobits import SEARCH_DELAY_MS

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class RadioSearch(_Base):
    if TYPE_CHECKING:   # what RadioTab has that these use
        _flash_until: Any
        _globe_error: Any
        _globe_list: Any
        _phone_found: Any
        _phone_query: Any
        _query: Any
        _refresh_info: Any
        _remember: Any
        _results: Any
        _search_failed: Any
        _search_timer: Any
        _stations: Any
        _type_timer: Any
        dir: Any
        favorites: Any
        listctl: Any
        phone_dir: Any
        recent: Any
        start: Any

    def _on_text(self, text: str):
        self._query = " ".join(text.split())
        if not self._query:
            self._search_timer.stop()
            self.dir.search("")    # drops any search still on its way
            self._results, self._search_failed = None, False
            self.listctl._show_list()
            self._flash_until = 0.0    # no "Searching…" left over from the cleared words
            self._refresh_info()
            return
        self._results, self._search_failed = None, False
        # soon: matches among the stations already known (not on every keystroke)
        self._type_timer.start()
        self._search_timer.start(SEARCH_DELAY_MS)

    def flush_typing(self):
        """Show the list for what's typed now, not after the typing pause."""
        if self._type_timer.isActive():
            self.listctl._show_list()

    def _search_now(self):
        self._search_timer.stop()
        self.flush_typing()
        if self._query:
            self.start()
            if self._search_failed:   # trying again: back to "Searching…"
                self._results, self._search_failed = None, False
                self.listctl._show_list()
            self.dir.search(self._query)
            self._refresh_info(_("Searching…"))

    def _on_results(self, query: str, stations: list):
        if query != radio.search_text(self._query):   # long queries are cut short
            return
        self._remember(stations)
        self._results = [self._stations[s.uuid] for s in stations]
        self.listctl._show_list()
        self._flash_until = 0.0        # the results are in: "Searching…" is over
        self._refresh_info()

    def _local_matches(self) -> list[Station]:
        words = radio.fold(self._query).split()
        seen, out = set(), []
        for s in self.favorites + self._globe_list:
            if s.uuid not in seen and all(w in s.search_hay for w in words):
                seen.add(s.uuid)
                out.append(s)
        return out

    # ------------------------------------------------------------------ a phone's lists
    def phone_list(self, which: str, query: str = "") -> tuple[list[Station], bool, str]:
        """(stations, still loading, error) for a phone remote (soundboard.control.remote): the
        popular, favourite or recent stations, or a search. A search answers with the
        known stations that match at once and asks the directory too; asking again
        brings the stations found online. It has its own directory, so it never
        touches the search on this tab."""
        if which in ("favorites", "favourites"):
            return list(self.favorites), False, ""
        if which == "recent":
            return list(self.recent), False, ""
        if which != "search":
            self.start()   # the popular list is fetched on first use
            return (list(self._globe_list), not self._globe_list and not self._globe_error,
                    self._globe_error)
        text = radio.search_text(" ".join(query.split()))
        if not text:
            return [], False, ""
        words = radio.fold(text).split()
        seen, local = set(), []
        for s in self.favorites + self.recent + self._globe_list:
            if s.uuid not in seen and all(w in s.search_hay for w in words):
                seen.add(s.uuid)
                local.append(s)
        if self.phone_dir is None:
            self.phone_dir = RadioDirectory(cache_dir=self.dir.cache_dir, bases=self.dir.bases,
                                            parent=self)
            self.phone_dir.results.connect(self._on_phone_results)
            self.phone_dir.failed.connect(
                lambda kind, msg: kind == "search" and self._on_phone_results(
                    self._phone_query, None, msg))
        found = self._phone_found.get(text)
        if found is None:
            if text != self._phone_query:
                self._phone_query = text
                self.phone_dir.search(text)
            return local, True, ""
        stations, err = found
        known = {s.uuid for s in stations}
        return (sorted(stations + [s for s in local if s.uuid not in known],
                       key=lambda s: -s.clicks), False, err)

    def _on_phone_results(self, query: str, stations: list | None, err: str = ""):
        if stations:
            self._remember(stations)
            stations = [self._stations[s.uuid] for s in stations]
        self._phone_found[query] = (stations or [], err)
        while len(self._phone_found) > 8:     # the last few searches only
            self._phone_found.pop(next(iter(self._phone_found)))
        if query == self._phone_query:
            self._phone_query = ""            # the same words again: ask again later
