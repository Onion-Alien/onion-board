"""The player's time ("17:40 / 58:51") always fits its label: measured in each theme's
own font, not once in the default one (a Consolas theme cut the minutes' first digit,
so a long song's time read "7:40" while the seek bar sat at 17:40)."""
import pytest
from PySide6.QtWidgets import QApplication

from soundboard.ui.kit import theme
from soundboard.ui.kit.seek import TIME_WIDEST
from test_mainwindow import window  # noqa: F401

# the themes with a font of their own, and the default one
FONTED = ["Dark"] + [n for n, t in theme.THEMES.items()
                     if isinstance(t, dict) and t.get("font")]


def _fits(label) -> bool:
    label.ensurePolished()
    return label.fontMetrics().horizontalAdvance(TIME_WIDEST) <= label.minimumWidth()


@pytest.mark.parametrize("name", FONTED)
def test_the_longest_time_fits_in_every_themes_font(window, name):  # noqa: F811
    window.themectl.apply_theme(name)
    QApplication.processEvents()
    assert _fits(window.np_time), name
    assert _fits(window.mini_time), name
