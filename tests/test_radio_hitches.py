"""The Radio tab mustn't hold up the audio threads: Qt keeps Python's lock through
each call into it, so one long call (drawing the whole map, loading the decoder) is
a sound skipping on the cable."""
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from conftest import process_events, real_pc_timing
from soundboard.online import radio
from soundboard.ui.radio import flatmap
from soundboard.ui.radio.flatmap import LAND_PART, FlatMap


def outlines():
    raw = (radio.ASSET_DIR / radio.COUNTRIES).read_bytes()
    return radio.outline_rings(raw), radio.outline_labels(raw)


def landed(m):
    """The rest of set_land's parts now (it makes them a step at a time)."""
    m._land_steps.stop()
    while m._rings:
        m._land_step()
    assert m._land_set
    return m


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 1.75, 2.0])
@pytest.mark.parametrize("solid", [False, True])
def test_settled_world_tiles_cover_the_antimeridian(qapp, monkeypatch, dpr, solid):
    from PySide6.QtGui import QColor, QImage, QPainter

    m = FlatMap()
    m.resize(240, 80)
    monkeypatch.setattr(m, "_scale", lambda: 100.49 / 360)
    monkeypatch.setattr(m, "devicePixelRatioF", lambda: dpr)
    m.cy = flatmap.LAT_TOP
    level = m._level()
    colour = (QColor("white") if solid else
              flatmap._mix(flatmap.theme.T["bg"], flatmap.theme.T["accent"], 0.06))
    for i, j in m._all_tiles(level):
        m._tile_now((level, i, j))
        if solid:
            m._tiles[level, i, j].fill(colour)
    try:
        for cx in (179.0, 180.0, 181.0, 182.0):
            m.cx = cx
            image = QImage(round(240 * dpr), round(80 * dpr), QImage.Format_RGB32)
            image.setDevicePixelRatio(dpr)
            painter = QPainter(image)
            try:
                m._paint(painter, dpr)
            finally:
                painter.end()
            assert all(image.pixelColor(x, round(60 * dpr)).rgba() == colour.rgba()
                       for x in range(round(25 * dpr), round(215 * dpr))), (dpr, cx)
    finally:
        m._stop_build()
        m.close()


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 1.75, 2.0])
def test_world_copy_seams_do_not_expose_the_background(qapp, monkeypatch, dpr):
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

    m = FlatMap()
    m.resize(240, 80)
    m.cx = 180.0
    m.cy = flatmap.LAT_TOP
    # The cached world's rounded device width is slightly smaller than its
    # fractional screen spacing, putting both anti-meridians inside the view.
    scale = 100.49 / 360
    monkeypatch.setattr(m, "_scale", lambda: scale)
    pic = QPixmap(100, 80)
    pic.fill(QColor("white"))
    image = QImage(round(240 * dpr), round(80 * dpr), QImage.Format_RGB32)
    image.setDevicePixelRatio(dpr)
    image.fill(QColor("black"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    try:
        m._draw_picture(painter, (scale, 1.0), (pic, 0, 0), (-360, 0, 360))
    finally:
        painter.end()
        m.close()
    row = round(60 * dpr)
    assert all(image.pixelColor(x, row) == QColor("white")
               for x in range(round(25 * dpr), round(215 * dpr)))


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
    """Paint m with the tiles in view drawn all at once (a shown map draws them a
    slice at a time), and return the picture."""
    m.grab()
    cur = m._level()
    for _k, i, j in m._slots(cur):
        if (cur, i, j) not in m._tiles:
            m._tile_now((cur, i, j))
    m._stop_build()
    return m.grab()


def world_map(rings, labels, zoom=2.0):
    m = FlatMap()
    m.resize(1200, 700)
    m.set_land(rings, labels)
    landed(m)
    m.set_loading(False)   # no stations: Bun would wait on it (and move between grabs)
    m.zoom = zoom
    return m


def test_the_land_is_drawn_in_small_parts(qapp):
    rings, _ = outlines()
    m = FlatMap()
    m.set_land(rings)
    landed(m)
    sizes = [sum(p.elementAt(i).isMoveTo() for i in range(p.elementCount()))
             for p in m._land]
    assert sum(sizes) == len(rings) and len(m._land) > 10   # every outline, in parts
    assert max(p.elementCount() for p in m._land) <= max(LAND_PART, *map(len, rings)) + 1


def test_the_land_is_made_a_part_at_a_time(qapp):
    """All ~30 parts of the outlines made in one go were 10-40 ms of back-to-back Qt
    calls as the Radio tab first opened, and a sound playing came up to 33 ms late (a
    skip): the audio threads wait on the UI thread. One part a step now, with a rest
    between, and the land shows once all of them are made."""
    rings, _ = outlines()
    m = FlatMap()
    m.set_land(rings)
    assert len(m._land_new) == 1 and not m._land_set and not m._land   # one at once
    steps = []
    real = m._land_step

    def step():
        before = len(m._land_new)
        real()
        steps.append(len(m._land_new) - before)
    m._land_steps.timeout.disconnect()
    m._land_steps.timeout.connect(step)
    assert process_events(qapp, lambda: m._land_set, 5)
    assert steps and max(steps) == 1 and len(m._land) == len(steps) + 1 > 10
    assert m._land_steps.interval() == flatmap.STEP_GAP_MS
    m.set_land([[(0, 0), (10, 0), (10, 10)]])   # a small one: done at once
    assert m._land_set and len(m._land) == 1


def test_the_map_looks_the_same_drawn_in_parts(qapp, monkeypatch):
    rings, labels = outlines()
    parts = drawn_now(world_map(rings, labels)).toImage()
    monkeypatch.setattr(flatmap, "LAND_PART", 10**9)   # the whole world as one path
    whole = drawn_now(world_map(rings, labels)).toImage()
    a = np.frombuffer(parts.constBits(), np.uint8)
    b = np.frombuffer(whole.constBits(), np.uint8)
    assert a.shape == b.shape
    assert np.mean(np.abs(a.astype(int) - b) > 8) < 0.002   # a few edge pixels at most


@real_pc_timing
def test_drawing_the_world_lets_the_audio_threads_run(qapp):
    """Qt keeps Python's lock while it draws a path: the whole world as one path held
    every other thread for 10-30 ms each time the map was drawn at a new zoom, and the
    sounds playing skipped (it happened as a station started: the map flies to it)."""
    import sys

    from soundboard.core.app import SWITCH_S
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

    from soundboard.core.app import SWITCH_S
    from soundboard.audio.engine import Engine
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


@real_pc_timing
def test_a_new_zoom_is_drawn_in_slices_beside_the_audio(qapp):
    """Every call under 1 ms still made the cable 10-20 ms late as a station started
    (the map flies to it): the audio thread waits out one draw call per numpy step,
    and the new zoom's world was 20-40 ms of them in a row. Now a tile a slice at a
    time, the old tiles (stretched) showing meanwhile, and the same picture at the end."""
    rings, labels = outlines()
    m = world_map(rings, labels, zoom=1.0)
    m.show()
    drawn_now(m)                               # the view's tiles, all at once
    first = set(m._tiles)
    m.zoom = 2.5
    m.grab()
    assert first <= set(m._tiles) and m.busy()          # the old ones, while it's drawn

    def fly_about():
        for zoom in (2.2, 2.4, 2.6, 2.8, 6.0, 20.0):
            m.zoom = zoom
            m.repaint()
            end = time.monotonic() + 5
            while m.busy() and time.monotonic() < end:
                qapp.processEvents()
                time.sleep(0.0005)   # the event loop waiting (without Python's lock)

    worst = quietest(lambda: audio_late_while(fly_about), 0.006)
    assert not m.busy() and not first & set(m._tiles)
    assert worst < 0.006, f"the cable was {worst * 1000:.0f} ms late"
    sliced = m.grab().toImage()
    m.hide()
    m._forget.timeout.emit()                   # let the tiles go...
    m.show()
    whole = drawn_now(m).toImage()             # ...and draw them afresh, all at once
    a = np.frombuffer(sliced.constBits(), np.uint8)
    b = np.frombuffer(whole.constBits(), np.uint8)
    assert a.shape == b.shape and np.array_equal(a, b)
    m.zoom = 2.3
    m.repaint()
    assert m.busy()
    m.hide()
    qapp.processEvents()
    time.sleep(0.01)
    qapp.processEvents()
    assert not m.busy()                        # off screen: not drawn after all


def test_a_drag_only_copies_tiles_at_any_zoom(qapp):
    """Zoomed in past one whole-world picture, every frame of a drag drew the map
    again (10-20 ms: it lagged). Now the tiles in view are only copied, and the
    ones a drag uncovers are drawn ahead of it, round the view."""
    rings, labels = outlines()
    for zoom in (2.5, 6.0, 40.0):
        m = world_map(rings, labels, zoom=zoom)
        m.show()
        m.repaint()
        end = time.monotonic() + 5
        while m.busy() and time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.0005)
        drawn = []
        real = m._tile_steps
        m._tile_steps = lambda *a, drawn=drawn, real=real: drawn.append(a) or real(*a)
        for _ in range(10):
            m.cx += 5 / m._scale()             # 50 px in all: inside the ring drawn ahead
            m.repaint()
        assert drawn == [], f"zoom {zoom}: drew {len(drawn)} tiles while dragging"
        m.close()


def test_a_new_zoom_shows_all_at_once_never_tile_by_tile(qapp):
    """While a new zoom was drawn, its tiles showed one by one over the old ones
    stretched tile by tile, and each stretched tile blurred into the background at
    its edges: a grid of squares over the map. Now the last view stands in as one
    picture, and the new zoom shows when all of it is drawn. (No country names: they're
    drawn over the tiles, not on them.)"""
    rings, _labels = outlines()
    m = world_map(rings, [], zoom=2.0)
    m.set_points([{"id": f"s{i}", "la": -40.0 + i, "lo": -100.0 + 2 * i, "k": i}
                  for i in range(80)])
    m._reveal_t0 = None                        # (the first stations' fade-in: not here)
    m.show()

    def done():
        # (offscreen, repaint() may not paint; a slow runner takes well over 5 s)
        m.grab()
        end = time.monotonic() + 30
        while time.monotonic() < end:
            if not m.busy():
                m.grab()
                if m._stable is not None and m._stable[0] == m._level():
                    break
            qapp.processEvents()
            time.sleep(0.0005)
        assert m._stable is not None and m._stable[0] == m._level()

    done()
    m._zoom_by(1.6)
    def look():
        img = m.grab().toImage()   # kept: constBits() points into it
        return hash(bytes(img.constBits()))

    seen = [look()]   # each different picture shown, in turn (this one starts it)
    assert m.busy()
    end = time.monotonic() + 30
    while m.busy() and time.monotonic() < end:
        h = look()
        if not seen or seen[-1] != h:
            seen.append(h)
        for _ in range(5):
            qapp.processEvents()
            time.sleep(0.001)
    assert not m.busy()
    done()
    final = look()
    if seen[-1] != final:
        seen.append(final)
    # the old view (stretched), then the new one all at once (the ring round it may
    # still be drawing then): nothing in between
    assert len(seen) == 2, f"{len(seen)} different pictures"
    m.close()


def test_bun_waits_on_the_map_and_the_first_stations_fade_in(qapp):
    from soundboard.ui.radio import flatmap
    m = FlatMap()
    m.resize(600, 400)
    m.show()
    qapp.processEvents()
    assert m._loading.isVisible()              # the map is there (it drags) with Bun on it
    m.set_land([], [])
    m.set_points([{"id": f"s{i}", "la": 0.0, "lo": float(i), "k": i} for i in range(50)])
    assert not m._loading.isVisible() and m.revealing()
    m.repaint()
    end = time.monotonic() + flatmap.NAMES_FIRST_S + flatmap.REVEAL_S + 2
    while m.revealing() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)
    assert not m.revealing()
    m.set_points([])
    m.show_message("The radio is down right now.")
    m.set_loading(True)
    assert m.oops.isVisible() and m.oops.bun.sad > 0.5   # sad Bun says what's wrong
    assert m.oops.line.text() == "The radio is down right now."
    assert not m._loading.isVisible()
    m.close()


def test_the_country_names_show_before_the_dots(qapp):
    """The names come first (even when the stations beat the land in), and the dots
    fade in after."""
    from soundboard.ui.radio import flatmap
    rings, labels = outlines()
    m = FlatMap()
    m.resize(600, 400)
    m.show()
    m.set_points([{"id": f"s{i}", "la": 0.0, "lo": float(i), "k": i} for i in range(50)])
    assert m.revealing() and m._reveal_t0 is None   # no dots till the land is in
    m.set_land(rings, labels)
    assert process_events(qapp, lambda: m._land_set, 5)   # (made a part a step)
    assert m._reveal_t0 > time.monotonic() + flatmap.NAMES_FIRST_S / 2
    drawn = []
    real = m._sprite
    m._sprite = lambda *a: drawn.append(a) or real(*a)
    m.grab()
    assert m._label_pm and not drawn                # the names are on the map, no dots yet
    end = time.monotonic() + flatmap.NAMES_FIRST_S + flatmap.REVEAL_S + 2
    while m.revealing() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)
    assert not m.revealing()
    m.grab()
    assert drawn
    m.close()


def test_new_stations_dont_draw_the_map_again(qapp):
    """The dots aren't on the map's tiles (drawn over them every paint, ~1.5 ms for
    3000): a new station list, a filter, leaves the drawn land as it is."""
    m = FlatMap()
    m.resize(600, 400)
    m.show()
    m.set_land(*outlines())
    landed(m)
    m.set_points([{"id": f"s{i}", "la": (i % 50) - 25.0, "lo": i * 1.1 - 165, "k": i}
                  for i in range(300)])
    assert process_events(qapp, lambda: (m.grab(), not m.busy())[1], 10)
    level, tiles = m._level(), dict(m._tiles)
    m.set_points([{"id": f"t{i}", "la": (i % 40) - 20.0, "lo": i * 1.3 - 160, "k": i}
                  for i in range(200)])
    m.grab()
    assert m._level() == level and not m.busy()
    assert all(m._tiles.get(k) is pm for k, pm in tiles.items())
    m.close()


def test_the_decoder_is_loaded_off_the_ui_thread_once(qapp, monkeypatch):
    """Qt loaded FFmpeg (avcodec and co, tens of MB) as the first station started, on
    the UI thread and holding Python's lock: 10-60 ms, and the sounds playing skipped."""
    import ctypes
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows only")
    loaded = []
    monkeypatch.setattr(ctypes, "WinDLL",
                        lambda path: loaded.append((path, threading.current_thread().name)))
    monkeypatch.setattr(radio, "_preloaded", False)
    radio.preload_decoder()   # the Radio tab's first show calls it
    radio.preload_decoder()   # and again: a no-op
    end = time.monotonic() + 5
    while not any("ffmpeg" in f.lower() for f, _ in loaded) and time.monotonic() < end:
        time.sleep(0.01)
    names = [Path(f).name.lower() for f, _ in loaded]
    assert names[0].startswith("avutil") and names[-1].startswith("ffmpeg")
    assert any(n.startswith("avcodec") for n in names)
    assert len(names) == len(set(names))                       # once, for both calls
    assert all(t == "radio-preload" for _, t in loaded)        # never the UI thread


def test_each_decoder_image_is_made_before_the_loader_takes_it(qapp, monkeypatch):
    """A file Windows hasn't seen yet (just installed) is checked as its image is made.
    In LoadLibrary that's under the loader lock, and every thread start waits for it:
    the window froze 6 s as the Apps tab started its lister. Each image is made first,
    on the preload thread, outside the lock, and kept until it's loaded."""
    import ctypes
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows only")
    steps = []
    made = {}

    def image(path):
        steps.append(("image", Path(path).name, threading.current_thread().name))
        made[Path(path).name] = (len(made) + 1, 0)
        return made[Path(path).name]

    monkeypatch.setattr(radio, "_image_section", image)
    monkeypatch.setattr(radio, "_close", lambda h: steps.append(("close", h, "")))
    monkeypatch.setattr(ctypes, "WinDLL", lambda path: steps.append(
        ("load", Path(path).name, threading.current_thread().name)))
    monkeypatch.setattr(radio, "_preloaded", False)
    radio.preload_decoder()
    end = time.monotonic() + 5
    while sum(s[0] == "close" for s in steps) < len(made or [1]) and time.monotonic() < end:
        time.sleep(0.01)
    images = [n for kind, n, _ in steps if kind == "image"]
    loads = [n for kind, n, _ in steps if kind == "load"]
    assert images and images == loads                       # every one, in load order
    first_load = next(i for i, s in enumerate(steps) if s[0] == "load")
    assert all(s[0] == "image" for s in steps[:first_load])  # all made before any load
    assert all(t == "radio-preload" for kind, _, t in steps if kind != "close")
    closes = [h for kind, h, _ in steps if kind == "close"]
    assert sorted(closes) == sorted(made.values())          # let go of, after the loads
    assert steps.index(("close", closes[0], "")) > max(
        i for i, s in enumerate(steps) if s[0] == "load")


def test_a_decoder_image_is_really_made(tmp_path):
    """The real call: Windows makes the image of one of Qt's FFmpeg DLLs, and a file
    that isn't one gets none (the load then goes on as before)."""
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows only")
    dll = radio._decoder_files()[0]
    fh, section = radio._image_section(dll)
    assert fh and section
    radio._close((fh, section))
    junk = tmp_path / "not-a.dll"
    junk.write_bytes(b"not a program")
    fh, section = radio._image_section(junk)
    assert fh and not section
    radio._close((fh, section))
    assert radio._image_section(tmp_path / "missing.dll") == (0, 0)
