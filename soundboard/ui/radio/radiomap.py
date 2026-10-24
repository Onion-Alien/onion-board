"""Part of the Radio tab (ui/radio/radiopanel.py `RadioTab`): the map and the station lists
behind it: building the flat map, the dots and town labels it shows, picking a station on it,
the popular and remembered stations, and what happens when the directory can't be reached."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from soundboard.core import usage
from soundboard.i18n import _, ngettext
from soundboard.online import radio
from soundboard.online.radio import Station
from soundboard.ui.kit import busy
from soundboard.ui.radio.radiolist import MAP_CACHE

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class RadioMap(_Base):
    if TYPE_CHECKING:   # what RadioTab has that these use
        _flash_until: Any
        _globe_error: Any
        _globe_list: Any
        _globe_shown: Any
        _map_cache: Any
        _outlines_hooked: Any
        _preload_timer: Any
        _query: Any
        _refresh_info: Any
        _reloading: Any
        _results: Any
        _save: Any
        _say: Any
        _search_failed: Any
        _stations: Any
        btn_refresh: Any
        cfg: Any
        dir: Any
        favorites: list[Station]
        flat: Any
        globe_layout: Any
        listctl: Any
        play: Any
        player: Any
        recent: list[Station]

    # ------------------------------------------------------------------ the map
    def _make_flat(self):
        if self.flat is not None:
            return   # start()'s queued call after the map was already made: never two
        from soundboard.ui.radio.flatmap import FlatMap
        self.flat = FlatMap()
        self.flat.clicked.connect(self._on_globe_click)
        self.flat.retry.connect(self._reload)
        self.globe_layout.addWidget(self.flat)
        if not self._outlines_hooked:
            self._outlines_hooked = True
            self.dir.outlines_ready.connect(self._on_outlines)
        self.dir.load_outlines()
        if self._globe_error:
            self.flat.show_message(self._globe_error)   # sad Bun on the map says why
            self.listctl._show_list()                   # ... so the list needn't
            self._refresh_info()
        self._push_globe(force=True)
        self._select_on_globe(fly=False)

    def _on_outlines(self, rings: list, labels: list):
        if self.flat is not None:
            self.flat.set_land(rings, labels)

    def _map(self, method: str, *args):
        """Tell the map (once it's made): one of FlatMap's methods."""
        if self.flat is not None:
            getattr(self.flat, method)(*args)

    def _push_globe(self, force: bool = False):
        """Pin the popular stations on the map — only those the filters let through — and
        name the cities and towns they're in."""
        shown = self.listctl._popular_filtered()
        ids = [s.uuid for s in shown]
        if force or ids != self._globe_shown:
            self._globe_shown = ids
            # back to a filter shown before: its towns aren't worked out again
            key = tuple(ids)
            got = self._map_cache.pop(key, None)
            if got is None:
                points = radio.globe_points(shown)
                got = [points, radio.town_labels(points)]
            self._map_cache[key] = got
            while len(self._map_cache) > MAP_CACHE:
                self._map_cache.pop(next(iter(self._map_cache)))
            self._map("set_points", got[0])
            self._map("set_towns", got[1])

    def _select_on_globe(self, fly: bool):
        st = self.player.station
        pts = radio.globe_points([st]) if st is not None else []
        self._map("select", pts[0] if pts else None, fly)

    def _on_globe_click(self, uuid: str):
        s = self._stations.get(uuid)
        if s is not None:
            self.play(s)
            self.listctl._highlight(s.uuid)

    # ------------------------------------------------------------------ station lists
    def _remember(self, stations: list[Station]):
        """Fresh directory data wins over what was known, favourites and recents
        included: a station whose stream moved plays again."""
        fresh = {s.uuid: s for s in stations}
        self._stations.update(fresh)
        favs = [fresh.get(f.uuid, f) for f in self.favorites]
        recent = [fresh.get(r.uuid, r) for r in self.recent]
        if favs != self.favorites or recent != self.recent:
            self.favorites, self.recent = favs, recent
            self.cfg.radio["favorites"] = [f.to_saved() for f in favs]
            self.cfg.radio["recent"] = [r.to_saved() for r in recent]
            self._save()

    def _reload(self):
        self._globe_error = ""
        self._map("show_message", "")   # the red card goes: Bun tunes in again
        self._map("set_loading", True)
        self._flash_until = 0.0
        self._reloading = True
        busy.set_busy(self.btn_refresh, True)   # back when the list (or an error) is in
        self.dir.load_globe(force=True)
        if self._globe_list:
            self._refresh_info(_("Refreshing the station list…"))
        if not self._globe_list:
            self.listctl._show_list()
            self._refresh_info()

    def _on_globe_stations(self, stations: list):
        # the stream decoder's DLLs, loaded on a thread before a station is picked (not
        # at every start-up: +22 MB for someone who never opens the radio). Not while
        # the tab first fills: Windows holds up every DLL load while one loads, and the
        # map's first draw waited out the decoder's, a freeze. A while after the last
        # list (the first few, then all of them).
        self._preload_timer.start()
        self._globe_error = ""
        self._globe_list = stations
        self._map_cache.clear()    # new station data: new points and towns
        self._remember(stations)
        self._push_globe(force=True)
        self.listctl._show_list()
        if self._reloading:
            self._reloading = False
            busy.set_busy(self.btn_refresh, False)
            stale = getattr(self.dir, "globe_stale", "")
            if stale:
                self._say(_("Couldn't reach the station directory, showing the saved list."),
                          "warn")
            else:
                self._say(ngettext("Station list updated: {n} station.",
                                   "Station list updated: {n} stations.", len(stations)), "ok")
        else:
            self._refresh_info()

    def _on_failed(self, kind: str, msg: str):
        if kind == "globe":
            self._preload_timer.start()   # (a saved station may still play)
            self._reloading = False
            busy.set_busy(self.btn_refresh, False)
            # plain words from radio (directory_down / _unreachable / a switch's reason);
            # sad Bun says them on the map, and they stay up (list and info line)
            # until a reload gets through
            self._globe_error = msg or radio.directory_unreachable()
            usage.used("radio-list-down")
            self._map("show_message", self._globe_error)
            self._flash_until = 0.0
            self.listctl._show_list()
            self._refresh_info()
        elif self._query:
            self._results, self._search_failed = [], True
            self.listctl._show_list()
            self._say((msg or radio.directory_unreachable()) + " "
                      + _("Press Enter to search again."), "error")
