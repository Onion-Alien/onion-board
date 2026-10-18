"""Boxes that fold away and fold out instead of blinking out of a card, and a green
flash on a box whose news just turned good. Used by the Setup tab's mic card: setting
up the mic swapped three boxes at once, and all anyone saw was boxes vanishing.

`set_shown(widget, on)`: the widget fades out, then its height slides to 0 and it's
hidden (or its height slides out from 0, then it fades in). Called again with the same
answer it does nothing, so a status redraw once a second can call it every time.
Instant when Windows' animation effects are off, or nobody can see it (a hidden tab).

`flash(box, at)`: the box lights up in the theme's "ok" colour, a band of light sweeps
across it and a ring pops out of `at` (its tick), then it all fades out. Skipped when
animations are off."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from soundboard.ui.kit import theme

FOLD_MS = 340    # folding away or out, fade included
FOLD_PART = 0.55  # of it, the height changing (the rest: fading)
FLASH_MS = 1100  # the "it worked" flash
MAX_H = 16777215  # Qt's QWIDGETSIZE_MAX: no maximum height


def _animate() -> bool:
    from soundboard.ui.kit.toast import animations_on
    return animations_on()


def _natural_height(w: QWidget) -> int:
    width = w.width()
    parent = w.parentWidget()
    if width <= 1 and parent is not None:   # (not laid out yet: its parent's inside)
        width = parent.contentsRect().width()
    lay = w.layout()
    if w.hasHeightForWidth():
        return max(0, w.heightForWidth(width))
    if lay is not None and lay.hasHeightForWidth():
        return max(0, lay.totalHeightForWidth(width))
    return max(0, w.sizeHint().height())


def shown(w: QWidget) -> bool:
    """Where `w` is going: shown, or folding out (False while it folds away)."""
    target = w.property("reveal_target")
    return bool(target) if target is not None else not w.isHidden()


def set_shown(w: QWidget, on: bool):
    """Fold `w` out (on) or away, unless it's already there or on its way."""
    target = w.property("reveal_target")
    if target is not None and bool(target) == on:
        return   # (on its way already)
    if target is None and w.isHidden() != on:
        return   # (there already)
    anim: QVariantAnimation | None = getattr(w, "_reveal_anim", None)
    if anim is not None:
        anim.stop()
    parent = w.parentWidget()
    if not _animate() or parent is None or not parent.isVisible():
        _finish(w, on)
        w.setVisible(on)
        return
    start = w.height() if not w.isHidden() else 0
    if w.isHidden():
        w.setMaximumHeight(0)
        w.show()
    end = _natural_height(w) if on else 0
    fx = w.graphicsEffect()
    if not isinstance(fx, QGraphicsOpacityEffect):
        fx = QGraphicsOpacityEffect(w)
        fx.setOpacity(0.0 if on else 1.0)
        w.setGraphicsEffect(fx)
    w.setProperty("reveal_target", on)
    anim = QVariantAnimation(w)
    anim.setDuration(FOLD_MS)
    # going away: it fades out at full height, then the empty space folds; coming
    # out, the reverse (a layout squeezed smaller than its words drew them on top
    # of each other)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.Linear)
    curve = QEasingCurve(QEasingCurve.Type.InOutCubic)

    def step(k):
        if on:
            fold, fade = min(1.0, k / FOLD_PART), max(0.0, (k - FOLD_PART) / (1 - FOLD_PART))
        else:
            fade, fold = min(1.0, k / (1 - FOLD_PART)), max(0.0, (k - (1 - FOLD_PART)) / FOLD_PART)
        h = start + (end - start) * curve.valueForProgress(fold)
        w.setMaximumHeight(round(h))
        fx.setOpacity(fade if on else 1 - fade)
    anim.valueChanged.connect(step)
    anim.finished.connect(lambda: _done(w, on))
    w._reveal_anim = anim   # pyright: ignore[reportAttributeAccessIssue]
    anim.start()


def _done(w: QWidget, on: bool):
    _finish(w, on)
    if not on:
        w.hide()


def _finish(w: QWidget, on: bool):
    w.setProperty("reveal_target", None)
    w.setMaximumHeight(MAX_H)
    if isinstance(w.graphicsEffect(), QGraphicsOpacityEffect):
        # (Qt deletes the effect; None is what clears it, PySide's stub misses it)
        w.setGraphicsEffect(None)   # pyright: ignore[reportArgumentType]
    w._reveal_anim = None   # pyright: ignore[reportAttributeAccessIssue]


class _Flash(QWidget):
    """Painted over a box for one flash, then gone."""

    def __init__(self, box: QWidget, at: QPointF):
        super().__init__(box)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(box.rect())
        self._at = at
        self._k = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(FLASH_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self._anim.start()

    def _step(self, k):
        self._k = float(k)
        box = self.parentWidget()
        if box is not None:
            self.setGeometry(box.rect())   # (the box can grow meanwhile)
        self.update()

    def paintEvent(self, ev):
        k = self._k
        ok = QColor(theme.T.get("ok_text", "#22c55e"))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # the box: lit up at once, then fading (slowest at the end)
        glow = (1 - k) ** 2
        fill = QColor(ok)
        fill.setAlphaF(0.16 * glow)
        edge = QColor(ok)
        edge.setAlphaF(0.85 * glow)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(edge, 2))
        p.setBrush(fill)
        p.drawRoundedRect(r, 10, 10)
        # a band of light sweeping across it, left to right, in the first half
        sweep = min(1.0, k / 0.55)
        if sweep < 1.0:
            x = r.left() - 120 + (r.width() + 240) * sweep
            band = QLinearGradient(x - 90, 0, x + 90, 0)
            lit = QColor(ok)
            lit.setAlphaF(0.22 * (1 - sweep * 0.5))
            clear = QColor(ok)
            clear.setAlphaF(0.0)
            band.setColorAt(0.0, clear)
            band.setColorAt(0.5, lit)
            band.setColorAt(1.0, clear)
            shape = QPainterPath()
            shape.addRoundedRect(r, 10, 10)
            p.fillPath(shape, band)
        # a ring popping out of the tick (small: it stays inside the box)
        room = max(4.0, min(self._at.y(), self.height() - self._at.y()) - 3)
        t = min(1.0, k / 0.7)
        ring = QColor(ok)
        ring.setAlphaF(0.9 * (1 - t) ** 1.5)
        radius = 10 + (room - 10) * (1 - (1 - t) ** 3)
        p.setPen(QPen(ring, 2.0 * (1 - t) + 0.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(self._at, radius, radius)
        p.end()


def flash(box: QWidget, at: QWidget | None = None):
    """Light `box` up green, a ring spreading from `at` (a widget in it, its tick)."""
    if not _animate() or not box.isVisible():
        return
    old = box.findChild(_Flash)
    if old is not None:
        old.deleteLater()
    centre = (QPointF(at.mapTo(box, at.rect().center())) if at is not None
              else QPointF(box.rect().center()))
    _Flash(box, centre)
