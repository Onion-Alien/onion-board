""""Others hear" off cuts the sounds, the radio and programs; your plain voice still goes
out while your mic is sent and no voice changer is on (Engine.mic_only)."""
import numpy as np

from soundboard.audio.engine import SR, Engine
from soundboard.voicefx import VoiceChain

BLOCK = 480


def out_engine() -> Engine:
    e = Engine()
    e.dest, e.limiter_on, e.send_mono = None, False, False   # no shaping, exact samples
    e.duck_db = 0.0
    e.main_stream = object()
    e.names["main"] = "fake main"
    e.play("song", np.full((SR, 2), 0.25, np.float32), 1.0, loop=True)
    return e


def sent(e: Engine, mic: float) -> float:
    """What the last of a few blocks sends out, with the mic at `mic`."""
    out = np.zeros((BLOCK, 2), np.float32)
    for _ in range(6):   # past every glide
        e.ring_main.write(np.full((BLOCK, 2), mic, np.float32))
        e._main(out, BLOCK)
    return float(out[-1, 0])


def test_off_still_sends_your_plain_voice_but_not_your_sounds():
    e = out_engine()
    e.mic_vol = 1.0
    live = sent(e, 0.5)
    assert live > 0.5   # the sound and the mic
    e.sending = False
    assert e.mic_only()
    assert abs(sent(e, 0.5) - 0.5) < 0.02   # only your voice
    assert abs(sent(e, 0.0)) < 1e-4         # and no sound under it
    e.sending = True
    assert not e.mic_only() and sent(e, 0.5) > 0.5


def test_off_is_silence_with_the_mic_not_sent_muted_or_changed():
    e = out_engine()
    e.sending = False
    e.mic_enabled = False                    # Send my mic off
    assert not e.mic_only() and not sent(e, 0.5)
    e.mic_enabled, e.mic_muted = True, True  # the mic hotkey
    assert not e.mic_only() and not sent(e, 0.5)
    e.mic_muted = False
    chain = VoiceChain()
    chain.replace = True                     # another voice: never let the real one out
    e.voice_chain = chain
    assert not e.mic_only() and not sent(e, 0.5)
    chain.replace = False                    # a chain that doesn't change you (a speech tap)
    assert e.mic_only()



def heard(e: Engine, mic: float) -> float:
    """The loudest sample of the last of a few blocks in your headphones, mic at `mic`."""
    out = np.zeros((BLOCK, 2), np.float32)
    for _ in range(12):   # past every glide and the path fade
        e.ring_mon.write(np.full((BLOCK, 2), mic, np.float32))
        e._mon(out, BLOCK)
    return float(np.abs(out).max())


def test_off_with_hear_what_they_hear_still_plays_your_sounds_for_you():
    """Off only cuts what others hear: with "Hear what they hear" on and your plain mic
    going out, the headphones went silent too."""
    e = Engine()
    e.dest, e.limiter_on, e.send_mono = None, False, False
    e.main_stream, e.mon_stream = object(), object()
    e.names["main"], e.names["mon"] = "fake main", "fake headphones"
    t = np.arange(SR) / SR
    e.play("song", np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1).astype(np.float32) * 0.5,
           1.0, loop=True)
    e.mic_vol = e.mon_vol = 1.0
    e.mic_check = True
    e.ring_mon.prefill = 0
    live = heard(e, 0.0)
    assert live > 0.1
    e.sending = False
    assert e.mic_only()
    assert heard(e, 0.0) > 0.1   # the sound still plays for you
