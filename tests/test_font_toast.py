"""Toast icon and first-capital ink align after live theme switches."""
import pytest
from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401
from test_font_footer import ink_middle
from soundboard.ui import busy


@pytest.mark.parametrize("name", ["Dark", "Amber Terminal", "Comic Sans"])
def test_toast_first_capital_matches_icon(window, name):  # noqa: F811
    window.resize(1700, 900)
    window.show()
    note = busy.toast(window, "Sound added", "ok", ms=0)
    for theme_name in (name, "Dark", name):
        window.apply_theme(theme_name)
        for _ in range(8):
            QApplication.processEvents()
            window._refit()
        assert abs(ink_middle(note.card.icon, note.card)
                   - ink_middle(note.card.label, note.card, capital=True)) <= 1, theme_name
