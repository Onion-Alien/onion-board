"""The Radio tab's station list (ui/radio/radiopanel.py): the Popular / Favorites / Recent
switch, the genre chips, the country / quality / sort boxes and their filters, and
the list itself, painted row by row (``_StationDelegate``).

``RadioTab`` makes one ``StationList`` (``RadioTab.listctl``), a QObject it owns; the
widgets it builds stay on the tab (``tab.list``, ``tab.cmb_country``…). Everything
here runs on the UI thread."""
from __future__ import annotations

import html
import zlib
from string import Template
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QStyle,
                               QStyledItemDelegate, QStyleOptionComboBox, QVBoxLayout,
                               QWidget)

from soundboard.ui.kit import theme
from soundboard.i18n import _, ngettext
from soundboard.online.radio import Station
from soundboard.ui.kit import icons
from soundboard.ui.kit.panel import Flow as _Flow
from soundboard.ui.kit.panel import EmptyList, RoundedFrame
from soundboard.ui.kit.restyled import on_restyle
from soundboard.ui.kit.widgets import paint_now_playing, take_out

if TYPE_CHECKING:
    from soundboard.ui.radio.radiopanel import RadioTab

LIST_MAX = 300             # rows shown at once
ROW_H = 54
MAP_CACHE = 8              # filter combinations whose map points and towns are kept

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
_GENRE_WORDS: dict[str, tuple[str, ...]] = dict(GENRES)
GENRE_LABELS = {"Pop": _("Pop"), "Rock": _("Rock"), "Dance": _("Dance"),
                "Hip-hop": _("Hip-hop"), "Jazz & Soul": _("Jazz & Soul"),
                "Classical": _("Classical"), "Chill": _("Chill"), "Oldies": _("Oldies"),
                "Country & Folk": _("Country & Folk"), "Latin": _("Latin"),
                "Reggae": _("Reggae"), "News & Talk": _("News & Talk")}

# (label, key) — None keeps the list's own order (most listened / starred / most recent)
SORTS = ((_("Default order"), None),
         (_("Most listened"), lambda s: -s.clicks),
         (_("Trending"), lambda s: -s.trend),
         (_("Most voted"), lambda s: -s.votes),
         (_("Name A–Z"), lambda s: s.name.lower()),
         (_("Best quality"), lambda s: -s.bitrate))
QUALITIES = ((_("Any quality"), 0), (_("{kbps} kbps +", kbps=128), 128),
             (_("{kbps} kbps +", kbps=192), 192), (_("{kbps} kbps +", kbps=256), 256))


def in_genre(s: Station, genre: str) -> bool:
    words = _GENRE_WORDS.get(genre)
    if not words:
        return True
    hay = s.genre_hay
    return any(w in hay for w in words)


def _country(s: Station) -> str:
    return s.country or s.cc


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
        return QSize(1, ROW_H if idx.data(Qt.ItemDataRole.UserRole) else 96)   # as wide as the list

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
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        uuid = idx.data(Qt.ItemDataRole.UserRole)
        s = self.tab._stations.get(uuid) if uuid else None
        if s is None:
            p.setPen(QColor(t["muted"]))
            p.drawText(opt.rect.adjusted(20, 8, -20, -8), Qt.AlignmentFlag.AlignCenter
                       | Qt.TextFlag.TextWordWrap,
                       idx.data(Qt.ItemDataRole.DisplayRole) or "")
            p.restore()
            return
        on = self.tab.player.station
        playing = on is not None and on.uuid == uuid
        fav = uuid in self.tab._fav_ids
        hover = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
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
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(cardf, 9, 9)
        if playing:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(card.left(), card.top() + 10, 3, card.height() - 20), 1.5, 1.5)

        # country badge / play button
        path = QPainterPath()
        path.addRoundedRect(QRectF(avatar), 10, 10)
        if playing or hover:
            p.fillPath(path, accent)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["on_accent"]))
            c = QRectF(avatar).center()
            if playing:          # a little equalizer, bouncing (still while tuning in)
                paint_now_playing(p, QRectF(c.x() - 9, c.y() - 9, 18, 18),
                                  QColor(t["on_accent"]), n=3,
                                  paused=self.tab.player.status == "connecting")
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
            p.drawText(avatar, Qt.AlignmentFlag.AlignCenter, s.cc or (s.name[:1].upper() or "?"))

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
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["badge"]))
            p.drawRoundedRect(pill, 9, 9)
            p.setFont(pill_f)
            p.setPen(QColor(t["live_text"] if s.bitrate >= 256 else t["badge_text"]))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, pill_txt)
            right = int(pill.left()) - 8

        # name over country · genres
        left = avatar.right() + 11
        width = max(10, right - left)
        p.setFont(name_f)
        p.setPen(QColor(t["accent_hi"] if playing else t["text_hi"]))
        name = name_fm.elidedText(s.name, Qt.TextElideMode.ElideRight, width)
        p.drawText(QRect(left, card.top() + 7, width, 21), Qt.AlignmentFlag.AlignLeft
                   | Qt.AlignmentFlag.AlignVCenter, name)
        p.setFont(sub_f)
        p.setPen(QColor(t["muted"]))
        sub = " · ".join(b for b in (_country(s), ", ".join(s.tags[:3])) if b)
        sub = sub_fm.elidedText(sub, Qt.TextElideMode.ElideRight, width)
        p.drawText(QRect(left, card.top() + 27, width, 18), Qt.AlignmentFlag.AlignLeft
                   | Qt.AlignmentFlag.AlignVCenter, sub)
        p.restore()

    def editorEvent(self, ev, model, opt, idx):
        if (ev.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick)
                and ev.button() == Qt.MouseButton.LeftButton
                and idx.data(Qt.ItemDataRole.UserRole)):
            uuid = idx.data(Qt.ItemDataRole.UserRole)
            _card, avatar, star = self._rects(opt.rect)
            pos = ev.position().toPoint()
            on_button = star.adjusted(-4, -4, 4, 4).contains(pos) or avatar.contains(pos)
            if ev.type() == QEvent.Type.MouseButtonDblClick:
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
            if ev.type() == QEvent.Type.MouseButtonRelease and opt.rect.contains(pos):
                QTimer.singleShot(0, lambda: self.tab.play_uuid(uuid))   # a click plays it
        return super().editorEvent(ev, model, opt, idx)


class _FilterRow(QWidget):
    """The country / quality / sort boxes: side by side while their words fit, else
    country on a row of its own above the other two, else one box a row. Squeezed
    into one row they read "All coun", "Any qua" in a narrow window."""

    GAP = 6

    def __init__(self, combos: list[QComboBox]):
        super().__init__()
        self.combos = combos
        for c in combos:
            c.setProperty("snug", False)   # sized here, by what their words need
        self.rows = 0
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(self.GAP)
        self._lines = []
        for _combo in combos:
            h = QHBoxLayout()
            h.setSpacing(self.GAP)
            v.addLayout(h)
            self._lines.append(h)
        self._arrange(1)
        for c in combos:   # a longer choice picked may need another row
            c.currentIndexChanged.connect(lambda _i: self._again())
            # and a theme's font: measured again once it's on the box (a hidden tab's
            # boxes get it a moment after the switch: theme._Later)
            on_restyle(c, self._again)

    def _again(self):
        if self.isVisible():   # (hidden, its width isn't laid out yet: on show)
            self._arrange(self.rows_for(self.width()))

    def showEvent(self, e):
        super().showEvent(e)
        self._again()

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
        full = c.style().sizeFromContents(QStyle.ContentsType.CT_ComboBox, opt,
                                          QSize(text, fm.height()), c)
        return max(c.minimumSizeHint().width(), full.width())

    def rows_for(self, width: int) -> int:
        need = [self.needs(c) for c in self.combos]
        if sum(need) + self.GAP * (len(need) - 1) <= width:
            return 1
        if sum(need[1:]) + self.GAP * (len(need) - 2) <= width:
            return 2
        return len(need)

    def _arrange(self, rows: int):
        if rows != self.rows:
            self.rows = rows
            for h in self._lines:
                while h.count():
                    take_out(h)
            for i, c in enumerate(self.combos):
                line = 0 if rows == 1 else (min(i, 1) if rows == 2 else i)
                self._lines[line].addWidget(c)
            for h in self._lines:
                h.addStretch(1)   # boxes as wide as their words, the rest left empty
            self.updateGeometry()
        for c in self.combos:   # a box's share of its row: what its words need
            need = self.needs(c)
            for h in self._lines:
                i = h.indexOf(c)
                if i >= 0:
                    h.setStretch(i, need)
            c.setMaximumWidth(need)   # and no wider: the row's rest stays empty

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._arrange(self.rows_for(self.width()))


class _StationPanel(RoundedFrame):
    """The station list's card: at least MIN_W wide, and never less than its rows
    need. A plain setMinimumWidth(220) overrode what the tabs and filters need, so the
    window kept the map beside a list squashed to "Favorit" and "Classic…" (the
    map is meant to give way first: RadioTab.fit_steps)."""
    MIN_W = 220

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(max(hint.width(), self.MIN_W), hint.height())


class StationList(QObject):
    """The station list and its filters for one RadioTab (``tab``)."""

    def __init__(self, tab: RadioTab):
        super().__init__(tab)
        self.tab = tab

    # ------------------------------------------------------------------ station panel
    _PANEL_STYLE = Template("""
QFrame#stations { background:$panel; border-radius:12px; }
QFrame#stations QWidget { background:transparent; }
QFrame#stations QComboBox QAbstractItemView, QFrame#stations QComboBoxPrivateContainer,
QFrame#stations QMenu { background:$card; }
QFrame#stations QListWidget { border:none; outline:0; }
QFrame#stations QPushButton#seg { border:none; border-radius:7px; padding:5px 10px;
    min-height:18px; background:transparent; color:$muted; font-weight:600; }
QFrame#stations QPushButton#seg:hover { color:$text_hi; background:$btn_hover; }
QFrame#stations QPushButton#seg:checked { background:$fill; color:$on_accent; }
QFrame#stations QWidget#segbox { background:$segbox; border-radius:9px; }
QFrame#stations QPushButton#genre { border-radius:6px; padding:3px 10px; font-size:8.5pt;
    background:$btn; border:1px solid transparent; color:$text; }
QFrame#stations QPushButton#genre:hover { background:$btn_hover; }
QFrame#stations QPushButton#genre:checked { background:$fill; border-color:$accent;
    color:$on_accent; }
QFrame#stations QComboBox { background:$card_ctl; padding:4px 8px; font-size:9pt; }
QFrame#stations QLabel#count { color:$muted; font-size:8.5pt; }
QFrame#stations QPushButton#clear { border:none; background:transparent; color:$accent_hi;
    font-size:8.5pt; padding:0 2px; }
QFrame#stations QPushButton#clear:hover { text-decoration:underline; }
QFrame#stations QFrame#rule { background:$border; max-height:1px; border:none; }
""")

    def _make_station_panel(self) -> QFrame:
        self.tab.station_panel = panel = _StationPanel()
        panel.setObjectName("stations")
        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 8, 6, 4)
        v.setSpacing(8)

        # Popular | Favorites | Recent
        seg = QWidget()
        seg.setObjectName("segbox")
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        self.tab.btn_popular = QPushButton(_("Popular"))
        self.tab.btn_favs = QPushButton(_("Favorites"))
        icons.set_icon(self.tab.btn_favs, "star", "muted")
        self.tab.btn_recent = QPushButton(_("Recent"))
        self.tab._mode = QButtonGroup(self.tab)
        for b in (self.tab.btn_popular, self.tab.btn_favs, self.tab.btn_recent):
            b.setObjectName("seg")
            b.setAccessibleName(b.text())    # kept when the fitter drops the words
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tab._mode.addButton(b)
            sh.addWidget(b)
        self.tab.btn_popular.setChecked(True)
        self.tab._mode.buttonClicked.connect(lambda _b: self._show_list())
        self.tab.seg_box = seg
        # as wide as its words
        seg.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        v.addWidget(seg)

        # genre chips
        self.tab.genre_box = QWidget()
        self.tab.genre_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        flow = _Flow(self.tab.genre_box, gap=5)
        self.tab._genres = QButtonGroup(self.tab)
        self.tab._genre_btns = {}
        for g in ("", *(name for name, _words in GENRES)):
            b = QPushButton((GENRE_LABELS.get(g, g) if g else _("All")).replace("&", "&&"))
            b.setObjectName("genre")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(not g)
            b.clicked.connect(lambda _c=False, g=g: self.set_genre(g))
            self.tab._genres.addButton(b)
            self.tab._genre_btns[g] = b
            flow.addWidget(b)
        v.addWidget(self.tab.genre_box)

        # country | quality | sort, then "312 of 3,000 stations"  ·  Clear filters
        self.tab.filter_box = QWidget()
        fv = QVBoxLayout(self.tab.filter_box)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(8)
        self.tab.cmb_country = QComboBox()
        self.tab.cmb_country.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.tab.cmb_country.setMinimumContentsLength(8)
        self.tab.cmb_country.addItem(_("All countries"), "")
        self.tab.cmb_country.setAccessibleName(_("Country"))
        self.tab.cmb_country.activated.connect(
            lambda _i: self.set_country(self.tab.cmb_country.currentData() or ""))
        self.tab.cmb_quality = QComboBox()
        self.tab.cmb_quality.setToolTip(_("Only stations streaming at least this bitrate"))
        self.tab.cmb_quality.setAccessibleName(_("Quality"))
        for label, kbps in QUALITIES:
            self.tab.cmb_quality.addItem(label, kbps)
        self.tab.cmb_quality.activated.connect(lambda _i: self._on_filter())
        self.tab.cmb_sort = QComboBox()
        self.tab.cmb_sort.setAccessibleName(_("Sort by"))
        for label, _key in SORTS:
            self.tab.cmb_sort.addItem(label)
        self.tab.cmb_sort.activated.connect(lambda _i: self._show_list())
        self.tab.filter_row = _FilterRow([self.tab.cmb_country, self.tab.cmb_quality,
                                          self.tab.cmb_sort])
        fv.addWidget(self.tab.filter_row)
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 4, 0)
        self.tab.count_label = QLabel()
        self.tab.count_label.setObjectName("count")
        row.addWidget(self.tab.count_label, 1)
        self.tab.btn_clear = QPushButton(_("Clear filters"))
        self.tab.btn_clear.setObjectName("clear")
        self.tab.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab.btn_clear.clicked.connect(self.clear_filters)
        self.tab.btn_clear.hide()
        row.addWidget(self.tab.btn_clear)
        fv.addLayout(row)
        v.addWidget(self.tab.filter_box)
        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        v.addWidget(rule)

        self.tab.list = EmptyList(icon="radio")   # says why it's empty, centred (_show_list)
        self.tab.list.setAccessibleName(_("Stations"))
        self.tab.list.setMinimumSize(160, 48)
        self.tab.list.setUniformItemSizes(True)
        self.tab.list.setWordWrap(False)
        self.tab.list.setMouseTracking(True)
        self.tab.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.tab.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tab.list.setItemDelegate(_StationDelegate(self.tab))
        self.tab.list.itemActivated.connect(self.tab._on_activated)          # double-click / Enter
        self.tab.list.currentItemChanged.connect(self.tab._on_current)
        v.addWidget(self.tab.list, 1)
        self._style_panel()
        return panel

    def _style_panel(self):
        self.tab.station_panel.setStyleSheet(self._PANEL_STYLE.substitute(
                                            theme.T, fill=theme.accent_fill())
                                        + theme.texture_style("QFrame#stations"))

    # -- filters
    def set_genre(self, genre: str):
        self.tab._genre = genre if genre in _GENRE_WORDS else ""
        self.tab._genre_btns[self.tab._genre].setChecked(True)
        self._on_filter()

    def set_country(self, country: str):
        self.tab._country = country
        self._on_filter()

    def _min_kbps(self) -> int:
        return int(self.tab.cmb_quality.currentData() or 0)

    def filters_on(self) -> bool:
        return bool(self.tab._genre or self.tab._country or self._min_kbps())

    def clear_filters(self):
        self.tab._genre, self.tab._country = "", ""
        self.tab._genre_btns[""].setChecked(True)
        self.tab.cmb_quality.setCurrentIndex(0)
        self._on_filter()

    def _on_filter(self):
        self._show_list()
        self.tab._push_globe()

    def _filtered(self, stations: list[Station], country: bool = True) -> list[Station]:
        kbps = self._min_kbps()
        words = _GENRE_WORDS.get(self.tab._genre)
        place = self.tab._country if country else ""
        if not (words or place or kbps):
            return list(stations)
        return [s for s in stations
                if (not words or any(w in s.genre_hay for w in words))
                and (not place or _country(s) == place)
                and (not kbps or s.bitrate >= kbps)]

    def _popular_filtered(self, country: bool = True) -> list[Station]:
        """_filtered(self.tab._globe_list): the genre and quality pass is done once per
        filter choice and kept (read it, don't change it); the country is picked out of
        that (cheap)."""
        if self.tab._popular_of is not self.tab._globe_list:   # a new list: nothing kept is true
            self.tab._popular_of = self.tab._globe_list
            self.tab._popular_cache.clear()
        key = (self.tab._genre, self._min_kbps())
        got = self.tab._popular_cache.pop(key, None)
        if got is None:
            got = self._filtered(self.tab._globe_list, country=False)
        self.tab._popular_cache[key] = got
        while len(self.tab._popular_cache) > MAP_CACHE:
            self.tab._popular_cache.pop(next(iter(self.tab._popular_cache)))
        if country and self.tab._country:
            return [s for s in got if _country(s) == self.tab._country]
        return got

    def _popular_showing(self) -> bool:
        return not (self.tab._query or self.tab.btn_favs.isChecked()
                    or self.tab.btn_recent.isChecked())

    def _source(self) -> list[Station]:
        """The list before filters: search results, favourites, recent or popular."""
        if self.tab._query:
            local = self.tab._local_matches()
            if self.tab._results is None:
                return local
            ids = {s.uuid for s in self.tab._results}
            return sorted(self.tab._results + [s for s in local if s.uuid not in ids],
                          key=lambda s: -s.clicks)
        if self.tab.btn_favs.isChecked():
            return list(self.tab.favorites)
        if self.tab.btn_recent.isChecked():
            return list(self.tab.recent)
        return list(self.tab._globe_list)

    def _fill_countries(self, others: list[Station]):
        """The country menu: how many of `others` (the stations with the other filters
        already on) each country has."""
        counts: dict[str, int] = {}
        for s in others:
            c = _country(s)
            if c:
                counts[c] = counts.get(c, 0) + 1
        if self.tab._country and self.tab._country not in counts:
            counts[self.tab._country] = 0          # keep the chosen one listed
        rows = tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower())))
        cmb = self.tab.cmb_country
        cmb.blockSignals(True)
        if rows != self.tab._countries_shown:   # the same counts: the menu is already right
            self.tab._countries_shown = rows
            cmb.clear()
            cmb.addItem(_("All countries"), "")
            for c, n in rows:
                cmb.addItem(f"{c}  ({n:,})", c)
        cmb.setCurrentIndex(max(0, cmb.findData(self.tab._country)))
        cmb.blockSignals(False)

    def visible_stations(self) -> list[Station]:
        return self._sorted(self._filtered(self._source()))

    def _sorted(self, stations: list[Station]) -> list[Station]:
        key = SORTS[max(0, self.tab.cmb_sort.currentIndex())][1]
        return sorted(stations, key=key) if key else stations

    def _show_list(self):
        self.tab._type_timer.stop()    # whatever was typed is in this one
        source = self._source()    # once: a search goes through every known station
        others = (self._popular_filtered(country=False) if self._popular_showing()
                  else self._filtered(source, country=False))
        self._fill_countries(others)
        every = self._sorted([s for s in others if _country(s) == self.tab._country]
                             if self.tab._country else others)
        stations = every[:LIST_MAX]
        n, total = len(every), len(source)
        if n != total:
            count = ngettext("{n} of {total} station", "{n} of {total} stations", total,
                             n=f"{n:,}", total=f"{total:,}")
        elif n > LIST_MAX:
            count = ngettext("{n} station (top {shown} shown)", "{n} stations (top {shown} shown)",
                             n, n=f"{n:,}", shown=LIST_MAX)
        else:
            count = ngettext("{n} station", "{n} stations", n, n=f"{n:,}")
        if not total and self._popular_showing() and not self.tab._globe_error:
            count = ""   # still on its way: the list says so, "0 stations" would be wrong
        self.tab.count_label.setText(count)
        self.tab.btn_clear.setVisible(self.filters_on())
        cur = self.tab.list.currentItem()
        keep = cur.data(Qt.ItemDataRole.UserRole) if cur is not None else None
        playing = self.tab.player.station.uuid if self.tab.player.station else None
        self.tab._rows_playing = playing
        fav = self.tab._fav_ids
        self.tab.list.blockSignals(True)
        self.tab.list.clear()
        for s in stations:
            it = QListWidgetItem(self._row_text(s, playing, fav))
            it.setData(Qt.ItemDataRole.UserRole, s.uuid)
            # station data is community-edited: escape it, or Qt renders it as HTML
            it.setToolTip(f"<p>{html.escape(s.name)}"
                          + (f"<br>{html.escape(s.homepage)}" if s.homepage else "") + "</p>")
            if s.uuid == playing:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.tab.list.addItem(it)
            if s.uuid == keep:
                self.tab.list.setCurrentItem(it)
        self.tab.list.blockSignals(False)
        if not stations:
            if self.tab._query:
                empty = (_("Searching…") if self.tab._results is None else
                         _("Search failed: press Enter to try again.") if self.tab._search_failed
                         else _("No stations found."))
            elif source and self.filters_on():
                empty = _("No stations match these filters.\nTry another genre or country.")
            elif self.tab.btn_favs.isChecked():
                empty = _("No favorites yet.\nHover a station and click its ☆ to keep it "
                          "here.")
            elif self.tab.btn_recent.isChecked():
                empty = _("Nothing played yet.\nStations you listen to show up here.")
            else:
                empty = self.tab._no_stations_text()
            self.tab.list.set_empty(empty)
        self.tab._update_buttons()

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
        playing = self.tab.player.station.uuid if self.tab.player.station else None
        fav = self.tab._fav_ids
        todo = {self.tab._rows_playing, playing, *changed} - {None}
        self.tab._rows_playing = playing
        for i in range(self.tab.list.count() if todo else 0):
            it = self.tab.list.item(i)
            uuid = it.data(Qt.ItemDataRole.UserRole)
            s = self.tab._stations.get(uuid) if uuid in todo else None
            if s is None:
                continue
            text = self._row_text(s, playing, fav)
            if it.text() != text:
                it.setText(text)
            if it.font().bold() != (s.uuid == playing):
                f = it.font()
                f.setBold(s.uuid == playing)
                it.setFont(f)
        self.tab.list.viewport().update()
        self.tab._update_buttons()

    def _highlight(self, uuid: str):
        for i in range(self.tab.list.count()):
            it = self.tab.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == uuid:
                self.tab.list.setCurrentItem(it)
                self.tab.list.scrollToItem(it)
                return
