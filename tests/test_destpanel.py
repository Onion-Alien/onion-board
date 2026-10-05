"""Settings → Audio → Who's listening, and the custom-mode editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QLabel

from soundboard import destination
from soundboard.library import Config
from soundboard.settings import SettingsDialog
from soundboard.ui.destpanel import CustomDestDialog, DestPanel, describe
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def _dest_combo(page) -> QComboBox:
    return next(cb for cb in page.findChildren(QComboBox) if cb.findData("steam") >= 0)


def test_picking_a_mode_applies_and_saves(window):  # noqa: F811
    assert window.engine.dest is None
    d = SettingsDialog(window, "audio")
    combo = _dest_combo(d.tabs.currentWidget())
    combo.setCurrentIndex(combo.findData("steam"))
    assert window.engine.dest is not None and window.engine.dest.key == "steam"
    assert window.cfg.dest["mode"] == "steam"
    assert window._save_timer.isActive()
    combo.setCurrentIndex(combo.findData("off"))
    assert window.engine.dest is None
    d.close()


def test_saved_mode_is_applied_at_startup(qapp, app_dir, monkeypatch):
    from test_mainwindow import engine, main, winkeys
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    Config(dest={"mode": "discord"}, mic_first=True).save()   # (on the cable)
    w = main.MainWindow()
    try:
        w._load_thread.join(15)
        assert w.engine.dest is not None and w.engine.dest.key == "discord"
    finally:
        w.close()


def test_custom_mode_add_edit_pick_remove(window):  # noqa: F811
    panel = DestPanel(window)
    dlg = CustomDestDialog(window, panel)
    dlg.add()
    assert len(window.cfg.dest["custom"]) == 1
    dlg.name.setText("Mumble")
    dlg.name.textEdited.emit("Mumble")
    dlg.ceiling.setCurrentIndex(dlg.ceiling.findData(16000))
    dlg.bass.setValue(30)
    dlg.mono.setChecked(False)
    raw = window.cfg.dest["custom"][0]
    assert raw["label"] == "Mumble" and raw["ceiling"] == 16000
    assert abs(raw["bass"] - 0.3) < 1e-9 and raw["mono"] is False
    assert dlg.list.item(0).text() == "Mumble"
    dlg.accept()

    panel.refresh()
    assert panel.combo.findData(raw["key"]) >= 0
    panel.combo.setCurrentIndex(panel.combo.findData(raw["key"]))
    e = window.engine.dest
    assert e is not None and e.custom and e.ceiling == 16000 and not e.mono
    assert "16 kHz" in panel.desc.text()

    # editing the mode in use reaches the engine straight away
    dlg = CustomDestDialog(window, panel)
    dlg.list.setCurrentRow(0)
    dlg.comp.setValue(80)
    assert abs(window.engine.dest.comp - 0.8) < 1e-9
    # removing it falls back to Off
    dlg.remove()
    assert window.cfg.dest["custom"] == [] and window.cfg.dest["mode"] == "off"
    assert window.engine.dest is None
    dlg.accept()
    panel.refresh()
    assert panel.combo.currentData() == "off"


def test_typing_into_the_empty_editor_makes_a_mode(window):  # noqa: F811
    """With no custom modes yet, the form is still live: the first edit creates one
    (it used to be disabled, which looked the same and just ignored typing)."""
    dlg = CustomDestDialog(window)
    assert window.cfg.dest.get("custom", []) == []
    assert dlg.name.isEnabled() and dlg.note.isEnabled() and dlg.empty.isVisibleTo(dlg)
    dlg.name.setText("Mumble")
    dlg.name.textEdited.emit("Mumble")
    dlg.bass.setValue(40)
    custom = window.cfg.dest["custom"]
    assert len(custom) == 1 and custom[0]["label"] == "Mumble"
    assert abs(custom[0]["bass"] - 0.4) < 1e-9
    assert dlg.list.count() == 1 and dlg.list.item(0).text() == "Mumble"
    assert dlg.b_del.isEnabled() and not dlg.empty.isVisibleTo(dlg)
    dlg.accept()


def test_copy_builtin_starts_from_its_settings(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QInputDialog
    steam = destination.BUILTIN_BY_KEY["steam"]
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (steam.label, True)))
    dlg = CustomDestDialog(window)
    dlg.copy_builtin()
    raw = window.cfg.dest["custom"][0]
    assert raw["ceiling"] == 12000 and raw["key"] not in destination.BUILTIN_BY_KEY
    assert raw["label"].endswith("(copy)")
    dlg.accept()


def test_low_cut_is_edited_and_saved(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QInputDialog
    game = destination.BUILTIN_BY_KEY["game"]
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (game.label, True)))
    dlg = CustomDestDialog(window)
    dlg.copy_builtin()
    assert dlg.lowcut.currentData() == game.lowcut
    dlg.lowcut.setCurrentIndex(dlg.lowcut.findData(90))
    assert window.cfg.dest["custom"][0]["lowcut"] == 90
    dlg.lowcut.setCurrentIndex(dlg.lowcut.findData(0))
    assert window.cfg.dest["custom"][0]["lowcut"] == 0
    dlg.accept()


def test_describe_lines():
    assert describe(destination.OFF) == destination.OFF.note
    s = describe(destination.BUILTIN_BY_KEY["steam"])
    assert "mono" in s and "12 kHz" in s and "harmonics 80%" in s
    assert "under 80 Hz" in describe(destination.BUILTIN_BY_KEY["game"])


def test_the_setup_tab_has_the_picker_and_settings_follows_it(window):  # noqa: F811
    combo = window.dest_panel.combo
    assert window.setup_page.isAncestorOf(window.dest_panel)
    combo.setCurrentIndex(combo.findData("discord"))
    assert window.engine.dest is not None and window.engine.dest.key == "discord"
    d = SettingsDialog(window, "audio")
    d.show()   # the Settings copy re-reads the mode when it appears
    assert _dest_combo(d.tabs.currentWidget()).currentData() == "discord"
    d.close()


def test_the_sounds_tab_has_a_mode_dropdown_that_follows_the_picker(window):  # noqa: F811
    mode = window.mode_combo
    assert window.sounds_page.isAncestorOf(mode)
    assert [mode.itemData(i) for i in range(mode.count())] == [
        "game", "voice", "clean", "advanced"]
    assert mode.currentData() == "clean" and mode.itemText(3) == "Advanced…"
    for i in range(mode.count()):                     # each one says what it does
        assert len(mode.itemData(i, Qt.ToolTipRole)) > 80
    mode.setCurrentIndex(mode.findData("voice"))      # picked on the Sounds tab
    assert window.engine.dest is not None and window.engine.dest.key == "discord"
    assert window.cfg.dest == {"mode": "discord", "simple": "voice", "auto": False}
    assert window._save_timer.isActive()
    assert "Voice chat: shaping for Discord." in mode.toolTip()
    window.dest_panel.refresh()                       # the Setup tab shows it
    assert window.dest_panel.buttons["voice"].isChecked()
    assert window.dest_panel.advanced.isHidden()      # the full list is Advanced's
    d = SettingsDialog(window, "audio")               # changed in Settings: it follows
    _dest_combo(d.tabs.currentWidget()).setCurrentIndex(
        _dest_combo(d.tabs.currentWidget()).findData("steam"))
    assert mode.currentData() == "advanced" and mode.itemText(3) == "Advanced: Steam voice"
    d.close()


def test_picking_advanced_on_the_sounds_tab_opens_its_settings(window, monkeypatch):  # noqa: F811
    opened = []
    monkeypatch.setattr(window, "open_settings", lambda page="privacy": opened.append(page))
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("advanced"))
    QApplication.processEvents()
    assert opened == ["audio"] and window.cfg.dest["simple"] == "advanced"
    assert window.engine.dest is None                 # kept the mode it had (Off)


def test_mode_buttons_switch_and_show_what_they_do(window):  # noqa: F811
    panel = window.dest_panel
    assert panel.buttons["clean"].isChecked() and panel.advanced.isHidden()
    assert "exactly as mixed" in panel.now.text()
    panel.buttons["game"].click()
    assert window.cfg.dest["simple"] == "game" and window.engine.dest.key == "game"
    assert "Game: shaping for Vivox" in panel.now.text()
    assert window.mode_combo.currentData() == "game"
    panel.buttons["advanced"].click()
    assert not panel.advanced.isHidden() and window.engine.dest.key == "game"
    assert panel.combo.currentData() == "game"
    panel.buttons["clean"].click()
    assert window.engine.dest is None and window.cfg.dest["mode"] == "off"


def test_what_do_these_do_lists_every_mode(window):  # noqa: F811
    from soundboard import profiles
    from soundboard.ui.destpanel import ModesHelp
    window.dest_panel.buttons["voice"].click()
    dlg = ModesHelp(window)
    text = " ".join(lbl.text() for lbl in dlg.findChildren(QLabel))
    assert "Right now:" in text and "Voice chat: shaping for Discord" in text
    for p in profiles.PROFILES:
        assert p.label in text and p.details[:40] in text
    dlg.accept()


def test_game_mode_picks_the_shaping_by_itself(window, monkeypatch):  # noqa: F811
    from soundboard import engine as eng
    monkeypatch.setattr(eng, "virtual_mic_for", lambda name: "CABLE Output (fake)")
    toasts = []
    monkeypatch.setattr(window, "toast", lambda text, kind="": toasts.append(text))
    panel = window.dest_panel
    panel.buttons["game"].click()

    class Watch:
        key = "unity"

        def poll(self):
            return self.key
    window.voice_watch = Watch()
    window.listeners = Heard()
    window._poll_voice()
    assert window.engine.dest.key == "unity" and window.cfg.dest["simple"] == "game"
    assert toasts and "Game mode" in toasts[-1] and "Unity" in toasts[-1]
    assert "The game you have open uses" in panel.now.text()
    assert panel.suggest.isHidden()
    window.voice_watch.key = None                     # the game closed: keeps it
    window._poll_voice()
    assert window.engine.dest.key == "unity"
    # Discord listening while in Game: suggested, never switched
    window.listeners.found = (("discord", "Discord"),)
    window._poll_voice()
    assert window.engine.dest.key == "unity" and not panel.suggest.isHidden()
    assert "Voice chat" in panel.suggest_text.text()
    panel.suggest_btn.click()
    assert window.cfg.dest["simple"] == "voice" and window.engine.dest.key == "discord"
    assert panel.suggest.isHidden() and panel.buttons["voice"].isChecked()


def test_custom_editor_opens_with_a_damaged_custom_list(window):  # noqa: F811
    window.cfg.dest = {"mode": "off", "custom": 5}
    dlg = CustomDestDialog(window)
    assert dlg.items == [] and window.cfg.dest["custom"] == []
    dlg.accept()
    window.cfg.dest = {"mode": "off", "custom": [3, {"key": "m", "label": "Mumble"}]}
    dlg = CustomDestDialog(window)
    assert [d["key"] for d in dlg.items] == ["m"]
    dlg.accept()


def test_main_window_starts_with_a_bad_custom_dest(qapp, app_dir, monkeypatch):
    from test_mainwindow import engine, main, winkeys
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    Config(dest={"mode": "discord", "custom": 5}).save()
    w = main.MainWindow()
    try:
        w._load_thread.join(15)
        assert w.engine.dest is not None and w.engine.dest.key == "discord"
    finally:
        w.close()


def test_the_game_in_front_suggests_its_voice_engine(window):  # noqa: F811
    panel = window.dest_panel
    panel.combo.setCurrentIndex(panel.combo.findData("discord"))
    assert panel.suggest.isHidden()

    class Watch:
        key = "game"

        def poll(self):
            return self.key
    window.voice_watch = Watch()
    window._poll_voice()
    assert window.voice_suggestion == "game" and not panel.suggest.isHidden()
    assert "Vivox" in panel.suggest_text.text()
    assert window.engine.dest.key == "discord"     # only suggested, never switched
    panel.suggest_btn.click()
    assert window.cfg.dest["mode"] == "game" and window.engine.dest.key == "game"
    assert panel.suggest.isHidden()                # already picked: nothing to suggest
    window.voice_watch.key = None                  # the game closed
    window._poll_voice()
    panel.combo.setCurrentIndex(panel.combo.findData("off"))
    assert panel.suggest.isHidden()
    d = SettingsDialog(window, "audio")            # a second picker hears it too
    window.voice_watch.key = "game"
    window._poll_voice()
    other = next(p for p in d.findChildren(DestPanel))
    assert not other.suggest.isHidden()
    d.close()


class Heard:
    """Stands in for voicesdk.Listeners: who records the cable's far end."""
    found = ()

    def poll(self, device):
        return self.found if device else ()


def test_the_program_listening_to_the_cable_beats_the_game_in_front(window, monkeypatch):  # noqa: F811
    from soundboard import engine as eng
    monkeypatch.setattr(eng, "virtual_mic_for", lambda name: "CABLE Output (fake)")
    panel = window.dest_panel

    class Watch:
        def poll(self):
            return "game"                          # Valorant in front...
    window.voice_watch = Watch()
    window.listeners = Heard()
    window.listeners.found = (("discord", "Discord"),)   # ...but Discord has the cable
    window._poll_voice()
    assert window.voice_suggestion == "discord"
    assert "Discord is listening" in panel.suggest_text.text()   # Clean: Voice chat suits
    assert "<b>Voice chat</b> mode" in panel.suggest_text.text()
    assert window.engine.dest is None              # only suggested
    panel.buttons["advanced"].click()              # Advanced suggests one exact mode
    assert "Discord is listening" in panel.suggest_text.text()
    assert "<b>Discord</b> suits it" in panel.suggest_text.text()
    window.listeners.found = (("discord", "Discord"), ("game", "Valorant"))
    window._poll_voice()
    assert window.voice_suggestion == "game"       # both: the game in front wins
    assert "Valorant is listening" in panel.suggest_text.text()


def test_switch_by_itself_follows_whoever_listens(window, monkeypatch):  # noqa: F811
    from soundboard import engine as eng
    monkeypatch.setattr(eng, "virtual_mic_for", lambda name: "CABLE Output (fake)")
    toasts = []
    monkeypatch.setattr(window, "toast", lambda text, kind="": toasts.append(text))
    panel = window.dest_panel
    window.voice_watch = None
    window.listeners = Heard()
    panel.chk_auto.setChecked(True)
    assert window.cfg.dest["auto"] is True and window.engine.dest is None
    window.listeners.found = (("discord", "Discord"),)
    window._poll_voice()
    assert window.cfg.dest["mode"] == "discord" and window.engine.dest.key == "discord"
    assert panel.combo.currentData() == "discord" and panel.suggest.isHidden()
    assert toasts and "Discord" in toasts[-1]
    window.listeners.found = ()                    # Discord closed: the mode stays
    window._poll_voice()
    assert window.engine.dest.key == "discord"
    panel.chk_auto.setChecked(False)
    window.listeners.found = (("game", "TeamSpeak"),)
    window._poll_voice()
    assert window.engine.dest.key == "discord"     # off: back to only suggesting
    assert not panel.suggest.isHidden()
