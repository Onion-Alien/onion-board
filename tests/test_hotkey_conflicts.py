"""Hotkeys that would fight each other: the game's push-to-talk key, the overlay's own
keys and the keyboard layout under the default overlay key. Headless (the real
MainWindow on Qt's offscreen platform, no hotkeys registered)."""
from soundboard import winkeys
from soundboard.library import Config
from soundboard.ui import mainwindow as main
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def registered(window, monkeypatch):  # noqa: F811
    sent = []
    monkeypatch.setattr(window.hotkeys, "register", lambda m: sent.append(dict(m)))
    window.register_hotkeys()
    return sent[-1]


def test_the_push_to_talk_key_is_never_one_of_our_hotkeys(window, monkeypatch):  # noqa: F811
    window.set_global_hotkey("pause_hotkey", "v")
    window.set_global_hotkey("ptt_key", "v")          # PTT takes it off the pause action
    assert window.cfg.pause_hotkey == "" and window.cfg.ptt_key == "v"
    window.set_global_hotkey("pause_hotkey", "v")     # and the other way round
    assert window.cfg.ptt_key == ""
    window.cfg.ptt_key = window.cfg.overlay_hotkey    # an old config with both the same
    assert window.cfg.ptt_key not in registered(window, monkeypatch)


def test_the_overlay_follows_whats_playing_with_the_window_in_the_tray(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(winkeys, "exclusive_fullscreen", lambda: False)
    monkeypatch.setattr(window.hotkeys, "register", lambda m: None)
    window.show()                 # offscreen: nothing appears
    window.hide()                 # into the tray
    assert not window._ui_live
    window.on_hotkey("__overlay__")
    seen = []
    monkeypatch.setattr(window.overlay, "tick", seen.append)
    window.tick()
    assert seen and window.timer.interval() == main.TICK_MS   # full pace for the overlay
    window.on_hotkey("__ov:close")
    window.tick()
    assert window.timer.interval() == main.TICK_IDLE_MS


def test_a_numpad_overlay_key_still_closes_it(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(winkeys, "exclusive_fullscreen", lambda: False)
    window.cfg.overlay_hotkey = "num 0"
    window.overlay.s.keys = "numpad"
    window.on_hotkey("__overlay__")
    assert registered(window, monkeypatch)["num 0"] == "__overlay__"
    window.on_hotkey("__ov:close")


def test_the_default_overlay_key_moves_off_a_letter_on_other_layouts(qapp, app_dir, monkeypatch):
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(main.Engine, name, lambda self, n: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    monkeypatch.setattr(winkeys, "key_char", lambda vk: "ö" if vk == 0xC0 else "")  # German
    Config().save()
    w = main.MainWindow()
    try:
        w._load_thread.join(15)
        assert w.cfg.overlay_hotkey == "alt+`" and w.cfg.overlay_key_checked
        w.cfg.overlay_hotkey = "`"               # picked again on purpose: left alone
        w._fit_overlay_key()
        assert w.cfg.overlay_hotkey == "`"
    finally:
        w.close()
        w._load_thread.join(15)
        w.deleteLater()


def test_a_us_layout_keeps_the_backtick(window):  # noqa: F811
    assert window.cfg.overlay_hotkey == "`" and window.cfg.overlay_key_checked


def test_a_blocked_ptt_key_up_is_tried_again(window, monkeypatch):  # noqa: F811
    """An admin window in front makes Windows drop the key-up: the app must keep
    trying, not forget it holds the key (the game's PTT would stay stuck down)."""
    ok = {"up": False}
    ups = []
    monkeypatch.setattr(main.winkeys, "release", lambda k: ups.append(k) or ok["up"])
    window._ptt_held = "v"
    assert window._release_ptt() is False and window._ptt_held == "v"
    ok["up"] = True
    assert window._release_ptt() is True and window._ptt_held is None
    assert ups == ["v", "v"]
