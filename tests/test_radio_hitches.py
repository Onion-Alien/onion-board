"""The Radio tab mustn't hold up the audio threads: Qt keeps Python's lock through
each call into it, so one long call (drawing the whole map, loading the decoder) is
a sound skipping on the cable."""
import threading
import time
from pathlib import Path

import numpy as np

from soundboard import radio
from soundboard.ui import flatmap
from soundboard.ui.flatmap import LAND_PART, FlatMap


def outlines():
    raw = (radio.ASSET_DIR / radio.COUNTRIES).read_bytes()
    return radio.outline_rings(raw), radio.outline_labels(raw)


def quietest(measure, limit, tries=5):
    """The best of a few tries of measure(), stopping at the first under limit. Holding
    Python's lock stalls the audio on every try; a busy shared machine (CI, the other
    test workers) stalls only some of them, so a real hitch still fails every time."""
    best = float("inf")
    for _ in range(tries):
        best = min(best, measure())
        if best < limit:
            break
    return best


def drawn_now(m):
    """Paint m with its world picture drawn all at once (a shown map draws it a slice
    at a time), and return the picture."""
    m.grab()
    b = m._build
    if b is not None:
        for _ in b[2]:
            pass
        m._build = None
        m._slice.stop()
        m._world = (b[0], b[1])
    return m.grab()


def world_map(rings, labels, zoom=2.0):
    m = FlatMap()
    m.resize(1200, 700)
    m.set_land(rings, labels)
    m.zoom = zoom
    return m


def test_the_land_is_drawn_in_small_parts(qapp):
    rings, _ = outlines()
    m = FlatMap()
    m.set_land(rings)
    sizes = [sum(p.elementAt(i).isMoveTo() for i in range(p.elementCount()))
             for p in m._land]
    assert sum(sizes) == len(rings) and len(m._land) > 10   # every outline, in parts
    assert max(p.elementCount() for p in m._land) <= max(LAND_PART, *map(len, rings)) + 1


def test_the_map_looks_the_same_drawn_in_parts(qapp, monkeypatch):
    rings, labels = outlines()
    parts = drawn_now(world_map(rings, labels)).toImage()
    monkeypatch.setattr(flatmap, "LAND_PART", 10**9)   # the whole world as one path
    whole = drawn_now(world_map(rings, labels)).toImage()
    a = np.frombuffer(parts.constBits(), np.uint8)
    b = np.frombuffer(whole.constBits(), np.uint8)
    assert a.shape == b.shape
    assert np.mean(np.abs(a.astype(int) - b) > 8) < 0.002   # a few edge pixels at most


def test_drawing_the_world_lets_the_audio_threads_run(qapp):
    """Qt keeps Python's lock while it draws a path: the whole world as one path held
    every other thread for 10-30 ms each time the map was drawn at a new zoom, and the
    sounds playing skipped (it happened as a station started: the map flies to it)."""
    import sys

    from soundboard.app import SWITCH_S
    rings, labels = outlines()

    def worst_gap():
        m = world_map(rings, labels)   # the whole world in one picture: 15-30 ms in one path
        gaps, stop = [], threading.Event()

        def audio():   # wakes every millisecond, like a callback that's due
            last = time.perf_counter()
            while not stop.is_set():
                time.sleep(0.001)
                t = time.perf_counter()
                gaps.append(t - last)
                last = t

        th = threading.Thread(target=audio, daemon=True)
        th.start()
        try:
            time.sleep(0.05)
            drawn_now(m)                 # draws the whole world at this zoom
        finally:
            stop.set()
            th.join()
        return max(gaps)

    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH_S)
    try:
        worst = quietest(worst_gap, 0.010)
    finally:
        sys.setswitchinterval(old)
    assert worst < 0.010, f"held up {worst * 1000:.0f} ms"


def audio_late_while(work):
    """How late the real cable callback (a looping song and the radio playing) was at
    worst while work() ran on this thread, on a 10 ms schedule like a device's."""
    import sys

    import sounddevice as sd

    from soundboard.app import SWITCH_S
    from soundboard.engine import Engine
    e = Engine()
    e.main_stream = e.mon_stream = object()    # stands in for open outputs: no device
    t = np.arange(48000 * 5) / 48000
    x = 0.3 * np.sin(2 * np.pi * 330 * t)
    e.play("song", (np.stack([x, x], 1) * 32767).astype(np.int16), 0.5, loop=True)
    e.radio_live = True
    took, stop = [], threading.Event()

    def audio():
        out = np.zeros((480, 2), np.float32)
        due = time.perf_counter()
        while not stop.is_set():
            due += 0.01
            time.sleep(max(0.0, due - time.perf_counter()))
            if e.ring_rmain.count < 4800:
                e.ring_rmain.write(np.full((4800, 2), 0.05, np.float32))
            e._cb_main(out, 480, None, sd.CallbackFlags())
            took.append(time.perf_counter() - due)   # finished this long after it was due

    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH_S)
    th = threading.Thread(target=audio, daemon=True)
    th.start()
    try:
        time.sleep(0.05)
        work()
        time.sleep(0.03)
    finally:
        stop.set()
        th.join()
        sys.setswitchinterval(old)
    assert e.voices and not any(e.cb_errors.values())
    return max(took)


def test_a_new_zoom_is_drawn_in_slices_beside_the_audio(qapp):
    """Every call under 1 ms still made the cable 10-20 ms late as a station started
    (the map flies to it): the audio thread waits out one draw call per numpy step,
    and the new zoom's world was 20-40 ms of them in a row. Now a slice at a time,
    the old picture showing meanwhile, and the same picture at the end."""
    rings, labels = outlines()
    m = world_map(rings, labels, zoom=1.0)
    m.show()
    drawn_now(m)
    first = m._world[1]
    m.zoom = 2.5
    shown = m._world_pixmap(m.devicePixelRatioF())
    assert shown is first and m._build is not None      # the old one, while it's drawn

    def fly_about():
        for zoom in (2.2, 2.4, 2.6, 2.8):   # each a whole-world picture (WORLD_MAX_PX)
            m.zoom = zoom
            m._world_pixmap(m.devicePixelRatioF())
            end = time.monotonic() + 5
            while m._build is not None and time.monotonic() < end:
                qapp.processEvents()
                time.sleep(0.0005)   # the event loop waiting (without Python's lock)

    worst = quietest(lambda: audio_late_while(fly_about), 0.006)
    assert m._build is None and m._world[1] is not first
    assert worst < 0.006, f"the cable was {worst * 1000:.0f} ms late"
    sliced = m._world[1].toImage()
    pm, steps = m._world_steps(m._world[0])
    for _ in steps:   # all at once
        pass
    whole = pm.toImage()
    a = np.frombuffer(sliced.constBits(), np.uint8)
    b = np.frombuffer(whole.constBits(), np.uint8)
    assert a.shape == b.shape and np.array_equal(a, b)
    m.zoom = 2.3
    m._world_pixmap(m.devicePixelRatioF())
    m.hide()
    qapp.processEvents()
    time.sleep(0.01)
    qapp.processEvents()
    assert m._build is None                    # off screen: not drawn after all


def test_the_decoder_is_loaded_off_the_ui_thread_once(qapp, monkeypatch):
    """Qt loaded FFmpeg (avcodec and co, tens of MB) as the first station started, on
    the UI thread and holding Python's lock: 10-60 ms, and the sounds playing skipped."""
    import ctypes
    import sys

    import pytest
    if sys.platform != "win32":
        pytest.skip("Windows only")
    loaded = []
    monkeypatch.setattr(ctypes, "WinDLL",
                        lambda path: loaded.append((path, threading.current_thread().name)))
    monkeypatch.setattr(radio, "_preloaded", False)
    p1, p2 = radio.RadioPlayer(), radio.RadioPlayer()
    end = time.monotonic() + 5
    while not any("ffmpeg" in f.lower() for f, _ in loaded) and time.monotonic() < end:
        time.sleep(0.01)
    names = [Path(f).name.lower() for f, _ in loaded]
    assert names[0].startswith("avutil") and names[-1].startswith("ffmpeg")
    assert any(n.startswith("avcodec") for n in names)
    assert len(names) == len(set(names))                       # once, for both players
    assert all(t == "radio-preload" for _, t in loaded)        # never the UI thread
    p1.deleteLater()
    p2.deleteLater()
