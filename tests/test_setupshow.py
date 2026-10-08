"""Bun's setup show: he rolls in, gets his toolbox out and builds a speaker, then it
either plays (ok) or blows up (not ok), he scoots off and the show hides itself."""

import time

from soundboard.ui.setupshow import PARTS, SetupShow


def _run(b, secs, paint_every=0):
    for i in range(int(secs / 0.035)):
        b._last = time.monotonic() - 0.035   # a frame's worth of pretend time
        b._step()
        if paint_every and i % paint_every == 0 and b.on:
            assert not b.grab().isNull()


def _show(qapp):
    b = SetupShow()
    b.resize(320, b.sizeHint().height())
    ended = []
    b.done.connect(lambda: ended.append(True))
    b.start()
    return b, ended


def test_ok_plays_then_he_scoots_off(qapp):
    b, ended = _show(qapp)
    phases = []
    for _ in range(80):
        _run(b, 0.1)
        if b.phase() not in phases:
            phases.append(b.phase())
    assert phases[:4] == ["roll", "dizzy", "toolbox", "build"]
    assert b._parts == PARTS - 1          # the last part waits for the result
    b.finish(True)
    seen = set()
    for _ in range(80):
        _run(b, 0.1, paint_every=2)
        seen.add(b.phase())
        if b.phase() == "yay":
            assert b._parts == PARTS
    assert {"yay", "scoot"} <= seen
    assert ended and not b.on and not b.isVisible()
    assert b.notes == [] or all(n.age < n.life for n in b.notes)


def test_failure_breaks_it_and_he_droops(qapp):
    b, ended = _show(qapp)
    _run(b, 5)
    b.finish(False)
    seen, sad = set(), 0.0
    for _ in range(80):
        _run(b, 0.1, paint_every=2)
        seen.add(b.phase())
        sad = max(sad, b._sad)
    assert {"shake", "sad", "scoot"} <= seen
    assert b._booms == 1 and sad > 0.5
    assert ended and not b.on


def test_early_result_waits_for_the_speaker(qapp):
    b, ended = _show(qapp)
    _run(b, 0.5)
    b.finish(True)                 # Windows said yes before he even got his toolbox out
    _run(b, 2)
    assert b.phase() in ("toolbox", "build")
    _run(b, 10)
    assert ended


def test_every_moment_paints(qapp):
    for ok in (True, False):
        b, ended = _show(qapp)
        _run(b, 4.5, paint_every=1)
        b.finish(ok)
        _run(b, 6, paint_every=1)
        assert ended


def test_start_twice_and_finish_when_hidden(qapp):
    b, ended = _show(qapp)
    _run(b, 1)
    t = b._t
    b.start()                      # already on: carries on
    assert b._t == t
    b.hide()
    b.finish(False)                # nobody watching: just stops
    assert ended and not b.on
    b.finish(True)                 # (not on: nothing)
    assert len(ended) == 1
