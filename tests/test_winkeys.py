import pytest

from soundboard import winkeys as wk


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


# ---------------------------------------------------------------- SendInput records

def test_key_sequence_orders_modifiers_around_the_key():
    down = wk.key_sequence("ctrl+shift+v", up=False)
    up = wk.key_sequence("ctrl+shift+v", up=True)
    assert down == [(0x11, False), (0x10, False), (ord("V"), False)]
    assert up == [(ord("V"), True), (0x10, True), (0x11, True)]
    assert wk.key_sequence("nope", up=False) is None


def test_key_input_record_flags():
    plain = wk.key_input(ord("V"), up=False)
    assert plain.type == wk.INPUT_KEYBOARD and plain.ki.wVk == ord("V")
    assert plain.ki.dwFlags == 0 and plain.ki.wScan != 0
    ext_up = wk.key_input(0x2E, up=True)                  # Delete: extended key
    assert ext_up.ki.dwFlags == wk.KEYEVENTF_KEYUP | wk.KEYEVENTF_EXTENDEDKEY


# ---------------------------------------------------------------- live registration

def test_register_reports_combos_another_thread_owns(qapp):
    from conftest import process_events
    combo = "ctrl+alt+shift+f24"                          # nothing on a PC uses this
    a, b = wk.Hotkeys(), wk.Hotkeys()
    assert a.alive and b.alive
    got = {"a": None, "b": None}
    a.failed_changed.connect(lambda f: got.__setitem__("a", f))
    b.failed_changed.connect(lambda f: got.__setitem__("b", f))
    try:
        a.register({combo: "x"})
        assert process_events(qapp, lambda: got["a"] is not None, 3)
        assert got["a"] == []                             # a owns it now
        b.register({combo: "y"})
        assert process_events(qapp, lambda: got["b"] is not None, 3)
        assert got["b"] == [combo]                        # ...so b can't
        got["a"] = None
        a.register({})
        assert process_events(qapp, lambda: got["a"] is not None, 3)   # a has let go...
        got["b"] = None
        b.register({combo: "y"})
        assert process_events(qapp, lambda: got["b"] is not None, 3)
        assert got["b"] == []                             # released: b gets it
    finally:
        a.register({})
        b.register({})
        process_events(qapp, lambda: False, 0.2)
        a.stop()
        b.stop()


def test_numpad_plus_round_trips():
    """Its old name "num +" contained the separator, so it could never be registered."""
    vk = wk.VK["num +"]
    name = wk.combo_name(wk.MOD_CONTROL, vk)
    assert "+" not in name.split("+", 1)[1]
    assert wk.parse(name) == (wk.MOD_CONTROL, vk)
    assert wk.parse("ctrl+num +") == (wk.MOD_CONTROL, vk)   # saved by 0.x
