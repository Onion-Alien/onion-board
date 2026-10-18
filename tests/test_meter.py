"""Level meter colours stay stable around their warning thresholds."""
import pytest

from soundboard.ui.kit.widgets import Meter


GREEN, YELLOW, RED = "#13ce66", "#ffb020", "#ff4d4f"


@pytest.mark.parametrize("levels, colours", [
    ([-12, -9, -9.1, -8.9, -10.99, -11, -11.01],
     [GREEN, YELLOW, YELLOW, YELLOW, YELLOW, YELLOW, GREEN]),
    ([-9, -2, -2.1, -1.9, -3.49, -3.5, -3.51],
     [YELLOW, RED, RED, RED, RED, RED, YELLOW]),
    ([-20, 0, -20, -2, -10, -12],
     [GREEN, RED, GREEN, RED, YELLOW, GREEN]),
])
def test_meter_threshold_hysteresis(qapp, levels, colours):
    meter = Meter()
    meter.resize(300, 8)
    for db, colour in zip(levels, colours):
        meter.set_level(10 ** (db / 20))
        frac, actual = meter._bar()
        assert actual == colour
        assert frac == pytest.approx((db + 50) / 50)
        # Painting calls _bar again; it must retain the same state.
        image = meter.grab().toImage()
        assert image.pixelColor(10, 4).name() == colour


def test_hot_override_tracks_underlying_level_and_silence_resets(qapp):
    meter = Meter()
    meter.hot = True
    meter.set_level(10 ** (-9 / 20))
    assert meter._bar()[1] == RED
    meter.hot = False
    assert meter._bar()[1] == YELLOW
    meter.set_level(1)
    meter.set_level(0)
    assert meter._bar() == (0, GREEN)
    meter.set_level(10 ** (-10 / 20))
    assert meter._bar()[1] == GREEN


def test_meter_colours_are_independent(qapp):
    first, second = Meter(), Meter()
    first.set_level(1)
    second.set_level(10 ** (-10 / 20))
    assert first._bar()[1] == RED
    assert second._bar()[1] == GREEN


def test_meter_tops_out_at_its_ceiling(qapp):
    """What others hear is held at the send limiter's ceiling: that's full and red."""
    from soundboard.audio.sendfx import CEILING_DB
    meter = Meter()
    meter.top_db = CEILING_DB
    meter.set_level(10 ** (CEILING_DB / 20))
    assert meter._bar() == (pytest.approx(1.0), RED)
    meter.set_level(10 ** ((CEILING_DB - 9) / 20))
    assert meter._bar()[1] == YELLOW
