"""The song's beat and style, as it plays (soundboard/groove.py): what Bun dances to."""
import numpy as np

from soundboard.groove import STYLES, Groove
from soundboard.engine import SR

TICK = 1 / 30


def _play(g: Groove, data: np.ndarray, start: float = 0.0, secs: float | None = None):
    """Feed it the way the tick does: 30 times a second, `secs` of play from `start`."""
    end = len(data) / SR if secs is None else start + secs
    t = start
    while t < end:
        g.feed(data, t * SR / len(data), now=t)
        t += TICK
    return t


def _stereo(mono: np.ndarray) -> np.ndarray:
    return (np.repeat(mono[:, None], 2, axis=1) * 32767 * 0.5).astype(np.int16)


def _club(bpm: float, secs: float, rng) -> np.ndarray:
    """A kick on every beat and a hi-hat between: four to the floor."""
    n = int(secs * SR)
    out = np.zeros(n, np.float32)
    beat = 60 / bpm
    t = np.arange(int(0.12 * SR)) / SR
    kick = np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 30)) * t) * np.exp(-t * 18)
    hat = rng.standard_normal(int(0.03 * SR)) * np.exp(-np.arange(int(0.03 * SR)) / 300) * 0.3
    k = 0
    while (pos := int(k * beat * SR)) < n:
        out[pos:pos + len(kick)] += kick[:n - pos]
        h = int((k + 0.5) * beat * SR)
        if h < n:
            out[h:h + len(hat)] += hat[:n - h]
        k += 1
    return _stereo(out)


def _talk(secs: float, rng) -> np.ndarray:
    """Speech-like: voiced syllables in words, with pauses between phrases."""
    n = int(secs * SR)
    out = np.zeros(n, np.float32)
    pos = 0
    while pos < n:
        for _w in range(rng.integers(3, 8)):   # a phrase: a few syllables
            length = int(rng.uniform(0.12, 0.3) * SR)
            t = np.arange(length) / SR
            f0 = rng.uniform(110, 180)
            tone = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 12))
            env = np.sin(np.pi * np.arange(length) / length) ** 2
            seg = (tone * env * 0.25)[:max(0, n - pos)]
            out[pos:pos + len(seg)] += seg
            pos += length + int(rng.uniform(0.03, 0.08) * SR)
        pos += int(rng.uniform(0.35, 0.8) * SR)   # a breath between phrases
    return _stereo(out)


def test_finds_the_tempo_and_lands_on_the_beat():
    data = _club(128, 20, np.random.default_rng(1))
    g = Groove()
    end = _play(g, data)
    assert abs(g.bpm - 128) < 2.5 and g.confidence > 0.4
    # a whole beat at a kick (allowing the 10 ms frames and one FFT of lag)
    last_kick = int((end - 0.2) / (60 / 128)) * 60 / 128
    off = g.beat(last_kick) % 1.0
    assert min(off, 1 - off) < 0.15, off


def test_tells_someone_talking_from_a_beat():
    talk = Groove()
    _play(talk, _talk(25, np.random.default_rng(2)))
    assert talk.style == "speech"
    club = Groove()
    _play(club, _club(128, 25, np.random.default_rng(3)))
    assert club.style in STYLES and club.style != "speech"


def test_reads_only_whats_been_played_and_copes_with_seeks():
    data = _club(120, 60, np.random.default_rng(4))
    g = Groove()
    _play(g, data, 0, 6)
    assert g._pos <= 6.05 * SR
    _play(g, data, 40, 1)            # a jump ahead: it starts again from there
    assert 39 * SR < g._pos <= 41.05 * SR
    _play(g, data, 10, 1)            # and back
    assert g._pos <= 11.05 * SR
    g.feed(data[:2000], 0.5)         # another sound: forgets this one
    assert g.bpm == 0 and g.style == ""
    g.feed(None, 0.3)                # nothing to read: harmless
    g.feed(data[:100], 0.3)          # too short to hear: harmless


def test_hits_carry_the_time_they_are_heard_and_are_read_a_little_ahead():
    bpm = 120
    data = _club(bpm, 8, np.random.default_rng(5))
    g = Groove()
    end = _play(g, data, 0, 6)
    kicks = np.arange(0, 8, 60 / bpm)
    times = [t for t, _s in g.hits["bass"]]
    assert len(times) >= 6
    # each on a kick, to within a 10 ms frame or so (Bun's head lands on these)
    assert all(np.abs(kicks - t).min() < 0.02 for t in times), times
    # the next kick is already known 30 ms before it's heard, and last_hit leaves it out
    nxt = kicks[kicks > end + 0.1][0]
    g.feed(data, (nxt - 0.03) * SR / len(data), now=nxt - 0.03)
    until, _s = g.next_hit("bass", nxt - 0.03)
    assert abs(until - 0.03) < 0.02
    assert g.last_hit("bass", nxt - 0.03)[0] > 0.3


def test_a_stream_like_the_radio_is_heard_chunk_by_chunk():
    bpm = 128
    data = _club(bpm, 14, np.random.default_rng(6)).astype(np.float32) / 32768
    g = Groove()
    step = int(SR * TICK)
    for pos in range(0, len(data) - step, step):
        g.feed_live(data[pos:pos + step], now=(pos + step) / SR)   # (heard as it arrives)
    assert abs(g.bpm - bpm) < 2.5 and g.style and g.style != "speech"
    kicks = np.arange(0, 14, 60 / bpm)
    times = [t for t, _s in g.hits["bass"]]
    assert len(times) >= 6 and all(np.abs(kicks - t).min() < 0.02 for t in times)
    g.feed(_club(bpm, 2, np.random.default_rng(7)), 0.5)   # a sound now: starts again
    assert g.bpm == 0
