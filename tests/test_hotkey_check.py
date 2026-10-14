"""Only hotkeys a keyboard (or a MIDI pad) can actually send are saved: any text used
to be stored and toasted as working. winkeys.check is the one rule, used by every
place a hotkey is set; old configs holding a bad one still load, without it."""
import json
import logging

import pytest
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

from soundboard import backup, library, winkeys
from soundboard.library import Config, SoundMeta

LONG = "ctrl+alt+" * 33 + "a"   # 298 characters

BAD = ["", "   ", "ünïcödé🎮", "f-1", "ctrl", "ctrl+alt", "ctrl+alt+shift+meta+f99", LONG,
       "ctrl+ctrl+a", "a+b", "ctrl+", "f25", "vk01", "vk10", "midi:nope", "midi:note x:LPD8"]
GOOD = [("F1", "f1"), ("Ctrl+1", "ctrl+1"), ("Shift+Alt+K", "alt+shift+k"),
        ("num 5", "num 5"), ("ctrl+num 0", "ctrl+num 0"), ("num +", "add"), ("num .", "num ."),
        ("play/pause media", "play/pause media"), ("next track", "next track"),
        ("volume mute", "volume mute"), ("ctrl+alt+shift+windows+z", "ctrl+alt+shift+windows+z"),
        ("`", "`"), ("ctrl++", "ctrl+="), ("alt+vke5", "alt+vke5"),
        ("midi:note 36:LPD8", "midi:note 36:LPD8")]


@pytest.mark.parametrize("combo", BAD)
def test_a_hotkey_no_keyboard_can_send_is_refused_with_a_reason(combo):
    saved, why = winkeys.check(combo)
    assert saved == "" and why


@pytest.mark.parametrize("combo, saved", GOOD)
def test_real_hotkeys_pass_as_the_backend_names_them(combo, saved):
    assert winkeys.check(combo) == (saved, "")
    if not saved.startswith("midi:"):
        assert winkeys.parse(saved) is not None


@pytest.mark.parametrize("combo, words", [
    ("ctrl", "Ctrl alone can't be a hotkey: add a key, like Ctrl+1."),
    ("ctrl+ctrl+a", "Ctrl is in that hotkey twice"),
    ("f-1", "“f-1” isn't a key"),
    ("ctrl+alt+shift+meta+f99", "“meta” isn't a key"),
    (LONG, "too long"),
    ("a+b", "this one has A + B"),
    ("   ", "needs a key"),
])
def test_the_reason_says_what_is_wrong(combo, words):
    assert words in winkeys.check(combo)[1]


def test_the_reason_is_safe_to_show_as_rich_text():
    assert "<b>" not in winkeys.check("<b>x</b>")[1]


def test_every_key_the_dialog_can_name_passes():
    for vk in range(1, 0xFF):
        if vk in winkeys.MODIFIER_VKS or vk in winkeys.MOUSE_VKS:
            continue
        combo = winkeys.combo_name(winkeys.MOD_CONTROL, vk)
        assert winkeys.check(combo) == (combo, ""), combo


@pytest.mark.parametrize("combo", ["   ", "ünïcödé🎮", "f-1", "ctrl", LONG])
def test_a_sound_keeps_its_hotkey_when_a_bad_one_is_given(window, monkeypatch, combo):  # noqa: F811
    toasts = []
    monkeypatch.setattr(window, "toast", lambda text, *a, **k: toasts.append(text))
    m = window.cfg.sounds[0]
    window.hkctl.set_sound_hotkey(m.id, "f7")
    window.hkctl.set_sound_hotkey(m.id, combo)
    assert m.hotkey == "f7"
    assert toasts[-1].startswith("Hotkey not saved: ")
    assert "plays" not in toasts[-1]


def test_a_good_hotkey_is_saved_as_the_backend_names_it(window, monkeypatch):  # noqa: F811
    toasts = []
    monkeypatch.setattr(window, "toast", lambda text, *a, **k: toasts.append(text))
    m = window.cfg.sounds[0]
    window.hkctl.set_sound_hotkey(m.id, "Shift+Alt+K")
    assert m.hotkey == "alt+shift+k" and "plays" in toasts[-1]
    window.hkctl.set_sound_hotkey(m.id, "")   # removing one is still fine
    assert m.hotkey == ""


def test_app_wide_and_category_hotkeys_refuse_bad_ones_too(window, monkeypatch):  # noqa: F811
    toasts = []
    monkeypatch.setattr(window, "toast", lambda text, *a, **k: toasts.append(text))
    window.hkctl.set_global_hotkey("stop_hotkey", "f8")
    window.hkctl.set_global_hotkey("stop_hotkey", "ctrl")
    assert window.cfg.stop_hotkey == "f8" and "Ctrl alone" in toasts[-1]
    window.hkctl.set_global_hotkey("ptt_key", "f-1")
    assert window.cfg.ptt_key == ""
    window.cfg.categories.append("Memes")
    window.hkctl.set_category_hotkey("Memes", "ctrl+ctrl+m")
    assert "Memes" not in window.cfg.category_hotkeys
    window.hkctl.set_category_hotkey("Memes", "ctrl+m")
    assert window.cfg.category_hotkeys["Memes"] == "ctrl+m"


def test_an_old_config_with_bad_hotkeys_still_loads_without_them(app_dir, caplog):
    library.CONFIG_PATH.write_text(json.dumps({
        "stop_hotkey": "ctrl", "pause_hotkey": "f9", "ptt_key": "   ",
        "category_hotkeys": {"Memes": "ünïcödé🎮", "Fun": "ctrl+f"},
        "categories": ["Memes", "Fun"],
        "sounds": [{"id": "a", "name": "A", "file": "a.wav", "hotkey": "f-1"},
                   {"id": "b", "name": "B", "file": "b.wav", "hotkey": "Ctrl+1"}],
    }), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = Config.load()
    assert cfg.stop_hotkey == "" and cfg.pause_hotkey == "f9" and cfg.ptt_key == ""
    assert cfg.category_hotkeys == {"Fun": "ctrl+f"}
    assert [m.hotkey for m in cfg.sounds] == ["", "Ctrl+1"]   # a good one stays as written
    assert "f-1" in caplog.text


def test_a_backup_or_pack_sound_with_a_bad_hotkey_comes_in_without_it():
    m = SoundMeta(id="x", name="X", file="x.wav")
    backup._apply_entry(m, {"hotkey": "ctrl+alt+shift+meta+f99"}, None)
    assert m.hotkey == ""
    backup._apply_entry(m, {"hotkey": "num 3"}, None)
    assert m.hotkey == "num 3"


def test_imported_settings_drop_a_bad_app_wide_hotkey():
    assert library.clean_setting("stop_hotkey", "f-1") == ""
    assert library.clean_setting("stop_hotkey", "ctrl+alt+s") == "ctrl+alt+s"
