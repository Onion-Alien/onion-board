"""Settings → Appearance: themes, texture, size, language and the highlight colour."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QRadioButton,
                               QSlider, QVBoxLayout, QWidget)

from soundboard import i18n, theme
from soundboard.i18n import _
from soundboard.ui import busy
from soundboard.ui.pixels import snap_to_pixels
from soundboard.ui.settingspages import Page, _button_row
from soundboard.wheelguard import no_wheel


_tiles: dict[str, QBrush | None] = {}


def _tile(name: str) -> QBrush | None:
    """A theme's texture as a brush for its preview card (None: the theme has none)."""
    if name not in _tiles:
        kind = theme.THEMES[name].get("texture", "")
        _tiles[name] = (QBrush(QPixmap.fromImage(theme.texture_image(kind, theme.THEMES[name])))
                        if kind in theme.TEXTURES else None)
    return _tiles[name]


class ThemeCard(QPushButton):
    """A clickable mini-preview of a theme: its colours, and with Textured on, its
    pattern on the panels and its glow behind them, so the switch shows what it does."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.setObjectName("themecard")
        self.setAccessibleName(name)   # it draws its name: a screen reader had nothing to say
        self.setCheckable(True)
        self.setFixedSize(QSize(150, 112))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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
        for i, col in enumerate(("#7c5cff", "#ff5c8a", "#1fb6ff", "#13ce66")):
            x = r.left() + 7 + (i % 2) * 44
            y = r.top() + 7 + (i // 2) * 34
            for brush in (QColor(t["card"]), tile):
                if brush is not None:
                    p.setBrush(brush)
                    p.drawRoundedRect(QRectF(x, y, 40, 28), 5, 5)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x + 5, y + 5, 10, 3), 1.5, 1.5)
        p.setBrush(QColor(t["groove"]))
        p.drawRoundedRect(QRectF(r.right() - 39, r.top() + 20, 28, 3), 1.5, 1.5)
        p.setBrush(QColor(t["accent"]))
        p.drawRoundedRect(QRectF(r.right() - 39, r.top() + 20, 17, 3), 1.5, 1.5)
        theme.paint_logo(p, QRectF(r.right() - 36, r.bottom() - 30, 22, 22),
                         t["accent"], t["accent2"])
        # name, in the theme's own font
        p.setPen(QColor(theme.T["text"]))
        f = QFont(self.font())
        f.setFamily(t.get("font", theme.FONT))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, self.height() - 28, self.width() - 20, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.name)
        p.end()


class ThemeGrid(QWidget):
    """Keep previews their readable size, using as many columns as fit."""

    def __init__(self, cards):
        super().__init__()
        self.cards = cards
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
        self._reflow(columns)
        # the width left over is shared out as equal gaps, first card on the left edge
        # and a full row's last on the right (all of it sat on the right, an empty strip)
        gap = 12
        if columns > 1:
            gap = max(12, (self.width() - columns * 150) // (columns - 1))
        self.grid.setHorizontalSpacing(gap)

    def _reflow(self, columns):
        if columns == self.columns:
            return
        for col in range(self.columns + 1):
            self.grid.setColumnStretch(col, 0)
        from soundboard.ui.widgets import take_out   # (it imports this module)
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
        """Language on its own, then one box for the look with a row of tabs (the
        themes, highlight colour, style, size, live tabs, background): one after another
        the page ran so long that some people never scrolled down to the themes."""
        w, v = self._page()
        self.dlg.theme_cards = []
        v.addWidget(self._language_card())
        hints = {"Classic": _("Changes the whole app instantly."),
                 "Meme": _("For when you want your soundboard to be a bit.")}
        themes, tv = self._card(_("Themes"), icon="palette")
        tv.setSpacing(6)
        from soundboard.ui.panel import heading_row
        group_icons = {"Classic": "star", "Colourful": "palette", "Wild": "shuffle",
                       "Meme": "like"}
        for group, names in theme.GROUPS:
            head, _title, _marks = heading_row(theme.group_name(group),
                                               group_icons.get(group, ""))
            tv.addLayout(head)
            if group in hints:
                h = QLabel(hints[group])
                h.setObjectName("hint")
                h.setWordWrap(True)
                tv.addWidget(h)
            cards = []
            for name in names:
                c = ThemeCard(name)
                c.setChecked(name == theme.current_name)
                c.clicked.connect(lambda __=False, n=name: self._pick_theme(n))
                cards.append(c)
                self.dlg.theme_cards.append(c)
            tv.addWidget(ThemeGrid(cards))
            tv.addSpacing(8)
        pages = [(_("Themes"), themes),
                 (_("Colour"), self._highlight_card()),
                 (_("Theme style"), self._texture_card()),
                 (_("Size"), self._ui_scale_card()),
                 (_("Live tabs"), self._live_tabs_card()),
                 (_("Background"), self._playing_background_card())]
        v.addWidget(self._look_box(pages))
        v.addStretch(1)
        return w

    def _look_box(self, pages) -> QFrame:
        """One card holding `pages` [(tab name, card)], a tab row on top showing one at a
        time (the others hidden, so the box is only as tall as the one showing). To
        search it is one card; a search lands on the tab with the words."""
        box = QFrame()
        box.setObjectName("setcard")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 14)
        bv.setSpacing(10)
        row = _button_row()
        bv.addLayout(row)
        group = QButtonGroup(box)
        tabs = []
        from soundboard.ui.widgets import widget_at   # (it imports this module)
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
                              _("A tab whose feature is on right now (a sound playing, the voice "
                                "changer, the radio…) is marked, so nothing is left on without "
                                "you noticing."), icon="live")
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
        from soundboard.library import UI_SCALES
        card, cv = self._card(_("Interface size"),
                              _("Makes everything in Onion Board bigger or smaller: text, "
                                "buttons and pads."), icon="expand")
        now = round(float(os.environ.get("QT_SCALE_FACTOR") or 1) * 100)
        combo = QComboBox()
        combo.setAccessibleName(_("Interface size"))
        for pct in UI_SCALES:
            combo.addItem(_("{percent}%", percent=pct), pct)
        combo.setCurrentIndex(max(0, combo.findData(self.mw.cfg.ui_scale)))
        no_wheel(combo)
        restart = QPushButton(_("Restart now"))
        restart.clicked.connect(self.mw.restart_app)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(combo)
        row.addWidget(restart)
        row.addStretch(1)   # as wide as their text, not the card
        cv.addLayout(row)
        note = QLabel(_("Onion Board changes size after a restart."))
        note.setObjectName("hint")
        note.setWordWrap(True)
        cv.addWidget(note)

        def show():
            later = self.mw.cfg.ui_scale != now
            note.setVisible(later)
            restart.setVisible(later)

        def picked(i):
            self.mw.cfg.ui_scale = combo.itemData(i)
            self.mw._save_later()
            show()
        combo.currentIndexChanged.connect(picked)
        show()
        (self.dlg.ui_scale_combo, self.dlg.ui_scale_note,
         self.dlg.ui_scale_restart) = combo, note, restart
        return card

    def _playing_background_card(self) -> QFrame:
        card, cv = self._card(_("Playing sound background"),
                              _("Show the playing sound's thumbnail behind the cards"), icon="wave")
        enabled = QCheckBox(_("On"))
        enabled.setAccessibleName(_("Playing sound background"))
        enabled.setChecked(self.mw.cfg.playing_background)
        enabled.toggled.connect(lambda on: self.mw.set_option("playing_background", on))
        cv.addWidget(enabled)
        row = QHBoxLayout()
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
        from soundboard.ui.langpick import LangButton
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
            from soundboard.ui.langpick import LanguageDialog
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
                              _("What's switched on (the voice changer, Live, a live tab) is "
                                "shown in the theme's colour. Slide to pick your own; it stays "
                                "when you change theme."), icon="edit")
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
        self.mw.themectl.apply_theme(name)
        self.dlg._category_icons()
        if getattr(self.dlg, "net_activity", None) is not None:
            self.dlg.net_activity.refresh(force=True)   # its status colours are per theme
        self.dlg._sync_highlight()   # the theme's own colour, unless you picked one
        for c in self.dlg.theme_cards:
            c.setChecked(c.name == name)
            c.update()
