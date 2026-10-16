"""Bun's animated widget: talking opens his mouth and throws notes, silence closes
it again, and the plain drawing still works with every pose."""

import time

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from soundboard.bunny import PROPS, draw_bunny
from soundboard.ui.bunnywidget import BunnyWidget


def _run(qapp, b, steps, level=None):
    for _ in range(steps):
        if level is not None:
            b.set_level(level)
        # exactly a frame's worth of time passed: only the pretend time, not however
        # long the test took since the last step (painting every frame on a slow
        # machine moved the act on, ending it between sawdust puffs)
        b._last = time.monotonic() - 0.035
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
    # ears drooping: folded down from the middle, not tilted out sideways (that read
    # as cross "airplane ears")
    assert glum["sad"] > 0.8 and glum["ears"] < 20
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

def test_idle_bob_runs_at_the_same_frame_rate_as_the_twitches(qapp):
    from soundboard.ui import bunnywidget
    b = BunnyWidget("plug")
    b._timer.start(bunnywidget.FAST_MS)   # as if on screen
    far = time.monotonic() + 60
    b._next_blink = b._next_flick = b._next_sigh = far
    _run(qapp, b, 5)                      # nothing but the bob going on
    assert b._timer.interval() == bunnywidget.FAST_MS
    b._timer.stop()


def test_headphones_trickle_calm_notes(qapp):
    b = BunnyWidget("headphones")
    b.resize(b.sizeHint())
    for _ in range(90):                 # ~3 s of silence: a note from his headphones
        _run(qapp, b, 1)
        if b.notes:
            break
    assert b.notes and all(n.calm for n in b.notes)


def test_robot_bunny_widget_build_and_props(qapp):
    from soundboard.bunny import bunny_image
    img = bunny_image(100, "wrench", robot=True)
    assert not img.isNull()
    b = BunnyWidget(robot=True)
    assert b.robot
    b.resize(b.sizeHint())
    b.build()
    assert b.building
    phases = []
    for _ in range(140):
        _run(qapp, b, 1)
        if b.act_phase() not in phases:
            phases.append(b.act_phase())
    assert "dash" in phases and "cloud" in phases and "back" in phases and "hammer" in phases
    assert b.prop == "wrench"
    b.stop_building(True)
    assert not b.building and b.celebrate and b.prop == "star"
    b.build()
    b.stop_building(False)
    assert not b.building and not b.celebrate and b.sad > 0.5


def _top_ink_row(img: QImage) -> int:
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 40:
                return y
    return img.height()


def test_sad_ears_fold_down_from_the_middle(qapp):
    from soundboard.bunny import bunny_image
    tops = []
    for sad in (0.0, 1.0):
        img = QImage(100, 120, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        draw_bunny(p, QRectF(0, 0, 100, 120), sad=sad, outfit=())
        p.end()
        tops.append(_top_ink_row(img))
    assert tops[1] > tops[0] + 12        # the tips came down a long way
    assert not bunny_image(60, robot=True).isNull()


def _frames(qapp, b, secs):
    for _ in range(round(secs / 0.035)):
        _run(qapp, b, 1)
        b.grab()


def test_run_off_stays_in_his_box_with_no_empty_frames(qapp):
    b = BunnyWidget("plug", pong=True)
    b.resize(b.sizeHint())
    for act in (b.build, b.fetch_bat):
        b.calm_down()
        act()
        while b.act_phase() in ("dash", "cloud", "back"):
            _run(qapp, b, 1)
            if b.act_phase() not in ("dash", "cloud", "back"):
                break
            pose = b.pose()
            assert pose["dx"] == 0            # he dives into the cloud right where he is
            if b.act_phase() == "dash":
                assert pose["sx"] <= 1.1      # squashed, stretched, never moved off
            # every frame shows him or the cloud (never an empty box)
            assert pose["shown"] or b.act_phase() in ("cloud", "back")
        assert b.act_phase() in ("hammer", "bat")


def test_rummaging_tosses_junk_out_of_the_cloud(qapp):
    b = BunnyWidget("plug")
    b.resize(b.sizeHint())
    b.build()
    seen = set()
    while b.act_phase() != "hammer":
        _run(qapp, b, 1)
        seen |= {j.kind for j in b.junk}
        for j in b.junk:                      # all of it lands inside the widget
            assert -4 <= j.x <= b.width() + 4
    assert seen


def test_hammering_builds_a_speaker_and_success_finishes_it(qapp):
    from soundboard.ui import bunnywidget as bw
    b = BunnyWidget("plug")
    b.resize(b.sizeHint())
    b.build()
    _frames(qapp, b, bw.BACK_END + 4 * bw.SWING)
    assert b._parts == bw.PARTS - 1           # the last part waits for the result
    b.stop_building(True)
    assert b._parts == bw.PARTS and b._fin_t >= 0 and b.prop == "star"
    _frames(qapp, b, bw.FINALE + 0.2)
    assert b._fin_t < 0


def test_a_failed_build_snaps_then_he_droops_and_sighs(qapp):
    from soundboard.ui import bunnywidget as bw
    b = BunnyWidget("plug")
    b.resize(b.sizeHint())
    b.build()
    _frames(qapp, b, bw.BACK_END + 2 * bw.SWING)
    b.stop_building(False)
    assert not b.building and b.prop == "plug"
    assert b.pose()["prop"] == "hammer"       # the blow still comes down
    _frames(qapp, b, bw.FAIL_SNAP + 0.1)
    shocked = b.pose()
    assert shocked["prop"] == "hammer_broken" and shocked["sad"] < 0.3   # not sad yet: "oh!"
    assert any(j.kind == "head" for j in b.junk)                       # the head flew off
    assert any(f.col == bw.SMOKE for f in b.puffs)
    _frames(qapp, b, bw.FAIL_DROP - bw.FAIL_SNAP + 0.6)
    assert b._sad > 0.6 and b._sigh_at > 0    # ears dropped with a sigh
    _frames(qapp, b, bw.FAIL_END)
    assert b._fail_t < 0 and b.pose()["prop"] == "plug" and b._sad > 0.6


def test_robo_bun_sparks_pulses_and_shorts_out(qapp):
    from soundboard.ui import bunnywidget as bw
    b = BunnyWidget(robot=True)
    b.resize(b.sizeHint())
    b.build()
    leds, sparked = set(), False
    for _ in range(round((bw.BACK_END + 3 * bw.SWING) / 0.035)):
        _run(qapp, b, 1)
        leds.add(round(b.pose()["led"], 1))
        sparked |= bool(b.sparks)
        b.grab()
    assert sparked and len(leds) > 3          # sparks per blow, LEDs pulsing
    assert b._parts >= 2                      # the screen's bar filling
    b.stop_building(False)
    _frames(qapp, b, bw.FAIL_SNAP + 0.1)
    assert len(b.sparks) > 6                  # shorted out
    _frames(qapp, b, bw.FAIL_END)
    assert b.pose()["led"] == 0


def test_robo_gadget_and_notes_read_on_dark_themes(qapp):
    from soundboard import theme
    from soundboard.bunny import GADGET
    from soundboard.ui.bunnywidget import NOTE_COLORS, _luma, note_colors

    def contrast(a, b):
        la, lb = _luma(a), _luma(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    for name in theme.THEMES:
        with theme.previewing(name):
            bg = QColor(theme.T["bg"])
            if _luma(bg) < 0.35:
                assert contrast(GADGET, bg) >= 3, name
            for col in NOTE_COLORS:
                assert contrast(note_colors(QColor(col))[0], bg) >= 3, (name, col)


def test_a_click_cheer_hops_high_with_a_happy_face_and_squashes(qapp):
    b = BunnyWidget("star", height=150, joy_lines=("yay",))
    b.cheer()
    t0 = b._joy_at
    top = min(b.pose(t0 + i / 60)["dy"] for i in range(30))
    assert top < -20                          # a real hop, not 12 px
    mid = b.pose(t0 + 0.2)
    assert mid["blink"] >= 1 and mid["mouth"] > 0.4   # eyes shut happy, a grin
    landing = b.pose(t0 + 0.4)
    assert landing["sy"] < 0.95 < landing["sx"]       # squashed on landing


def test_idle_fidgets_now_and_then(qapp):
    from soundboard.ui import bunnywidget as bw
    b = BunnyWidget("headphones")
    b.resize(b.sizeHint())
    b._next_blink = b._next_flick = time.monotonic() + 600
    b._next_fidget = 0
    _run(qapp, b, 1)
    assert b._fidget in bw.FIDGETS
    for kind in bw.FIDGETS:
        b.fidget(kind)
        poses = [b.pose(b._fidget_at + i * 0.1) for i in range(int(bw.FIDGETS[kind] * 10))]
        assert any(p["mouth"] > 0.5 or abs(p["angle"]) > 2 or p["dy"] < -1.5 for p in poses)
        b.grab()
    b._next_fidget = 0
    b.build()                                 # never in the middle of anything
    b._fidget = ""
    _run(qapp, b, 1)
    assert not b._fidget


def test_a_napping_bun_stays_up_for_the_end_of_his_act(qapp, monkeypatch):
    from soundboard.ui import bunnywidget as bw
    monkeypatch.setattr(bw, "local_hour", lambda: bw.NAP_HOURS[0])
    b = BunnyWidget(naps=True)
    b.resize(b.sizeHint())
    b.build()
    _frames(qapp, b, bw.BACK_END + 2 * bw.SWING)
    b.stop_building(False)
    _frames(qapp, b, bw.FAIL_SNAP + 0.1)
    assert not b.asleep and b.pose()["prop"] == "hammer_broken"   # sees it fail, awake
    _frames(qapp, b, bw.FAIL_END)
    assert b.asleep                                               # then back to his nap


def test_a_blink_shuts_fast_and_opens_slowly():
    from soundboard.ui import bunnywidget as bw
    assert bw.blink_amount(-0.1) == 0 and bw.blink_amount(1.0) == 0
    assert bw.blink_amount(bw.BLINK_SHUT) == 1
    assert bw.blink_amount(bw.BLINK_SHUT * 0.5) < 0.5               # speeding up as it shuts
    opening = bw.BLINK_SHUT + bw.BLINK_HOLD
    assert abs(bw.blink_amount(opening + bw.BLINK_OPEN * 0.5) - 0.5) < 1e-9   # halfway open
    assert bw.BLINK_OPEN > 2 * bw.BLINK_SHUT                        # opens more slowly


def test_landing_squashes_him_and_he_jiggles_back(qapp):
    b = BunnyWidget("star", height=150, joy_lines=("yay",))
    b.resize(b.sizeHint())
    b.cheer()
    t0 = b._joy_at
    squash = []
    for i in range(90):   # 1.5 s at 60 fps, on a pretend clock
        b._spring(t0 + i / 60, 1 / 60)
        squash.append(b._squash_s.x)
    assert min(squash) < -0.03          # squashed on a landing
    assert max(squash) > 0.01           # stretched as he takes off / falls
    for i in range(90, 240):            # the hops are over: he settles back into shape
        b._spring(t0 + i / 60, 1 / 60)
    assert abs(b._squash_s.x) < 0.01


def test_his_stretch_never_leaves_his_box(qapp):
    b = BunnyWidget("star", height=150, pad=4)
    b.resize(b.sizeHint())
    b._squash_s.x = 0.15                # as tall as the spring lets him get
    pose = b.springy({**b.pose(), "dy": -2.0})
    top = b._bun_rect().top() - 2.0 + 150 * (1 - pose["sy"])
    assert top >= 0


def test_ears_trail_behind_and_settle(qapp):
    b = BunnyWidget("plug")
    b.resize(b.sizeHint())
    now = time.monotonic()
    b._spring(now, 1 / 60)
    b._ears_s.x += 20                   # flung out (a hop)
    peaks = []
    for i in range(1, 120):
        b._spring(now + i / 60, 1 / 60)
        peaks.append(b._ears_s.x - b.pose(now + i / 60)["ears"])
    assert min(peaks) < -1              # swings past where they rest: a wobble
    assert abs(peaks[-1]) < 0.5         # ... and settles


def test_bun_mode_keeps_going_behind_a_game_at_a_slower_pace(qapp):
    from soundboard.ui import appstate
    from soundboard.ui import bunnywidget as bw
    b = BunnyWidget("plug", in_background=True)
    b._resume()
    assert b._timer.interval() == appstate.interval(bw.FAST_MS, bw.BACK_MS)
    b._timer.stop()
