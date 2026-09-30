"""The real voice-processing libraries (soundboard.realproc). They live in the bench
environment only (requirements-bench.txt); in the app's environment these skip."""
import numpy as np
import pytest

from soundboard import codecsim, realproc

SR = realproc.SR


def _db(y) -> float:
    y = np.asarray(y, np.float64)
    return float(20 * np.log10(np.sqrt((y ** 2).mean()) + 1e-12))


def _tone(hz: float, seconds: float, level: float = 0.1) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (level * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        realproc.process(np.zeros(480, np.float32), ("suppress",))


webrtc = pytest.mark.skipif(not realproc.available(realproc.WEBRTC),
                            reason="livekit not installed (bench environment only)")
rnn = pytest.mark.skipif(not realproc.available(("rnnoise",)),
                         reason="pyrnnoise not installed (bench environment only)")


@webrtc
def test_output_shape_and_length_match_input():
    x = codecsim.pink_noise(1.23)
    y = realproc.process(x, ("webrtc_ns",))
    assert y.shape == x.shape and y.dtype == np.float32


@webrtc
def test_noise_suppression_pulls_a_steady_tone_down():
    # steady music looks like noise to the suppressor (about -12 dB here, from the
    # first second on)
    x = _tone(440, 4)
    y = realproc.process(x, ("webrtc_ns",))[:, 0]
    assert _db(y[-SR:]) < _db(x[-SR:]) - 6


@webrtc
def test_high_pass_cuts_hum_and_keeps_the_voice_band():
    hum = realproc.process(_tone(40, 2), ("webrtc_hpf",))[SR:, 0]
    mid = realproc.process(_tone(1000, 2), ("webrtc_hpf",))[SR:, 0]
    assert _db(hum) < _db(_tone(40, 1)) - 6
    assert abs(_db(mid) - _db(_tone(1000, 1))) < 1.5


@webrtc
def test_agc_raises_a_quiet_voice():
    x = codecsim.speech_like(4, level=0.02)
    y = realproc.process(x, ("webrtc_agc",))[:, 0]
    assert _db(y[-SR:]) > _db(x[-SR:, 0]) + 3


@rnn
def test_rnnoise_removes_noise_and_reports_voice_probability():
    x = codecsim.pink_noise(2)[:, 0].astype(np.float64)
    y, probs = realproc.rnnoise(x, with_prob=True)
    assert len(y) == len(x)
    assert len(probs) == -(-len(x) // realproc.FRAME)
    assert _db(y[SR:]) < _db(x[SR:]) - 10          # it isn't a voice, so it goes
    assert float(np.max(probs)) <= 1.0


@webrtc
@rnn
def test_all_stages_together():
    y = realproc.process(codecsim.speech_like(2), realproc.STAGES)
    assert y.shape == (2 * SR, 2) and np.isfinite(y).all()
