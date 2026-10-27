"""The Radio tab: internet radio from all over the world, picked on a world map or
by searching, played through the engine so it can go out to others like your
sounds do (Send). The directory and player are in radio.py; the map, painted by
Qt itself, is ui/radio/flatmap.py; the station list and its filters are
ui/radio/radiolist.py (RadioTab.listctl).

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

from soundboard.sounds import library
from soundboard.ui.kit import theme
from soundboard.core import achievements, usage
from soundboard.online import radio
from soundboard.i18n import _
from soundboard.audio.engine import SR
from soundboard.sounds.library import MAX_SECONDS
from soundboard.online.radio import RadioDirectory, RadioPlayer, Station
from soundboard.ui.kit import appstate, busy, icons
from soundboard.ui.kit.panel import (CONTROL_H, EmptyList, RoundedFrame, VolumeControl, bar,
                                     icon_label, vsep)
# the station list and its filters live in radiolist.py; their names stay importable here
from soundboard.ui.radio.radiolist import (GENRE_LABELS, GENRES, LIST_MAX,  # noqa: F401
                                           MAP_CACHE, QUALITIES, ROW_H, SORTS, StationList,
                                           _FilterRow, _StationDelegate, in_genre)
from soundboard.ui.sounds.speedpitch import SpeedPitchButton
from soundboard.ui.kit.widgets import paint_now_playing
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.radio.radiobits import (  # noqa: F401
    _steady_text,
    FAV_MAX,
    PRELOAD_MS,
    RECENT_MAX,
    SEARCH_DELAY_MS,
    TYPE_DELAY_MS,
)
from soundboard.ui.radio.radiomap import RadioMap
from soundboard.ui.radio.radiosearch import RadioSearch
from soundboard.ui.radio.radioinfo import RadioInfo

log = logging.getLogger(__name__)


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


class RadioTab(RadioMap, RadioSearch, RadioInfo, QWidget):
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
        from soundboard.audio.recorder import Recorder
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
        # one height for both, as on the Sounds tab: the box alone was shorter, so the
        # row lost 4 px when a narrow window hid the button and the page under it jumped
        for w in (self.search, self.btn_refresh):
            w.setFixedHeight(CONTROL_H)
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
        if not self._globe_list:   # the list itself says it's on its way, not a blank box
            self.listctl._show_list()
        self._refresh_info()


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
        """The Play / Stop button, and Space on this tab (ui/window/spacekey.py)."""
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
        if st == "playing" and self.player.station is not None:   # (Settings > Achievements)
            achievements.station(self.player.station.uuid, self.player.station.country,
                                 self.player.station.cc)
        if st == "stopped":        # what the engine still had queued doesn't play out
            self.engine.stop_radio()
        self._flash_until = 0.0    # what's playing matters more than an older notice
        self._refresh_info()
        self._update_buttons()
        self._report_active()      # the player gave the station up by itself

    def _on_error(self, msg: str):
        usage.used("radio-failed")
        self.listctl._restate_rows()
        # the player's own plain words (radio.station_off_air, a switch's reason), and
        # Try again on the card: the same station once more
        st = self._fed_by
        text = html.escape(msg or radio.station_off_air())
        if st is not None:
            busy.toast(self, text, "error", action=(_("Try again"), lambda: self.play(st)))
        else:
            busy.toast(self, text, "error")
        self._flash_until = 0.0
        self._refresh_info()
        self._select_on_globe(fly=False)

    def _on_now_playing(self, title: str):
        st = self.player.station
        if st is not None and title.strip().lower() != st.name.strip().lower():
            self._title = title
            self._refresh_info()
            self._update_now()


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
