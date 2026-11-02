"""Every theme in theme.THEMES, not just Dark and Light: the bugs a full
render of each one found, kept from coming back."""
import math
import re

import pytest
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QPushButton, QTabBar,
                               QVBoxLayout)
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

from soundboard.ui.kit import theme
from soundboard.ui.settings.settings import ThemeCard
from soundboard.ui.kit import icons


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_heading_colours_read_on_all_card_surfaces(name):
    t = theme.tokens(name)
    for surface in theme.TEXT_ON:
        assert theme._contrast(t["section"], t[surface]) >= 4.5, surface


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_button_hover_is_distinct_and_keeps_readable_words(name):
    t = theme.tokens(name)
    # A chosen feedback floor, not a WCAG requirement between hover/rest states.
    for base, hover, text in (("btn", "btn_hover", "text"),
                              ("accent", "accent_hover", "on_accent")):
        assert theme._contrast(t[base], t[hover]) >= 1.3, hover
        assert theme._contrast(t[text], t[hover]) >= 4.5, hover


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_the_accent_reads_where_its_drawn_as_an_icon_or_label(name):
    """Flashbang's yellow *Add sounds* was 1.4:1 on white: accent_text, the accent as
    text or an icon on the window or a card, reads (3:1) in every theme."""
    t = theme.tokens(name)
    for bg in ("bg", "panel", "card"):
        assert theme._contrast(t["accent_text"], t[bg]) >= 3.0, bg


@pytest.mark.parametrize("name", ["Dark", "Light"])
def test_the_reference_themes_keep_their_exact_accent(name):
    t = theme.tokens(name)
    assert t["accent_text"] == t["accent"]


def test_an_accent_icon_uses_the_readable_shade(qapp):
    theme.set_current("Flashbang")
    try:
        img = icons.icon("music", "accent").pixmap(QSize(24, 24)).toImage()
        seen = {QColor.fromRgba(img.pixel(x, y)).name() for x in range(24) for y in range(24)
                if QColor.fromRgba(img.pixel(x, y)).alpha() == 255}
        assert theme.T["accent_text"] in seen
        assert theme.T["accent"] not in seen
    finally:
        theme.set_current(theme.DEFAULT)


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_the_picked_theme_card_keeps_the_panel_behind_its_name(qapp, name):
    """Inside a Settings card the generic `QFrame#setcard QPushButton:checked` rule
    filled the picked theme's card with the accent, under a name drawn in the text
    colour: grey on grey in Carbon, dark on purple in Light."""
    frame = QFrame()
    frame.setObjectName("setcard")
    QVBoxLayout(frame).addWidget(card := ThemeCard(name))
    card.setChecked(True)
    frame.setStyleSheet(theme.stylesheet(name))
    frame.resize(200, 160)
    frame.ensurePolished()
    old = dict(theme.T)
    theme.set_current(name)
    try:
        img = card.grab().toImage()
        # beside the name, under the preview: the card's own background (`tile`: the
        # panel in every theme but Flashbang, where the panel is white like the window)
        got = QColor(img.pixel(img.width() - 14, img.height() - 8)).name()
        assert got == theme.T["tile"], (got, theme.T["tile"], theme.T["accent"])
    finally:
        theme.T.clear()
        theme.T.update(old)
        theme.set_current(theme.DEFAULT)


def _colours(icon: QIcon, mode=QIcon.Mode.Normal, state=QIcon.State.Off) -> set[str]:
    img = icon.pixmap(QSize(18, 18), mode, state).toImage()
    return {QColor.fromRgba(img.pixel(x, y)).name() for x in range(img.width())
            for y in range(img.height()) if QColor.fromRgba(img.pixel(x, y)).alpha() > 200}


def test_a_live_switch_leaves_no_old_theme_colours_in_icons(main_window):  # noqa: F811
    """Reported in Carbon: Add sounds still in Dark's purple and the On Air mark in
    Blood Moon's red after switching Dark -> Blood Moon -> Carbon."""
    main_window.resize(1180, 720)
    main_window.show()
    QApplication.processEvents()
    seen = []
    for name in ("Dark", "Blood Moon", "Carbon"):
        if name != "Dark":
            main_window.themectl.apply_theme(name)
            QApplication.processEvents()
        new = theme.tokens(name)
        now = {new[k] for k in ("accent", "accent_text", "live_text", "muted", "text",
                                "on_accent", "text_hi", "danger_text", "warn_text")}
        old = {theme.tokens(n)[k] for n in seen for k in ("accent", "live_text")} - now
        bad = []
        for b in main_window.findChildren(QAbstractButton):
            for state in (QIcon.State.Off, QIcon.State.On):
                if not b.icon().isNull() and (hit := _colours(b.icon(), state=state) & old):
                    bad.append((b.objectName() or b.text(), hit))
        for bar in main_window.findChildren(QTabBar):
            for i in range(bar.count()):
                if hit := _colours(bar.tabIcon(i), QIcon.Mode.Selected) & old:
                    bad.append((bar.tabText(i), hit))
        assert not bad, (name, bad)
        seen.append(name)


@pytest.mark.parametrize("name", ["Hacker", "Dark", "Light"])
def test_scroll_area_corner_is_not_drawn(qapp, name):
    """With both scroll bars up (a narrow Setup page), the square where they meet was
    drawn as a dark box with a black outline: it's see-through now."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea, QWidget

    from soundboard.ui.kit.wheelguard import AppStyle
    old_sheet = qapp.styleSheet()
    qapp.setStyle(AppStyle("Fusion"))   # the app's own style (app.py)
    qapp.setStyleSheet(theme.stylesheet(name) + "QWidget#cornerholder { background:#ff00ff; }")
    try:
        holder = QWidget()
        holder.setObjectName("cornerholder")
        holder.resize(200, 200)
        area = QScrollArea(holder)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.resize(200, 200)
        inner = QWidget()
        inner.setFixedSize(600, 600)
        area.setWidget(inner)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        holder.show()
        QApplication.processEvents()
        img = holder.grab().toImage()
        v, h = area.verticalScrollBar(), area.horizontalScrollBar()
        left, top = v.mapTo(holder, QPoint()).x(), h.mapTo(holder, QPoint()).y()
        corner = {img.pixelColor(x, y).name() for x in range(left, left + v.width())
                  for y in range(top, top + h.height())}
        assert corner == {"#ff00ff"}
        holder.close()
    finally:
        qapp.setStyleSheet(old_sheet)


def _ink_contrast(button) -> float:
    """The icon against what's behind it, from the pixels: the button drawn with its
    icon and with a blank one the same size, the pixels that change are the icon."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QPixmap
    host = button.parentWidget()
    with_icon = host.grab(button.geometry()).toImage()
    ico = button.icon()
    blank = QPixmap(button.iconSize())
    blank.fill(_Qt.GlobalColor.transparent)
    button.setIcon(QIcon(blank))
    without = host.grab(button.geometry()).toImage()
    button.setIcon(ico)
    pairs = []
    for y in range(with_icon.height()):
        for x in range(with_icon.width()):
            a, b = QColor(with_icon.pixel(x, y)), QColor(without.pixel(x, y))
            d = abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
            if d > 24:
                pairs.append((d, a.name(), b.name()))
    assert len(pairs) > 4, "no icon drawn"
    pairs.sort(reverse=True)
    __, ink, bg = pairs[len(pairs) // 10]   # the icon's solid middle, not its soft edge
    return theme._contrast(ink, bg)


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_switched_on_icon_buttons_in_a_card_show_their_icon(qapp, name):
    """A Store row's play turned stop drew its on_accent square on the row's own
    colour (a quiet icon button stays clear when switched on): black on near-black in
    Amber Terminal. An app row's Record, switched on, drew its white dot on the card's
    accent (Hacker's green, 1.4:1) instead of its red, and its red dot was 2.5:1 on
    Light's grey button."""
    from soundboard.online import store
    from soundboard.ui.kit import icons
    from soundboard.ui.store.storetab import SoundRow
    old = dict(theme.T)
    theme.set_current(name)
    try:
        frame = QFrame()
        lay = QVBoxLayout(frame)
        row = SoundRow(store.Sound(id="s", name="Owl hoot", ext="mp3"), object())
        rec_card = QFrame()
        rec_card.setObjectName("card")
        rec = QPushButton("Record")
        rec.setObjectName("rec")
        rec.setCheckable(True)
        icons.set_icon(rec, "record", "danger_text", "#ffffff", size=14)   # as approw's
        QVBoxLayout(rec_card).addWidget(rec)
        lay.addWidget(row)
        lay.addWidget(rec_card)
        frame.setStyleSheet(theme.stylesheet(name))
        frame.resize(560, 160)
        frame.show()
        QApplication.processEvents()
        play = row.btn_play
        for b in (play, rec):
            assert _ink_contrast(b) >= 3.0, (b.text() or "play", "off")
        play.blockSignals(True)
        play.setChecked(True)
        play.blockSignals(False)
        row.playing_look(True)
        rec.setChecked(True)
        QApplication.processEvents()
        for b in (play, rec):
            assert _ink_contrast(b) >= 3.0, (b.text() or "stop", "on")
        frame.close()
    finally:
        theme.T.clear()
        theme.T.update(old)
        theme.set_current(theme.DEFAULT)


def test_each_theme_card_shows_bun_as_he_looks_in_that_theme(qapp):
    """The card's Bun is that theme's (headphones, outfit, look), not the current one's,
    drawing him leaves the current theme as it was, and an upright ear isn't cut off."""
    from soundboard.ui.bun.bunny import ROOM_TOP, H
    from soundboard.ui.settings import appearance

    before = dict(theme.T)
    royal, dark = appearance._bun("Royal", 1.0), appearance._bun("Dark", 1.0)
    assert theme.T == before
    room = appearance.BUN_H * ROOM_TOP / H
    assert royal.height() == math.ceil(appearance.BUN_H + room)
    assert royal.toImage() != dark.toImage()
    img = appearance._bun("Light", 2.0).toImage()   # ears up: their tips in the room
    top = [img.pixelColor(x, y).alpha() for y in range(int(room * 2))
           for x in range(img.width())]
    assert max(top) > 200
    assert all(img.pixelColor(x, 0).alpha() == 0 for x in range(img.width()))


def test_hovering_a_theme_card_makes_bun_wave(qapp, monkeypatch):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent

    from soundboard.ui.kit import toast
    from soundboard.ui.settings import appearance, lite

    clock = [10.0]
    monkeypatch.setattr(appearance.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(toast, "ANIMATE", False)   # Windows' Animation effects off: he still waves
    card = ThemeCard("Royal")
    card.resize(card.sizeHint())
    still = card.grab().toImage()
    card.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert card._tick.isActive()
    clock[0] += 0.6
    assert card.grab().toImage() != still   # waving
    clock[0] += appearance.WAVE_S
    card._step()
    assert not card._tick.isActive() and card.grab().toImage() == still
    monkeypatch.setattr(lite, "on", lambda: True)   # lite mode: he stays still
    card.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert not card._tick.isActive()


_TEXTURED = re.compile(r"QFrame#(card|setcard|fxcard)(\[[^\]]*\])*(:[\w!]+)*$")


@pytest.mark.parametrize("name", [n for n in theme.THEMES if theme.tokens(n).get("texture")])
def test_a_hovered_or_picked_card_keeps_its_texture(name):
    """Carbon's weave went flat on a hovered card: `background:` in a state rule wipes the
    texture tile too. A card's states set only `background-color`, and a hovered box in
    a Settings card is a see-through wash, so the card's texture and its buttons show."""
    css = theme.stylesheet(name)
    for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
        sels = [s.strip() for s in re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S).split(",")]
        for sel in sels:
            if _TEXTURED.match(sel) and ("[" in sel or ":" in sel):
                assert not re.search(r"(^|[;\s])background\s*:", m.group(2)), sel
    hover = re.search(r"QFrame#setcard QFrame#tabcard:hover \{ background:([^;]*);", css)
    assert hover and hover.group(1).startswith("rgba("), "hovered box isn't see-through"


def test_settings_with_the_pink_themes_old_name_get_the_new_one():
    from soundboard.sounds.config import Config
    cfg = Config.from_raw({"version": 1, "theme": "Barbie",
                           "achievements": {"s": {"themes": ["Dark", "Barbie", "Bubblegum"]}}})
    assert cfg.theme == "Bubblegum"
    assert cfg.achievements["s"]["themes"] == ["Dark", "Bubblegum"]   # counted once
    assert "Bubblegum" in theme.THEMES
