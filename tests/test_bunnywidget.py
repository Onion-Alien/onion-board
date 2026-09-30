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


def test_build_act_runs_off_fetches_tools_and_hammers(qapp):
    b = BunnyWidget("plug")
    b.resize(b.sizeHint())
    b.build()
    phases = []
    for _ in range(140):   # ~5 s
        _run(qapp, b, 1)
        if b.act_phase() not in phases:
            phases.append(b.act_phase())
        if b.act_phase() == "cloud":
            assert not b.pose()["shown"]
        b.grab()           # every frame paints
    assert phases == ["dash", "cloud", "back", "hammer"]
    assert b.prop == "hammer" and b._blows >= 3 and b.puffs
    b.stop_building(True)
    assert not b.building and b.prop == "star" and b.celebrate
    b.build()
    b.stop_building(False)
    assert b.prop == "plug" and not b.celebrate


def test_hammer_swings(qapp):
    img = QImage(100, 120, QImage.Format_ARGB32_Premultiplied)
    for swing in (0.0, 0.5, 1.0):
        p = QPainter(img)
        draw_bunny(p, QRectF(0, 0, 100, 120), "hammer", swing=swing)
        p.end()


def test_sad_bun_droops_and_cheers_up_while_hoping(qapp):
    b = BunnyWidget(sad=0.9)
    b.resize(b.sizeHint())
    _run(qapp, b, 5)
    glum = b.pose()
    assert glum["sad"] > 0.8 and glum["ears"] > 20   # ears drooping
    b.hope(True)                                     # files dragged over him
    assert b.notes
    _run(qapp, b, 30)
    assert b.pose()["sad"] < 0.1
    assert not b.grab().isNull()
    b.hope(False)
    _run(qapp, b, 120)
    assert b.pose()["sad"] > 0.8                     # back to waiting


def test_sad_bun_begs_in_a_bubble_and_cheers_when_clicked(qapp):
    b = BunnyWidget(sad=0.9, lines=("add a sound?",), hope_lines=("for me?",),
                    joy_lines=("yay",))
    b.resize(b.sizeHint())
    assert b.sizeHint().width() > BunnyWidget(sad=0.9).sizeHint().width()   # bubble room
    b._next_beg = 0
    _run(qapp, b, 3)
    assert b.say == "add a sound?"
    assert not b.grab().isNull()
    b.hope(True)
    assert b.say == "for me?"
    b.hope(False)
    assert b.say == ""
    hits = []
    b.clicked.connect(lambda: hits.append(1))
    b.cheer()
    assert b.say == "yay"
    _run(qapp, b, 15)
    assert b.pose()["sad"] < 0.3             # happy while cheering
