"""Garbage collection runs on the UI thread only (soundboard.core.uigc)."""
import gc
import threading
import weakref

from PySide6.QtCore import QObject, QTimer

from soundboard.core import uigc


def dropped_cycle():
    """A QObject with a running timer, kept alive only by a reference cycle."""
    class Holder:
        pass
    h = Holder()
    h.me = h
    h.obj = QObject()
    h.timer = QTimer(h.obj)
    h.timer.start(1000)
    return weakref.ref(h)


def test_a_cycle_is_never_collected_on_another_thread(qapp):
    assert not gc.isenabled()                  # the app's UiCollector; conftest for tests
    # the older generations' counts go up only as younger ones are collected: set them
    # here, not by whatever the tests before this one happened to collect
    for gen in (1, 1, 0, 0):
        gc.collect(gen)
    held = dropped_cycle()

    kept = []

    def busy():                                # allocates far past every threshold
        junk = []
        for _ in range(200_000):
            junk.append([])
            if len(junk) > 1000:
                junk.clear()
        # ...and keeps some: the count is of objects made minus freed, and with all of
        # them freed again it could end at 0 (nothing due: the test failed, now and then)
        kept.extend([] for _ in range(5000))
    t = threading.Thread(target=busy)
    t.start()
    t.join(30)
    assert held() is not None                  # not freed there: its timer would dangle
    assert uigc.collect_due((1, 1, 1)) == 2    # due: collected here, on the UI thread
    assert held() is None


def test_nothing_is_collected_before_its_threshold(qapp):
    gc.collect()
    assert uigc.collect_due((10**9, 10, 10)) == -1


def test_the_collector_checks_on_a_timer(qapp):
    c = uigc.UiCollector(interval_ms=10, freeze=False)
    try:
        assert c._timer.isActive() and not gc.isenabled()
        held = dropped_cycle()
        c.thresholds = (0, 0, 0)
        end = threading.Event()
        QTimer.singleShot(200, end.set)
        while held() is not None and not end.is_set():
            qapp.processEvents()
        assert held() is None
    finally:
        c._timer.stop()                        # (not stop(): gc stays off for the suite)
        c.deleteLater()


def test_what_a_thread_held_is_let_go_of_on_the_ui_thread(qapp):
    """A tab switched off while its thread works: the thread's target held the last
    reference, and the tab (with the Qt objects only it held) was freed there."""
    freed_on = []

    class Tab:
        def __init__(self):
            self.timer = QTimer()   # held by Python only, as a tab's parts can be

        def work(self, _arg):
            pass

        def __del__(self):
            freed_on.append(threading.current_thread())

    uigc.let_go()
    t = threading.Thread(target=Tab().work, args=(Tab(),))
    t.start()
    t.join(10)
    assert freed_on == []                      # handed over, not freed on the thread
    assert uigc.let_go() == 1
    assert freed_on == [threading.main_thread()] * 2


def test_a_thread_run_on_the_ui_thread_lets_go_at_once(qapp):
    freed = []

    class Job:
        def work(self):
            pass

        def __del__(self):
            freed.append(1)

    threading.Thread(target=Job().work).run()
    assert freed == [1]


def test_full_collections_skip_whats_set_aside_till_its_quiet(qapp, monkeypatch):
    """A collection holds Python's lock and the audio callbacks wait it out: a full
    one over the whole app took ~30 ms, a skip in the sound playing. What's alive when
    the collector starts is set aside, so the usual collections only go through what's
    new, and all of it is gone through only while nothing plays (or after DEEP_MAX_S)."""
    old = dropped_cycle()                      # made before: set aside
    quiet = [False]
    c = uigc.UiCollector(interval_ms=10**6, quiet=lambda: quiet[0])
    try:
        assert gc.get_freeze_count() > 0
        new = dropped_cycle()
        c.thresholds = (0, 0, 0)
        c.check()
        gc.collect(2)                          # even a full collection (not a deep one)...
        assert new() is None and old() is not None   # ...goes through what's new only
        monkeypatch.setattr(uigc, "DEEP_S", 0)
        c.check()                              # a sound playing: still no deep sweep
        assert old() is not None
        quiet[0] = True
        assert c.check() == 3 and old() is None   # quiet: everything gone through
        assert gc.get_freeze_count() > 0       # ...and set aside again
        quiet[0] = False
        monkeypatch.setattr(uigc, "DEEP_MAX_S", 0)
        old = dropped_cycle()
        gc.freeze()
        assert c.check() == 3 and old() is None   # never quiet: after DEEP_MAX_S anyway
    finally:
        c._timer.stop()                        # (not stop(): gc stays off for the suite)
        c.deleteLater()
        gc.unfreeze()


def test_the_young_generation_is_collected_small():
    c = uigc.UiCollector(interval_ms=10**6, freeze=False)
    try:
        assert c.thresholds[0] == uigc.YOUNG <= 5_000   # 50,000 new objects: ~8 ms
        assert uigc.INTERVAL_MS <= 100
    finally:
        c._timer.stop()
        c.deleteLater()


def test_the_engine_is_quiet_only_with_nothing_playing():
    import time
    from types import SimpleNamespace

    from soundboard.audio.engine import Engine
    e = Engine.__new__(Engine)                 # just the state quiet() reads
    e.voices, e.aux, e._radio_heard = (), (), 0.0
    assert e.quiet()
    e.voices = (SimpleNamespace(silent=False),)
    assert not e.quiet()
    e.voices = (SimpleNamespace(silent=True),)
    assert e.quiet()
    e._radio_heard = time.monotonic()
    assert not e.quiet()
    e._radio_heard, e.aux = 0.0, (object(),)
    assert not e.quiet()
