"""Click feedback for buttons: a "working…" state while something runs and a short
"✓ done" on the button afterwards, so no click ends in silence.

- ``run_busy(btn, "Scanning…", fn, done)`` for quick work that runs on the GUI thread:
  the button greys out and shows the busy text *before* ``fn`` runs (it's deferred one
  event-loop turn so the label paints), then shows ``done(result)`` for a moment.
- ``hold(btn, "Checking…")`` for work that finishes later (a thread, a timer): it
  returns a ``release(text=None)`` to call when it's over.
- ``flash(btn, "✓ Copied")`` just swaps the label for a moment.
- ``toast(window, "✓ Added 3 sounds")`` for a result that isn't about one button: a
  card in the bottom corner of the window (or of the dialog in front) for a few
  seconds (``ui/kit/toast.py``). A child widget, so it never takes focus from a game.
"""
from __future__ import annotations

import html
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon, QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid as qt_valid

from soundboard.core import errors
from soundboard.i18n import _
from soundboard.ui.kit import toast as toastmod

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
        if btn.property("icon_before") is not None:
            btn.setIcon(btn.property("icon_before"))
            btn.setProperty("icon_before", None)
        if btn.property("min_w_before") is not None:   # let it shrink again (small windows)
            btn.setMinimumWidth(btn.property("min_w_before"))
            btn.setProperty("min_w_before", None)
    except RuntimeError:   # the button was deleted meanwhile
        pass


def _keep_width(btn):
    # the label changes length; don't let the button jump narrower under the cursor
    # while it shows (_restore lets go again)
    if btn.property("min_w_before") is None:
        btn.setProperty("min_w_before", btn.minimumWidth())
    # (never wider than it is: a WrapButton on two lines would push its page wider)
    hint = btn.sizeHint().width()
    btn.setMinimumWidth(max(btn.minimumWidth(), min(hint, btn.width()) if btn.isVisible()
                            else hint))


def _set_label(btn, text: str, serial: int):
    """Show ``text``, never cut off: a "✓ done" stands in for the button's own icon
    (side by side they only crowd it), and if the label still won't fit the room the
    layout gives it (a full header can't widen the button), it's trimmed to its "✓"
    or the normal label stays."""
    if text[:1] in "✓✗" and not btn.icon().isNull():
        if btn.property("icon_before") is None:
            btn.setProperty("icon_before", btn.icon())
        btn.setIcon(QIcon())
    btn.setText(text)   # wider: it gets the room only if the layout has some spare

    def check():
        try:
            if btn.property(_SERIAL) != serial or not btn.isVisible():
                return
            if btn.width() < btn.sizeHint().width():
                short = text[:1] if text[:1] in "✓✗" else _idle_text(btn)
                btn.setText(short)
                if not short.strip() and btn.property("icon_before") is not None:
                    btn.setIcon(btn.property("icon_before"))
        except RuntimeError:   # the button was deleted meanwhile
            pass
    QTimer.singleShot(0, check)   # after the layout has had its say


def flash(btn, text: str, ms: int = FLASH_MS):
    """Show ``text`` on the button for ``ms``, then its normal label again."""
    btn.setProperty(_IDLE, _idle_text(btn))
    _keep_width(btn)
    serial = _bump(btn)
    _set_label(btn, text, serial)
    QTimer.singleShot(ms, lambda: _restore(btn, serial))


class _ClickBlocker(QObject):
    """Swallows clicks and Space / Enter on a busy button. Used instead of
    setEnabled(False): disabling the button that has keyboard focus makes Qt move the
    focus to the next control (e.g. the combo box under Re-scan)."""

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if not obj.property("busy"):
            return False
        t = ev.type()
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                 QEvent.Type.MouseButtonDblClick):
            return True
        return isinstance(ev, QKeyEvent) and t in (QEvent.Type.KeyPress,
                                                   QEvent.Type.KeyRelease) and ev.key() in (
            Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Select)


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
    _set_label(btn, text, serial)
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
             done: Callable[[Any], str | None] | str | None = None,
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
            release(_("Didn't work, try again"))
            raise
        release(msg, ms)
    QTimer.singleShot(0, go)


TOAST_MS = toastmod.TOAST_MS
_Toast = toastmod._Toast


def toast(window: QWidget | None, text: str, kind: str = "", ms: int = TOAST_MS, **kw):
    """Show ``text`` (rich text; kind "ok" / "warn" / "error" / "busy" / "") in the
    bottom corner of the dialog in front if there is one (Settings is modal over the
    window), else of ``window``. ``action=(label, fn)``, ``key`` and ``progress`` as in
    ``toast.show``."""
    return toastmod.show(window, text, kind, ms, **kw)


def hold_until(btn, text: str, signal, done: Callable[..., str | None] | None = None):
    """``hold`` the button until ``signal`` next fires, then flash ``done(*args)``."""
    release = hold(btn, text)

    def slot(*args):
        signal.disconnect(slot)
        release(done(*args) if done else None)
    signal.connect(slot)


class _Carrier(QObject):
    """Brings a worker's result over to the UI thread, where it's emitted on the
    widget that asked. The worker never emits on that widget itself: freed by the UI
    thread during the emit (its tab switched off, a dialog closed), that was a native
    access violation or a corrupt heap, not the RuntimeError a widget freed earlier
    gives. This one lives as long as the app."""
    call = Signal(object)

    @Slot(object)
    def _run(self, fn):
        fn()


_carrier: _Carrier | None = None
_carrier_lock = threading.Lock()


def _the_carrier() -> _Carrier:
    global _carrier
    with _carrier_lock:
        if _carrier is None:
            c = _Carrier()
            app = QApplication.instance()
            assert app is not None   # made before any worker
            c.moveToThread(app.thread())   # (made on a worker)
            c.call.connect(c._run)
            _carrier = c
        return _carrier


def _emit_now(signal, args, owner=None) -> bool:
    if owner is not None and not qt_valid(owner):
        return False
    try:
        signal.emit(*args)
        return True
    except (RuntimeError, TypeError):   # "Signal source has been deleted"
        return False


def emit(signal, *args, owner=None) -> bool:
    """From a worker thread: hand a result to the widget that started it, unless that
    widget (or ``owner``, when the signal is on a helper object) was deleted meanwhile
    (its tab switched off in Settings > Tabs, the app closing). It's emitted on the UI
    thread, so the widget can't be freed under it; False when it's gone (known at once
    on the UI thread, else True)."""
    if threading.current_thread() is threading.main_thread():
        return _emit_now(signal, args, owner)
    try:
        _the_carrier().call.emit(lambda: _emit_now(signal, args, owner))
    except (RuntimeError, AttributeError):   # app closing: the carrier (or the app) is gone
        _forget_carrier()
        return False
    return True


def _forget_carrier():
    global _carrier
    with _carrier_lock:
        _carrier = None


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
            flash(btn, opened or _("✓ Opened"))
        return True
    where = q.toLocalFile() if q.isLocalFile() else q.toString()
    toast(window or (btn.window() if btn is not None else None),
          _("{message}: <b>{link}</b>", message=failed or _("Couldn’t open it"),
            link=html.escape(where)), "warn", 8000)
    return False



def open_folder(folder, btn=None, window: QWidget | None = None) -> bool:
    """Open a folder in Explorer: ``folder`` is a path, or a function making it (and
    returning its path) whose OSError is told rather than crashing the app."""
    try:
        path = folder() if callable(folder) else folder
    except OSError as e:
        toast(window or (btn.window() if btn is not None else None),
              _("Couldn't make the folder: {error}", error=html.escape(errors.plain(e))),
              "warn", 8000)
        return False
    return open_url(QUrl.fromLocalFile(str(path)), btn, window, opened=_("✓ Opened"),
                    failed=_("Couldn't open the folder"))
