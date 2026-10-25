"""The page kit's label helpers (ui/kit/panel.py): a section's title, a number label that keeps
the width of its widest value, and a hint's small muted words. `panel` re-exports them."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel

from soundboard.ui.kit.restyled import measured


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def steady_number(lbl: QLabel, widest: str) -> QLabel:
    """A number that changes in place (9% → 100%) keeps its width: same-width digits,
    room for the widest value, right-aligned, so nothing beside it moves."""
    def fit():
        lbl.ensurePolished()
        f = lbl.font()
        f.setFeature(QFont.Tag("tnum"), 1)
        lbl.setFont(f)
        text = lbl.text()
        lbl.setMinimumWidth(0)              # (a label's size hint grows to its minimum)
        lbl.setText(widest)                 # its size hint counts the stylesheet's padding too
        lbl.setMinimumWidth(lbl.sizeHint().width() + 2)
        lbl.setText(text)

    measured(lbl, fit)   # (again in the theme's font: see restyled)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lbl


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setObjectName("hint")
    return lbl
