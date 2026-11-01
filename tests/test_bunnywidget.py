"""Bun's animated widget: talking opens his mouth and throws notes, silence closes
it again, and the plain drawing still works with every pose."""

import random
import time

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from soundboard.ui.bun.bunbits import DANCE_FACES
from soundboard.ui.bun.bunny import PROPS, draw_bunny
from soundboard.ui.bun.bunnywidget import BunnyWidget


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
    # (his level takes ~1.2 s to fall below talking and the last note lives up to
    # 1.9 s more: 80 frames was ~7% too few, 100 (3.5 s) always does)
    _run(qapp, b, 100)
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
    from soundboard.style import mascotlines
    assert b.say in ("yay",) + mascotlines.bun()   # his own line or his theme's
    _run(qapp, b, 15)
    assert b.pose()["sad"] < 0.3             # happy while cheering

def test_idle_bob_runs_at_the_same_frame_rate_as_the_twitches(qapp):
    from soundboard.ui.bun import bunnywidget
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
    from soundboard.ui.bun.bunny import bunny_image
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
    from soundboard.ui.bun.bunny import bunny_image
    tops = []
    for sad in (0.0, 1.0):
        img = QImage(100, 140, QImage.Format_ARGB32_Premultiplied)   # (room above: an
        img.fill(0)                                                  # upright ear's tip
        p = QPainter(img)                                            # reaches past him)
        draw_bunny(p, QRectF(0, 20, 100, 120), sad=sad, outfit=())
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
    from soundboard.ui.bun import bunnywidget as bw
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
    from soundboard.ui.bun import bunnywidget as bw
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
    from soundboard.ui.bun import bunnywidget as bw
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
    from soundboard.ui.kit import theme
    from soundboard.ui.bun.bunny import GADGET
    from soundboard.ui.bun.bunnywidget import NOTE_COLORS, _luma, note_colors

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


def test_idle_fidgets_now_and_then(qapp, monkeypatch):
    from soundboard.ui.bun import bunnywidget as bw
    monkeypatch.setattr(bw.bunskits, "NEXT_PROB", 0.0)   # (a fidget, not his skit)
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
    from soundboard.ui.bun import bunnywidget as bw
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
    from soundboard.ui.bun import bunnywidget as bw
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
    from soundboard.ui.kit import appstate
    from soundboard.ui.bun import bunnywidget as bw
    b = BunnyWidget("plug", in_background=True)
    b._resume()
    assert b._timer.interval() == appstate.interval(bw.FAST_MS, bw.BACK_MS)
    b._timer.stop()


class _Clock:
    """Pretend time for the module (time.monotonic), moved on by hand."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def localtime(self):
        return time.localtime()


class _Song:
    """What groove.Groove gives Bun: a steady beat at `bpm`, in `style`."""

    def __init__(self, clock, style, bpm=120.0, voice=0.5):
        self.clock, self.style, self.bpm, self.t0 = clock, style, bpm, clock.now
        self.energy, self.kick, self.voice, self.onset = 0.8, 0.0, voice, 0.0

    def beat(self, now=None):
        return ((self.clock.now if now is None else now) - self.t0) * self.bpm / 60

    def last_hit(self, band, now):   # a hit on every beat
        return ((now - self.t0) % (60 / self.bpm), 0.9)

    def gap(self, band):
        return 60 / self.bpm


def _dance(monkeypatch, style, height=110, voice=0.5):
    from soundboard.ui.bun import bunnywidget
    clock = _Clock()
    monkeypatch.setattr(bunnywidget, "time", clock)
    b = BunnyWidget("headphones", height=height)
    b.set_groove(_Song(clock, style, voice=voice))
    return b, clock


def _beats(b, clock, secs, each=None):
    for _ in range(round(secs * 60)):
        clock.now += 1 / 60
        b._step()
        if each:
            each()


def test_notes_grow_and_shrink_with_him(qapp):
    small, big = BunnyWidget("headphones", height=40), BunnyWidget("headphones", height=400)
    for b in (small, big):
        b.resize(b.sizeHint())
        b.burst(3)
        assert not b.grab().isNull()
    ks, kb = small.notes[0].k, big.notes[0].k
    assert kb / ks > 5   # (they used to be the same size at any size of Bun)
    speed = lambda b: sum(abs(n.vy) for n in b.notes) / len(b.notes)  # noqa: E731
    assert speed(big) > speed(small) * 4   # ...and flew the same few pixels


def test_he_dances_on_the_beat_and_notes_come_out_on_it(qapp, monkeypatch):
    b, clock = _dance(monkeypatch, "electronic")
    _beats(b, clock, 1.0)   # gets into it
    times = []
    count = [len(b.notes)]

    def note_times():
        if len(b.notes) > count[0]:
            times.append(b.groove.beat())
        count[0] = len(b.notes)
    _beats(b, clock, 3.0, note_times)
    assert len(times) >= 5   # 6 beats in 3 s at 120: notes on (nearly) every one
    assert all(min(x % 1, 1 - x % 1) < 0.05 for x in times)   # on the beat, not a stream
    # in the air between beats, down on them
    clock.now = b.groove.t0 + 10 * 0.5 + 0.25          # half way through a beat
    mid = b.pose()["dy"]
    clock.now = b.groove.t0 + 11 * 0.5                  # on one
    on = b.pose()["dy"]
    assert mid < on - 5


def test_a_bigger_bun_dances_bigger(qapp, monkeypatch):
    heights = {}
    for h in (60, 360):
        b, clock = _dance(monkeypatch, "electronic", height=h)
        _beats(b, clock, 2.0)
        clock.now = b.groove.t0 + 6 * 0.5 + 0.25
        heights[h] = -b.pose()["dy"]
    assert heights[360] > heights[60] * 4


def test_each_style_dances_its_own_way(qapp, monkeypatch):
    rock, clock = _dance(monkeypatch, "rock")
    _beats(rock, clock, 2.0)
    clock.now = rock.groove.t0 + 6 * 0.5 + 0.04        # just after the beat: head down
    assert rock.pose()["dip"] > 5 and rock.pose()["intense"] > 0.2
    talk, clock = _dance(monkeypatch, "speech", voice=0.9)
    _beats(talk, clock, 3.0)
    assert talk.pose()["mouth"] > 0.5 and not talk.notes   # talking along, no notes
    talk.groove.voice = 0.0
    _beats(talk, clock, 0.5)
    assert talk.pose()["mouth"] < 0.1
    cool, clock = _dance(monkeypatch, "hiphop")
    _beats(cool, clock, 2.0)
    assert cool.pose()["smug"]
    calm, clock = _dance(monkeypatch, "chill")
    _beats(calm, clock, 2.0)
    clock.now = calm.groove.t0 + 2 * 0.5   # (eyes shut, swaying)
    assert calm.pose()["blink"] > 0.9
    for b in (rock, talk, cool, calm):   # every style draws
        b.resize(b.sizeHint())
        assert not b.grab().isNull()
    calm.set_groove(None)                # the song ends: he stops dancing
    _beats(calm, clock, 2.0)
    assert calm._dance < 0.01 and calm.pose()["nod"] == 0.0


def test_his_mouth_never_follows_music_and_only_talks_to_speech(qapp, monkeypatch):
    # to music his mouth holds still: shut in his little smile, or a dance face's grin
    for face in range(len(DANCE_FACES)):
        for style in ("electronic", "rock", "hiphop", "chill", "pop"):
            b, clock = _dance(monkeypatch, style, voice=1.0)   # (a loud singer, too)
            b._face, b._face_until = face, 1e12
            seen: list[float] = []
            _beats(b, clock, 3.0, lambda s=seen, b=b: s.append(b.pose()["mouth"]))
            grin = DANCE_FACES[face][1] if style in ("electronic", "pop") else 0.0
            assert max(seen[len(seen) // 2:]) <= grin + 0.05, (face, style)
            assert max(seen[len(seen) // 2:]) - min(seen[len(seen) // 2:]) < 0.05, (face, style)
    talk, clock = _dance(monkeypatch, "speech", voice=1.0)
    _beats(talk, clock, 2.0)
    assert talk.pose()["mouth"] > 0.5


def test_his_dance_face_holds_a_random_while_and_can_come_up_again(qapp, monkeypatch):
    b, clock = _dance(monkeypatch, "electronic")
    faces, holds = [], []
    for _i in range(200):
        clock.now = max(clock.now, b._face_until) + 0.01   # (just past the last change)
        b._step()
        faces.append(b._face)
        holds.append(b._face_until - clock.now)
    assert 5 <= min(holds) and max(holds) <= 30
    assert 12 < sum(holds) / len(holds) < 18                     # about 15 s on average
    assert set(faces) == set(range(len(DANCE_FACES)))
    assert any(x == y for x, y in zip(faces, faces[1:]))         # the same one twice


def test_every_themes_skit_plays_through_and_ends_clean(qapp, monkeypatch):
    from soundboard.ui.kit import theme
    from soundboard.ui.bun import bunnywidget, bunskits
    clock = _Clock()
    monkeypatch.setattr(bunnywidget, "time", clock)
    was = theme.current_name
    try:
        for name in [*bunskits.SKITS, "Textured"]:   # (Textured: no outfit, juggles)
            theme.apply(qapp, name)
            b = BunnyWidget(height=120)
            b.resize(b.sizeHint())
            b._next_fidget = 1e12
            b.skit()
            length = bunskits.for_theme(name)[0]
            seen_hidden = False
            for i in range(int(length * 12) + 3):   # (every 1/12 s, and one past the end)
                clock.now += 1 / 12
                b._step()
                pose = b.pose()
                seen_hidden |= pose["outfit"] is not None
                if i % 4 == 0:
                    assert not b.grab().isNull()
            assert not b.skit_playing, name           # over: nothing left behind
            pose = b.pose()
            assert pose["outfit"] is None and pose["alpha"] == 1.0, name
            if name == "Blood Moon":   # he took the moon out of the sky...
                assert seen_hidden
    finally:
        theme.apply(qapp, was)


def test_blood_moon_bun_bites_the_moon_and_its_cheese(qapp, monkeypatch):
    from soundboard.ui.kit import theme
    from soundboard.ui.bun import bunnywidget, bunskits
    clock = _Clock()
    monkeypatch.setattr(bunnywidget, "time", clock)
    was = theme.current_name
    try:
        theme.apply(qapp, "Blood Moon")
        kit = bunskits.Kit()
        bunskits.blood_moon(kit, 1.0)
        assert "moon" not in kit.hide                    # still in the sky
        kit = bunskits.Kit()
        bunskits.blood_moon(kit, 3.3)
        assert "moon" in kit.hide and kit.front           # in his paw, bitten
        assert kit.pose["ears"] < -5                      # surprised: ears up
    finally:
        theme.apply(qapp, was)


def test_a_skit_only_starts_when_hes_idle_and_stops_for_anything_else(qapp, monkeypatch):
    from soundboard.ui.bun import bunnywidget
    clock = _Clock()
    monkeypatch.setattr(bunnywidget, "time", clock)
    monkeypatch.setattr(bunnywidget.bunskits, "NEXT_PROB", 1.0)
    b = BunnyWidget(height=110)
    b._next_fidget = clock.now
    b.set_level(0.5)        # talking: no skit
    b._step()
    assert not b.skit_playing
    b._level = 0.0
    b._next_fidget = clock.now
    _beats(b, clock, 0.1)
    assert b.skit_playing   # idle: off he goes
    b.set_groove(_Song(clock, "pop"))   # music: the skit stops, he dances
    _beats(b, clock, 1.0)
    assert not b.skit_playing

def test_hiphop_nods_on_the_808_hits_themselves(qapp, monkeypatch):
    b, clock = _dance(monkeypatch, "hiphop")
    _beats(b, clock, 2.0)
    song = b.groove
    hits = [song.t0 + 3.0, song.t0 + 3.7]   # off any beat grid: syncopated 808s
    song.last_hit = lambda band, now: next(((now - h, 1.0) for h in reversed(hits) if h <= now),
                                           (float("inf"), 0.0))
    clock.now = hits[0] - 0.02
    before = b.pose()["dip"]
    clock.now = hits[0] + 0.05
    assert b.pose()["dip"] > before + 3   # down with the 808, not the grid
    clock.now = hits[1] - 0.05
    assert b.pose()["dip"] < 2            # back up before the next one



def test_hiphop_nods_on_a_sure_beat_too_not_only_on_the_808(qapp, monkeypatch):
    # a few 808s a bar left him all but still: with the beat sure, he nods on it too
    b, clock = _dance(monkeypatch, "hiphop")
    song = b.groove
    song.bpm = 92.0
    song.last_hit = lambda band, now: (float("inf"), 0.0)   # no 808 at all
    _beats(b, clock, 2.0)
    beat = song.t0 + 60 / song.bpm * 8
    clock.now = beat - 0.2
    still = b.pose()["dip"]
    clock.now = beat
    assert b.pose()["dip"] < still + 1   # unsure of the beat: no nod of its own
    song.confidence = 0.9
    clock.now = beat
    assert b.pose()["dip"] > still + 5   # sure: down on the beat

def test_a_sad_bun_on_an_empty_page_cheers_up_and_dances_to_what_plays(qapp, monkeypatch):
    from soundboard.ui.bun import bunnywidget
    clock = _Clock()
    monkeypatch.setattr(bunnywidget, "time", clock)
    b = BunnyWidget(height=110, sad=0.9, lines=("add a sound?",), dances=True)
    assert b in BunnyWidget.dancers and BunnyWidget("star") not in BunnyWidget.dancers
    _beats(b, clock, 2.0)
    assert b._sad > 0.6
    b.set_groove(_Song(clock, "electronic"))
    _beats(b, clock, 3.0)
    assert b._sad < 0.1 and b._dance > 0.9
    dys = []
    _beats(b, clock, 1.0, lambda: dys.append(b.pose()["dy"]))
    assert max(dys) - min(dys) > 5   # hopping, not sulking


def test_hoot_bobs_to_the_hits(qapp, monkeypatch):
    from soundboard.style import owl
    clock = _Clock()
    monkeypatch.setattr(owl, "time", clock)
    o = owl.OwlWidget(96, dances=True)
    assert o in owl.OwlWidget.dancers
    song = _Song(clock, "hiphop")
    hits = [clock.now + 2.0, clock.now + 2.6]
    song.last_hit = lambda band, now: next(((now - h, 1.0) for h in reversed(hits) if h <= now),
                                           (float("inf"), 0.0))
    song.next_hit = lambda band, now: next(((h - now, 1.0) for h in hits if h > now),
                                           (float("inf"), 0.0))
    o.set_groove(song)
    for _i in range(110):   # (dancing by the first hit)
        clock.now += 1 / 60
        o.step(1 / 60, mouse=None)
    assert o._dance > 0.9 and o.act is None
    clock.now = hits[0] - 0.1
    before = o.pose()["dy"]
    clock.now = hits[0]
    assert o.pose()["dy"] > before + 3   # head down right on the hit
    o.set_groove(None)
    for _i in range(180):
        o.step(1 / 60, mouse=None)
    assert o._dance < 0.01
    o.resize(o.sizeHint())
    assert not o.grab().isNull()


def test_his_paws_clasp_when_he_hopes_and_fold_when_hes_cross(qapp):
    def chest(**kw):   # his chest, just under his chin, where the paws come up to
        img = QImage(400, 480, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        draw_bunny(p, QRectF(0, 0, 400, 480), outfit=(), **kw)
        p.end()
        return img.copy(120, 368, 160, 56)
    calm = chest()
    assert chest(sad=1.0) != calm
    assert chest(angry=1.0) != calm
    assert chest(angry=1.0, prop="bat") != chest(angry=1.0)   # the bat takes a paw


def test_his_head_tilts_on_its_own_but_not_while_dancing(qapp):
    b = BunnyWidget()
    tilts = {round(b.pose(b._t0 + t)["tilt"], 2) for t in (0.5, 2.0, 4.0)}
    assert len(tilts) > 1 and all(abs(t) < 8 for t in tilts)


def test_pictures_of_bun_leave_room_for_an_upright_ear_and_a_wide_collar(qapp):
    """bunny_image's canvas cut the tip off an upright ear (Light) and the sides off
    Vampire's collar: they're inside the picture now, with clear edges."""
    from soundboard.ui.kit import theme
    from soundboard.ui.bun.bunny import bunny_image

    for name, edge in (("Light", "top"), ("Vampire", "sides")):
        with theme.previewing(name):
            img = bunny_image(120)
        w, h = img.width(), img.height()
        if edge == "top":
            line = [img.pixelColor(x, 0).alpha() for x in range(w)]
        else:
            line = [img.pixelColor(x, y).alpha() for y in range(h) for x in (0, w - 1)]
        assert max(line) == 0, name


def test_bits_of_bun_drawn_outside_draw_bunny_wear_his_theme_fur(qapp):
    """A skit's paw was always plain white fur, even on Mocha's brown Bun."""
    from soundboard.ui.kit import theme
    from soundboard.style import bunnyfit
    from soundboard.ui.bun import bunskits

    with theme.previewing("Mocha"):
        img = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bunskits.paw(p, 20, 20)
        p.end()
        assert img.pixelColor(20, 20).rgb() == QColor(bunnyfit.look()["fur"]).rgb()


def test_a_small_bun_widget_has_room_above_him_for_an_upright_ear(qapp):
    """The setup guide's 74 px Bun had 5 px above him: an upright ear's tip was cut off
    at the top of every bob."""
    from soundboard.ui.bun.bunny import ROOM_TOP, H
    from soundboard.ui.bun.bunnywidget import BOB_UP

    b = BunnyWidget("star", height=74, pad=5)
    b.resize(b.sizeHint())
    assert b._bun_rect().top() >= 74 * ROOM_TOP / H + BOB_UP
    assert b.height() - b._bun_rect().bottom() >= 5   # (his shadow's room kept)


def _still_bun(qapp, monkeypatch, **kw):
    """A shown Bun with rest_after_s, in front, awake, on a pretend clock (b.clock)."""
    from soundboard.ui.bun import bunnywidget as bw
    clock = _Clock()
    monkeypatch.setattr(bw, "time", clock)
    monkeypatch.setattr(bw, "local_hour", lambda: 12)
    monkeypatch.setattr(bw.appstate, "active", lambda: True)
    b = BunnyWidget(height=130, pad=18, sad=0.6, lines=("play?",), joy_lines=("yay",),
                    pong=True, naps=True, dances=True, rest_after_s=30.0, **kw)
    b.clock = clock
    b.resize(b.sizeHint())
    b.show()
    qapp.processEvents()
    return b


def _tick(b, n=1):
    for _ in range(n):
        b.clock.now += 0.035
        b._last = b.clock.now - 0.035
        b._step()


def _settle(qapp, b, secs=10.0):
    """Frames until he rests (or `secs` of pretend time)."""
    for _ in range(round(secs / 0.035)):
        if b.resting:
            return
        _tick(b)


def test_a_resting_bun_moves_for_a_while_then_holds_still(qapp, monkeypatch):
    b = _still_bun(qapp, monkeypatch)
    assert b._timer.isActive() and not b.resting   # shown: he moves
    _tick(b, round(29 / 0.035))
    assert not b.resting                           # ... the whole first 30 s
    _settle(qapp, b)                               # 30 s on
    assert b.resting and not b._timer.isActive()   # timer off
    painted = []
    monkeypatch.setattr(b, "update", lambda *a: painted.append(1))
    for _ in range(20):
        qapp.processEvents()
    assert not painted                             # no repaints of his own
    frozen = b.grab().toImage()
    b.clock.now += 0.4
    assert b.grab().toImage() == frozen            # a parent's repaint shows the kept pose
    b.close()


def test_a_sound_or_a_click_wakes_a_resting_bun(qapp, monkeypatch):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    b = _still_bun(qapp, monkeypatch)
    b.clock.now = b._rest_at + 1
    _settle(qapp, b)
    assert b.resting
    b.set_groove(None)                             # silence: still resting
    assert b.resting and not b._timer.isActive()
    b.set_groove(object())                         # a sound or the radio
    assert not b.resting and b._timer.isActive()
    assert b._rest_at > b.clock.now + 25      # ... and another 30 s after it
    assert b._next_beg > b.clock.now + 2      # (not "music, please?" as it starts)
    b.set_groove(None)
    b.clock.now = b._rest_at + 1
    _settle(qapp, b)
    assert b.resting
    QTest.mouseClick(b, Qt.MouseButton.LeftButton, pos=QPoint(b.width() // 2, b.height() // 2))
    assert not b.resting and b._timer.isActive()   # a click: he hops (and moves again)
    assert b._joy_at == b.clock.now
    b.close()


def test_showing_a_resting_bun_again_gives_him_another_stretch(qapp, monkeypatch):
    b = _still_bun(qapp, monkeypatch)
    b.clock.now = b._rest_at + 1
    _settle(qapp, b)
    assert b.resting
    b.hide()
    b.show()
    qapp.processEvents()
    assert not b.resting and b._timer.isActive()
    assert b._rest_at > b.clock.now + 25
    b.close()


def test_a_resting_bun_waits_to_finish_what_hes_doing(qapp, monkeypatch):
    b = _still_bun(qapp, monkeypatch)
    b.clock.now = b._rest_at + 1
    b._beg_at = b.clock.now                        # mid-beg: a line up, hopping,
    b._say(b.lines, 2.0)
    for _i in range(3):
        b._spawn()                                 # ... notes in the air
    _tick(b)
    assert not b.resting                           # never frozen mid-move
    _settle(qapp, b, 15)
    assert b.resting and not b.notes and not b.say
    assert b.clock.now - b._beg_at >= 2.8
    b.close()


def test_buns_without_rest_after_s_never_rest(qapp, monkeypatch):
    b = _still_bun(qapp, monkeypatch)
    b.rest_after_s = None
    _tick(b, round(60 / 0.035))
    assert not b.resting and b._timer.isActive()
    b.close()

def test_the_apps_tabs_empty_bun_rests_after_30_s():
    import soundboard.ui.apps.appspanel as ap
    import inspect
    assert ap.BUN_REST_S == 30.0
    assert "rest_after_s=BUN_REST_S" in inspect.getsource(ap)


def test_a_skit_paw_gets_his_arm_on_its_side_instead_of_a_third_paw(qapp):
    """A skit's paw held his prop with no arm while both arms still rested at his
    sides: held_paws hands draw_bunny where it is, so that arm reaches out to it."""
    from soundboard.ui.bun import bunskits

    kit = bunskits.Kit()
    kit.front.append(lambda p: bunskits.paw(p, 78, 96))
    assert bunskits.held_paws(kit) == (None, (78.0, 96.0))
    kit.front.append(lambda p: bunskits.paw(p, 24, 96))
    assert bunskits.held_paws(kit) == ((24.0, 96.0), (78.0, 96.0))
    assert bunskits.held_paws(bunskits.Kit()) is None


def _still_kind(qapp, monkeypatch, prop=None, sad=0.0, sulk=False):
    """A shown resting Bun of a given kind (the Store's headphones one, a sulking one)."""
    from soundboard.ui.bun import bunnywidget as bw
    clock = _Clock()
    monkeypatch.setattr(bw, "time", clock)
    monkeypatch.setattr(bw, "local_hour", lambda: 12)
    monkeypatch.setattr(bw.appstate, "active", lambda: True)
    b = BunnyWidget(prop, height=72, pad=12, sad=sad, rest_after_s=30.0)
    b.sulk = sulk
    b.clock = clock
    b.resize(b.sizeHint())
    b.show()
    qapp.processEvents()
    return b


def test_the_headphones_bun_stops_his_notes_and_rests(qapp, monkeypatch):
    """The Community tab's Bun: notes float out of his headphones nonstop, so he never
    held still (60 repaints a second of the whole banner, for as long as it's open)."""
    b = _still_kind(qapp, monkeypatch, "headphones")
    seen = 0
    for _ in range(round(10 / 0.035)):
        _tick(b)
        seen = max(seen, len(b.notes))
    # (a note comes every ~1.4 s and lives a random 1.2-1.9 s: any one frame can
    # fall in a gap between two, so look across the whole stretch)
    assert seen and not b.resting                   # his idle notes, while he moves
    b.clock.now = b._rest_at + 0.1
    _settle(qapp, b, 15)
    assert b.resting and not b._timer.isActive() and not b.notes
    b.close()


def test_a_sulking_bun_rests_with_his_foot_down(qapp, monkeypatch):
    """The red card's Bun kicks at the ground over and over: after his 30 s he stops
    between two kicks, the dust settled."""
    from soundboard.ui.bun import bunnywidget as bw
    b = _still_kind(qapp, monkeypatch, sad=1.0, sulk=True)
    b.clock.now = b._rest_at + 0.1
    _settle(qapp, b, 15)
    assert b.resting and not b._timer.isActive() and not b.puffs
    kick, u = bw.sulk_kick(b._still_at - b._t0)
    assert kick == 0.0 and u >= 0.75
    b.stir()                                         # a new problem: he sulks again
    assert not b.resting and b._timer.isActive()
    b.close()


def test_the_store_and_oops_buns_rest_after_30_s(qapp):
    from soundboard.ui.kit import oops
    from soundboard.ui.store import storelook
    bun = storelook.make_bun(72)
    assert bun.rest_after_s == storelook.BUN_REST_S == 30.0
    card = oops.OopsPanel()
    assert card.bun.rest_after_s == oops.BUN_REST_S == 30.0
    card.bun.resting = True
    card.show_problem("Store's down", "try later")
    assert not card.bun.resting                      # a new problem stirs him
    bun.deleteLater()
    card.deleteLater()


def test_only_bun_himself_takes_clicks_and_shows_the_hand(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    b = BunnyWidget(height=130, pad=18, sad=0.6, lines=("play?",), joy_lines=("yay",))
    b.resize(b.sizeHint())
    b.show()
    body = b._bun_rect()
    beside = QPoint(round(body.left()) - 30, round(body.center().y()))   # the bubble's room
    assert b.width() > 2 * body.width() and not b.on_bun(beside)
    QTest.mouseMove(b, beside)
    assert b.cursor().shape() != Qt.CursorShape.PointingHandCursor
    QTest.mouseClick(b, Qt.MouseButton.LeftButton, pos=beside)
    assert b._joy_at < 0                                 # nothing happened
    on = body.center().toPoint()
    QTest.mouseMove(b, on)
    assert b.cursor().shape() == Qt.CursorShape.PointingHandCursor
    QTest.mouseClick(b, Qt.MouseButton.LeftButton, pos=on)
    assert b._joy_at > 0                                 # he hops for joy
    b.close()


def test_a_click_hop_and_a_dance_hop_stay_inside_his_box(qapp):
    from soundboard.ui.bun.bunny import ROOM_TOP, H
    for kw in ({"joy_lines": ("yay",)}, {"dances": True}):
        b = BunnyWidget(height=130, pad=16, **kw)
        b.resize(b.sizeHint())
        if "joy_lines" in kw:
            b.cheer()
            t0 = b._joy_at
            hop = min(b.pose(t0 + i / 120)["dy"] for i in range(60))
        else:
            hop = -0.07 * 130
        top = b._bun_rect().top() + hop - 2.2 - b.bun_h * ROOM_TOP / H   # (bob, ears, hat)
        assert top >= 0, kw


def test_hiphop_nod_stays_smooth_with_a_bass_note_between_beats(qapp, monkeypatch):
    # a snap down on every beat and again on every bass note looked like headbanging
    b, clock = _dance(monkeypatch, "hiphop")
    song = b.groove
    song.bpm, song.confidence = 105.0, 0.9
    song.last_hit = lambda band, now: ((now - song.t0) % (30 / song.bpm), 0.9)   # 2 a beat
    _beats(b, clock, 2.0)
    dips = []
    _beats(b, clock, 4.0, lambda: dips.append(b.pose()["dip"]))
    assert max(dips) < 8                                       # a nod, not a bang
    assert max(abs(x - y) for x, y in zip(dips, dips[1:])) < 1.6   # no snaps


def test_his_bubble_wraps_a_long_line_onto_even_lines_beside_him(qapp):
    from PySide6.QtGui import QFont, QFontMetrics

    from soundboard.ui.bun.bunbubble import wrap
    f = QFont()
    f.setPixelSize(15)
    fm = QFontMetrics(f)
    assert wrap(fm, "hehe!", 500) == ["hehe!"]
    long = "Ich habe gerade keine Ahnung, was das heißt"
    lines = wrap(fm, long, fm.horizontalAdvance("Ich habe gerade"))
    assert len(lines) == 3 and " ".join(lines) == long
    assert wrap(fm, "Wortwortwort", 5) == ["Wortwortwort"]   # (one word: never split)


def test_a_soundbite_is_said_along_with_not_danced_to(qapp, monkeypatch):
    b, clock = _dance(monkeypatch, "pop", voice=0.9)
    b.groove.music = False                  # (groove.Groove: a soundbite or talking)
    _beats(b, clock, 0.3)                   # a one-second "bruh" is said at once
    assert b.pose()["mouth"] > 0.5
    _beats(b, clock, 2.0)
    assert not b.notes and abs(b.pose()["dy"]) < 3   # no notes, no bouncing
    b.set_groove(None)
    _beats(b, clock, 0.3)
    assert b.pose()["mouth"] < 0.1          # it's over: mouth shut


def test_notes_come_in_every_shape(qapp):
    b = BunnyWidget("headphones")
    b.resize(b.sizeHint())
    b._rng = random.Random(4)
    b.burst(80)
    assert {n.shape for n in b.notes if not n.kind} == {0, 1, 2, 3}   # ♪ ♩ ♫ ♬
    assert not b.grab().isNull()


def test_every_theme_throws_its_own_things(qapp):
    from soundboard.ui.bun import bunsymbols
    from soundboard.ui.bun.bunbits import _Note, paint_note
    from soundboard.ui.kit import theme
    assert set(theme.THEMES) <= set(bunsymbols.MIXES)
    sets = [frozenset(k for k, _c in mix if k != "note") for mix in bunsymbols.MIXES.values()]
    assert len(set(sets)) == len(sets) and all(sets)   # no two themes throw the same
    was = theme.current_name
    try:
        for name, mix in bunsymbols.MIXES.items():
            if name not in theme.THEMES:
                continue
            theme.apply(qapp, name)
            for kind, col in mix:
                if kind == "note":
                    continue
                img = QImage(40, 40, QImage.Format.Format_ARGB32)
                img.fill(0)
                p = QPainter(img)
                n = _Note(20, 20, random.Random(1))
                n.age, n.life, n.kind, n.col = 0.5, 10.0, kind, QColor(col)
                paint_note(p, n)
                p.end()
                inked = sum(img.pixelColor(x, y).alpha() > 128
                            for x in range(40) for y in range(40))
                assert inked > 25, (name, kind)   # it drew something you can see
    finally:
        theme.apply(qapp, was)
