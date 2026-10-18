"""Bun's kept shapes (bunny.CACHE): the paths that don't change from frame to frame are
built once and reused. That must never show: every theme, pose, prop, look and skit
frame comes out the same pixels with them kept as built fresh."""
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from soundboard.ui.bun import bunny
from soundboard.ui.kit import theme
from soundboard.style import bunnyfit

POSES = (
    {}, {"blink": 1.0}, {"blink": 0.4, "mouth": 0.7, "look": -1.0}, {"sad": 0.3},
    {"sad": 0.7, "wave": 0.6}, {"sad": 1.0}, {"angry": 0.8}, {"smug": True},
    {"nightcap": True, "blink": 1.0}, {"robot": True, "led": 0.8, "mouth": 0.5},
    {"robot": True, "sad": 0.8}, {"nod": 8.0, "dip": 2.0, "ears": 6.0}, {"kick": 1.0},
    {"kick": -0.6, "wave": -1.0}, {"hold": ((22.0, 95.0), (78.0, 95.0))},
    {"hold": (None, (82.0, 88.0)), "sad": 0.2}, {"outfit": ()},
)


def _draw(prop=None, **kw) -> QImage:
    img = QImage(130, 156, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    bunny.draw_bunny(p, QRectF(3, 3, 124, 150), prop, **kw)
    p.end()
    return img


def _both(monkeypatch, prop=None, **kw):
    """(kept, fresh): drawn twice with the shapes kept (the second from the cache),
    then built fresh."""
    _draw(prop, **kw)
    kept = _draw(prop, **kw)
    monkeypatch.setattr(bunny, "CACHE", False)
    fresh = _draw(prop, **kw)
    monkeypatch.setattr(bunny, "CACHE", True)
    return kept, fresh


@pytest.fixture
def cleared():
    was = theme.current_name
    yield
    theme.set_current(was)


def test_every_theme_and_pose_is_the_same_kept_or_fresh(qapp, monkeypatch, cleared):
    for name in theme.THEMES:
        theme.set_current(name)
        for pose in POSES:
            kept, fresh = _both(monkeypatch, **pose)
            assert kept == fresh, (name, pose)


def test_every_prop_and_look_is_the_same_kept_or_fresh(qapp, monkeypatch, cleared):
    theme.set_current(bunny.theme.DEFAULT)
    for prop in bunny.PROPS:
        for swing in (0.0, 0.5, 1.0):
            kept, fresh = _both(monkeypatch, prop, swing=swing, nod=3.0 * swing)
            assert kept == fresh, (prop, swing)
    for ears in ("up", "left", "right", "both"):
        for tail in bunnyfit.TAILS:
            for pattern in ((), ("patch",), ("spots",), ("mask",), ("patch", "spots")):
                kit = {"ears": ears, "tail": tail, "pattern": pattern, "fur": "#5c5964",
                       "extras": ("chomp", "earring", "shiner", "freckles", "bandaid")}
                for pose in ({}, {"sad": 0.6, "wave": 0.3}):
                    kept, fresh = _both(monkeypatch, kit=kit, **pose)
                    assert kept == fresh, (ears, tail, pattern, pose)


def test_every_skit_frame_is_the_same_kept_or_fresh(qapp, monkeypatch, cleared):
    """Whole frames of the live widget (his skits hold things, so his arms reach)."""
    from soundboard.ui.bun import bunnywidget, bunskits

    class Clock:
        now = 1000.0

        def monotonic(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(bunnywidget, "time", clock)
    for name in bunskits.SKITS:
        theme.apply(qapp, name)
        b = bunnywidget.BunnyWidget(height=120)
        b.resize(b.sizeHint())
        b._next_fidget = 1e12
        b.skit()
        for i in range(int(bunskits.for_theme(name)[0] * 6) + 1):
            clock.now += 1 / 6
            b._step()
            if i % 2:
                continue
            b.grab()
            kept = b.grab().toImage()
            monkeypatch.setattr(bunny, "CACHE", False)
            fresh = b.grab().toImage()
            monkeypatch.setattr(bunny, "CACHE", True)
            assert kept == fresh, (name, i)
        b.deleteLater()


def test_shapes_are_kept_and_cleared(qapp):
    bunny._tail_shape.cache_clear()
    a = bunny._tail_shape("fluffy")
    assert bunny._tail_shape("fluffy") is a          # kept
    bunny._tail_shape.cache_clear()
    assert bunny._tail_shape("fluffy") is not a      # built again
    assert bunny._tail_shape("fluffy") == a          # the same shape
