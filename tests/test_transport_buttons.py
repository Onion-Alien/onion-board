"""Tests for the modernized play/stop transport buttons and multi-theme support."""
from PySide6.QtWidgets import QPushButton

from soundboard import theme
from soundboard.ui import icons


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
