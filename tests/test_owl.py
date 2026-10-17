"""Hoot alive (style/owl.OwlWidget, shared with Onion Watch): every act he does while
he waits runs start to end and paints, the mouse coming near cuts an act short and
perks him up, and a click cheers him. Offscreen, stepped by hand: no timers are waited on."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

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
    from soundboard.style import mascotlines
    assert hits and w.say in ("yay",) + mascotlines.hoot()   # his own line or his theme's
    w.step(0.4, mouse=None)
    assert "joy" in w.pose()
    w.step(2.0, mouse=None)
    w.step(1.0, mouse=None)   # (a longer line stays up until it's read)
    assert "joy" not in w.pose() and w.say == ""


def test_owl_image_still_plain(qapp):
    img = owl.owl_image(120)
    assert img.height() == 120 and not img.isNull()


def _hoot(k: int = 1, **kw) -> QImage:
    img = QImage(100 * k, 120 * k, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    owl.draw_owl(p, QRectF(0, 0, 100 * k, 120 * k), **kw)
    p.end()
    return img


def test_every_look_names_a_theme_and_known_keys(qapp):
    from soundboard import theme
    for name, kit in owl.LOOKS.items():
        assert name in theme.THEMES, name
        assert set(kit) <= set(owl.VANILLA), name
        assert kit.get("marks", "scallops") in owl.MARKS, name
        assert kit.get("tufts", "point") in owl.TUFTS, name
        for key in ("feather", "wing", "iris", "face", "belly", "mark", "beak", "feet"):
            if kit.get(key) is not None:
                assert QColor(kit[key]).isValid(), (name, key)


def test_every_theme_but_the_plain_ones_has_its_own_hoot(qapp):
    from soundboard import theme
    plain = {"Dark", "High Contrast"}      # the default (artwork) and accessibility
    for name in theme.THEMES:
        assert (name in owl.LOOKS) == (name not in plain), name
    assert owl.look("Dark") == owl.VANILLA
    bare = _hoot(outfit=(), kit=owl.VANILLA)
    for name in owl.LOOKS:
        assert _hoot(outfit=(), kit=owl.look(name)) != bare, name


def test_plain_hoot_keeps_his_old_colours(qapp):
    assert owl.VANILLA["feather"] == owl.FEATHER.name()
    assert owl.VANILLA["wing"] == owl.FEATHER_DARK.name()
    assert owl.VANILLA["iris"] == owl.EYE_LOW.name()
    assert owl.VANILLA["beak"] == owl.BEAK.name() and owl.VANILLA["feet"] is None
    assert owl.VANILLA["marks"] == "scallops" and owl.VANILLA["tufts"] == "point"


def test_every_look_change_shows(qapp):
    plain = _hoot(outfit=(), kit=owl.VANILLA)
    changes = [{"feather": "#ff3b2f"}, {"wing": "#3b2fff"}, {"iris": "#ffd66b"},
               {"face": "#ffd0dc"}, {"belly": "#c9f2f7"}, {"mark": "#ff00ff"},
               {"beak": "#39ff7a"}, {"feet": "#ff8cc6"}]
    changes += [{"marks": m} for m in owl.MARKS if m != "scallops"]
    changes += [{"tufts": t} for t in owl.TUFTS if t != "point"]
    for kit in changes:
        assert _hoot(outfit=(), kit=kit) != plain, kit
    # every theme's keys show too (each draws something of its own)
    for name, kit in owl.LOOKS.items():
        for key, value in kit.items():
            assert _hoot(outfit=(), kit={key: value}) != plain, (name, key)


def test_belly_marks_stay_on_his_belly(qapp):
    mark = "#ff00ff"   # (a colour nothing else on him uses)
    belly = QPainterPath()
    belly.addEllipse(QRectF(29, 70, 42, 42))
    for kind in owl.MARKS:
        img = _hoot(4, outfit=(), kit={"marks": kind, "mark": mark})
        pink = [(x, y) for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
                 if (c := img.pixelColor(x, y)).red() > 200 and c.blue() > 200
                 and c.green() < 60]
        assert bool(pink) == (kind != "plain"), kind
        for x, y in pink:
            assert belly.contains(QPointF(x / 4, y / 4)), (kind, x, y)


def test_his_look_follows_the_theme(qapp, monkeypatch):
    from soundboard import theme
    monkeypatch.setattr(theme, "current_name", "Mocha")
    assert _hoot(outfit=()) == _hoot(outfit=(), kit=owl.look("Mocha"))
    assert _hoot(outfit=()) != _hoot(outfit=(), kit=owl.VANILLA)
    monkeypatch.setattr(theme, "current_name", "Dark")
    assert _hoot(outfit=()) == _hoot(outfit=(), kit=owl.VANILLA)
    # given feathers still win over the look's (and their own shade goes with them)
    assert (_hoot(outfit=(), feather="#ff0000")
            == _hoot(outfit=(), feather="#ff0000", kit={"feather": "#00ff00",
                                                        "wing": "#0000ff"}))



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


def test_his_beak_opens_when_he_cheers(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter

    def hoot(**kw):
        img = QImage(100, 120, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        owl.draw_owl(p, QRectF(0, 0, 100, 120), outfit=(), **kw)
        p.end()
        return img
    assert hoot(beak=1.0) != hoot()
    w = owl.OwlWidget(96)
    w.cheer()
    w.step(0.3, mouse=None)
    assert w.pose()["beak"] > 0.3


def test_wave_raises_one_wing_and_swings_it(qapp):
    still = _hoot(outfit=(), kit=owl.VANILLA)
    assert _hoot(outfit=(), kit=owl.VANILLA, wave=None) == still
    a = _hoot(outfit=(), kit=owl.VANILLA, wave=-1.0)
    b = _hoot(outfit=(), kit=owl.VANILLA, wave=1.0)
    assert a != still and b != still and a != b
    # only the wing on your left moves: his right half is as it was
    right = [(x, y) for x in range(52, 100, 3) for y in range(0, 120, 3)]
    assert all(a.pixelColor(x, y) == still.pixelColor(x, y) for x, y in right)
