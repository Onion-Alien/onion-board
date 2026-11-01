"""The song's beat and style, as it plays (soundboard/audio/groove.py): what Bun dances to."""
import numpy as np

from soundboard.audio.groove import STYLES, Groove
from soundboard.audio.engine import SR

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


def test_a_soundbite_or_someone_talking_is_not_music_from_the_first_moment():
    rng = np.random.default_rng(11)
    clip = Groove()
    clip.feed(_club(128, 3, rng), 0.0)      # 3 s: a soundbite, beat or not
    assert clip.music is False
    talk = Groove()
    talk.feed(_talk(25, rng), 0.0)          # its first seconds read ahead: talking
    assert talk.music is False and talk.style == ""
    song = Groove()
    song.feed(_club(128, 25, rng), 0.0)
    assert song.music is True
    radio = Groove()                        # a stream can't be read ahead
    radio.feed_live(_club(128, 1, rng)[:SR // 30].astype(np.float32) / 32768, now=0.0)
    assert radio.music is None


def test_talking_over_music_is_still_talking():
    # a talk video: a soft bass hum fills the gaps between the words, so they're never
    # silent
    rng = np.random.default_rng(12)
    talk = _talk(25, rng).astype(np.float32)
    t = np.arange(len(talk)) / SR
    pad = np.sin(2 * np.pi * 70 * t) * 32767 * 0.04
    data = np.clip(talk + pad[:, None], -32768, 32767).astype(np.int16)
    g = Groove()
    _play(g, data)
    assert g.features()["gaps"] < 0.25   # (the first speech rule can't hear it)
    assert g.style == "speech" and g.music is False


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


def test_a_busy_chorus_near_the_rock_line_keeps_his_dance(monkeypatch):
    # a loud pop chorus: busy, bright, its beat's sureness wobbling around the line the
    # "busy and unsure: rock" rule draws (it flipped him into headbanging and back)
    g = Groove()
    chorus = {"bpm": 110.0, "conf": 0.47, "four": 0.1, "on_beat": 0.8, "gaps": 0.0, "bass": -5.0,
              "voice": -4.0, "high": -12.0, "flat": 0.25, "cent": -0.2, "dyn": 1.0,
              "onsets": 0.9, "loud": -7.0}
    monkeypatch.setattr(g, "features", lambda: dict(chorus))
    assert g.guess() == "rock"   # (heard fresh, it's on the rock side of the line)
    g.style = "pop"
    assert g.guess() == "pop"    # but dancing to pop, a wobble this near the line keeps it
    chorus["conf"] = 0.38
    assert g.guess() == "rock"   # well over the line: it's really changed


def test_dark_techno_with_a_kick_on_every_beat_is_electronic_not_hiphop(monkeypatch):
    # dark and bassy at 143 BPM reads like hip-hop, where he nods to every bass note;
    # with a kick on nearly every beat it's techno, and he hops on the beat instead
    g = Groove()
    track = {"bpm": 143.0, "conf": 0.9, "four": 0.2, "on_beat": 0.8, "gaps": 0.0,
             "bass": -0.6, "voice": -20.0, "high": -26.0, "flat": 0.4, "cent": -3.1,
             "dyn": 1.0, "onsets": 0.14, "loud": -4.3}
    monkeypatch.setattr(g, "features", lambda: dict(track))
    assert g.guess() == "electronic"
    track["on_beat"] = 0.3   # an 808 on a few of the beats: hip-hop
    assert g.guess() == "hiphop"
    g.style = "electronic"   # but a breakdown, the kick out and the beat as sure, stays
    assert g.guess() == "electronic"
