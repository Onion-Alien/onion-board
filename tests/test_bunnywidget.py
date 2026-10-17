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
    from soundboard.ui import bunnywidget
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


def test_his_mouth_stays_shut_to_music_and_only_talks_to_speech(qapp, monkeypatch):
    for style in ("electronic", "rock", "hiphop", "chill", "pop"):
        b, clock = _dance(monkeypatch, style, voice=1.0)   # (a loud singer, too)
        widest = [0.0]
        _beats(b, clock, 3.0, lambda w=widest, b=b: w.__setitem__(0, max(w[0], b.pose()["mouth"])))
        assert widest[0] < 0.05, style
    talk, clock = _dance(monkeypatch, "speech", voice=1.0)
    _beats(talk, clock, 2.0)
    assert talk.pose()["mouth"] > 0.5


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
