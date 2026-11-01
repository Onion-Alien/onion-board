"""Settings → Appearance: themes, texture, size, language and the highlight colour."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QDate, QLocale, QPointF, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QRadioButton,
                               QSizePolicy, QSlider, QVBoxLayout, QWidget)

from soundboard import i18n
from soundboard.core import achievements
from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.ui.kit import busy
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.settings import Page, _button_row
from soundboard.ui.kit.wheelguard import no_wheel


_tiles: dict[str, QBrush | None] = {}


def _tile(name: str) -> QBrush | None:
    """A theme's texture as a brush for its preview card (None: the theme has none)."""
    if name not in _tiles:
        kind = theme.THEMES[name].get("texture", "")
        _tiles[name] = (QBrush(QPixmap.fromImage(theme.texture_image(kind, theme.THEMES[name])))
                        if kind in theme.TEXTURES else None)
    return _tiles[name]


_buns: dict[tuple[str, float], QPixmap] = {}
BUN_H = 58   # Bun's height on a theme card


def _bun(name: str, dpr: float) -> QPixmap:
    """Bun as he looks in theme `name` (its headphones, outfit and look), for its card,
    with room above and beside him (bunny.bunny_image) so nothing on him is cut off."""
    key = (name, dpr)
    if key not in _buns:
        from soundboard.ui.bun.bunny import bunny_pixmap
        with theme.previewing(name):
            _buns[key] = bunny_pixmap(BUN_H, dpr=dpr)
    return _buns[key]


WAVE_S = 1.7   # his hello when the mouse comes onto a card, seconds


def wave_pose(t: float) -> dict | None:
    """Bun's hello `t` seconds after the mouse came onto his card (None: done): a little
    hop, then three waves of his paw with a happy face."""
    if not 0 <= t < WAVE_S:
        return None
    k = min(1.0, t / 0.2, (WAVE_S - t) / 0.2)   # (the paw swings in and out softly)
    happy = 0.35 <= t < 1.3
    return {"hop": 3.5 * math.sin(math.pi * t / 0.3) if t < 0.3 else 0.0,
            "wave": k * math.sin(2 * math.pi * 1.9 * (t - 0.15)),
            "blink": 1.0 if happy else 0.0, "mouth": 0.4 if happy else 0.0}


def limited_tip(name: str) -> str:
    """A limited-edition theme card's tooltip: until when it can be had, or that it's kept."""
    if name in theme.kept:
        return _("Limited edition: this one's yours to keep.")
    last = theme.LIMITED[name]
    day = QLocale().toString(QDate(last.year, last.month, last.day), "d MMMM")
    return _("Limited edition: use it by {date} and it's yours to keep. After that it's "
             "gone for good.", date=day)


def paint_limited_tag(p: QPainter, x: float, y: float, font: QFont, max_w: float) -> None:
    """The "Limited edition" tag: a glowing pumpkin-to-purple ribbon with a sparkle,
    its top-left corner at (x, y), no wider than `max_w`."""
    text = _("Limited edition")
    f = QFont(font)
    f.setFamily(theme.FONT)
    f.setBold(True)
    f.setPointSizeF(6.8)
    fm = QFontMetricsF(f)
    star = 9.0
    pad = 6.0
    text = fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w - 2 * pad - star - 3)
    w = min(max_w, 2 * pad + star + 3 + fm.horizontalAdvance(text))
    h = 16.0
    tag = QRectF(x, y, w, h)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    for grow, alpha in ((3.0, 40), (1.5, 70)):   # its glow
        p.setBrush(QColor(255, 117, 24, alpha))
        p.drawRoundedRect(tag.adjusted(-grow, -grow, grow, grow), h / 2 + grow, h / 2 + grow)
    fill = QLinearGradient(tag.topLeft(), tag.topRight())
    fill.setColorAt(0, QColor("#ff7518"))
    fill.setColorAt(0.55, QColor("#e0469a"))
    fill.setColorAt(1, QColor("#8f3ff0"))
    p.setBrush(fill)
    p.setPen(QPen(QColor(255, 255, 255, 120), 1))
    p.drawRoundedRect(tag, h / 2, h / 2)
    shine = QLinearGradient(tag.topLeft(), tag.bottomLeft())   # glossy top half
    shine.setColorAt(0, QColor(255, 255, 255, 90))
    shine.setColorAt(0.5, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(shine)
    p.drawRoundedRect(tag.adjusted(1, 1, -1, -h / 2), h / 2 - 1, h / 2 - 1)
    cx, cy, r = x + pad + star / 2, y + h / 2, star / 2   # a four-point sparkle
    spark = QPainterPath(QPointF(cx, cy - r))
    for px, py in ((cx + r * 0.28, cy - r * 0.28), (cx + r, cy), (cx + r * 0.28, cy + r * 0.28),
                   (cx, cy + r), (cx - r * 0.28, cy + r * 0.28), (cx - r, cy),
                   (cx - r * 0.28, cy - r * 0.28), (cx, cy - r)):
        spark.lineTo(QPointF(px, py))
    p.setBrush(QColor("#fff3b0"))
    p.drawPath(spark)
    p.setFont(f)
    p.setPen(QColor(0, 0, 0, 90))   # a soft drop shadow under the white text
    text_at = QRectF(x + pad + star + 3, y, w, h)
    p.drawText(text_at.translated(0, 1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               text)
    p.setPen(QColor("#ffffff"))
    p.drawText(text_at, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    p.restore()


class ThemeCard(QPushButton):
    """A clickable mini-preview of a theme: its colours, and with Textured on, its
    pattern on the panels and its glow behind them, so the switch shows what it does.
    Bun stands in its corner dressed for the theme."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.setObjectName("themecard")
        self.setAccessibleName(name)   # it draws its name: a screen reader had nothing to say
        if name in theme.LIMITED:
            self.setToolTip(limited_tip(name))
            self.setAccessibleDescription(limited_tip(name))   # until when, or kept
        self.setCheckable(True)
        self.setFixedSize(QSize(150, 112))   # (ThemeGrid widens it to fill its column)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hello = None   # when Bun started waving (time.monotonic), None: he isn't
        self._tick = QTimer(self)
        self._tick.setInterval(1000 // 24)
        self._tick.timeout.connect(self._step)

    def enterEvent(self, e):
        super().enterEvent(e)
        # Lite mode only, like Bun's other moves when stirred: Windows' Animation effects
        # (toast.animations_on) is off on many PCs, and there he never waved
        from soundboard.ui.settings import lite
        if self._hello is None and not lite.on():   # (once per visit: no restart)
            self._hello = time.monotonic()
            self._tick.start()

    def _step(self):
        if self._hello is not None and wave_pose(time.monotonic() - self._hello) is None:
            self._hello = None
            self._tick.stop()
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)   # frame + checked border from the stylesheet
        t = theme.THEMES[self.name]
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -30)
        win = QPainterPath()
        win.addRoundedRect(r, 8, 8)
        p.fillPath(win, QColor(t["bg"]))
        tile = _tile(self.name) if theme.textures_on else None
        if theme.textures_on:
            p.save()
            p.setClipPath(win)
            theme.paint_window_bg(p, r, r.topLeft(), r.width(), r.height(), tk=t)
            p.restore()
        # side panel, pads and a slider, in the theme's own colours
        p.setPen(Qt.PenStyle.NoPen)
        for brush in (QColor(t["panel"]), tile):
            if brush is not None:
                p.setBrush(brush)
                p.drawRoundedRect(QRectF(r.right() - 44, r.top() + 6, 38, r.height() - 12), 5, 5)
        # two columns of pads across what the side panel leaves (a wider card: wider pads)
        pw = max(40.0, (r.width() - 44 - 7 - 6 - 4) / 2)   # (40: the old fixed size)
        for i, col in enumerate(("#7c5cff", "#ff5c8a", "#1fb6ff", "#13ce66")):
            x = r.left() + 7 + (i % 2) * (pw + 4)
            y = r.top() + 7 + (i // 2) * 34
            for brush in (QColor(t["card"]), tile):
                if brush is not None:
                    p.setBrush(brush)
                    p.drawRoundedRect(QRectF(x, y, pw, 28), 5, 5)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x + 5, y + 5, 10, 3), 1.5, 1.5)
        # Bun on the side panel, standing at its foot: the theme's headphones, outfit
        # and look, so you can see who you'd get
        bun = _bun(self.name, self.devicePixelRatioF() or 1.0)
        bw, bh = bun.width() / bun.devicePixelRatio(), bun.height() / bun.devicePixelRatio()
        spot = QRectF(r.right() - 3 - bw, r.bottom() - 1 - BUN_H, bw, BUN_H)
        pose = wave_pose(time.monotonic() - self._hello) if self._hello is not None else None
        if pose is None:
            p.drawPixmap(QRectF(spot.left(), spot.bottom() - bh, bw, bh), bun, QRectF(bun.rect()))
        else:   # saying hello: drawn live in his theme
            from soundboard.ui.bun.bunny import draw_bunny
            with theme.previewing(self.name):
                draw_bunny(p, spot.translated(0, -pose.pop("hop")), **pose)
        # name, in the theme's own font
        p.setPen(QColor(theme.T["text"]))
        f = QFont(self.font())
        f.setFamily(t.get("font", theme.FONT))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, self.height() - 28, self.width() - 20, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.name)
        if self.name in theme.LIMITED:   # just inside the preview's top-left corner
            paint_limited_tag(p, r.left() + 5, r.top() + 5, self.font(), r.width() - 10)
        p.end()


class ThemeGrid(QWidget):
    """Keep previews their readable size, using as many columns as fit (at most
    `max_columns`: the setup guide's rows are picked to be three across)."""

    def __init__(self, cards, max_columns: int = 0):
        super().__init__()
        self.cards = cards
        self.max_columns = max_columns
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._reflow(1)

    def minimumSizeHint(self):
        return QSize(150, 112)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # as many columns as fit, even past this group's cards: every group then gets
        # the same columns and gaps and they line up (a short group spread its few
        # cards over the whole width, out of line with the groups above and below)
        columns = max(1, (self.width() + 12) // 162)
        if self.max_columns:
            columns = min(columns, self.max_columns)
        self._reflow(columns)
        # the cards widen to share the width left over, first on the left edge and a full
        # row's last on the right, with the same 12 px gap across as down (sharing it out
        # as gaps instead left ~70 px between cards beside 12 px between rows)
        width = max(150, (self.width() - 12 * (columns - 1)) // columns)
        for card in self.cards:
            card.setFixedWidth(width)
        self.grid.setHorizontalSpacing(12)

    def _reflow(self, columns):
        if columns == self.columns:
            return
        for col in range(self.columns + 1):
            self.grid.setColumnStretch(col, 0)
        from soundboard.ui.kit.widgets import take_out  # (it imports this module)
        while self.grid.count():
            take_out(self.grid)
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // columns, i % columns, Qt.AlignmentFlag.AlignLeft)
        self.grid.setColumnStretch(columns, 1)
        self.columns = columns
        self.updateGeometry()


class AppearancePage(Page):
    """Settings → Appearance: themes, texture, size, language and the highlight colour."""

    def _appearance(self):
        """Language on its own, then one box for the look with two tabs: Themes (Textured
        or Plain on top, then the cards) and Look (highlight colour, size, live tabs and
        background, one under another). One after another the page ran so long that some
        people never scrolled down to the themes; six tabs of an option or two each were
        a lot of clicking for little."""
        w, v = self._page()
        self.dlg.theme_cards = []
        v.addWidget(self._language_card())
        hints = {"Classic": _("Changes the whole app instantly."),
                 "Meme": _("For when you want your soundboard to be a bit.")}
        themes, tv = self._card(_("Themes"), icon="palette")
        tv.setSpacing(6)
        tv.addWidget(self._section(self._texture_card()))
        tv.addSpacing(14)
        from soundboard.ui.kit.panel import heading_row
        group_icons = {"Classic": "star", "Colourful": "palette", "Wild": "shuffle",
                       "Meme": "like"}
        for group, names in theme.groups():
            head, _title, _marks = heading_row(theme.group_name(group),
                                               group_icons.get(group, ""))
            tv.addLayout(head)
            if group in hints:
                h = QLabel(hints[group])
                h.setObjectName("hint")
                h.setWordWrap(True)
                tv.addWidget(h)
                tv.addSpacing(10)   # (the cards sat right under it)
            cards = []
            for name in names:
                c = ThemeCard(name)
                c.setChecked(name == theme.current_name)
                c.clicked.connect(lambda __=False, n=name: self._pick_theme(n))
                cards.append(c)
                self.dlg.theme_cards.append(c)
            tv.addWidget(ThemeGrid(cards))
            tv.addSpacing(8)
        look, lv = self._card(_("Look"), icon="image")
        lv.setSpacing(6)
        groups = ((_("Colour"), (self._highlight_card(), self._live_tabs_card())),
                  (_("Size"), (self._ui_scale_card(),)),
                  (_("Background"), (self._playing_background_card(),)))
        for i, (name, parts) in enumerate(groups):
            if i:
                lv.addSpacing(10)
            lv.addWidget(self._group(name, parts))
        v.addWidget(self._look_box([(_("Themes"), themes), (_("Look"), look)]))
        v.addStretch(1)
        return w

    @staticmethod
    def _section(card: QFrame) -> QFrame:
        """Settings card `card` as a part of a look tab: flat, its title a heading."""
        card.setObjectName("lookpage")
        if (lay := card.layout()) is not None:
            lay.setContentsMargins(0, 0, 0, 0)
        return card

    def _group(self, name: str, parts) -> QWidget:
        """A muted group label over a soft box holding `parts` (look tab sections), a thin
        line between them: the Look tab's five settings read as three small groups,
        not one long list of headings."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        label = QLabel(name)
        label.setObjectName("hint")
        v.addWidget(label)
        box = QFrame()
        box.setObjectName("lookgroup")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 14)
        bv.setSpacing(12)
        for i, part in enumerate(parts):
            if i:
                rule = QFrame()
                rule.setObjectName("lookrule")
                rule.setFixedHeight(1)
                bv.addWidget(rule)
            bv.addWidget(self._section(part))
        v.addWidget(box)
        return w

    def _look_box(self, pages) -> QFrame:
        """One card holding `pages` [(tab name, card)], a tab row on top showing one at a
        time (the others hidden, so the box is only as tall as the one showing). To
        search it is one card; a search lands on the tab with the words."""
        box = QFrame()
        box.setObjectName("setcard")
        theme.vary_texture(box)
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 14)
        bv.setSpacing(10)
        row = _button_row()
        bv.addLayout(row)
        group = QButtonGroup(box)
        tabs = []
        from soundboard.ui.kit.widgets import widget_at  # (it imports this module)
        for i, (name, card) in enumerate(pages):
            card.setObjectName("lookpage")   # not a card of its own: flat inside the box
            lay = card.layout()
            lay.setContentsMargins(0, 0, 0, 0)
            title = widget_at(lay, 0)
            assert title is not None
            title.hide()   # its title: the tab says it (search still reads it)
            b = QPushButton(name)
            b.setObjectName("voicetab")    # the same tabs as the voice changer's
            b.setCheckable(True)
            group.addButton(b, i)
            row.addWidget(b)
            bv.addWidget(card)
            tabs.append(b)
        dlg = self.dlg
        dlg.look_shown = 0   # the tab showing

        def show(i):
            tabs[i].setChecked(True)
            for j, (__, card) in enumerate(pages):
                card.setVisible(j == i)
            dlg.look_shown = i
        group.idClicked.connect(show)
        show(0)

        def pick(words):
            for i, (name, card) in enumerate(pages):
                if all(wd in name.lower() or wd in dlg._words_of(card) for wd in words):
                    show(i)
                    return
        dlg._look_pick = pick
        dlg.look_tabs, dlg.look_pages, dlg.look_box = tabs, [c for __, c in pages], box
        return box

    def _live_tabs_card(self) -> QFrame:
        card, cv = self._card(_("Live tabs"),
                              _("Marks a tab whose feature is on, so nothing is left on "
                                "without you noticing."), icon="live")
        # side by side like Connection's and Network activity's choices (DESIGN section 0:
        # comparable short choices look alike); they wrap when Settings is narrow
        row = _button_row()
        green = QRadioButton(_("A bar beside the tab"))
        green.setToolTip(_("A bar at the edge of the tabs and a coloured icon, in the highlight "
                           "colour: easy to spot from across the room"))
        dot = QRadioButton(_("A small dot on its icon"))
        dot.setToolTip(_("Quieter: only a dot on the tab's icon"))
        modes = QButtonGroup(card)
        for b in (dot, green):
            modes.addButton(b)
            row.addWidget(b)
        (green if self.mw.cfg.live_tab_green else dot).setChecked(True)
        green.toggled.connect(self.mw.themectl.set_live_tab_tint)
        self.dlg.live_green, self.dlg.live_dot = green, dot
        cv.addLayout(row)
        return card

    def _texture_card(self) -> QFrame:
        """Textured or Plain: each theme's own pattern on its panels, or flat panels."""
        card, cv = self._card(_("Theme style"),
                              _("Textured gives each theme its own pattern on the panels: "
                                "scanlines, carbon fibre, waves and more. Plain keeps them flat."),
                              icon="image")
        row = _button_row()
        textured = QRadioButton(_("Textured"))
        plain = QRadioButton(_("Plain"))
        group = QButtonGroup(card)
        for b in (textured, plain):
            group.addButton(b)
            row.addWidget(b)
        (textured if self.mw.cfg.theme_texture else plain).setChecked(True)
        textured.toggled.connect(self.mw.themectl.set_theme_texture)
        self.dlg.texture_on, self.dlg.texture_off = textured, plain
        cv.addLayout(row)
        return card

    def _ui_scale_card(self) -> QFrame:
        """Interface size: everything bigger or smaller, on top of Windows' display
        scaling. Qt sizes the app only as it starts (app.ui_scale_startup), so a new
        size offers a restart, like the language."""
        import os
        from soundboard.sounds.library import UI_SCALES
        now = round(float(os.environ.get("QT_SCALE_FACTOR") or 1) * 100)
        combo = QComboBox()
        combo.setAccessibleName(_("Interface size"))
        combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)   # (not the row)
        for pct in UI_SCALES:
            combo.addItem(_("{percent}%", percent=pct), pct)
        combo.setCurrentIndex(max(0, combo.findData(self.mw.cfg.ui_scale)))
        no_wheel(combo)
        card, cv = self._card(_("Interface size"),
                              _("Makes everything in Onion Board bigger or smaller: text, "
                                "buttons and pads."), icon="expand", end=(combo,))
        restart = QPushButton(_("Restart now"))
        restart.clicked.connect(self.mw.restart_app)
        note = QLabel(_("Onion Board changes size after a restart."))
        note.setObjectName("hint")
        note.setWordWrap(True)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(note, 1)
        row.addWidget(restart)
        cv.addLayout(row)

        def show():
            later = self.mw.cfg.ui_scale != now
            note.setVisible(later)
            restart.setVisible(later)

        def picked(i):
            if i == combo.count() - 1:   # the biggest (Big Picture)
                achievements.at_least("big_ui", 1)
            self.mw.cfg.ui_scale = combo.itemData(i)
            self.mw._save_later()
            show()
        combo.currentIndexChanged.connect(picked)
        show()
        (self.dlg.ui_scale_combo, self.dlg.ui_scale_note,
         self.dlg.ui_scale_restart) = combo, note, restart
        return card

    def _playing_background_card(self) -> QFrame:
        enabled = QCheckBox(_("On"))
        enabled.setAccessibleName(_("Playing sound background"))
        enabled.setChecked(self.mw.cfg.playing_background)
        enabled.toggled.connect(lambda on: self.mw.set_option("playing_background", on))
        card, cv = self._card(_("Playing sound background"),
                              _("Show the playing sound's thumbnail behind the cards"), icon="wave",
                              end=(enabled,))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel(_("Opacity")))
        opacity = QSlider(Qt.Orientation.Horizontal)
        opacity.setRange(0, 100)
        opacity.setValue(self.mw.cfg.playing_background_opacity)
        opacity.setAccessibleName(_("Opacity"))
        no_wheel(opacity)
        value = QLabel(f"{opacity.value()}%")
        value.setMinimumWidth(value.fontMetrics().horizontalAdvance("100%"))
        opacity.valueChanged.connect(lambda n: (
            value.setText(f"{n}%"), self.mw.set_option("playing_background_opacity", n)))
        opacity.setEnabled(enabled.isChecked())
        enabled.toggled.connect(opacity.setEnabled)
        row.addWidget(opacity, 1)
        row.addWidget(value)
        cv.addLayout(row)
        self.dlg.playing_background_check, self.dlg.playing_background_opacity = enabled, opacity
        return card

    def _language_card(self) -> QFrame:
        """The app's language: a button showing the one picked (its letter coin and
        name), opening a drop-down of languages with a search (ui.langpick). The title
        is in Windows' language too, so someone who can't read this page still finds
        it; what it says about restarting is in the language picked."""
        title = _("Language")
        other = i18n.offer()
        if other:
            word = i18n.in_language(other, lambda: _("Language"))
            title = title if word == title else f"{title} · {word}"
        card, cv = self._card(title, icon="browser")
        from soundboard.ui.settings.langpick import LangButton
        pick = LangButton()
        pick.setAccessibleName(_("Language"))
        pick.setToolTip(_("Pick the language Onion Board is shown in"))
        restart = QPushButton()
        restart.clicked.connect(self.mw.restart_app)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(pick)
        row.addWidget(restart)
        row.addStretch(1)   # buttons as wide as their text, not the card
        cv.addLayout(row)
        note = QLabel()
        note.setObjectName("hint")
        note.setWordWrap(True)
        cv.addWidget(note)
        langs = dict(i18n.available())

        def chosen() -> str:
            c = self.mw.cfg.language
            return c if c in langs else i18n.current()

        def show():
            code = chosen()
            pick.show_language(code, langs.get(code, code))
            later = code != i18n.current()
            if later:
                text, button = i18n.in_language(code, lambda: (
                    _("Onion Board shows {name} after a restart.", name=i18n.name_of(code)),
                    _("Restart now")))
                note.setText("‏" + text if i18n.is_rtl(code) else text)   # (RLM: see
                # LanguageControl._offer_language)
                restart.setText(button)
                note.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl(code)
                                        else Qt.LayoutDirection.LeftToRight)
            note.setVisible(later)
            restart.setVisible(later)

        def open_picker():
            from soundboard.ui.settings.langpick import LanguageDialog
            if self.dlg.lang_dialog is not None and self.dlg.lang_dialog.isVisible():
                return
            dlg = LanguageDialog(self.dlg, chosen())
            self.dlg.lang_dialog = dlg   # (tests reach it while it's open)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dlg.chosen.connect(lambda code: (
                self.mw.langctl.switch_language(code, restart=False), show()))
            dlg.destroyed.connect(lambda *__: setattr(self.dlg, "lang_dialog", None))
            dlg.open_under(pick)   # a drop-down, not a window: nothing waits on it
        pick.clicked.connect(open_picker)
        show()
        self.dlg.lang_button, self.dlg.lang_note, self.dlg.lang_restart = pick, note, restart
        self.dlg.lang_dialog = None
        return card

    def _highlight_card(self) -> QFrame:
        """Your own colour for what's on right now (the voice changer, Live, a live tab),
        kept whatever the theme: for when you like a theme but not its colour."""
        card, cv = self._card(_("Highlight colour"),
                              _("What's switched on is shown in this colour. Slide to pick "
                                "your own; it stays when you change theme."), icon="edit")
        row = QHBoxLayout()
        row.setSpacing(10)
        swatch = QPushButton(_("On"))   # a switched-on button, as it will look
        swatch.setObjectName("power")
        swatch.setCheckable(True)
        swatch.setChecked(True)
        swatch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        swatch.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        swatch.setFixedWidth(64)
        swatch.setAccessibleName(_("Highlight colour preview"))
        hue = QSlider(Qt.Orientation.Horizontal)
        hue.setObjectName("hue")
        hue.setRange(0, 359)
        hue.setAccessibleName(_("Highlight colour hue"))
        hue.setToolTip(_("Drag along the rainbow to pick the highlight colour"))
        no_wheel(hue)
        row.addWidget(swatch)
        row.addWidget(hue, 1)
        cv.addLayout(row)
        btns = _button_row()   # (one under the other in a narrow window: no clipping)
        more = QPushButton(_("More colours"))
        more.setToolTip(_("Pick any colour, including how strong and how bright it is"))
        reset = QPushButton(_("Theme's colour"))
        reset.setToolTip(_("Go back to each theme's own highlight colour"))
        btns.addWidget(reset)
        btns.addWidget(more)
        cv.addLayout(btns)
        now = QLabel()
        now.setObjectName("hint")
        now.setWordWrap(True)
        cv.addWidget(now)
        (self.dlg.hue_slider, self.dlg.hue_swatch, self.dlg.hue_reset,
         self.dlg.hue_now) = hue, swatch, reset, now
        # arrow keys / clicks on the strip come in bursts: apply once they stop
        settle = QTimer(card, singleShot=True, interval=250)
        self.dlg.hue_settle = settle

        def own(h: int) -> str:
            """Hue `h` at the strength / brightness of the current colour (a vivid one
            when it's too grey for a hue to show)."""
            c = QColor(theme.T["live"])
            sat, val = c.hsvSaturationF(), c.valueF()
            if sat < 0.35 or val < 0.45:
                sat, val = 0.75, 0.95
            return QColor.fromHsvF(h / 360, sat, val).name()

        def preview(colour: str = ""):
            """Show `colour` on the swatch only (while dragging); "" = what's applied."""
            if colour:
                on = max(("#ffffff", "#111111"), key=lambda c: theme._contrast(c, colour))
                swatch.setStyleSheet(f"QPushButton#power:checked {{ background:{colour}; "
                                     f"border:1px solid {colour}; color:{on}; }}")
            else:
                swatch.setStyleSheet(theme.live_sheet())

        def sync():
            hue.blockSignals(True)
            h = QColor(theme.T["live"]).hsvHue()
            hue.setValue(h if h >= 0 else 0)
            hue.blockSignals(False)
            now.setText(_("Now: your own colour, in every theme.")
                        if theme.live_override else
                        _("Now: {theme}'s own colour.", theme=theme.current_name))
            preview()

        def use(colour: str, btn=None, done: str = "") -> bool:
            settle.stop()
            changed = self.mw.themectl.set_live_color(colour)
            sync()
            if btn is not None and done:
                busy.flash(btn, done)
            return changed

        def moved(h: int):
            preview(own(h))
            if not hue.isSliderDown():
                settle.start()
        hue.valueChanged.connect(moved)
        hue.sliderReleased.connect(lambda: use(own(hue.value())))
        settle.timeout.connect(lambda: use(own(hue.value())))

        def pick():
            c = QColorDialog.getColor(QColor(theme.T["live"]), self.dlg, _("Highlight colour"))
            if c.isValid():
                use(c.name(), more, _("✓ Changed"))

        def back():
            if not theme.live_override:
                busy.flash(reset, _("✓ Already the theme's"))
            else:
                use("", reset, _("✓ Back to the theme's"))
        more.clicked.connect(pick)
        reset.clicked.connect(back)
        self.dlg._sync_highlight = sync
        sync()
        return card

    def _pick_theme(self, name: str):
        if name == theme.current_name:   # already on: restyling every widget again froze
            for c in self.dlg.theme_cards:   # the app for nothing (a click unticks the card)
                c.setChecked(c.name == name)
            return
        for c in self.dlg.theme_cards:   # ticked before the restyle: the fade's picture
            c.setChecked(c.name == name)   # of the new look has the right card ringed
        self.mw.themectl.apply_theme(name)
        self.dlg._category_icons()
        if getattr(self.dlg, "net_activity", None) is not None:
            self.dlg.net_activity.refresh(force=True)   # its status colours are per theme
        self.dlg._sync_highlight()   # the theme's own colour, unless you picked one
        for c in self.dlg.theme_cards:
            if c.name in theme.LIMITED:   # picked in time: now it's theirs
                c.setToolTip(limited_tip(c.name))
                c.setAccessibleDescription(c.toolTip())
            c.update()
