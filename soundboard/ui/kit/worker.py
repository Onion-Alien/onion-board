"""Work on a thread whose answer always comes back to the UI.

``run(fn, signal, name, error=…)`` runs ``fn`` on a daemon thread and then emits
``signal`` (on the UI thread, through ``busy.emit``) with what it returned. If ``fn``
raises, the exception is logged and ``error`` is emitted instead. So a flag or a
button set busy before the start is always cleared by the slot, never left stuck
until the app restarts (a bare ``threading.Thread`` only logs the exception).
"""
from __future__ import annotations

import _thread
import logging
import threading
from collections.abc import Callable
from typing import Any

from soundboard.ui.kit import busy

log = logging.getLogger(__name__)

SKIP: Any = object()      # returned by fn (or error): emit nothing, nobody waits on it
_MISSING: Any = object()


def _args(value) -> tuple:
    return value if isinstance(value, tuple) else (value,)


class Job:
    """What ``run`` returns: ``join`` and ``is_alive`` like a Thread's, without
    ``Thread.start``'s wait for the thread to get going."""

    def __init__(self, name: str):
        self.name = name
        self._done = threading.Event()

    def join(self, timeout: float | None = None) -> None:
        self._done.wait(timeout)

    def is_alive(self) -> bool:
        return not self._done.is_set()


def run(fn: Callable[..., Any], signal=None, name: str = "worker", *,
        error: Any = _MISSING, owner=None, args: tuple = ()) -> Job:
    """Run ``fn(*args)`` on a daemon thread named ``name`` and emit ``signal`` with
    its result: a tuple is spread over the signal's arguments (``()`` for a signal
    without any, ``(value,)`` for a tuple value), anything else is the one argument.

    ``error``: what's emitted when ``fn`` raises, in the same form, or a function of
    the exception (called on the thread) returning it. Required with a signal, so no
    caller forgets the failure. Either may be ``SKIP``: then nothing is emitted (a
    newer request owns the answer). ``owner``: the widget the answer is for; deleted
    meanwhile (its tab switched off, the window closed), nothing is emitted.
    Without a signal, fn's result is dropped and an exception only logged.

    Returns a ``Job`` to ``join`` or ask ``is_alive``. The caller never waits for the
    thread to get going (``Thread.start`` does, with no limit: with the PC swapping
    the window froze in it for 10-30 s)."""
    if signal is not None and error is _MISSING:
        raise TypeError("worker.run: a signal needs an error value")
    job = Job(name)

    def body():
        threading.current_thread().name = name
        try:
            call(fn, signal, name, error=error, owner=owner, args=args)
        finally:
            job._done.set()
    _thread.start_new_thread(body, ())
    return job


def start(fn: Callable[..., Any], signal=None, name: str = "worker", *,
          error: Any = _MISSING, owner=None, args: tuple = ()) -> None:
    """``run`` for work nothing joins."""
    if signal is not None and error is _MISSING:
        raise TypeError("worker.start: a signal needs an error value")
    run(fn, signal, name, error=error, owner=owner, args=args)


def call(fn: Callable[..., Any], signal=None, name: str = "worker", *,
         error: Any = None, owner=None, args: tuple = ()):
    """What ``run``'s thread does (a test can do it in place)."""
    try:
        out = fn(*args)
    except Exception as e:  # noqa: BLE001 - logged, and the error goes out instead
        log.exception("%s failed", name)
        if signal is None:
            return
        try:
            out = error(e) if callable(error) else error
        except Exception:  # noqa: BLE001
            log.exception("%s: making its error answer failed", name)
            return
    if signal is None or out is SKIP:
        return
    busy.emit(signal, *_args(out), owner=owner)
