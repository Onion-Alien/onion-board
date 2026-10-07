"""The Voice panel, offscreen: presets reach the chain, settings round-trip."""
import numpy as np
import pytest

from soundboard import voicefx
from soundboard.speech import tts
from tests.conftest import process_events


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
    # mic clean-up is your own setting (on to start with), ahead of the voice's effects
    assert [e.type for e in p.chain._effects] == ["cleanup", "robot", "compressor", "reverb"]


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
    assert not p.fx.btn_power.isChecked() and "OFF" in p.fx.btn_power.text()
    p.fx.pick("Deep voice")                  # picking a voice turns it on
    assert p.fx.btn_power.isChecked() and "ON" in p.fx.btn_power.text()
    assert p.fx._tile["Deep voice"].isChecked()
    p.fx.btn_power.setChecked(False)         # the switch turns it off, voice kept
    assert not seen[-1]["enabled"] and seen[-1]["preset"] == "Deep voice"
    assert not p.fx._tile["Deep voice"].isChecked()   # nothing looks selected while off
    assert not hasattr(p.fx, "btn_hear")     # one switch for hearing it: the mixer's


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
        assert p.speech.lang_box.isHidden() and not p.speech.missing.isHidden()


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
    assert codes[0] == "" and {"zh", "es", "fr", "de", "ru", "ja", "pt-BR", "zh-TW"} <= set(codes)
    assert len(codes) == 34
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
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    s._remove_download()                         # asks, then "Deleting…" on the button
    process_events(QApplication.instance(), lambda: not d.exists())
    assert "(download" in s.cb_lang.currentText()


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
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
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


def test_discord_notice_shows_with_the_changer_on_until_dismissed(panel):
    p, _ = panel
    fx = p.fx
    assert fx.tip.isHidden()                     # changer off: nothing to warn about
    fx.pick(next(iter(voicefx.PRESETS)))
    assert not fx.tip.isHidden()
    helped, dismissed = [], []
    fx.chat_help.connect(lambda: helped.append(1))
    fx.tip_dismissed.connect(lambda: dismissed.append(1))
    fx.btn_tip_help.click()
    assert helped == [1] and not fx.tip.isHidden()   # the guide doesn't dismiss it
    fx.btn_tip_ok.click()
    assert dismissed == [1] and fx.tip.isHidden()
    fx.btn_power.setChecked(False)
    fx.btn_power.setChecked(True)
    assert fx.tip.isHidden()                     # stays gone once dismissed


def test_discord_notice_stays_hidden_when_already_dismissed(panel):
    p, _ = panel
    p.fx.set_tip_enabled(False)
    p.fx.pick(next(iter(voicefx.PRESETS)))
    assert p.fx.tip.isHidden()


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
    from soundboard.ui.voicepanel import VoicePanel
    mix = {"pitch": {"on": True, "semitones": 3.0}}
    p = VoicePanel(FakeEngine(), {"enabled": True, "preset": "Robot", "effects": {},
                                  "custom": mix}, {})
    try:
        p.fx.pick("Custom")
        assert p.fx.spec()["effects"]["pitch"]["semitones"] == pytest.approx(3.0)
    finally:
        p.shutdown()
        p.deleteLater()


def test_voice_tiles_reflow_in_a_narrow_window(qapp, monkeypatch):
    """Three voices a row ran off the side of a narrow window: the switch's text
    gets shorter, then two a row, then one."""
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from PySide6.QtWidgets import QWidget

    from soundboard.ui.voicepanel import POWER_SHORT, POWER_TEXT, VoiceFxPanel
    holder = QWidget()                 # inside the tab, it gets the width there is
    fx = VoiceFxPanel({})
    fx.setParent(holder)
    holder.show()
    fx.setGeometry(0, 0, 1600, 600)   # (test fonts run wide)
    assert fx._tile_cols == 3 and fx.btn_power.text() == POWER_TEXT[False]
    for width in (420, 260):
        fx.setGeometry(0, 0, width, 1200)
        assert fx._tile_cols < 3 and fx.btn_power.text() == POWER_SHORT[False]
        qapp.processEvents()
        assert max(b.geometry().right() for b in fx.tiles.buttons()) <= fx.width()
    fx.setGeometry(0, 0, 1600, 600)
    assert fx._tile_cols == 3 and fx.btn_power.text() == POWER_TEXT[False]
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
        edits = [lambda v=v: s.sl_gain.slider.setValue(v) for v in range(0, 201, 4)]
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
        assert ctl.gain == pytest.approx(2.0) and saved[-1]["gain"] == pytest.approx(2.0)
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
    return [w.text() for w in sorted((g.itemAt(i).widget() for i in range(g.count())),
                                     key=lambda w: g.getItemPosition(g.indexOf(w))[:2])]


def test_random_voice_opens_fine_tune_with_what_it_set_lit_up(panel):
    import random
    p, _ = panel
    assert not p.fx.dlg.isVisible()
    p.fx.btn_random.click()                  # the dice is in Make it yours
    assert p.fx.dlg.isVisible() and p.fx.preset == "Custom"
    p.fx.randomize(random.Random(3))
    on = {t for t, r in p.fx.rows.items() if r.chk.isChecked() and t != "cleanup"}
    lit = {t for t, r in p.fx.rows.items() if r.is_fresh()}
    assert lit == on and "pitch" in lit
    p.fx.pick("Robot")                       # gone as soon as you move on...
    assert not any(r.is_fresh() for r in p.fx.rows.values())
    p.fx.randomize(random.Random(4))
    p.fx._fresh_timer.timeout.emit()         # ...or after a few seconds
    assert not any(r.is_fresh() for r in p.fx.rows.values())


def test_my_own_mix_is_the_last_tile_and_voices_have_pictures(panel):
    from soundboard.ui import art
    p, _ = panel
    order = _grid_order(p.fx)
    assert order[-1] == "My own mix" and "Random voice" not in order
    assert p.fx.btn_random.window() is p.fx.dlg     # Randomize lives in Make it yours
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
    assert _grid_order(p.fx)[-2:] == ["My own mix", "Squeaky"]
    assert p.fx.spec()["custom"] == mine           # "My own mix" is still that mix
    p.fx.pick("Robot")
    p.fx.pick("Squeaky")
    assert p.fx.spec()["effects"] == mine
    # a restart: the tile is there and still the one that's on
    from soundboard.ui.voicepanel import VoiceFxPanel
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
    assert "One" not in p.fx._tile and p.fx.undo_bar.isVisibleTo(p.fx)
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
    from soundboard.ui import deleted
    seen = []

    def fake_exec(dlg):
        seen.append(dlg.list.item(0).text())
        dlg.list.setCurrentRow(0)
        dlg.bring_back()
    monkeypatch.setattr(deleted.DeletedDialog, "exec", fake_exec)
    p.fx.show_deleted()
    assert seen[0].startswith("One") and "One" in p.fx._tile
    assert p.fx.btn_bin.isHidden()


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

    from soundboard import savedvoices
    from soundboard.ui.voicepanel import VoiceFxPanel
    store = savedvoices.Store()
    for n in ("A", "B"):
        store.put(n, {})
    holder = QWidget()
    fx = VoiceFxPanel({}, store)
    fx.setParent(holder)
    holder.show()
    fx.setGeometry(0, 0, 260, 1600)
    qapp.processEvents()
    assert _grid_order(fx)[-3:] == ["My own mix", "A", "B"]
    assert max(b.geometry().right() for b in fx.tiles.buttons()) <= fx.width()
    holder.hide()


def test_mic_cleanup_stays_as_you_set_it_whatever_voice_you_pick(panel):
    p, _ = panel
    clean = p.fx.rows["cleanup"]
    assert clean.chk.isChecked()                  # on to start with
    p.fx.pick("Robot")
    clean.chk.setChecked(False)                   # switched off: Robot stays picked
    assert p.fx.preset == "Robot"
    for name in ("Chipmunk", "Custom"):
        p.fx.pick(name)
        assert not clean.chk.isChecked()
    import random
    p.fx.randomize(random.Random(1))
    assert not clean.chk.isChecked()
    assert not p.fx.spec()["effects"]["cleanup"]["on"]


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
    fx.pick("Robot")                              # no pitch: only the clean-up's frame
    small = fx.effects_delay()
    fx.pick("Deep voice")                         # pitch + natural formants cost the most
    big = fx.effects_delay()
    assert 5 < small < 20 and 50 < big < 100
    fx.set_device_delay(30.0)
    assert not fx.delay.isHidden() and f"{big + 30:.0f} ms" in fx.delay.text()


def test_switch_settings_and_cards_round_trip(panel):
    p, _ = panel
    p.fx.pick("Walkie-talkie")
    radio = p.fx.rows["radio"]
    squelch = next(s for s in radio.sliders if s.q.key == "squelch")
    assert squelch.switch is not None and squelch.slider is None and squelch.value() == 1
    squelch.switch.setChecked(False)
    assert p.fx.spec()["effects"]["radio"]["squelch"] == 0
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
    s = p.fx.rows["robot"].sliders[0].slider
    for v in range(s.minimum(), s.minimum() + 10):
        s.setValue(v)
    assert len(rebuilds) == 10 and sent == [True]   # was 2 rebuilds + a send a step
    p.chain.errors["robot"] = "boom"                # a bypassed effect: another go
    s.setValue(s.value() + 1)
    assert not p.chain.errors and len(rebuilds) == 11
    p.fx.btn_power.setChecked(False)
    assert sent == [True, False]


def test_effects_that_never_delay_the_voice_arent_built_to_ask(panel, monkeypatch):
    p, _ = panel
    built = []
    for etype, cls in voicefx.REGISTRY.items():
        real = cls.__init__
        monkeypatch.setattr(cls, "__init__", lambda self, *a, _r=real, _t=etype, **k: (
            built.append(_t), _r(self, *a, **k))[1])
    p.fx.pick("Robot")                  # no mic yet: only the delay readout builds any
    assert p.fx.effects_delay() > 0
    assert "robot" not in built         # its latency() is the base one: always 0
    assert all(voicefx.REGISTRY[t].latency is not voicefx.Effect.latency for t in built)


def test_add_ons_refresh_scans_the_disk_off_the_ui_thread(panel, qapp, monkeypatch):
    import threading

    from soundboard.ui import busy
    from soundboard.ui import voicepanel as vp
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
    from soundboard.ui import busy
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


def test_resizing_within_one_shape_does_no_layout_passes(panel, monkeypatch):
    p, _ = panel
    fx = p.fx
    fx._fit_width(1100)
    shapes = []
    real = type(fx)._set_shape
    monkeypatch.setattr(type(fx), "_set_shape",
                        lambda self, *a: (shapes.append(a), real(self, *a))[1])
    for w in range(1100, 1000, -4):     # roomy all the way: nothing to try
        fx._fit_width(w)                # what each resize step does
    assert shapes == []
    fx._fit_width(250)                  # narrower than anything: tried, then left alone
    tried = len(shapes)
    assert tried and (fx._short, fx._tile_cols) == (True, 1)
    for w in range(250, 200, -4):
        fx._fit_width(w)
    assert len(shapes) == tried
    fx._fit_width(1100)
    assert (fx._short, fx._tile_cols) == (False, fx.COLS)


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
    from soundboard.ui.voicepanel import param_text
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


def test_cards_fold_away_and_stay_folded(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {}, {"folded": ["ai", 7, "later"]})   # 7: junk
    try:
        assert p.ai.isHidden() and not p.fx.isHidden() and not p.speech.isHidden()
        saved = []
        p.speech_changed.connect(saved.append)
        p._heads["fx"].arrow.click()                 # fold the voice changer
        assert p.fx.isHidden() and saved[-1]["folded"] == ["ai", "fx", "later"]
        p._heads["ai"].arrow.click()                 # and open the AI voices again
        # "later": a newer version's card, kept for it
        assert not p.ai.isHidden() and saved[-1]["folded"] == ["fx", "later"]
        p.fx.pick("Robot")                           # folded, it still says it's on
        assert p._heads["fx"].pill.text() == "On"
    finally:
        p.shutdown()
        p.deleteLater()


def test_the_voice_thats_on_speaks_the_language_picked(panel, monkeypatch):
    """Speak in belongs to the whole tab: the AI voice gets the translated lines,
    else the voice changer (real mic muted); text-to-speech's own Start wins."""
    from types import SimpleNamespace
    p, _ = panel
    sp = p.speech
    asked = []
    monkeypatch.setattr(sp, "translate_for", asked.append)
    p._sync_translate()
    assert asked[-1] == "" and sp.ctl.dub is None             # English: nothing to do
    de = SimpleNamespace(language="de", language_name="German")
    monkeypatch.setattr(sp, "translating", lambda: de)
    p._sync_translate()
    assert asked[-1] == "" and "Turn on the AI voice" in sp.lbl_bg.text()
    p.fx.pick("Robot")
    assert asked[-1] == "fx" and sp.ctl.fx_always and sp.ctl.dub is None
    assert "German, a few seconds late" in p._heads["fx"].pill.text()
    monkeypatch.setattr(p.ai, "is_on", lambda: True)
    p._sync_translate()
    assert asked[-1] == "ai" and sp.ctl.dub is p.ai_controller and p.ai_controller.dub_on
    sp.b_live.blockSignals(True)
    sp.b_live.setChecked(True)
    sp.b_live.blockSignals(False)
    p._sync_translate()
    assert asked[-1] == "" and sp.ctl.dub is None and not p.ai_controller.dub_on


# ---------------------------------------------------------------- Make it yours window

def test_the_card_is_just_the_switch_the_voices_and_one_button(panel):
    p, _ = panel
    fx = p.fx
    on_card = [w for w in (fx.btn_power, fx.meter, fx.btn_tweak, *fx.tiles.buttons())]
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
    from soundboard.ui.voicepanel import VoiceFxPanel
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
    strip = {t: e for t, e in sound.items() if t != "cleanup"}
    assert {t: e for t, e in p.fx.spec()["effects"].items() if t != "cleanup"} == strip


def test_importing_junk_says_why_and_adds_nothing(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    p, _ = panel
    said = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: said.append(a[2]))
    assert p.fx.import_code("OB1-not-a-real-code") == ""
    assert said and not p.fx.store.voices
    # a built-in voice's name gets "(shared)"; saying No adds nothing
    from soundboard import savedvoices
    code = savedvoices.share_code("Robot", {"robot": {"on": True}})
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.No)
    assert p.fx.import_code(code) == "" and not p.fx.store.voices
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    assert p.fx.import_code(code) == "Robot (shared)"


def test_copy_from_a_tile_with_the_window_closed_says_so(panel, monkeypatch):
    p, _ = panel
    _ask(monkeypatch, "Mine", "Other")
    p.fx.save_voice()
    p.fx.save_voice()
    p.fx.copy_code("Mine")
    assert p.fx.undo_bar.isVisibleTo(p.fx) and p.fx.undo_bar.btn_undo.isHidden()
    p.fx.delete_voice("Mine")                        # a real Undo shows its button again
    assert not p.fx.undo_bar.btn_undo.isHidden()


def test_make_it_yours_buttons_are_at_the_top(panel):
    fx = panel[0].fx
    tools = fx.btn_random.parentWidget()
    for b in (fx.btn_save, fx.btn_share, fx.btn_import, fx.btn_bin):
        assert b.parentWidget() is tools                     # one row of buttons...
    assert fx.tweak.layout().indexOf(tools) == 0             # ...first in the window


def test_effect_cards_fold_and_stay_folded(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voicepanel import VoicePanel
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
    """Two columns, each card under the shorter one: no hole beside a short card,
    and the columns end close together, after a voice pick and after folding."""
    fx = panel[0].fx
    fx.open_tweak()
    fx.dlg.resize(800, 700)

    def check():
        for _ in range(3):
            qapp.processEvents()
        assert fx._fx_cols == 2
        cols = [[col.itemAt(i).widget() for i in range(col.count() - 1)]
                for col in fx._fx_columns]
        assert sorted(len(c) for c in cols)[0] >= 3
        assert not any(lbl.isVisible() for lbl in fx._groups.values())
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
    fx.dlg.resize(500, 700)                                   # one column: titles back
    for _ in range(3):
        qapp.processEvents()
    assert fx._fx_cols == 1 and fx._groups["Character"].isVisible()
    fx.dlg.close()


def _remembered(names_langs, fp):
    names = [n for n, _ in names_langs]
    return tts.remember_voices(names, dict(names_langs), fp)


def test_a_launch_with_the_same_windows_voices_starts_no_speech_helper(qapp, monkeypatch):
    """The voice list is remembered with the Windows voices it was listed for: the
    next launch shows it without starting PowerShell (~2 s, 85 MB) just to list them."""
    from soundboard.speech import winvoices
    from soundboard.ui.voicepanel import VoicePanel
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
    from soundboard.ui.voicepanel import VoicePanel
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
