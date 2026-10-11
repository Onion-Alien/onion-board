"""Tests for the modernized play/stop transport buttons and multi-theme support."""
from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionButton
import pytest

from soundboard import theme
from soundboard.ui import icons


@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 1.75, 2])
@pytest.mark.parametrize("size", [(36, 36), (34, 30)])
@pytest.mark.parametrize("name", ["Dark", "Light"])
def test_stop_hover_outline_survives_scaling(qapp, scale, size, name):
    theme.apply(qapp, name)
    button = QPushButton()
    button.setObjectName("transport_stop")
    button.resize(*size)
    button.ensurePolished()
    option = QStyleOptionButton()
    option.initFrom(button)
    option.state |= QStyle.State_MouseOver | QStyle.State_Enabled
    image = QImage(round(size[0] * scale), round(size[1] * scale), QImage.Format_ARGB32)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    button.style().drawControl(QStyle.CE_PushButton, option, painter, button)
    painter.end()
    red = QColor(theme.T["danger_text"])
    for xs in (range(4), range(image.width() - 4, image.width())):
        # Two solid pixels per side keep fractional-scale antialiasing from
        # swallowing the left edge of the outline.
        colors = [image.pixelColor(x, image.height() // 2) for x in xs]
        assert sum(c == red for c in colors) >= 2


def test_transport_icon_shapes(qapp):
    """Verify play, pause, and stop vector pixmaps render cleanly and non-null."""
    for name in ("play", "pause", "stop"):
        pm = icons.pixmap(name, 24, "#ffffff")
        assert not pm.isNull()
        assert pm.width() == 24
        assert pm.height() == 24


def test_all_themes_transport_styles(qapp):
    """Verify that every theme supports the transport button selectors and accent colors."""
    for theme_name in theme.THEMES:
        theme.apply(qapp, theme_name)
        icons.retheme()
        css = qapp.styleSheet()

        assert "QPushButton#transport_play" in css, f"Missing transport_play in {theme_name}"
        assert "QPushButton#transport_stop" in css, f"Missing transport_stop in {theme_name}"

        # Ensure tokens exist and resolve
        t = theme.T
        assert "accent" in t and "on_accent" in t, f"Missing accent tokens in {theme_name}"
        assert "btn" in t and "border" in t and "danger_text" in t

        # Ensure icon resolves in this theme
        ic_play = icons.icon("play", "on_accent")
        ic_pause = icons.icon("pause", "on_accent")
        ic_stop = icons.icon("stop")
        assert not ic_play.isNull()
        assert not ic_pause.isNull()
        assert not ic_stop.isNull()


def test_transport_buttons_live_retheme(qapp):
    """Verify that buttons with transport_play and on_accent update cleanly on theme change."""
    btn_play = QPushButton()
    btn_play.setObjectName("transport_play")
    icons.set_icon(btn_play, "play", "on_accent", size=16)

    btn_stop = QPushButton()
    btn_stop.setObjectName("transport_stop")
    icons.set_icon(btn_stop, "stop", size=16)

    assert not btn_play.icon().isNull()
    assert not btn_stop.icon().isNull()

    for theme_name in ("Dark", "Light", "Toxic", "Ocean", "High Contrast"):
        if theme_name in theme.THEMES:
            theme.apply(qapp, theme_name)
            icons.retheme()
            assert not btn_play.icon().isNull()
            assert not btn_stop.icon().isNull()
