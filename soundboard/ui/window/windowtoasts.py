"""The main window's toasts: say, tell and toast, where they stand and how they show
(ui/kit/toast.py draws them)."""
from __future__ import annotations

import re
import logging

from PySide6.QtCore import QPoint, QSize

from soundboard.ui.kit import toast as toastmod
from soundboard.ui.kit import busy

from soundboard.ui.window.windowparts import WindowParts
log = logging.getLogger("soundboard.ui.window.mainwindow")

TOAST_EXPAND = QSize(900, 640)   # a shrunk card clicked: the window grows to this

# the colour wrapper old status-line texts carry (MainWindow.say drops it)
_TONE_SPAN = re.compile(r"<span style='color:[^']*'>(.*)</span>", re.S)


class WindowToasts(WindowParts):
    """MainWindow's toasts (a mixin)."""

    def _relayout_toasts(self):
        """The download card came, went or changed size: the toasts stand on it."""
        toastmod.relayout(self)

    def toast(self, text: str, kind: str = "", ms: int = busy.TOAST_MS, **kw):
        """A result the user should see now, whatever tab or dialog is in front (the
        status line is rewritten on every tab change and hidden in small windows)."""
        return busy.toast(self, text, kind, ms, **kw)

    def say(self, text: str, kind: str = "", ms: int = busy.TOAST_MS, **kw):
        """A toast for a text written for the old status line: its coloured
        ``<span style='color:…'>`` wrapper (still in the translations) is dropped, the
        card's colour says it now."""
        m = _TONE_SPAN.fullmatch(text)
        return self.toast(m.group(1) if m else text, kind, ms, **kw)

    def tell(self, title: str, text: str, kind: str, ms: int = 8000, **kw):
        """What a message box would have said (a title and plain words, maybe on
        several lines) as one toast: the title bold on its own line."""
        return self.toast(toastmod.titled(title, text), kind, ms, **kw)

    def unsay(self, key: str):
        """Take the toast with this key down (what it said is over)."""
        toastmod.close(self, key)

    def toast_floor(self) -> int | None:
        """Where toasts stand (window y): just above the player, or the mixer strip
        when the player's hidden."""
        bar = next((w for w in (self.transport, self.mixer) if w.isVisible()), None)
        y = None if bar is None else bar.mapTo(self, QPoint(0, 0)).y()
        card = self.download_bar   # the download card in the corner: on top of it
        if card.isVisible():
            top = card.mapTo(self, QPoint(0, 0)).y() - 4
            y = top if y is None else min(y, top)
        return y

    def toast_mode(self) -> str:
        """How the corner cards show (ui/kit/toast.py): as cards in the window; as icons on
        top of the mini player's pads; not at all in the mini player with no pads (a
        remote: errors wait for the window to grow)."""
        if not self.fitctl.is_mini():
            return "cards"
        return "icons" if self._pads_scroll.isVisible() else "hidden"

    def toast_expand(self):
        """A card shrunk to its icon was clicked: make the window big enough to read
        the cards (and leave the mini player), kept on its screen."""
        if self.isMinimized():
            self.showNormal()
        if self.isMaximized() or self.isFullScreen():
            return
        room = self.screen().availableGeometry()
        want = QSize(min(max(self.width(), TOAST_EXPAND.width()), room.width()),
                     min(max(self.height(), TOAST_EXPAND.height()), room.height()))
        if want == self.size():
            return
        frame = self.frameGeometry()
        extra = frame.size() - self.size()   # the title bar and borders
        x = min(max(frame.x(), room.left()), room.right() + 1 - want.width() - extra.width())
        y = min(max(frame.y(), room.top()), room.bottom() + 1 - want.height() - extra.height())
        self.resize(want)
        self.move(max(room.left(), x), max(room.top(), y))
