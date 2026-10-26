"""What the Radio tab's parts (ui/radio/radiopanel.py) share: its timings and list sizes, and
`_steady_text`, the button words that keep the button as wide as its widest label.
`radiopanel` re-exports them."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from soundboard.ui.kit.restyled import on_restyle


SEARCH_DELAY_MS = 450      # typing pause before the directory is asked
TYPE_DELAY_MS = 80         # ...and before the list shows the matches already known
FAV_MAX = 200
RECENT_MAX = 30
PRELOAD_MS = 2000          # after the station list is up: the decoder loads (preload_decoder)


def _steady_text(btn: QPushButton, text: str, *others: str):
    """Show `text` on a button that switches between labels (Play / Stop), kept as wide
    as the widest of them so the buttons beside it don't shift on every click. A
    checkable one is measured on and off too: its on look has a border."""
    btn.ensurePolished()                # measured in its stylesheet's (bold) font
    widest = 0
    was = btn.isChecked()
    blocked = btn.blockSignals(True)
    for on in {was, not was} if btn.isCheckable() else {was}:
        btn.setChecked(on)
        for t in (*others, text):
            btn.setText(t)
            widest = max(widest, btn.sizeHint().width())
    btn.setChecked(was)
    btn.blockSignals(blocked)
    btn.setText(text)
    btn.setMinimumWidth(widest if text else 0)
    if btn.property("steady") is None:   # again in the theme's font (see restyled)
        on_restyle(btn, lambda: _steady_text(btn, btn.text(), *btn.property("steady")))
    btn.setProperty("steady", list(others))
