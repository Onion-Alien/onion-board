"""The Radio tab: internet radio from all over the world, picked on a world map or
by searching, played through the engine so it can go out to others like your
sounds do (LIVE). The directory, player and globe page are in radio.py; the
flat map (the default view) is ui/flatmap.py, the 3D globe its HD option.

Nothing touches the network until the tab is first opened.
"""
from __future__ import annotations

import html
import json
import logging
import random
import time
import zlib
from string import Template

import numpy as np
from PySide6.QtCore import (QEvent, QFile, QIODevice, QObject, QRect, QRectF, QSize,
                            Qt, QTimer, Signal, Slot)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QPainter,
                           QPainterPath)
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSizePolicy, QSplitter, QStyle,
                               QStyledItemDelegate, QStyleOptionComboBox, QVBoxLayout,
                               QWidget)

from soundboard import library, radio, theme
from soundboard.engine import SR
from soundboard.library import MAX_SECONDS, trim_silence
from soundboard.radio import RadioDirectory, RadioPlayer, Station
from soundboard.ui import appstate, busy, icons
from soundboard.ui.panel import Flow as _Flow
from soundboard.ui.panel import VolumeControl, bar, icon_label, vsep

log = logging.getLogger(__name__)

CLIP_S = 15
LIST_MAX = 300             # rows shown at once
SEARCH_DELAY_MS = 450      # typing pause before the directory is asked
TYPE_DELAY_MS = 80         # ...and before the list shows the matches already known
FAV_MAX = 200
RECENT_MAX = 30
ROW_H = 54
MAP_CACHE = 8              # filter combinations whose map points and towns are kept
# what the globe page may load: its own files and inline data, never the network
LOCAL_SCHEMES = ("file", "data", "blob", "about", "qrc")

# genre chips: a station is in a genre when one of its tags contains one of the words
GENRES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Pop", ("pop", "top 40", "top40", "hits", "charts")),
    ("Rock", ("rock", "metal", "alternative", "indie", "punk", "grunge")),
    ("Dance", ("dance", "house", "edm", "club", "techno", "trance", "electro", "dnb",
               "drum and bass")),
    ("Hip-hop", ("hip hop", "hip-hop", "hiphop", "rap", "r&b", "rnb", "urban")),
    ("Jazz & Soul", ("jazz", "blues", "soul", "funk", "swing")),
    ("Classical", ("classical", "orchestra", "opera", "baroque", "symphon")),
    ("Chill", ("chill", "lounge", "ambient", "relax", "easy listening", "downtempo", "lofi",
               "lo-fi")),
    ("Oldies", ("oldies", "60s", "70s", "80s", "90s", "retro", "classic hits")),
    ("Country & Folk", ("country", "folk", "bluegrass", "americana")),
    ("Latin", ("latin", "reggaeton", "salsa", "bachata", "cumbia", "tropical")),
    ("Reggae", ("reggae", "dancehall", "ska", "dub")),
    ("News & Talk", ("news", "talk", "sport", "information", "public radio", "politics")),
)
_GENRE_WORDS = dict(GENRES)

# (label, key) — None keeps the list's own order (most listened / starred / most recent)
SORTS = (("Default order", None),
         ("Most listened", lambda s: -s.clicks),
         ("Trending", lambda s: -s.trend),
         ("Most voted", lambda s: -s.votes),
         ("Name A–Z", lambda s: s.name.lower()),
         ("Best quality", lambda s: -s.bitrate))
QUALITIES = (("Any quality", 0), ("128 kbps +", 128), ("192 kbps +", 192), ("256 kbps +", 256))


def in_genre(s: Station, genre: str) -> bool:
    words = _GENRE_WORDS.get(genre)
    if not words:
        return True
    hay = s.genre_hay
    return any(w in hay for w in words)


def _country(s: Station) -> str:
    return s.country or s.cc


def _qwebchannel_js() -> str:
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.ReadOnly):
        return ""
    try:
        return bytes(f.readAll()).decode("utf-8")
    finally:
        f.close()


class _Bridge(QObject):
    """The globe page's only way back into the app: "this dot was clicked" and
    "back to the flat map" (setHd(false))."""
    clicked = Signal(str)
    hd = Signal(bool)

    @Slot(str)
    def play(self, uuid):
        self.clicked.emit(str(uuid)[:64])

    @Slot(bool)
    def setHd(self, on):
        self.hd.emit(bool(on))


class _StationDelegate(QStyledItemDelegate):
    """Paints a station row: a country badge (play button on hover), the name over its
    country and genres, a bitrate pill and a star. Clicking the badge plays or stops
    the station; clicking the star adds or removes it from Favorites."""

    def __init__(self, tab: RadioTab):
        super().__init__(tab.list)
        self.tab = tab
        self._skip_release = False   # the second release of a double-click on badge/star
        self._fonts: dict[str, tuple] = {}     # list font (QFont.key()): its fonts below
        self._badges: dict[str, QColor] = {}   # a country's badge colour

    def _fonts_for(self, base: QFont) -> tuple:
        """(badge, pill, name, subtitle) fonts and the last three's metrics: made once
        per list font (the playing row's is bold), not for every row painted."""
        key = base.key()
        got = self._fonts.get(key)
        if got is None:
            def font(size: float, bold: bool | None) -> QFont:
                f = QFont(base)
                f.setPointSizeF(size)
                if bold is not None:
                    f.setBold(bold)
                return f
            badge, pill, name, sub = (font(8.5, True), font(7.5, True), font(10, True),
                                      font(8.5, None))
            if len(self._fonts) > 8:
                self._fonts.clear()
            got = self._fonts[key] = (badge, pill, name, sub, QFontMetrics(pill),
                                      QFontMetrics(name), QFontMetrics(sub))
        return got

    def _badge(self, key: str) -> QColor:
        c = self._badges.get(key)
        if c is None:
            if len(self._badges) > 2000:
                self._badges.clear()
            c = self._badges[key] = QColor.fromHsl(zlib.crc32(key.encode("utf-8")) % 360,
                                                   95, 88)
        return c

    def sizeHint(self, opt, idx):
        return QSize(1, ROW_H if idx.data(Qt.UserRole) else 96)   # as wide as the list

    @staticmethod
    def _rects(r: QRect):
        card = r.adjusted(4, 2, -6, -2)
        cy = card.center().y()
        avatar = QRect(card.left() + 8, cy - 18, 36, 36)
        star = QRect(card.right() - 30, cy - 12, 24, 24)
        return card, avatar, star

    def paint(self, p: QPainter, opt, idx):
        t = theme.T
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        uuid = idx.data(Qt.UserRole)
        s = self.tab._stations.get(uuid) if uuid else None
        if s is None:
            p.setPen(QColor(t["muted"]))
            p.drawText(opt.rect.adjusted(20, 8, -20, -8), Qt.AlignCenter | Qt.TextWordWrap,
                       idx.data(Qt.DisplayRole) or "")
            p.restore()
            return
        on = self.tab.player.station
        playing = on is not None and on.uuid == uuid
        fav = uuid in self.tab._fav_ids
        hover = bool(opt.state & QStyle.State_MouseOver)
        sel = bool(opt.state & QStyle.State_Selected)
        card, avatar, star = self._rects(opt.rect)
        cardf = QRectF(card)
        badge_f, pill_f, name_f, sub_f, pill_fm, name_fm, sub_fm = self._fonts_for(opt.font)

        # row background
        accent = QColor(t["accent"])
        if sel:
            bg = QColor(accent)
            bg.setAlpha(56)
            p.setPen(QColor(accent.red(), accent.green(), accent.blue(), 150))
            p.setBrush(bg)
            p.drawRoundedRect(cardf.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        elif playing or hover:
            bg = QColor(accent) if playing else QColor(t["card_hi"])
            if playing:
                bg.setAlpha(30)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(cardf, 9, 9)
        if playing:
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(card.left(), card.top() + 10, 3, card.height() - 20), 1.5, 1.5)

        # country badge / play button
        path = QPainterPath()
        path.addRoundedRect(QRectF(avatar), 10, 10)
        if playing or hover:
            p.fillPath(path, accent)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["on_accent"]))
            c = QRectF(avatar).center()
            if playing:          # a little equalizer
                for i, h in enumerate((10, 16, 7)):
                    p.drawRoundedRect(QRectF(c.x() - 8 + i * 6, c.y() + 8 - h, 4, h), 1, 1)
            else:                # ▶
                tri = QPainterPath()
                tri.moveTo(c.x() - 5, c.y() - 8)
                tri.lineTo(c.x() + 8, c.y())
                tri.lineTo(c.x() - 5, c.y() + 8)
                tri.closeSubpath()
                p.fillPath(tri, QColor(t["on_accent"]))
        else:
            p.fillPath(path, self._badge(s.cc or _country(s) or s.name))
            p.setFont(badge_f)
            p.setPen(QColor("#ffffff"))
            p.drawText(avatar, Qt.AlignCenter, s.cc or (s.name[:1].upper() or "?"))

        # star
        if fav:
            icons.icon("star_filled", "accent").paint(p, star.adjusted(3, 3, -3, -3))
        elif hover or sel:
            icons.icon("star", "muted").paint(p, star.adjusted(3, 3, -3, -3))

        # bitrate pill
        right = star.left() - 6
        pill_txt = f"{s.bitrate}k" if s.bitrate else (s.codec or "")[:5].upper()
        if pill_txt:
            w = pill_fm.horizontalAdvance(pill_txt) + 12
            pill = QRectF(right - w, card.center().y() - 9, w, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["badge"]))
            p.drawRoundedRect(pill, 9, 9)
            p.setFont(pill_f)
            p.setPen(QColor(t["live_text"] if s.bitrate >= 256 else t["badge_text"]))
            p.drawText(pill, Qt.AlignCenter, pill_txt)
            right = int(pill.left()) - 8

        # name over country · genres
        left = avatar.right() + 11
        width = max(10, right - left)
        p.setFont(name_f)
        p.setPen(QColor(t["accent_hi"] if playing else t["text_hi"]))
        name = name_fm.elidedText(s.name, Qt.ElideRight, width)
        p.drawText(QRect(left, card.top() + 7, width, 21), Qt.AlignLeft | Qt.AlignVCenter, name)
        p.setFont(sub_f)
        p.setPen(QColor(t["muted"]))
        sub = " · ".join(b for b in (_country(s), ", ".join(s.tags[:3])) if b)
        sub = sub_fm.elidedText(sub, Qt.ElideRight, width)
        p.drawText(QRect(left, card.top() + 27, width, 18), Qt.AlignLeft | Qt.AlignVCenter, sub)
        p.restore()

    def editorEvent(self, ev, model, opt, idx):
        if (ev.type() in (QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick)
                and ev.button() == Qt.LeftButton and idx.data(Qt.UserRole)):
            uuid = idx.data(Qt.UserRole)
            _card, avatar, star = self._rects(opt.rect)
            pos = ev.position().toPoint()
            on_button = star.adjusted(-4, -4, 4, 4).contains(pos) or avatar.contains(pos)
            if ev.type() == QEvent.MouseButtonDblClick:
                # the first click already played / starred it: swallow the double-click
                # (no "activated" play on top) and the release after it (no undo)
                if on_button:
                    self._skip_release = True
                    return True
                return super().editorEvent(ev, model, opt, idx)
            if self._skip_release:
                self._skip_release = False
                if on_button:
                    return True
            # after this event: both rebuild the list this row belongs to
            if star.adjusted(-4, -4, 4, 4).contains(pos):
                QTimer.singleShot(0, lambda: self.tab._toggle_fav(uuid))
                return True
            if avatar.contains(pos):
                QTimer.singleShot(0, lambda: self.tab._play_or_stop(uuid))
                return True
        return super().editorEvent(ev, model, opt, idx)


class _FilterRow(QWidget):
    """The country / quality / sort boxes: side by side while their words fit, else
    country on a row of its own above the other two, else one box a row. Squeezed
    into one row they read "All coun", "Any qua" in a narrow window."""

    GAP = 6

    def __init__(self, combos: list[QComboBox]):
        super().__init__()
        self.combos = combos
        self.rows = 0
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(self.GAP)
        self._lines = []
        for _ in combos:
            h = QHBoxLayout()
            h.setSpacing(self.GAP)
            v.addLayout(h)
            self._lines.append(h)
        self._arrange(1)
        for c in combos:   # a longer choice picked may need another row
            c.currentIndexChanged.connect(lambda _i: self._arrange(self.rows_for(self.width())))

    @staticmethod
    def needs(c: QComboBox) -> int:
        """The width that shows the box's longest choice in full, arrow included (for
        a long list, like every country, the first choice and the one showing)."""
        fm = c.fontMetrics()
        texts = ([c.itemText(i) for i in range(c.count())] if c.count() <= 10
                 else [c.itemText(0), c.currentText()])
        text = max((fm.horizontalAdvance(t) for t in texts), default=0)
        opt = QStyleOptionComboBox()
        c.initStyleOption(opt)
        full = c.style().sizeFromContents(QStyle.CT_ComboBox, opt, QSize(text, fm.height()), c)
        return max(c.minimumSizeHint().width(), full.width())

    def fits(self, idx: list[int], width: int) -> bool:
        """Whether these boxes side by side in `width` each get their words' room
        (_arrange shares a row out in proportion to what each box needs)."""
        return sum(self.needs(self.combos[i]) for i in idx) + self.GAP * (len(idx) - 1) <= width

    def rows_for(self, width: int) -> int:
        every = list(range(len(self.combos)))
        if self.fits(every, width):
            return 1
        if self.fits(every[1:], width):
            return 2
        return len(every)

    def _arrange(self, rows: int):
        if rows != self.rows:
            self.rows = rows
            for h in self._lines:
                while h.count():
                    h.takeAt(0)
            for i, c in enumerate(self.combos):
                line = 0 if rows == 1 else (min(i, 1) if rows == 2 else i)
                self._lines[line].addWidget(c)
            self.updateGeometry()
        for c in self.combos:   # a box's share of its row: what its words need
            for h in self._lines:
                if h.indexOf(c) >= 0:
                    h.setStretch(h.indexOf(c), self.needs(c))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._arrange(self.rows_for(self.width()))


class RadioTab(QWidget):
    clip_ready = Signal(object, str)   # audio, suggested name (like AppsTab's)
    active_changed = Signal(bool)      # a station started / stopped (for the tab's live dot)

    def __init__(self, engine, cfg, save_cb, meter_cls, directory: RadioDirectory | None = None,
                 globe: bool = True):
        super().__init__()
        self.engine, self.cfg, self._save = engine, cfg, save_cb
        if not isinstance(cfg.radio, dict):
            cfg.radio = {}
        self.dir = directory or RadioDirectory(parent=self)
        self.dir.setParent(self)
        self.dir.globe_ready.connect(self._on_globe_stations)
        self.dir.results.connect(self._on_results)
        self.dir.failed.connect(self._on_failed)
        self.player = RadioPlayer(self)
        # on the decoding thread: a busy window mustn't hold the radio up
        self.player.audio.connect(self._on_audio, Qt.DirectConnection)
        self.player.state.connect(self._on_state)
        self.player.error.connect(self._on_error)
        self.player.now_playing.connect(self._on_now_playing)
        from soundboard.recorder import Recorder
        self.recorder = Recorder(library.APP_DIR / "radio-recording.tmp.wav")

        self._want_globe = globe   # a map at all (tests run without one)
        self.view = None           # the 3D globe (HD), made on first show when chosen
        self.flat = None           # ...or the flat map (the default)
        self._globe_loaded = False
        self._app_state_hooked = False
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
        # shown ids: [points, towns, the globe's JS for them (made when first sent)]
        self._map_cache: dict[tuple, list] = {}
        self._type_timer = QTimer(self)   # the list follows typing after a short pause
        self._type_timer.setSingleShot(True)
        self._type_timer.setInterval(TYPE_DELAY_MS)
        self._type_timer.timeout.connect(self._show_list)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)

        # ---- search row
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search radio stations, genres, countries or cities…  "
                                       "(or click a dot on the map)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_text)
        self.search.returnPressed.connect(self._search_now)
        top.addWidget(self.search, 1)
        self.btn_refresh = QPushButton()
        self.btn_refresh.setToolTip("Fetch the station list again")
        icons.set_icon(self.btn_refresh, "reload")
        self.btn_refresh.clicked.connect(self._reload)
        top.addWidget(self.btn_refresh)
        v.addLayout(top)

        # ---- globe | station list
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.globe_box = QWidget()
        self.globe_box.setMinimumWidth(200)
        self.globe_layout = QVBoxLayout(self.globe_box)
        self.globe_layout.setContentsMargins(0, 0, 0, 0)
        self.split.addWidget(self.globe_box)
        self.split.addWidget(self._make_station_panel())
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        if not globe:
            self.globe_box.hide()
        v.addWidget(self.split, 1)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setObjectName("muted")
        v.addWidget(self.info)

        # ---- control bar: play, random, star | live ... record, last 15 s | volume | hear
        bar_, bh = bar()
        self.btn_play = QPushButton("Play")
        self.btn_play.setToolTip("Play the selected station / stop the radio")
        icons.set_icon(self.btn_play, "play")
        self.btn_play.clicked.connect(self._toggle_play)
        bh.addWidget(self.btn_play)
        self.btn_random = QPushButton()
        self.btn_random.setObjectName("iconbutton")
        self.btn_random.setAccessibleName("Play a random station")
        icons.set_icon(self.btn_random, "shuffle")
        self.btn_random.setToolTip("Play a random station from the list showing (pick a "
                                   "genre or country first to narrow it)")
        self.btn_random.clicked.connect(self.play_random)
        bh.addWidget(self.btn_random)
        self.btn_fav = QPushButton()
        self.btn_fav.setObjectName("iconbutton")
        self.btn_fav.setAccessibleName("Favorite station")
        self.btn_fav.setToolTip("Add the selected station to Favorites")
        icons.set_icon(self.btn_fav, "star")
        self.btn_fav.clicked.connect(lambda: self._toggle_fav())
        bh.addWidget(self.btn_fav)
        bh.addWidget(vsep())
        self.btn_live = QPushButton()
        self.btn_live.setObjectName("live")
        self.btn_live.setCheckable(True)
        icons.set_icon(self.btn_live, "live", checked_color="#ffffff")
        self.btn_live.toggled.connect(self._on_live)
        bh.addWidget(self.btn_live)
        bh.addStretch(1)
        self.btn_rec = QPushButton("Record")
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip("Record the radio. Click again to stop — the clip is added "
                                "to your Sounds.")
        icons.set_icon(self.btn_rec, "record", "#ff4d4f", "#ffffff", size=14)
        self.btn_rec.toggled.connect(self._on_rec)
        bh.addWidget(self.btn_rec)
        self.btn_last = QPushButton(f"Last {CLIP_S}s")
        self.btn_last.setToolTip(f"Save the last {CLIP_S} seconds of the radio as a sound")
        icons.set_icon(self.btn_last, "history")
        self.btn_last.clicked.connect(self.clip_last)
        bh.addWidget(self.btn_last)
        sep2 = vsep()
        bh.addWidget(sep2)
        tip = "Radio volume (for them and for you). The dot shows audio activity."
        vol_icon = icon_label("volume", tip)
        bh.addWidget(vol_icon)
        vol = cfg.radio.get("vol", 1.0)
        self.vol = VolumeControl(float(vol) if isinstance(vol, (int, float)) else 1.0,
                                 tip=tip, meter=True)
        self.meter = self.vol.meter
        self.vol.changed.connect(self._on_vol)
        bh.addWidget(self.vol)
        self._clip_group = (self.btn_rec, self.btn_last)
        self._vol_group = (sep2, vol_icon, self.vol)
        self._play_short = False
        self.chk_hear = QCheckBox("Hear it myself")
        self.chk_hear.setToolTip("Also play the radio into your headphones")
        self.chk_hear.toggled.connect(self._on_hear)
        bh.addWidget(self.chk_hear)
        v.addWidget(bar_)

        # LIVE always starts off
        self._on_live(False)
        self._on_vol(self.vol.value())
        hear = bool(cfg.radio.get("monitor", True))
        self.chk_hear.setChecked(hear)
        self._on_hear(hear)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._search_now)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)   # runs while shown, or while recording
        appstate.slow_in_background(self, self.timer, 50)   # behind a game: 4 a second
        # the window being dragged keeps the globe drawing (a few wakes a second, not one
        # per move event): a move to another screen loses a sleeping globe's picture
        self._wake_timer = QTimer(self)
        self._wake_timer.setSingleShot(True)
        self._wake_timer.setInterval(120)
        self._wake_timer.timeout.connect(self._wake_globe)
        self._watched = None   # the window whose moves we follow
        self._refresh_info()
        self._update_buttons()

    # ------------------------------------------------------------------ station panel
    _PANEL_STYLE = Template("""
QFrame#stations { background:$panel; border-radius:12px; }
QFrame#stations QWidget { background:transparent; }
QFrame#stations QComboBox QAbstractItemView, QFrame#stations QComboBoxPrivateContainer,
QFrame#stations QMenu { background:$card; }
QFrame#stations QListWidget { border:none; outline:0; }
QFrame#stations QPushButton#seg { border:none; border-radius:7px; padding:5px 10px;
    background:transparent; color:$muted; font-weight:600; }
QFrame#stations QPushButton#seg:hover { color:$text_hi; background:$card_hi; }
QFrame#stations QPushButton#seg:checked { background:$accent; color:$on_accent; }
QFrame#stations QWidget#segbox { background:$inset; border-radius:9px; }
QFrame#stations QPushButton#genre { border-radius:12px; padding:3px 10px; font-size:8.5pt;
    background:$btn; border:1px solid $border; color:$text; }
QFrame#stations QPushButton#genre:hover { border-color:$border_hi; }
QFrame#stations QPushButton#genre:checked { background:$accent; border-color:$accent;
    color:$on_accent; }
QFrame#stations QComboBox { background:$card; padding:4px 8px; font-size:9pt; }
QFrame#stations QLabel#count { color:$muted; font-size:8.5pt; }
QFrame#stations QPushButton#clear { border:none; background:transparent; color:$accent_hi;
    font-size:8.5pt; padding:0 2px; }
QFrame#stations QPushButton#clear:hover { text-decoration:underline; }
QFrame#stations QFrame#rule { background:$border; max-height:1px; border:none; }
""")

    def _make_station_panel(self) -> QFrame:
        self.station_panel = panel = QFrame()
        panel.setObjectName("stations")
        panel.setMinimumWidth(220)
        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 8, 6, 4)
        v.setSpacing(8)

        # Popular | Favorites | Recent
        seg = QWidget()
        seg.setObjectName("segbox")
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        self.btn_popular = QPushButton("Popular")
        self.btn_favs = QPushButton("Favorites")
        icons.set_icon(self.btn_favs, "star", "muted")
        self.btn_recent = QPushButton("Recent")
        self._mode = QButtonGroup(self)
        for b in (self.btn_popular, self.btn_favs, self.btn_recent):
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self._mode.addButton(b)
            sh.addWidget(b, 1)
        self.btn_popular.setChecked(True)
        self.btn_popular.setToolTip("The most listened-to stations right now")
        self.btn_favs.setToolTip("Stations you starred")
        self.btn_recent.setToolTip("Stations you played lately")
        self._mode.buttonClicked.connect(lambda _b: self._show_list())
        self.seg_box = seg
        v.addWidget(seg)

        # genre chips
        self.genre_box = QWidget()
        self.genre_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        flow = _Flow(self.genre_box, gap=5)
        self._genres = QButtonGroup(self)
        self._genre_btns: dict[str, QPushButton] = {}
        for g in ("", *(name for name, _ in GENRES)):
            b = QPushButton((g or "All").replace("&", "&&"))
            b.setObjectName("genre")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(not g)
            b.clicked.connect(lambda _c=False, g=g: self.set_genre(g))
            self._genres.addButton(b)
            self._genre_btns[g] = b
            flow.addWidget(b)
        v.addWidget(self.genre_box)

        # country | quality | sort, then "312 of 3,000 stations"  ·  Clear filters
        self.filter_box = QWidget()
        fv = QVBoxLayout(self.filter_box)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(8)
        self.cmb_country = QComboBox()
        self.cmb_country.setToolTip("Only stations from this country")
        self.cmb_country.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_country.setMinimumContentsLength(8)
        self.cmb_country.addItem("All countries", "")
        self.cmb_country.activated.connect(
            lambda _i: self.set_country(self.cmb_country.currentData() or ""))
        self.cmb_quality = QComboBox()
        self.cmb_quality.setToolTip("Only stations streaming at least this bitrate")
        for label, kbps in QUALITIES:
            self.cmb_quality.addItem(label, kbps)
        self.cmb_quality.activated.connect(lambda _i: self._on_filter())
        self.cmb_sort = QComboBox()
        self.cmb_sort.setToolTip("Sort the list")
        for label, _key in SORTS:
            self.cmb_sort.addItem(label)
        self.cmb_sort.activated.connect(lambda _i: self._show_list())
        self.filter_row = _FilterRow([self.cmb_country, self.cmb_quality, self.cmb_sort])
        fv.addWidget(self.filter_row)
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 4, 0)
        self.count_label = QLabel()
        self.count_label.setObjectName("count")
        row.addWidget(self.count_label, 1)
        self.btn_clear = QPushButton("Clear filters")
        self.btn_clear.setObjectName("clear")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self.clear_filters)
        self.btn_clear.hide()
        row.addWidget(self.btn_clear)
        fv.addLayout(row)
        v.addWidget(self.filter_box)
        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        v.addWidget(rule)

        self.list = QListWidget()
        self.list.setMinimumSize(160, 48)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(False)
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setItemDelegate(_StationDelegate(self))
        self.list.itemActivated.connect(self._on_activated)          # double-click / Enter
        self.list.currentItemChanged.connect(self._on_current)
        v.addWidget(self.list, 1)
        self._style_panel()
        return panel

    def _style_panel(self):
        self.station_panel.setStyleSheet(self._PANEL_STYLE.substitute(theme.T))

    # -- filters
    def set_genre(self, genre: str):
        self._genre = genre if genre in _GENRE_WORDS else ""
        self._genre_btns[self._genre].setChecked(True)
        self._on_filter()

    def set_country(self, country: str):
        self._country = country
        self._on_filter()

    def _min_kbps(self) -> int:
        return int(self.cmb_quality.currentData() or 0)

    def filters_on(self) -> bool:
        return bool(self._genre or self._country or self._min_kbps())

    def clear_filters(self):
        self._genre, self._country = "", ""
        self._genre_btns[""].setChecked(True)
        self.cmb_quality.setCurrentIndex(0)
        self._on_filter()

    def _on_filter(self):
        self._show_list()
        self._push_globe()

    def _filtered(self, stations: list[Station], country: bool = True) -> list[Station]:
        kbps = self._min_kbps()
        words = _GENRE_WORDS.get(self._genre)
        place = self._country if country else ""
        if not (words or place or kbps):
            return list(stations)
        return [s for s in stations
                if (not words or any(w in s.genre_hay for w in words))
                and (not place or _country(s) == place)
                and (not kbps or s.bitrate >= kbps)]

    def _source(self) -> list[Station]:
        """The list before filters: search results, favourites, recent or popular."""
        if self._query:
            local = self._local_matches()
            if self._results is None:
                return local
            ids = {s.uuid for s in self._results}
            return sorted(self._results + [s for s in local if s.uuid not in ids],
                          key=lambda s: -s.clicks)
        if self.btn_favs.isChecked():
            return list(self.favorites)
        if self.btn_recent.isChecked():
            return list(self.recent)
        return list(self._globe_list)

    def _fill_countries(self, source: list[Station], filtered: bool = False):
        """The country menu: how many of `source` each country has with the other
        filters on (`filtered`: they already are)."""
        counts: dict[str, int] = {}
        for s in source if filtered else self._filtered(source, country=False):
            c = _country(s)
            if c:
                counts[c] = counts.get(c, 0) + 1
        if self._country and self._country not in counts:
            counts[self._country] = 0          # keep the chosen one listed
        cmb = self.cmb_country
        cmb.blockSignals(True)
        cmb.clear()
        cmb.addItem("All countries", "")
        for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower())):
            cmb.addItem(f"{c}  ({n:,})", c)
        cmb.setCurrentIndex(max(0, cmb.findData(self._country)))
        cmb.blockSignals(False)

    # ------------------------------------------------------------------ first open
    def showEvent(self, e):
        super().showEvent(e)
        self.timer.start(appstate.interval(50))
        self.start()
        self._wake_globe()   # back from another tab: draw the globe under its names

    def hideEvent(self, e):
        super().hideEvent(e)
        if not self.recorder.recording:   # a recording still needs its length cap
            self.timer.stop()
            self.engine.level_radio = 0.0

    def start(self):
        """Fetch the stations and build the globe (on first open; safe to repeat)."""
        if self._started:
            return
        self._started = True
        if self._want_globe:
            w = max(self.split.width(), 800)
            self.split.setSizes([w * 3 // 5, w * 2 // 5])
            # after the tab has painted: starting a web view takes a moment
            QTimer.singleShot(0, self, self._make_map)
        self.dir.load_globe()
        self._refresh_info()

    # ------------------------------------------------------------------ the map
    def _map_mode(self) -> str:
        """"flat" (the default, painted by Qt: no web engine) or "globe" (HD, 3D)."""
        return "globe" if self.cfg.radio.get("map") == "globe" else "flat"

    def _make_map(self):
        if self.view is not None or self.flat is not None:
            return   # start()'s queued call after a map was already made: never two
        if self._map_mode() == "globe":
            self._make_globe()
        else:
            self._make_flat()

    def _set_map(self, mode: str):
        """Swap the flat map and the 3D globe. The one going away is deleted, so the
        globe's web engine isn't kept alive behind a flat map."""
        if mode == self._map_mode() and (self.view or self.flat):
            return
        self.cfg.radio["map"] = mode
        self.cfg.radio.pop("globe_hd", None)   # the old light / HD globe switch
        self._save()
        for w in (self.view, self.flat):
            if w is not None:
                self.globe_layout.removeWidget(w)
                w.hide()
                w.deleteLater()
        self.view = self.flat = None
        self._globe_loaded = False
        self._globe_shown = []
        self._make_map()

    def _make_flat(self):
        from soundboard.ui.flatmap import FlatMap
        self.flat = FlatMap()
        self.flat.clicked.connect(self._on_globe_click)
        self.flat.hd_requested.connect(self._go_hd)
        self.globe_layout.addWidget(self.flat)
        if not self._outlines_hooked:
            self._outlines_hooked = True
            self.dir.outlines_ready.connect(self._on_outlines)
        self.dir.load_outlines()
        if self._globe_error:
            self.flat.show_message(self._no_stations_text())
        self._push_globe(force=True)
        self._select_on_globe(fly=False)

    def _go_hd(self):
        """The 3D globe's web engine takes a few seconds to start the first time: say so
        on the flat map before the window stops answering for it."""
        if self.flat is not None:
            self.flat.show_message("Loading the 3D globe…")
            self.flat.repaint()
        QTimer.singleShot(30, self, lambda: self._set_map("globe"))

    def _on_outlines(self, rings: list, labels: list):
        if self.flat is not None:
            self.flat.set_land(rings, labels)

    _FLAT_CALLS = {"setStations": "set_points", "setTowns": "set_towns", "select": "select",
                   "fly": "fly", "showMessage": "show_message", "setTheme": "set_theme"}

    def _map(self, fn: str, *args):
        """Tell whichever map is showing: the flat map's method, or the globe page's
        function for the same job (args go to the page as JSON)."""
        if self.flat is not None:
            method = self._FLAT_CALLS.get(fn)
            if method:
                getattr(self.flat, method)(*args)
        else:
            self._js(f"{fn}({', '.join(json.dumps(a) for a in args)})")

    def _make_globe(self):
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                             QWebEngineUrlRequestInterceptor)
        from PySide6.QtWebEngineWidgets import QWebEngineView

        class LocalOnly(QWebEngineUrlRequestInterceptor):
            # the page and everything it loads ship with the app: a request for the
            # network (a bug, or a station name that got past the escaping) is refused,
            # so the map can't step around Settings > Connection
            def interceptRequest(self, info):
                if info.requestUrl().scheme().lower() not in LOCAL_SCHEMES:
                    info.block(True)

        class Page(QWebEnginePage):
            def createWindow(self, _type):
                return None

            def acceptNavigationRequest(self, url, _type, is_main_frame):
                # only our own page (setHtml arrives as a data: URL); links go nowhere
                return not is_main_frame or url.scheme() in ("data", "about")

        if getattr(self, "profile", None) is None:
            store = radio.radio_dir() / "web"
            self.profile = QWebEngineProfile("soundboard-radio", self)   # caches the script
            self.profile.setPersistentStoragePath(str(store))
            self.profile.setCachePath(str(store / "cache"))
            self._local_only = LocalOnly(self.profile)
            self.profile.setUrlRequestInterceptor(self._local_only)
        self.view = QWebEngineView()
        page = Page(self.profile, self.view)
        self._bridge = _Bridge(self)
        self._bridge.clicked.connect(self._on_globe_click)
        self._bridge.hd.connect(self._on_globe_hd)
        self._channel = QWebChannel(page)
        self._channel.registerObject("radio", self._bridge)
        page.setWebChannel(self._channel)
        page.loadFinished.connect(self._on_globe_loaded)
        self.view.setPage(page)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        t = theme.T
        page.setHtml(radio.globe_html(_qwebchannel_js(), t["bg"], t["accent"], t["accent2"],
                                      t["text"]), radio.globe_base_url())
        self.globe_layout.addWidget(self.view)
        app = QGuiApplication.instance()
        if app is not None and not self._app_state_hooked:
            self._app_state_hooked = True
            app.applicationStateChanged.connect(self._on_app_state)
        self._follow_window()

    def _follow_window(self):
        """Redraw the globe while the window moves or goes to another screen. A sleeping
        globe isn't redrawn by itself, and a screen change can drop its picture while the
        country names (page text) stay — names floating on nothing."""
        win = self.window()
        if win is self._watched:
            return
        if self._watched is not None:
            self._watched.removeEventFilter(self)
        self._watched = win
        win.installEventFilter(self)
        handle = win.windowHandle()
        if handle is not None:
            handle.screenChanged.connect(self._wake_globe)

    def eventFilter(self, obj, ev):
        if obj is self._watched and ev.type() in (QEvent.Move, QEvent.Resize,
                                                  QEvent.ScreenChangeInternal,
                                                  QEvent.DevicePixelRatioChange):
            if not self._wake_timer.isActive():
                self._wake_timer.start()
        return super().eventFilter(obj, ev)

    def _wake_globe(self, *_):
        self._js("wake()")

    def _on_globe_hd(self, on: bool):
        # from inside the page's own callback: swap once it has returned
        QTimer.singleShot(0, self, lambda: self._set_map("globe" if on else "flat"))

    def _on_app_state(self, state):
        # a game or another window in front: the globe stops drawing
        self._js(f"setActive({'true' if state == Qt.ApplicationActive else 'false'})")

    def _js(self, js: str):
        if self.view is not None and self._globe_loaded:
            self.view.page().runJavaScript(js)

    def _on_globe_loaded(self, ok: bool):
        self._globe_loaded = bool(ok)
        self._globe_theme()   # the theme may have changed while it was loading
        app = QGuiApplication.instance()
        if app is not None and app.applicationState() != Qt.ApplicationActive:
            self._on_app_state(app.applicationState())
        if self._globe_list:
            self._push_globe(force=True)
        self._select_on_globe(fly=False)

    def _push_globe(self, force: bool = False):
        """Pin the popular stations on the map — only those the filters let through — and
        name the cities and towns they're in. The flat map takes them all, the globe the
        most listened (WebGL: fewer is smoother)."""
        shown = self._filtered(self._globe_list)
        if self._map_mode() == "globe":
            shown = shown[:radio.GLOBE_LIGHT]   # the list is most-listened first
        ids = [s.uuid for s in shown]
        if force or ids != self._globe_shown:
            self._globe_shown = ids
            # back to a filter shown before: its towns aren't worked out again
            key = tuple(ids)
            got = self._map_cache.pop(key, None)
            if got is None:
                points = radio.globe_points(shown)
                got = [points, radio.town_labels(points), None]
            self._map_cache[key] = got
            while len(self._map_cache) > MAP_CACHE:
                self._map_cache.pop(next(iter(self._map_cache)))
            if self.flat is None and self.view is not None and self._globe_loaded:
                if got[2] is None:     # JSON for 3000 stations: ~7 ms
                    got[2] = (f"setStations({json.dumps(got[0])})",
                              f"setTowns({json.dumps(got[1])})")
                for js in got[2]:
                    self._js(js)
            else:
                self._map("setStations", got[0])
                self._map("setTowns", got[1])

    def _select_on_globe(self, fly: bool):
        st = self.player.station
        pts = radio.globe_points([st]) if st is not None else []
        self._map("select", pts[0] if pts else None, fly)

    def _on_globe_click(self, uuid: str):
        s = self._stations.get(uuid)
        if s is not None:
            self.play(s)
            self._highlight(s.uuid)

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
            self._refresh_info("Refreshing the station list…")
        if not self._globe_list:
            self._show_list()
            self._refresh_info()

    def _on_globe_stations(self, stations: list):
        self._globe_error = ""
        self._globe_list = stations
        self._map_cache.clear()    # new station data: new points and towns
        self._remember(stations)
        self._push_globe(force=True)
        self._show_list()
        if self._reloading:
            self._reloading = False
            busy.set_busy(self.btn_refresh, False)
            stale = getattr(self.dir, "globe_stale", "")
            self._refresh_info(
                f"<span style='color:{theme.status('warn')}'>Couldn't reach the station "
                "directory — showing the saved list.</span>" if stale else
                f"<span style='color:{theme.status('ok')}'>✓ Station list updated: "
                f"{len(stations)} stations.</span>")
        else:
            self._refresh_info()

    def _on_failed(self, kind: str, msg: str):
        if kind == "globe":
            self._reloading = False
            busy.set_busy(self.btn_refresh, False)
            self._map("showMessage", "The station directory can't be reached right now. "
                      "Check your connection and press ↻.")
            # stays up (list and info line) until a reload gets through
            self._globe_error = msg or "no answer"
            self._flash_until = 0.0
            self._show_list()
            self._refresh_info()
        elif self._query:
            self._results, self._search_failed = [], True
            self._show_list()
            self._refresh_info(f"<span style='color:{theme.status('error')}'>Search failed "
                               f"({html.escape(msg)}). Check your connection and press "
                               f"Enter to try again.</span>")

    def _on_text(self, text: str):
        self._query = " ".join(text.split())
        if not self._query:
            self._search_timer.stop()
            self.dir.search("")    # drops any search still on its way
            self._results, self._search_failed = None, False
            self._show_list()
            return
        self._results, self._search_failed = None, False
        # soon: matches among the stations already known (not on every keystroke)
        self._type_timer.start()
        self._search_timer.start(SEARCH_DELAY_MS)

    def flush_typing(self):
        """Show the list for what's typed now, not after the typing pause."""
        if self._type_timer.isActive():
            self._show_list()

    def _search_now(self):
        self._search_timer.stop()
        self.flush_typing()
        if self._query:
            self.start()
            if self._search_failed:   # trying again: back to "Searching…"
                self._results, self._search_failed = None, False
                self._show_list()
            self.dir.search(self._query)
            self._refresh_info("Searching…")

    def _on_results(self, query: str, stations: list):
        if query != radio.search_text(self._query):   # long queries are cut short
            return
        self._remember(stations)
        self._results = [self._stations[s.uuid] for s in stations]
        self._show_list()
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

    def visible_stations(self, source: list[Station] | None = None) -> list[Station]:
        return self._sorted(self._filtered(self._source() if source is None else source))

    def _sorted(self, stations: list[Station]) -> list[Station]:
        key = SORTS[max(0, self.cmb_sort.currentIndex())][1]
        return sorted(stations, key=key) if key else stations

    def _show_list(self):
        self._type_timer.stop()    # whatever was typed is in this one
        source = self._source()    # once: a search goes through every known station
        others = self._filtered(source, country=False)
        self._fill_countries(others, filtered=True)
        every = self._sorted([s for s in others if _country(s) == self._country]
                             if self._country else others)
        stations = every[:LIST_MAX]
        n, total = len(every), len(source)
        self.count_label.setText(
            f"{n:,} of {total:,} stations" if n != total else
            f"{n:,} station{'' if n == 1 else 's'}" + (" (top 300 shown)" if n > LIST_MAX else ""))
        self.btn_clear.setVisible(self.filters_on())
        cur = self.list.currentItem()
        keep = cur.data(Qt.UserRole) if cur is not None else None
        playing = self.player.station.uuid if self.player.station else None
        self._rows_playing = playing
        fav = self._fav_ids
        self.list.blockSignals(True)
        self.list.clear()
        for s in stations:
            it = QListWidgetItem(self._row_text(s, playing, fav))
            it.setData(Qt.UserRole, s.uuid)
            # station data is community-edited: escape it, or Qt renders it as HTML
            it.setToolTip(f"<p>{html.escape(s.name)}"
                          + (f"<br>{html.escape(s.homepage)}" if s.homepage else "") + "</p>")
            if s.uuid == playing:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.list.addItem(it)
            if s.uuid == keep:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if not stations:
            if self._query:
                empty = ("Searching…" if self._results is None else
                         "Search failed — press Enter to try again." if self._search_failed
                         else "No stations found.")
            elif source and self.filters_on():
                empty = "No stations match these filters.\nTry another genre or country."
            elif self.btn_favs.isChecked():
                empty = "No favorites yet.\nHover a station and click its ☆ to keep it here."
            elif self.btn_recent.isChecked():
                empty = "Nothing played yet.\nStations you listen to show up here."
            else:
                empty = self._no_stations_text()
            if empty:
                it = QListWidgetItem(empty)
                it.setFlags(Qt.NoItemFlags)
                self.list.addItem(it)
        self._update_buttons()

    @staticmethod
    def _row_text(s: Station, playing: str | None, fav: set[str]) -> str:
        """A row's text (the delegate paints its own; this is for screen readers)."""
        star = "★ " if s.uuid in fav else ""
        return f"{'▶ ' if s.uuid == playing else ''}{star}{s.name}\n{s.subtitle()}"

    def _restate_rows(self, *changed: str, rebuild: bool = False):
        """Playing, stopping or starring a station changes how its row looks, not which
        rows there are (unless `rebuild`: Favorites or Recent showing): the rows of the
        station that was playing, the one playing now and `changed` are relabelled and
        the list repainted, instead of the whole list being made again."""
        if rebuild:
            self._show_list()
            return
        playing = self.player.station.uuid if self.player.station else None
        fav = self._fav_ids
        todo = {self._rows_playing, playing, *changed} - {None}
        self._rows_playing = playing
        for i in range(self.list.count() if todo else 0):
            it = self.list.item(i)
            uuid = it.data(Qt.UserRole)
            s = self._stations.get(uuid) if uuid in todo else None
            if s is None:
                continue
            text = self._row_text(s, playing, fav)
            if it.text() != text:
                it.setText(text)
            if it.font().bold() != (s.uuid == playing):
                f = it.font()
                f.setBold(s.uuid == playing)
                it.setFont(f)
        self.list.viewport().update()
        self._update_buttons()

    def _highlight(self, uuid: str):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) == uuid:
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it)
                return

    def selected(self) -> Station | None:
        it = self.list.currentItem()
        return self._stations.get(it.data(Qt.UserRole)) if it is not None else None

    def _on_current(self, it, _prev):
        s = self._stations.get(it.data(Qt.UserRole)) if it is not None else None
        if s is not None and s.lat is not None and self.player.station is None:
            # browsing the list turns the map to the station (play one and it stays put)
            p = radio.globe_points([s])[0]
            self._map("fly", p["la"], p["lo"], 1.8, 800)
        self._update_buttons()

    def _on_activated(self, it):
        s = self._stations.get(it.data(Qt.UserRole))
        if s is not None:
            self.play(s)

    # ------------------------------------------------------------------ playing
    def play_random(self):
        """A random station from the ones listed (the filters apply), never the one
        already playing."""
        now = self.player.station
        pool = [s for s in self.visible_stations()[:LIST_MAX]
                if now is None or s.uuid != now.uuid]
        if pool:
            self.play(random.choice(pool))

    def play(self, s: Station):
        self._title = ""
        if self._fed_by is None or self._fed_by.uuid != s.uuid:
            self.recorder.clear_replay()   # "Last 15s" is only ever this station
        self._fed_by = s
        self.player.play(s)
        if self.cfg.radio.get("count_plays", False):   # Settings > Privacy, off by default
            self.dir.count_click(s.uuid)
        self.cfg.radio["last"] = s.to_saved()
        self.recent = ([s] + [r for r in self.recent if r.uuid != s.uuid])[:RECENT_MAX]
        self.cfg.radio["recent"] = [r.to_saved() for r in self.recent]
        self._save()
        self._select_on_globe(fly=True)
        self._restate_rows(rebuild=self.btn_recent.isChecked() and not self._query)
        self._refresh_info()
        self._report_active()

    def is_active(self) -> bool:
        """A station is playing (to you, or to everyone with LIVE on)."""
        return self.player.station is not None

    def live_tip(self) -> str:
        """The "● ON" line for the Radio tab's tooltip while a station plays."""
        return ("● ON: a station is playing — others hear it" if self.engine.radio_live
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
            self._restate_rows()
        self._report_active()

    def _toggle_play(self):
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

    def _on_state(self, _st: str):
        self._flash_until = 0.0    # what's playing matters more than an older notice
        self._refresh_info()
        self._update_buttons()
        self._report_active()      # the player gave the station up by itself

    def _on_error(self, msg: str):
        self._restate_rows()
        red = theme.status("error")
        self._refresh_info(f"<span style='color:{red}'>That station isn't working "
                           f"({html.escape(msg)}). Try another one.</span>")
        self._select_on_globe(fly=False)

    def _on_now_playing(self, title: str):
        st = self.player.station
        if st is not None and title.strip().lower() != st.name.strip().lower():
            self._title = title
            self._refresh_info()

    def _update_buttons(self):
        on = self.player.station is not None
        self.btn_play.setText("" if self._play_short else "Stop" if on else "Play")
        icons.set_icon(self.btn_play, "stop" if on else "play")
        self.btn_play.setEnabled(on or self.selected() is not None
                                 or bool(self.cfg.radio.get("last")))
        s = self.selected() or self.player.station
        fav = s is not None and s.uuid in self._fav_ids
        icons.set_icon(self.btn_fav, "star_filled" if fav else "star",
                       "accent" if fav else "text")
        self.btn_fav.setToolTip("Remove from Favorites" if fav else "Add to Favorites")
        self.btn_fav.setEnabled(s is not None)

    def _no_stations_text(self) -> str:
        if self._globe_error:
            return "Can't reach the station directory — press ↻ to try again."
        return "Finding stations…" if self._started else ""

    def _refresh_info(self, msg: str = ""):
        if msg:
            self._flash_until = time.monotonic() + 4
            self.info.setText(msg)
            return
        if time.monotonic() < self._flash_until:
            return
        st, state = self.player.station, self.player.status
        if st is None:
            n = len(self._globe_list)
            text = (f"{n:,} popular stations — click a dot on the map, or search. "
                    "Click a station's badge (or double-click it) to play it." if n else
                    self._no_stations_text())
            if not n and self._globe_error:
                red = theme.status("error")
                text = (f"<span style='color:{red}'>Can't reach the station directory "
                        f"({html.escape(self._globe_error)}) — press ↻ to try again.</span>")
        else:
            name = html.escape(st.name)
            where = html.escape(st.country) if st.country else ""
            if state == "connecting":
                text = f"Tuning in to <b>{name}</b>…"
            else:
                text = f"▶ <b>{name}</b>" + (f" · {where}" if where else "")
                if self._title:
                    text += f" — <i>{html.escape(self._title)}</i>"
            if self.engine.radio_live:
                text += f"  <span style='color:{theme.status('ok')}'>· others hear it</span>"
            else:
                text += ("  · only you hear the radio: press “Only me” below to send it "
                         "to others too")
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
        self._restate_rows(s.uuid, rebuild=self.btn_favs.isChecked() or bool(self._query))

    # ------------------------------------------------------------------ controls
    def _on_live(self, on: bool):
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
        self.btn_live.setText("LIVE" if on else "Only me")
        self.btn_live.setToolTip("Others hear the radio. Click so only you do." if on else
                                 "Only you hear the radio. Click to go live: others hear "
                                 "it too.")

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r
        def star_only(compact):
            self.btn_favs.setText("" if compact else "Favorites")
            r.touch(self.btn_favs)

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
                (36, "w", r.icon_only(self.btn_last)),
                (36, "w", play_icon),
                (40, "w", r.hide(*self._vol_group)),
                (46, "w", r.hide(self.globe_box)),      # narrow: just the list
                (50, "w", r.hide(*self._clip_group, self.btn_fav, self.btn_refresh)),
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
        self.btn_rec.setText("Record")
        self._emit_clip(self.recorder.stop(), "Nothing was playing while you recorded.")

    def clip_last(self) -> bool:
        return self._emit_clip(self.recorder.last(),
                               f"Nothing has played in the last {CLIP_S} seconds.")

    def _emit_clip(self, data: np.ndarray, empty_msg: str) -> bool:
        data = trim_silence(data)
        if len(data) < int(0.2 * SR):
            self._refresh_info(f"<span style='color:{theme.status('warn')}'>{empty_msg}</span>")
            return False
        st = self.player.station or self._fed_by or self.selected()
        name = (st.name[:30] if st else "Radio") + " " + time.strftime("%H.%M.%S")
        self.clip_error = ""
        self.clip_ready.emit(data, name)   # the window saves it (and sets clip_error if not)
        if self.clip_error:
            self._refresh_info(f"<span style='color:{theme.status('error')}'>Couldn't save "
                               f"the clip: {html.escape(self.clip_error)}</span>")
            return False
        green = theme.status("ok")
        self._refresh_info(f"<span style='color:{green}'>✓ Saved a {len(data) / SR:.1f}s clip "
                           "to your Sounds.</span>")
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
        if self.recorder.recording:
            secs = self.recorder.rec_frames / SR
            self.btn_rec.setText(f"Stop  {int(secs // 60)}:{int(secs % 60):02d}")
        elif self._flash_until and time.monotonic() >= self._flash_until:
            self._flash_until = 0.0
            self._refresh_info()

    def retheme(self):
        self._style_panel()
        self._globe_theme()

    def _globe_theme(self):
        """The map was drawn in the theme of its day: send it today's."""
        self._map("setTheme", *(theme.T[k] for k in ("bg", "accent", "accent2", "text")))

    def shutdown(self):
        self.timer.stop()
        self._search_timer.stop()
        self._type_timer.stop()
        if self.recorder.recording:
            self.recorder.stop()
        self.player.shutdown()


class RadioOff(QWidget):
    """The Radio tab while Radio is switched off in Settings > Privacy & security: a
    short note and a way there. Nothing here goes online (no directory, player or web
    view is made). It answers the main window like RadioTab, with nothing playing."""
    clip_ready = Signal(object, str)
    active_changed = Signal(bool)
    open_settings = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addStretch(1)
        title = QLabel("Radio is off")
        title.setObjectName("section")
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)
        note = QLabel("It's switched off in Settings > Privacy & security, so the radio "
                      "contacts nobody: no station directory, no stations.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignCenter)
        v.addWidget(note)
        go = QPushButton("Privacy & security settings")
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
