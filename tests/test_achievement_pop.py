"""The "Achievement unlocked" pop-up (ui/window/achievepop.py) and its chime."""
import threading

import numpy as np
import pytest
from PySide6.QtWidgets import QWidget

from conftest import process_events
from soundboard.audio import achievechime
from soundboard.core import achievements as ach
from soundboard.sounds.library import Config
from soundboard.ui.window import achievepop as ap
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_the_chime_is_short_stereo_and_never_clips():
    x = achievechime.chime()
    assert x.dtype == np.float32 and x.ndim == 2 and x.shape[1] == 2
    assert 1.0 < len(x) / achievechime.SR < 2.0
    assert np.abs(x).max() <= achievechime.PEAK + 1e-6
    assert abs(float(x[-1].max())) < 1e-3   # fades out: no click at the end
    assert not np.allclose(x[:, 0], x[:, 1])   # the echo is wider than mono


def test_the_pop_up_opens_holds_and_folds_away():
    assert ap.shape_at(0) == (0.0, 0.0, 0.0)
    orb, bar, words = ap.shape_at(2000)
    assert orb == pytest.approx(1.0) and bar == pytest.approx(1.0) and words == 1.0
    orb, bar, words = ap.shape_at(ap.TOTAL)
    assert orb == pytest.approx(0.0, abs=1e-6) and bar == pytest.approx(0.0, abs=1e-6)
    assert words == 0.0


def test_its_words_have_the_points_and_the_name():
    top, bottom = ap.words("first_blood")
    assert top == "Achievement unlocked"
    assert bottom == "10G - First Blood"
    assert ap.words("rainbow_bun")[1].startswith("100G - ")
    assert set(ap.POINTS) == set(ach.TIERS)


class _Engine:
    def __init__(self):
        self.played = []

    def play(self, sid, data, gain, **kw):
        self.played.append((sid, kw))


@pytest.fixture
def pops(qapp, monkeypatch):
    monkeypatch.setattr(ap, "START_MS", 0)
    monkeypatch.setattr(ap, "GAP_MS", 0)
    host = QWidget()
    host.engine = _Engine()
    host.cfg = Config(achievement_popups=True, achievement_sound=True)
    p = ap.AchievementPops(host)
    process_events(qapp, lambda: p.ready)
    yield p
    p.shutdown()
    host.deleteLater()


def test_an_earned_one_pops_up_with_its_chime_in_the_headphones_only(qapp, pops):
    for f in list(ach.on_unlock):
        f("first_blood")
    process_events(qapp, lambda: pops.showing)
    assert pops.pop.isVisible() and pops.pop.bottom == "10G - First Blood"
    assert pops.mw.engine.played == [("__achievement__",
                                      {"mode": "restart", "preview": True})]


def test_pop_ups_and_their_chime_are_off_by_default(qapp, pops):
    pops.mw.cfg = Config()
    assert not pops.mw.cfg.achievement_popups and not pops.mw.cfg.achievement_sound
    pops.earned.emit("first_blood")
    process_events(qapp, lambda: pops.showing, timeout=0.3)
    assert not pops.showing and not pops.queue and pops.mw.engine.played == []


def test_the_chime_is_off_by_default_and_the_pop_up_still_shows(qapp, pops):
    pops.mw.cfg = Config(achievement_popups=True)
    pops.earned.emit("first_blood")
    process_events(qapp, lambda: pops.showing)
    assert pops.pop.isVisible() and pops.mw.engine.played == []


def test_several_queue_and_show_one_after_another(qapp, pops):
    for aid in ("first_blood", "spammer"):
        pops.earned.emit(aid)
    process_events(qapp, lambda: pops.showing)
    assert pops.queue == ["spammer"]
    pops.pop.t = ap.TOTAL   # the first one ends
    pops.pop._start = ap.TOTAL
    process_events(qapp, lambda: pops.pop.bottom.endswith("Spammer"))
    assert not pops.queue and len(pops.mw.engine.played) == 2


def test_one_earned_on_another_thread_shows_on_the_ui_thread(qapp, pops):
    t = threading.Thread(target=lambda: [f("critic") for f in list(ach.on_unlock)])
    t.start()
    t.join()
    process_events(qapp, lambda: pops.showing)
    assert pops.pop.bottom.endswith("Critic")


def test_shutdown_stops_listening(qapp, pops):
    pops.shutdown()
    assert pops._heard not in ach.on_unlock
    assert pops.pop is None


def test_the_window_makes_one_and_stops_it_at_quit(window):  # noqa: F811
    assert window.achievepops._heard in ach.on_unlock
    window.achievepops.shutdown()
    assert window.achievepops._heard not in ach.on_unlock



def test_pop_ups_turned_off_show_nothing_and_play_nothing(qapp, pops):
    pops.mw.cfg = Config(achievement_popups=False, achievement_sound=True)
    pops.earned.emit("first_blood")
    process_events(qapp, lambda: pops.showing, timeout=0.3)
    assert not pops.showing and not pops.queue and pops.mw.engine.played == []


def test_an_earned_one_is_counted_by_its_id_even_with_pop_ups_off(qapp, pops, monkeypatch):
    from soundboard.core import usage
    monkeypatch.setattr(usage, "_used", set())
    pops.mw.cfg = Config()   # pop-ups off: still earned, so still counted
    pops.earned.emit("golden_bun")
    process_events(qapp, lambda: "ach-golden-bun" in usage._used, timeout=1)
    assert usage._used == {"ach-golden-bun"}
