"""One thread kept for the app's life, for a timer's small look-up that runs again and
again (Windows' default output every 1.5 s, Discord's settings every 10 s).

Those used to start a new thread every time. On the UI thread, Thread.start waits until
the new thread is running, and a new thread first has to get through Windows' start-up
of it (every loaded DLL is told about it, one thread at a time) and then Python's lock:
2.0.4's window was caught in that wait in freezes of 10 s and more. Handing the job to
a thread that's already running never waits."""
from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class PollThread:
    def __init__(self, name: str):
        self.name = name
        self._q: queue.SimpleQueue[Callable[[], object] | None] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stopped = False

    def run(self, fn: Callable[[], object]) -> None:
        """Call fn() on the thread, after the jobs before it. Never waits for it (only
        the first call starts the thread); fn's errors are logged, never raised.
        Nothing once stopped."""
        with self._lock:
            if self._stopped:
                return
            self._q.put(fn)
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, daemon=True,
                                                name=self.name)
                self._thread.start()

    def stop(self) -> None:
        """The thread ends after the job it's on (without waiting for it)."""
        with self._lock:
            self._stopped = True
            self._q.put(None)

    def _loop(self):
        while True:
            fn = self._q.get()
            if fn is None:
                return
            try:
                fn()
            except Exception:  # noqa: BLE001 - the next look must still run
                log.exception("%s failed", self.name)
