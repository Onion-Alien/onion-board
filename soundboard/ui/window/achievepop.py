"""The "Achievement unlocked" pop-up: the classic console toast at the bottom middle of
the screen, over games and other apps, as an achievement is earned.

A glossy green orb pops in, a dark rounded bar slides out of it with "Achievement
unlocked" and "<points>G - <name>", it stays a few seconds, then folds back into the orb
and the orb shrinks away. Its chime (audio/achievechime.py), when Settings >
Achievements has it on (off by default), plays in your headphones
only. It never takes focus or clicks (a game in front keeps them). Several at once
queue up and show one after another.

The look is the same in every theme on purpose (it's the console's toast, not a card of
the app), so its colours are fixed here rather than theme tokens."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication,
                           QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid as qt_valid

from soundboard.core import achievements
from soundboard.i18n import _
from soundboard.ui.kit import icons

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

# points per rarity, the console's usual steps
POINTS = {"common": 10, "uncommon": 20, "rare": 30, "legendary": 50, "super": 100}

BAR_H = 58          # the dark bar's height
ORB = 70            # the green orb, a little taller than the bar it sits on
PAD = 10            # room around it for the shadow and the orb's overshoot
MIN_W = 340
START_MS = 4000     # nothing pops while the app is still starting (the splash)
GAP_MS = 450        # between two queued pop-ups

# the timeline (ms): the orb pops, the bar slides out, the words fade in; then back
ORB_IN = (0, 260)
BAR_OUT = (200, 620)
TEXT_IN = (480, 720)
TEXT_OUT = (4500, 4700)
BAR_IN = (4620, 4980)
ORB_OUT = (4960, 5220)
TOTAL = 5240

BAR_TOP, BAR_MID, BAR_BOTTOM = QColor("#4d4f52"), QColor("#2a2b2d"), QColor("#161718")
ORB_LIGHT, ORB_MID, ORB_DARK = QColor("#c5f75a"), QColor("#6cc416"), QColor("#2e7a05")


def _phase(t: float, span: tuple[int, int]) -> float:
    a, b = span
    return min(1.0, max(0.0, (t - a) / (b - a)))


_OUT_BACK = QEasingCurve(QEasingCurve.Type.OutBack)
_OUT_CUBIC = QEasingCurve(QEasingCurve.Type.OutCubic)
_IN_CUBIC = QEasingCurve(QEasingCurve.Type.InCubic)


def shape_at(t: float) -> tuple[float, float, float]:
    """(orb scale, bar open 0..1, words opacity 0..1) `t` ms into the pop-up."""
    if t < ORB_OUT[0]:
        orb = _OUT_BACK.valueForProgress(_phase(t, ORB_IN))
    else:
        orb = 1.0 - _IN_CUBIC.valueForProgress(_phase(t, ORB_OUT))
    if t < BAR_IN[0]:
        bar = _OUT_CUBIC.valueForProgress(_phase(t, BAR_OUT))
    else:
        bar = 1.0 - _IN_CUBIC.valueForProgress(_phase(t, BAR_IN))
    words = _phase(t, TEXT_IN) - _phase(t, TEXT_OUT)
    return orb, bar, max(0.0, min(1.0, words))


def words(aid: str) -> tuple[str, str]:
    """The pop-up's two lines for achievement `aid`."""
    from soundboard.ui.settings.achievements import texts
    a = achievements.BY_ID[aid]
    name = texts().get(aid, (aid, ""))[0]
    return _("Achievement unlocked"), _("{points}G - {name}", points=POINTS[a.tier],
                                        name=name)


class AchievementPop(QWidget):
    """One pop-up on screen at a time; show_one() runs it from the start."""
    finished = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Onion Board")
        self.top, self.bottom = "", ""
        self.t = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)
        self._top_font = QFont(self.font())
        self._top_font.setPointSizeF(10.0)
        self._bottom_font = QFont(self.font())
        self._bottom_font.setPointSizeF(12.5)
        self._bottom_font.setBold(True)
        self._icon = icons.pixmap("trophy", int(ORB * 0.46), "#ffffff")

    def show_one(self, top: str, bottom: str, t: float = 0.0):
        """Show these two lines from `t` ms in (tests start part-way)."""
        self.top, self.bottom = top, bottom
        text_w = max(QFontMetrics(self._top_font).horizontalAdvance(top),
                     QFontMetrics(self._bottom_font).horizontalAdvance(bottom))
        w = max(MIN_W, PAD + ORB + 14 + text_w + BAR_H // 2 + PAD)
        self.resize(w, ORB + 2 * PAD)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            self.move(g.center().x() - w // 2,
                      g.bottom() - self.height() - int(g.height() * 0.09))
        self.t = t
        self._clock.restart()
        self._start = t
        self._timer.start()
        self.show()
        self.raise_()
        self.update()

    def _step(self):
        self.t = self._start + self._clock.elapsed()
        if self.t >= TOTAL:
            self._timer.stop()
            self.hide()
            self.finished.emit()
            return
        self.update()

    def paintEvent(self, _ev):
        orb, bar, alpha = shape_at(self.t)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cy = self.height() / 2
        cx = PAD + ORB / 2
        if bar > 0.001:
            self._paint_bar(p, cx, cy, bar, alpha)
        if orb > 0.001:
            self._paint_orb(p, cx, cy, orb)
        p.end()

    def _paint_bar(self, p: QPainter, cx: float, cy: float, bar: float, alpha: float):
        full = self.width() - PAD - cx
        rect = QRectF(cx - BAR_H / 2, cy - BAR_H / 2, BAR_H / 2 + full * bar, BAR_H)
        r = BAR_H / 2
        # a soft shadow under it
        for i, a in ((5, 18), (3, 30), (1, 45)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(rect.adjusted(-i, -i + 2, i, i + 2), r + i, r + i)
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        g.setColorAt(0.0, BAR_TOP)
        g.setColorAt(0.48, BAR_MID)
        g.setColorAt(1.0, BAR_BOTTOM)
        p.setBrush(g)
        p.setPen(QPen(QColor(255, 255, 255, 46), 1.0))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        # the glassy shine on its top half
        shine = QPainterPath()
        shine.addRoundedRect(rect.adjusted(3, 2, -3, -BAR_H / 2), r - 3, r - 3)
        sg = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.center().y()))
        sg.setColorAt(0.0, QColor(255, 255, 255, 46))
        sg.setColorAt(1.0, QColor(255, 255, 255, 4))
        p.fillPath(shine, sg)
        if alpha <= 0.001:
            return
        p.save()
        p.setClipRect(rect.adjusted(0, 0, -r / 2, 0))
        p.setOpacity(alpha)
        x = cx + ORB / 2 + 12
        p.setPen(QColor(255, 255, 255, 220))
        p.setFont(self._top_font)
        top_fm = QFontMetrics(self._top_font)
        bottom_fm = QFontMetrics(self._bottom_font)
        gap = 2
        block = top_fm.height() + gap + bottom_fm.height()
        y = cy - block / 2
        p.drawText(QPointF(x, y + top_fm.ascent()), self.top)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._bottom_font)
        p.drawText(QPointF(x, y + top_fm.height() + gap + bottom_fm.ascent()), self.bottom)
        p.restore()

    def _paint_orb(self, p: QPainter, cx: float, cy: float, scale: float):
        d = ORB * scale
        rect = QRectF(cx - d / 2, cy - d / 2, d, d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(rect.adjusted(-1, 1, 1, 3))
        g = QRadialGradient(QPointF(cx - d * 0.12, cy - d * 0.2), d * 0.68)
        g.setColorAt(0.0, ORB_LIGHT)
        g.setColorAt(0.55, ORB_MID)
        g.setColorAt(1.0, ORB_DARK)
        p.setBrush(g)
        p.setPen(QPen(QColor(20, 60, 0, 170), max(1.0, 2.0 * scale)))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        size = self._icon.width() * scale
        if size >= 2:
            p.drawPixmap(QRectF(cx - size / 2, cy - size / 2 + d * 0.02, size, size),
                         self._icon, QRectF(self._icon.rect()))
        # the glossy cap over the top
        cap = QRectF(cx - d * 0.36, cy - d * 0.45, d * 0.72, d * 0.42)
        cg = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        cg.setColorAt(0.0, QColor(255, 255, 255, 150))
        cg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(cg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cap)


class AchievementPops(QObject):
    """Listens for earned achievements (from any thread) and shows them one by one,
    with the chime in the headphones when Settings > Achievements has it on."""
    earned = Signal(str)

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.mw = mw
        self.queue: list[str] = []
        self.pop: AchievementPop | None = None
        self.showing = False
        self.ready = False
        self.earned.connect(self._add)   # queued when it comes from another thread
        achievements.on_unlock.append(self._heard)
        QTimer.singleShot(START_MS, self, self._start)

    def _heard(self, aid: str):
        if qt_valid(self):
            self.earned.emit(aid)
        else:   # its window went without shutdown() (tests): stop listening
            self.shutdown()

    def _start(self):
        self.ready = True
        self._next()

    def _add(self, aid: str):
        cfg = getattr(self.mw, "cfg", None)
        if not getattr(cfg, "achievement_popups", True):
            return   # (turned off in Settings > Achievements: still earned, just quiet)
        if aid in achievements.BY_ID:
            self.queue.append(aid)
            self._next()

    def _next(self):
        if not self.ready or self.showing or not self.queue or getattr(
                self.mw, "_shut_down", False):
            return
        aid = self.queue.pop(0)
        if self.pop is None:
            self.pop = AchievementPop()
            self.pop.finished.connect(self._done)
        self.showing = True
        self.pop.show_one(*words(aid))
        self._chime()

    def _chime(self):
        from soundboard.audio import achievechime
        engine = getattr(self.mw, "engine", None)
        cfg = getattr(self.mw, "cfg", None)
        if engine is None or not getattr(cfg, "achievement_sound", False):
            return   # (off by default: Settings > Achievements turns it on)
        # preview=True: the headphones only, never the mic or the call
        engine.play("__achievement__", achievechime.chime(), 1.0, mode="restart",
                    preview=True)

    def _done(self):
        self.showing = False
        QTimer.singleShot(GAP_MS, self, self._next)

    def shutdown(self):
        try:
            achievements.on_unlock.remove(self._heard)
        except ValueError:
            pass
        self.queue.clear()
        if self.pop is not None and qt_valid(self.pop):
            self.pop.close()
            self.pop.deleteLater()
        self.pop = None
