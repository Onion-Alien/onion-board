"""Every theme in theme.THEMES (31 of them), not just Dark and Light: the bugs a full
render of each one found, kept from coming back."""
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QTabBar, QVBoxLayout
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

from soundboard import theme
from soundboard.settings import ThemeCard
from soundboard.ui import icons


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
            main_window.apply_theme(name)
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
