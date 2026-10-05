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
    parts = world_map(rings, labels).grab().toImage()
    monkeypatch.setattr(flatmap, "LAND_PART", 10**9)   # the whole world as one path
    whole = world_map(rings, labels).grab().toImage()
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
    m = world_map(rings, labels)   # the whole world in one picture: 15-30 ms in one path
    gaps, stop = [], threading.Event()

    def audio():   # wakes every millisecond, like a callback that's due
        last = time.perf_counter()
        while not stop.is_set():
            time.sleep(0.001)
            t = time.perf_counter()
            gaps.append(t - last)
            last = t

    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH_S)
    th = threading.Thread(target=audio, daemon=True)
    th.start()
    try:
        time.sleep(0.05)
        m.grab()                         # draws the whole world at this zoom
    finally:
        stop.set()
        th.join()
        sys.setswitchinterval(old)
    assert max(gaps) < 0.010, f"held up {max(gaps) * 1000:.0f} ms"


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
