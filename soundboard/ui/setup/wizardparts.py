"""The setup guide's own widgets: the step bar, the page stack that fades between
steps, the scroll area round it and the cable step's status card."""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QScrollArea, QVBoxLayout, QWidget)

from soundboard.ui.kit import theme
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.kit.toast import animations_on
from soundboard.ui.setup.wizardkit import PAGE_MS, STEP_MS


class StepBar(QWidget):
    """Where you are in the guide: one short bar per step, the ones done and the
    current one in the accent colour (painted, so it follows the theme)."""
    SEG_W, SEG_H, GAP = 28, 4, 4

    def __init__(self, steps: int):
        super().__init__()
        self.steps, self.current = steps, 0
        self._shown = 0.0   # where the fill is (it slides to `current`)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(STEP_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._slide)
        self.setFixedSize(steps * self.SEG_W + (steps - 1) * self.GAP, self.SEG_H)

    def set_step(self, i: int):
        self.current = i
        self._anim.stop()
        if animations_on() and self.isVisible():
            self._anim.setStartValue(self._shown)
            self._anim.setEndValue(float(i))
            self._anim.start()
        else:
            self._slide(float(i))

    def _slide(self, v):
        self._shown = float(v)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        t = theme.T
        for i in range(self.steps):
            seg = QRectF(i * (self.SEG_W + self.GAP), 0, self.SEG_W, self.SEG_H)
            p.setBrush(QColor(t["card_hi"]))
            p.drawRoundedRect(seg, 2, 2)
            fill = min(1.0, max(0.0, self._shown + 1 - i))   # the step on: full
            if fill > 0:
                p.setBrush(QColor(t["accent"]))
                p.drawRoundedRect(QRectF(seg.x(), 0, seg.width() * fill, self.SEG_H), 2, 2)


class _PageStack(QWidget):
    """The steps, one shown at a time, sized by the one showing: a QStackedWidget
    measures itself by its tallest page (its layout asks every page), so a short step
    sat above an empty band. Here the others are hidden, and a hidden widget takes no
    room (DESIGN.md: a multi-step dialog shrinks to the current page). The calls the
    guide uses are QStackedWidget's."""
    currentChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._pages: list[QWidget] = []
        self._current = -1

    def addWidget(self, page: QWidget) -> int:
        self._pages.append(page)
        self._lay.addWidget(page)
        if self._current < 0:
            self._current = 0
        else:
            page.hide()
        return len(self._pages) - 1

    def count(self) -> int:
        return len(self._pages)

    def widget(self, i: int) -> QWidget | None:
        return self._pages[i] if 0 <= i < len(self._pages) else None

    def currentIndex(self) -> int:
        return self._current

    def currentWidget(self) -> QWidget | None:
        return self.widget(self._current)

    def setCurrentIndex(self, i: int):
        if not 0 <= i < len(self._pages) or i == self._current:
            return
        old, self._current = self.currentWidget(), i
        # the old one goes first: with both shown for a moment, Qt grew the window to
        # fit the two (to the screen's height, moved up) before it shrank back
        if old is not None:
            old.hide()
            if old.graphicsEffect() is not None:   # (left mid-fade)
                old.setGraphicsEffect(None)   # pyright: ignore[reportArgumentType]
        page = self._pages[i]
        page.show()
        if animations_on() and self.isVisible():
            fx = QGraphicsOpacityEffect(page)
            fx.setOpacity(0.0)
            page.setGraphicsEffect(fx)
            anim = QVariantAnimation(fx)
            anim.setDuration(PAGE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(fx.setOpacity)
            # (the effect off once it's in: it paints the page through a picture)
            anim.finished.connect(lambda p=page, f=fx: p.graphicsEffect() is f
                                  and p.setGraphicsEffect(None))  # pyright: ignore[reportArgumentType]
            anim.start()
        self.currentChanged.emit(i)


class _StepScroll(QScrollArea):
    """The steps, scrolling when the window can't be tall enough for one (1920x1080 at
    150% scaling: 1280x672): Qt squeezed the page instead, and its fixed-size tiles
    drew over each other and over the words. As tall as the step needs otherwise, so
    the guide sizes to it as before (fit.py). Its scroll bar sits in the guide's right
    margin (ROOM), so the pages keep their edges on Back's and Next's either way."""
    ROOM = 18   # the bar (10 px, theme.py) and the gap before the page (DESIGN.md: 8)

    def __init__(self, stack: QWidget):
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self._page = stack   # (before setWidget: that already filters its events)
        self.setWidget(stack)
        stack.installEventFilter(self)
        self.verticalScrollBar().rangeChanged.connect(self._room)
        self._room()

    def _room(self, *_a):
        """The page's right margin: ROOM, less the bar's width while it shows."""
        bar = self.verticalScrollBar()
        shown = bar.maximum() > 0
        lay = self._page.layout()
        if lay is not None:
            lay.setContentsMargins(0, 0, self.ROOM - (bar.sizeHint().width() if shown else 0), 0)

    def eventFilter(self, obj, ev):
        if obj is self._page and ev.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()   # the step changed: the guide asks again (fit.py)
        return super().eventFilter(obj, ev)   # (its own: the bar follows the page)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        lay = self._page.layout()
        if lay is not None and lay.hasHeightForWidth():
            return max(lay.totalHeightForWidth(w), lay.totalMinimumSize().height())
        return self._page.sizeHint().height()

    def sizeHint(self) -> QSize:
        page = self._page.sizeHint()
        return QSize(page.width(), self.heightForWidth(max(self.width(), page.width())))

    def minimumSizeHint(self) -> QSize:
        # as wide as the page needs (the tiles set the guide's width), never squeezed
        # below the page: only short, it scrolls
        return QSize(self._page.minimumSizeHint().width(), 80)


class StatusCard(QFrame):
    """Step 3's answer to "is it working?": a round badge (a tick, a ! or dots), an
    optional bold line, the status words and a pill, on a card tinted with the
    state's colour ("ok", "warn", "busy" or "" for not set up). Before, a green
    "On your mic." at the start of a sentence was all there was."""
    BADGE = 32

    def __init__(self, text: QLabel):
        super().__init__()
        self.tone = ""
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 14)
        h.setSpacing(12)
        self._badge = QWidget()   # painted by the card (paintEvent)
        self._badge.setFixedSize(self.BADGE, self.BADGE)
        self._badge.setStyleSheet("background:transparent;")
        h.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size:11pt; font-weight:700;")   # Standard kit: Large
        col.addWidget(self.title)
        col.addWidget(text)
        self.action_box = QVBoxLayout()   # a button that belongs to the state (Repair...)
        self.action_box.setContentsMargins(0, 4, 0, 0)
        col.addLayout(self.action_box)
        h.addLayout(col, 1)
        self.pill = QLabel()
        h.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)

    def _colour(self) -> QColor:
        t = theme.T
        return QColor({"ok": t["ok_text"], "warn": t["warn_text"],
                       "busy": t["accent"]}.get(self.tone, t["muted"]))

    def set_state(self, tone: str, pill: str, title: str = ""):
        self.tone = tone
        self.title.setText(title)
        self.title.setVisible(bool(title))
        c = self._colour()
        self.pill.setText(pill)
        self.pill.setVisible(bool(pill))
        self.pill.setStyleSheet(
            f"background:rgba({c.red()},{c.green()},{c.blue()},45); color:{c.name()}; "
            "border-radius:10px; padding:3px 10px; font-size:8pt; font-weight:600;")
        self.update()

    def paintEvent(self, ev):
        t = theme.T
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect())
        p.setBrush(QColor(t["panel"]))
        p.drawRoundedRect(r, 12, 12)
        c = self._colour()
        tint = QColor(c)
        tint.setAlpha(28 if self.tone else 0)
        p.setBrush(tint)
        p.drawRoundedRect(r, 12, 12)
        b = QRectF(self._badge.geometry())
        p.setBrush(c)
        p.drawEllipse(b)
        pen = QPen(QColor(t["on_accent"] if self.tone == "busy" else t["bg"]), 2.6,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = b.center().x(), b.center().y()
        if self.tone == "ok":
            p.drawPolyline([QPointF(cx - 6, cy), QPointF(cx - 1.5, cy + 4.5),
                            QPointF(cx + 6.5, cy - 4.5)])
        elif self.tone == "warn":
            p.drawLine(QPointF(cx, cy - 7), QPointF(cx, cy + 2))
            p.drawPoint(QPointF(cx, cy + 6.5))
        else:   # setting up / not yet: three dots
            for dx in (-6, 0, 6):
                p.drawPoint(QPointF(cx + dx, cy))
