"""The player's seek row: the crisp slider, the click-to-seek slider, the sound name
beside it, and the time text."""
from __future__ import annotations

import math

from PySide6.QtCore import (QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer)
from PySide6.QtGui import (QColor, QPainter, QPen)
from PySide6.QtWidgets import (QLabel, QSlider, QStyle, QStyleOptionSlider, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.ui.kit import theme
from soundboard.i18n import _


class CrispSlider(QSlider):
    """Themed horizontal slider with a circle aligned to physical pixels."""

    def paintEvent(self, e):
        if self.orientation() != Qt.Orientation.Horizontal:
            return super().paintEvent(e)
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                      QStyle.SubControl.SC_SliderHandle, self)
        groove = QRectF(style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                            QStyle.SubControl.SC_SliderGroove, self))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["groove"]))
        radius = groove.height() / 2
        p.drawRoundedRect(groove, radius, radius)
        if self.isEnabled() and self.sliderPosition() > self.minimum():
            fill = QRectF(groove)
            if opt.upsideDown:
                fill.setLeft(handle.center().x())
            else:
                fill.setRight(handle.center().x())
            p.setBrush(QColor(theme.T["accent" if self.objectName() == "seek" else "muted"]))
            p.drawRoundedRect(fill, radius, radius)
        # A stylesheet's rounded box with a transparent border leaves a soft rim.
        # Paint one circle instead, with its bounds on physical pixel boundaries.
        transform = p.deviceTransform()
        scale = transform.m11()
        bounds = transform.mapRect(QRectF(handle))
        diameter = math.floor(min(bounds.width(), bounds.height()) + 0.5)
        x = math.floor(bounds.center().x() - diameter / 2 + 0.5)
        y = math.floor(bounds.center().y() - diameter / 2 + 0.5)
        circle = QRectF((x - transform.dx()) / scale, (y - transform.dy()) / scale,
                        diameter / scale, diameter / scale)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["text_hi" if self.isEnabled() else
                                 ("off" if self.objectName() == "seek" else "inset")]))
        p.drawEllipse(circle)
        hovered = opt.activeSubControls == QStyle.SubControl.SC_SliderHandle
        if self.isEnabled() and (self.hasFocus() or hovered or self.isSliderDown()):
            ring = self.hasFocus() or self.isSliderDown()   # Tab, or held by the mouse
            width = 2 if ring else 1
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(theme.T["accent" if ring else "border_hi"]), width))
            p.drawEllipse(circle.adjusted(width / 2, width / 2, -width / 2, -width / 2))


class SeekSlider(CrispSlider):
    """Slider that jumps straight to where you click (then drags from there)."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setAccessibleName(_("Playback position"))   # a screen reader said nothing on it
        # at 0:00 Qt still paints a sliver of fill beside the handle (it looked a few
        # seconds in): the theme hides the fill while "atstart" is set
        self.setProperty("atstart", True)

    def sliderChange(self, change):
        super().sliderChange(change)
        if change not in (QSlider.SliderChange.SliderValueChange,
                          QSlider.SliderChange.SliderRangeChange):
            return
        # Playback blocks signals to avoid seeking on each tick. This virtual
        # callback still runs, so the fill follows both playback and user input.
        at = self.value() <= self.minimum()
        if self.property("atstart") != at:   # restyle only when it flips, not every tick
            self.setProperty("atstart", at)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setValue(QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(e.position().x()), self.width()))
        super().mousePressEvent(e)


class EdgeMatch(QObject):
    """Trim the seek slider to the output meter's end when they are close.

    Only the manually placed slider gives up space. Changing a spacer in the
    meter's layout feeds back into that row's minimum width; at its limit the
    added space cannot shrink the meter, so matching again adds more space until
    MAX removes it and the cycle starts over.
    """

    MAX = 24

    def __init__(self, a: QWidget, pad_a, b: QWidget):
        super().__init__(a)
        self._bars = (a, b)
        self._set_pad = pad_a
        self._pad = 0
        self._queued = False
        for w in (a, b):
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show,
                            QEvent.Type.Hide) and not self._queued:
            self._queued = True   # after the layouts have placed both
            QTimer.singleShot(0, self, self.match)
        return False

    def match(self):
        self._queued = False
        bars = self._bars
        if not all(qt_valid(w) for w in bars):
            return
        pad = 0
        win = bars[0].window()
        if (all(w.isVisible() and w.isLeftToRight() and w.window() is win for w in bars)):
            ends = [w.mapTo(win, QPoint(w.width(), 0)).x() for w in bars]
            give = ends[0] + self._pad - ends[1]
            if 0 <= give <= self.MAX:
                pad = give
        if pad != self._pad:
            self._pad = pad
            self._set_pad(pad)


class NameAndSeek(QWidget):
    """The player's sound name with its seek slider right after it: the name is only
    as wide as its text (up to ``max_name``) and the slider takes the rest. Placed by
    hand, so a new name never changes this widget's size hint: the name changes with
    every pad press, and a hint change would lay out the whole page again."""

    GAP = 10
    SEEK_MIN = 120   # the slider, at the least

    def __init__(self, name: QLabel, seek: QWidget, max_name: int, parent=None):
        super().__init__(parent)
        self.name, self.seek, self.max_name = name, seek, max_name
        self.full = name.text()   # the whole name: the label shows it cut to fit, with "…"
        self.pad_right = 0   # room left after the slider (EdgeMatch)
        name.setParent(self)
        seek.setParent(self)
        name.installEventFilter(self)

    def sizeHint(self):
        return QSize(self.max_name + 120, max(self.name.height(), self.seek.sizeHint().height()))

    def minimumSizeHint(self):
        # honest, so the window's fitter hides other things (or the name) before the
        # slider gets too short to aim at or the name is cut: the name as it is now (up
        # to max_name). Not announced on a new name (no relayout per pad press): the
        # fitter measures it fresh on the next resize
        # (asked while the window closes too: nothing here may raise, overridepin.py)
        if not (qt_valid(self.name) and qt_valid(self.seek)):
            return QSize(self.SEEK_MIN, 0)
        name = 0 if self.name.isHidden() else self.GAP + min(
            self.max_name, self.name.fontMetrics().horizontalAdvance(self.full) + 4)
        return QSize(self.SEEK_MIN + name, self.sizeHint().height())

    def set_text(self, text: str):
        """A new name: cut to the room it gets (relayout)."""
        self.full = text
        self.relayout()

    def relayout(self):
        h = self.height()
        self.name.ensurePolished()   # (its bold comes from a style sheet: measure in bold)
        fm = self.name.fontMetrics()
        w = 0 if self.name.isHidden() else min(
            self.max_name, fm.horizontalAdvance(self.full) + 4,
            max(0, self.width() - self.SEEK_MIN - self.GAP))
        # cut where the label ends, with "…": squeezed by a narrow window, the label
        # cut a name cut for the widest room mid-letter
        # (not laid out yet: cut for the widest room, as the next resize lays it out)
        room = w if self.isVisible() and not self.name.isHidden() else self.max_name
        self.name.setText(fm.elidedText(self.full, Qt.TextElideMode.ElideRight,
                                        max(0, room - 4)))
        self.name.setGeometry(0, 0, w, h)
        sh = self.seek.sizeHint().height()
        x = w + self.GAP if not self.name.isHidden() else 0
        self.seek.setGeometry(x, (h - sh) // 2,
                              max(0, self.width() - self.pad_right - x), sh)

    def set_pad_right(self, px: int):
        self.pad_right = px
        self.relayout()

    def eventFilter(self, obj, event):
        if obj is self.name and event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.updateGeometry()   # the minimum has room for the name or not
            self.relayout()
        return super().eventFilter(obj, event)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def showEvent(self, e):
        super().showEvent(e)
        self.relayout()   # a name set while hidden was cut for the widest room

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.relayout()


def fmt_time(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


def fmt_pos(pos: float, total: float) -> str:
    if total < 60:  # short clips: tenths of a second are more useful
        return f"{max(pos, 0):.1f}s / {total:.1f}s"
    return f"{fmt_time(pos)} / {fmt_time(total)}"
