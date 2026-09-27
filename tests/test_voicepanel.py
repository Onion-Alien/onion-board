"""The Voice panel, offscreen: presets reach the chain, settings round-trip."""
import numpy as np
import pytest

from soundboard import voicefx
from soundboard.speech import tts
from tests.conftest import process_events


class FakeEngine:
    voice_chain = None

    def play(self, *a, **k):
        pass

    def stop(self, sid):
        pass


@pytest.fixture
def panel(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voicepanel import VoicePanel
    eng = FakeEngine()
    p = VoicePanel(eng, {"enabled": False, "effects": {}},
                   {"voice": "Microsoft Zira Desktop", "rate": 2})
    yield p, eng
    p.shutdown()
    p.deleteLater()


def test_panel_installs_the_chain_on_the_engine(panel):
    p, eng = panel
    assert eng.voice_chain is p.chain
    assert set(voicefx.REGISTRY) <= set(p.fx.rows)       # built-ins and add-ons get rows


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
    row.sliders[0].slider.setValue(row.sliders[0].slider.value() - 3)
    assert p.fx.preset == "Custom"
    assert p.fx.spec()["effects"]["pitch"]["semitones"] == 5


def test_power_switch_and_hear_button(panel):
    p, _ = panel
    seen, hear = [], []
    p.fx_changed.connect(seen.append)
    p.fx.hear_toggled.connect(hear.append)
    assert not p.fx.btn_power.isChecked() and "OFF" in p.fx.btn_power.text()
    p.fx.pick("Deep voice")                  # picking a voice turns it on
    assert p.fx.btn_power.isChecked() and "ON" in p.fx.btn_power.text()
    assert p.fx._tile["Deep voice"].isChecked()
    p.fx.btn_power.setChecked(False)         # the switch turns it off, voice kept
    assert not seen[-1]["enabled"] and seen[-1]["preset"] == "Deep voice"
    assert not p.fx._tile["Deep voice"].isChecked()   # nothing looks selected while off
    p.fx.btn_hear.setChecked(True)
    assert hear == [True]
    p.fx.set_hearing(False)                  # mirrored from the window: no echo back
    assert hear == [True] and not p.fx.btn_hear.isChecked()


def test_saved_spec_loads_back(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voicepanel import VoiceFxPanel
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
        assert p.speech.live_box.isHidden() and not p.speech.missing.isHidden()


def test_everything_spoken_lands_in_the_log(panel, monkeypatch):
    p, _ = panel
    s = p.speech
    monkeypatch.setattr(s.ctl, "say", lambda text: None)
    s.ed.setText("typed line")
    s._say()
    s._on_event({"type": "final", "text": "heard line"})
    s._on_event({"type": "final", "text": ""})
    lines = s.said_log.toPlainText().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("typed line") and lines[1].endswith("heard line")


def test_changer_starts_off_even_if_it_was_left_on(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voicepanel import POWER_TEXT, VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": True, "preset": "Old telephone", "effects": {}}, {})
    try:
        assert not p.fx.btn_power.isChecked() and not p.chain.enabled
        assert p.fx.btn_power.text() == POWER_TEXT[False]
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
    assert codes[0] == "" and set(codes[1:]) == {"zh", "es", "fr", "de", "ru"}
    assert s.tr_box.isHidden()                          # English: nothing to download
    assert not translation.base_dir().exists()          # and nothing was fetched
    got = []
    s.changed.connect(got.append)
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("de"))
    assert got[-1]["translate"] == "de"
    assert not s.tr_box.isHidden() and not s.b_dl.isHidden()
    assert s.b_dl.text() == "Download German" and "151 MB" in s.lbl_tr.text()
    started = []
    monkeypatch.setattr(s.ctl, "start_live", lambda m, args=(): started.append(args))
    if s.module is not None:
        s._toggle_live(True)                            # not downloaded: refuses to start
        assert started == [] and "Download German first" in s.lbl_state.text()


def test_downloaded_language_needs_a_windows_voice_and_uses_it(panel, monkeypatch):
    from soundboard.speech import translation
    p, _ = panel
    s = p.speech
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("de"))
    m = s._lang()
    d = translation.model_dir(m)
    (d / "model").mkdir(parents=True)
    (d / "model" / "model.bin").write_bytes(b"x")
    (d / "sentencepiece.model").write_bytes(b"x")
    tts = s.ctl.tts
    tts.voices, tts.voice_langs = ["Microsoft Zira Desktop"], {"Microsoft Zira Desktop": "en-US"}
    s._fill_langs()
    assert s.cb_lang.currentText() == "German"
    assert s.b_dl.isHidden() and not s.b_voices.isHidden()
    assert "no German voice" in s.lbl_tr.text()
    tts.voices.append("Microsoft Katja")
    tts.voice_langs["Microsoft Katja"] = "de-DE"
    s._refresh_translation()
    assert s.b_voices.isHidden() and "Katja says it in German" in s.lbl_tr.text()
    started = []
    monkeypatch.setattr(s.ctl, "start_live", lambda mod, args=(): started.append(args))
    s.module = s.module or object()
    s._toggle_live(True)
    args = started[0]
    assert args[args.index("--translate") + 1] == str(d)
    assert s.ctl.live_voice == "Microsoft Katja"
    s._on_event({"type": "final", "text": "Hallo", "original": "Hello"})
    assert s.said_log.toPlainText().endswith("Hallo   (you said: Hello)")
    s._remove_download()
    assert not d.exists() and "(download" in s.cb_lang.currentText()


def test_voice_installed_in_windows_settings_is_found_on_return(panel, qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDesktopServices
    from soundboard.speech import translation
    p, _ = panel
    s = p.speech
    assert process_events(qapp, lambda: not s._loading())    # the first voice load
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("zh"))
    d = translation.model_dir(s._lang())
    (d / "model").mkdir(parents=True)
    (d / "model" / "model.bin").write_bytes(b"x")
    (d / "sentencepiece.model").write_bytes(b"x")
    tts_ = s.ctl.tts
    tts_.voices, tts_.voice_langs = ["Microsoft Zira Desktop"], {"Microsoft Zira Desktop": "en-US"}
    s._fill_langs()
    assert not s.b_voices.isHidden() and not s.b_voices_check.isHidden()
    assert "Add-ons" not in s.lbl_tr.text()
    s._app_state(Qt.ApplicationActive)          # not sent to settings: no rescan
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    s.b_voices.click()
    assert opened and s._voice_wait

    def installed(self):
        self.voices = ["Microsoft Zira Desktop", "Microsoft Huihui Desktop"]
        self.voice_langs = {"Microsoft Zira Desktop": "en-US",
                            "Microsoft Huihui Desktop": "zh-CN"}
        return self.voices
    monkeypatch.setattr(tts.SapiTTS, "refresh", installed)
    s._app_state(Qt.ApplicationActive)          # back from settings: looks again by itself
    assert process_events(qapp, lambda: "Huihui says it in Chinese" in s.lbl_tr.text())
    assert s.b_voices.isHidden() and s.b_voices_check.isHidden() and not s._voice_wait
    assert s.b_voice_install.isHidden()


def _chinese_without_a_voice(s, qapp):
    from soundboard.speech import translation
    assert process_events(qapp, lambda: not s._loading())
    s.cb_lang.setCurrentIndex(s.cb_lang.findData("zh"))
    d = translation.model_dir(s._lang())
    (d / "model").mkdir(parents=True)
    (d / "model" / "model.bin").write_bytes(b"x")
    (d / "sentencepiece.model").write_bytes(b"x")
    s.ctl.tts.voices = ["Microsoft Zira Desktop"]
    s.ctl.tts.voice_langs = {"Microsoft Zira Desktop": "en-US"}
    s._fill_langs()


def _huihui_arrives(monkeypatch):
    def installed(self):
        self.voices = ["Microsoft Zira Desktop", "Microsoft Huihui"]
        self.voice_langs = {"Microsoft Zira Desktop": "en-US", "Microsoft Huihui": "zh-CN"}
        return self.voices
    monkeypatch.setattr(tts.SapiTTS, "refresh", installed)


def test_one_click_voice_install_then_its_picked_up(panel, qapp, monkeypatch):
    import threading
    from soundboard.speech import winvoices
    p, _ = panel
    s = p.speech
    _chinese_without_a_voice(s, qapp)
    assert not s.b_voice_install.isHidden() and "Chinese voice" in s.b_voice_install.text()
    assert s._voice_timer.isActive()               # watching for it to turn up
    go = threading.Event()
    asked = []
    monkeypatch.setattr(winvoices, "install", lambda lang: (asked.append(lang), go.wait(5),
                                                            "ok")[-1])
    _huihui_arrives(monkeypatch)
    s.b_voice_install.click()
    assert not s.b_voice_install.isEnabled() and "Installing" in s.lbl_tr.text()
    s.b_voice_install.click()                      # a second click does nothing
    go.set()
    assert process_events(qapp, lambda: "Huihui says it in Chinese" in s.lbl_tr.text())
    assert asked == ["zh"]
    assert s.b_voice_install.isHidden() and not s._voice_timer.isActive()


def test_voice_install_cancelled_or_failed_says_so(panel, qapp, monkeypatch):
    from soundboard.speech import winvoices
    p, _ = panel
    s = p.speech
    _chinese_without_a_voice(s, qapp)

    def cancel(lang):
        raise winvoices.Cancelled()
    monkeypatch.setattr(winvoices, "install", cancel)
    s.b_voice_install.click()
    assert process_events(qapp, lambda: "permission prompt was closed" in s.lbl_tr.text())
    assert s.b_voice_install.isEnabled() and not s.b_voices.isHidden()

    def fail(lang):
        raise RuntimeError("0x800f0954")
    monkeypatch.setattr(winvoices, "install", fail)
    s.b_voice_install.click()
    assert process_events(qapp, lambda: "0x800f0954" in s.lbl_tr.text())
    assert s.b_voice_install.isEnabled()


def test_new_voice_is_used_mid_talk_without_a_restart(panel, qapp, monkeypatch):
    from soundboard.speech import winvoices
    p, _ = panel
    s = p.speech
    _chinese_without_a_voice(s, qapp)
    monkeypatch.setattr(s.ctl, "start_live", lambda mod, args=(): None)
    monkeypatch.setattr(type(s.ctl), "live", property(lambda self: True))
    s.module = s.module or object()
    s._toggle_live(True)
    assert s.ctl.live_voice is None                # nothing speaks Chinese yet
    old = frozenset({"MSTTS_V110_enUS_ZiraM"})
    s._voice_fp = old
    monkeypatch.setattr(winvoices, "fingerprint", lambda: old)
    s._poll_voices()                               # nothing changed: no reload
    assert not s._loading()
    _huihui_arrives(monkeypatch)
    monkeypatch.setattr(winvoices, "fingerprint",
                        lambda: old | {"MSTTS_V110_zhCN_HuihuiM"})
    s._poll_voices()
    assert process_events(qapp, lambda: s.ctl.live_voice == "Microsoft Huihui")
    assert "Huihui speaks" in s.lbl_state.text()


def test_update_shows_progress_and_blocks_a_second_install(panel, qapp, monkeypatch):
    from soundboard import applog
    from soundboard import modules as mods
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
    monkeypatch.setattr(applog, "report", lambda **k: None)
    s._install()
    assert not s.b_update.isEnabled() and not s.b_install.isEnabled()
    s._install()                                   # a double-click: still one pip
    assert process_events(qapp, lambda: s.b_update.isEnabled())
    assert len(started) == 1 and not s.lbl_install.isHidden()
    assert "disk full" in s.lbl_install.text() and "again" in s.lbl_install.text()
    assert s.b_update.text() == "Update speech recognition"


def test_no_update_button_without_the_addon(panel):
    p, _ = panel
    s = p.speech
    s.module = None
    s._refresh_module()
    assert s.b_update.isHidden()
    s._install()                                   # nothing to install: no thread, no crash
    assert not s._installing


def test_a_live_voice_that_cant_load_turns_the_button_back_off(panel):
    p, _ = panel
    s = p.speech
    s._set_live_ui(True, "starting…")
    s._on_event({"type": "error", "text": "no model"})
    s._on_event({"type": "stopped", "text": "no model"})
    assert not s.b_live.isChecked() and "no model" in s.lbl_state.text()
    assert s.b_update.isEnabled()


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
    from soundboard.ui.voicepanel import VoicePanel
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
    from soundboard.ui.voicepanel import VoicePanel
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
    from soundboard.ui.voicepanel import ParamSlider
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
    from soundboard.ui.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {}, {})
    try:
        m = next(m for m in p.modules if m.id == "stuck")
        assert "lo < hi" in m.error and "stuck.e" not in p.fx.rows
    finally:
        p.shutdown()
        p.deleteLater()
