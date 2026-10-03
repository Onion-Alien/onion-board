"""Click feedback for buttons: a "working…" state while something runs and a short
"✓ done" on the button afterwards, so no click ends in silence.

- ``run_busy(btn, "Scanning…", fn, done)`` for quick work that runs on the GUI thread:
  the button greys out and shows the busy text *before* ``fn`` runs (it's deferred one
  event-loop turn so the label paints), then shows ``done(result)`` for a moment.
- ``hold(btn, "Checking…")`` for work that finishes later (a thread, a timer): it
  returns a ``release(text=None)`` to call when it's over.
- ``flash(btn, "✓ Copied")`` just swaps the label for a moment.
- ``toast(window, "✓ Added 3 sounds")`` for a result that isn't about one button: a
  pill along the bottom of the window (or of the dialog in front) for a few seconds.
  A child widget, so it never takes focus from a game.
"""
from __future__ import annotations

import html
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from soundboard import theme

FLASH_MS = 2200
_IDLE = "_busy_idle_text"
_SERIAL = "_busy_serial"


def _idle_text(btn) -> str:
    saved = btn.property(_IDLE)
    return btn.text() if saved is None else saved


def _bump(btn) -> int:
    n = (btn.property(_SERIAL) or 0) + 1
    btn.setProperty(_SERIAL, n)
    return n


def _restore(btn, serial: int):
    try:
        if btn.property(_SERIAL) != serial:
            return   # a newer flash / busy state owns the label now
        btn.setText(_idle_text(btn))
        btn.setProperty(_IDLE, None)
    except RuntimeError:   # the button was deleted meanwhile
        pass


def _keep_width(btn):
    # the label changes length; don't let the button jump narrower under the cursor
    btn.setMinimumWidth(max(btn.minimumWidth(), btn.sizeHint().width()))


def flash(btn, text: str, ms: int = FLASH_MS):
    """Show ``text`` on the button for ``ms``, then its normal label again."""
    btn.setProperty(_IDLE, _idle_text(btn))
    _keep_width(btn)
    serial = _bump(btn)
    btn.setText(text)
    QTimer.singleShot(ms, lambda: _restore(btn, serial))


class _ClickBlocker(QObject):
    """Swallows clicks and Space / Enter on a busy button. Used instead of
    setEnabled(False): disabling the button that has keyboard focus makes Qt move the
    focus to the next control (e.g. the combo box under Re-scan)."""

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if not obj.property("busy"):
            return False
        t = ev.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                 QEvent.MouseButtonDblClick):
            return True
        return t in (QEvent.KeyPress, QEvent.KeyRelease) and ev.key() in (
            Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Select)


_blocker: _ClickBlocker | None = None


def set_busy(btn, on: bool):
    """Grey ``btn`` out and ignore clicks on it (``on``), or back to normal. Unlike
    setEnabled(False) it keeps the keyboard focus where it is."""
    global _blocker
    if _blocker is None:
        _blocker = _ClickBlocker(QApplication.instance())
    if not btn.property("_busy_filtered"):
        btn.setProperty("_busy_filtered", True)
        btn.installEventFilter(_blocker)
    if bool(btn.property("busy")) != on:
        btn.setProperty("busy", on)
        btn.setDown(False)
        btn.style().unpolish(btn)
        btn.style().polish(btn)


def is_busy(btn) -> bool:
    return bool(btn.property("busy"))


def hold(btn, text: str) -> Callable[..., None]:
    """Grey the button out showing ``text``; returns ``release(text=None, ms=…)`` which
    takes it back and, given a text, flashes that before going back to normal."""
    btn.setProperty(_IDLE, _idle_text(btn))
    _keep_width(btn)
    serial = _bump(btn)
    btn.setText(text)
    set_busy(btn, True)
    btn.repaint()
    done = []

    def release(text: str | None = None, ms: int = FLASH_MS):
        if done:
            return
        done.append(True)
        try:
            set_busy(btn, False)
            if btn.property(_SERIAL) != serial:
                return
            if text:
                flash(btn, text, ms)
            else:
                _restore(btn, serial)
        except RuntimeError:
            pass
    return release


def run_busy(btn, text: str, fn: Callable[[], object],
             done: Callable[[object], str | None] | str | None = None,
             ms: int = FLASH_MS):
    """Run ``fn`` (on the GUI thread) with the button showing ``text`` meanwhile, then
    flash ``done`` — a string, or a function of ``fn``'s result returning one."""
    if is_busy(btn) or not btn.isEnabled():
        return   # already running: a double click mustn't start it twice
    release = hold(btn, text)

    def go():
        result, msg = None, None
        try:
            result = fn()
            msg = done(result) if callable(done) else done
        except Exception:
            release("Didn't work — try again")
            raise
        release(msg, ms)
    QTimer.singleShot(0, go)


TOAST_MS = 4000


class _Toast(QLabel):
    """The pill ``toast`` shows: follows its window's size, hides itself."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAccessibleName("Notice")
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        host.installEventFilter(self)
        self.hide()

    def show_text(self, text: str, kind: str, ms: int):
        self.setText(text)
        theme.set_tone(self, kind)
        self._place()
        self.show()
        self.raise_()
        self._timer.start(ms)

    def _place(self):
        host = self.parentWidget()
        w = min(560, max(200, host.width() - 32))
        self.setFixedWidth(w)
        self.adjustSize()
        self.move((host.width() - w) // 2, host.height() - self.height() - 18)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() == QEvent.Resize and self.isVisible():
            self._place()
        return False


def toast(window: QWidget | None, text: str, kind: str = "", ms: int = TOAST_MS):
    """Show ``text`` (rich text; kind "ok" / "warn" / "error" / "") at the bottom of
    the dialog in front if there is one (Settings is modal over the window), else of
    ``window``."""
    host = QApplication.activeModalWidget() or window
    if host is None:
        return
    host = host.window()
    t = host.findChild(_Toast, options=Qt.FindDirectChildrenOnly)
    if t is None:
        t = _Toast(host)
    t.show_text(text, kind, ms)


def hold_until(btn, text: str, signal, done: Callable[..., str | None] | None = None):
    """``hold`` the button until ``signal`` next fires, then flash ``done(*args)``."""
    release = hold(btn, text)

    def slot(*args):
        signal.disconnect(slot)
        release(done(*args) if done else None)
    signal.connect(slot)


def open_url(url, btn=None, window: QWidget | None = None, opened: str = "",
             failed: str = "") -> bool:
    """Open a link / folder (a QUrl or str) and say so: ``opened`` flashes on ``btn``
    (default "✓ Opened"); a failure toasts ``failed`` with the link, which can then be
    copied by hand."""
    q = url if isinstance(url, QUrl) else QUrl(url)
    try:
        ok = QDesktopServices.openUrl(q)
    except OSError:
        ok = False
    if ok:
        if btn is not None:
            flash(btn, opened or "✓ Opened")
        return True
    where = q.toLocalFile() if q.isLocalFile() else q.toString()
    toast(window or (btn.window() if btn is not None else None),
          f"{failed or 'Couldn’t open it'}: <b>{html.escape(where)}</b>", "warn", 8000)
    return False



def open_folder(folder, btn=None, window: QWidget | None = None) -> bool:
    """Open a folder in Explorer: ``folder`` is a path, or a function making it (and
    returning its path) whose OSError is told rather than crashing the app."""
    try:
        path = folder() if callable(folder) else folder
    except OSError as e:
        toast(window or (btn.window() if btn is not None else None),
              f"Couldn't make the folder: {html.escape(str(e))}", "warn", 8000)
        return False
    return open_url(QUrl.fromLocalFile(str(path)), btn, window, opened="✓ Opened",
                    failed="Couldn't open the folder")
