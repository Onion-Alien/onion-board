"""The Radio tab: internet radio from all over the world, picked on a 3D globe or
by searching, played through the engine so it can go out through your mic like
the Browser tab's audio. The directory, player and globe page are in radio.py.

Nothing touches the network until the tab is first opened.
"""
from __future__ import annotations

import html
import json
import logging
import time
import zlib
from string import Template

import numpy as np
from PySide6.QtCore import (QEvent, QFile, QIODevice, QObject, QRect, QRectF, QSize,
                            Qt, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSizePolicy, QSplitter, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from soundboard import library, radio, theme
from soundboard.engine import SR
from soundboard.library import MAX_SECONDS, trim_silence
from soundboard.radio import RadioDirectory, RadioPlayer, Station
from soundboard.ui import icons
from soundboard.ui.panel import Flow as _Flow
from soundboard.ui.panel import VolumeControl, bar, icon_label, vsep

log = logging.getLogger(__name__)

CLIP_S = 15
LIST_MAX = 300             # rows shown at once
SEARCH_DELAY_MS = 450      # typing pause before the directory is asked
FAV_MAX = 200
RECENT_MAX = 30
GREEN, AMBER, RED = "#13ce66", "#ffb020", "#ff4d4f"
ROW_H = 54

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
    return any(w in t.lower() for t in s.tags for w in words)


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
    """The globe page's only way back into the app: "this dot was clicked"."""
    clicked = Signal(str)

    @Slot(str)
    def play(self, uuid):
        self.clicked.emit(str(uuid)[:64])


class _StationDelegate(QStyledItemDelegate):
    """Paints a station row: a country badge (play button on hover), the name over its
    country and genres, a bitrate pill and a star. Clicking the badge plays or stops
    the station; clicking the star adds or removes it from Favorites."""

    def __init__(self, tab: RadioTab):
        super().__init__(tab.list)
        self.tab = tab

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
            key = s.cc or _country(s) or s.name
            hue = zlib.crc32(key.encode("utf-8")) % 360
            p.fillPath(path, QColor.fromHsl(hue, 95, 88))
            f = QFont(opt.font)
            f.setPointSizeF(8.5)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(avatar, Qt.AlignCenter, s.cc or (s.name[:1].upper() or "?"))

        # star
        f = QFont(opt.font)
        f.setPointSizeF(13)
        p.setFont(f)
        if fav:
            p.setPen(QColor("#ffc53d"))
            p.drawText(star, Qt.AlignCenter, "★")
        elif hover or sel:
            p.setPen(QColor(t["faint"]))
            p.drawText(star, Qt.AlignCenter, "☆")

        # bitrate pill
        right = star.left() - 6
        pill_txt = f"{s.bitrate}k" if s.bitrate else (s.codec or "")[:5].upper()
        if pill_txt:
            f = QFont(opt.font)
            f.setPointSizeF(7.5)
            f.setBold(True)
            fm = QFontMetrics(f)
            w = fm.horizontalAdvance(pill_txt) + 12
            pill = QRectF(right - w, card.center().y() - 9, w, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["badge"]))
            p.drawRoundedRect(pill, 9, 9)
            p.setFont(f)
            hi = GREEN if QColor(t["bg"]).lightness() < 128 else "#0b7a43"
            p.setPen(QColor(hi if s.bitrate >= 256 else t["badge_text"]))
            p.drawText(pill, Qt.AlignCenter, pill_txt)
            right = int(pill.left()) - 8

        # name over country · genres
        left = avatar.right() + 11
        width = max(10, right - left)
        f = QFont(opt.font)
        f.setPointSizeF(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(t["accent_hi"] if playing else t["text_hi"]))
        name = QFontMetrics(f).elidedText(s.name, Qt.ElideRight, width)
        p.drawText(QRect(left, card.top() + 7, width, 21), Qt.AlignLeft | Qt.AlignVCenter, name)
        f = QFont(opt.font)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(t["muted"]))
        sub = " · ".join(b for b in (_country(s), ", ".join(s.tags[:3])) if b)
        sub = QFontMetrics(f).elidedText(sub, Qt.ElideRight, width)
        p.drawText(QRect(left, card.top() + 27, width, 18), Qt.AlignLeft | Qt.AlignVCenter, sub)
        p.restore()

    def editorEvent(self, ev, model, opt, idx):
        if (ev.type() == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton
                and idx.data(Qt.UserRole)):
            uuid = idx.data(Qt.UserRole)
            _card, avatar, star = self._rects(opt.rect)
            pos = ev.position().toPoint()
            # after this event: both rebuild the list this row belongs to
            if star.adjusted(-4, -4, 4, 4).contains(pos):
                QTimer.singleShot(0, lambda: self.tab._toggle_fav(uuid))
                return True
            if avatar.contains(pos):
                QTimer.singleShot(0, lambda: self.tab._play_or_stop(uuid))
                return True
        return super().editorEvent(ev, model, opt, idx)


class RadioTab(QWidget):
    clip_ready = Signal(object, str)   # audio, suggested name (like BrowserTab's)

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
        self.player.audio.connect(self._on_audio)
        self.player.state.connect(self._on_state)
        self.player.error.connect(self._on_error)
        self.player.now_playing.connect(self._on_now_playing)
        from soundboard.recorder import Recorder
        self.recorder = Recorder(library.APP_DIR / "radio-recording.tmp.wav")

        self._want_globe = globe
        self.view = None           # the globe, made on first show
        self._globe_loaded = False
        self._started = False
        self._stations: dict[str, Station] = {}
        self._globe_list: list[Station] = []
        self._results: list[Station] | None = None
        self._query = ""
        self._search_failed = False  # the last directory search didn't get through
        self._globe_error = ""       # the station list couldn't be fetched (and none cached)
        self._title = ""           # what the station says is playing
        self._flash_until = 0.0
        self.favorites: list[Station] = [s for s in map(Station.from_saved,
                                                        cfg.radio.get("favorites", [])) if s]
        self.recent: list[Station] = [s for s in map(Station.from_saved,
                                                     cfg.radio.get("recent", [])) if s]
        for s in self.recent + self.favorites:
            self._stations[s.uuid] = s
        self._fav_ids = {s.uuid for s in self.favorites}
        self._genre = ""           # "" = all genres
        self._country = ""         # "" = all countries
        self._globe_shown: list[str] = []   # uuids last pinned on the globe

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)

        # ---- search row
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search radio stations, genres or countries…  "
                                       "(or spin the globe and click a dot)")
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

        # ---- control bar: play | live | meter | record | last 15 s | star | volume | hear
        bar_, bh = bar()
        self.btn_play = QPushButton("Play")
        self.btn_play.setToolTip("Play the selected station / stop the radio")
        icons.set_icon(self.btn_play, "play")
        self.btn_play.clicked.connect(self._toggle_play)
        bh.addWidget(self.btn_play)
        self.btn_live = QPushButton()
        self.btn_live.setObjectName("live")
        self.btn_live.setCheckable(True)
        icons.set_icon(self.btn_live, "live", checked_color="#ffffff")
        self.btn_live.toggled.connect(self._on_live)
        bh.addWidget(self.btn_live)
        self.meter = meter_cls()
        self.meter.setMinimumWidth(50)
        self.meter.setToolTip("Radio level")
        bh.addWidget(self.meter, 1)
        sep1 = vsep()
        bh.addWidget(sep1)
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
        self.btn_fav = QPushButton("☆")
        self.btn_fav.setToolTip("Star the selected station (★ Favorites)")
        self.btn_fav.clicked.connect(lambda: self._toggle_fav())
        bh.addWidget(self.btn_fav)
        sep2 = vsep()
        bh.addWidget(sep2)
        vol_icon = icon_label("volume", "Radio volume (for them and for you)")
        bh.addWidget(vol_icon)
        vol_lbl = QLabel("Radio volume")
        bh.addWidget(vol_lbl)
        self.vol = VolumeControl(float(cfg.radio.get("vol", 1.0) or 1.0),
                                 tip="Radio volume (for them and for you)")
        self.vol.changed.connect(self._on_vol)
        bh.addWidget(self.vol)
        self._clip_group = (sep1, self.btn_rec, self.btn_last)
        self._vol_group = (sep2, vol_icon, vol_lbl, self.vol)
        self._live_short = self._play_short = False
        self.chk_hear = QCheckBox("Hear it myself")
        self.chk_hear.setToolTip("Also play the radio into your headphones")
        self.chk_hear.toggled.connect(self._on_hear)
        bh.addWidget(self.chk_hear)
        v.addWidget(bar_)

        # LIVE always starts off, like the Browser tab's
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
        self._refresh_info()
        self._update_buttons()

    # ------------------------------------------------------------------ station panel
    _PANEL_STYLE = Template("""
QFrame#stations { background:$panel; border-radius:12px; }
QFrame#stations QWidget { background:transparent; }
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
        self.btn_favs = QPushButton("★ Favorites")
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
        row = QHBoxLayout()
        row.setSpacing(6)
        self.cmb_country = QComboBox()
        self.cmb_country.setToolTip("Only stations from this country")
        self.cmb_country.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_country.setMinimumContentsLength(8)
        self.cmb_country.addItem("All countries", "")
        self.cmb_country.activated.connect(
            lambda _i: self.set_country(self.cmb_country.currentData() or ""))
        row.addWidget(self.cmb_country, 3)
        self.cmb_quality = QComboBox()
        self.cmb_quality.setToolTip("Only stations streaming at least this bitrate")
        for label, kbps in QUALITIES:
            self.cmb_quality.addItem(label, kbps)
        self.cmb_quality.activated.connect(lambda _i: self._on_filter())
        row.addWidget(self.cmb_quality, 2)
        self.cmb_sort = QComboBox()
        self.cmb_sort.setToolTip("Sort the list")
        for label, _key in SORTS:
            self.cmb_sort.addItem(label)
        self.cmb_sort.activated.connect(lambda _i: self._show_list())
        row.addWidget(self.cmb_sort, 2)
        fv.addLayout(row)
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
        return [s for s in stations
                if (not self._genre or in_genre(s, self._genre))
                and (not country or not self._country or _country(s) == self._country)
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

    def _fill_countries(self, source: list[Station]):
        counts: dict[str, int] = {}
        for s in self._filtered(source, country=False):
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
        self.timer.start(50)
        self.start()

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
            self._make_globe()
            w = max(self.split.width(), 800)
            self.split.setSizes([w * 3 // 5, w * 2 // 5])
        self.dir.load_globe()
        self._refresh_info()

    def _make_globe(self):
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        class Page(QWebEnginePage):
            def createWindow(self, _type):
                return None

            def acceptNavigationRequest(self, url, _type, is_main_frame):
                # only our own page (setHtml arrives as a data: URL); links go nowhere
                return not is_main_frame or url.scheme() in ("data", "about")

        store = radio.radio_dir() / "web"
        self.profile = QWebEngineProfile("soundboard-radio", self)   # caches the globe script
        self.profile.setPersistentStoragePath(str(store))
        self.profile.setCachePath(str(store / "cache"))
        self.view = QWebEngineView()
        page = Page(self.profile, self.view)
        self._bridge = _Bridge(self)
        self._bridge.clicked.connect(self._on_globe_click)
        self._channel = QWebChannel(page)
        self._channel.registerObject("radio", self._bridge)
        page.setWebChannel(self._channel)
        page.loadFinished.connect(self._on_globe_loaded)
        self.view.setPage(page)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        t = theme.T
        page.setHtml(radio.globe_html(_qwebchannel_js(), t["bg"], t["accent"], t["accent2"],
                                      t["text"]), QUrl("about:blank"))
        self.globe_layout.addWidget(self.view)

    def _js(self, js: str):
        if self.view is not None and self._globe_loaded:
            self.view.page().runJavaScript(js)

    def _on_globe_loaded(self, ok: bool):
        self._globe_loaded = bool(ok)
        if self._globe_list:
            self._push_globe(force=True)
        self._select_on_globe(fly=False)

    def _push_globe(self, force: bool = False):
        """Pin the popular stations on the globe — only those the filters let through."""
        shown = self._filtered(self._globe_list)
        ids = [s.uuid for s in shown]
        if force or ids != self._globe_shown:
            self._globe_shown = ids
            self._js(f"setStations({json.dumps(radio.globe_points(shown))})")

    def _select_on_globe(self, fly: bool):
        st = self.player.station
        pts = radio.globe_points([st]) if st is not None else []
        self._js(f"select({json.dumps(pts[0] if pts else None)}, {'true' if fly else 'false'})")

    def _on_globe_click(self, uuid: str):
        s = self._stations.get(uuid)
        if s is not None:
            self.play(s)
            self._highlight(s.uuid)

    # ------------------------------------------------------------------ station lists
    def _remember(self, stations: list[Station]):
        for s in stations:
            self._stations.setdefault(s.uuid, s)

    def _reload(self):
        self._globe_error = ""
        self._flash_until = 0.0
        self.dir.load_globe(force=True)
        if not self._globe_list:
            self._show_list()
            self._refresh_info()

    def _on_globe_stations(self, stations: list):
        self._globe_error = ""
        self._globe_list = stations
        self._remember(stations)
        self._push_globe(force=True)
        self._show_list()
        self._refresh_info()

    def _on_failed(self, kind: str, msg: str):
        if kind == "globe":
            self._js("showMessage('The station directory can\\'t be reached right now. "
                     "Check your connection and press ↻.')")
            # stays up (list and info line) until a reload gets through
            self._globe_error = msg or "no answer"
            self._flash_until = 0.0
            self._show_list()
            self._refresh_info()
        elif self._query:
            self._results, self._search_failed = [], True
            self._show_list()
            self._refresh_info(f"<span style='color:{RED}'>Search failed "
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
        self._show_list()          # instant: matches among the stations already known
        self._search_timer.start(SEARCH_DELAY_MS)

    def _search_now(self):
        self._search_timer.stop()
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
        words = self._query.lower().split()
        seen, out = set(), []
        for s in self.favorites + self._globe_list:
            if s.uuid not in seen and s.matches(words):
                seen.add(s.uuid)
                out.append(s)
        return out

    def visible_stations(self) -> list[Station]:
        out = self._filtered(self._source())
        key = SORTS[max(0, self.cmb_sort.currentIndex())][1]
        return sorted(out, key=key) if key else out

    def _show_list(self):
        source = self._source()
        self._fill_countries(source)
        every = self.visible_stations()
        stations = every[:LIST_MAX]
        n, total = len(every), len(source)
        self.count_label.setText(
            f"{n:,} of {total:,} stations" if n != total else
            f"{n:,} station{'' if n == 1 else 's'}" + (" (top 300 shown)" if n > LIST_MAX else ""))
        self.btn_clear.setVisible(self.filters_on())
        cur = self.list.currentItem()
        keep = cur.data(Qt.UserRole) if cur is not None else None
        playing = self.player.station.uuid if self.player.station else None
        fav = self._fav_ids
        self.list.blockSignals(True)
        self.list.clear()
        for s in stations:
            star = "★ " if s.uuid in fav else ""
            it = QListWidgetItem(f"{'▶ ' if s.uuid == playing else ''}{star}{s.name}\n"
                                 f"{s.subtitle()}")
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
            elif self._source() and self.filters_on():
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
            # browsing the list turns the globe to the station (play one and it stays put)
            p = radio.globe_points([s])[0]
            self._js(f"W && (W.controls().autoRotate = false, "
                     f"W.pointOfView({{lat: {p['la']}, lng: {p['lo']}, altitude: 1.8}}, 800))")
        self._update_buttons()

    def _on_activated(self, it):
        s = self._stations.get(it.data(Qt.UserRole))
        if s is not None:
            self.play(s)

    # ------------------------------------------------------------------ playing
    def play(self, s: Station):
        self._title = ""
        self.player.play(s)
        self.dir.count_click(s.uuid)
        self.cfg.radio["last"] = s.to_saved()
        self.recent = ([s] + [r for r in self.recent if r.uuid != s.uuid])[:RECENT_MAX]
        self.cfg.radio["recent"] = [r.to_saved() for r in self.recent]
        self._save()
        self._select_on_globe(fly=True)
        self._show_list()
        self._refresh_info()

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
            self._show_list()

    def _toggle_play(self):
        if self.player.station is not None:
            self.stop()
            return
        s = self.selected() or Station.from_saved(self.cfg.radio.get("last") or {})
        if s is not None:
            self._stations.setdefault(s.uuid, s)
            self.play(s)

    def _on_audio(self, x: np.ndarray):
        self.engine.feed_radio(x)
        self.recorder.push(x)

    def _on_state(self, _st: str):
        self._flash_until = 0.0    # what's playing matters more than an older notice
        self._refresh_info()
        self._update_buttons()

    def _on_error(self, msg: str):
        self._show_list()
        self._refresh_info(f"<span style='color:{RED}'>That station isn't working "
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
        self.btn_fav.setText("★" if fav else "☆")
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
            text = (f"{n:,} stations on the globe — spin it and click a dot, or search. "
                    "Click a station's badge (or double-click it) to play it." if n else
                    self._no_stations_text())
            if not n and self._globe_error:
                text = (f"<span style='color:{RED}'>Can't reach the station directory "
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
                text += f"  <span style='color:{GREEN}'>· others hear it</span>"
            else:
                text += "  · only you hear it (LIVE sends it to others)"
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
        self._show_list()

    # ------------------------------------------------------------------ controls
    def _on_live(self, on: bool):
        self.engine.radio_live = on
        self.btn_live.blockSignals(True)
        self.btn_live.setChecked(on)
        self.btn_live.blockSignals(False)
        self._label_live()
        self._refresh_info()

    def _label_live(self):
        on = self.btn_live.isChecked()
        if self._live_short:
            self.btn_live.setText("LIVE" if on else "Only me")
        else:
            self.btn_live.setText("LIVE — others hear it" if on else "Only me — click to go live")

    def _short_live(self, short: bool):
        from soundboard.ui import responsive
        self._live_short = short
        self._label_live()
        responsive.touch(self.btn_live)

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r
        def star_only(compact):
            self.btn_favs.setText("★" if compact else "★ Favorites")
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
                (44, "w", self._short_live),
                (46, "w", r.hide(self.globe_box)),      # narrow: just the list
                (50, "w", r.hide(*self._clip_group, self.btn_fav, self.btn_refresh)),
                (75, "w", r.hide(self.meter)),         # tiny: just Play and LIVE
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
            self.timer.start(50)   # the length cap is checked on the tick
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
            self._refresh_info(f"<span style='color:{AMBER}'>{empty_msg}</span>")
            return False
        st = self.player.station or self.selected()
        name = (st.name[:30] if st else "Radio") + " " + time.strftime("%H.%M.%S")
        self.clip_ready.emit(data, name)
        self._refresh_info(f"<span style='color:{GREEN}'>✓ Saved a {len(data) / SR:.1f}s clip "
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
        t = theme.T
        self._style_panel()
        self._js(f"document.body.style.background = {json.dumps(t['bg'])}; "
                 f"W && W.backgroundColor({json.dumps(t['bg'])})")

    def shutdown(self):
        self.timer.stop()
        self._search_timer.stop()
        if self.recorder.recording:
            self.recorder.stop()
        self.player.shutdown()
