"""What the download card's parts (ui/window/downloadbar.py) share: its sizes and timings (but
FOLD_MS and FOLDED_MS, which stay in downloadbar) and the clickable queue row and summary line.
`downloadbar` re-exports them."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QWidget


BAR_W = 480   # the progress bar's length in the banner
LINE_GAP = 6  # between line 1 (the title) and line 2 (the bar); the mini player: 4

THUMB_W, THUMB_H = 64, 36     # the running pick's picture
ROW_THUMB = (48, 27)          # and the other rows' ones
WIDE_AT = 720                 # the banner is this wide or more: the uploader and length show
TIGHT_BELOW = 640             # narrower: the rows drop their pictures (as in the mini player)
BAR_MIN_W = 48                # the progress bar never shrinks past this
QUEUE_ROWS = 5                # queue rows shown before the list scrolls
CARD_W = 420                  # the corner card's width (narrower windows: less 32)
CARD_TIGHT = 320              # a corner card narrower than this drops its pictures
CARD_MARGIN = 16              # from the page's side, as the toasts (ui/kit/toast.py)
CARD_GAP = 8                  # from the page's bottom: the player bar under it
PILL_BAR_W = 64               # the summary's bar in the pill


GLIDE_MS = 280                # the corner card sliding down to its pill and back up

PILL_R = 20  # the minimised corner card's corners: half its height


class _QueueRow(QFrame):
    """A row of the queue list; clicking a waiting one makes it next up."""
    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class _Summary(QWidget):
    """The banner's summary line ("Adding 3 sounds"). Minimised, it's all that shows, and
    a click on it opens the list again."""
    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)
