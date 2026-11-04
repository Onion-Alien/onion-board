"""The admin shield on the buttons that ask Windows for permission (the mic part's Update
now and the set-up button)."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QStyle

from soundboard.ui.kit import icons


def _shield(btn: QPushButton):
    """Windows' admin shield on the button, like Windows' own buttons that ask for
    permission; the app's painted shield where the style has none (offscreen)."""
    ic = btn.style().standardIcon(QStyle.StandardPixmap.SP_VistaShield)
    if ic.isNull() or not ic.availableSizes():
        icons.set_icon(btn, "shield", "on_accent")
    else:
        btn.setIcon(ic)
