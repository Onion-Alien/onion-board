"""Bun's animated widget: talking opens his mouth and throws notes, silence closes
it again, and the plain drawing still works with every pose."""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter

from soundboard.bunny import PROPS, draw_bunny
from soundboard.ui.bunnywidget import BunnyWidget


def _run(qapp, b, steps, level=None):
    for _ in range(steps):
        if level is not None:
            b.set_level(level)
        b._last -= 0.035   # pretend a frame's worth of time passed
        b._step()


def test_talking_opens_mouth_and_throws_notes(qapp):
    b = BunnyWidget("mic")
    _run(qapp, b, 20, level=0.3)
    assert b.pose()["mouth"] > 0.2
    assert b.notes
    _run(qapp, b, 80)
    assert b.pose()["mouth"] < 0.05
    assert not b.notes   # they all floated off


def test_burst_and_paint(qapp):
    b = BunnyWidget("headphones", celebrate=True)
    b.resize(b.sizeHint())
    b.burst(5)
    assert len(b.notes) == 5
    img = b.grab()
    assert not img.isNull()


def test_every_pose_draws(qapp):
    img = QImage(100, 120, QImage.Format_ARGB32_Premultiplied)
    for prop in PROPS:
        for pose in ({}, {"blink": 1.0, "mouth": 1.0, "ears": 15}, {"blink": 0.4}):
            p = QPainter(img)
            draw_bunny(p, QRectF(0, 0, 100, 120), prop, **pose)
            p.end()
