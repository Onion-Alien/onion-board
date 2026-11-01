"""The Voice panel, offscreen: presets reach the chain, settings round-trip."""
from collections import OrderedDict
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint

from soundboard import voicefx
from soundboard.speech import tts
from tests.conftest import process_events
from test_mainwindow import window  # noqa: F401

# Chinese, downloaded with its voice (for a test that only needs "it's translating")
ZH = SimpleNamespace(language="zh", language_name="Chinese", voice={"name": "Huayan"})


class FakeEngine:
    voice_chain = None
    mic_stream = None   # a shown panel's meter asks: no mic here
    level_mic = 0.0

    def play(self, *a, **k):
        pass

    def stop(self, sid):
        pass


@pytest.fixture
def panel(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voice.voicepanel import VoicePanel
    eng = FakeEngine()
    p = VoicePanel(eng, {"enabled": False, "effects": {}},
                   {"voice": "Microsoft Zira Desktop", "rate": 2})
    # a language picked starts translating at once: never a real helper in a test (one
    # that wants to see it starting patches start_live itself)
    monkeypatch.setattr(p.speech.ctl, "start_live", lambda *a, **k: None)
    yield p, eng
    p.shutdown()
    p.deleteLater()


def test_panel_installs_the_chain_on_the_engine(panel):
    p, eng = panel
    assert eng.voice_chain is p.chain
    # built-ins and add-ons get rows (the Effects pop-up's extras live there instead)
    assert {t for t, c in voicefx.REGISTRY.items() if not c.extra} <= set(p.fx.rows)
    assert not {t for t, c in voicefx.REGISTRY.items() if c.extra} & set(p.fx.rows)


@pytest.mark.parametrize("name", ["Hothead", "Autotune"])
def test_hothead_and_autotune_tiles_change_the_engine_mic_and_stop_cleanly(panel, name):
    p, eng = panel
    p.fx._tile[name].click()
    assert p.fx.preset == name and eng.voice_chain.enabled
    t = np.arange(48000 // 2) / 48000
    x = (0.02 * (np.sin(2 * np.pi * 120 * t) + np.sin(2 * np.pi * 1500 * t)))
    x = np.repeat(x.astype(np.float32)[:, None], 2, axis=1)
    y = np.concatenate([eng.voice_chain.process(x[i:i + 480], 48000)
                        for i in range(0, len(x), 480)])
    assert not eng.voice_chain.errors
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) > 0.001
    assert not np.allclose(y[4800:], x[4800:], atol=0.001)
    p.bar.master.click()
    assert np.array_equal(eng.voice_chain.process(x[:480], 48000), x[:480])
    p.fx._tile[name].click()
    assert eng.voice_chain.enabled
    assert np.all(np.isfinite(eng.voice_chain.process(x[:480], 48000)))


def bar(p, key: str) -> str:
    """A voice's own bar (the voice changer's, the AI voice's, a language's own voice's):
    on, paused or hidden."""
    panel = {"fx": p.fx, "ai": p.ai, "lang": p.lang_bar}[key]
    return "hidden" if panel.picked.isHidden() else "paused" if panel._paused else "on"


@pytest.mark.parametrize("tab", ["fx", "ai", "speak", "addons"])
def test_voices_switch_is_visible_and_brings_the_same_voice_back(panel, qapp, tab):
    """The bottom bar's Voices switch (it replaced a red Stop that forgot what was on):
    OFF pauses the voice, ON brings the very same one back, from any tab."""
    p, eng = panel
    p.resize(800, 600)
    p.show()
    p.fx.pick("Robot")
    before = p.fx.spec()
    p.show_tab(tab)
    qapp.processEvents()
    button = p.bar.master
    assert button.isVisibleTo(p) and button.isChecked()
    assert button.accessibleName() == "Voices on or off"
    assert p.bar.rect().contains(button.rect().translated(button.mapTo(p.bar, QPoint())))
    button.click()
    assert not p.is_active() and not button.isChecked()
    assert p.current_tab() == tab
    assert p.fx.spec() == {**before, "enabled": False}
    assert p.bar.texts() == ["Mic unchanged"] and bar(p, "fx") == "paused"
    assert "Robot" in button.toolTip()
    button.click()
    assert p.fx.spec() == before and button.isChecked()
    assert p.bar.texts() == [] and bar(p, "fx") == "on"
    assert eng.voice_chain is p.chain


def test_voices_switch_off_remembers_every_voice_and_on_brings_exactly_those(
        panel, monkeypatch):
    p, _eng = panel
    monkeypatch.setattr("soundboard.speech.spoken.heard", lambda: True)
    started = []
    monkeypatch.setattr(type(p.speech), "translating",
                        lambda self: ZH if self.cb_lang.currentData() else None)
    monkeypatch.setattr("soundboard.core.langnames.of", lambda m: "Chinese")
    p.fx.pick("Robot")
    p.speech.cb_lang.blockSignals(True)
    p.speech.cb_lang.setCurrentIndex(p.speech.cb_lang.findData("zh"))
    p.speech.cb_lang.blockSignals(False)
    assert p.on_keys() == ["fx", "lang"]
    p.set_voices(False)
    assert p.on_keys() == [] and not p.speech.cb_lang.currentData()
    assert not p.bar.master.isChecked()
    assert [k for k in p.bar.chips if k != "none"] == ["lang"]
    assert p.bar.chips["lang"].property("state") == "off"
    assert bar(p, "fx") == "paused"
    p.set_voices(False)                   # already off: still remembers
    p.set_voices(True)
    assert p.on_keys() == ["fx", "lang"]
    assert p.fx.preset == "Robot" and p.speech.cb_lang.currentData() == "zh"
    assert started == []
    assert p.bar.master.isChecked()


def test_voices_switch_with_nothing_remembered_says_and_turns_on_the_picked_voice(panel):
    p, _eng = panel
    p.fx.pick("Robot")
    p.fx.btn_power.setChecked(False)      # off on its card: nothing for the switch to recall
    assert p.bar.texts() == ["Mic unchanged"] and bar(p, "fx") == "paused"
    assert not p._bar_ctl["fx"][1].isHidden()     # its ✕ works
    assert "Turns on: Robot" in p.bar.master.toolTip()
    p.bar.master.click()
    assert p.fx.btn_power.isChecked() and p.fx.preset == "Robot"


def test_voices_off_then_x_on_the_grey_voice_takes_its_chip_away(panel):
    """OFF, then the grey voice's ✕: its chip goes and ON turns nothing on. (It came
    straight back as "ON turns on:" the same voice, with no ✕: the ✕ looked dead.)"""
    p, _eng = panel
    p.fx.pick("Robot")
    p.bar.master.click()
    assert p.bar.texts() == ["Mic unchanged"] and bar(p, "fx") == "paused"
    p._bar_ctl["fx"][1].click()
    assert p.bar.texts() == ["Mic unchanged"] and p.back_keys() == []
    assert bar(p, "fx") == "hidden"
    p.bar.master.click()
    assert not p.is_active() and not p.bar.master.isChecked()
    p.fx.pick("Robot")                    # picked again: on, and ON/OFF work as before
    assert p.on_keys() == ["fx"]
    p.bar.master.click()
    p.bar.master.click()
    assert p.on_keys() == ["fx"]


def test_voices_switch_off_keeps_a_voice_greyed_by_its_chip(panel):
    """A chip clicked off shows grey, "coming back": switching Voices OFF afterwards
    must not forget it."""
    p, _eng = panel
    p.fx.pick("Robot")
    p._bar_ctl["fx"][0].click()           # Robot paused from its bar
    assert p.bar.texts() == ["Mic unchanged"] and not p.bar.master.isChecked()
    assert bar(p, "fx") == "paused"
    p.bar.master.click()
    assert p.on_keys() == ["fx"] and p.fx.preset == "Robot"


def test_stop_all_remembers_for_the_voices_switch(panel):
    p, _eng = panel
    p.fx.pick("Robot")
    p.stop_all()                          # the window's Stop everything
    assert not p.is_active()
    p.toggle_voices()
    assert p.fx.btn_power.isChecked() and p.fx.preset == "Robot"


def test_reset_forgets_every_voice_so_voices_on_brings_none_back(panel):
    """Voices OFF (or Stop all) remembers what was on; Reset is the fresh start: off,
    forgotten, the mix emptied, so Voices ON brings nothing back. Undo puts it all back."""
    p, eng = panel
    p.fx.use_mix({"pitch": {"on": True, "semitones": 5.0, "mix": 1.0},
                  "robot": {"on": True}})
    p.bar.master.click()                  # off: remembered, its bar dimmed
    assert p.bar.texts() == ["Mic unchanged"]
    assert bar(p, "fx") == "paused"
    assert p.bar.reset_button.isVisibleTo(p.bar)
    p.bar.reset_button.click()
    assert not p.is_active() and p.back_keys() == []
    assert p.fx.is_blank() and not eng.voice_chain.enabled
    assert p.bar.texts() == ["Mic unchanged"] and bar(p, "fx") == "hidden"
    p.bar.master.click()                  # ON: nothing to bring back, stays off
    assert not p.is_active() and not p.bar.master.isChecked()
    assert p.bar.texts() == ["Mic unchanged"]
    p.fx.pick("Robot")                    # a voice picked works as before
    assert p.on_keys() == ["fx"]


def test_reset_while_voices_are_on_turns_them_off_and_undo_brings_them_back(panel):
    p, eng = panel
    p.fx.use_mix({"pitch": {"on": True, "semitones": 5.0, "mix": 1.0}})
    before = p.fx.spec()
    p.bar.reset_button.click()
    assert p.on_keys() == [] and p.fx.is_blank()
    assert p.reset_undo.active()
    p.reset_undo.undo()
    assert p.on_keys() == ["fx"] and p.fx.spec() == before
    assert eng.voice_chain.enabled


def test_reset_shows_its_undo_card_on_the_window(window):  # noqa: F811
    """The bar's Reset puts a "Voices reset" card up on the window, and its Undo
    button brings the voice back."""
    from soundboard.ui.kit import toast
    v = window.voice
    v.fx.pick("Robot")
    assert v.on_keys() == ["fx"]
    v.reset_voices()
    assert v.on_keys() == []
    cards = [t for t in toast.shown(window) if "Voices reset" in t.words()]
    assert len(cards) == 1
    undo = cards[0].card.action
    assert undo.isVisibleTo(cards[0]) and undo.text() == "Undo"
    undo.click()
    assert v.on_keys() == ["fx"] and v.fx.preset == "Robot"

def test_global_voice_stop_turns_off_replacements_and_translation(panel, monkeypatch):
    p, eng = panel
    calls = []
    # Set the switches without starting real helpers, then restore their signals.
    for button in (p.ai.b_start,):
        button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(False)
    p.speech.cb_lang.blockSignals(True)
    p.speech.cb_lang.setCurrentIndex(p.speech.cb_lang.findData("zh"))
    p.speech.cb_lang.blockSignals(False)
    lv = p.speech.livevoice
    lv.bg_for, lv._bg_key = "ai", ("ai", "zh")          # translating for the AI voice
    monkeypatch.setattr(type(p.ai_controller), "running", property(lambda self: True))
    monkeypatch.setattr(p.ai_controller, "stop", lambda: calls.append("ai"))
    monkeypatch.setattr(type(p.controller), "live", property(lambda self: True))
    monkeypatch.setattr(p.controller, "stop_live", lambda: calls.append("speech"))
    monkeypatch.setattr(p.controller, "stop_speaking", lambda: calls.append("typed"))
    p.stop_all()
    assert not p.ai.is_on()
    assert not p.speech.cb_lang.currentData()          # Don't translate
    assert "typed" in calls
    assert "ai" in calls
    assert "speech" in calls


def test_preset_turns_the_changer_on_and_configures_the_chain(panel):
    p, _ = panel
    seen = []
    p.fx_changed.connect(seen.append)
    p.fx.pick("Robot")
    spec = seen[-1]
    assert spec["enabled"] and spec["preset"] == "Robot"
    assert spec["effects"]["robot"]["on"] and not spec["effects"]["pitch"]["on"]
    p.chain.process(np.zeros((32, 2), np.float32), 48000)
    assert [e.type for e in p.chain._effects] == ["robot", "compressor", "reverb"]


def test_editing_a_slider_switches_to_custom(panel):
    p, _ = panel
    p.fx.pick("Chipmunk")
    row = p.fx.rows["pitch"]
    row.sliders[0].slider.setValue(row.sliders[0].slider.value() - 3)   # half steps
    assert p.fx.preset == "Custom"
    assert p.fx.spec()["effects"]["pitch"]["semitones"] == 6.5


def test_power_switch(panel):
    p, _ = panel
    seen = []
    p.fx_changed.connect(seen.append)
    assert not p.fx.btn_power.isChecked() and p.fx.btn_power.text() == "Off"
    assert "OFF" in p.fx.btn_power.accessibleName()
    p.fx.pick("Deep voice")                  # picking a voice turns it on
    assert p.fx.btn_power.isChecked() and p.fx.btn_power.text() == "On"
    assert "ON" in p.fx.btn_power.accessibleName()
    assert p.fx._tile["Deep voice"].isChecked()
    p.fx.btn_power.setChecked(False)         # the switch turns it off, voice kept
    assert not seen[-1]["enabled"] and seen[-1]["preset"] == "Deep voice"
    assert not p.fx._tile["Deep voice"].isChecked()   # nothing looks selected while off
    assert not hasattr(p.fx, "btn_hear")     # one switch for hearing it: the mixer's


def test_the_lit_voice_card_says_a_click_turns_it_off(panel):
    p, _ = panel
    deep, robot = p.fx._tile["Deep voice"], p.fx._tile["Robot"]
    assert "turn the voice changer off" not in deep.toolTip()
    deep.click()                             # on
    assert p.fx.btn_power.isChecked()
    assert "turn the voice changer off" in deep.toolTip()
    assert "turn the voice changer off" not in robot.toolTip()
    deep.click()                             # the lit card again: the changer off
    assert not p.fx.btn_power.isChecked()
    assert "turn the voice changer off" not in deep.toolTip()


def test_saved_spec_loads_back(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicepanel import VoiceFxPanel
    spec = {"enabled": True, "preset": "Custom",
            "effects": {"echo": {"on": True, "delay": 400, "feedback": 0.5, "mix": 0.2}}}
    fx = VoiceFxPanel(spec)
    got = fx.spec()
    assert got["enabled"] and got["effects"]["echo"]["on"]
    assert got["effects"]["echo"]["delay"] == pytest.approx(400)
    assert not got["effects"]["robot"]["on"]


def test_voice_list_arrives_and_selection_is_kept(panel, qapp):
    p, _ = panel
    assert process_events(qapp, lambda: p.speech.cb_voice.isEnabled())
    assert p.speech.cb_voice.currentData() == "Microsoft Zira Desktop"
    assert p.controller.speaker.rate == 2


def test_live_voice_needs_the_addon_set_up(panel):
    p, _ = panel
    # the repo's live-voice module has no .venv in a test checkout -> install hint
    m = p.speech.module
    if m is None or not m.installed:
        assert p.speech.lang_box.isHidden() and not p.speech.installs.missing.isHidden()


def test_everything_spoken_lands_in_the_log(panel, monkeypatch):
    p, _ = panel
    s = p.speech
    monkeypatch.setattr(s.ctl, "say", lambda text: None)
    s.ed.setText("typed line")
    s._say()
    s.livevoice._on_event({"type": "final", "text": "heard line"})
    s.livevoice._on_event({"type": "final", "text": ""})
    lines = s.said_log.toPlainText().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("typed line") and lines[1].endswith("heard line")


def test_changer_starts_off_even_if_it_was_left_on(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicefxpanel import POWER_TEXT
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": True, "preset": "Old telephone", "effects": {}}, {})
    try:
        assert not p.fx.btn_power.isChecked() and not p.chain.enabled
        assert p.fx.btn_power.accessibleName() == POWER_TEXT[False]
        assert not any(t.isChecked() for t in p.fx._tile.values())   # nothing looks active
        assert p.fx.preset == "Old telephone"                          # the choice is kept
    finally:
        p.shutdown()
        p.deleteLater()


def test_speak_in_offers_the_languages_and_downloads_only_on_request(panel, monkeypatch):
    from soundboard.speech import translation
    p, _ = panel
    s = p.speech
    codes = [s.cb_lang.itemData(i) for i in range(s.cb_lang.count())]
    assert codes[0] == "" and {"zh", "es", "fr", "de", "ru", "ja", "pt-BR", "zh-TW"} <= set(codes)
    assert len(codes) == 36
    assert s.tr_box.isHidden()                          # English: nothing to download
    assert not translation.base_dir().exists()          # and nothing was fetched
    got = []
    s.changed.connect(got.append)
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("de"))
    assert got[-1]["translate"] == "de"
    assert not s.tr_box.isHidden() and not s.installs.b_dl.isHidden()
    assert s.installs.b_dl.text() == "Download German" and "214 MB" in s.lbl_tr.text()
    started = []
    monkeypatch.setattr(s.ctl, "start_live", lambda m, args=(): started.append(args))
    if s.module is not None:
        s.livevoice._toggle_live(True)                  # not downloaded: refuses to start
        assert started == [] and "Download German first" in s.livevoice.lbl_state.text()


def _ready(monkeypatch, codes):
    from soundboard.addons import modules as mods
    monkeypatch.setattr(mods.ModuleInfo, "installed", property(
        lambda self: self.language in codes if self.kind == "translation" else True))


def test_languages_are_cards_grey_until_downloaded(panel, monkeypatch):
    """The Languages card works as AI voices: a card per language, the downloaded ones
    first, the rest grey; the switch next to the card's name."""
    p, _ = panel
    _ready(monkeypatch, {"de", "fr"})
    s = p.speech
    s.set_modules(p.modules)
    assert set(s._tile) == {m.language for m in s.langs}
    assert not s._tile["de"].property("missing") and s._tile["it"].property("missing")
    assert "Click to download" in s._tile["it"].toolTip()
    assert s.cb_lang.isHidden()                       # no Speak in list any more
    assert s.head.isAncestorOf(s.b_on)
    s.show_group("ready")
    assert {c for c, b in s._tile.items() if not b.isHidden()} == {"de", "fr"}
    s.set_favorite("fr", True)
    s.show_group("favs")
    assert {c for c, b in s._tile.items() if not b.isHidden()} == {"fr"}
    assert s.s["lang_favorites"] == ["fr"]


def test_a_language_card_turns_it_on_and_off_like_a_voice(panel, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    p, _ = panel
    _ready(monkeypatch, {"de", "fr"})
    s = p.speech
    s.set_modules(p.modules)
    monkeypatch.setattr(s.ctl, "start_live", lambda *a, **k: None)
    monkeypatch.setattr(s, "_warm_for_a_line", lambda: None)
    p.ai.is_on = lambda: True                       # the AI voice says it: no computer voice
    s.said_by("ai", "Duke")
    QTest.mouseClick(s._tile["de"], Qt.LeftButton)
    assert s.cb_lang.currentData() == "de" and s.b_on.isChecked()
    assert s._tile["de"].isChecked() and not s._tile["fr"].isChecked()
    assert not s.livevoice.b_live.isChecked()
    QTest.mouseClick(s._tile["fr"], Qt.LeftButton)  # another one: that one instead
    assert s.cb_lang.currentData() == "fr" and not s._tile["de"].isChecked()
    QTest.mouseClick(s._tile["fr"], Qt.LeftButton)  # the lit one: off
    assert not s.cb_lang.currentData() and not s.b_on.isChecked()
    assert not any(b.isChecked() for b in s._tile.values())
    QTest.mouseClick(s.b_on, Qt.LeftButton)         # the switch: the last one back
    assert s.cb_lang.currentData() == "fr" and s.b_on.isChecked()
    QTest.mouseClick(s.b_on, Qt.LeftButton)
    assert not s.cb_lang.currentData()


def test_a_language_with_nobody_else_to_say_it_is_read_by_its_own_voice(panel, monkeypatch):
    """The bug: Chinese on, nothing else on, and a "David (Computer voice)" row showed
    up: the old computer voice was started for it. Now the language's own voice reads
    it, with no row of its own (the Chinese chip says it) and no Start."""
    p, _ = panel
    _ready(monkeypatch, {"de"})
    monkeypatch.setattr("soundboard.speech.spoken.heard", lambda: True)
    s = p.speech
    s.set_modules(p.modules)
    s.voices_need = ""                             # its voice downloaded, and readable
    monkeypatch.setattr(s.ctl.tts, "voice_for", lambda lang, prefer="": "piper:" + lang)
    asked = []
    monkeypatch.setattr(s.livevoice, "translate_for", asked.append)
    s.set_language("de")
    assert asked[-1] == "read" and not s.livevoice.b_live.isChecked()
    # the voice speaking has its row, like the AI voice's: its own name, not David
    assert bar(p, "lang") == "on" and p.is_active()
    assert p.lang_bar.picked_name.text() == "Thorsten"
    assert p.lang_bar.picked_kind.text() == "(German voice)"
    assert p.bar.texts() == []                     # on its row, not a chip as well
    assert p.controller.on_top                     # the Effects play on its lines
    p._bar_ctl["lang"][0].click()                  # its pause: off, the row dimmed
    assert bar(p, "lang") == "paused" and not s.cb_lang.currentData()
    assert "Thorsten" in p.bar.master.toolTip()    # ON brings it back
    p._bar_ctl["lang"][0].click()                  # ...and back, the same language
    assert bar(p, "lang") == "on" and s.cb_lang.currentData() == "de"
    p._bar_ctl["lang"][1].click()                  # its ✕: off and forgotten
    assert bar(p, "lang") == "hidden" and not p.is_active() and not p.controller.on_top
    assert asked[-1] == ""


def test_with_the_ai_voice_speaking_the_language_its_row_says_who(panel, monkeypatch):
    """Pixie says the Chinese: Pixie's row shows (it's her voice others hear), the
    language is a chip, and the language voice has no row of its own."""
    p, _ = panel
    _ready(monkeypatch, {"zh"})
    monkeypatch.setattr("soundboard.speech.spoken.heard", lambda: True)
    s = p.speech
    s.set_modules(p.modules)
    monkeypatch.setattr(s.livevoice, "translate_for", lambda who: None)
    monkeypatch.setattr(p.ai, "is_on", lambda: True)
    s.set_language("zh")
    p._emit_active()
    assert bar(p, "lang") == "hidden" and "Chinese" in p.bar.texts()


def test_a_grey_language_card_asks_then_downloads_and_turns_it_on(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    p, _ = panel
    ready = {"de"}
    _ready(monkeypatch, ready)
    s = p.speech
    s.set_modules(p.modules)
    monkeypatch.setattr("soundboard.online.net.offline", lambda: False)
    monkeypatch.setattr("soundboard.online.net.allowed", lambda what: True)
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: (asked.append(a[2]), answers.pop(0))[1])
    got = []
    monkeypatch.setattr(s.installs, "_download", lambda m=None: got.append(m.language))
    voice = []
    monkeypatch.setattr(s.installs, "_install_voice", lambda: voice.append("windows"))
    monkeypatch.setattr(s.installs, "_recheck_voices", lambda: voice.append("reload"))
    s._tile_clicked("it")                           # No: nothing happens
    assert "Italian isn't downloaded yet" in asked[0] and got == []
    assert not s.cb_lang.currentData()
    s._tile_clicked("it")                           # Yes: it downloads
    assert got == ["it"] and not s.cb_lang.currentData()
    assert "with a voice that speaks Italian" in asked[0]
    ready.add("it")                                 # ...it's in, with its voice
    s.downloaded.emit()
    assert s.cb_lang.currentData() == "it" and s._tile["it"].isChecked()
    assert voice == ["reload"]                      # its voice joins the lists; no Windows


def test_a_grey_language_card_offline_says_why(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    p, _ = panel
    _ready(monkeypatch, set())
    s = p.speech
    s.set_modules(p.modules)
    monkeypatch.setattr("soundboard.online.net.offline", lambda: True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: 1 / 0)
    toasts = []
    monkeypatch.setattr("soundboard.ui.kit.busy.toast", lambda w, t, *a, **k: toasts.append(t))
    s._tile_clicked("it")
    assert toasts and "Offline mode" in toasts[0]


def test_languages_tab_hides_offline_until_speech_recognition_is_in(panel, monkeypatch):
    """Offline mode and no speech recognition: nothing on the Languages card can work
    or be installed, so its tab goes (as AI voices'). Installed, it works offline."""
    from soundboard.addons import modules as mods
    p, _ = panel
    s = p.speech
    if s.module is None:
        pytest.skip("no live-voice add-on in this copy")
    live = s.module.id
    installed = [False]
    monkeypatch.setattr(mods.ModuleInfo, "installed", property(
        lambda self: installed[0] if self.id == live else True))
    monkeypatch.setattr("soundboard.speech.spoken.heard", lambda: True)
    off = [False]
    monkeypatch.setattr("soundboard.online.net.offline", lambda: off[0])
    s.installs._refresh_module()
    p._ai_net_changed()
    p.show_tab("speak")
    assert p.current_tab() == "speak"
    # online: Install shows, but no switch or "Pick a language" with nothing to pick
    assert not s.installs.b_install.isHidden()
    assert s.b_on.isHidden() and s.lbl_intro.isHidden() and s.cards.isHidden()
    off[0] = True
    s.installs._net_changed()
    p._ai_net_changed()
    assert p._tabs["speak"].isHidden() and p.current_tab() == "fx"
    installed[0] = True
    s.installs._refresh_module()
    p._ai_net_changed()
    assert not p._tabs["speak"].isHidden()
    assert not s.b_on.isHidden() and not s.lbl_intro.isHidden()


def test_a_language_without_its_own_voice_needs_a_windows_voice(panel, monkeypatch):
    """Japanese comes without a voice of its own (yet): it still uses a Windows one."""
    from soundboard.speech import translation
    p, _ = panel
    s = p.speech
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("ja"))
    m = s._lang()
    d = translation.model_dir(m)
    (d / "model").mkdir(parents=True)
    (d / "model" / "model.bin").write_bytes(b"x")
    (d / "sentencepiece.model").write_bytes(b"x")
    tts = s.ctl.tts
    tts.voices, tts.voice_langs = ["Microsoft Zira Desktop"], {"Microsoft Zira Desktop": "en-US"}
    s._fill_langs()
    assert s.cb_lang.currentText() == "Japanese"
    assert s.installs.b_dl.isHidden() and not s.installs.b_voices.isHidden()
    assert "no Japanese voice" in s.lbl_tr.text()
    tts.voices.append("Microsoft Haruka")
    tts.voice_langs["Microsoft Haruka"] = "ja-JP"
    s._refresh_translation()
    assert s.installs.b_voices.isHidden() and sp_who(s, "Haruka")
    args = s.livevoice._live_args()
    assert args[args.index("--translate") + 1] == str(d)
    assert s.ctl.live_voice == "Microsoft Haruka"
    s.livevoice._on_event({"type": "final", "text": "Konnichiwa", "original": "Hello"})
    assert s.said_log.toPlainText().endswith("Konnichiwa   (you said: Hello)")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    s.installs._remove_download()                         # asks, then "Deleting…" on the button
    process_events(QApplication.instance(), lambda: not d.exists())
    assert "(download" in s.cb_lang.currentText()


def test_remove_languages_takes_speech_recognition_back_off(panel, qapp, monkeypatch,
                                                            tmp_path):
    """More options' Remove languages (as AI voices' Remove): speech recognition's
    environment, its speech models and every downloaded language go; the add-on that
    came with the app stays, so Install speech recognition gets it all back."""
    import dataclasses
    from PySide6.QtWidgets import QMessageBox
    from soundboard.speech import translation
    p, _ = panel
    s = p.speech
    if s.module is None:
        pytest.skip("no live-voice add-on in this copy")
    mod = dataclasses.replace(s.module, path=tmp_path / "live-voice")
    (mod.path / ".venv" / "Scripts").mkdir(parents=True)
    (mod.path / ".venv" / "Scripts" / "python.exe").write_bytes(b"x")
    (mod.path / "helper.py").write_text("")
    hub = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    whisper = hub / "models--Systran--faster-whisper-base.en"
    other = hub / "models--someone--else"
    for d in (whisper, other):
        d.mkdir(parents=True)
    d = translation.model_dir(s.langs[0])
    (d / "model").mkdir(parents=True)
    (d / "model" / "model.bin").write_bytes(b"x")
    (d / "sentencepiece.model").write_bytes(b"x")
    s.module = mod
    s.installs._refresh_module()
    assert s.installs.b_install.isHidden() and not s.installs.b_remove.isHidden()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    s.installs.b_remove.click()                       # asks, then "Removing…"
    process_events(qapp, lambda: not (mod.path / ".venv").exists() and not d.exists())
    assert not whisper.exists() and other.exists()    # only our models leave the cache
    assert (mod.path / "helper.py").exists()          # the add-on itself stays
    process_events(qapp, lambda: not s.installs.b_install.isHidden())
    assert s.installs.b_remove.isHidden()
    (d / "model").mkdir(parents=True)                 # a language without recognition:
    (d / "model" / "model.bin").write_bytes(b"x")     # still something to remove
    (d / "sentencepiece.model").write_bytes(b"x")
    s._fill_langs()
    assert not s.installs.b_remove.isHidden()


def test_voice_installed_in_windows_settings_is_found_on_return(panel, qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDesktopServices
    from soundboard.speech import translation
    p, _ = panel
    s = p.speech
    assert process_events(qapp, lambda: not s.installs._loading())  # the first voice load
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("ja"))
    d = translation.model_dir(s._lang())
    (d / "model").mkdir(parents=True)
    (d / "model" / "model.bin").write_bytes(b"x")
    (d / "sentencepiece.model").write_bytes(b"x")
    tts_ = s.ctl.tts
    tts_.voices, tts_.voice_langs = ["Microsoft Zira Desktop"], {"Microsoft Zira Desktop": "en-US"}
    s._fill_langs()
    assert not s.installs.b_voices.isHidden() and not s.installs.b_voices_check.isHidden()
    assert "Add-ons" not in s.lbl_tr.text()
    s.installs._app_state(Qt.ApplicationActive)  # not sent to settings: no rescan
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    s.installs.b_voices.click()
    assert opened and s.installs._voice_wait

    def installed(self):
        self.voices = ["Microsoft Zira Desktop", "Microsoft Haruka Desktop"]
        self.voice_langs = {"Microsoft Zira Desktop": "en-US",
                            "Microsoft Haruka Desktop": "ja-JP"}
        return self.voices
    monkeypatch.setattr(tts.SapiTTS, "refresh", installed)
    s.installs._app_state(Qt.ApplicationActive)  # back from settings: looks again by itself
    assert process_events(qapp, lambda: sp_who(s, "Haruka"))
    assert s.installs.b_voices.isHidden() and s.installs.b_voices_check.isHidden()
    assert not s.installs._voice_wait
    assert s.installs.b_voice_install.isHidden()


def _japanese_without_a_voice(s, qapp):
    """Japanese (no voice of its own yet) downloaded, and no Windows voice for it."""
    from soundboard.speech import translation
    assert process_events(qapp, lambda: not s.installs._loading())
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("ja"))
    d = translation.model_dir(s._lang())
    (d / "model").mkdir(parents=True)
    (d / "model" / "model.bin").write_bytes(b"x")
    (d / "sentencepiece.model").write_bytes(b"x")
    s.ctl.tts.voices = ["Microsoft Zira Desktop"]
    s.ctl.tts.voice_langs = {"Microsoft Zira Desktop": "en-US"}
    s._fill_langs()


def _haruka_arrives(monkeypatch):
    def installed(self):
        self.voices = ["Microsoft Zira Desktop", "Microsoft Haruka"]
        self.voice_langs = {"Microsoft Zira Desktop": "en-US", "Microsoft Haruka": "ja-JP"}
        return self.voices
    monkeypatch.setattr(tts.SapiTTS, "refresh", installed)


def test_one_click_voice_install_then_its_picked_up(panel, qapp, monkeypatch):
    import threading
    from soundboard.speech import winvoices
    p, _ = panel
    s = p.speech
    _japanese_without_a_voice(s, qapp)
    assert not s.installs.b_voice_install.isHidden()
    assert "Japanese voice" in s.installs.b_voice_install.text()
    assert s.installs._voice_timer.isActive()      # watching for it to turn up
    go = threading.Event()
    asked = []
    monkeypatch.setattr(winvoices, "install", lambda lang: (asked.append(lang), go.wait(5),
                                                            "ok")[-1])
    _haruka_arrives(monkeypatch)
    s.installs.b_voice_install.click()
    from soundboard.ui.kit import busy
    assert busy.is_busy(s.installs.b_voice_install) and "Installing" in s.lbl_tr.text()
    s.installs.b_voice_install.click()             # a second click does nothing
    go.set()
    assert process_events(qapp, lambda: sp_who(s, "Haruka"))
    assert asked == ["ja"]
    assert s.installs.b_voice_install.isHidden() and not s.installs._voice_timer.isActive()


def test_voice_install_cancelled_or_failed_says_so(panel, qapp, monkeypatch):
    from soundboard.speech import winvoices
    p, _ = panel
    s = p.speech
    _japanese_without_a_voice(s, qapp)

    def cancel(lang):
        raise winvoices.Cancelled()
    monkeypatch.setattr(winvoices, "install", cancel)
    s.installs.b_voice_install.click()
    assert process_events(qapp, lambda: "permission prompt was closed" in s.lbl_tr.text())
    assert s.installs.b_voice_install.isEnabled() and not s.installs.b_voices.isHidden()

    def fail(lang):
        raise RuntimeError("0x800f0954")
    monkeypatch.setattr(winvoices, "install", fail)
    s.installs.b_voice_install.click()
    assert process_events(qapp, lambda: "0x800f0954" in s.lbl_tr.text())
    assert s.installs.b_voice_install.isEnabled()


def test_new_voice_is_used_mid_talk_without_a_restart(panel, qapp, monkeypatch):
    from soundboard.speech import winvoices
    p, _ = panel
    s = p.speech
    _japanese_without_a_voice(s, qapp)
    monkeypatch.setattr(s.ctl, "start_live", lambda mod, args=(): None)
    monkeypatch.setattr(type(s.ctl), "live", property(lambda self: True))
    s.livevoice._live_args()                       # translating, as it starts
    assert s.ctl.live_voice is None                # nothing speaks Japanese yet
    old = frozenset({"MSTTS_V110_enUS_ZiraM"})
    s._voice_fp = old
    monkeypatch.setattr(winvoices, "fingerprint", lambda: old)
    s.installs._poll_voices()                      # nothing changed: no reload
    assert not s.installs._loading()
    _haruka_arrives(monkeypatch)
    monkeypatch.setattr(winvoices, "fingerprint",
                        lambda: old | {"MSTTS_V110_jaJP_HarukaM"})
    s.installs._poll_voices()
    assert process_events(qapp, lambda: s.ctl.live_voice == "Microsoft Haruka")
    assert "Haruka speaks" in s.livevoice.lbl_state.text()


def test_update_shows_progress_and_blocks_a_second_install(panel, qapp, monkeypatch):
    from soundboard.core import applog
    from soundboard.addons import modules as mods
    p, _ = panel
    s = p.speech
    if s.module is None:
        pytest.skip("no live-voice add-on in this checkout")
    started = []

    def boom(info, on_line):
        started.append(info)
        on_line("> pip install")
        raise OSError("disk full")

    monkeypatch.setattr(mods, "install", boom)
    reported = []
    monkeypatch.setattr(applog, "report", lambda **k: reported.append(k))
    s.installs._install()
    from soundboard.ui.kit import busy
    assert busy.is_busy(s.installs.b_update) and busy.is_busy(s.installs.b_install)
    s.installs._install()                          # a double-click: still one pip
    assert process_events(qapp, lambda: not busy.is_busy(s.installs.b_update))
    from soundboard.ui.kit import toast
    [t] = [t for t in toast.shown(s) if "disk full" in t.words()]
    assert len(started) == 1 and t.kind == "error" and "again" in t.words()
    assert s.installs.b_update.text() == "Update speech recognition"
    assert reported == []   # a full disk is said on the card, not shown as a crash


def test_no_update_button_without_the_addon(panel):
    p, _ = panel
    s = p.speech
    s.module = None
    s.installs._refresh_module()
    assert s.installs.b_update.isHidden()
    s.installs._install()                          # nothing to install: no thread, no crash
    assert not s.installs._installing


def test_a_live_voice_that_cant_load_turns_the_button_back_off(panel):
    p, _ = panel
    s = p.speech
    s.livevoice._set_live_ui(True, "starting…")
    s.livevoice._on_event({"type": "error", "text": "no model"})
    s.livevoice._on_event({"type": "stopped", "text": "no model"})
    assert not s.livevoice.b_live.isChecked() and "no model" in s.livevoice.lbl_state.text()
    assert s.installs.b_update.isEnabled()
    # a "stopped" with no words keeps the helper's own reason (live and translating)
    s.livevoice._set_live_ui(True, "starting…")
    s.livevoice._on_event({"type": "error", "text": "out of memory"})
    s.livevoice._on_event({"type": "stopped", "text": ""})
    assert "out of memory" in s.livevoice.lbl_state.text()
    s.livevoice.bg_for = "ai"
    s.livevoice._on_event({"type": "error", "text": "no translation"})
    s.livevoice._on_event({"type": "stopped", "text": ""})
    assert "no translation" in s.livevoice.lbl_bg.text()


@pytest.mark.parametrize("fx, speech", [
    ({"effects": None}, {}),
    ({"effects": {"pitch": None, "echo": [1, 2]}}, {}),
    ({"effects": {"pitch": {"on": True, "semitones": float("nan")}}}, {}),
    ([1, 2], None),
    ({"enabled": "yes", "preset": ["x"]}, {}),
    ({}, {"rate": None, "gain": "loud", "mute_real_voice": None, "voice": None,
          "language": None, "model": None, "translate": None}),
    ({}, {"rate": 99, "gain": float("inf")}),
    ({}, [1, 2]),
])
def test_damaged_saved_settings_still_open_the_tab(qapp, monkeypatch, fx, speech):
    # a hand-edited config or an old backup used to stop the app starting at all
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), fx, speech)
    try:
        assert process_events(qapp, lambda: p.speech.cb_voice.isEnabled())
        p.speech._settings_edited()
        assert -10 <= p.controller.speaker.rate <= 10 and 0 <= p.controller.gain <= 4
        spec = p.fx.spec()
        assert spec["preset"] in {"Custom", *voicefx.PRESETS}
        p.chain.configure({**spec, "enabled": True})
        p.chain.process(np.zeros((480, 2), np.float32), 48000)
    finally:
        p.shutdown()
        p.deleteLater()


def test_a_saved_voice_that_was_uninstalled_falls_back_to_the_default(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {}, {"voice": "Microsoft Gone Desktop"})
    try:
        s = p.speech
        assert process_events(qapp, lambda: s.cb_voice.isEnabled())
        assert s.cb_voice.currentData() == ""                  # shows "Windows default"
        assert p.controller.speaker.voice == ""                # and speaks in it
    finally:
        p.shutdown()
        p.deleteLater()


@pytest.mark.parametrize("q", [voicefx.Param("k", "K", 1, 1, 1),
                               voicefx.Param("k", "K", 0, 1, 0, "", 2)])
def test_a_slider_with_no_room_to_move_doesnt_divide_by_zero(qapp, q):
    from soundboard.ui.voice.voicefxpanel import ParamSlider
    s = ParamSlider(q, q.default)
    s.set_value(float("nan"))
    assert s.steps >= 1 and s.value() == q.lo


def test_an_add_on_with_a_bad_slider_is_reported_not_fatal(qapp, app_dir, monkeypatch):
    d = app_dir / "modules" / "stuck"
    d.mkdir(parents=True)
    (d / "module.json").write_text('{"id": "stuck", "kind": "effects", "entry": "fx.py"}',
                                   encoding="utf-8")
    (d / "fx.py").write_text(
        "def register(api):\n"
        "    class E(api.Effect):\n"
        "        type, name = 'stuck.e', 'Stuck'\n"
        "        params = (api.Param('k', 'K', 1, 1, 1),)\n"
        "        def run(self, x, rate):\n"
        "            return x\n"
        "    api.register_effect(E)\n", encoding="utf-8")
    monkeypatch.setattr(voicefx, "REGISTRY", dict(voicefx.REGISTRY))
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {}, {})
    try:
        m = next(m for m in p.modules if m.id == "stuck")
        assert "lo < hi" in m.error and "stuck.e" not in p.fx.rows
    finally:
        p.shutdown()
        p.deleteLater()


def test_picking_a_preset_keeps_my_own_mix(panel):
    p, _ = panel
    p.fx.pick("Chipmunk")
    row = p.fx.rows["pitch"]
    row.sliders[0].slider.setValue(row.sliders[0].slider.value() - 3)   # my own mix
    mine = p.fx.spec()["effects"]
    p.fx.pick("Robot")                          # a preset overwrites Fine-tune...
    assert p.fx.spec()["custom"] == mine
    p.fx.pick("Custom")                         # ...and My own mix brings it back
    assert p.fx.preset == "Custom" and p.fx.spec()["effects"] == mine


def test_nudging_a_preset_doesnt_replace_my_own_mix(panel):
    """Own mix made, Robot picked, a slider nudged (shows as Custom), then Ghost: the
    mix you made is still "My own mix", not the nudged Robot."""
    p, _ = panel
    p.fx.pick("Chipmunk")
    row = p.fx.rows["pitch"]
    row.sliders[0].slider.setValue(row.sliders[0].slider.value() - 3)
    mine = p.fx.spec()["effects"]
    p.fx.pick("Robot")
    robot = p.fx.rows[next(t for t in voicefx.PRESETS["Robot"])]
    robot.sliders[0].slider.setValue(robot.sliders[0].slider.value() + 2)   # a nudge
    assert p.fx.preset == "Custom" and p.fx.spec()["custom"] == mine
    p.fx.pick("Ghost")
    assert p.fx.spec()["custom"] == mine
    p.fx.pick("Custom")
    assert p.fx.spec()["effects"] == mine


def test_my_own_mix_is_kept_across_restarts(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicepanel import VoicePanel
    mix = {"pitch": {"on": True, "semitones": 3.0}}
    p = VoicePanel(FakeEngine(), {"enabled": True, "preset": "Robot", "effects": {},
                                  "custom": mix}, {})
    try:
        p.fx.pick("Custom")
        assert p.fx.spec()["effects"]["pitch"]["semitones"] == pytest.approx(3.0)
    finally:
        p.shutdown()
        p.deleteLater()


def test_voices_as_a_list(qapp, monkeypatch):
    """The list view: a small picture beside each name, shorter rows, the star kept."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from PySide6.QtWidgets import QWidget

    from soundboard.ui.voice.voicefxpanel import LIST_MIN_W, VoiceFxPanel
    holder = QWidget()
    fx = VoiceFxPanel({})
    fx.setParent(holder)
    holder.show()
    fx.setGeometry(0, 0, 1200, 1400)
    qapp.processEvents()
    tile = next(iter(fx._tile.values()))
    card_h = tile.height()
    fx.view_toggle.buttons["list"].click()
    qapp.processEvents()
    assert fx.view_toggle.view() == "list" and tile.listed
    assert tile.height() < card_h and tile.width() >= LIST_MIN_W
    assert tile.star.geometry().right() <= tile.width()
    tile.grab()   # paints its own row without trouble
    fx.set_view("grid")
    qapp.processEvents()
    assert not tile.listed and fx.view_toggle.view() == "grid"


def test_voice_tiles_reflow_in_a_narrow_window(qapp, monkeypatch):
    """Voice cards: as many a row as the width holds, down to one; never off the side."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from PySide6.QtWidgets import QWidget

    from soundboard.ui.voice.voicefxpanel import MAX_COLS, VoiceFxPanel
    holder = QWidget()                 # inside the tab, it gets the width there is
    fx = VoiceFxPanel({})
    fx.setParent(holder)
    holder.show()
    fx.setGeometry(0, 0, 1600, 600)
    wide = fx._tile_cols
    assert 3 < wide <= MAX_COLS
    for width in (420, 260, 100):
        fx.setGeometry(0, 0, width, 1200)
        qapp.processEvents()
        assert fx._tile_cols < wide and fx._tile_cols >= 1
        if width >= 260:
            assert max(b.geometry().right() for b in fx.tiles.buttons()) <= fx.width()
    assert fx._tile_cols == 1
    fx.setGeometry(0, 0, 1600, 600)
    assert fx._tile_cols == wide
    holder.hide()


def test_voice_settings_never_wait_on_a_line_being_spoken(panel, monkeypatch):
    """Dragging the voice volume (or any voice setting) while a translated line is
    being synthesized mustn't wait on the speech engine: the UI thread never takes
    SapiTTS's lock or waits on the Speaker (a report of the window going "Not
    Responding" mid-line; this pins down that the settings path stays clear)."""
    import threading
    import time

    p, _ = panel
    s = p.speech
    ctl = s.ctl
    gate, busy = threading.Event(), threading.Event()

    def stuck_synth(text, voice="", rate=0):
        with ctl.tts._lock:            # as the real one holds it for the whole line
            busy.set()
            gate.wait(10)
        return np.zeros(0, np.float32), tts.TTS_RATE

    monkeypatch.setattr(ctl.tts, "synth", stuck_synth)
    monkeypatch.setattr(type(ctl), "live", property(lambda self: True))
    ctl.live_voice = "Microsoft Huihui Desktop"
    try:
        ctl.speaker.say("你好", ctl.live_voice)
        assert busy.wait(5)
        saved = []
        s.changed.connect(saved.append)
        worst = 0.0
        edits = [lambda v=v: s.sl_rate.setValue(v) for v in range(-10, 11)]
        edits += [lambda: s.sl_rate.setValue(3), lambda: s.chk_mute.toggle(),
                  lambda: s.cb_voice.setCurrentIndex(s.cb_voice.count() - 1),
                  lambda: s.cb_lang.setCurrentIndex(s.cb_lang.findData("zh")),
                  lambda: s.ed_lang.editingFinished.emit()]
        for edit in edits:
            t = time.monotonic()
            edit()
            worst = max(worst, time.monotonic() - t)
        assert worst < 0.5, f"a settings edit waited {worst:.1f}s on the speech engine"
        assert not gate.is_set() and ctl.tts._lock.locked()   # still mid-line throughout
        assert ctl.speaker.rate == 3
    finally:
        gate.set()


# ---------------------------------------------------------------- random, saved voices

def _ask(monkeypatch, *answers):
    """QInputDialog.getText answers, in order (None = Cancel)."""
    from PySide6.QtWidgets import QInputDialog
    left = list(answers)
    asked = []

    def get_text(parent, title, label, mode, text):
        asked.append(text)
        a = left.pop(0)
        return ("", False) if a is None else (a, True)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(get_text))
    return asked


def _grid_order(fx):
    g = fx._tile_grid
    return [w.accessibleName() for w in sorted((g.itemAt(i).widget() for i in range(g.count())),
                                     key=lambda w: g.getItemPosition(g.indexOf(w))[:2])]


def test_random_voice_opens_fine_tune_with_what_it_set_lit_up(panel):
    import random
    p, _ = panel
    assert not p.fx.dlg.isVisible()
    p.fx.btn_random.click()                  # the dice is in Edit voice
    assert p.fx.dlg.isVisible() and p.fx.preset == "Custom"
    p.fx.randomize(random.Random(3))
    on = {t for t, r in p.fx.rows.items() if r.chk.isChecked()}
    lit = {t for t, r in p.fx.rows.items() if r.is_fresh()}
    assert lit == on and "pitch" in lit
    p.fx.pick("Robot")                       # gone as soon as you move on...
    assert not any(r.is_fresh() for r in p.fx.rows.values())
    p.fx.randomize(random.Random(4))
    p.fx._fresh_timer.timeout.emit()         # ...or after a few seconds
    assert not any(r.is_fresh() for r in p.fx.rows.values())


def test_my_own_mix_is_the_last_tile_and_voices_have_pictures(panel):
    from soundboard.ui.voice import art
    p, _ = panel
    order = _grid_order(p.fx)
    assert order[-2:] == ["My own mix", "Random voice"]   # the die goes after the last card
    rt = p.fx.random_tile
    assert not rt.isCheckable() and rt not in p.fx.tiles.buttons() and not rt.star.isVisibleTo(rt)
    assert p.fx.btn_random.window() is p.fx.dlg     # Randomize lives in Edit voice
    assert not p.fx.btn_random.icon().isNull()
    if art.exists(art.voice_key("Robot")):          # the repo's pictures are used
        assert p.fx._tile["Robot"].property("art")


def test_save_as_a_voice_makes_a_tile_that_comes_back(panel, monkeypatch, qapp):
    p, _ = panel
    p.fx.pick("Chipmunk")
    row = p.fx.rows["pitch"]
    row.sliders[0].slider.setValue(row.sliders[0].slider.value() - 3)
    mine = p.fx.spec()["effects"]
    asked = _ask(monkeypatch, "Squeaky")
    p.fx.btn_save.click()
    assert asked == ["My voice"]
    assert p.fx.preset == "Squeaky" and p.fx._tile["Squeaky"].isChecked()
    assert _grid_order(p.fx)[-3:] == ["My own mix", "Squeaky", "Random voice"]
    assert p.fx.spec()["custom"] == mine           # "My own mix" is still that mix
    p.fx.pick("Robot")
    p.fx.pick("Squeaky")
    assert p.fx.spec()["effects"] == mine
    # a restart: the tile is there and still the one that's on
    from soundboard.ui.voice.voicepanel import VoiceFxPanel
    again = VoiceFxPanel(p.fx.spec())
    assert again.preset == "Squeaky" and "Squeaky" in again._tile
    again.deleteLater()


def test_saving_again_offers_the_voice_you_started_from(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    p, _ = panel
    _ask(monkeypatch, "Squeaky")
    p.fx.save_voice()
    row = p.fx.rows["pitch"]
    row.chk.setChecked(True)                       # a nudge: shows as Custom
    assert p.fx.preset == "Custom"
    asked = _ask(monkeypatch, "Squeaky")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)   # replace
    p.fx.save_voice()
    assert asked == ["Squeaky"] and list(p.fx.store.voices) == ["Squeaky"]
    assert p.fx.store.voices["Squeaky"]["pitch"]["on"] is True


def test_built_in_names_are_taken(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    p, _ = panel
    said = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: said.append(a[2]))
    _ask(monkeypatch, "robot", "Random voice", None)
    p.fx.save_voice()
    assert len(said) == 2 and not p.fx.store.voices


def test_delete_a_saved_voice_then_undo_or_bring_it_back(panel, monkeypatch):
    p, _ = panel
    _ask(monkeypatch, "One", "Two")
    p.fx.save_voice()
    p.fx.save_voice()
    assert p.fx.preset == "Two"
    sound = p.fx.spec()["effects"]
    p.fx.delete_voice("One")
    assert "One" not in p.fx._tile and p.fx.undo_bar.active()
    p.fx.undo_bar.undo()
    assert list(p.fx.store.voices) == ["One", "Two"]
    p.fx.delete_voice("Two")                       # the one that's on: you still sound
    assert p.fx.preset == "Custom" and p.fx.spec()["effects"] == sound   # the same
    p.fx.undo_bar.undo()
    assert p.fx.preset == "Two"
    # past Undo, "Recently deleted" still has it
    p.fx.delete_voice("One")
    p.fx.undo_bar.finish()
    assert not p.fx.btn_bin.isHidden()
    from soundboard.ui.sounds import deleted
    seen = []

    def fake_exec(dlg):
        seen.append(dlg.list.item(0).text())
        dlg.list.setCurrentRow(0)
        dlg.bring_back()
    monkeypatch.setattr(deleted.DeletedDialog, "exec", fake_exec)
    p.fx.show_deleted()
    assert seen[0].startswith("One") and "One" in p.fx._tile
    assert list(p.fx.store.voices) == ["One", "Two"]   # in its old place, as Undo does
    assert p.fx.btn_bin.isHidden()


def test_saving_a_voice_says_its_name_on_a_card(panel, monkeypatch):
    """The button's "✓ Saved" is gone in a second: a card says it stuck, and as what."""
    from tests.conftest import said
    p, _ = panel
    _ask(monkeypatch, "Squeaky")
    p.fx.save_voice()
    assert said(p) == "Saved “Squeaky”."
    assert p.fx.btn_save.text() == "✓ Saved"


def test_say_with_an_empty_box_says_to_type_a_line(panel):
    p, _ = panel
    p.show()
    sp = p.speech
    sp.ed.setText("   ")
    sp.b_say.click()
    assert sp.b_say.text() == "Type a line first" and not sp._last_said
    assert sp.ed.hasFocus() or p.window().focusWidget() is sp.ed


def test_rename_a_saved_voice(panel, monkeypatch):
    p, _ = panel
    _ask(monkeypatch, "One", "Better name")
    p.fx.save_voice()
    p.fx.rename_voice("One")
    assert list(p.fx.store.voices) == ["Better name"] and p.fx.preset == "Better name"
    p.fx.btn_power.setChecked(True)
    assert p.fx._tile["Better name"].isChecked()


def test_tiles_reflow_with_saved_voices(qapp, app_dir, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from soundboard.mic import savedvoices
    from soundboard.ui.voice.voicepanel import VoiceFxPanel
    store = savedvoices.Store()
    for n in ("A", "B"):
        store.put(n, {})
    holder = QWidget()
    fx = VoiceFxPanel({}, store)
    fx.setParent(holder)
    holder.show()
    fx.setGeometry(0, 0, 260, 1600)
    qapp.processEvents()
    assert _grid_order(fx)[-4:] == ["My own mix", "A", "B", "Random voice"]
    assert max(b.geometry().right() for b in fx.tiles.buttons()) <= fx.width()
    holder.hide()


def test_edit_voice_has_no_mic_clean_up_card_clean_mic_does_that(qapp, monkeypatch):
    """The old Clean up my mic effect is gone (Clean mic, the Voice tab's first tab,
    does the job): settings that still have it open without it and never run it."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicepanel import VoicePanel
    old = {"cleanup": {"on": True, "gate": 0.6, "hiss": 0.5}, "robot": {"on": True}}
    p = VoicePanel(FakeEngine(), {"enabled": True, "preset": "Custom", "effects": old,
                                  "custom": old}, {})
    try:
        assert "cleanup" not in p.fx.rows and "cleanup" not in voicefx.REGISTRY
        hero = p.fx.hero_box
        assert [hero.itemAt(i).widget() for i in range(hero.count())] == [p.fx.rows["pitch"]]
        assert "cleanup" not in p.fx.spec()["effects"]
        p.chain.process(np.zeros((32, 2), np.float32), 48000)
        assert [e.type for e in p.chain._effects] == ["robot"]
    finally:
        p.shutdown()
        p.deleteLater()


def test_moving_a_pitch_slider_switches_pitch_on(panel):
    p, _ = panel
    row = p.fx.rows["pitch"]
    assert not row.chk.isChecked() and not row.body.isHidden()   # always in view
    size = next(s for s in row.sliders if s.q.key == "size")
    size.slider.setValue(size.slider.value() + 4)
    spec = p.fx.spec()
    assert spec["enabled"] and spec["effects"]["pitch"]["on"]
    assert spec["effects"]["pitch"]["size"] == 2


def test_delay_shows_what_the_effects_and_devices_add(panel):
    p, _ = panel
    fx = p.fx
    assert fx.delay.isHidden()                    # off: no delay to speak of
    fx.pick("Robot")                              # no pitch: next to nothing
    small = fx.effects_delay()
    fx.pick("Deep voice")                         # pitch + natural formants cost the most
    big = fx.effects_delay()
    assert 0 <= small < 5 and 40 < big < 100
    fx.set_device_delay(30.0)
    assert not fx.delay.isHidden() and f"{big + 30:.0f} ms" in fx.delay.text()


def test_switch_settings_and_cards_round_trip(panel):
    p, _ = panel
    p.fx.pick("Walkie-talkie")
    radio = p.fx.rows["radio"]
    squelch = next(s for s in radio.sliders if s.q.key == "squelch")
    # off in the preset: the clicks sounded like a hi-hat
    assert squelch.switch is not None and squelch.slider is None and squelch.value() == 0
    squelch.switch.setChecked(True)
    assert p.fx.spec()["effects"]["radio"]["squelch"] == 1
    radio.reset()
    assert p.fx.spec()["effects"]["radio"]["low"] == voicefx.defaults("radio")["low"]


def test_a_slider_step_rebuilds_the_chain_once_and_redraws_the_tab_only_on_a_flip(
        panel, monkeypatch):
    p, _ = panel
    p.chain.process(np.zeros((480, 2), np.float32), 48000)   # a rate: configure builds
    sent = []
    p.active_changed.connect(sent.append)
    p.fx.pick("Robot")
    assert sent == [True]
    rebuilds = []
    real = voicefx.VoiceChain._rebuild
    monkeypatch.setattr(voicefx.VoiceChain, "_rebuild",
                        lambda self, rate: (rebuilds.append(rate), real(self, rate)))
    gen = p.chain._gen
    s = p.fx.rows["robot"].sliders[0].slider
    for v in range(s.minimum(), s.minimum() + 10):
        s.setValue(v)
    # one new spec a step (was 2 rebuilds + a send a step); the mic's next block builds it
    assert p.chain._gen - gen == 10 and sent == [True] and not rebuilds
    p.chain.process(np.zeros((480, 2), np.float32), 48000)
    assert rebuilds == [48000]
    p.chain.errors["robot"] = "boom"                # a bypassed effect: another go
    s.setValue(s.value() + 1)
    assert not p.chain.errors and p.chain._gen - gen == 11
    p.fx.btn_power.setChecked(False)
    assert sent == [True, False]


def test_effects_that_never_delay_the_voice_arent_built_to_ask(panel, monkeypatch):
    p, _ = panel
    built = []
    for etype, cls in voicefx.REGISTRY.items():
        real = cls.__init__
        monkeypatch.setattr(cls, "__init__", lambda self, *a, _r=real, _t=etype, **k: (
            built.append(_t), _r(self, *a, **k))[1])
    p.fx.pick("Autotune")               # no mic yet: only the delay readout builds any
    assert p.fx.effects_delay() > 0 and "pitch" in built
    assert "robot" not in built         # its latency() is the base one: always 0
    assert all(voicefx.REGISTRY[t].latency is not voicefx.Effect.latency for t in built)


def test_add_ons_refresh_scans_the_disk_off_the_ui_thread(panel, qapp, monkeypatch):
    import threading

    from soundboard.ui.kit import busy
    from soundboard.ui.voice import voicepanel as vp
    p, _ = panel
    real, where = vp.mods.discover, []
    monkeypatch.setattr(vp.mods, "discover",
                        lambda *a: (where.append(threading.current_thread()), real(*a))[1])
    b = p.addons.b_refresh
    b.click()
    assert busy.is_busy(b)
    b.click()                           # a double click doesn't scan twice
    assert process_events(qapp, lambda: not busy.is_busy(b))
    assert len(where) == 1 and where[0] is not threading.main_thread()
    assert [m.id for m in p.modules] == [m.id for m in real()]


def test_add_ons_refresh_lets_go_of_the_button_when_the_scan_fails(panel, monkeypatch):
    from soundboard.ui.kit import busy
    p, _ = panel

    def boom(*a):
        raise OSError("disk gone")
    monkeypatch.setattr(p, "rescan_modules", boom)
    b = p.addons.b_refresh
    busy.hold_until(b, "Checking…", p.addons.shown)   # what Refresh does, minus the worker
    assert busy.is_busy(b)
    with pytest.raises(OSError):
        p._apply_scan(None, None)
    assert not busy.is_busy(b)


def test_resizing_within_one_column_count_does_no_layout_passes(panel, monkeypatch):
    """A drag-resize sends one resize per pixel: the voices are only placed again when
    the number a row changes."""
    p, _ = panel
    fx = p.fx
    fx._fit_width(1100)
    placed = []
    real = type(fx)._place_tiles
    monkeypatch.setattr(type(fx), "_place_tiles",
                        lambda self: (placed.append(self._tile_cols), real(self))[1])
    cols = fx._tile_cols
    w = 1100
    while fx._tile_cols == cols:          # down to the next column count, pixel by pixel
        w -= 1
        fx._fit_width(w)
    assert placed == [cols - 1]
    for w2 in range(w, w - 20, -1):       # within that count: nothing placed again
        fx._fit_width(w2)
    assert placed == [cols - 1]


def test_a_slider_step_lays_nothing_out_and_its_value_always_fits(panel, qapp):
    """The value next to a slider is as wide as its widest value: one that changed
    width laid out the card, its neighbours and the page again on every step."""
    from PySide6.QtCore import QEvent, QObject
    p, _ = panel
    p.resize(1100, 800)
    p.show()
    p.fx.open_tweak()
    p.fx.pick("Robot")
    qapp.processEvents()
    row = p.fx.rows["robot"]
    s = row.sliders[0]
    s.slider.setValue(s.slider.maximum())   # the first edit: Robot -> My own mix
    qapp.processEvents()
    hint = s.val.sizeHint()
    fm = s.val.fontMetrics()

    seen = []

    class Layouts(QObject):
        def eventFilter(self, o, e):
            if e.type() == QEvent.LayoutRequest and o in (s, row, row.body):
                seen.append(o)
            return False
    watch = Layouts()
    qapp.installEventFilter(watch)
    try:
        for v in range(s.slider.minimum(), s.slider.maximum() + 1, 7):
            s.slider.setValue(v)
            qapp.processEvents()
            assert s.val.sizeHint() == hint
            assert fm.horizontalAdvance(s.val.text()) <= s.val.contentsRect().width()
    finally:
        qapp.removeEventFilter(watch)
    assert seen == []   # was the slider's row, its card and up the page, every step
    assert s.val.text() == s.text() and s.slider.accessibleDescription() == s.text()


def test_every_value_a_slider_shows_fits_its_label(panel):
    from soundboard.ui.voice.voicefxpanel import param_text
    p, _ = panel
    p.show()
    for row in p.fx.rows.values():
        for s in row.sliders:
            if s.slider is None:
                continue
            s.val.ensurePolished()
            fm, room = s.val.fontMetrics(), s.val.sizeHint().width()
            for i in range(s.steps + 1):
                v = s.q.lo + (s.q.hi - s.q.lo) * i / s.steps
                assert fm.horizontalAdvance(param_text(s.q, v)) <= room, (s.q.key, v)


def test_every_tab_thats_on_lights_up_at_once(panel, monkeypatch):
    """The AI voice on and another language spoken for it: both tabs light up, not
    just one (Languages lit only while the computer voice spoke)."""
    p, _ = panel
    monkeypatch.setattr("soundboard.speech.spoken.heard", lambda: True)
    monkeypatch.setattr(type(p.speech), "translating", lambda self: self._lang())
    monkeypatch.setattr(p.ai, "is_on", lambda: True)
    p.speech.cb_lang.blockSignals(True)
    p.speech.cb_lang.setCurrentIndex(p.speech.cb_lang.findData("zh"))
    p.speech.cb_lang.blockSignals(False)
    p.fx.pick("Robot")
    p._update_heads()
    assert not p.speech.livevoice.b_live.isChecked()
    assert all(p._tabs[k].property("live") for k in ("fx", "ai", "speak"))
    p.speech.stop_translating()
    p._update_heads()
    assert not p._tabs["speak"].property("live") and p._tabs["ai"].property("live")


def test_a_tab_thats_on_says_so_from_another_tab(panel):
    """The voice changer on, another tab showing: its tab still says it's on."""
    p, _ = panel
    p.show_tab("ai")
    assert not p._tabs["fx"].property("live")
    p.fx.pick("Robot")
    assert p._tabs["fx"].property("live") and not p._tabs["ai"].property("live")
    p.fx.btn_power.setChecked(False)
    assert not p._tabs["fx"].property("live")


def test_the_voice_thats_on_speaks_the_language_picked(panel, monkeypatch):
    """Speak in belongs to the whole tab: the AI voice gets the translated lines,
    else the voice changer (real mic muted), else the language's own voice: picking a
    language is enough, there's no Start to press."""
    from types import SimpleNamespace
    p, _ = panel
    sp = p.speech
    asked = []
    monkeypatch.setattr(sp.livevoice, "translate_for", asked.append)
    p._sync_translate()
    assert asked[-1] == "" and sp.ctl.dub is None             # English: nothing to do
    de = SimpleNamespace(language="de", language_name="German", voice={"name": "Thorsten"})
    monkeypatch.setattr(sp, "translating", lambda: de)
    monkeypatch.setattr(sp, "_lang_on", lambda: de)
    monkeypatch.setattr(sp.ctl.tts, "voice_for", lambda lang, prefer="": "piper:de")
    sp.voices_need = ""                              # the AI voices add-on can read it
    p._sync_translate()
    assert asked[-1] == "read" and sp.ctl.dub is None
    assert sp.lbl_who.text() == "Thorsten, the German voice. It's on: just talk."
    assert p.is_active()                      # it speaks for you: your real voice is muted
    p.fx.pick("Robot")
    assert asked[-1] == "fx" and sp.ctl.fx_always and sp.ctl.dub is None
    assert "German, a few seconds late" in p._states["fx"].text()
    monkeypatch.setattr(p.ai, "is_on", lambda: True)
    p._sync_translate()
    assert asked[-1] == "ai" and sp.ctl.dub is p.ai_controller and p.ai_controller.dub_on


def sp_who(sp, voice: str) -> bool:
    """Said by names this voice."""
    return sp.lbl_who.text().startswith(voice + ", the ")


def _chinese_downloaded(sp):
    from types import SimpleNamespace
    from soundboard.speech import translation
    sp.module = SimpleNamespace(installed=True, broken=False, id="live")
    zh = next(m for m in sp.langs if m.language == "zh")
    d = translation.model_dir(zh)
    (d / "model").mkdir(parents=True)
    (d / "model" / "model.bin").write_bytes(b"x")
    (d / "sentencepiece.model").write_bytes(b"x")
    (d / "voice").mkdir()                              # and the voice that reads it
    (d / "voice" / translation.VOICE_FILE).write_bytes(b"x")
    (d / "voice" / (translation.VOICE_FILE + ".json")).write_text('{"dataset": "huayan"}')
    assert zh.installed
    sp.voices_need = ""                                # and the AI voices add-on reads it


def test_speak_in_is_one_list_a_voice_never_turns_it_back_on(panel, monkeypatch):
    """Chinese picked, then Don't translate, then a voice changer voice: it must stay
    English; picking Chinese again is the only way back."""
    p, _ = panel
    sp = p.speech
    _chinese_downloaded(sp)
    asked = []
    monkeypatch.setattr(sp.livevoice, "translate_for", asked.append)
    assert not sp.cb_lang.currentData()               # Don't translate by default
    saved = []
    sp.changed.connect(saved.append)
    sp.cb_lang.setCurrentIndex(sp.cb_lang.findData("zh"))
    assert sp.translating() is not None               # picked = on
    assert saved[-1]["translate_on"] and saved[-1]["translate"] == "zh"
    sp.cb_lang.setCurrentIndex(0)                     # Don't translate
    assert sp.translating() is None and sp.livevoice.lbl_bg.isHidden()
    assert not saved[-1]["translate_on"] and saved[-1]["translate"] == "zh"   # kept
    p.fx.pick("Robot")                                # a voice from another card
    assert asked[-1] == "" and not sp.ctl.fx_always
    assert "Chinese" not in p._states["fx"].text()
    assert "lang" not in p.bar.chips                  # the status bar says English too
    sp.cb_lang.setCurrentIndex(sp.cb_lang.findData("zh"))
    assert asked[-1] == "fx" and sp.ctl.fx_always
    assert "lang" in p.bar.chips


def test_said_by_names_who_speaks(panel, monkeypatch):
    """Said by names the voice others will hear: the language's own voice by its name,
    or the voice changer's voice reading it."""
    p, _ = panel
    sp = p.speech
    _chinese_downloaded(sp)
    monkeypatch.setattr(sp.livevoice, "translate_for", lambda who: None)
    monkeypatch.setattr(sp.ctl.tts, "voice_for",
                        lambda lang, prefer="": "piper:zh" if lang == "zh" else "")
    sp._refresh_translation()
    assert sp.lbl_who.text() == ""                    # no language: nobody to name
    sp.cb_lang.setCurrentIndex(sp.cb_lang.findData("zh"))
    assert sp.lbl_who.text() == "Huayan, the Chinese voice. It's on: just talk."
    assert sp.livevoice.b_live.isHidden()             # no Start: it's on already
    p.fx.pick("Robot")                                # the voice changer says it now
    assert sp.lbl_who.text().startswith("Huayan with your Robot voice changer")
    p.fx.btn_power.setChecked(False)
    assert sp_who(sp, "Huayan")



def _chinese_windows_voice(sp, monkeypatch):
    """Windows has a Chinese voice, Huihui, beside the language's own one."""
    monkeypatch.setattr(sp.livevoice, "translate_for", lambda who: None)
    tts_ = sp.ctl.tts
    monkeypatch.setattr(tts_, "voices", ["Microsoft Zira Desktop",
                                         "Microsoft Huihui Desktop", "piper:zh"])
    monkeypatch.setattr(tts_, "voice_langs", {"Microsoft Zira Desktop": "en-US",
                                              "Microsoft Huihui Desktop": "zh-CN",
                                              "piper:zh": "zh"})


@pytest.mark.parametrize("need", ["get", "update"])
def test_a_language_voice_falls_back_to_windows_without_new_ai_voices(panel, monkeypatch,
                                                                      need):
    """No AI voices add-on, or one from before the language voices (no reader.py): the
    language's own voice can't be read, so a Windows voice that speaks it reads the
    lines, Said by and the bar name that one, and the Languages cards are hidden."""
    p, _ = panel
    sp = p.speech
    _chinese_downloaded(sp)
    _chinese_windows_voice(sp, monkeypatch)
    monkeypatch.setattr(sp.ctl.tts, "languages", {"piper:zh": (None, "zh", "Huayan (Chinese)")})
    sp.voices_need = need
    sp.cb_lang.setCurrentIndex(sp.cb_lang.findData("zh"))
    sp._refresh_translation()
    zh = sp._lang_on()
    assert sp._voice_for(zh) == "Microsoft Huihui Desktop"
    assert sp_who(sp, "Huihui")
    assert p._lang_bar_name() == "Huihui"
    sp.livevoice._live_args()
    assert sp.ctl.live_voice == "Microsoft Huihui Desktop"   # never piper:zh
    assert p._language_voices() == []
    sp.voices_need = ""                                # the new add-on: its own voice
    sp._refresh_translation()
    assert sp._voice_for(zh) == "piper:zh" and sp_who(sp, "Huayan")
    assert p._lang_bar_name() == "Huayan"
    assert [v["id"] for v in p._language_voices()] == ["piper:zh"]


def test_a_language_downloaded_without_its_voice_still_speaks(panel, monkeypatch):
    """Chinese downloaded before it came with a voice: it's still downloaded, a Windows
    voice reads it, and Download the Chinese voice offers the rest."""
    import shutil
    from soundboard.speech import translation
    p, _ = panel
    sp = p.speech
    _chinese_downloaded(sp)
    zh = next(m for m in sp.langs if m.language == "zh")
    shutil.rmtree(translation.model_dir(zh) / "voice")
    _chinese_windows_voice(sp, monkeypatch)
    monkeypatch.setattr(sp.ctl.tts, "languages", {})
    sp.voices_need = ""
    assert zh.installed
    sp.cb_lang.setCurrentIndex(sp.cb_lang.findData("zh"))
    sp._refresh_translation()
    assert sp.translating() is zh
    assert sp._voice_for(zh) == "Microsoft Huihui Desktop" and sp_who(sp, "Huihui")
    assert sp.lbl_tr.text().startswith("Huihui reads Chinese for now.")
    monkeypatch.setattr(sp.ctl.tts, "voices", ["Microsoft Zira Desktop"])
    sp._refresh_translation()                          # no Chinese Windows voice either
    assert sp.lbl_who.text() == "The Chinese voice, once it's downloaded (below)."
    assert sp.installs.b_dl.text() == "Download the Chinese voice"
    monkeypatch.setattr(sp.ctl.tts, "voices", ["Microsoft Zira Desktop",
                                               "Microsoft Huihui Desktop"])
    sp._refresh_translation()
    assert not sp.installs.b_dl.isHidden()
    assert sp.installs.b_dl.text() == "Download the Chinese voice"
    assert p._lang_bar_name() == "Huihui"
    sp.livevoice._live_args()
    assert sp.ctl.live_voice == "Microsoft Huihui Desktop"

def test_speak_in_starts_off_for_a_language_saved_switched_off(qapp, monkeypatch):
    """A language saved switched off (or from before the switch) shows Don't
    translate, and is still remembered."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"voice": "Microsoft Zira Desktop", "translate": "zh"})
    try:
        sp = p.speech
        assert not sp.cb_lang.currentData() and sp.s["translate"] == "zh"
        _chinese_downloaded(sp)
        assert sp.translating() is None
        args = sp.livevoice._live_args()              # not translating
        assert "--translate" not in args
    finally:
        p.shutdown()
        p.deleteLater()


def test_speaking_another_language_goes_through_english(panel, monkeypatch):
    """The translations go from English: a Spanish speaker's line is heard straight
    into English first (Whisper's translate task), by a model that hears Spanish."""
    from soundboard import i18n
    p, _ = panel
    sp = p.speech
    _chinese_downloaded(sp)
    sp.cb_lang.setCurrentIndex(sp.cb_lang.findData("zh"))
    args = sp.livevoice._live_args()                  # English: as before
    assert args[:4] == ["--model", "base.en", "--language", "en"]
    assert "--task" not in args and "--translate" in args
    monkeypatch.setattr(i18n, "current", lambda: "es")
    args = sp.livevoice._live_args()                  # the app in Spanish: Spanish in
    assert args[:4] == ["--model", "small", "--language", "es"]
    assert args[args.index("--task") + 1] == "translate" and "--translate" in args
    monkeypatch.setattr(i18n, "current", lambda: "zh-CN")
    args = sp.livevoice._live_args()                  # said in Chinese: just spoken
    assert "--task" not in args and "--translate" not in args
    sp.ed_lang.setText("en")                          # English typed in on purpose
    sp.ed_lang.editingFinished.emit()
    assert sp.s["spoken"] == "en" and sp.livevoice._live_args()[3] == "en"


def test_speech_model_download_shows_a_bar_until_its_ready(panel):
    p, _ = panel
    sp = p.speech
    assert sp.livevoice.dl_bar.isHidden() and sp.livevoice.bg_bar.isHidden()
    sp.livevoice._on_event({"type": "download", "done": 121_450_000, "total": 485_800_000})
    assert not sp.livevoice.dl_bar.isHidden() and sp.livevoice.dl_bar.value() == 250
    assert "121 of 485 MB" in sp.livevoice.lbl_state.text()
    sp.livevoice._on_event({"type": "status", "text": "loading translation…"})  # downloaded
    assert sp.livevoice.dl_bar.isHidden()
    sp.livevoice._on_event({"type": "download", "done": 5, "total": 0})  # no size: empty bar
    assert not sp.livevoice.dl_bar.isHidden() and sp.livevoice.dl_bar.value() == 0
    sp.livevoice._set_live_ui(False, "stopped")                        # stopped by hand
    assert sp.livevoice.dl_bar.isHidden()
    sp.livevoice.bg_for = "ai"                                         # for another voice
    sp.livevoice._on_event({"type": "download", "done": 50_000_000, "total": 100_000_000})
    assert not sp.livevoice.bg_bar.isHidden() and sp.livevoice.dl_bar.isHidden()
    assert "50 of 100 MB" in sp.livevoice.lbl_bg.text()
    sp.livevoice._on_event({"type": "ready"})
    assert sp.livevoice.bg_bar.isHidden()


def test_languages_tab_hides_when_speech_recognition_cant_hear_the_app(qapp, monkeypatch):
    from soundboard import i18n
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    monkeypatch.setattr(i18n, "current", lambda: "tlh")
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}}, {"tab": "speak"})
    try:
        assert not p._tabs["speak"].isVisibleTo(p) and p.current_tab() == "fx"
        assert p._tabs["fx"].isVisibleTo(p) and p._tabs["addons"].isVisibleTo(p)
    finally:
        p.shutdown()
        p.deleteLater()


# ---------------------------------------------------------------- Edit voice window

def test_the_card_is_just_the_switch_the_voices_and_one_button(panel):
    p, _ = panel
    fx = p.fx
    on_card = [w for w in (fx.btn_power, fx.btn_tweak, *fx.tiles.buttons())]
    assert all(w.window() is not fx.dlg for w in on_card)
    for w in (fx.hero_box.parentWidget(), fx.btn_random, fx.btn_save, fx.btn_share,
              fx.btn_import, fx.btn_bin, fx.more, *fx.rows.values()):
        assert w.window() is fx.dlg
    assert not fx.dlg.isModal() and not fx.dlg.isVisible()
    fx.btn_tweak.click()
    assert fx.dlg.isVisible()
    fx.pick("Robot")                                  # the voices still work beside it
    assert fx.preset == "Robot" and fx.btn_tweak.text().endswith("on")
    fx.dlg.close()


def test_my_own_mix_opens_make_it_yours(panel):
    p, _ = panel
    p.fx.pick("Custom")
    assert p.fx.dlg.isVisible()
    p.fx.dlg.close()


def test_make_it_yours_remembers_its_size(panel, qapp):
    from soundboard.ui.voice.voicepanel import VoiceFxPanel
    p, _ = panel
    seen = []
    p.fx.changed.connect(seen.append)
    p.fx.open_tweak()
    p.fx.dlg.resize(520, 480)
    qapp.processEvents()
    assert p.fx._fx_cols == 1                         # narrow: one effect a row
    p.fx.dlg.close()
    assert seen[-1]["panel_size"] == [520, 480]
    again = VoiceFxPanel(voicefx.clean_spec(seen[-1]))
    again.open_tweak()
    assert (again.dlg.width(), again.dlg.height()) == (520, 480)
    again.dlg.close()
    again.deleteLater()


def test_copy_and_import_a_share_code(panel, monkeypatch, qapp):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QMessageBox
    p, _ = panel
    p.fx.pick("Chipmunk")
    _ask(monkeypatch, "Squeaky")
    p.fx.save_voice()
    assert p.fx.btn_share.isEnabled()                # a saved voice is on
    code = p.fx.copy_code("Squeaky")
    assert QGuiApplication.clipboard().text() == code and code.startswith("OB1-")
    sound = p.fx.spec()["effects"]
    p.fx.pick("Robot")
    assert not p.fx.btn_share.isEnabled()
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a: asked.append(a[2]) or QMessageBox.Yes)
    _ask(monkeypatch, code)
    p.fx.btn_import.click()
    # the name was taken: it comes in alongside, on, and sounding the same
    assert "Squeaky (2)" in asked[0] and p.fx.preset == "Squeaky (2)"
    assert list(p.fx.store.voices) == ["Squeaky", "Squeaky (2)"]
    assert p.fx.spec()["effects"] == sound


def test_importing_junk_says_why_and_adds_nothing(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from soundboard.ui.kit import busy
    p, _ = panel
    said = []
    monkeypatch.setattr(busy, "toast", lambda *a, **k: said.append(a[1]))
    assert p.fx.import_code("OB1-not-a-real-code") == ""
    assert said and not p.fx.store.voices
    # a built-in voice's name gets "(shared)"; saying No adds nothing
    from soundboard.mic import savedvoices
    code = savedvoices.share_code("Robot", {"robot": {"on": True}})
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.No)
    assert p.fx.import_code(code) == "" and not p.fx.store.voices
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    assert p.fx.import_code(code) == "Robot (shared)"


def test_import_with_an_empty_box_says_so_and_cancel_says_nothing(panel, monkeypatch):
    import html

    from soundboard.ui.kit import busy
    p, _ = panel
    said = []
    monkeypatch.setattr(busy, "toast", lambda *a, **k: said.append(a[1]))
    _ask(monkeypatch, "  ", None)
    p.fx.btn_import.click()             # OK with nothing pasted: it says why
    assert [html.unescape(s) for s in said] == ["There's no code there."]
    assert not p.fx.store.voices
    p.fx.btn_import.click()             # Cancel: nothing to say
    assert len(said) == 1


def test_copy_from_a_tile_with_the_window_closed_says_so(panel, monkeypatch):
    p, _ = panel
    _ask(monkeypatch, "Mine", "Other")
    p.fx.save_voice()
    p.fx.save_voice()
    p.fx.copy_code("Mine")
    from soundboard.ui.kit import toast
    [t] = [t for t in toast.shown(p.fx) if "share code" in t.text()]
    assert t.kind == "ok" and t.card.action.isHidden() and not p.fx.undo_bar.active()
    p.fx.delete_voice("Mine")                        # a real Undo has its button
    assert p.fx.undo_bar.active()


def test_make_it_yours_buttons_are_at_the_top(panel):
    fx = panel[0].fx
    tools = fx.btn_random.parentWidget()
    for b in (fx.btn_mix, fx.btn_share, fx.btn_import, fx.btn_bin):
        assert b.parentWidget() is tools                     # one row of buttons...
    assert fx.tweak.layout().indexOf(tools) == 1             # ...under the voice's name
    assert fx.btn_save.parentWidget() is fx.btn_undo.parentWidget()   # Save: by Done


def test_effect_cards_fold_and_stay_folded(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {}, {"folded": ["ai", "fx.echo"]})
    try:
        echo, radio = p.fx.rows["echo"], p.fx.rows["radio"]
        assert echo.is_folded() and echo.desc.isHidden() and not radio.is_folded()
        saved = []
        p.speech_changed.connect(saved.append)
        radio.chk.setChecked(True)
        assert not radio.body.isHidden()
        radio.arrow.click()                                  # fold it: just its title line
        assert radio.body.isHidden() and radio.desc.isHidden() and radio.chk.isChecked()
        assert saved[-1]["folded"] == ["ai", "fx.echo", "fx.radio"]
        echo.chk.setChecked(True)                            # switching it on opens it
        assert not echo.is_folded() and not echo.body.isHidden()
        assert saved[-1]["folded"] == ["ai", "fx.radio"]
        p.fx.pick("Robot")                                   # a voice pick leaves folds be
        assert radio.is_folded() and not p.fx.rows["robot"].is_folded()
    finally:
        p.shutdown()
        p.deleteLater()


def test_effect_columns_stack_without_holes(panel, qapp):
    """Two columns a tab, each card under the shorter one: no hole beside a short card,
    and the columns end close together, after a voice pick and after folding."""
    fx = panel[0].fx
    fx.open_tweak()
    fx.dlg.resize(800, 700)

    def check():
        for _ in range(3):
            qapp.processEvents()
        assert fx._fx_cols == 2
        for title in ("Character", "Room"):
            fx.more.setCurrentWidget(fx._pages[title][0])
            for _ in range(3):
                qapp.processEvents()
            cols = [[col.itemAt(i).widget() for i in range(col.count() - 1)]
                    for col in fx._pages[title][2]]
            assert sorted(len(c) for c in cols)[0] >= 2
            bottoms = []
            for col in cols:
                for a, b in zip(col, col[1:]):
                    assert b.y() - (a.y() + a.height()) == 10      # just the spacing
                bottoms.append(col[-1].y() + col[-1].height())
            tallest = max(c.height() for col in cols for c in col)
            assert abs(bottoms[0] - bottoms[1]) <= tallest          # no long empty run

    check()
    fx.pick("Robot")
    for t in ("radio", "helmet", "tone"):
        fx.rows[t].chk.setChecked(True)
    check()
    for t in ("compressor", "distortion", "shout", "chorus", "echo"):
        fx.rows[t].arrow.click()
    check()
    fx.dlg.resize(500, 700)                                   # one column
    for _ in range(3):
        qapp.processEvents()
    assert fx._fx_cols == 1
    assert all(cols[1].count() == 1 for _s, _r, cols in fx._pages.values())
    fx.dlg.close()


def test_edit_voice_has_a_tab_a_group_that_counts_whats_on(panel, qapp):
    """Edit voice was one long page: Main (pitch), then a tab a group,
    each saying how many of its effects are on; Add-ons only with an add-on effect."""
    fx = panel[0].fx
    fx.open_tweak()
    names = [fx.more.tabText(i) for i in range(fx.more.count())
             if fx.more.isTabVisible(i)]
    assert names[0] == "Main" and fx.rows["pitch"].isVisibleTo(fx.more.widget(0))
    assert [n.split("  ·  ")[0] for n in names[1:4]] == ["Change the voice", "Character",
                                                         "Room"]
    addon = any(t not in ("monk",) and r.cls.__module__.startswith("soundboard_module")
                for t, r in fx.rows.items())     # (a test may have loaded one)
    from soundboard.ui.voice.voicefxpanel import GROUPS
    assert (names[4:] == ["Add-ons"]) == addon and "monk" in dict(GROUPS)["Change the voice"]
    fx.pick("Robot")
    fx.rows["radio"].chk.setChecked(True)
    i = fx.more.indexOf(fx._pages["Character"][0])
    on = sum(fx.rows[t].chk.isChecked() for t in ("compressor", "tone", "radio",
                                                  "distortion", "shout", "helmet",
                                                  "polish"))
    assert fx.more.tabText(i) == f"Character  ·  {on} on"
    fx.dlg.close()


def _remembered(names_langs, fp):
    names = [n for n, _ in names_langs]
    return tts.remember_voices(names, dict(names_langs), fp)


def test_a_launch_with_the_same_windows_voices_starts_no_speech_helper(qapp, monkeypatch):
    """The voice list is remembered with the Windows voices it was listed for: the
    next launch shows it without starting PowerShell (~2 s, 85 MB) just to list them."""
    from soundboard.speech import winvoices
    from soundboard.ui.voice.voicepanel import VoicePanel
    fp = frozenset({"TTS_MS_EN-US_ZIRA_11.0", "TTS_MS_DE-DE_HEDDA_11.0"})
    monkeypatch.setattr(winvoices, "fingerprint", lambda: fp)
    started = []

    class Helper:   # stands in for the PowerShell process
        stdin = None

        def poll(self):
            return None

        def kill(self):
            pass

    def warm_up(self):
        started.append(1)
        self._proc = Helper()
        return self.voices
    monkeypatch.setattr(tts.SapiTTS, "warm_up", warm_up)
    known = _remembered([("Microsoft Zira Desktop", "en-US"),
                         ("Microsoft Hedda Desktop", "de-DE")], fp)
    p = VoicePanel(FakeEngine(), {}, {"voice": "Microsoft Hedda Desktop",
                                      tts.VOICE_CACHE: known})
    sp = p.speech
    try:
        assert process_events(qapp, lambda: sp.cb_voice.count() == 3, timeout=5)
        assert not started and not sp.ctl.tts.running
        assert sp.cb_voice.currentData() == "Microsoft Hedda Desktop"
        assert sp.ctl.tts.voice_for("de") == "Microsoft Hedda Desktop"
        sp.ctl.speaker.voice = "Microsoft Hedda Desktop"
        sp.ed.textEdited.emit("Hel")                 # typing a line: start it now
        assert process_events(qapp, lambda: started and not sp._warming, timeout=5)
        sp.ed.textEdited.emit("Hell")
        process_events(qapp, lambda: False, timeout=0.2)
        assert len(started) == 1                     # ...once, not per key
    finally:
        p.shutdown()
        p.deleteLater()


def test_other_windows_voices_list_them_again_and_remember_that(qapp, monkeypatch):
    from soundboard.speech import winvoices
    from soundboard.ui.voice.voicepanel import VoicePanel
    fp = frozenset({"TTS_MS_EN-US_ZIRA_11.0", "TTS_MS_FR-FR_JULIE_11.0"})
    monkeypatch.setattr(winvoices, "fingerprint", lambda: fp)

    def listed(self):   # what the helper's READY line gives
        self.voices, self.voice_langs = ["Zira", "Julie"], {"Zira": "en-US", "Julie": "fr-FR"}
        self.listed = (list(self.voices), dict(self.voice_langs))
        return self.voices
    monkeypatch.setattr(tts.SapiTTS, "warm_up", listed)
    old = _remembered([("Zira", "en-US")], {"TTS_MS_EN-US_ZIRA_11.0"})   # before Julie
    p = VoicePanel(FakeEngine(), {}, {tts.VOICE_CACHE: old})
    saved = []
    p.speech_changed.connect(saved.append)
    try:
        assert process_events(qapp, lambda: saved, timeout=5)
        assert tts.remembered_voices(saved[-1][tts.VOICE_CACHE], fp) == (
            ["Zira", "Julie"], {"Zira": "en-US", "Julie": "fr-FR"})
    finally:
        p.shutdown()
        p.deleteLater()


def test_remembered_voices_only_count_for_the_same_voices_and_a_sound_entry():
    fp = frozenset({"A", "B"})
    entry = tts.remember_voices(["Zira", "Hedda"], {"Zira": "en-US", "Hedda": "de-DE"}, fp)
    assert tts.remembered_voices(entry, frozenset({"B", "A"})) == (
        ["Zira", "Hedda"], {"Zira": "en-US", "Hedda": "de-DE"})
    assert tts.remembered_voices(entry, frozenset({"A"})) is None      # one removed
    assert tts.remembered_voices(entry, frozenset()) is None           # can't tell
    for bad in (None, "x", {"fp": ["A", "B"]}, {"fp": ["A", "B"], "voices": [["Zira"]]},
                {"fp": ["A", "B"], "voices": [[1, "en"]]}, {"fp": "AB", "voices": []}):
        assert tts.remembered_voices(bad, fp) is None


# ---------------------------------------------------------------- the status bar

def test_status_bar_off_label_cannot_open_a_card(panel, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel
    p, _ = panel
    opened = []
    p.bar.open_card.connect(opened.append)
    label = p.bar.chips["none"]
    assert isinstance(label, QLabel)
    assert label.focusPolicy() == Qt.NoFocus
    assert label.cursor().shape() == Qt.ArrowCursor
    p.show_tab("addons")
    QTest.mouseClick(label, Qt.LeftButton)
    p._open_card("none")
    assert not opened and p.current_tab() == "addons"
    monkeypatch.setattr("soundboard.speech.spoken.heard", lambda: True)
    monkeypatch.setattr(type(p.speech), "translating",
                        lambda self: ZH if self.cb_lang.currentData() else None)
    monkeypatch.setattr("soundboard.core.langnames.of", lambda m: "Chinese")
    p.speech.cb_lang.blockSignals(True)
    p.speech.cb_lang.setCurrentIndex(p.speech.cb_lang.findData("zh"))
    p.speech.cb_lang.blockSignals(False)
    p._update_bar()
    QTest.mouseClick(p.bar.chips["lang"], Qt.RightButton)   # a right-click opens its card
    assert opened == ["lang"] and p.current_tab() == "speak"
    assert p.speech.cb_lang.currentData() == "zh"              # ...and leaves it on


def test_status_bar_chip_click_turns_that_one_off_and_on_again(panel):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    p, _ = panel
    p.fx.pick("Robot")
    assert p.bar.texts() == [] and bar(p, "fx") == "on"
    p.show_tab("addons")
    pause = p._bar_ctl["fx"][0]
    QTest.mouseClick(pause, Qt.LeftButton)   # its bar's pause
    assert not p.fx.btn_power.isChecked()
    assert bar(p, "fx") == "paused" and "back on" in pause.toolTip()
    assert p.current_tab() == "addons"                  # a click doesn't jump tabs
    QTest.mouseClick(pause, Qt.LeftButton)              # ...and back on, the same voice
    assert p.fx.btn_power.isChecked() and p.fx.preset == "Robot"
    assert bar(p, "fx") == "on" and "Pause" in pause.toolTip()


def test_status_bar_chip_x_turns_off_only_that_one(panel, monkeypatch):
    p, _ = panel
    monkeypatch.setattr("soundboard.speech.spoken.heard", lambda: True)
    monkeypatch.setattr(type(p.speech), "translating",
                        lambda self: ZH if self.cb_lang.currentData() else None)
    monkeypatch.setattr("soundboard.core.langnames.of", lambda m: "Chinese")
    p.fx.pick("Robot")
    p.speech.cb_lang.setCurrentIndex(p.speech.cb_lang.findData("zh"))
    assert p.bar.texts() == ["Chinese"]
    opened = []
    p.bar.open_card.connect(opened.append)
    p._bar_ctl["fx"][1].click()                  # the voice changer goes, Chinese stays
    assert not p.fx.btn_power.isChecked() and p.speech.cb_lang.currentData() == "zh"
    assert bar(p, "fx") == "hidden" and not opened   # gone, not paused
    # ...now said by its own voice: on that voice's bar, not a chip
    assert p.bar.texts() == [] and bar(p, "lang") == "on"


def test_status_bar_says_what_others_hear(panel):
    p, eng = panel
    assert p.bar.texts() == ["Mic unchanged"]   # an empty mix: nothing for ON to turn on
    p.fx.pick("Robot")
    assert p.bar.texts() == [] and bar(p, "fx") == "on"   # on its own bar, not a chip
    assert p.bar.lbl_heard.isHidden()          # no chips: no "what others hear" ear
    # the mic: its level, or that none is open
    p.bar.set_level(None)
    assert not p.bar.lbl_mic.isHidden() and p.bar.lbl_mic.text() == "No mic open"
    p.bar.set_level(0.5)
    assert p.bar.lbl_mic.isHidden() and p.bar.meter.level == 0.5
    assert not hasattr(p.fx, "meter")                     # one meter, in the bar


def test_status_bar_shows_the_ai_voice_starting_on_and_failed(panel, monkeypatch):
    p, _ = panel
    ai = p.ai
    monkeypatch.setattr(ai, "is_on", lambda: True)
    monkeypatch.setattr(ai, "voice_title", lambda: "Squeak")
    for st, words, state in (("starting", "Squeak…", "on"), ("on", None, None),
                             ("failed", "AI voice off", "warn")):
        monkeypatch.setattr(ai, "status", lambda st=st: st)
        p._update_bar()
        if words is None:   # on: its own bar says it, no chip
            assert p.bar.texts() == [] and "ai" not in p.bar.chips
            continue
        assert p.bar.texts() == [words]
        assert p.bar.chips["ai"].property("state") == state


def test_first_visit_exposes_voice_presets(panel):
    p, _ = panel
    assert p.current_tab() == "fx" and p.fx.isVisibleTo(p)
    assert not p.ai.isVisibleTo(p)


def test_config_entries_sit_with_their_cards_main_controls(panel):
    """Edit voice (the big editor) is in the picked voice's bar, pinned in
    sight under the voices (not under 24 of them, off the bottom); Speak another
    language's More options comes before the past-lines box; both More options use
    the one fold look and show/hide their fields."""
    p, _eng = panel
    fx = p.fx
    assert fx.btn_tweak.parentWidget() is fx.picked
    assert fx.picked.parentWidget() is p             # pinned outside the scrolling card
    sp = p.speech
    lay = sp.layout()
    at = {lay.itemAt(i).widget(): i for i in range(lay.count()) if lay.itemAt(i).widget()}
    assert at[sp.btn_opts] < at[sp.opts] < at[sp.said_log]
    for b, body in ((sp.btn_opts, sp.opts), (p.ai.btn_opts, p.ai.opts)):
        assert b.objectName() == "fold" and b.isCheckable()
        b.setChecked(True)
        assert not body.isHidden()
        b.setChecked(False)
        assert body.isHidden()


def test_make_it_yours_reopens_the_same_window(panel):
    p, _eng = panel
    fx = p.fx
    fx.open_tweak()
    first = fx.dlg
    fx.open_tweak()                       # a second click raises it, no new window
    assert fx.dlg is first and first.isVisible()
    first.close()


def test_say_bar_has_no_volume_of_its_own(qapp, monkeypatch):
    """A typed line plays like a sound: the bottom bar's volumes set its loudness, so
    the Say bar has no slider and an old saved gain no longer turns it down (it stays
    in the settings for older versions)."""
    from soundboard.ui.kit.panel import VolumeControl
    from soundboard.ui.voice.voicepanel import VoicePanel
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"voice": "Microsoft Zira Desktop", "gain": 0.4})
    try:
        assert not p.speech.say_bar.findChildren(VolumeControl)
        assert p.speech.ctl.gain == 1.0
        assert p.speech.s["gain"] == pytest.approx(0.4)
    finally:
        p.shutdown()
        p.deleteLater()


def test_voice_reload_and_install_keep_focus(panel, qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from soundboard.ui.kit import busy
    from soundboard.ui.voice import speechinstall
    p, _ = panel
    s = p.speech
    _japanese_without_a_voice(s, qapp)
    p.show_tab("speak")
    p.show()
    qapp.processEvents()
    workers = []
    class Thread:
        def __init__(self, target, **kw): self.target = target
        def start(self): workers.append(self.target)
    monkeypatch.setattr(speechinstall, "threading", type("Threads", (), {"Thread": Thread}))
    for btn, finish in (
            (s.installs.b_voices_check, lambda: s._fill_voices(["Microsoft Zira Desktop"], "")),
            (s.installs.b_voice_install, lambda: s.installs._on_voice_installed("", "offline"))):
        btn.setFocus()
        QTest.mouseClick(btn, Qt.LeftButton)
        assert btn.isEnabled() and busy.is_busy(btn) and p.focusWidget() is btn
        QTest.mouseClick(btn, Qt.LeftButton)
        assert len(workers) == 1
        workers.clear()
        finish()
        qapp.processEvents()
        assert not busy.is_busy(btn) and p.focusWidget() is btn


def test_speech_install_and_cancel_keep_focus(panel, qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from soundboard.ui.kit import busy
    from soundboard.ui.voice import speechinstall
    p, _ = panel
    s = p.speech
    assert process_events(qapp, lambda: not s.installs._loading())
    from types import SimpleNamespace
    s.module = SimpleNamespace(installed=True, broken=False, id="live")   # Update: it's in
    s.installs._refresh_module()
    p.show_tab("speak")
    p.show()
    s.opts.show()
    s.installs.b_update.show()
    qapp.processEvents()
    workers = []
    class Thread:
        def __init__(self, target, **kw): self.target = target
        def start(self): workers.append(self.target)
    monkeypatch.setattr(speechinstall, "threading", type("Threads", (), {"Thread": Thread}))
    s.installs.b_update.setFocus()
    QTest.mouseClick(s.installs.b_update, Qt.LeftButton)
    assert busy.is_busy(s.installs.b_update) and p.focusWidget() is s.installs.b_update
    QTest.mouseClick(s.installs.b_update, Qt.LeftButton)
    assert len(workers) == 1
    s.installs._on_install_done(False, "offline")
    assert not busy.is_busy(s.installs.b_update) and p.focusWidget() is s.installs.b_update
    _japanese_without_a_voice(s, qapp)
    s.installs._dl_busy = s._lang()
    s._refresh_translation()
    s.installs.b_dl_cancel.setFocus()
    QTest.mouseClick(s.installs.b_dl_cancel, Qt.LeftButton)
    assert busy.is_busy(s.installs.b_dl_cancel) and p.focusWidget() is s.installs.b_dl_cancel
    s.installs._on_dl_done("cancelled")
    assert not busy.is_busy(s.installs.b_dl_cancel)


def test_translation_download_keeps_focus(panel, qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from soundboard.online import net
    from soundboard.speech import translation
    from soundboard.ui.kit import busy
    from soundboard.ui.voice import speechinstall
    monkeypatch.setattr(net, "allowed", lambda key: True)
    monkeypatch.setattr(net, "offline", lambda: False)
    p, _ = panel
    s = p.speech
    assert process_events(qapp, lambda: not s.installs._loading())
    monkeypatch.setattr(translation, "is_downloaded", lambda info: False)
    installed = speechinstall.mods.ModuleInfo.installed.fget
    monkeypatch.setattr(speechinstall.mods.ModuleInfo, "installed", property(
        lambda info: True if info.id == "live-voice" else installed(info)))
    s._fill_langs()
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("zh"))
    p.show_tab("speak")
    p.show()
    qapp.processEvents()
    workers = []
    class Thread:
        def __init__(self, target, **kw): self.target = target
        def start(self): workers.append(self.target)
    monkeypatch.setattr(speechinstall, "threading", type("Threads", (), {"Thread": Thread}))
    s.installs.b_dl.setFocus()
    QTest.mouseClick(s.installs.b_dl, Qt.LeftButton)
    b_dl = s.installs.b_dl
    assert b_dl.isVisible() and busy.is_busy(b_dl) and p.focusWidget() is b_dl
    QTest.mouseClick(s.installs.b_dl, Qt.LeftButton)
    assert len(workers) == 1
    s.installs._on_dl_done("offline")
    assert not busy.is_busy(s.installs.b_dl) and p.focusWidget() is s.installs.b_dl


@pytest.mark.parametrize("width", [900, 1600])
def test_ai_voice_list_keeps_its_height_with_a_long_description(panel, qapp, width):
    """A voice's long description is the tip of its card and of the voice bar's name (as
    the voice changer's bar: the name only), so it never squashes the voice cards."""
    p, _eng = panel
    ai = p.ai
    about = "A light, high, young-sounding voice, good for cheerful characters. " * 6
    ai.voices = [{"id": "pixie", "name": "Pixie", "about": about}]
    ai._fill_tiles()
    ai.ready_box.setVisible(True)
    ai.missing.setVisible(False)
    p.resize(width, 700)
    p.show()
    p.show_tab("ai")
    for _ in range(6):
        qapp.processEvents()
    ai._show_about()
    tile = ai._tile["pixie"]
    process_events(qapp, lambda: tile.height() >= tile.sizeHint().height(), 1.0)
    assert ai.picked_name.text() == "Pixie" and about in ai.picked_name.toolTip()
    assert about in tile.toolTip()
    assert tile.height() >= tile.sizeHint().height()


def test_voices_off_dims_the_picked_voice_bar_and_x_takes_it_away(panel):
    """Voices OFF pauses the voice changer: its bar stays, dimmed, with play to bring
    it back (left looking the same, it seemed still on). Its ✕ takes the bar away."""
    p, _eng = panel
    p.resize(1000, 900)
    p.show()
    p.show_tab("fx")
    name = next(n for n in p.fx._tile if n != "Custom")
    p.fx._tile[name].click()
    assert p.fx.btn_power.isChecked() and bar(p, "fx") == "on"
    p.bar.master.click()
    assert not p.fx.btn_power.isChecked() and not p.fx._tile[name].isChecked()
    assert bar(p, "fx") == "paused"
    assert p._bar_dim["fx"][0].opacity() < 1           # dimmed
    p.show_tab("ai")
    assert bar(p, "fx") == "paused"                    # on every tab
    p._bar_ctl["fx"][1].click()                        # its ✕: gone
    assert bar(p, "fx") == "hidden" and not p.fx.btn_power.isChecked()
    p.show_tab("fx")
    p.fx._tile[name].click()                           # a voice picked again: it's back
    assert bar(p, "fx") == "on" and p._bar_dim["fx"][0].opacity() == 1

def test_voice_groups_and_favorites(qapp, monkeypatch):
    """Every voice sits under one group; a starred voice shows under Favorites (in the
    order starred), is saved with the settings and comes back starred."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard import voicefx
    from soundboard.ui.voice.voicefxpanel import (CUSTOM, FAVS, MINE, VOICE_GROUPS,
                                                  VoiceFxPanel, voice_group)
    grouped = [n for _k, _t, names in VOICE_GROUPS for n in names]
    assert sorted(grouped) == sorted(voicefx.PRESETS)   # each preset once, none left out
    assert voice_group(CUSTOM) == MINE
    fx = VoiceFxPanel({})
    shown = lambda: {n for n, b in fx._tile.items() if not b.isHidden()}  # noqa: E731
    assert shown() == set(fx._tile)
    fx.bar.choose("scary")
    assert shown() == set(dict(((k, n) for k, _t, n in VOICE_GROUPS))["scary"])
    fx.bar.choose(FAVS)
    assert shown() == set() and not fx.no_favs.isHidden()
    # the dropdown counts each group; a search narrows the group showing
    assert fx._group_count("scary") == len(dict(((k, n) for k, _t, n in VOICE_GROUPS))["scary"])
    fx.bar.choose("scary")
    fx.bar.search.setText("dem")
    assert shown() == {"Demon"} and fx.no_match.isHidden()
    fx.bar.search.setText("zzz")
    assert shown() == set() and not fx.no_match.isHidden()
    fx.bar.search.clear()
    fx.bar.choose(FAVS)
    fx._tile["Robot"].star.click()
    fx._tile["Demon"].star.click()
    assert shown() == {"Robot", "Demon"} and fx.no_favs.isHidden()
    assert fx.spec()["favorites"] == ["Robot", "Demon"]
    again = VoiceFxPanel(voicefx.clean_spec(fx.spec()))
    assert again.favorites == ["Robot", "Demon"]
    assert again._tile["Robot"].star.isChecked()
    fx._tile["Robot"].star.click()                      # unstarred: it leaves Favorites
    assert shown() == {"Demon"} and fx.favorites == ["Demon"]
    assert voicefx.clean_spec({"favorites": ["A", 3, "A", ""]})["favorites"] == ["A"]



def test_a_huge_search_stops_at_the_cap_and_says_so_briefly(qapp, monkeypatch):
    """Thousands of letters typed or pasted into the search sort the cards at most
    SEARCH_MAX times, and the "nothing matches" line stays one short line."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.groupbar import SEARCH_MAX
    from soundboard.ui.voice.voicefxpanel import VoiceFxPanel
    fx = VoiceFxPanel({})
    runs = []
    fx.bar.searched.connect(runs.append)
    fx.bar.search.setFocus()
    from PySide6.QtTest import QTest
    QTest.keyClicks(fx.bar.search, "Z" * 400)
    assert len(fx.bar.search.text()) == SEARCH_MAX
    assert len(runs) == SEARCH_MAX
    assert not fx.no_match.isHidden()
    assert len(fx.no_match.text()) < 60 and "…" in fx.no_match.text()
    fx.bar.search.clear()
    fx.bar.search.insert("Q" * 4000)   # a paste
    assert len(fx.bar.search.text()) == SEARCH_MAX

def test_random_voice_turns_on_a_shown_voice_never_the_same_twice(panel):
    import random
    p, _ = panel
    fx = p.fx
    rng = random.Random(3)
    seen = set()
    last = ""
    for _i in range(40):
        name = fx.roll(rng)
        assert name in voicefx.PRESETS and name != last     # never My own mix, never again
        assert fx.btn_power.isChecked() and fx.preset == name and fx._tile[name].isChecked()
        seen.add(name)
        last = name
    assert len(seen) > 10
    fx.show_group("scary")                    # one group shown: picks from that group only
    from soundboard.ui.voice.voicefxpanel import voice_group
    for _i in range(10):
        assert voice_group(fx.roll(rng)) == "scary"
    assert _grid_order(fx)[-1] == "Random voice"


def test_random_voice_needs_two_voices_to_pick_from(panel):
    p, _ = panel
    fx = p.fx
    fx.show_group("favs")
    assert not fx.random_tile.isVisibleTo(fx) and fx.roll() == ""
    fx.set_favorite("Ghost", True)
    assert not fx.random_tile.isVisibleTo(fx)        # one favorite: nothing to roll
    fx.set_favorite("Demon", True)
    assert fx.random_tile.isVisibleTo(fx)
    fx.random_tile.click()
    assert fx.preset in ("Ghost", "Demon")
    first = fx.preset
    fx.random_tile.click()
    assert fx.preset in ("Ghost", "Demon") and fx.preset != first


def test_hear_it_plays_the_voice_in_the_headphones(panel, monkeypatch):
    from soundboard.speech import aipreview
    p, eng = panel
    played = []
    monkeypatch.setattr(eng, "play", lambda sid, data, gain, **k: played.append((sid, data, k)),
                        raising=False)
    t = np.arange(16000) / 16000
    monkeypatch.setattr(aipreview, "sample", lambda: (0.5 * np.sin(2 * np.pi * 150 * t))
                        .astype(np.float32))
    monkeypatch.setattr(aipreview, "_cache", OrderedDict())
    fx = p.fx
    fx.pick("Chipmunk")
    assert fx.btn_sample.isHidden()   # not on the bar: a card's right-click Hear it
    fx.btn_sample.click()
    from PySide6.QtWidgets import QApplication
    assert process_events(QApplication.instance(), lambda: played), "no sample played"
    sid, data, kw = played[0]
    assert kw.get("preview") is True                  # your headphones only
    assert data.ndim == 2 and data.shape[1] == 2 and 0.1 < np.max(np.abs(data)) <= 0.8
    assert fx.btn_sample.text() == aipreview_text()   # the button came back
    assert fx.effects_of("Chipmunk")["pitch"]["semitones"] == 8
    assert "cleanup" not in fx.effects_of("Chipmunk")


def aipreview_text():
    from soundboard.ui.voice.aivoicebrowser import HEAR
    return HEAR


def test_hear_it_failing_says_why_and_comes_back(panel, monkeypatch):
    from soundboard.speech import aipreview
    from soundboard.ui.kit import busy
    p, _ = panel
    said = []
    monkeypatch.setattr(busy, "toast", lambda w, text, kind="", *a, **k: said.append(text))

    def fail():
        raise aipreview.PreviewError("no speech voice")
    monkeypatch.setattr(aipreview, "sample", fail)
    monkeypatch.setattr(aipreview, "_cache", OrderedDict())
    p.fx.hear("Robot")
    from PySide6.QtWidgets import QApplication
    assert process_events(QApplication.instance(), lambda: said)
    assert said and "no speech voice" in said[0]
    from soundboard.ui.voice.aivoicebrowser import HEAR
    assert p.fx.btn_sample.text() == HEAR and not p.fx._hearing


def test_a_setup_goes_to_a_friend_as_a_code_and_comes_back(panel, monkeypatch):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QMessageBox

    from soundboard.ui.kit import busy
    p, _ = panel
    bar = p.setups_bar
    assert bar.btn_import.isVisibleTo(bar) and bar.btn_import.parentWidget() is bar.chips
    p.fx.pick("Chipmunk")
    assert p.setups.put("Chip", p.current_setup()) == "Chip"
    assert p.copy_setup_code("Chip")
    code = QGuiApplication.clipboard().text()
    assert code.startswith("OB2-")
    asked, said = [], []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a[2]) or QMessageBox.Yes)
    monkeypatch.setattr(busy, "toast", lambda *a, **k: said.append(a[1]))
    _ask(monkeypatch, code)
    bar.btn_import.click()          # the My voice combos row's own Import a code
    assert "Chip" in asked[0] and list(p.setups.setups) == ["Chip", "Chip (2)"]
    assert "Chip (2)" in bar.buttons and "My voice combos" in said[-1]
    # the voice changer's Import a code takes a setup code too
    assert p.fx.import_code(code) == "Chip (3)"
    assert not p.fx.store.voices                 # (a setup, not a saved voice)


def test_a_shared_setup_never_turns_on_your_own_voice_of_the_same_name(panel, monkeypatch):
    p, _ = panel
    p.fx.pick("Robot")
    _ask(monkeypatch, "Squeaky")
    p.fx.save_voice()                             # yours: a robot
    theirs = {"pitch": {"on": True, "semitones": 9.0}}
    p.use_setup({"fx": "Squeaky", "effects": theirs})
    effects = p.fx.spec()["effects"]
    assert p.fx.preset != "Squeaky" and effects["pitch"]["semitones"] == 9.0
    assert not effects.get("robot", {}).get("on")
    p.use_setup({"fx": "Squeaky", "effects": p.fx.store.voices["Squeaky"]})
    assert p.fx.preset == "Squeaky"               # the same voice: picked as itself


def test_a_saved_voice_named_like_a_ready_voice_gets_its_own_card(qapp, monkeypatch):
    # a voices.json from before "Chipmunk" was a ready voice: its card is its own
    import json
    from soundboard.mic import savedvoices
    mine = {"pitch": {"on": True, "semitones": -5.0}}
    savedvoices.path().parent.mkdir(parents=True, exist_ok=True)
    savedvoices.path().write_text(json.dumps({"voices": [{"name": "Chipmunk",
                                                          "effects": mine}]}),
                                  encoding="utf-8")
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"voice": "Microsoft Zira Desktop", "rate": 2})
    assert p.fx.saved_names() == ["Chipmunk (2)"]
    assert p.fx._tile["Chipmunk"] is not p.fx._tile["Chipmunk (2)"]
    p.fx._tile["Chipmunk (2)"].click()
    assert p.fx.preset == "Chipmunk (2)"
    assert p.fx.spec()["effects"]["pitch"]["semitones"] == -5.0
    p.fx._tile["Chipmunk"].click()
    assert p.fx.spec()["effects"]["pitch"]["semitones"] != -5.0


def test_ai_voices_card_has_the_voice_changers_switch_bar_and_view(panel, qapp, monkeypatch):
    """AI voices' card head is the voice changer's: its switch, no "On" pill; its voice
    bar is pinned under the cards on its own tab; cards or a list is one setting."""
    p, _eng = panel
    p.resize(1000, 700)
    p.show()
    p.show_tab("ai")
    qapp.processEvents()
    assert p.ai.head.isVisibleTo(p) and p._states["ai"].isHidden()
    outer = p.layout()
    assert outer.indexOf(p.ai.picked) >= 0 and outer.indexOf(p.fx.picked) >= 0
    # turned on (without the add-on's helper): its bar shows, on every tab
    p.ai.b_start.blockSignals(True)
    p.ai.b_start.setChecked(True)
    p.ai.b_start.blockSignals(False)
    p.ai.show_picked_row()
    p._emit_active()
    assert p.ai.picked.isVisibleTo(p) and p._states["ai"].isHidden()
    p.show_tab("fx")
    assert p.ai.picked.isVisibleTo(p)
    p.show_tab("ai")
    assert p.ai.picked.isVisibleTo(p)
    p.ai.b_start.blockSignals(True)
    p.ai.b_start.setChecked(False)
    p.ai.b_start.blockSignals(False)
    # the list view, switched on either card, is both cards' (and saved once)
    saved = []
    p.fx.view_toggle.changed.connect(saved.append)
    p.ai.view_toggle.buttons["list"].click()
    assert p.fx._listed and p.ai._listed and saved == ["list"]
    p.fx.view_toggle.buttons["grid"].click()
    assert not p.fx._listed and not p.ai._listed and p.ai.view_toggle.view() == "grid"
    p.set_view("list")
    assert p.fx._listed and p.ai._listed


def test_clicking_the_lit_voice_again_turns_the_voice_changer_off(panel):
    """A second click on the voice that's on turns it off; another voice switches."""
    p, eng = panel
    p.fx._tile["Robot"].click()
    assert p.fx.btn_power.isChecked() and p.fx.btn_power.text() == "On"
    p.fx._tile["Ghost"].click()                 # another one: switches, stays on
    assert p.fx.btn_power.isChecked() and p.fx.preset == "Ghost"
    p.fx._tile["Ghost"].click()                 # the lit one again: off
    assert not p.fx.btn_power.isChecked() and p.fx.btn_power.text() == "Off"
    assert not p.fx._tile["Ghost"].isChecked() and not eng.voice_chain.enabled
    p.fx._tile["Ghost"].click()                 # and on again
    assert p.fx.btn_power.isChecked() and eng.voice_chain.enabled


def test_use_less_cpu_asks_for_the_small_speech_model_if_it_is_there(panel):
    """With Use less CPU the helper is told it may use tiny.en in place of base.en
    (it does only when that's downloaded already: modules/live-voice --lighter)."""
    from soundboard import voicefx
    p, _ = panel
    lv = p.speech.livevoice
    assert "--lighter" not in lv._live_args()
    voicefx.set_light(True)
    try:
        args = lv._live_args()
        assert args[:2] == ["--model", "base.en"]
        assert args[args.index("--lighter") + 1] == "tiny.en"
    finally:
        voicefx.set_light(False)


def test_clicks_on_the_voice_tab_dont_check_the_disk_each_time(panel, monkeypatch, tmp_path):
    """Every click on the tab asks which voices are on (translating()). It reads the
    add-on's install from the disk once, not per click: during an install the disk is
    busy and one check held the window, and the sounds, for seconds."""
    p, _ = panel
    asked = []

    class Mod:
        broken, language, language_name, voice = False, "zh", "Chinese", {}

        def __init__(self, name):
            self.path = tmp_path / name

        @property
        def installed(self):
            asked.append(self.path.name)
            return True

    live, lang = Mod("live"), Mod("zh")
    monkeypatch.setattr(p.speech, "module", live)
    monkeypatch.setattr(p.speech, "_lang_on", lambda: lang)
    monkeypatch.setattr("soundboard.core.langnames.of", lambda m: "Chinese")
    p.speech._ready.clear()
    for _i in range(5):
        assert p.speech.translating() is lang
    assert sorted(asked) == ["live", "zh"]
    p.speech.installs._refresh_module()        # installed / repaired / rescanned
    asked.clear()
    assert p.speech.translating() is lang and sorted(asked) == ["live", "zh"]
    p.speech._ready[id(lang)] = False          # a language removed: _fill_langs asks again
    asked.clear()
    p.speech._fill_langs()
    assert p.speech.translating() is lang and "zh" in asked


def test_off_at_start_forgets_the_picked_voice(qapp, monkeypatch):
    """Left off last run: ON starts from no picked voice (your own mix), not the old
    one. Left on: it comes back as it was."""
    from soundboard.ui.voice.voicefxpanel import CUSTOM, at_start
    ghost = voicefx.PRESETS["Ghost"]
    mine = {"echo": {"on": True, "mix": 0.3}}
    off = {"enabled": False, "preset": "Ghost", "effects": ghost, "custom": mine}
    assert at_start(off) == {"enabled": False, "preset": CUSTOM, "effects": mine,
                             "custom": mine}
    assert at_start({"enabled": False, "preset": "Ghost", "effects": ghost})["effects"] == {}
    on = {**off, "enabled": True}
    assert at_start(on) == on
    assert at_start({}) == {} and at_start(None) is None

    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), at_start({"enabled": False, "preset": "Ghost",
                                           "effects": ghost}),
                   {"voice": "Microsoft Zira Desktop", "rate": 2})
    assert p.fx.preset == CUSTOM
    assert p.bar.texts() == ["Mic unchanged"]   # your own mix is empty: nothing to turn on
    p.deleteLater()


def test_start_and_recognition_options_wait_for_speech_recognition(panel):
    """No recognition settings above "Install speech recognition": they show once it's
    in. The old computer voice's Start (and its mute box) never show."""
    from types import SimpleNamespace
    p, _ = panel
    s = p.speech
    needs = (s.cb_model, s.ed_lang, s.installs.b_update)
    s.module = SimpleNamespace(installed=False, broken=False, id="live")
    s.installs._refresh_module()
    assert all(w.isHidden() for w in needs)
    assert not s.installs.missing.isHidden()
    s.module = SimpleNamespace(installed=True, broken=False, id="live")
    s.installs._refresh_module()
    assert not any(w.isHidden() for w in needs)
    assert s.installs.missing.isHidden()
    assert s.livevoice.b_live.isHidden() and s.chk_mute.isHidden()


def test_a_stuck_windows_speech_at_launch_shows_no_toast(qapp, monkeypatch):
    """The launch lists Windows' voices in the background, before anyone asked for
    speech (they may be on the Sounds tab): its error is logged, not toasted. The
    same error when a line is being typed is shown."""
    from tests.conftest import process_events

    def stuck(self):
        self.error = "Windows speech stopped answering"
        return []
    monkeypatch.setattr(tts.SapiTTS, "warm_up", stuck)
    toasts = []
    monkeypatch.setattr("soundboard.ui.kit.busy.toast", lambda w, t, *a, **k: toasts.append(t))
    from soundboard.ui.voice.voicepanel import VoicePanel
    filled = []
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}}, {"rate": 2})
    try:
        s = p.speech
        s._voices_quiet.connect(lambda *a: filled.append(a))
        assert process_events(qapp, lambda: filled)
        qapp.processEvents()
        assert not [t for t in toasts if "Text-to-speech" in t]
        s._fill_voices([], "Windows speech stopped answering")   # a line being typed
        assert [t for t in toasts if "Text-to-speech" in t]
    finally:
        p.shutdown()
        p.deleteLater()


def test_a_folded_bar_keeps_pause_and_x_on_the_names_line(panel, qapp):
    """Narrow, a bar's buttons go under the name; its pause and ✕ stay level with the
    name (on a line of their own they made a tall, mostly empty third row)."""
    from PySide6.QtWidgets import QBoxLayout
    p, _eng = panel
    p.fx.pick("Robot")
    p.show()
    bar = p.fx
    pause, _close = p._bar_ctl["fx"]
    for width, folded in ((440, True), (1500, False), (440, True)):
        p.resize(width, 700)
        for _ in range(5):
            qapp.processEvents()
        assert (bar.picked_box.direction() == QBoxLayout.Direction.TopToBottom) == folded
        name_y = bar.picked_name.mapTo(bar.picked, bar.picked_name.rect().center()).y()
        ctl_y = pause.mapTo(bar.picked, pause.rect().center()).y()
        assert abs(name_y - ctl_y) <= 12, (width, name_y, ctl_y)
        if folded:   # two lines: the name's (with pause and ✕), then the buttons
            assert pause.mapTo(bar.picked, pause.rect().topLeft()).y() < \
                bar.btn_tweak.mapTo(bar.picked, bar.btn_tweak.rect().topLeft()).y()


def test_languages_know_at_start_whether_their_voice_can_read(panel):
    """Not only after a rescan: at start, with no AI voices add-on (or one without
    reader.py), a language named its own voice and said nothing."""
    p, _ = panel
    m = p.ai.module
    want = ("get" if m is None or not m.installed
            else "update" if not (m.path / "reader.py").is_file() else "")
    assert p.speech.voices_need == want


def test_languages_say_when_ai_voices_is_missing_or_too_old(panel, monkeypatch, tmp_path):
    """The language voices read through the AI voices add-on: without it (or with one
    from before they came) the Languages tab says what to do, not a silent voice."""
    import dataclasses
    p, _ = panel
    sp = p.speech
    _chinese_downloaded(sp)
    sp.cb_lang.setCurrentIndex(sp.cb_lang.findData("zh"))
    monkeypatch.setattr(sp.ctl.tts, "voice_for", lambda lang, prefer="": "piper:zh")
    monkeypatch.setattr(sp.ctl.tts, "voices", ["piper:zh"], raising=False)
    p.ai.module = None
    p.rescan_modules(p.modules, [])
    assert sp.voices_need == "get" and "needs the AI voices add-on" in sp.lbl_tr.text()
    assert p.lang_bar.picked_name.text() != "Huayan"   # it can't read: not named
    old = tmp_path / "ai-voices"
    (old / ".venv" / "Scripts").mkdir(parents=True)
    (old / ".venv" / "Scripts" / "python.exe").write_bytes(b"x")
    ai = next((m for m in p.modules if m.id == "ai-voices"), None)
    if ai is None:
        pytest.skip("no ai-voices add-on in this copy")
    found = [m for m in p.modules if m.id != "ai-voices"] + [dataclasses.replace(ai, path=old)]
    p.rescan_modules(found, [])                       # installed, but no reader.py yet
    assert sp.voices_need == "update" and "Update AI voices" in sp.lbl_tr.text()
    (old / "reader.py").write_text("")
    p.rescan_modules(found, [])
    assert sp.voices_need == "" and "not perfect with slang" in sp.lbl_tr.text()
    assert p.lang_bar.picked_name.text() == "Huayan"   # the new add-on: its row follows
