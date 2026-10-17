"""The Radio tab: internet radio from all over the world, picked on a world map or
by searching, played through the engine so it can go out to others like your
sounds do (Send). The directory and player are in radio.py; the map, painted by
Qt itself, is ui/flatmap.py; the station list and its filters are
ui/radiolist.py (RadioTab.listctl).

Nothing touches the network until the tab is first opened.
"""
from __future__ import annotations

import html
import logging
import random
import time

import numpy as np
from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QSplitter, QVBoxLayout,
                               QWidget)

from soundboard import library, radio, theme, usage
from soundboard.i18n import _, ngettext
from soundboard.engine import SR
from soundboard.library import MAX_SECONDS, trim_silence
from soundboard.radio import RadioDirectory, RadioPlayer, Station
from soundboard.ui import appstate, busy, icons
from soundboard.ui.panel import EmptyList, RoundedFrame, VolumeControl, bar, icon_label, vsep
# the station list and its filters live in radiolist.py; their names stay importable here
from soundboard.ui.radiolist import (GENRE_LABELS, GENRES, LIST_MAX,  # noqa: F401
                                     MAP_CACHE, QUALITIES, ROW_H, SORTS, StationList,
                                     _FilterRow, _StationDelegate, in_genre)
from soundboard.ui.speedpitch import SpeedPitchButton
from soundboard.ui.widgets import paint_now_playing
from soundboard.ui.pixels import snap_to_pixels

log = logging.getLogger(__name__)

SEARCH_DELAY_MS = 450      # typing pause before the directory is asked
TYPE_DELAY_MS = 80         # ...and before the list shows the matches already known
FAV_MAX = 200
RECENT_MAX = 30
PRELOAD_MS = 2000          # after the station list is up: the decoder loads (preload_decoder)


def _steady_text(btn: QPushButton, text: str, *others: str):
    """Show `text` on a button that switches between labels (Play / Stop), kept as wide
    as the widest of them so the buttons beside it don't shift on every click. A
    checkable one is measured on and off too: its on look has a border."""
    btn.ensurePolished()                # measured in its stylesheet's (bold) font
    widest = 0
    was = btn.isChecked()
    blocked = btn.blockSignals(True)
    for on in {was, not was} if btn.isCheckable() else {was}:
        btn.setChecked(on)
        for t in (*others, text):
            btn.setText(t)
            widest = max(widest, btn.sizeHint().width())
    btn.setChecked(was)
    btn.blockSignals(blocked)
    btn.setText(text)
    btn.setMinimumWidth(widest if text else 0)


class NowPlaying(QWidget):
    """The control bar's "what's on": bouncing bars and the station's name (and the
    song, when the station says) while one plays, so it's plain at a glance even with
    the station scrolled out of the list. Click it to find the station in the list."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.name = ""
        self.title = ""
        self.tuning = False
        self.setMinimumWidth(80)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(_("Now playing"))
        self.setAccessibleDescription(_("Nothing playing"))

    def set_station(self, name: str, title: str = "", tuning: bool = False):
        if (name, title, tuning) != (self.name, self.title, self.tuning):
            self.name, self.title, self.tuning = name, title, tuning
            self.setCursor(Qt.CursorShape.PointingHandCursor if name
                           else Qt.CursorShape.ArrowCursor)
            self.setToolTip(_("Show it in the list") if name else "")
            what = (_("Tuning in to {name}", name=name) if tuning else
                    _("Playing {name}: {title}", name=name, title=title) if title else
                    _("Playing {name}", name=name))
            self.setAccessibleDescription(what if name else _("Nothing playing"))
        self.update()   # the bars move on every tick while it plays

    def mouseReleaseEvent(self, e):
        if self.name and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):
        t = theme.T
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        f = QFont(self.font())
        if not self.name:
            p.setPen(QColor(t["muted"]))
            p.setFont(f)
            p.drawText(r.adjusted(10, 0, -4, 0), Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(_("Nothing playing: click a station"),
                                                  Qt.TextElideMode.ElideRight, int(r.width()) - 14))
            p.end()
            return
        bg = QColor(t["accent"])
        bg.setAlpha(40)
        p.setPen(QColor(t["accent"]))
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        paint_now_playing(p, QRectF(r.left() + 12, r.top() + 9, 16, r.height() - 18),
                          QColor(t["accent_hi"]), paused=self.tuning)
        x = r.left() + 36
        room = int(r.right() - 12 - x)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(t["text_hi"]))
        head = _("Tuning in to {name}…", name=self.name) if self.tuning else self.name
        head = p.fontMetrics().elidedText(head, Qt.TextElideMode.ElideRight, room)
        p.drawText(QRectF(x, r.top(), room, r.height()), Qt.AlignmentFlag.AlignLeft
                   | Qt.AlignmentFlag.AlignVCenter, head)
        used = p.fontMetrics().horizontalAdvance(head)
        if self.title and not self.tuning and used + 40 < room:
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(t["muted"]))
            rest = p.fontMetrics().elidedText(f"— {self.title}", Qt.TextElideMode.ElideRight,
                                              room - used - 8)
            p.drawText(QRectF(x + used + 8, r.top(), room - used - 8, r.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, rest)
        p.end()


class RadioTab(QWidget):
    clip_ready = Signal(object, str)   # audio, suggested name (like AppsTab's)
    active_changed = Signal(bool)      # a station started / stopped (for the tab's live dot)
    # made by the station list (radiolist.StationList._make_station_panel)
    station_panel: RoundedFrame
    seg_box: QWidget
    btn_popular: QPushButton
    btn_favs: QPushButton
    btn_recent: QPushButton
    _mode: QButtonGroup
    genre_box: QWidget
    _genres: QButtonGroup
    _genre_btns: dict[str, QPushButton]
    filter_box: QWidget
    cmb_country: QComboBox
    cmb_quality: QComboBox
    cmb_sort: QComboBox
    filter_row: _FilterRow
    count_label: QLabel
    btn_clear: QPushButton
    list: EmptyList

    def __init__(self, engine, cfg, save_cb, meter_cls, directory: RadioDirectory | None = None,
                 globe: bool = True):
        super().__init__()
        self.engine, self.cfg, self._save = engine, cfg, save_cb
        self.listctl = StationList(self)   # the station list and its filters
        if not isinstance(cfg.radio, dict):
            cfg.radio = {}
        self.dir = directory or RadioDirectory(parent=self)
        self.dir.setParent(self)
        self.dir.globe_ready.connect(self._on_globe_stations)
        self.dir.results.connect(self._on_results)
        self.dir.failed.connect(self._on_failed)
        self.player = RadioPlayer(self)
        # on the decoding thread: a busy window mustn't hold the radio up
        self.player.audio.connect(self._on_audio, Qt.ConnectionType.DirectConnection)
        self.player.state.connect(self._on_state)
        self.player.error.connect(self._on_error)
        self.player.now_playing.connect(self._on_now_playing)
        from soundboard.recorder import Recorder
        self.recorder = Recorder(library.APP_DIR / "radio-recording.tmp.wav", seconds=0)

        self._want_globe = globe   # a map at all (tests run without one)
        self.flat = None           # the map, made on first show
        # The 3D globe (an "HD" button on the map until 1.9.7) is gone: whoever had it
        # on gets the map. "flat" is a value every older version reads.
        if cfg.radio.get("map") not in (None, "flat"):
            cfg.radio["map"] = "flat"
            save_cb()
        self._outlines_hooked = False
        self._started = False
        self._stations: dict[str, Station] = {}
        self._globe_list: list[Station] = []
        self._results: list[Station] | None = None
        self._query = ""
        self._search_failed = False  # the last directory search didn't get through
        self._globe_error = ""       # the station list couldn't be fetched (and none cached)
        self._title = ""           # what the station says is playing
        self._active = False       # is_active() as last reported
        self._flash_until = 0.0
        self._reloading = False   # ↻ was pressed: say how the refresh went
        self.clip_error = ""      # set by whoever saves a clip_ready clip, when it can't
        self._fed_by: Station | None = None   # the station the clip buffers hold
        self.favorites: list[Station] = [s for s in map(Station.from_saved,
                                                        cfg.radio.get("favorites", [])) if s]
        self.recent: list[Station] = [s for s in map(Station.from_saved,
                                                     cfg.radio.get("recent", [])) if s]
        for s in self.recent + self.favorites:
            self._stations[s.uuid] = s
        self._fav_ids = {s.uuid for s in self.favorites}
        self.phone_dir: RadioDirectory | None = None   # a phone remote's searches
        self._phone_query = ""                         # ...the one on its way
        self._phone_found: dict[str, tuple[list[Station], str]] = {}   # ...and the answers
        self._genre = ""           # "" = all genres
        self._country = ""         # "" = all countries
        self._globe_shown: list[str] = []   # uuids last pinned on the map
        self._rows_playing: str | None = None   # the station the list's rows say plays
        # shown ids: [points, towns]
        self._map_cache: dict[tuple, list] = {}
        # (genre, min kbps): the popular stations they let through, worked out once per
        # filter change for both the list and the map (and kept for going back to one)
        self._popular_cache: dict[tuple, list[Station]] = {}
        self._popular_of: list[Station] | None = None   # ...of this list
        self._countries_shown: tuple | None = None   # what the country menu was filled with
        self._type_timer = QTimer(self)   # the list follows typing after a short pause
        self._type_timer.setSingleShot(True)
        self._type_timer.setInterval(TYPE_DELAY_MS)
        self._type_timer.timeout.connect(self.listctl._show_list)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)

        # ---- search row
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit()
        icons.clear_button(self.search)
        self.search.textChanged.connect(self._on_text)
        self.search.returnPressed.connect(self._search_now)
        top.addWidget(self.search, 1)
        self.btn_refresh = QPushButton()
        self.btn_refresh.setAccessibleName(_("Fetch the station list again"))
        icons.set_icon(self.btn_refresh, "reload")
        self.btn_refresh.clicked.connect(self._reload)
        top.addWidget(self.btn_refresh)
        v.addLayout(top)

        # ---- globe | station list
        self.split = QSplitter(Qt.Orientation.Horizontal)
        # Both ancestors must reveal the window through the map's corner cutouts.
        self.split.setStyleSheet("QSplitter { background:transparent; }")
        self.split.setChildrenCollapsible(False)
        # A plain QWidget inherits the window background. QFrame paints a solid
        # rectangle behind the map's transparent corner cutouts, leaving square
        # corners even though the map itself is rounded. No mask here: the map
        # antialiases its own corners.
        self.globe_box = QWidget()
        self.globe_box.setMinimumWidth(200)
        self.globe_layout = QVBoxLayout(self.globe_box)
        self.globe_layout.setContentsMargins(0, 0, 0, 0)
        self.split.addWidget(self.globe_box)
        self.split.addWidget(self.listctl._make_station_panel())
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        if not globe:
            self.globe_box.hide()
        self._search_hint()
        v.addWidget(self.split, 1)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setObjectName("muted")
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.info.linkActivated.connect(lambda _link: self._on_live(True))   # Send to others
        v.addWidget(self.info)

        # Who hears the radio: asked once, on the first station, then remembered
        # (cfg.radio["send"]). The Send button changes it any time after.
        self.ask_bar = QFrame()
        self.ask_bar.setObjectName("tipbar")
        ah = QHBoxLayout(self.ask_bar)
        ah.setContentsMargins(12, 6, 6, 6)
        ah.setSpacing(8)
        ask = QLabel(_("Who should hear the radio?"))
        ask.setWordWrap(True)
        ah.addWidget(ask, 1)
        self.btn_ask_all = QPushButton(_("Me and others"))
        self.btn_ask_all.setObjectName("primary")
        self.btn_ask_all.clicked.connect(lambda: self._on_live(True))
        ah.addWidget(self.btn_ask_all)
        self.btn_ask_me = QPushButton(_("Just me"))
        self.btn_ask_me.setObjectName("small")
        self.btn_ask_me.clicked.connect(lambda: self._on_live(False))
        ah.addWidget(self.btn_ask_me)
        self.ask_bar.hide()
        v.addWidget(self.ask_bar)

        # ---- control bar: play, random, star | live ... record | volume | hear
        bar_, bh = bar()
        self.btn_play = QPushButton(_("Play"))
        icons.set_icon(self.btn_play, "play")
        self.btn_play.clicked.connect(self.toggle_play)
        bh.addWidget(self.btn_play)
        self.btn_random = QPushButton()
        self.btn_random.setObjectName("iconbutton")
        self.btn_random.setAccessibleName(_("Play a random station"))
        icons.set_icon(self.btn_random, "shuffle")
        self.btn_random.setToolTip(_("Play a random station"))
        self.btn_random.clicked.connect(self.play_random)
        bh.addWidget(self.btn_random)
        self.btn_fav = QPushButton()
        self.btn_fav.setObjectName("iconbutton")
        self.btn_fav.setAccessibleName(_("Favorite station"))
        icons.set_icon(self.btn_fav, "star")
        self.btn_fav.clicked.connect(lambda: self._toggle_fav())
        bh.addWidget(self.btn_fav)
        bh.addWidget(vsep())
        self.btn_live = QPushButton()   # Send, like a program's on the Apps tab
        self.btn_live.setObjectName("live")
        self.btn_live.setCheckable(True)
        icons.set_icon(self.btn_live, "live", checked_color="on_live")
        self.btn_live.toggled.connect(self._on_live)
        bh.addWidget(self.btn_live)
        self.now = NowPlaying()
        self.now.clicked.connect(self._show_playing)
        bh.addWidget(self.now, 1)
        bh.addStretch(0)   # what Now playing leaves when it's hidden: not into the buttons
        self.btn_rec = QPushButton(_("Record"))
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip(_("Record the radio. Click again to stop and the clip is "
                                  "added to your Sounds."))
        icons.set_icon(self.btn_rec, "record", "danger_text", "#ffffff", size=14)
        self.btn_rec.toggled.connect(self._on_rec)
        bh.addWidget(self.btn_rec)
        # Live controls: the radio's pitch and effects (no speed: it's a live stream)
        self.fx_btn = SpeedPitchButton("radio")
        self.fx_btn.changed.connect(lambda _s, p, _k: setattr(self.engine, "radio_pitch", p))
        self.fx_btn.fx_changed.connect(lambda fx: setattr(self.engine, "radio_fx", fx))
        bh.addWidget(self.fx_btn)
        sep2 = vsep()
        bh.addWidget(sep2)
        tip = _("Radio volume (for them and for you). The dot shows audio activity.")
        vol_icon = icon_label("volume", tip)
        bh.addWidget(vol_icon)
        vol = cfg.radio.get("vol", 1.0)
        self.vol = VolumeControl(float(vol) if isinstance(vol, (int, float)) else 1.0,
                                 tip=tip, meter=True)
        meter = self.vol.meter
        assert meter is not None   # meter=True
        self.meter = meter
        self.vol.changed.connect(self._on_vol)
        bh.addWidget(self.vol)
        self._clip_group = (self.btn_rec,)
        self._vol_group = (sep2, vol_icon, self.vol)
        self._play_short = False
        self.chk_hear = QCheckBox(_("Hear it myself"))
        self.chk_hear.toggled.connect(self._on_hear)
        bh.addWidget(self.chk_hear)
        v.addWidget(bar_)

        # Send as last chosen (asked on the first station played)
        self._on_live(cfg.radio.get("send") is True, remember=False)
        self._on_vol(self.vol.value())
        hear = bool(cfg.radio.get("monitor", True))
        self.chk_hear.setChecked(hear)
        self._on_hear(hear)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._search_now)
        # the stream decoder's DLLs load on a thread once the stations are up (or the
        # directory failed), not alongside them: see _on_globe_stations
        self._preload_timer = QTimer(self)
        self._preload_timer.setSingleShot(True)
        self._preload_timer.setInterval(PRELOAD_MS)
        self._preload_timer.timeout.connect(radio.preload_decoder)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)   # runs while shown, or while recording
        appstate.slow_in_background(self, self.timer, 50)   # behind a game: 4 a second
        self._refresh_info()
        self._update_buttons()

    # ------------------------------------------------------------------ first open
    def showEvent(self, e):
        super().showEvent(e)
        self._update_buttons()   # Play / Send measured in the font they're shown in
        self._label_live()
        self.timer.start(appstate.interval(50))
        self.start()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange) and self.isVisible():
            self._update_buttons()   # a new theme or text size: measure them again
            self._label_live()

    def hideEvent(self, e):
        super().hideEvent(e)
        if not self.recorder.recording:   # a recording still needs its length cap
            self.timer.stop()
            self.engine.level_radio = 0.0

    def start(self):
        """Fetch the stations and build the map (on first open; safe to repeat)."""
        if self._started:
            return
        self._started = True
        if self._want_globe:
            w = max(self.split.width(), 800)
            self.split.setSizes([w * 3 // 5, w * 2 // 5])
            # after the tab has painted
            QTimer.singleShot(0, self, self._make_flat)
        self.dir.load_globe()
        self._refresh_info()

    # ------------------------------------------------------------------ the map
    def _make_flat(self):
        if self.flat is not None:
            return   # start()'s queued call after the map was already made: never two
        from soundboard.ui.flatmap import FlatMap
        self.flat = FlatMap()
        self.flat.clicked.connect(self._on_globe_click)
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
        """(stations, still loading, error) for a phone remote (soundboard.remote): the
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

    def selected(self) -> Station | None:
        it = self.list.currentItem()
        return self._stations.get(it.data(Qt.ItemDataRole.UserRole)) if it is not None else None

    def _on_current(self, it, _prev):
        s = self._stations.get(it.data(Qt.ItemDataRole.UserRole)) if it is not None else None
        if s is not None and s.lat is not None and self.player.station is None:
            # browsing the list turns the map to the station (play one and it stays put)
            p = radio.globe_points([s])[0]
            self._map("fly", p["la"], p["lo"], 1.8, 800)
        self._update_buttons()

    def _on_activated(self, it):
        self.play_uuid(it.data(Qt.ItemDataRole.UserRole))

    def play_uuid(self, uuid: str):
        """Play the station unless it's already the one playing (a click, a
        double-click, Enter): clicking it again doesn't restart it."""
        s = self._stations.get(uuid)
        on = self.player.station
        if s is not None and (on is None or on.uuid != uuid):
            self.play(s)

    def _show_playing(self):
        """The now-playing strip was clicked: the station's row in the list."""
        if self.player.station is not None:
            self.listctl._highlight(self.player.station.uuid)
            self._select_on_globe(fly=True)

    # ------------------------------------------------------------------ playing
    def play_random(self):
        """Any of the popular stations, whatever list, search or filters are showing,
        never the one already playing."""
        now = self.player.station
        pool = [s for s in self._globe_list if now is None or s.uuid != now.uuid]
        if pool:
            self.play(random.choice(pool))
        elif not self._globe_list:
            self._refresh_info(self._no_stations_text())   # the directory isn't in yet

    def play(self, s: Station):
        self._title = ""
        self._fed_by = s
        self.player.play(s)
        usage.used("radio-played")
        if self.cfg.radio.get("count_plays", False):   # Settings > Privacy, off by default
            self.dir.count_click(s.uuid)
        self.cfg.radio["last"] = s.to_saved()
        self.recent = ([s] + [r for r in self.recent if r.uuid != s.uuid])[:RECENT_MAX]
        self.cfg.radio["recent"] = [r.to_saved() for r in self.recent]
        self._save()
        self._select_on_globe(fly=True)
        self.listctl._restate_rows(rebuild=self.btn_recent.isChecked() and not self._query)
        if "send" not in self.cfg.radio:
            self.ask_bar.show()       # once: who should hear it?
        self._refresh_info()
        self._report_active()

    def is_active(self) -> bool:
        """A station is playing (to you, or to everyone with Send on)."""
        return self.player.station is not None

    def live_tip(self) -> str:
        """The "● ON" line for the Radio tab's tooltip while a station plays."""
        return ("● ON: a station is playing, others hear it" if self.engine.radio_live
                else "● ON: a station is playing (only you hear it)")

    def _report_active(self):
        on = self.is_active()
        if on != self._active:
            self._active = on
            self.active_changed.emit(on)

    def _play_or_stop(self, uuid: str):
        on = self.player.station
        if on is not None and on.uuid == uuid:
            self.stop()
        elif uuid in self._stations:
            self.play(self._stations[uuid])

    def stop(self):
        if self.player.station is not None:
            self.player.stop()
            self._select_on_globe(fly=False)
            self.listctl._restate_rows()
        self._report_active()

    def toggle_play(self):
        """The Play / Stop button, and Space on this tab (ui/spacekey.py)."""
        if self.player.station is not None:
            self.stop()
            return
        s = self.selected() or Station.from_saved(self.cfg.radio.get("last") or {})
        if s is not None:
            s = self._stations.setdefault(s.uuid, s)
            self.play(s)

    def _on_audio(self, x: np.ndarray):
        """On the radio's decoding thread: only thread-safe calls here."""
        self.engine.feed_radio(x)
        self.recorder.push(x)

    def _on_state(self, st: str):
        if st == "stopped":        # what the engine still had queued doesn't play out
            self.engine.stop_radio()
        self._flash_until = 0.0    # what's playing matters more than an older notice
        self._refresh_info()
        self._update_buttons()
        self._report_active()      # the player gave the station up by itself

    def _on_error(self, msg: str):
        usage.used("radio-failed")
        self.listctl._restate_rows()
        # the player's own plain words (radio.station_off_air, a switch's reason)
        self._say(msg or radio.station_off_air(), "error")
        self._select_on_globe(fly=False)

    def _on_now_playing(self, title: str):
        st = self.player.station
        if st is not None and title.strip().lower() != st.name.strip().lower():
            self._title = title
            self._refresh_info()
            self._update_now()

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
            if not n:
                text = self._no_stations_text()
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
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r
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

    def _tick(self):
        e = self.engine
        if self.recorder.recording and self.recorder.rec_frames / SR >= MAX_SECONDS:
            self.btn_rec.setChecked(False)
        if not self.isVisible():
            e.level_radio *= 0.8
            return
        self.meter.set_level(e.level_radio)
        e.level_radio *= 0.8
        st = self.player.station
        if st is not None:   # the bouncing bars: the strip and the playing row's badge
            self.now.update()
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == st.uuid:
                    self.list.viewport().update(self.list.visualItemRect(it))
                    break
        if self.recorder.recording:
            secs = self.recorder.rec_frames / SR
            self.btn_rec.setText(_("Stop") + f"  {int(secs // 60)}:{int(secs % 60):02d}")
        elif self._flash_until and time.monotonic() >= self._flash_until:
            self._flash_until = 0.0
            self._refresh_info()

    def retheme(self):
        self.listctl._style_panel()
        self._globe_theme()

    def _globe_theme(self):
        """The map was drawn in the theme of its day: send it today's."""
        self._map("set_theme", *(theme.T[k] for k in ("bg", "accent", "accent2", "text")))

    def shutdown(self):
        self.timer.stop()
        self._search_timer.stop()
        self._type_timer.stop()
        if self.recorder.recording:
            self.recorder.stop()
        self.player.shutdown()


class RadioOff(QWidget):
    """The Radio tab while Radio is switched off in Settings > Privacy & security: a
    short note and a way there. Nothing here goes online (no directory or player
    is made). It answers the main window like RadioTab, with nothing playing."""
    clip_ready = Signal(object, str)
    active_changed = Signal(bool)
    open_settings = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addStretch(1)
        title = QLabel(_("Radio is off"))
        title.setObjectName("section")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(title)
        note = QLabel(_("It's switched off in Settings > Privacy & security, so the radio "
                        "contacts nobody: no station directory, no stations."))
        note.setObjectName("hint")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(note)
        go = QPushButton(_("Privacy && security settings"))
        go.clicked.connect(self.open_settings)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(go)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(2)

    def start(self):
        pass

    def stop(self):
        pass

    def shutdown(self):
        pass

    def retheme(self):
        pass

    def is_active(self) -> bool:
        return False

    def live_tip(self) -> str:
        return ""

    def fit_steps(self):
        return []
