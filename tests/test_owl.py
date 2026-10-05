"""Hoot alive (ui/owl.OwlWidget, a copy of Onion Watch's): every act he does while
he waits runs start to end and paints, the mouse coming near cuts an act short and
perks him up, and a click cheers him. Offscreen, stepped by hand: no timers are waited on."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from soundboard.ui import owl


def paint(w):
    img = QImage(w.size(), QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    w.render(img)
    return img


def test_every_act_runs_and_paints(qapp):
    w = owl.OwlWidget(80)
    w.resize(w.sizeHint())
    for act, length in owl.ACTS.items():
        w.start(act)
        assert w.act == act
        for _ in range(int(length / 0.1) + 2):
            w.step(0.1, mouse=None)
            paint(w)
        assert w.act is None


def test_begging_says_something_and_clasps(qapp):
    w = owl.OwlWidget(80, lines=("please?",))
    w.start("plead")
    w.step(owl.ACTS["plead"] / 2, mouse=None)
    assert w.say == "please?"
    assert w.pose()["clasp"] > 0.9


def test_mouse_near_perks_him_up(qapp):
    w = owl.OwlWidget(80)
    w.resize(w.sizeHint())
    sad = w.pose()["sad"]
    w.start("doze")
    for _ in range(30):
        w.step(0.05, mouse=(0.5, -0.2))
    assert w.act is None                   # woke up for you
    assert w.pose()["sad"] < sad / 3
    assert w.pose()["look"] > 0.5          # and looks your way


def test_click_cheers(qapp):
    w = owl.OwlWidget(80, lines=(), joy=("yay",))   # no begging line once joy ends
    # (his first act is due 2-3.5 s in: a plead within the 2.4 s stepped here said one)
    w.resize(w.sizeHint())
    hits = []
    w.clicked.connect(lambda: hits.append(1))
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    c = QPointF(w.width() / 2, w.height() / 2)
    w.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, c, c, Qt.LeftButton,
                                  Qt.LeftButton, Qt.NoModifier))
    assert hits and w.say == "yay"
    w.step(0.4, mouse=None)
    assert "joy" in w.pose()
    w.step(2.0, mouse=None)
    assert "joy" not in w.pose() and w.say == ""


def test_owl_image_still_plain(qapp):
    img = owl.owl_image(120)
    assert img.height() == 120 and not img.isNull()



def test_he_slows_down_when_only_swaying(qapp):
    w = owl.OwlWidget(80)
    w._next_act = w._next_blink = w._next_glance = 1e9   # nothing due
    for _ in range(60):
        w.step(0.1, mouse=None)
    assert not w.busy()            # 10 frames a second for the sway
    w.start("doze")
    assert w.busy()
    w.act = None
    assert not w.busy()
    w.cheer()
    assert w.busy()
    w._joy_t = -1.0
    w.say = ""
    w.step(0.1, mouse=(0.1, 0.1))  # the mouse comes near
    assert w.busy()
