"""Setup -> Devices -> beside Send my sounds to: is the sound effect on the mic picked
there? Built into a device grid (the Setup tab's, and Settings -> Audio's copy of it);
RouteControl._show_route and StatusControl._update_flow keep them up to date."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget

from soundboard.i18n import _
from soundboard.mic import directmic
from soundboard.ui.kit import icons, theme


class MicBadge(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self._shown = None   # the look it has (sync: set again only when it changes)
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 0, 0, 0)
        h.setSpacing(6)
        self.pic = QLabel()
        h.addWidget(self.pic)
        self.words = QLabel()
        self.words.setProperty("keepline", True)
        # takes no room of its own: with no room left it goes, and the icon's tooltip says
        # it (wrapped, it held the column open and Settings went wider than the window)
        self.words.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        h.addWidget(self.words, 100)
        h.addStretch(1)
        self.sync()

    def sync(self):
        mw = self.mw
        mic = mw.cfg.mic_device
        on_mic = mw.cb_route.currentData() == "mic" and bool(mic)
        self.setVisible(on_mic and not getattr(mw, "_attaching", False))
        if not on_mic:
            return
        works = directmic.works(directmic.status(mic))
        if works != self._shown:
            self._shown = works
            icons.set_label_icon(self.pic, "check" if works else "warn",
                                 "ok_text" if works else "warn_text", size=16)
            self.words.setText(_("Sound effect installed") if works
                               else _("Sound effect not installed"))
            theme.set_tone(self.words, "ok" if works else "warn")
            self.pic.setToolTip(self.words.text())
            self.words.setMaximumWidth(self._words_width())
            self._fit_words()


    def _words_width(self) -> int:
        return self.words.fontMetrics().horizontalAdvance(self.words.text()) + 8

    def _fit_words(self):
        room = self.width() - self.pic.sizeHint().width() - 10
        self.words.setVisible(room >= self._words_width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_words()


def build(mw, grid: QGridLayout, row: int, col: int) -> MicBadge:
    """The badge in `grid`'s `row`, column `col`."""
    badge = MicBadge(mw)
    grid.addWidget(badge, row, col)
    mw.mic_badges.append(badge)
    badge.destroyed.connect(lambda *__: mw.mic_badges.remove(badge)
                            if badge in mw.mic_badges else None)
    return badge
