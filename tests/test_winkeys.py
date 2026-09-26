import pytest

import winkeys as wk


@pytest.mark.parametrize("combo, mods, vk", [
    ("ctrl+alt+s", wk.MOD_CONTROL | wk.MOD_ALT, ord("S")),
    ("f5", 0, 0x74),
    ("shift+num 1", wk.MOD_SHIFT, 0x61),
    ("windows+esc", wk.MOD_WIN, 0x1B),
    ("Ctrl+Alt+S", wk.MOD_CONTROL | wk.MOD_ALT, ord("S")),     # case-insensitive
    ("control+escape", wk.MOD_CONTROL, 0x1B),                   # aliases
    ("ctrl+vk1b", wk.MOD_CONTROL, 0x1B),                        # raw vk fallback
    ("ctrl++", wk.MOD_CONTROL, 0xBB),                           # "+" key itself
])
def test_parse(combo, mods, vk):
    assert wk.parse(combo) == (mods, vk)


@pytest.mark.parametrize("combo", ["", "ctrl", "ctrl+", "nope", "ctrl+vkzz", "ctrl+alt"])
def test_parse_rejects_garbage(combo):
    assert wk.parse(combo) is None


@pytest.mark.parametrize("combo", ["ctrl+alt+s", "f5", "shift+num 1", "windows+esc",
                                   "alt+page down", "ctrl+alt+shift+windows+a", "=", "num ."])
def test_combo_name_round_trips(combo):
    mods, vk = wk.parse(combo)
    assert wk.combo_name(mods, vk) == combo


def test_unknown_vk_gets_hex_name_that_parses_back():
    name = wk.combo_name(wk.MOD_ALT, 0xE5)
    assert name == "alt+vke5"
    assert wk.parse(name) == (wk.MOD_ALT, 0xE5)


def test_every_letter_and_digit_is_a_key():
    for c in "abcdefghijklmnopqrstuvwxyz0123456789":
        assert wk.parse(c) is not None
