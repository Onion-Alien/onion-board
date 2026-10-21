"""The main window's watch (Space, the drop veil) gets onto its new native window even
when a dead layout item's Python wrapper sits at that address."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from soundboard.ui.kit.widgets import widget_at
from soundboard.ui.window.winwatch import WindowWatch


def _drop_deleted():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _leave_dead_items(lay, n, *, raw):
    """Items Qt deletes with their widgets, after Python asked for them."""
    for _ in range(n):
        lbl = QLabel("x")
        lay.addWidget(lbl)
        if raw:
            lay.itemAt(lay.count() - 1).widget()
        else:
            widget_at(lay, lay.count() - 1)
        lbl.setParent(None)
        lbl.deleteLater()
    _drop_deleted()


def _stale_window(lay, *, raw):
    """A shown window whose windowHandle() comes back as a dead item, else None."""
    for _ in range(100):
        _leave_dead_items(lay, 20, raw=raw)
        w = QWidget()
        w.show()
        if not isinstance(w.windowHandle(), QWindow):
            return w
        w.close()
        w.deleteLater()
        _drop_deleted()
    return None


def test_attach_survives_a_stale_wrapper(qapp):
    host = QWidget()
    w = _stale_window(QHBoxLayout(host), raw=True)
    if w is None:
        pytest.skip("no address was reused this run")
    watch = WindowWatch(w)
    seen = []
    watch.add((QEvent.Type.User,), lambda ev: seen.append(ev.type()) or False)
    watch.attach()
    handle = w.windowHandle()
    assert isinstance(handle, QWindow)
    QCoreApplication.sendEvent(handle, QEvent(QEvent.Type.User))
    assert seen == [QEvent.Type.User]
    w.close()


def test_widget_at_leaves_no_stale_wrapper(qapp):
    host = QWidget()
    assert _stale_window(QHBoxLayout(host), raw=False) is None
