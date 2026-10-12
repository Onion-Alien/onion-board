"""Effects rendered a piece at a time (soundfx.render_into, library.render_cached): the
same result as one pass over the whole sound, and memory that doesn't grow with it."""
import tracemalloc

import numpy as np
import pytest
import soxr

from soundboard import dsp, eq, library, soundfx, voicefx
from soundboard.engine import SR

EXTRA = {
    "trim+pitch+eq": {"start": 0.1, "end": 1.3, "pitch": 3, "eq": [3, 0, -2, 0, 4, 0, 1]},
    "tape+pitch": {"speed": 0.6, "tape": True, "pitch": -5},
    "reverse+reverb+gain": {"reverse": True, "gain_db": 9,
                            "effects": {"reverb": {"on": True, "size": 0.9, "mix": 0.5}}},
    "echo+distortion": {"effects": {"echo": {"on": True, "delay": 300, "feedback": 0.6},
                                    "distortion": {"on": True, "drive": 20}}},
}
CASES = {**{k: v for k, v in soundfx.PRESETS.items() if not soundfx.is_neutral(v)}, **EXTRA}


def noisy(seconds, seed=0):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    x = 0.4 * np.sin(2 * np.pi * 330 * t)[:, None] + 0.15 * rng.standard_normal((n, 2))
    x[n // 3:n // 3 + 200] = 0.99
    return np.clip(np.rint(x * 32767), -32768, 32767).astype(np.int16)


@pytest.fixture
def seeded(monkeypatch):
    """The radio's static is random: the same noise in every render."""
    real = np.random.default_rng
    monkeypatch.setattr(np.random, "default_rng",
                        lambda seed=None, *a: real(7 if seed is None else seed, *a))


@pytest.mark.parametrize("name", list(CASES))
def test_pieces_give_what_one_pass_gives(name, monkeypatch, seeded):
    x = noisy(1.5)
    fx = CASES[name]
    monkeypatch.setattr(soundfx, "CHUNK", 1 << 30)              # all of it in one piece
    whole = library.to_int16(soundfx.render(x, fx))
    monkeypatch.setattr(soundfx, "CHUNK", 2 * soundfx.BLOCK)    # ~18 pieces and the tail
    parts = library.to_int16(soundfx.render(x, fx))
    assert whole.shape == parts.shape
    d = np.abs(whole.astype(np.int32) - parts.astype(np.int32))
    f = soundfx.clean(fx)
    if eq.design(f["eq"], SR) is None:
        assert d.max(initial=0) == 0, name   # everything but the EQ: the same samples
        return
    # the EQ's filter splits its blocks differently: float rounding, a step or two
    # (more on some CPUs). Distortion after it can magnify that at a few samples
    # (steep zero crossings), so only nearly all of them must be that close.
    assert np.mean(d > 4) < 1e-3, f"{name}: {np.count_nonzero(d > 4)} samples, max {d.max()}"
    if not f["effects"]:
        assert d.max(initial=0) <= 4, name


@pytest.mark.parametrize("name", list(CASES))
def test_render_cached_writes_what_render_gives(app_dir, monkeypatch, seeded, name):
    monkeypatch.setattr(library, "REVERSE_CHUNK", 1000)           # many swaps, odd length
    x = noisy(1.2)[:-1]
    fx = CASES[name]
    want = library.to_int16(soundfx.render(x, fx))
    got = library.render_cached("s1", x, fx)
    assert got.dtype == np.int16 and np.array_equal(got, want), name
    assert np.array_equal(np.load(library.cache_path("s1", soundfx.key(fx))), want)
    assert not list(library.CACHE_DIR.glob("*.tmp.npy"))


def test_render_cached_falls_back_to_memory_when_the_file_cant_be_written(app_dir,
                                                                           monkeypatch):
    x = noisy(0.5)
    fx = {"gain_db": 6}

    def refuse(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(library, "_npy_header", refuse)
    got = library.render_cached("s1", x, fx)
    assert np.array_equal(got, library.to_int16(soundfx.render(x, fx)))
    assert not list(library.CACHE_DIR.glob("*.npy"))


def test_a_render_given_up_on_stops_and_keeps_nothing(app_dir):
    x = noisy(3.0)
    calls = []
    with pytest.raises(library.Cancelled):
        library.render_cached("s1", x, {"pitch": 4}, cancel=lambda: calls.append(1) or
                              len(calls) > 1)
    assert len(calls) == 2                       # stopped at the second piece
    assert not list(library.CACHE_DIR.glob("*.npy"))
    got = library.render_cached("s1", x, {"pitch": 4}, cancel=lambda: False)
    assert np.array_equal(got, library.to_int16(soundfx.render(x, {"pitch": 4})))


def test_preview_part_is_what_plays_first():
    x = np.arange(10 * SR, dtype=np.int16).reshape(-1, 1).repeat(2, 1)
    part, fx = soundfx.preview_part(x, {"start": 2.0, "end": 8.0, "pitch": 3}, 1.0)
    assert part[0, 0] == x[2 * SR, 0] and len(part) == SR
    assert fx["start"] == fx["end"] == 0.0 and fx["pitch"] == 3   # trimmed already
    part, _ = soundfx.preview_part(x, {"reverse": True}, 1.0)
    assert part[-1, 0] == x[-1, 0] and len(part) == SR           # backwards: the end
    part, _ = soundfx.preview_part(x, {"speed": 2.0}, 1.0)
    assert len(part) == 2 * SR                                    # a second as heard


def test_a_long_sound_renders_in_bounded_memory(app_dir):
    """A two-hour sound used to need ~10 GB: float32 copies of all of it, one per step.
    Now the peak is a few pieces, the same for 20 s as for 40 s."""
    peaks = {}
    for secs in (20, 40):
        x = noisy(secs, seed=secs)
        for name in ("Bass boosted", "Reversed", "Slowed + reverb", "Fast (same pitch)"):
            tracemalloc.start()
            try:
                library.render_cached(f"s{secs}", x, soundfx.PRESETS[name])
                _cur, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            peaks[secs, name] = peak
    for name in ("Bass boosted", "Reversed", "Slowed + reverb", "Fast (same pitch)"):
        assert peaks[40, name] < 32e6, f"{name}: {peaks[40, name] / 1e6:.0f} MB"
        assert peaks[40, name] < 1.2 * peaks[20, name] + 2e6, name     # doesn't grow


def test_an_effect_that_breaks_partway_is_rendered_again_without_it(monkeypatch):
    made = []

    class Flaky(voicefx.Effect):
        type, name = "test.flaky", "Flaky"

        def __init__(self, rate, values=None):
            super().__init__(rate, values)
            self.first, self.blocks = not made, 0
            made.append(self)

        def run(self, x, rate):
            self.blocks += 1
            if self.first and self.blocks > 70:     # past the first piece (64 blocks)
                raise RuntimeError("boom")
            return x * 0.5

    monkeypatch.setitem(voicefx.REGISTRY, Flaky.type, Flaky)
    x = noisy(3.0).astype(np.float32) / 32767
    y = soundfx.render(x, {"effects": {Flaky.type: {"on": True}}})
    assert len(y) == len(x)                              # started over: no doubled audio
    assert np.allclose(y[:, 0], x[:, 0], atol=1e-4)      # the broken channel: untouched
    assert np.allclose(y[:, 1], x[:, 1] * 0.5, atol=1e-4)


def test_sos_run_in_pieces_matches_one_filter_call():
    rng = np.random.default_rng(3)
    x = (rng.standard_normal((50_000, 2)) * 0.3).astype(np.float32)
    sos = eq.design([12, 10, 3, 0, 0, 0, 0], SR)
    whole = dsp.sosfilt(sos, x, axis=0)
    run = dsp.SosRun(sos)
    cuts = [0, 1, 777, 4096, 20_000, 33_333, 50_000]
    parts = np.concatenate([run.run(x[a:b]) for a, b in zip(cuts, cuts[1:])])
    assert np.abs(parts - whole).max() < 1e-5


@pytest.mark.parametrize("n,dst", [(1, 44100), (48_000, 38_400), (123_457, 60_000),
                                   (99_999, 30_235), (7, 192_000)])
def test_resampled_len_is_soxrs_own(n, dst):
    x = np.zeros((n, 2), np.float32)
    assert soundfx.resampled_len(n, dst) == len(soxr.resample(x, SR, dst, quality="VHQ"))
