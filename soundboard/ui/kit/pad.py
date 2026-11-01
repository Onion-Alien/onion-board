"""One sound's pad: the hand-painted button on the board, its sizes and colours."""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import (QEasingCurve, QEvent, QMimeData, QPoint, QPointF, QRectF, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QDrag, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QToolTip)

from soundboard.sounds import library, thumbs
from soundboard.ui.kit import theme
from soundboard.control import midi
from soundboard.sounds.library import SoundMeta
from soundboard.ui.kit.hotkeypick import pretty_key
from soundboard.ui.kit import icons
from soundboard.ui.settings import lite
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.kit.plaintext import plain_tip


PAD_MIME = "application/x-soundboard-pad"


MINI_PAD_MIN_W = 96   # the mini player's two-a-row pads get no smaller than this


SLIM_PAD_H = 30      # a pad as a one-line row: the mini player when it's too small for cards


# the Sounds tab's list view, by its row size (Config.list_rows): how tall a row is,
# and how wide at least (as many a line as fit)
LIST_ROW_H = {"small": 26, "medium": 30, "large": 38}


LIST_ROW_W = {"small": 220, "medium": 260, "large": 300}


ROW_MAX_H = max(LIST_ROW_H.values())   # a pad this short or shorter is drawn as a row


def pad_height(width: int) -> int:
    return int(width * 0.62)


# a picture on a pad is darkened towards the bottom so the text reads on it:
# (where 0..1, black's alpha), lighter while the mouse is over it
PAD_RADIUS = 12      # a pad card's rounded corners


HOVER_LIFT = 2.0     # how far a card rises under the mouse (it has 2 px spare above)


HOVER_MS = 120       # ...and how quickly: short, so moving across the board feels light


PAD_SHRINK = 0.8     # a row takes one more pad when that shrinks them by a fifth at most


PIC_SHADE = ((0.0, 100), (0.55, 150), (1.0, 205))


PIC_SHADE_HOVER = ((0.0, 70), (0.55, 120), (1.0, 205))


_PAD_COLOURS = ("card", "card_hi", "border", "border_hi", "accent", "on_accent", "text_hi",
                "muted", "error_text", "badge", "badge_text")


_pad_palette: list = [None, {}]   # (the theme's values, QColor for each) - see pad_colours


_SHADOW, _WHITE = QColor(0, 0, 0, 200), QColor("#ffffff")   # text on a picture


_METER_WARM, _METER_HOT = QColor("#ffb84d"), QColor("#ff5a4f")   # a level meter near full scale


_WHITE_DIM, _WHITE_MUTED = QColor(255, 255, 255, 170), QColor(255, 255, 255, 200)


_ERROR_ON_PIC = QColor("#ff6b6b")


LINK_PX = 12         # the linked-file mark: the footer text's height


STOP_PX = 12         # the ✕ on an effects render in progress...


STOP_HIT_PX = 24     # ...and where a click on it counts (WCAG 2.2 target size)


_link_pm: dict = {}  # (colour, real pixels) -> its pixmap


def _link_pixmap(colour: QColor, dpr: float) -> QPixmap:
    px = round(LINK_PX * dpr)
    key = (colour.rgba(), px)
    pm = _link_pm.get(key)
    if pm is None:
        pm = _link_pm[key] = icons.pixmap("link", px, colour.name(QColor.NameFormat.HexArgb))
        pm.setDevicePixelRatio(dpr)
    return pm


def pad_colours() -> dict[str, QColor]:
    """The theme colours a pad paints with, as QColors made once per theme (a few
    hundred pads each made a dozen every paint)."""
    key = tuple(theme.T[k] for k in _PAD_COLOURS)
    if key != _pad_palette[0]:
        _pad_palette[0] = key
        _pad_palette[1] = {k: QColor(v) for k, v in zip(_PAD_COLOURS, key)}
    return _pad_palette[1]


PAUSE_W = 7   # the painted pause sign's width: two 3 px bars, 1 px apart


def _paint_pause(p: QPainter, right: float, cy: float, h: float, colour: QColor):
    """Two bars ending at `right`, `h` tall around `cy`, on whole pixels (sharp).
    Painted, not the ❚❚ text: some fonts spaced those bars a word apart."""
    x, top, h = round(right) - PAUSE_W, round(cy - h / 2), round(h)
    p.fillRect(QRectF(x, top, 3, h), colour)
    p.fillRect(QRectF(x + 4, top, 3, h), colour)


def _hover_mix(lo: QColor, hi: QColor, k: float) -> QColor:
    """`lo` blended `k` of the way to `hi` (a pad's hover fade)."""
    return QColor.fromRgbF(lo.redF() + (hi.redF() - lo.redF()) * k,
                           lo.greenF() + (hi.greenF() - lo.greenF()) * k,
                           lo.blueF() + (hi.blueF() - lo.blueF()) * k)


def _badge_text(hotkey: str) -> str:
    """A hotkey as its badge shows it ("" for none)."""
    return hotkey and (midi.short(hotkey) if midi.is_midi(hotkey) else pretty_key(hotkey))


class Pad(QAbstractButton):
    """One sound's button, painted by hand. It's a QAbstractButton so screen readers
    see a button with the sound's name, and it works from the keyboard: Tab / arrows
    to move, Enter or Space to play, Ctrl+Space to pick, the Menu key for its menu,
    F2 to rename it, Alt+Enter to edit it (Delete removes it: ui/sounds/padbatch.py)."""
    activated = Signal(str)     # play it (a double-click, Enter, a screen reader's press)
    rename = Signal(str)        # F2: ask for a new name
    edit = Signal(str)          # Alt+Enter: the Edit window
    chosen = Signal(str)        # a single click: select it (transport bar) without playing
    pick = Signal(str, bool)    # Ctrl+click / Ctrl+Space (False) or Shift+click (True)
    space = Signal(str)         # Space: pause / resume it if it's playing, else play it
    menu = Signal(str, QPoint)
    step = Signal(object, int, int)   # arrow key: this pad, columns, rows to move focus
    nudge = Signal(str, int)    # Ctrl+wheel: its volume this many steps up (+) or down (-)
    stop_render = Signal(str)   # the ✕ on its effects render: stop it, keep the old effects
    seen = Signal(str)          # a new sound's card had the mouse over it (newsounds.py)
    single_click = True         # Settings: a click plays it (activated) instead of selecting

    def __init__(self, meta: SoundMeta, width: int):
        super().__init__()
        # Space pauses / plays this pad (ui/window/spacekey.py)
        self.setProperty("own_space", True)
        self.meta = meta
        self.progress: float | None = None     # None = not playing
        self.paused = False
        self.bands: np.ndarray | None = None   # visualizer levels (0..1) while playing
        self.peaks: np.ndarray | None = None   # the little caps that fall slowly
        self.meter = None        # how loud it is right now (0..1) while playing
        self.meter_peak = 0.0    # the meter's peak mark, falling slowly
        self.selected = False    # the sound in the transport bar
        self.picked = False      # one of several picked for a batch change (ui.padbatch)
        self.fresh = False       # new on the board, not looked at yet: it glows
        self.state = "loading"   # loading | rendering | ready | error
        self.error = ""
        self.render_frac: float | None = None   # rendering: how far, 0..1 (EditControl)
        self.can_stop = False    # rendering: its ✕ shows (there are old effects to go back to)
        self._stop_rect: QRectF | None = None   # where the ✕ was painted
        self.hover = False
        self._hover_k = 0.0      # 0..1, eased in and out (the card lights up smoothly)
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(HOVER_MS)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)   # quick up, soft landing
        self._hover_anim.valueChanged.connect(self._on_hover_k)
        self._down = False       # pressed: the card sinks a little
        self.name_cut = False    # the name is cut short with "…" (_fit_name)
        self._play_t: float | None = None   # when it started playing (the flash on start)
        self._press = None
        self._last_click = -1e9   # when a plain left click was let go (ms): see _second_click
        self._kbd_focus = False  # focus came from the keyboard: draw the focus ring
        self._described = None
        self._name_fit = None    # (what it was fitted to, how) - see _fit_name
        self._font_key = self.font().key()
        self._accent: tuple[str | None, QColor] = (None, QColor())   # (meta.color, its QColor)
        # (what the footer shows, its font, text and badge)
        self._foot: tuple[tuple | None, tuple[QFont, str, tuple[str, int] | None] | None] = \
            (None, None)
        self._linked = (None, "")     # (meta.file, its path when outside the library)
        self._link_rect: QRectF | None = None   # where the linked-file mark was painted
        self._wheel = 0               # Ctrl+wheel turned less than a notch (touchpads)
        self.setFixedSize(width, pad_height(width))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(lambda: self.activated.emit(self.meta.id))   # keyboard / a11y
        self.describe()

    def set_fresh(self, on: bool):
        if on != self.fresh:
            self.fresh = on
            self.update()

    def set_picked(self, on: bool):
        self.picked = on
        self.describe()
        self.update()

    def describe(self):
        """Keep what a screen reader says in step with the pad (only when it changes)."""
        m = self.meta
        bits = []
        if self.progress is not None:
            bits.append(_("paused") if self.paused else _("playing"))
        if self.picked:
            bits.append(_("selected"))
        if self.state == "rendering" and self.render_frac is not None:
            bits.append(_("applying effects… {pct}%", pct=int(self.render_frac * 100)))
        elif self.state in ("loading", "rendering"):
            bits.append(_("loading"))
        elif self.state == "error":
            bits.append(_("can't load the file"))
        else:
            bits.append(_("{s} seconds", s=f"{m.duration:.1f}"))
        if m.hotkey:
            bits.append(_("hotkey {key}", key=pretty_key(m.hotkey)))
        if m.loop:
            bits.append(_("loops"))
        if m.mode in ("overlap", "toggle"):
            bits.append({"overlap": _("presses overlap"),
                         "toggle": _("press again stops")}[m.mode])
        if m.hold:
            bits.append(_("plays while its hotkey is held"))
        if m.fx:
            bits.append(_("effects"))
        if m.tags:
            bits.append(_("in {categories}", categories=", ".join(
                t if "/" not in t else t.replace(" / ", " › ") for t in m.tags
                if not any(o.startswith(t + " / ") for o in m.tags))))
        if self.linked_file():
            bits.append(_("Plays from: {path}", path=self.linked_file()))
        desc = ", ".join(bits)
        if (m.name, desc) != self._described:
            self._described = (m.name, desc)
            self.setText(m.name.replace("&", "&&"))   # else "R&B" claims Alt+B
            self.setAccessibleName(m.name)
            self.setAccessibleDescription(desc)

    def linked_file(self) -> str:
        """The sound's file on the disk when the library didn't copy it in ("Copy into
        library" is off: the pad plays the original), else ""."""
        f = self.meta.file
        if self._linked[0] != f:
            self._linked = (f, str(Path(f)) if f and not library.owns(f) else "")
        return self._linked[1]

    def event(self, e):
        """The linked-file mark's tooltip shows over the mark only; elsewhere on the pad,
        the whole name when it's cut short."""
        if e.type() == QEvent.Type.ToolTip:
            box = self._link_rect
            hit = box.adjusted(-4, -4, 4, 4) if box is not None else None
            stop = self._stop_hit(QPointF(e.pos()))
            if stop is not None:
                QToolTip.showText(e.globalPos(), _("Stop, keep the old effects"), self,
                                  stop.toAlignedRect())
            elif hit is not None and hit.contains(QPointF(e.pos())) and self.linked_file():
                QToolTip.showText(e.globalPos(), plain_tip(_("Plays from: {path}",
                                                             path=self.linked_file())),
                                  self, hit.toAlignedRect())
            elif self.name_cut:   # (names come from the web and other boards)
                QToolTip.showText(e.globalPos(), plain_tip(self.meta.name), self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def focusInEvent(self, e):
        self._kbd_focus = e.reason() in (Qt.FocusReason.TabFocusReason,
                                         Qt.FocusReason.BacktabFocusReason,
                                         Qt.FocusReason.ShortcutFocusReason,
                                         Qt.FocusReason.OtherFocusReason)
        super().focusInEvent(e)
        from soundboard.ui.kit.padgrid import PadGrid   # (it imports this module)
        grid = self.parentWidget()
        if isinstance(grid, PadGrid) and e.reason() in (Qt.FocusReason.TabFocusReason,
                                                        Qt.FocusReason.BacktabFocusReason):
            grid.reveal(self)   # (Shift+Tab lands on the last pad, maybe far down)

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)

    def focusNextPrevChild(self, next):
        """Tab leaves the pads in one press (the arrows move between them): one Tab per
        sound stood between the pads and the rest of the window."""
        from soundboard.ui.kit.padgrid import PadGrid   # (it imports this module)
        grid = self.parentWidget()
        if isinstance(grid, PadGrid) and grid.tab_out(next):
            return True
        return super().focusNextPrevChild(next)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1),
                  Qt.Key.Key_Down: (0, 1)}
        if k == Qt.Key.Key_Space and mods & Qt.KeyboardModifier.ControlModifier:
            self.pick.emit(self.meta.id, False)
        elif k == Qt.Key.Key_Space and not mods:
            if not e.isAutoRepeat():
                self.space.emit(self.meta.id)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods & Qt.KeyboardModifier.AltModifier:
            self.edit.emit(self.meta.id)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.emit(self.meta.id)
        elif k == Qt.Key.Key_F2 and not mods:
            self.rename.emit(self.meta.id)
        elif k == Qt.Key.Key_Menu or (k == Qt.Key.Key_F10
                                      and mods & Qt.KeyboardModifier.ShiftModifier):
            self.menu.emit(self.meta.id, self.mapToGlobal(self.rect().center()))
        elif k in arrows and not mods & (Qt.KeyboardModifier.ControlModifier
                                         | Qt.KeyboardModifier.AltModifier):
            self.step.emit(self, *arrows[k])
        else:
            super().keyPressEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.FontChange:
            self._font_key = self.font().key()
        super().changeEvent(e)

    def _fit_name(self, room: QRectF) -> tuple[QFont, Qt.AlignmentFlag, str]:
        """The name's font, flags and text: one line from the top, cut short with "…"
        when it doesn't fit (hovering the pad shows all of it). Wrapping it, or a size
        smaller, changed with the pad's width: a resize made names jump between one
        line and two."""
        key = (self.meta.name, room.width(), self._font_key)
        if self._name_fit is None or self._name_fit[0] != key:
            name = self.meta.name
            f = QFont(self.font())
            f.setBold(True)
            f.setPointSizeF(10.5)
            text = QFontMetrics(f).elidedText(name, Qt.TextElideMode.ElideRight,
                                              room.toRect().width())
            self._name_fit = (key, (f, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                    text))
            self.name_cut = text != name
        return self._name_fit[1]

    def _accent_colour(self) -> QColor:
        if self._accent[0] != self.meta.color:
            self._accent = (self.meta.color, QColor(self.meta.color))
        return self._accent[1]

    def _footer(self, foot: QRectF, name_font: QFont) -> tuple[QFont, str, tuple[str, int] | None]:
        """(font, the right-hand text, the hotkey badge's (text, width) or None): only
        worked out again when something it shows changes."""
        m = self.meta
        key = (m.fx, m.loop, m.mode, m.hold, m.duration, m.hotkey, self.paused,
               foot.width(), self._font_key)
        if self._foot[0] != key:
            f = QFont(name_font)
            f.setBold(False)
            f.setPointSizeF(8.5)
            flags = ("FX " if m.fx else "") + ("⟳ " if m.loop else "") + \
                {"overlap": "⧉ ", "toggle": "⏯ "}.get(m.mode, "") + \
                (_("hold") + " " if m.hold else "")
            right = _("paused") if self.paused else f"{flags}{m.duration:.1f}s"
            hk = _badge_text(m.hotkey)
            badge = None
            fm = QFontMetrics(f)
            # a cut-off key ("Ctrl+Al…") says nothing: no badge on a pad too narrow
            if hk and fm.horizontalAdvance(hk) + 12 <= foot.width() * 0.68:
                badge = (hk, fm.horizontalAdvance(hk) + 12)
            self._foot = (key, (f, right, badge))
        out = self._foot[1]
        assert out is not None   # made above
        return out

    @property
    def n_bands(self) -> int:
        return max(8, min(28, (self.width() - 20) // 9))

    def set_levels(self, levels):
        """New visualizer levels (None clears): bars jump up and fall back smoothly."""
        if levels is None:
            self.bands = self.peaks = None
            return
        levels = np.asarray(levels, np.float32)
        if self.bands is None or len(self.bands) != len(levels):
            self.bands, self.peaks = levels.copy(), levels.copy()
            return
        assert self.peaks is not None   # set with the bands
        self.bands = np.maximum(levels, self.bands * 0.78)
        self.peaks = np.maximum(self.bands, self.peaks - 0.025)

    def set_meter(self, v):
        """The level meter's new reading (None clears): up at once, down smoothly, so
        it reads as loudness rather than flicker; the peak mark falls slower still."""
        if v is None:
            self.meter, self.meter_peak = None, 0.0
            return
        v = min(max(float(v), 0.0), 1.0)
        self.meter = v if self.meter is None else max(v, self.meter * 0.86)
        self.meter_peak = max(self.meter, self.meter_peak - 0.012)

    def _on_hover_k(self, v):
        self._hover_k = float(v)
        self.update()

    def _fade_hover(self, on: bool):
        self.hover = on
        self._hover_anim.stop()
        if lite.on():   # (Lite mode: lit or not, no fade)
            self._on_hover_k(1.0 if on else 0.0)
            return
        self._hover_anim.setStartValue(self._hover_k)
        self._hover_anim.setEndValue(1.0 if on else 0.0)
        self._hover_anim.start()

    def enterEvent(self, e):
        self._fade_hover(True)
        if self.fresh:   # looked at: not new any more
            self.set_fresh(False)
            self.seen.emit(self.meta.id)

    def leaveEvent(self, e):
        self._down = False
        self._fade_hover(False)

    def _second_click(self, e) -> bool:
        """A second plain left click soon after the first, anywhere on the pad. Qt only
        counts a double-click when both land a few pixels apart, so top-left then
        bottom-right was two single clicks (and a drag if the mouse was still moving)."""
        return (not Pad.single_click and e.button() == Qt.MouseButton.LeftButton
                and not e.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                         | Qt.KeyboardModifier.ControlModifier)
                and time.monotonic() * 1000 - self._last_click
                <= QApplication.doubleClickInterval())

    def mousePressEvent(self, e):
        if self._second_click(e):
            self._last_click = -1e9   # a third click starts over
            self._press = None        # no drag, no select on release
            self._down = True
            self.update()
            self.activated.emit(self.meta.id)
        elif e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
            self._down = True
            self.update()
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu.emit(self.meta.id, e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        moved = self._press is not None and \
            (e.position().toPoint() - self._press).manhattanLength() > 12
        if moved:
            self._press = None
            self._down = False
            self.update()
            drag = QDrag(self)
            md = QMimeData()
            md.setData(PAD_MIME, self.meta.id.encode())
            drag.setMimeData(md)
            # half the pad's size on screen: grab() is in real pixels, so scaling it to
            # half the logical size made a 40 % preview on a 125 % screen
            shot = self.grab()
            dpr = shot.devicePixelRatio()
            half = shot.scaled(round(self.width() / 2 * dpr), round(self.height() / 2 * dpr),
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            half.setDevicePixelRatio(dpr)
            drag.setPixmap(half)
            drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if self._down:
            self._down = False
            self.update()
        if e.button() == Qt.MouseButton.LeftButton and self._press is not None:
            self._press = None
            mods = e.modifiers()
            if self._stop_hit(e.position()) is not None:
                self.stop_render.emit(self.meta.id)
                return
            if self.state == "rendering" and not mods & (Qt.KeyboardModifier.ShiftModifier
                                                         | Qt.KeyboardModifier.ControlModifier):
                self.activated.emit(self.meta.id)   # it says why it can't play yet
                return
            if not mods & (Qt.KeyboardModifier.ShiftModifier
                           | Qt.KeyboardModifier.ControlModifier):
                self._last_click = time.monotonic() * 1000
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.pick.emit(self.meta.id, True)
            elif mods & Qt.KeyboardModifier.ControlModifier:
                self.pick.emit(self.meta.id, False)
            elif Pad.single_click:
                self.activated.emit(self.meta.id)
            else:
                self.chosen.emit(self.meta.id)

    def wheelEvent(self, e):
        """Ctrl+wheel: the sound's volume. A plain wheel still scrolls the pads."""
        if not e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            e.ignore()
            return
        self._wheel += e.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            self.nudge.emit(self.meta.id, steps)
        e.accept()

    def mouseDoubleClickEvent(self, e):
        # Qt sends this in place of the second press: the same as a press (it plays when
        # it's a second click: _second_click; a quick second click is just another click
        # when one click plays)
        self.mousePressEvent(e)

    def paintEvent(self, e):
        self.describe()
        if self.height() <= ROW_MAX_H:
            self._paint_slim()
            return
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        accent = self._accent_colour()
        C = pad_colours()
        lo, hi, k = C["card"], C["card_hi"], self._hover_k
        if self._down:
            r.adjust(1.5, 1.5, -1.5, -1.5)
        elif k > 0.0:   # the mouse over it: it lifts off a soft shadow
            p.setPen(Qt.PenStyle.NoPen)
            for grow, alpha in ((0.0, 60), (1.0, 30), (2.0, 14)):   # a blur, cheaply
                p.setBrush(QColor(0, 0, 0, int(alpha * k)))
                p.drawRoundedRect(r.adjusted(-grow, HOVER_LIFT - grow + 0.5,
                                             grow, HOVER_LIFT + grow),
                                  PAD_RADIUS + grow, PAD_RADIUS + grow)
            r.translate(0, -HOVER_LIFT * k)
        base = lo if k <= 0.0 else hi if k >= 1.0 else _hover_mix(lo, hi, k)
        if self._down:
            base = base.darker(108)
        path = QPainterPath()
        path.addRoundedRect(r, PAD_RADIUS, PAD_RADIUS)
        p.fillPath(path, base)
        pic = self._picture(r)
        playing = self.progress is not None
        now = time.monotonic()
        if not playing:
            self._play_t = None
        elif self._play_t is None:
            self._play_t = now
        if pic is not None:   # already the pad's size, shade and corners: a plain copy
            p.drawPixmap(r.topLeft(), pic)
        else:   # its colour as a soft wash from the top, not a stripe
            tint = QLinearGradient(0, r.top(), 0, r.bottom())
            top, clear = QColor(accent), QColor(accent)
            top.setAlpha(32)
            clear.setAlpha(0)
            tint.setColorAt(0.0, top)
            tint.setColorAt(0.75, clear)
            p.fillPath(path, tint)
        if playing:
            p.save()
            p.setClipPath(path)
            done = QColor(accent)   # how far it's got: the card fills from the left
            done.setAlpha(34)
            progress = self.progress or 0.0   # (playing: set)
            p.fillRect(QRectF(r.left(), r.top(), r.width() * progress, r.height()), done)
            flash = 1 - (now - (self._play_t if self._play_t is not None else now)) / 0.35
            if flash > 0 and not lite.on():   # a quick wash of its colour as it starts
                wash = QColor(accent)
                wash.setAlpha(int(90 * flash))
                p.fillPath(path, wash)
            self._paint_visualizer(p, r, accent)
            self._paint_meter(p, r, accent)
            # progress: a thin accent line along the bottom edge
            p.fillRect(QRectF(r.left(), r.bottom() - 3, r.width() * progress, 3), accent)
            p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if playing:
            glow = QColor(accent)   # breathes while it plays
            glow.setAlpha(60 if self.paused else 105 if lite.on()   # (lite: steady)
                          else int(105 + 35 * math.sin(now * 5)))
            p.setPen(QPen(glow, 6))
            p.drawPath(path)
            ink = QColor(accent)
            if self.paused:   # paused: the same line, faded
                ink.setAlpha(110)
            pen = QPen(ink, 2.2)
            p.setPen(pen)
        elif self.picked:
            p.setPen(QPen(C["accent"], 2.4))
        elif self.fresh:   # new: a soft glow of the highlight colour inside its edge
            p.save()
            p.setClipPath(path)
            for width, alpha in ((12, 40), (7, 70)):
                halo = QColor(C["accent"])
                halo.setAlpha(alpha)
                p.setPen(QPen(halo, width))
                p.drawPath(path)
            p.restore()
            p.setPen(QPen(C["accent"], 2.2))
        elif self.selected:
            p.setPen(QPen(C["border_hi"], 1.6))
        else:   # at rest: no outline, the card's own shade is enough
            p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
        if self.picked:   # a tick in the corner, so it reads as picked while playing too
            c = QRectF(r.right() - 24, r.top() + 6, 18, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C["accent"])
            p.drawEllipse(c)
            tick = QPen(C["on_accent"], 2.2)   # white vanished on yellow accents
            tick.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(tick)
            p.drawPolyline([QPointF(c.left() + 5, c.center().y()),
                            QPointF(c.left() + 8, c.bottom() - 5),
                            QPointF(c.right() - 4, c.top() + 5)])
            p.setBrush(Qt.BrushStyle.NoBrush)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(C["text_hi"], 1.4))
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 10, 10)
        on_pic = pic is not None
        # name
        text_r = r.adjusted(10, 12, -10, -24)
        f, flags, name = self._fit_name(text_r)
        p.setFont(f)
        if on_pic:   # a soft shadow keeps it readable on any picture
            p.setPen(_SHADOW)
            p.drawText(text_r.translated(1, 1), flags, name)
            p.setPen(_WHITE if self.state == "ready" else _WHITE_DIM)
        else:
            p.setPen(C["text_hi"] if self.state == "ready" else C["muted"])
        p.drawText(text_r, flags, name)
        muted = _WHITE_MUTED if on_pic else C["muted"]
        # footer: hotkey + duration / state
        foot = r.adjusted(10, r.height() - 24, -10, -6)
        f, right, badge = self._footer(foot, f)
        p.setFont(f)
        self._link_rect = None
        self._stop_rect = None
        if self.state == "rendering" and self.render_frac is not None:
            self._paint_render(p, foot, QRectF(foot.left(), r.bottom() - 4.5, foot.width(), 3),
                               muted, on_pic, _("applying… {pct}%",
                                                pct=int(self.render_frac * 100)))
        elif self.state in ("loading", "rendering"):
            p.setPen(muted)
            p.drawText(foot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       _("applying effects…") if self.state == "rendering" else _("loading…"))
        elif self.state == "error":
            p.setPen(_ERROR_ON_PIC if on_pic else C["error_text"])   # readable on light
            p.drawText(foot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       _("can't load file"))
        else:
            p.setPen(muted)
            p.drawText(foot, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)
            fm = QFontMetrics(f)
            tw = fm.horizontalAdvance(right)
            if self.paused:
                _paint_pause(p, foot.right() - tw - 4, foot.center().y(), fm.capHeight(), muted)
                tw += PAUSE_W + 4
            # a small chain link just before the length, while the mouse is on the pad
            # only: on every pad it was noise ("is it a web link?")
            if self.hover and self.linked_file():
                x = foot.right() - tw - 5 - LINK_PX
                if x >= foot.left() + (badge[1] + 6 if badge is not None else 0):
                    box = QRectF(x, foot.center().y() - LINK_PX / 2, LINK_PX, LINK_PX)
                    p.drawPixmap(box.topLeft(), _link_pixmap(muted, self.devicePixelRatioF()))
                    self._link_rect = box
            if badge is not None:
                hk, w = badge
                box = QRectF(foot.left(), foot.top() + 1, w, foot.height() - 2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C["badge"])
                p.drawRoundedRect(box, 5, 5)
                p.setPen(C["badge_text"])
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, hk)

    def _picture(self, r: QRectF):
        """The pad's picture fitted to `r` in real pixels with its shade drawn on, or
        None. thumbs.fitted caches it by picture, size, screen and shade, so a resize,
        a press, a new picture, another screen or the mouse over it each get their own
        and nothing is scaled on an ordinary paint. None (the plain card) while the
        file is still being read."""
        if not self.meta.image:
            return None
        dpr = self.devicePixelRatioF()
        return thumbs.fitted(self.meta.image, math.ceil(r.width() * dpr),
                             math.ceil(r.height() * dpr), dpr,
                             PIC_SHADE_HOVER if self.hover else PIC_SHADE, PAD_RADIUS,
                             waiter=self)   # read off the UI thread: repainted when in

    def _paint_slim(self):
        """A one-line row: accent dot, name, duration; progress along the bottom."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        C = pad_colours()
        accent = self._accent_colour()
        base = _hover_mix(C["card"], C["card_hi"], self._hover_k)
        if self._down:
            base = base.darker(108)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.fillPath(path, base)
        playing = self.progress is not None
        if playing:
            p.save()
            p.setClipPath(path)
            wash = QColor(accent)
            wash.setAlpha(40)
            p.fillPath(path, wash)
            p.fillRect(QRectF(r.left(), r.bottom() - 2, r.width() * (self.progress or 0.0), 2),
                       accent)
            p.restore()
        if playing:
            ink = QColor(accent)
            if self.paused:   # paused: the same line, faded
                ink.setAlpha(110)
            pen = QPen(ink, 1.8)
        elif self.picked or self.fresh:   # (new: its glow, as a line)
            pen = QPen(C["accent"], 2)
        elif self.selected:
            pen = QPen(C["border_hi"], 1.4)
        else:
            pen = Qt.PenStyle.NoPen
        p.setPen(pen)
        p.drawPath(path)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(C["text_hi"], 1.2))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 5, 5)
        p.setPen(Qt.PenStyle.NoPen)
        dot = QRectF(r.left() + 9, r.center().y() - 4, 8, 8)
        if self.meter:   # the row's level meter: a halo round the dot, as loud as it is
            halo = QColor(accent)
            halo.setAlpha(60 if self.paused else 140)
            p.setBrush(halo)
            grow = 1 + 5 * self.meter
            p.drawEllipse(dot.adjusted(-grow, -grow, grow, grow))
        p.setBrush(C["accent"] if self.picked else accent)
        p.drawEllipse(dot)
        f = QFont(self.font())
        h = self.height()   # bigger rows (the list's row size), bigger text
        f.setPointSizeF(8.0 if h < SLIM_PAD_H else 8.5 if h < ROW_MAX_H else 9.5)
        p.setFont(f)
        fm = p.fontMetrics()
        self._stop_rect = None
        rendering = self.state == "rendering" and self.render_frac is not None
        if rendering:
            right = _("applying… {pct}%", pct=int((self.render_frac or 0.0) * 100))
            rc = C["muted"]
        elif self.state in ("loading", "rendering"):
            right = _("applying…") if self.state == "rendering" else _("loading…")
            rc = C["muted"]
        elif self.state == "error":
            right, rc = _("can't load"), _ERROR_ON_PIC
        else:
            m = self.meta
            flags = ("⟳ " if m.loop else "") + \
                {"overlap": "⧉ ", "toggle": "⏯ "}.get(m.mode, "")
            right = "" if self.paused else f"{flags}{m.duration:.1f}s"
            rc = C["muted"]
        rw = (PAUSE_W if right == "" else fm.horizontalAdvance(right)) + 4
        self._link_rect = None
        if self.state == "ready" and self.hover and self.linked_file() and r.width() >= 160:
            box = QRectF(r.right() - 9 - rw - 2 - LINK_PX, r.center().y() - LINK_PX / 2,
                         LINK_PX, LINK_PX)
            p.drawPixmap(box.topLeft(), _link_pixmap(C["muted"], self.devicePixelRatioF()))
            self._link_rect = box
            rw += LINK_PX + 6
        if rendering:   # the ✕ at the end, the bar along the bottom
            text_end = r.right() - 9
            if self.can_stop:
                text_end -= STOP_PX + 8
                rw += STOP_PX + 8
            self._paint_render(p, QRectF(r.left(), r.top(), r.right() - 9 - r.left(),
                                         r.height()),
                               QRectF(r.left() + 9, r.bottom() - 3, r.width() - 18, 2),
                               rc, False, None)
            p.setPen(rc)
            p.drawText(QRectF(r.left(), r.top(), text_end - r.left(), r.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)
        else:
            p.setPen(rc)
            p.drawText(r.adjusted(0, 0, -9, 0), Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, right)
            if right == "":
                _paint_pause(p, r.right() - 9, r.center().y(), fm.capHeight(), rc)
        hk = _badge_text(self.meta.hotkey)
        if hk and r.width() >= 200:   # the key as a badge left of the length, room allowing
            bw = fm.horizontalAdvance(hk) + 10
            if bw <= r.width() * 0.4:
                box = QRectF(r.right() - 9 - rw - 4 - bw, r.center().y() - 9, bw, 18)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C["badge"])
                p.drawRoundedRect(box, 5, 5)
                p.setPen(C["badge_text"])
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, hk)
                rw += bw + 8
        f.setBold(True)
        p.setFont(f)
        text_r = r.adjusted(24, 0, -14 - rw, 0)
        p.setPen(C["text_hi"] if self.state == "ready" else C["muted"])
        p.drawText(text_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.meta.name, Qt.TextElideMode.ElideRight,
                                              int(text_r.width())))

    def _stop_hit(self, pos: QPointF) -> QRectF | None:
        """The ✕'s target (grown to a finger's size) when `pos` is on it."""
        box = self._stop_rect
        if box is None or self.state != "rendering" or not self.can_stop:
            return None
        grow = max(0.0, (STOP_HIT_PX - box.width()) / 2)
        hit = box.adjusted(-grow, -grow, grow, grow)
        return hit if hit.contains(pos) else None

    def _paint_render(self, p: QPainter, row: QRectF, bar: QRectF, ink: QColor,
                      on_pic: bool, text: str | None):
        """An effects render in progress: `text` on the left of `row` (None: the caller
        writes it), its ✕ at the right end (when it can be stopped) and the bar."""
        x_w = STOP_PX if self.can_stop else 0
        hi = QColor(theme.T.get("text_hi", "#ffffff"))
        if text is not None:
            p.setPen(ink)
            tr = row.adjusted(0, 0, -(x_w + 6) if x_w else 0, 0)
            p.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight,
                                                  int(tr.width())))
        if x_w:
            c = QPointF(row.right() - x_w / 2, row.center().y())
            box = QRectF(c.x() - x_w / 2, c.y() - x_w / 2, x_w, x_w)
            self._stop_rect = box
            if self.hover:   # a soft disc behind it while the mouse is on the pad
                disc = QColor(_WHITE if on_pic else hi)
                disc.setAlpha(40)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(disc)
                p.drawEllipse(box.adjusted(-3, -3, 3, 3))
            pen = QPen((_WHITE if on_pic else hi) if self.hover else ink, 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            k = x_w * 0.3
            p.drawLine(QPointF(c.x() - k, c.y() - k), QPointF(c.x() + k, c.y() + k))
            p.drawLine(QPointF(c.x() - k, c.y() + k), QPointF(c.x() + k, c.y() - k))
        rad = bar.height() / 2
        groove = QColor(_WHITE if on_pic else theme.T.get("groove", "#343849"))
        if on_pic:
            groove.setAlpha(70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(groove)
        p.drawRoundedRect(bar, rad, rad)
        frac = min(1.0, max(0.0, self.render_frac or 0.0))
        if frac > 0:
            p.setBrush(QColor(theme.T.get("accent", "#7c5cff")))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(),
                                     max(bar.height(), bar.width() * frac), bar.height()),
                              rad, rad)

    def _paint_meter(self, p: QPainter, r: QRectF, accent: QColor):
        """A slim level meter up the card's left edge: how loud it is right now, with a
        peak mark. Its own colour, warming to amber then red near full scale."""
        if self.meter is None:
            return
        # from under the top corner to just above the footer (the hotkey badge)
        track = QRectF(r.left() + 4, r.top() + PAD_RADIUS, 3, r.height() - PAD_RADIUS - 28)
        p.setPen(Qt.PenStyle.NoPen)
        dim = QColor(accent)
        dim.setAlpha(40)
        p.setBrush(dim)
        p.drawRoundedRect(track, 1.5, 1.5)
        h = track.height() * self.meter
        if h >= 1.0:
            grad = QLinearGradient(0, track.bottom(), 0, track.top())
            grad.setColorAt(0.0, QColor(accent).lighter(115))
            grad.setColorAt(0.72, QColor(accent).lighter(130))
            grad.setColorAt(0.86, _METER_WARM)
            grad.setColorAt(1.0, _METER_HOT)
            if self.paused:
                p.setOpacity(0.45)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(track.left(), track.bottom() - h, track.width(), h),
                              1.5, 1.5)
            if self.meter_peak > self.meter + 0.02:
                y = track.bottom() - track.height() * self.meter_peak
                p.drawRect(QRectF(track.left(), y, track.width(), 1.5))
            p.setOpacity(1.0)

    def _paint_visualizer(self, p: QPainter, r: QRectF, accent: QColor):
        """Spectrum bars rising from the bottom, behind the text."""
        bands = self.bands
        if bands is None or not len(bands):
            return
        n = len(bands)
        area = r.adjusted(8, r.height() * 0.58, -8, -5)   # under the name, not through it
        gap = 2.0 if area.width() / n > 6 else 1.0
        bw = (area.width() - gap * (n - 1)) / n
        top, bottom = QColor(accent).lighter(135), QColor(accent)
        top.setAlpha(70 if self.paused else 150)
        bottom.setAlpha(15 if self.paused else 40)
        grad = QLinearGradient(0, area.top(), 0, area.bottom())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        rad = min(bw / 2, 2.5)
        for i, lv in enumerate(bands):
            x = area.left() + i * (bw + gap)
            h = max(2.0, float(lv) * area.height())
            p.drawRoundedRect(QRectF(x, area.bottom() - h, bw, h), rad, rad)
        if self.peaks is not None:
            cap = QColor(accent).lighter(160)
            cap.setAlpha(70 if self.paused else 160)
            p.setBrush(cap)
            for i, pk in enumerate(self.peaks):
                x = area.left() + i * (bw + gap)
                y = area.bottom() - max(2.0, float(pk) * area.height()) - 4
                p.drawRoundedRect(QRectF(x, y, bw, 2), 1, 1)
