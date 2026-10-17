"""Hoot alive (style/owl.OwlWidget, shared with Onion Watch): every act he does while
he waits runs start to end and paints, the mouse coming near cuts an act short and
perks him up, and a click cheers him. Offscreen, stepped by hand: no timers are waited on."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from soundboard.style import owl


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



def test_swaying_keeps_the_full_frame_rate(qapp):
    w = owl.OwlWidget(80)
    w._next_act = w._next_blink = w._next_glance = 1e9   # nothing due
    w._timer.start(owl.FAST_MS)
    for _ in range(5):
        w._tick()
    assert w._timer.interval() == owl.FAST_MS
    w._timer.stop()


def _steps(w, secs, fps=30, mouse=None, keys=("dy", "rot", "blink", "sad", "tufts")):
    """Steps him `secs` at `fps`; the biggest frame-to-frame jump per pose key."""
    worst, last = dict.fromkeys(keys, 0.0), None
    for _ in range(round(secs * fps)):
        w.step(1 / fps, mouse=mouse)
        p = w.pose()
        if last:
            for k in keys:
                worst[k] = max(worst[k], abs(p[k] - last[k]))
        last = p
    return worst


def test_an_act_cut_short_fades_out_instead_of_snapping(qapp):
    w = owl.OwlWidget(96)
    w._next_blink = w._next_glance = 1e9
    w.start("doze")
    _steps(w, 2.0)                       # nodded right off: eyes shut, slumped
    assert w.pose()["blink"] > 0.8
    jumps = _steps(w, 1.0, mouse=(0.3, 0.0))   # the mouse wakes him
    assert w.act is None
    assert jumps["blink"] < 0.3 and jumps["rot"] < 1.5 and jumps["dy"] < 1.5


def test_a_landing_squashes_him_and_he_springs_back(qapp):
    w = owl.OwlWidget(96, lines=(), joy=())
    w._next_act = w._next_blink = w._next_glance = 1e9
    _steps(w, 0.5)
    w.cheer()
    sy = []
    for _ in range(60):
        w.step(1 / 30, mouse=None)
        sy.append(w.pose()["sy"])
    assert min(sy) < 0.97                # squashed on a landing
    _steps(w, 1.5)
    assert abs(w.pose()["sy"] - 1) < 0.02   # and back in shape


class _Grid:
    """A steady beat for the dance (the beat-grid styles)."""
    style, bpm = "electronic", 120.0

    def __init__(self, clock):
        self.clock, self.t0 = clock, clock.now

    def beat(self, now):
        return (now - self.t0) * self.bpm / 60


def test_his_bob_on_the_beat_never_jumps(qapp, monkeypatch):
    class Clock:
        now = 100.0

        def monotonic(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(owl, "time", clock)
    w = owl.OwlWidget(96)
    w._next_act = w._next_blink = w._next_glance = 1e9
    w.set_groove(_Grid(clock))
    dys = []
    for _ in range(4 * 60):
        clock.now += 1 / 60
        w.step(1 / 60, mouse=None)
        dys.append(w.pose()["dy"])
    tail = dys[120:]
    assert max(tail) - min(tail) > 5                       # bobbing
    assert max(abs(b - a) for a, b in zip(tail, tail[1:])) < 2.5   # (was a 3.5 px snap)
    peaks = [i for i in range(1, len(tail) - 1) if tail[i - 1] <= tail[i] > tail[i + 1]
             and tail[i] > max(tail) - 1]
    for i in peaks:                      # bottoms out right on the beat
        assert abs(((120 + i + 1) / 60 * 2 + 0.5) % 1 - 0.5) < 0.04
