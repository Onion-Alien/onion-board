"""A pad drawn as a Stream Deck key: the board's own card (the theme's colours, the pad's
picture, its name, hotkey and length), so the key looks like the pad it plays.
/api/key_image sends it (soundboard.control.remote). UI thread only."""
from __future__ import annotations

import hashlib
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QPixmap

from soundboard.sounds.library import SoundMeta

SIZE = 144      # pixels: the biggest Stream Deck keys; it scales the picture down for the rest
CARD = 96       # the card is laid out this big (as on the board) and drawn at SIZE
MIN_SIZE, MAX_SIZE = 72, 288
FLASH = 0.4     # playing: how much of the board's "it just started" wash stays on (0..1)


def look(meta: SoundMeta, theme: str) -> str:
    """A short tag that changes whenever the key's picture would: a plugin keeps the
    picture it has until then."""
    bits = (meta.name, meta.color, meta.image, meta.hotkey, f"{meta.duration:.1f}", theme)
    return hashlib.sha1("\0".join(map(str, bits)).encode()).hexdigest()[:10]


def png(meta: SoundMeta, playing: bool = False, size: int = SIZE) -> bytes:
    """The pad as a `size` x `size` PNG; `playing` draws it lit up, as on the board."""
    from soundboard.sounds import thumbs
    from soundboard.ui.kit.widgets import Pad

    if meta.image:   # the board reads pictures in the background: this one is needed now
        thumbs.load_now(meta.image)
    class KeyPad(Pad):
        def devicePixelRatioF(self):   # its picture is fitted at the key's pixels, not
            return size / CARD         # the screen's: scaled up after, it was blocky

    pad = KeyPad(meta, CARD)
    try:
        pad.setFixedSize(CARD, CARD)
        pad.state = "ready"
        if playing:
            pad.progress = 0.0
            pad._play_t = time.monotonic() - 0.35 * (1 - FLASH)   # (Pad's flash lasts 0.35 s)
        pm = QPixmap(size, size)
        pm.setDevicePixelRatio(size / CARD)
        pm.fill(Qt.GlobalColor.transparent)
        pad.render(pm)
    finally:
        pad.deleteLater()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(data.data())
