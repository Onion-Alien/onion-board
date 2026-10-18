"""The Store tab's Voices (ui/store/storevoices.py) against a fake store: no test goes online."""
import json

import numpy as np
import pytest
from conftest import process_events
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)

from soundboard.mic import savedvoices, voicesetups
from soundboard.online import store
from soundboard.sounds.library import Config
from soundboard.speech import aipreview
from soundboard.speech import aivoicelist as avl
from soundboard.ui.store import storetab
from soundboard.ui.store.storevoices import ShareVoiceDialog, VoiceHooks, VoiceRow


def _voice(i, kind="fx", **kw):
    data = {"fx": {"e": {"pitch": {"semitones": 7}}},
            "ai": {"mix": [[171, 1]], "formant": -1, "pitch_hz": 90},
            "setup": {"e": {"pitch": {"semitones": 3}}, "ai": {"id": "bear", "name": "Bear",
                                                                "pitch": 0}, "lang": "it"}}[kind]
    d = {"id": f"{i:012x}", "kind": kind, "name": f"Voice {i}", "about": "for fun",
         "emoji": "", "tags": [], "data": data, "up": 0, "down": 0, "mine": 0, "created": i}
    d.update(kw)
    return d


class FakeVoices:
    """Stands in for store._request for the /v1/voices calls."""

    def __init__(self, voices):
        self.voices = {v["id"]: v for v in voices}
        self.calls = []
        self.shared = []

    def __call__(self, method, path, install="", body=None, ctype="", limit=0, timeout=0,
                 why=None):
        self.calls.append((method, path))
        if path.startswith("/v1/voices?"):
            kind = next((p[5:] for p in path.split("?")[1].split("&") if p.startswith("kind=")), "")
            vs = [v for v in self.voices.values() if not kind or v["kind"] == kind]
            return json.dumps({"voices": vs, "more": False}).encode()
        if path == "/v1/voices":
            self.shared.append(json.loads(body))
            return b'{"id": "abcdefabcdef", "status": "live"}'
        vid = path.split("/")[3]
        if path.endswith("/vote"):
            v = self.voices[vid]
            val = json.loads(body)["value"]
            v["up"] += (val == 1) - (v["mine"] == 1)
            v["mine"] = val
            return json.dumps({"up": v["up"], "down": v["down"], "mine": val}).encode()
        if path.endswith("/report"):
            return b'{"reported": true}'
        if path.startswith("/v1/sounds") or path == "/v1/categories":
            return b'{"sounds": [], "categories": [], "total": 0}'
        raise AssertionError(path)


@pytest.fixture
def fake(monkeypatch, app_dir):
    f = FakeVoices([_voice(1, up=4), _voice(2, "ai", emoji="🐻"), _voice(3, "setup")])
    monkeypatch.setattr(store, "_request", f)
    t = np.arange(16000) / 16000
    monkeypatch.setattr(aipreview, "sample",
                        lambda: (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32))
    return f


def _tab(qapp, played):
    t = storetab.StoreTab(Config(), [].append, lambda d, g: played.append(d) or True,
                          lambda: None, voices=VoiceHooks(lambda: None))
    t.resize(800, 600)
    t.show()
    return t


def test_voices_list_hear_vote_get_and_report(qapp, fake):
    played = []
    t = _tab(qapp, played)
    assert "voices" in t.mode_btns
    t.mode_btns["voices"].click()
    assert process_events(qapp, lambda: len(t._rows) == 3)
    assert all(isinstance(r, VoiceRow) for r in t._rows)
    assert t.btn_share.text() == "Share a voice"
    assert [t.cat_pick.itemData(i) for i in range(t.cat_pick.count())] == [
        "", "fx", "ai", "setup"]
    fx, ai, setup = t._rows
    assert fx.meta.full.startswith("Voice changer") and "for fun" in fx.meta.full
    assert setup.meta.full.startswith("Setup · ") and "Bear" in setup.meta.full
    # hear it: the sample line through the voice, to the headphones only
    fx.btn_play.click()
    assert process_events(qapp, lambda: played and played[-1] is not None, timeout=20)
    assert played[-1].ndim == 2 and played[-1].shape[1] == 2
    # votes go to the voice routes
    fx.btn_up.click()
    assert process_events(qapp, lambda: (fx.sound.id, "vote") not in t._busy)
    assert ("POST", f"/v1/voices/{fx.sound.id}/vote") in fake.calls and fx.btn_up.text() == "5"
    # get: each kind lands in its own list of yours
    fx.btn_add.click()
    ai.btn_add.click()
    setup.btn_add.click()
    assert "Voice 1" in savedvoices.Store().voices
    assert [v["name"] for v in avl.Store().voices] == ["Voice 2"]
    assert voicesetups.Store().setups["Voice 3"]["language"] == "it"
    t.report(fx, "offensive")
    assert process_events(qapp, lambda: ("POST", f"/v1/voices/{fx.sound.id}/report")
                          in fake.calls)
    # a kind filters; back to Sounds lists sounds again
    t.cat_pick.activated.emit(t.cat_pick.findData("ai"))
    assert process_events(qapp, lambda: len(t._rows) == 1 and t._rows[0].sound.kind == "ai")
    t.mode_btns["sounds"].click()
    assert process_events(qapp, lambda: t.btn_share.text() == "Share a sound")
    assert process_events(qapp, lambda: not t._rows)
    t.shutdown()


def test_a_nasty_name_from_the_store_is_shown_as_plain_text(qapp, fake):
    fake.voices = {"000000000009": _voice(9, name="<img src=x>‮<b>Evil</b>\n​X")}
    t = _tab(qapp, [])
    t.set_mode("voices")
    assert process_events(qapp, lambda: len(t._rows) == 1)
    r = t._rows[0]
    assert r.sound.name == "img src=x b Evil /b X"   # no <>: as the store's sound names
    assert r.name.full == r.sound.name
    assert "‮" not in r.name.toolTip()
    t.shutdown()


def test_share_window_sends_only_the_settings(qapp, fake, app_dir):
    saved = savedvoices.Store()
    saved.put("Squeaky", {"pitch": {"on": True, "semitones": 9.0},
                          "cleanup": {"on": True, "gate": 0.9}})
    hooks = VoiceHooks(lambda: None)
    items = hooks.shareable()
    assert [label for label, _p in items] == ["Voice changer: Squeaky"]
    d = ShareVoiceDialog("0" * 20, items)
    assert d.name.text() == "Squeaky"
    d.name.setText("  Squeaky   robot ")
    d.about.setText("for\nmemes")
    d.send()
    assert process_events(qapp, lambda: fake.shared)
    assert fake.shared[0] == {"kind": "fx", "name": "Squeaky robot", "about": "for memes",
                              "emoji": "", "data": {"e": {"pitch": {"semitones": 9.0}}}}


def test_voice_tab_menus_open_the_share_window(main_window, qapp, monkeypatch):  # noqa: F811
    window = main_window
    if not window.tabctl.tab_on("voice"):
        return
    asked = []
    monkeypatch.setattr(window, "share_voice", asked.append)
    vp = window.voice
    vp.share_asked.disconnect()
    vp.share_asked.connect(window.share_voice)
    vp.fx.share_asked.emit("Squeaky")
    vp.setups_bar.share("Combo")
    assert asked == ["Voice changer: Squeaky", "Setup: Combo"]
    assert isinstance(window.store, storetab.StoreTab) and window.store.voices is not None
