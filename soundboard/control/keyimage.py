"""Stream Deck keys drawn with the board's own pad card (the theme's colours and font, a
pad's picture, its name, hotkey and length, the glow while it plays), so a key looks like
the board. A pad's key is the pad; Stop all, Random sound and the switches are the same
card with an icon. /api/key_image sends them (soundboard.control.remote). UI thread only.

A key is filled edge to edge (a card's own corners showed as black notches), and its
outline and picture are rounded like the key itself (KEY_RADIUS): the Stream Deck rounds
its keys, and a square outline was cut off at the corners."""
from __future__ import annotations

import hashlib
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from soundboard.i18n import _
from soundboard.sounds.library import SoundMeta

SIZE = 144      # pixels: the biggest Stream Deck keys; it scales the picture down for the rest
CARD = 96       # the card is laid out this big (as on the board) and drawn at SIZE
MIN_SIZE, MAX_SIZE = 72, 288
FLASH = 0.4     # playing: how much of the board's "it just started" wash stays on (0..1)
EDGE = 2        # a pad card leaves this much round itself (for its glow): cut off on a key
KEY_RADIUS = 14  # a Stream Deck key's own rounded corners, on the CARD scale (~14 %)
FOOT_GROW = 1.4  # the most a small key's footer text grows (it fills the footer then)

# the keys that aren't a pad: what they say (on, off) and their icon
CONTROLS = {
    "stop": ("stop", lambda on: _("Stop all")),
    "random": ("dice", lambda on: _("Random sound")),
    "live": ("switch", lambda on: _("Live") if on else _("Muted")),
    "voice": ("switch", lambda on: _("Voice changer")),
    "mic": ("switch", lambda on: _("My mic")),
    "hotkeys": ("switch", lambda on: _("Hotkeys")),
}


def look(meta: SoundMeta, theme: str) -> str:
    """A short tag that changes whenever the pad's key would: a plugin keeps the picture
    it has until then."""
    bits = (meta.name, meta.color, meta.image, meta.hotkey, f"{meta.duration:.1f}", theme)
    return hashlib.sha1("\0".join(map(str, bits)).encode()).hexdigest()[:10]


def controls_look(theme: str, language: str) -> str:
    """The same for the Stop / Random / switch keys: they change with the theme and the
    language only."""
    return hashlib.sha1(f"{theme}\0{language}".encode()).hexdigest()[:10]


def two_lines(name: str, fm: QFontMetrics, width: int) -> str:
    """The name over at most two lines `width` wide, the second cut short with "…": a
    key is narrower than a card, and one line left "Sad Trom…"."""
    words = name.split()
    first, i = "", 0
    while i < len(words) and fm.horizontalAdvance(f"{first} {words[i]}".strip()) <= width:
        first = f"{first} {words[i]}".strip()
        i += 1
    if not first:   # one word wider than the key
        return fm.elidedText(name, Qt.TextElideMode.ElideRight, width)
    rest = " ".join(words[i:])
    return first + ("\n" + fm.elidedText(rest, Qt.TextElideMode.ElideRight, width) if rest else "")


def png(meta: SoundMeta, playing: bool = False, size: int = SIZE) -> bytes:
    """A pad's key as a `size` x `size` PNG; `playing` draws it lit up, as on the board."""
    from soundboard.sounds import thumbs

    if meta.image:   # the board reads pictures in the background: this one is needed now
        thumbs.load_now(meta.image)
    return _encode(_card(meta, playing, size)[0])


def control_png(kind: str, on: bool, size: int = SIZE) -> bytes:
    """Stop all / Random sound / a switch (`kind`, a CONTROLS key) as a key: the pad card
    with the theme's accent, its name, an icon, and for a switch On / Off and the glow."""
    from soundboard.ui.kit.widgets import pad_colours

    icon, label = CONTROLS[kind]
    C = pad_colours()
    switch = icon == "switch"
    meta = SoundMeta(id=f"key:{kind}", name=label(on), file="", color=C["accent"].name())
    foot = (_("On") if on else _("Off")) if switch and kind != "live" else ""
    pm, name = _card(meta, switch and on, size, foot)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _icon(p, icon, on, C, two=("\n" in name))
    p.end()
    return _encode(pm)


def _card(meta: SoundMeta, lit: bool, size: int,
          foot: str | None = None) -> tuple[QPixmap, str]:
    """The card as a pixmap, and its name as drawn (on two lines: a newline in it)."""
    from soundboard.control import midi
    from soundboard.ui.kit import widgets
    from soundboard.ui.kit.hotkeypick import pretty_key

    class KeyPad(widgets.Pad):
        def devicePixelRatioF(self):   # its picture is fitted at the key's pixels, not
            return size / CARD         # the screen's: scaled up after, it was blocky

        def _fit_name(self, room: QRectF):
            f, flags, _n = super()._fit_name(room)
            self.shown = two_lines(self.meta.name, QFontMetrics(f), room.toRect().width())
            return f, flags, self.shown

        def _footer(self, room: QRectF, name_font):
            f, right, badge = super()._footer(room, name_font)
            if size < SIZE:
                # the board's 8.5 pt, drawn at 72 px, was a few pixels high: bigger
                # on a small key (up to FOOT_GROW), the hotkey's badge measured again
                f = QFont(f)
                f.setPointSizeF(f.pointSizeF() * min(FOOT_GROW, max(1.0, SIZE * 0.7 / size)))
                badge = None
            if foot is not None:
                return f, foot, None
            if badge is None and self.meta.hotkey:
                # the board drops a badge wider than 68 % of the footer, and a key is
                # always 96 wide: "Ctrl+Alt+7" never showed. The key's hotkey goes over
                # its length instead, when the two don't fit side by side (the length
                # without its ⟳ / FX marks first: a small key's bigger font)
                m = self.meta.hotkey
                hk = midi.short(m) if midi.is_midi(m) else pretty_key(m)
                fm = QFontMetrics(f)
                w = fm.horizontalAdvance(hk) + 12
                if w <= room.width():
                    badge = (hk, w)
                    length = f"{self.meta.duration:.1f}s"
                    for text in (right, length if right.endswith(length) else "", ""):
                        if w + 6 + fm.horizontalAdvance(text) <= room.width():
                            break
                    right = text
            return f, right, badge

    pad = KeyPad(meta, CARD)
    pad.shown = meta.name
    radius = widgets.PAD_RADIUS
    widgets.PAD_RADIUS = KEY_RADIUS   # the key's own curve (the corners outside: card colour)
    try:
        pad.setFixedSize(CARD + 2 * EDGE, CARD + 2 * EDGE)
        pad.state = "ready"
        if lit:
            pad.progress = 0.0
            pad._play_t = time.monotonic() - 0.35 * (1 - FLASH)   # (Pad's flash lasts 0.35 s)
        pm = QPixmap(size, size)
        pm.setDevicePixelRatio(size / CARD)
        pm.fill(widgets.pad_colours()["card"])
        # no window background: a widget of its own paints the theme's behind it, and
        # the corners outside the curve came out that dark instead of the card colour
        pad.render(pm, QPoint(-EDGE, -EDGE), renderFlags=QWidget.RenderFlag.DrawChildren)
    finally:
        widgets.PAD_RADIUS = radius
        pad.deleteLater()
    return pm, pad.shown


def _icon(p: QPainter, icon: str, on: bool, C: dict[str, QColor], two: bool = False):
    """The control's icon between the name and the footer (logical CARD x CARD); lower
    and a little smaller under a name on two lines."""
    if icon == "stop":   # red: the theme's own (its Stop all's pink read as purple-ish)
        ink = QColor(C["error_text"])
    else:
        ink = QColor(C["accent"] if on or icon != "switch" else C["muted"])
    cx, cy = CARD / 2, (61 if two else 55)
    p.translate(cx, cy)
    p.scale(0.8 if two else 0.92, 0.8 if two else 0.92)
    cx = cy = 0
    p.setPen(Qt.PenStyle.NoPen)
    if icon == "stop":
        p.setBrush(ink)
        p.drawRoundedRect(QRectF(cx - 13, cy - 13, 26, 26), 6, 6)
    elif icon == "dice":
        p.setPen(QPen(ink, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(cx - 15, cy - 15, 30, 30), 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        for dx, dy in ((-7, -7), (0, 0), (7, 7)):
            p.drawEllipse(QRectF(cx + dx - 3, cy + dy - 3, 6, 6))
    else:   # a switch, as the board's own: filled with the knob right when on
        track = QRectF(cx - 20, cy - 11, 40, 22)
        if on:
            p.setBrush(ink)
            p.drawRoundedRect(track, 11, 11)
            p.setBrush(C["on_accent"])
            p.drawEllipse(QRectF(track.right() - 19, track.top() + 3, 16, 16))
        else:
            p.setPen(QPen(ink, 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(1, 1, -1, -1), 10, 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ink)
            p.drawEllipse(QRectF(track.left() + 4, track.top() + 4, 14, 14))


def _encode(pm: QPixmap) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(data.data())
