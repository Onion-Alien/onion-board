"""A voice whose recordings aren't downloaded yet (Cat, Farm, Fart, Drum kit...) goes on
only once they're in: never before, playing its made-up stand-in. Every way of
picking one waits the same way, and switching off or picking another drops the wait."""
import numpy as np
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from soundboard import voicefx
from soundboard.online import net
from soundboard.speech import tts
from soundboard.ui.kit import busy
from soundboard.voicefx import critters

REAL_STATE = critters.state   # (conftest makes every download count as in)


class Downloads:
    """critters' downloads, by hand: fetch starts one, finish/fail ends it."""

    def __init__(self, monkeypatch):
        self.fetched: list[str] = []
        monkeypatch.setattr(critters, "state", REAL_STATE)
        monkeypatch.setattr(critters, "_busy", set())
        monkeypatch.setattr(critters, "_failed", {})
        monkeypatch.setattr(critters, "_done", {})
        monkeypatch.setattr(critters, "fetch", self._fetch)

    def _fetch(self, kind):
        if kind not in critters._calls and kind not in critters._busy:
            critters._busy.add(kind)
            critters._failed.pop(kind, None)
            critters._done[kind] = 0
            self.fetched.append(kind)

    def finish(self, *kinds):
        for k in kinds:
            critters._calls[k] = (np.zeros(4800, np.float32),)
            critters._busy.discard(k)
        QTest.qWait(250)

    def fail(self, kind, why="the connection timed out"):
        critters._failed[kind] = why
        critters._busy.discard(kind)
        QTest.qWait(250)


@pytest.fixture
def dl(monkeypatch):
    return Downloads(monkeypatch)


@pytest.fixture
def toasts(monkeypatch):
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(busy, "toast", lambda w, text, kind="", *a, **k: seen.append((kind,
                                                                                        text)))
    return seen


@pytest.fixture
def fx(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicefxpanel import VoiceFxPanel
    holder = QWidget()
    panel = VoiceFxPanel({})
    panel.setParent(holder)
    holder.show()
    panel.setGeometry(0, 0, 1200, 1400)
    qapp.processEvents()
    yield panel
    holder.deleteLater()


def lit(fx) -> list[str]:
    return [n for n, b in fx._tile.items() if b.isChecked()]


def test_the_voices_that_download_say_what(dl):
    def kinds(name):
        return voicefx.downloads({t: {"on": True, **c}
                                  for t, c in voicefx.PRESETS[name].items()})
    assert kinds("Cat") == ["cat"]
    assert kinds("Fart") == ["fart"]
    assert kinds("Drum kit") == ["drum-kick", "drum-snare", "drum-hat", "drum-crash"]
    assert set(kinds("Farm")) == {"goat", "duck", "pig", "sheep", "cow", "cowbell", "donkey"}
    assert kinds("Robot") == []
    # every voice that needs a download names what it downloads, and only those do
    for name, p in voicefx.PRESETS.items():
        assert bool(kinds(name)) == voicefx.needs_download(p), name
    assert voicefx.downloads({"cat": {"on": False}}) == []   # switched off: nothing


def test_state_ready_loading_failed(dl):
    assert REAL_STATE(["cat"]) == critters.LOADING     # not fetched yet: still to come
    critters.fetch("cat")
    assert REAL_STATE(["cat"]) == critters.LOADING
    critters._failed["cat"] = "no connection"
    critters._busy.discard("cat")
    assert REAL_STATE(["cat"]) == critters.FAILED
    assert critters.error(["cat"]) == "no connection"
    critters.fetch("cat")                               # tried again
    assert REAL_STATE(["cat"]) == critters.LOADING and not critters.error(["cat"])
    critters._calls["cat"] = (np.zeros(10, np.float32),)
    critters._busy.discard("cat")
    assert REAL_STATE(["cat"]) == critters.READY
    assert REAL_STATE(["cat", "dog"]) == critters.LOADING   # all of them, not just one
    assert REAL_STATE([]) == critters.READY


def test_progress_counts_files(dl):
    critters.fetch("cat")
    assert critters.progress(["cat"]) == 0.0
    critters._done["cat"] = 1                            # 1 of its 2 files
    assert critters.progress(["cat"]) == pytest.approx(1 / 2)
    critters._calls["cat"] = (np.zeros(10, np.float32),)
    assert critters.progress(["cat"]) == 1.0


def test_load_records_why_it_failed(dl, monkeypatch):
    """The real loader: every file failing leaves the reason, not a voice with no calls."""
    def broken(src):
        raise OSError("no route to host")
    monkeypatch.setattr(critters, "_file", broken)
    critters._busy.add("cow")
    critters._load("cow")
    assert REAL_STATE(["cow"]) == critters.FAILED
    assert "no route to host" in critters.error(["cow"])
    assert critters._done["cow"] == len(critters.SOURCES["cow"])


def test_a_clicked_voice_waits_and_its_card_shows_it(fx, dl, toasts):
    fx.pick("Robot")
    fx._tile["Cat"].click()
    assert dl.fetched == ["cat"]
    QTest.qWait(250)
    assert fx.preset == "Robot" and fx.btn_power.isChecked()   # the old voice stays
    assert lit(fx) == ["Robot"]                                # Cat isn't lit up yet
    assert fx._tile["Cat"].progress is not None
    assert fx.waiting == "Cat"
    assert any(k == "busy" and "Cat" in t for k, t in toasts)
    dl.finish("cat")
    assert fx.preset == "Cat" and fx.btn_power.isChecked() and lit(fx) == ["Cat"]
    assert fx._tile["Cat"].progress is None and fx.waiting == ""


def test_off_stays_off_until_its_in(fx, dl):
    fx._tile["Cat"].click()
    QTest.qWait(250)
    assert not fx.btn_power.isChecked() and not fx.spec()["enabled"]
    assert lit(fx) == []
    dl.finish("cat")
    assert fx.spec()["enabled"] and fx.preset == "Cat"


def test_another_voice_picked_drops_the_wait(fx, dl):
    fx._tile["Cat"].click()
    fx._tile["Robot"].click()                 # needs nothing: on at once
    assert fx.preset == "Robot" and fx._tile["Cat"].progress is None
    dl.finish("cat")
    assert fx.preset == "Robot"               # Cat's wait was dropped


def test_another_downloading_voice_replaces_the_wait(fx, dl):
    fx._tile["Cat"].click()
    fx._tile["Dog"].click()
    assert fx.waiting == "Dog" and fx._tile["Cat"].progress is None
    dl.finish("cat")
    assert not fx.btn_power.isChecked()       # Cat came in, but Dog was picked since
    dl.finish("dog")
    assert fx.preset == "Dog" and fx.btn_power.isChecked()


def test_clicking_it_again_cancels(fx, dl):
    fx.pick("Robot")
    fx._tile["Cat"].click()
    fx._tile["Cat"].click()
    assert fx.waiting == "" and fx._tile["Cat"].progress is None
    assert lit(fx) == ["Robot"]
    dl.finish("cat")
    assert fx.preset == "Robot"


def test_switching_off_cancels(fx, dl):
    fx.pick("Robot")
    fx._tile["Cat"].click()
    fx.btn_power.setChecked(False)
    assert fx.waiting == ""
    dl.finish("cat")
    assert not fx.btn_power.isChecked()


def test_a_failed_download_turns_nothing_on(fx, dl, toasts):
    fx.pick("Robot")
    fx._tile["Cat"].click()
    dl.fail("cat")
    assert fx.preset == "Robot" and lit(fx) == ["Robot"]
    assert fx._tile["Cat"].progress is None and fx.waiting == ""
    warn = [t for k, t in toasts if k == "warn"]
    assert warn and "Cat" in warn[-1] and "timed out" in warn[-1]
    fx._tile["Cat"].click()                   # a click tries again
    assert dl.fetched == ["cat", "cat"]
    dl.finish("cat")
    assert fx.preset == "Cat"


@pytest.mark.parametrize("how", ["pick", "roll"])
def test_hotkeys_remote_and_random_wait_too(fx, dl, how):
    """A voice's hotkey, the remote and combos call pick; Random voice calls roll."""
    fx.pick("Robot")
    if how == "pick":
        assert fx.pick("Farm") is False
    else:
        class OnlyFarm:
            @staticmethod
            def choice(pool):
                return "Farm"
        assert fx.roll(OnlyFarm()) == "Farm"
    assert fx.preset == "Robot" and fx.waiting == "Farm"
    dl.finish("goat", "duck", "pig", "sheep", "cow", "cowbell")
    assert fx.preset == "Robot"               # the donkey still to come: not yet
    dl.finish("donkey")
    assert fx.preset == "Farm" and fx.btn_power.isChecked()


def test_switching_on_waits_for_the_voice_picked(fx, dl):
    dl.finish("cat")
    fx.pick("Cat")
    fx.btn_power.setChecked(False)
    del critters._calls["cat"]                 # (as if never downloaded)
    fx.btn_power.setChecked(True)              # the switch, a hotkey, Voices ON
    assert not fx.btn_power.isChecked() and not fx.spec()["enabled"]
    assert fx.waiting == "Cat"
    dl.finish("cat")
    assert fx.btn_power.isChecked() and fx.preset == "Cat"


def test_start_up_waits_for_last_times_voice(qapp, dl, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicefxpanel import VoiceFxPanel
    panel = VoiceFxPanel({"enabled": True, "preset": "Cat",
                          "effects": {"cat": {"on": True}}})
    try:
        assert not panel.spec()["enabled"] and panel.waiting == "Cat"
        dl.finish("cat")
        assert panel.spec()["enabled"] and panel.preset == "Cat"
    finally:
        panel.deleteLater()


def test_going_offline_drops_the_wait(fx, dl):
    fx._tile["Cat"].click()
    net.configure_features(offline=True)
    assert fx.waiting == ""
    dl.finish("cat")
    assert not fx.btn_power.isChecked()


def test_offline_says_why_and_turns_nothing_on(fx, dl, toasts):
    net.configure_features(off=["voices"])
    assert fx.pick("Cat") is False
    assert not fx.btn_power.isChecked() and dl.fetched == []
    assert any(k == "warn" and "Cat" in t for k, t in toasts)


def test_a_mix_with_an_animal_waits(fx, dl):
    fx.pick("Robot")
    fx.use_mix({"cat": {"on": True}, "pitch": {"on": True, "semitones": 3}})
    assert fx.preset == "Robot"
    dl.finish("cat")
    assert fx.btn_power.isChecked() and fx.rows["cat"].chk.isChecked()


def test_tile_paints_its_progress(fx, dl):
    fx._tile["Cat"].click()
    critters._done["cat"] = 1
    QTest.qWait(250)
    tile = fx._tile["Cat"]
    assert tile.progress == pytest.approx(1 / 2)
    assert "50%" in tile.toolTip()
    tile.grab()                                 # paints with the bar, Simple and Advanced
    fx.set_view("advanced")
    tile.grab()
