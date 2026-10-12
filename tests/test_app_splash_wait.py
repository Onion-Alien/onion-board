"""The loading screen waits for the sounds and the window's first paint (app.py)."""
import threading
import time

from soundboard import app as sbapp


class FakeApp:
    def __init__(self):
        self.pumped = 0

    def processEvents(self):
        self.pumped += 1


class FakeWindow:
    def __init__(self, load_s: float | None):
        self.painted = 0
        self._load_thread = None
        if load_s is not None:
            self._load_thread = threading.Thread(target=time.sleep, args=(load_s,), daemon=True)
            self._load_thread.start()

    def windowHandle(self):
        return None

    def repaint(self):
        self.painted += 1


def test_waits_until_the_sounds_are_loaded():
    app, w = FakeApp(), FakeWindow(0.2)
    sbapp.wait_for_sounds(app, w)
    assert not w._load_thread.is_alive()
    assert app.pumped >= 2   # events handled meanwhile (each pad's sound arrives)


def test_a_big_library_waits_no_longer_than_the_cap():
    app, w = FakeApp(), FakeWindow(5.0)
    t0 = time.monotonic()
    sbapp.wait_for_sounds(app, w, cap_s=0.1)
    assert time.monotonic() - t0 < 1.0
    assert w._load_thread.is_alive()


def test_no_loader_is_fine():
    sbapp.wait_for_sounds(FakeApp(), FakeWindow(None))


def test_first_paint_paints_once():
    app, w = FakeApp(), FakeWindow(None)
    sbapp.first_paint(app, w)
    assert w.painted == 1
