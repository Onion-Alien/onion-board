"""Hear what they hear while the send device plays: the headphones get the send mix
itself (EngineBus._mon_sent), not a second one made the same way. Streams are stood in
by plain objects and the callbacks driven by hand, main then the headphones, block by
block, as two devices on the same clock would run them."""
import time

import numpy as np
import pytest

from soundboard.audio.engine import SR, Engine
from soundboard.mic import directmic

BLOCK = 480


def song(seconds=3.0, seed=1):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.12, (int(seconds * SR), 2))
    return np.clip(x, -1, 1).astype(np.float32)


def tone(seconds=1.0, hz=660.0):
    t = np.arange(int(seconds * SR)) / SR
    return np.stack([np.sin(2 * np.pi * hz * t)] * 2, 1).astype(np.float32) * 0.3


def engine(shared=True, rates=None):
    e = Engine()
    e.MON_SENT = shared
    e.main_stream, e.mon_stream = object(), object()
    e.mon_vol, e.sound_vol = 1.0, 1.0
    e.mic_check = e.monitor_sounds = True
    e.mic_enabled = False              # no mic: what's sent is the sounds alone
    e.sound_fx = {"echo": 0.4, "reverb": 0.3, "crunch": 0.2, "bass": 3.0}
    e.sound_pitch = 3.0
    if rates:
        e.rates.update(rates)
        e._reconfigure_out("main")
        e._reconfigure_out("mon")
    return e


def run(e, blocks, each=None):
    """main's and the headphones' blocks, one after the other; `each(i)` before each."""
    mains, mons = [], []
    om = np.zeros((BLOCK, 2), np.float32)
    n_mon = round(BLOCK * e.rates["mon"] / e.rates["main"])
    oh = np.zeros((n_mon, 2), np.float32)
    for i in range(blocks):
        if each is not None:
            each(i)
        e._cb_main(om, BLOCK, None, None)
        mains.append(om.copy())
        e._cb_mon(oh, n_mon, None, None)
        mons.append(oh.copy())
    return np.concatenate(mains), np.concatenate(mons)


def lag_of(a, b, most):
    """The delay (frames) of b behind a, by cross-correlation of the left channel."""
    a, b = a[:, 0].astype(np.float64), b[:, 0].astype(np.float64)
    best = max(range(most), key=lambda d: float(np.dot(a[:len(a) - d], b[d:])))
    return best


def db(x):
    return 20 * np.log10(max(float(np.sqrt(np.mean(x.astype(np.float64) ** 2))), 1e-12))


def test_the_headphones_hear_exactly_what_is_sent_a_cushion_later():
    e = engine()
    e.play("song", song(), 1.0)
    main, mon = run(e, 250)
    assert e._sent_want and e._mon_path[3]
    lag = lag_of(main, mon, 2400)
    assert lag <= int(0.03 * SR)            # the cushion: 15 ms plus a block at most
    a, b = main[SR // 2:len(main) - lag], mon[SR // 2 + lag:]
    assert db(b - a) < db(a) - 100          # the same samples (only float rounding)


def test_what_the_headphones_heard_before_is_the_same_mix():
    # the old way (each output mixing its own) and the new one play the same song
    # through the same effects, pitch, limiter: the same audio, the new one later
    old, new = engine(shared=False), engine()
    for e in (old, new):
        e.play("song", song(), 1.0)
    _, a = run(old, 250)
    _, b = run(new, 250)
    lag = lag_of(a, b, 2400)
    a, b = a[SR // 2:len(a) - lag], b[SR // 2 + lag:]
    assert db(b - a) < db(a) - 90           # float rounding only (measured: -96 dB)


def test_a_preview_and_a_headphones_only_sound_are_heard_on_top_but_not_sent():
    e = engine()
    run(e, 30)
    assert e._mon_path[3]
    e.play("p", tone(hz=1500), 1.0, preview=True)
    e.play("h", tone(hz=3000), 1.0, only="mon")
    main, mon = run(e, 60)

    def at(x, hz, rate=SR):
        f = np.fft.rfft(x[:, 0] * np.hanning(len(x)))
        k = int(round(hz * len(x) / rate))
        return float(np.abs(f[k - 2:k + 3]).max())

    for hz in (1500, 3000):
        assert at(mon[BLOCK * 10:], hz) > 50 * at(main[BLOCK * 10:], hz)


def test_the_radio_you_listen_to_but_do_not_send_stays_in_the_headphones():
    e = engine()
    e.radio_live, e.radio_monitor = False, True
    r = tone(2.0, hz=1000)

    def feed(i):
        e.ring_rmain.write(r[i * BLOCK:(i + 1) * BLOCK])
        e.ring_rmon.write(r[i * BLOCK:(i + 1) * BLOCK])

    main, mon = run(e, 120, feed)
    assert db(mon[SR // 2:]) > db(main[SR // 2:]) + 60
    e.radio_live = True                       # now sent: heard once, from what's sent
    main, mon = run(e, 120, lambda i: feed(i + 120))
    assert abs(db(mon[SR // 2:]) - db(main[SR // 2:])) < 0.5


def test_switching_it_off_mid_song_goes_on_from_where_the_song_is():
    e = engine()
    v = e.play("song", song(6.0), 1.0)
    run(e, 200)
    assert abs(v.pos["mon"] - v.pos["main"]) <= BLOCK
    assert abs(v.progress() - v.pos["main"] / len(v.data["main"])) < 0.01
    e.mic_check = False
    main, mon = run(e, 60)
    assert not e._sent_want and not e._mon_path[3]
    assert abs(v.pos["mon"] - v.pos["main"]) <= 2 * BLOCK
    assert db(mon[-BLOCK * 20:]) > db(main[-BLOCK * 20:]) - 6   # still playing


def test_a_seek_while_shared_moves_both():
    e = engine()
    v = e.play("song", song(6.0), 1.0)
    run(e, 50)
    v.seek(0.5)
    run(e, 3)
    half = len(v.data["main"]) // 2
    assert abs(v.pos["main"] - half) < 5 * BLOCK
    assert abs(v.pos["mon"] - v.pos["main"]) <= BLOCK
    assert "mon" not in v.seek_to


def test_a_sound_that_ends_on_main_ends_in_the_headphones():
    e = engine()
    v = e.play("short", tone(0.3), 1.0)
    run(e, 100)
    assert "main" in v.done and "mon" in v.done and v.finished


def test_a_stalled_send_device_leaves_the_headphones_mixing_their_own():
    e = engine()
    e.play("song", song(), 1.0)
    run(e, 60)
    assert e._mon_path[3]
    e._last_cb["main"] = time.monotonic() - 1.0   # main stopped calling back
    oh = np.zeros((BLOCK, 2), np.float32)
    y = []
    for _ in range(40):
        e._mon(oh, BLOCK)
        y.append(oh.copy())
    assert not e._mon_path[3] and not e._sent_want
    assert db(np.concatenate(y)[-BLOCK * 20:]) > -40   # still hearing the song


def test_with_no_send_device_the_headphones_mix_it_themselves():
    e = engine()
    e.main_stream = None
    e.play("song", song(), 1.0, only="mon")
    oh = np.zeros((BLOCK, 2), np.float32)
    for _ in range(30):
        e._cb_mon(oh, BLOCK, None, None)
    assert not e._mon_path[3] and db(oh) > -40


@pytest.mark.parametrize("main_rate,mon_rate", [(48000, 44100), (44100, 48000)])
def test_different_rates_play_the_same_loudness_at_the_headphones_rate(main_rate, mon_rate):
    e = engine(rates={"main": main_rate, "mon": mon_rate})
    e.play("song", song(), 1.0)
    main, mon = run(e, 250)
    assert len(mon) == 250 * round(BLOCK * mon_rate / main_rate)
    a, b = main[main_rate // 2:], mon[mon_rate // 2:]
    assert abs(db(a) - db(b)) < 0.3
    assert e.ring_sent.rate == mon_rate and e.ring_sent.underruns == 0


def test_the_mic_effect_adding_the_mic_itself_still_puts_your_voice_in_the_headphones():
    # add mode: Windows keeps the real mic, main's mix has none of it
    e = engine()
    e.mic_enabled = True
    e.main_direct, e.direct_mode = True, directmic.MODE_ADD
    voice = song(3.0, seed=5) * np.float32(0.3)   # (a steady tone is a howl: switched off)

    def mic(i):
        e._mic(voice[i * BLOCK:(i + 1) * BLOCK])

    main, mon = run(e, 150, mic)
    assert e._mon_path[3]
    assert db(mon[SR // 2:]) > db(main[SR // 2:]) + 60


def test_off_switch_brings_back_the_old_way():
    e = engine(shared=False)
    e.play("song", song(), 1.0)
    run(e, 30)
    assert not e._sent_want and not e._mon_path[3] and e.ring_sent.count == 0
