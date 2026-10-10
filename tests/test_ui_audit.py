"""Readable secondary text across built-in themes."""
import pytest
from soundboard import theme


@pytest.mark.parametrize("name", theme.THEMES)
def test_secondary_text_contrast(name):
    tokens = theme.tokens(name)
    for key in ("muted", "faint"):
        for background in ("bg", "panel", "card", "card_hi", "btn"):
            assert theme._contrast(tokens[key], tokens[background]) >= 4.5
