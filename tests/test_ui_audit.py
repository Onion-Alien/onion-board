"""Readable secondary text across built-in themes."""
import pytest
from PySide6.QtWidgets import QLineEdit

from soundboard import theme


@pytest.mark.parametrize("name", theme.THEMES)
def test_secondary_text_contrast(name):
    tokens = theme.tokens(name)
    for key in ("muted", "faint"):
        # a quiet button's hover and the inset boxes too: 3.6-4.5:1 in most themes before
        for background in ("bg", "panel", "card", "card_hi", "btn", "btn_hover", "inset"):
            assert theme._contrast(tokens[key], tokens[background]) >= 4.5, (key, background)


@pytest.mark.parametrize("name", ["Dark", "Light", "High Contrast", "Retro 98"])
def test_placeholder_text_is_muted_not_half_see_through(qapp, name):
    """Qt draws placeholder text at half opacity by itself (3.2:1 in Light): the
    style sheet gives it the theme's muted colour instead."""
    theme.apply(qapp, name)
    try:
        box = QLineEdit()
        box.setPlaceholderText("Search")
        box.ensurePolished()
        colour = box.palette().placeholderText().color()
        assert colour.alpha() == 255
        assert colour.name() == theme.T["muted"]
    finally:
        theme.apply(qapp, theme.DEFAULT)
