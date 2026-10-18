"""Pong with Bun's sounds (soundboard/sounds/pongsounds.py): every sound in every theme's
style is clean (in range, no click at either end, not silent), the rally climbs, and
a sound sits on the side of the court the ball is on."""

import numpy as np
import pytest

from soundboard.sounds import pongsounds as ps
from soundboard import theme
from soundboard.engine import SR


@pytest.mark.parametrize("style", ps.KINDS)
@pytest.mark.parametrize("name", ps.NAMES)
def test_every_sound_is_clean_in_every_style(name, style):
    a = ps.render(name, style, rally=6, pan=0.3, heat=0.5, edge=True, level=2)
    assert a.dtype == np.float32 and a.ndim == 2 and a.shape[1] == 2
    assert np.isfinite(a).all()
    peak = np.abs(a).max()
    assert 0.01 < peak <= ps.PEAK + 1e-6
    assert np.abs(a[0]).max() < 0.05 and np.abs(a[-1]).max() < 1e-3   # no clicks
    assert len(a) < 2 * SR


def test_every_theme_has_a_known_style():
    assert set(ps.STYLES) <= set(theme.THEMES)
    for name in theme.THEMES:
        assert ps.style_for(name) in ps.KINDS
    assert ps.style_for("Not a theme") == "soft"


def _pitch(a):
    m = a.mean(1)[: int(0.05 * SR)]
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m)), 1 << 16))
    return np.argmax(spec) * SR / (1 << 16)


def test_a_rally_climbs_the_ladder():
    pitches = [_pitch(ps.render("you", "soft", rally=i)) for i in range(8)]
    assert all(b > a for a, b in zip(pitches, pitches[1:], strict=False))
    # past the top it stays on the top note
    assert ps.note(99) == ps.LADDER[-1]


def test_a_sound_comes_from_the_balls_side():
    left = ps.render("you", "soft", pan=-0.7)
    right = ps.render("you", "soft", pan=0.7)
    assert np.abs(left[:, 0]).sum() > 2 * np.abs(left[:, 1]).sum()
    assert np.abs(right[:, 1]).sum() > 2 * np.abs(right[:, 0]).sum()


def test_hits_are_never_quite_the_same():
    a, b = ps.render("you", "soft"), ps.render("you", "soft")
    n = min(len(a), len(b))
    assert not np.allclose(a[:n], b[:n])
