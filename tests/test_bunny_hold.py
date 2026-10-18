"""Bun's and Hoot's kept pictures (bunnywidget.HOLD, owl.HOLD): a frame drawn through
the kept picture looks the same as one drawn straight onto the widget, at any screen
scale; the picture stands in only while he's moved less than HOLD_PX; and a frame
where nothing moved isn't repainted at all."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter

from soundboard import theme
from soundboard.style import owl
from soundboard.ui import bunnywidget as bw
from test_bunnywidget import _Clock

THEMES = ("Dark", "Light", "Ocean", "Vampire", "Hacker")


def _pixels(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    return np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(
        img.height(), -1).astype(int)


def _shot(w, dpr: float) -> np.ndarray:
    """The widget as the screen would show it at `dpr`, on a backdrop."""
    img = QImage(round(w.width() * dpr), round(w.height() * dpr),
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(0xff2a2a3a)
    p = QPainter(img)
    w.render(p, QPoint())
    p.end()
    return _pixels(img)


def _same(a: np.ndarray, b: np.ndarray):
    # (a picture laid over the backdrop rounds a hair differently from drawing on it)
    assert np.abs(a - b).max() <= 2


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(bw, "time", c)
    monkeypatch.setattr(owl, "time", c)
    monkeypatch.setattr(bw, "local_hour", lambda: 12)
    monkeypatch.setattr(bw.appstate, "active", lambda: True)
    return c


def _tick(b, clock, n):
    for _ in range(n):
        clock.now += 1 / 60
        b._last = clock.now - 1 / 60
        b._step()


@pytest.mark.parametrize("name", THEMES)
@pytest.mark.parametrize("dpr", (1.0, 1.25, 1.5, 2.0))
def test_bun_through_his_kept_picture_looks_the_same(qapp, clock, monkeypatch, name, dpr):
    theme.set_current(name)
    for kw in ({}, {"prop": "headphones"}, {"sad": 0.6}, {"robot": True}):
        b = bw.BunnyWidget(height=72, pad=12, **kw)
        b.resize(b.sizeHint())
        b.set_level(0.2)
        for _ in range(6):   # (a few moments: talking, blinking, bobbing)
            _tick(b, clock, 7)
            monkeypatch.setattr(bw, "HOLD", False)
            plain = _shot(b, dpr)
            monkeypatch.setattr(bw, "HOLD", True)
            b._kept_pose = None   # (a fresh picture)
            _same(_shot(b, dpr), plain)
            assert b._kept_pose is not None
        b.close()


@pytest.mark.parametrize("name", THEMES)
@pytest.mark.parametrize("dpr", (1.0, 1.5))
def test_hoot_through_his_kept_picture_looks_the_same(qapp, clock, monkeypatch, name, dpr):
    theme.set_current(name)
    h = owl.OwlWidget(96)
    h._mouse = lambda: None
    h.resize(h.sizeHint())
    for i in range(6):
        for _ in range(9):
            h.step(1 / 30)
        if i == 3:
            h.cheer()   # (a hop and his bubble)
        monkeypatch.setattr(owl, "HOLD", False)
        plain = _shot(h, dpr)
        monkeypatch.setattr(owl, "HOLD", True)
        h._kept_pose = None
        _same(_shot(h, dpr), plain)
    h.close()


def test_his_picture_is_kept_only_while_he_hardly_moves(qapp, clock):
    theme.set_current("Dark")
    b = bw.BunnyWidget(height=120, pad=14)
    b.resize(b.sizeHint())
    b.grab()
    kept = b._kept_pose
    assert kept is not None
    pose = b.springy(b.pose())
    assert b._held(pose, 1.0) is kept   # nothing moved yet
    for key, by in (("dy", 0.3), ("ears", 0.3), ("blink", 0.03), ("look", 0.2)):
        assert b._held({**pose, key: pose[key] + by}, 1.0) is not kept, key
    assert b._held({**pose, "dy": pose["dy"] + 0.1}, 1.0) is kept
    assert b._held({**pose, "dy": pose["dy"] + 0.1}, 3.0) is not kept   # (a sharper screen)
    assert b._held({**pose, "alpha": 0.99}, 1.0) is not kept           # (a fade)
    assert b._held({**pose, "prop": "mic"}, 1.0) is not kept
    theme.set_current("Ocean")
    assert b._held(pose, 1.0) is not kept   # (another outfit)
    b.close()


def test_a_frame_where_nothing_moved_is_not_repainted(qapp, clock):
    theme.set_current("Dark")
    b = bw.BunnyWidget(height=72, pad=12)
    b.resize(b.sizeHint())
    b.show()
    qapp.processEvents()
    asked = []
    b.update = lambda *a: asked.append(1)
    b.grab()
    clock.now += 0.001   # (a moment: he can't have moved a pixel)
    b._last = clock.now
    b._step()
    assert not asked
    b.burst(3)           # notes in the air: they move every frame
    b._step()
    assert asked
    b.close()


def test_hoot_skips_a_frame_where_nothing_moved(qapp, clock):
    theme.set_current("Dark")
    h = owl.OwlWidget(96)
    h._mouse = lambda: None
    h.resize(h.sizeHint())
    h.grab()
    asked = []
    h.update = lambda *a: asked.append(1)
    h._last = clock.now
    h._tick()            # (no time passed)
    assert not asked
    h.cheer()
    h._tick()
    assert asked
    h.close()
