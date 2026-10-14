"""The rail's Live / Muted button is never filled with the accent, so its words must
read on its own box when it's switched on, as Stop all's beside it do (the general
`:checked` rule's on-accent colour was near-black on its grey box in many themes)."""
import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout

from soundboard import theme


def _ink(b: QPushButton) -> float:
    """The strongest contrast between any pixel of the button and its box's centre-left
    (the words are the only ink on it)."""
    img = b.grab().toImage()
    bg = img.pixelColor(3, img.height() // 2).name()
    return max(theme._contrast(img.pixelColor(x, y).name(), bg)
               for x in range(0, img.width(), 1) for y in range(0, img.height(), 2))


@pytest.mark.parametrize("name", list(theme.THEMES))
def test_live_words_read_like_stop_alls(qapp, name):
    card = QFrame()
    card.setObjectName("railoutput")
    lay = QVBoxLayout(card)
    live, stop = QPushButton("Live"), QPushButton("Stop all")
    for b in (live, stop):
        b.setObjectName("railpair")
        b.setFixedSize(90, 34)
        lay.addWidget(b)
    live.setCheckable(True)
    live.setChecked(True)
    card.setStyleSheet(theme.stylesheet(name))
    card.adjustSize()
    assert _ink(live) >= min(3.0, _ink(stop) - 0.5)
