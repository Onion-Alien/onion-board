"""Part of the Radio tab (ui/radio/radiopanel.py `RadioTab`): what it tells you (the line under the
list, the now-playing title, the buttons' words), favourites, the Live switch and its nudge,
the search hint, fitting the tab to a narrow window, and the volume, hearing and recording
controls with their clips."""
from __future__ import annotations

import html
import time
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtWidgets import QWidget

from soundboard.audio.engine import SR
from soundboard.i18n import _, ngettext
from soundboard.sounds.library import trim_silence
from soundboard.ui.kit import appstate, busy, icons, theme
from soundboard.ui.radio.radiobits import FAV_MAX, _steady_text

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class RadioInfo(_Base):
    if TYPE_CHECKING:   # what RadioTab has that these use
        _active: Any
        _clip_group: Any
        _fav_ids: Any
        _fed_by: Any
        _flash_until: Any
        _globe_error: Any
        _globe_list: Any
        _play_short: Any
        _query: Any
        _save: Any
        _started: Any
        _stations: Any
        _title: Any
        _vol_group: Any
        active_changed: Any
        ask_bar: Any
        btn_fav: Any
        btn_favs: Any
        btn_live: Any
        btn_play: Any
        btn_rec: Any
        btn_refresh: Any
        cfg: Any
        chk_hear: Any
        clip_error: Any
        clip_ready: Any
        engine: Any
        favorites: Any
        filter_box: Any
        flat: Any
        fx_btn: Any
        genre_box: Any
        globe_box: Any
        info: Any
        isVisible: Any
        list: Any
        listctl: Any
        now: Any
        player: Any
        recorder: Any
        search: Any
        seg_box: Any
        selected: Any
        timer: Any

    def _update_now(self):
        st = self.player.station
        self.now.set_station(st.name if st else "", self._title if st else "",
                             st is not None and self.player.status == "connecting")

    def _update_buttons(self):
        on = self.player.station is not None
        self._update_now()
        self._nudge_live()
        if not on:
            self.ask_bar.hide()       # stopped unanswered: asked again on the next one
        word = _("Stop") if on else _("Play")
        _steady_text(self.btn_play, "" if self._play_short else word, _("Stop"), _("Play"))
        self.btn_play.setAccessibleName(word)     # still named when it's only an icon
        self.btn_play.setToolTip(word if self._play_short else "")
        icons.set_icon(self.btn_play, "stop" if on else "play")
        self.btn_play.setEnabled(on or self.selected() is not None
                                 or bool(self.cfg.radio.get("last")))
        s = self.selected() or self.player.station
        fav = s is not None and s.uuid in self._fav_ids
        icons.set_icon(self.btn_fav, "star_filled" if fav else "star",
                       "accent" if fav else "text")
        self.btn_fav.setAccessibleName(_("Remove from Favorites") if fav
                                       else _("Add to Favorites"))
        self.btn_fav.setEnabled(s is not None)

    def _no_stations_text(self) -> str:
        if self._globe_error:   # said once: by sad Bun on the map when it's showing
            return "" if self._map_says_it() else (self._globe_error + " "
                                                   + _("Press ↻ to try again."))
        return _("Finding stations…") if self._started else ""

    def _map_says_it(self) -> bool:
        """The map is showing why there are no stations (sad Bun's card)."""
        return (self.flat is not None and bool(self.flat._msg)
                and self.flat.isVisibleTo(self))

    def _say(self, text: str, kind: str):
        """A result or a problem as a corner card; the info line goes back to what's
        playing (only "Refreshing…" / "Searching…" stay on it)."""
        busy.toast(self, html.escape(text), kind)
        self._flash_until = 0.0
        self._refresh_info()

    def _refresh_info(self, msg: str = "", secs: float = 4):
        if msg:
            self._flash_until = time.monotonic() + secs
            self.info.setText(msg)
            return
        if time.monotonic() < self._flash_until:
            return
        st, state = self.player.station, self.player.status
        if st is None:
            n = len(self._globe_list)
            if not n:   # on its way: an empty list says it already, not twice
                text = ("" if not self._globe_error and not self.list.count()
                        else self._no_stations_text())
            elif self.globe_box.isHidden():   # narrow: no map to click
                text = ngettext("{n} popular station: search, or click a station to "
                                "play it.",
                                "{n} popular stations: search, or click a station to "
                                "play it.", n, n=f"{n:,}")
            else:
                text = ngettext("{n} popular station: click a dot on the map, or search. "
                                "Click a station to play it.",
                                "{n} popular stations: click a dot on the map, or search. "
                                "Click a station to play it.", n, n=f"{n:,}")
            if not n and self._globe_error:
                red = theme.status("error")
                text = (f"<span style='color:{red}'>" + html.escape(
                    _("Press ↻ to try again.") if self._map_says_it()
                    else self._no_stations_text()) + "</span>")
        else:
            name = html.escape(st.name)
            where = html.escape(st.country) if st.country else ""
            if state == "connecting":
                text = _("Tuning in to {name}…", name=f"<b>{name}</b>")
            else:
                text = f"▶ <b>{name}</b>" + (f" · {where}" if where else "")
                if self._title:
                    text += f" — <i>{html.escape(self._title)}</i>"
            if self.engine.radio_live:
                text += (f"  <span style='color:{theme.status('ok')}'>· "
                         + _("others hear it") + "</span>")
            else:
                text += "  · " + _("only you hear it")
                if self.ask_bar.isHidden():   # (while it asks, it asks)
                    text += (f"  · <a href='send' style='color:{theme.T['accent_link']};'>"
                             + html.escape(_("Send to others")) + "</a>")
        self.info.setText(text)

    # ------------------------------------------------------------------ favourites
    def _toggle_fav(self, uuid: str | None = None):
        """Star / unstar a station: the one given, else the selected or playing one."""
        s = self._stations.get(uuid) if uuid else self.selected() or self.player.station
        if s is None:
            return
        if s.uuid in self._fav_ids:
            self.favorites = [f for f in self.favorites if f.uuid != s.uuid]
        else:
            self.favorites = ([s] + self.favorites)[:FAV_MAX]
        self._fav_ids = {f.uuid for f in self.favorites}
        self.cfg.radio["favorites"] = [f.to_saved() for f in self.favorites]
        self._save()
        # searching lists favourites first, so their order there changes too
        self.listctl._restate_rows(s.uuid, rebuild=self.btn_favs.isChecked() or bool(self._query))

    # ------------------------------------------------------------------ controls
    def _on_live(self, on: bool, remember: bool = True):
        """Others hear the radio (`on`) or only you do. A choice (the button, the ask bar,
        the hint's link, a phone) is remembered for the next start."""
        if remember:
            self.cfg.radio["send"] = on
            self.ask_bar.hide()
            self._save()
        self.engine.radio_live = on
        self.btn_live.blockSignals(True)
        self.btn_live.setChecked(on)
        self.btn_live.blockSignals(False)
        self._label_live()
        self._refresh_info()
        if self._active:
            self.active_changed.emit(True)   # again: the tab's tip says who hears it

    def _label_live(self):
        on = self.btn_live.isChecked()
        _steady_text(self.btn_live, _("Others hear it") if on else _("Send to others"),
                     _("Others hear it"), _("Send to others"))
        icons.text_gap(self.btn_live)   # (its icon was set before it had words)
        self._nudge_live()
        self.btn_live.setToolTip(_("Others hear the radio. Click so only you do.") if on else
                                 _("Send the radio out to others, the way your sounds go "
                                   "(Setup tab). Off: only you hear it."))

    def _nudge_live(self):
        """A station playing to only you: Send gets the accent edge, so it's found."""
        nudge = self.player.station is not None and not self.btn_live.isChecked()
        if bool(self.btn_live.property("nudge")) != nudge:
            self.btn_live.setProperty("nudge", nudge)
            icons.set_icon(self.btn_live, "live", "accent" if nudge else None,
                           checked_color="on_live")
            self.btn_live.style().unpolish(self.btn_live)
            self.btn_live.style().polish(self.btn_live)

    def _search_hint(self):
        """The search box's hint, pointing at the map only while it's showing."""
        self.search.setPlaceholderText(
            _("Search radio stations, genres, countries or cities…") if self.globe_box.isHidden()
            else _("Search radio stations, genres, countries or "
                   "cities…  (or click a dot on the map)"))

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/window/responsive.py)."""
        from soundboard.ui.window import responsive as r
        def star_only(compact):
            self.btn_favs.setText("" if compact else _("Favorites"))
            self.btn_favs.setToolTip(_("Favorites") if compact else "")
            # again: just the star must drop the gap kept for the words beside it,
            # or it sits off-centre in a wider pill between Popular and Recent
            icons.set_icon(self.btn_favs, "star", "muted")
            r.touch(self.btn_favs)

        hide_map = r.hide(self.globe_box)

        def no_map(compact):
            hide_map(compact)
            self._search_hint()    # the hints stop pointing at a map that isn't there
            self._refresh_info()

        def play_icon(compact):
            self._play_short = compact
            self._update_buttons()
            r.touch(self.btn_play)
        return [(10, "w", star_only),
                (12, "h", r.hide(self.genre_box)),     # short: filters give way first
                (16, "h", r.hide(self.filter_box)),
                (24, "h", r.hide(self.seg_box)),
                (30, "w", r.hide(self.chk_hear)),
                (36, "w", r.icon_only(self.btn_rec)),
                (36, "w", play_icon),
                (40, "w", r.hide(*self._vol_group)),
                (45, "w", r.hide(self.fx_btn)),
                (46, "w", no_map),                      # narrow: just the list
                (50, "w", r.hide(*self._clip_group, self.btn_fav, self.btn_refresh)),
                (54, "w", r.hide(self.now)),
                (20, "h", r.hide(self.info))]

    def _on_vol(self, gain: float):
        self.cfg.radio["vol"] = gain
        self.engine.radio_vol = gain
        self._save()

    def _on_hear(self, on: bool):
        self.cfg.radio["monitor"] = on
        self.engine.radio_monitor = on
        self._save()

    def _on_rec(self, on: bool):
        if on:
            self.recorder.start()
            self.timer.start(appstate.interval(50))   # the length cap is checked on the tick
            return
        if not self.isVisible():
            self.timer.stop()
        self.btn_rec.setText(_("Record"))
        self._emit_clip(self.recorder.stop(),
                        _("Nothing was playing on the radio while you recorded."))

    def _emit_clip(self, data: np.ndarray, empty_msg: str) -> bool:
        data = trim_silence(data)
        if len(data) < int(0.2 * SR):
            self._say(empty_msg, "warn")
            return False
        st = self.player.station or self._fed_by or self.selected()
        name = (st.name[:30] if st else _("Radio")) + " " + time.strftime("%H.%M.%S")
        self.clip_error = ""
        self.clip_ready.emit(data, name)   # the window saves it (and sets clip_error if not)
        if self.clip_error:
            self._say(_("Couldn't save the clip: {error}", error=self.clip_error), "error")
            return False
        self._say(_("Saved a {secs}s clip to your Sounds.", secs=f"{len(data) / SR:.1f}"),
                  "ok")
        return True
