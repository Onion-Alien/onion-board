"""Toasts: short notices that float over a window's bottom corner for a few seconds.

``show(window, "✓ Added 3 sounds", "ok")`` puts a card in the bottom-right corner of
the window (bottom-left in right-to-left languages), above its player bar, or of the
dialog in front. ``busy.toast`` is the same call; most code uses that.

- **Kinds**: "" (a plain notice), "ok", "warn", "error" and "busy" (working on it). Each
  has its own icon and a coloured stripe; the text itself stays the normal colour.
  A leading "✓ " in the text is dropped: the tick icon says it now.
- **Stacking**: up to ``MAX_SHOWN`` at once, the newest nearest the corner. The same
  text again shows "×2" on the card that's there instead of a second card.
- **Working → done**: a "busy" card (or text ending in "…") is replaced by the next
  notice in the same window, so "Adding 3 sounds…" becomes "Added 3 sounds" in place.
  ``key`` does the same for a named card: a later toast with that key updates it.
- **Buttons**: ``action=(label, callback)`` adds one (Undo, See why); ✕ closes.
  ``on_close`` runs when the card goes without its button clicked: timed out, closed,
  pushed out by newer cards or replaced (an Undo card's "too late now").
- **Timing**: hovering pauses the countdown. Errors stay until closed.

Child widgets of the window, never their own windows, so they never take focus from a
game. Animations are skipped when Windows' "Animation effects" setting is off.
"""
from __future__ import annotations

import sys
from collections.abc import Callable

import shiboken6

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent, QObject, QPoint,
                            QPointF, QPropertyAnimation, QRectF, Qt, QTimer)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QGraphicsDropShadowEffect,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.i18n import _
from soundboard.ui import icons

TOAST_MS = 4000
BUSY_MS = 5 * 60 * 1000   # a "busy" card nobody finished goes eventually
MAX_SHOWN = 3
UNDER = 28                # where the text starts: past the icon (18) and a gap (10)
ACTION_INLINE = 110       # a button wider than this goes under the text
WIDTH = 380               # at most; narrower windows get their width less 32
MARGIN = 16               # from the window's side
ANIM_MS = 180
LINE = 26                 # the row's height: icon, first text line, buttons
ANIMATE: bool | None = None   # None: follow Windows' setting (off when offscreen)

# kind -> (icon name, colour token for the icon and stripe)
KINDS = {
    "": ("info", "accent"),
    "ok": ("check", "ok_text"),
    "warn": ("warn", "warn_text"),
    "error": ("alert", "error_text"),
    "busy": ("", "accent"),   # a spinner instead of an icon
}


def animations_on() -> bool:
    if ANIMATE is not None:
        return ANIMATE
    app = QApplication.instance()
    if app is None or app.platformName() in ("offscreen", "minimal"):
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            on = ctypes.c_int(1)
            # SPI_GETCLIENTAREAANIMATION: Settings > Accessibility > Animation effects
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0):
                return bool(on.value)
        except (AttributeError, OSError):
            pass
    return True


class _Spinner(QWidget):
    """The "busy" card's icon: an arc going round (still when animations are off)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, LINE)
        self._angle = 0
        self._timer = QTimer(self, interval=33, timeout=self._step)

    def _step(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def showEvent(self, ev):
        if animations_on():
            self._timer.start()
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2.5, (self.height() - 13) / 2, 13, 13)
        pen = QPen(QColor(theme.T.get("border_hi", "#888")), 2.2)
        p.setPen(pen)
        p.drawEllipse(r)
        pen.setColor(QColor(theme.T.get("accent", "#7c5cff")))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, -self._angle * 16, 100 * 16)
        p.end()


class _Card(QFrame):
    """The visible card: stripe, icon, text (with ×N), an optional button and ✕."""

    def __init__(self, toast: _Toast):
        super().__init__(toast)
        self.setObjectName("toast")
        self._tone = "accent"
        self.progress: tuple[int, int] | None = None
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        # every part of the row is LINE tall and centred in it, the text's first line
        # too (set_line), so icon, words, ×N, the button, copy and ✕ share one middle
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 10, 6, 10)   # 18: room for the stripe
        outer.setSpacing(2)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        outer.addLayout(row)
        self._row = row
        # a long button goes on a line of its own under the text (set_action_place),
        # so it doesn't squeeze the words into a thin column
        self._under = QHBoxLayout()
        outer.addLayout(self._under)
        self.icon = QLabel()
        self.icon.setFixedSize(18, LINE)
        self.icon.setAlignment(Qt.AlignCenter)
        self.spinner = _Spinner()
        self.spinner.hide()
        row.addWidget(self.icon, 0, Qt.AlignTop)
        row.addWidget(self.spinner, 0, Qt.AlignTop)

        self.label = QLabel()
        self.label.setObjectName("toasttext")
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        self.label.setOpenExternalLinks(False)
        self.label.setTextInteractionFlags(Qt.NoTextInteraction)
        row.addWidget(self.label, 1, Qt.AlignTop)

        self.action = QPushButton()
        self.action.setObjectName("toastaction")
        self.action.setFixedHeight(LINE)
        self.action.setCursor(Qt.PointingHandCursor)
        self.action.hide()
        row.addWidget(self.action, 0, Qt.AlignTop)

        self.btn_copy = self._icon_button("copy", 13, _("Copy"))
        self.btn_copy.hide()
        row.addWidget(self.btn_copy, 0, Qt.AlignTop)
        self.btn_close = self._icon_button("close", 12, _("Dismiss"))
        row.addWidget(self.btn_close, 0, Qt.AlignTop)

    @staticmethod
    def _icon_button(name: str, size: int, words: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("toastclose")
        b.setFixedSize(LINE, LINE)
        b.setToolTip(words)
        b.setAccessibleName(words)
        b.setCursor(Qt.PointingHandCursor)
        icons.set_icon(b, name, "muted", size=size)
        return b

    def set_action_place(self):
        """A short button (Undo, See why) sits on the text's line; a long one goes on a
        line of its own under the text."""
        self.action.ensurePolished()
        wide = self.action.sizeHint().width() > ACTION_INLINE
        self._row.removeWidget(self.action)
        while self._under.count():   # the button and its stretch, if it was under
            self._under.takeAt(0)
        if wide:
            # the button's words start where the text does: past the icon, less the
            # button's own padding
            inset = (self.action.sizeHint().width()
                     - self.action.fontMetrics().horizontalAdvance(self.action.text())) // 2
            self._under.setContentsMargins(max(0, UNDER - inset), 0, 0, 0)
            self._under.addWidget(self.action)
            self._under.addStretch(1)
        else:
            self._row.insertWidget(self._row.indexOf(self.btn_copy), self.action, 0,
                                   Qt.AlignTop)

    def set_line(self):
        """Pad the text so its first line sits in the middle of the LINE-tall row."""
        self.label.ensurePolished()
        pad = max(0, (LINE - self.label.fontMetrics().height()) // 2)
        self.label.setContentsMargins(0, pad, 0, pad)

    def set_kind(self, kind: str):
        name, self._tone = KINDS.get(kind, KINDS[""])
        busy = kind == "busy"
        self.spinner.setVisible(busy)
        self.icon.setVisible(not busy)
        if name:
            icons.set_label_icon(self.icon, name, self._tone, 18)
        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tone = QColor(theme.T.get(self._tone, theme.T.get("accent", "#7c5cff")))
        x = 6 if not self.isRightToLeft() else self.width() - 10
        p.setPen(Qt.NoPen)
        p.setBrush(tone)
        p.drawRoundedRect(QRectF(x, 10, 4, self.height() - 20), 2, 2)
        if self.progress is not None:
            done, total = self.progress
            left = 18
            track = QRectF(left, self.height() - 6, self.width() - left - 14, 3)
            p.setBrush(QColor(theme.T.get("groove", "#444")))
            p.drawRoundedRect(track, 1.5, 1.5)
            if total > 0 and done > 0:
                fill = QRectF(track)
                fill.setWidth(track.width() * min(1.0, done / total))
                if self.isRightToLeft():
                    fill.moveRight(track.right())
                p.setBrush(QColor(theme.T.get("accent", "#7c5cff")))
                p.drawRoundedRect(fill, 1.5, 1.5)
        p.end()


class _Toast(QWidget):
    """One notice. A transparent frame around the card, with room for its shadow."""
    # room for the card's shadow: at the sides, above and below (it falls downwards).
    # Cards are placed so this see-through edge never lies over anything else (it would
    # take the clicks meant for the player bar under it); TOP + BOTTOM is the gap
    # between two cards, BOTTOM the one above the player
    PAD = 8
    TOP, BOTTOM = 4, 8

    def __init__(self, host: QWidget, stack: _Stack):
        super().__init__(host)
        self._stack = stack
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAccessibleName(_("Notice"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(self.PAD, self.TOP, self.PAD, self.BOTTOM)
        self.card = _Card(self)
        lay.addWidget(self.card)
        self.card.btn_close.clicked.connect(self.dismiss)
        self.card.btn_copy.clicked.connect(self.copy)
        self.card.action.clicked.connect(self._act)
        self.kind = ""
        self.key: str | None = None
        self._text = ""
        self._n = 1
        self._callback: Callable[[], None] | None = None
        self._on_close: Callable[[], None] | None = None
        self._timer = QTimer(self, singleShot=True, timeout=self.dismiss)
        self._left = 0          # ms left when the countdown was paused by hovering
        self._leaving = False
        self._anims: list[QAbstractAnimation] = []
        self.hide()

    # -- what it says
    def text(self) -> str:
        return self._text

    def set_content(self, text: str, kind: str, ms: int, action, progress, on_close=None):
        self._closed()   # what it said before is gone now
        self._on_close = on_close
        self._text, self.kind = text, kind
        self.setProperty("tone", kind)
        self.card.set_kind(kind)
        self.card.label.setText(text)
        self.card.set_line()
        self.card.label.setAccessibleName(_strip_tags(text))
        # what went wrong can be copied (to search it, or to send it to us): the
        # button copies it all, and the text can be selected for a part of it
        problem = kind in ("warn", "error")
        self.card.btn_copy.setVisible(problem)
        self.card.label.setTextInteractionFlags(
            Qt.TextSelectableByMouse if problem else Qt.NoTextInteraction)
        self.card.label.setCursor(Qt.IBeamCursor if problem else Qt.ArrowCursor)
        if action:
            label, self._callback = action
            self.card.action.setText(label)
            self.card.set_action_place()
            self.card.action.show()
        else:
            self._callback = None
            self.card.action.hide()
        self.card.progress = progress
        if progress is not None:   # the bar sits under the text
            self.card.layout().setContentsMargins(18, 10, 6, 14)
        else:
            self.card.layout().setContentsMargins(18, 10, 6, 10)
        self._n = 1
        self.restart(ms)
        self.card.update()

    def bump(self, ms: int):
        """The same notice again: count it rather than show a second card."""
        self._n += 1
        # right after the words it counts (wrapping with them), in the muted colour
        self.card.label.setText(
            f'{self._text}&nbsp;&nbsp;<span style="color:{theme.T.get("muted", "gray")};'
            f' font-weight:600">×{self._n}</span>')
        self.restart(ms)

    def restart(self, ms: int):
        self._timer.stop()
        self._left = 0
        sticky = self.kind == "error" or ms <= 0
        if not sticky:
            self._timer.start(ms)
        elif self.kind == "busy":
            self._timer.start(BUSY_MS)
        self._ms = ms

    # -- hover pauses the countdown
    def enterEvent(self, ev):
        if self._timer.isActive():
            self._left = max(self._timer.remainingTime(), 0)
            self._timer.stop()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        if self._left and not self._leaving:
            self._timer.start(max(self._left, 1500))   # time to move the mouse away and read
            self._left = 0
        super().leaveEvent(ev)

    def copy(self):
        QApplication.clipboard().setText(_strip_tags(self._text))
        btn = self.card.btn_copy
        icons.set_icon(btn, "check", "ok_text", size=13)
        btn.setToolTip(_("✓ Copied"))
        QTimer.singleShot(1500, btn, lambda: (icons.set_icon(btn, "copy", "muted", size=13),
                                              btn.setToolTip(_("Copy"))))

    def _act(self):
        cb = self._callback
        self._on_close = None   # it was acted on
        self.dismiss()
        if cb is not None:
            cb()

    def dismiss(self):
        if self._leaving:
            return
        self._leaving = True
        self._timer.stop()
        self._stack.forget(self)
        self._closed()
        if not animations_on() or not self.isVisible():
            self._gone()
            return
        fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity", self)
        a.setDuration(ANIM_MS)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.finished.connect(self._gone)
        self._anims.append(a)
        a.start()

    def _closed(self):
        cb, self._on_close = self._on_close, None
        if cb is not None:
            cb()

    def _gone(self):
        self.hide()
        self.deleteLater()

    def fade_in(self):
        if not animations_on():
            return
        fx = QGraphicsOpacityEffect(self)
        fx.setOpacity(0.0)
        self.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity", self)
        a.setDuration(ANIM_MS)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        # the card's own shadow draws again once the fade is over
        a.finished.connect(lambda: shiboken6.isValid(self) and self.setGraphicsEffect(None))
        self._anims.append(a)
        a.start()

    def glide_to(self, pos: QPoint, from_below: bool = False):
        for a in self._anims:
            if a.propertyName() == b"pos":
                a.stop()
        if not animations_on() or (not from_below and self.pos() == pos):
            self.move(pos)
            return
        a = QPropertyAnimation(self, b"pos", self)
        a.setDuration(ANIM_MS + 40)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.setStartValue(pos + QPoint(0, 14) if from_below else self.pos())
        a.setEndValue(pos)
        self._anims = [x for x in self._anims if x.state() == QAbstractAnimation.Running]
        self._anims.append(a)
        a.start()


class _Stack(QObject):
    """A window's toasts: which are up, and where each goes."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setObjectName("toaststack")
        self.host = host
        self.toasts: list[_Toast] = []   # oldest first
        host.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize and self.toasts:
            self.place(animate=False)
        return False

    def forget(self, t: _Toast):
        if t in self.toasts:
            self.toasts.remove(t)
            self.place()

    def find(self, text: str, kind: str, key: str | None) -> _Toast | None:
        live = [t for t in self.toasts if not t._leaving]
        if key is not None:
            return next((t for t in live if t.key == key), None)
        return next((t for t in live if t.text() == text and t.kind == kind), None)

    def newest_busy(self) -> _Toast | None:
        return next((t for t in reversed(self.toasts)
                     if t.kind == "busy" and t.key is None and not t._leaving), None)

    def add(self, t: _Toast):
        self.toasts.append(t)
        while len(self.toasts) > MAX_SHOWN:
            self.toasts[0].dismiss()   # the oldest makes room (it forgets itself)

    def _floor(self) -> int:
        """The y the cards stand on: above the player bar, or a dialog's buttons."""
        host = self.host
        floor = getattr(host, "toast_floor", None)
        if callable(floor):
            y = floor()
            if y is not None:
                return int(y)
        bottom = host.height() - 8
        if isinstance(host, QDialog):
            buttons = [b for b in host.findChildren(QPushButton)
                       if b.isVisible() and not _in_toast(b)]
            low = [b for b in buttons
                   if b.mapTo(host, QPointF(0, 0)).y() + b.height() >= host.height() - 70]
            if low:
                bottom = min(bottom, int(min(b.mapTo(host, QPointF(0, 0)).y() for b in low)) - 2)
        return bottom

    def place(self, animate: bool = True):
        host = self.host
        w = min(WIDTH, max(200, host.width() - 2 * MARGIN)) + 2 * _Toast.PAD
        bottom = self._floor()
        rtl = host.isRightToLeft()
        x = MARGIN - _Toast.PAD if rtl else host.width() - w - MARGIN + _Toast.PAD
        for t in reversed(self.toasts):   # newest at the bottom, older ones above it
            t.setFixedWidth(w)
            t.ensurePolished()
            t.card.ensurePolished()
            lay = t.layout()
            h = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else t.sizeHint().height()
            h = max(h, t.minimumSizeHint().height())
            t.setFixedHeight(h)
            top = bottom - h
            pos = QPoint(max(0, x), max(0, top))
            if animate and t.isVisible():
                t.glide_to(pos)
            else:
                t.move(pos)
            bottom = top
        for t in self.toasts:
            t.raise_()


def _in_toast(w: QWidget) -> bool:
    while w is not None:
        if isinstance(w, _Toast):
            return True
        w = w.parentWidget()
    return False


def _strip_tags(text: str) -> str:
    from PySide6.QtGui import QTextDocumentFragment
    return QTextDocumentFragment.fromHtml(text).toPlainText()


def _stack_for(host: QWidget) -> _Stack:
    s = host.findChild(_Stack, "toaststack", Qt.FindDirectChildrenOnly)
    return s if s is not None else _Stack(host)


def _announce(t: _Toast, text: str):
    """Screen readers say new notices out loud."""
    try:
        from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
        if QAccessible.isActive():
            QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(t, _strip_tags(text)))
    except (ImportError, AttributeError, TypeError):
        pass


def titled(title: str, text: str) -> str:
    """A message box's title and plain words (lines kept) as a toast's rich text."""
    import html
    body = html.escape(text).replace("\n", "<br>")
    return f"<b>{html.escape(title)}</b><br>{body}" if title else body


def show(window: QWidget | None, text: str, kind: str = "", ms: int = TOAST_MS, *,
         action: tuple[str, Callable[[], None]] | None = None, key: str | None = None,
         progress: tuple[int, int] | None = None,
         on_close: Callable[[], None] | None = None) -> _Toast | None:
    """Show ``text`` (rich text) on ``window``, or the dialog in front of it (Settings
    is modal over the window). Returns the card, or None with no window."""
    host = QApplication.activeModalWidget() or window
    if host is None:
        return None
    host = host.window()
    if text.startswith("✓ "):
        text = text[2:]
        kind = kind or "ok"
    if kind == "" and text.rstrip().endswith("…"):
        kind = "busy"
    stack = _stack_for(host)
    t = stack.find(text, kind, key)
    if t is not None and key is None and progress is None and not action and not on_close:
        t.bump(ms)
        stack.place()
        return t
    if t is None and kind != "busy" and key is None:
        t = stack.newest_busy()   # "working…" becomes its result, in place
    new = t is None
    if new:
        t = _Toast(host, stack)
    t.key = key
    t.set_content(text, kind, ms, action, progress, on_close)
    if new:
        stack.add(t)
        stack.place(animate=False)
        t.show()
        t.raise_()
        t.fade_in()
        t.glide_to(t.pos(), from_below=True)
        stack.place()   # the older cards make room
    else:
        stack.place()
    _announce(t, text)
    return t


def close(window: QWidget | None, key: str):
    """Take down the card shown with ``key`` on ``window`` (or the dialog in front)."""
    for host in {w.window() for w in (QApplication.activeModalWidget(), window) if w}:
        s = host.findChild(_Stack, "toaststack", Qt.FindDirectChildrenOnly)
        t = s.find("", "", key) if s is not None else None
        if t is not None:
            t.dismiss()


def shown(window: QWidget) -> list[_Toast]:
    """The cards up on ``window`` (or nothing), oldest first. For tests."""
    s = window.window().findChild(_Stack, "toaststack", Qt.FindDirectChildrenOnly)
    return [t for t in s.toasts if not t._leaving] if s is not None else []
