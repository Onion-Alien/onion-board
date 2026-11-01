"""Bun's acts beside window titles (ui/bun/bunacts.py): every act draws at every moment,
one-offs go back to the loop, the sound's speed and pitch move him, lite mode stills him,
and each window has him."""
import math
import time

from PySide6.QtGui import QImage, QPainter

from soundboard.ui.bun import bunacts
from soundboard.ui.bun.bunskitkit import Kit

ACTS = (bunacts.SNIP, bunacts.MIC, bunacts.RECORDING, bunacts.BIN_ACT, bunacts.BRING_BACK,
        bunacts.BYE, bunacts.PAT, bunacts.RUN, bunacts.OPEN, bunacts.GIFT)


def test_every_act_draws_through_its_whole_length(qapp):
    img = QImage(100, 125, QImage.Format.Format_ARGB32)
    for secs, act in ACTS:
        for i in range(25):
            kit = Kit()
            act(kit, secs * i / 24)
            p = QPainter(img)
            for fn in kit.behind + kit.front + kit.world:
                fn(p)
            p.end()


def test_a_one_off_plays_then_he_goes_back_to_the_loop(qapp):
    b = bunacts.ActBunny(bunacts.BIN_ACT)
    b._step_fidget(time.monotonic())
    assert b.skit_playing
    b.play(bunacts.BRING_BACK)
    assert b._once is not None
    b._step_fidget(time.monotonic() + bunacts.BRING_BACK[0] + 0.1)
    assert b._once is None and b.act is bunacts.BIN_ACT


def test_speed_hurries_him_and_pitch_stretches_him(qapp):
    b = bunacts.ActBunny(bunacts.SNIP)
    now = time.monotonic()
    b._was = now
    b._step_fidget(now + 0.05)
    slow = b._phase
    b.tune(2.0, 12)
    b._step_fidget(now + 0.1)
    assert math.isclose(b._phase - slow, 0.1, abs_tol=1e-6)   # 0.05 s at 2x
    kit = Kit()
    b._frame(kit, 0.0)
    assert kit.pose["sy"] > 0 and kit.pose["ears"] < 0   # stretched up, ears high
    b.tune(1.0, -12)
    kit = Kit()
    b._frame(kit, 0.0)
    assert kit.pose["sy"] < 0


def test_lite_mode_is_a_still_picture_of_his_act(qapp, monkeypatch):
    """Lite mode: no animation, but still the bin / parcel / present (not a bare Bun),
    no one-offs, and he settles so his timer stops."""
    from soundboard.ui.settings import lite
    monkeypatch.setattr(lite, "on", lambda: True)
    for act in (bunacts.GIFT, bunacts.BIN_ACT, bunacts.PAT):
        b = bunacts.ActBunny(act)
        b._step_fidget(time.monotonic())
        b.play(bunacts.BRING_BACK)
        b._step_fidget(time.monotonic())
        assert b._once is None
        frames = []
        for t in (0.0, 1.3, 3.1):   # the same picture whenever it's drawn
            kit = Kit()
            b._phase = t
            b._frame(kit, t)
            frames.append((len(kit.world), sorted(kit.pose.items())))
            assert kit.world   # his act's things are drawn
        assert frames[0] == frames[1] == frames[2]
        assert b._calm(time.monotonic() + 60)


def test_he_keeps_his_size_in_a_short_window(qapp):
    b = bunacts.ActBunny(bunacts.MIC, prop="mic")
    assert b.minimumSize() == b.maximumSize() == b.sizeHint()
    img = QImage(b.size(), QImage.Format.Format_ARGB32)
    b.render(img)


def test_recently_deleted_and_sound_packs_have_him(qapp, app_dir):
    from soundboard.ui.sounds.deleted import DeletedDialog
    from soundboard.ui.sounds.packsdialog import PacksDialog
    d = DeletedDialog("sound", "sounds", lambda _item: True)
    assert d.bun.act is bunacts.BIN_ACT
    d.delete_for_good()   # (nothing picked: no question, no bye)
    assert d.bun._once is None
    pk = PacksDialog(lambda p: None, fetch_list=False)
    assert pk.bun.act is bunacts.PAT



def test_in_the_bin_nothing_of_him_is_drawn_below_the_rim(qapp, monkeypatch):
    """His legs, feet and tail (a long one in some looks) stay inside the bin: he's
    drawn clipped at its rim. Out of the bin he's whole."""
    from soundboard.ui.bun.bunnywidget import BunnyWidget
    clips = []
    real = BunnyWidget._draw_bun

    def spy(self, p, pose, body):
        clips.append(p.clipBoundingRect() if p.hasClipping() else None)
        real(self, p, pose, body)
    monkeypatch.setattr(BunnyWidget, "_draw_bun", spy)
    for act in (bunacts.BIN_ACT, bunacts.PAT):
        b = bunacts.ActBunny(act, height=120)
        b._step_fidget(time.monotonic())
        img = QImage(b.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        b.render(img)
        r = b._bun_rect()
        rim = r.top() + bunacts.RIM * r.height() / 120
        if act is bunacts.BIN_ACT:
            assert clips[-1] is not None and clips[-1].bottom() <= rim + 0.5
        else:
            assert clips[-1] is None or clips[-1].bottom() >= r.bottom()
