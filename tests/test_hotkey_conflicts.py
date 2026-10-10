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
    assert seen and window.timer.interval() == main.TICK_QUIET_MS   # nothing playing
    monkeypatch.setattr(window.engine, "playing", lambda: {"s0": (0.5, False)})
    window.tick()
    assert window.timer.interval() == main.TICK_MS   # full pace for the overlay
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


def test_a_sound_brought_back_gives_up_a_key_an_action_took_meanwhile(window, qapp):  # noqa: F811
    """F9 went to Stop all while the pad was on the Undo bar / in Recently deleted:
    the pad comes back without it, rather than showing a key that never plays it."""
    from conftest import process_events
    from soundboard import trash
    assert process_events(qapp, lambda: all(m.id in window.audio for m in window.cfg.sounds))
    for sid, done in (("s0", window.undo_remove), ("s1", None)):
        window.meta(sid).hotkey = "f9"
        window.remove_sound(sid)
        window.set_global_hotkey("stop_hotkey", "f9")
        if done is None:   # from Recently deleted
            window._finish_removals()
            [it] = trash.items(trash.SOUND)
            assert window._restore_deleted(trash.take(it.id))
        else:
            done()
        assert window.meta(sid).hotkey == "" and window.cfg.stop_hotkey == "f9"
        window.cfg.stop_hotkey = ""


def test_the_sounds_tab_quick_hotkeys_menu(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMenu
    window.set_global_hotkey("stop_hotkey", "f9")
    menu = QMenu()
    window._fill_quick_hotkeys(menu)
    texts = [a.text() for a in menu.actions()]
    assert "Stop everything\tF9" in texts and texts[-1] == "All hotkeys…"

    class Picked:   # the key capture, answered with F10
        result_combo = "f10"

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True
    monkeypatch.setattr(main, "HotkeyDialog", Picked)
    monkeypatch.setattr(main, "free_dialog", lambda d: None)
    next(a for a in menu.actions() if a.text().startswith("Stop")).trigger()
    assert window.cfg.stop_hotkey == "f10"
    pages = []
    monkeypatch.setattr(window, "open_settings", pages.append)
    menu.actions()[-1].trigger()
    assert pages == ["hotkeys"]


def test_tab_explanations_sit_behind_one_info_button(window, monkeypatch):  # noqa: F811
    shown = []
    monkeypatch.setattr(main.TabHelpPopup, "exec", lambda box: shown.append(box.windowTitle()))
    window.tabs.setCurrentWidget(window.apps)
    assert not window.btn_info.isHidden()
    window.btn_info.click()
    assert shown == ["Send a program's sound"]
    window.tabs.setCurrentWidget(window.sounds_page)
    assert not window.btn_info.isHidden()   # every tab has a line now
    window.btn_info.click()
    assert shown[-1] == "Your sounds"
