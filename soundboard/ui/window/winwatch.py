"""One event filter on the main window's own native window (its QWindow), for the
few things that watch the whole window: Space playing (spacekey.py) and the veil
while files are dragged in (dropveil.py).

Qt hands a key press or a drag to the window first, then to the widget it's for. An
application-wide filter would see it too, but Qt calls one for every event of every
object (paints, layouts, timers): an eighth of building Settings and a fifth of each
step of a window resize went on it. The window's own QWindow gets a few events a
step. It's made again when the window's flags change (Always on top), so attach()
runs on every show."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)


class WindowWatch(QObject):
    """`add(kinds, fn)`: fn(event) for the window's events of those types, first one
    added first; fn returning True eats the event."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._by_type: dict[QEvent.Type, list[Callable[[QEvent], bool]]] = {}

    def add(self, kinds, fn: Callable[[QEvent], bool]) -> None:
        for k in kinds:
            self._by_type.setdefault(k, []).append(fn)

    def attach(self) -> None:
        """On the window's QWindow as it is now (once: Qt doesn't add a filter twice)."""
        handle = self._window.windowHandle()
        if handle is not None:
            handle.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:   # noqa: N802 - Qt API
        fns = self._by_type.get(ev.type())
        if not fns:
            return False
        try:
            return any(fn(ev) for fn in fns)
        except Exception:  # noqa: BLE001 - nothing raises out of Qt's own call
            log.warning("window watch failed", exc_info=True)
            return False


def watch(window: QWidget) -> WindowWatch:
    """The window's WindowWatch, made the first time it's asked for."""
    w = getattr(window, "_window_watch", None)
    if w is None:
        w = WindowWatch(window)
        window._window_watch = w   # pyright: ignore[reportAttributeAccessIssue]
        w.attach()
    return w
