"""A still of the window over it while the theme changes, faded in and out (the style
kit's cover: soundboard/style/cover.py).

Restyling every widget takes a moment on a full board (seconds on a busy PC), and a
frame painted part way through showed the app half styled: Qt's plain look, or the
old theme's colours on some parts and the new one's on others. Like other polished
desktop apps (a Qt chat client fades its old frame out the same way), the window
shows a picture of itself, dimming with Bun in the middle until the new theme is in,
then fades to it. The dimming and Bun are already in the new theme's colours (his
headphones and outfit too): the old theme's showed the theme being left, not the one
coming. The cover is a child of the window: no window of its own appears.
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import theme
from soundboard.style import cover as kit
from soundboard.ui.settings import lite

# Lite mode: the cover is up and gone without fading
kit.animate = lambda: not lite.on()   # pyright: ignore[reportAttributeAccessIssue]

BUNNY_H = 96


class ThemeCover(kit.Cover):
    def __init__(self, window: QWidget, name: str | None = None):
        # the theme being switched to (`name`; None: the current one), so the cover
        # already shows where it's going
        from soundboard.bunny import bunny_pixmap
        dpr = window.devicePixelRatioF() or 1.0
        with theme.previewing(name or theme.current_name):
            scrim = QColor(theme.T["bg"])
            self.bunny = bunny_pixmap(BUNNY_H, dpr=dpr)
        super().__init__(window, scrim, self.bunny)


def covered(window: QWidget, name: str | None = None):
    """The cover over `window` for a `with` block (nothing when it isn't on screen), in
    theme `name`'s colours (the one being switched to)."""
    return kit.covered([window], lambda w: ThemeCover(w, name))


def blended(window: QWidget):
    """A plain blend over `window` for a `with` block: a quick restyle (the highlight
    colour) fades from the old look to the new instead of swapping in one frame."""
    return kit.covered([window])
