"""Garbage collection runs on the UI thread only (soundboard.uigc)."""
import gc
import threading
import weakref

from PySide6.QtCore import QObject, QTimer

from soundboard import uigc


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

    def busy():                                # allocates far past every threshold
        junk = []
        for _ in range(200_000):
            junk.append([])
            if len(junk) > 1000:
                junk.clear()
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
    c = uigc.UiCollector(interval_ms=10)
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
