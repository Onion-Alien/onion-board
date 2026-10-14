"""ui/worker.run: a thread's answer always comes back, even when the work raises."""
import logging

import pytest
from PySide6.QtCore import QObject, Signal

from soundboard.ui import worker
from tests.conftest import process_events


class _Owner(QObject):
    done = Signal(object, str)
    bare = Signal()


def _answers(owner):
    got = []
    owner.done.connect(lambda value, err: got.append((value, err)))
    return got


def test_the_result_comes_back(qapp):
    o = _Owner()
    got = _answers(o)
    worker.run(lambda: (3, ""), o.done, "t", error=(None, "x"), owner=o)
    assert process_events(qapp, lambda: got)
    assert got == [(3, "")]


def test_a_raising_worker_still_answers_and_logs(qapp, caplog):
    """The bug: a worker that raised never emitted, so the busy flag and button its
    slot clears stayed on until a restart."""
    o = _Owner()
    got = _answers(o)

    def boom():
        raise OSError("no room")
    with caplog.at_level(logging.ERROR, logger=worker.__name__):
        worker.run(boom, o.done, "t", error=lambda e: (None, str(e)), owner=o).join(5)
        assert process_events(qapp, lambda: got)
    assert got == [(None, "no room")]
    assert "t failed" in caplog.text and "no room" in caplog.text


def test_a_signal_without_arguments(qapp):
    o = _Owner()
    got = []
    o.bare.connect(lambda: got.append(1))

    def boom():
        raise ValueError
    worker.run(boom, o.bare, "t", error=(), owner=o)
    assert process_events(qapp, lambda: got)


def test_skip_and_a_deleted_owner_emit_nothing(qapp):
    o = _Owner()
    got = _answers(o)
    worker.run(lambda: worker.SKIP, o.done, "t", error=(None, "")).join(5)
    gone = _Owner()
    late = _answers(gone)
    t = worker.run(lambda: (1, ""), gone.done, "t", error=(None, ""), owner=o)
    t.join(5)
    worker.call(lambda: (2, ""), gone.done, "t", error=(None, ""), owner=_dead())
    process_events(qapp, lambda: False, timeout=0.3)
    assert got == [] and late == [(1, "")]


def _dead():
    o = QObject()
    import shiboken6
    shiboken6.delete(o)
    return o


def test_a_signal_needs_its_error_answer():
    with pytest.raises(TypeError):
        worker.run(lambda: 1, _Owner().done, "t")
