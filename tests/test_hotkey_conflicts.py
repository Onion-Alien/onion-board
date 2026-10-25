"""Hotkeys that would fight each other: the game's push-to-talk key, the overlay's own
keys and the keyboard layout under the default overlay key. Headless (the real
MainWindow on Qt's offscreen platform, no hotkeys registered)."""
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

from soundboard.control import winkeys
from soundboard.sounds.library import Config
from soundboard.ui.window import hotkeycontrol, tickcontrol
from soundboard.ui.window import mainwindow as main
from soundboard.ui.sounds.dialogs import TabHelpPopup


def registered(window, monkeypatch):  # noqa: F811
    sent = []
    monkeypatch.setattr(window.hotkeys, "register", lambda m: sent.append(dict(m)))
    window.hkctl.register_hotkeys()
    return sent[-1]


def test_the_push_to_talk_key_is_never_one_of_our_hotkeys(window, monkeypatch):  # noqa: F811
    window.hkctl.set_global_hotkey("pause_hotkey", "v")
    window.hkctl.set_global_hotkey("ptt_key", "v")          # PTT takes it off the pause action
    assert window.cfg.pause_hotkey == "" and window.cfg.ptt_key == "v"
    window.hkctl.set_global_hotkey("pause_hotkey", "v")     # and the other way round
    assert window.cfg.ptt_key == ""
    window.cfg.ptt_key = window.cfg.overlay_hotkey    # an old config with both the same
    assert window.cfg.ptt_key not in registered(window, monkeypatch)


def test_the_overlay_follows_whats_playing_with_the_window_in_the_tray(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(winkeys, "exclusive_fullscreen", lambda: False)
    monkeypatch.setattr(window.hotkeys, "register", lambda m: None)
    window.show()                 # offscreen: nothing appears
    window.hide()                 # into the tray
    assert not window._ui_live
    window.hkctl.on_hotkey("__overlay__")
    seen = []
    monkeypatch.setattr(window.overlay, "tick", seen.append)
    window.tickctl.tick()
    assert seen and window.timer.interval() == tickcontrol.TICK_QUIET_MS   # nothing playing
    monkeypatch.setattr(window.engine, "playing", lambda: {"s0": (0.5, False)})
    window.tickctl.tick()
    assert window.timer.interval() == tickcontrol.TICK_MS   # full pace for the overlay
    window.hkctl.on_hotkey("__ov:close")
    window.tickctl.tick()
    assert window.timer.interval() == tickcontrol.TICK_IDLE_MS


def test_a_numpad_overlay_key_still_closes_it(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(winkeys, "exclusive_fullscreen", lambda: False)
    window.cfg.overlay_hotkey = "num 0"
    window.overlay.s.keys = "numpad"
    window.hkctl.on_hotkey("__overlay__")
    assert registered(window, monkeypatch)["num 0"] == "__overlay__"
    window.hkctl.on_hotkey("__ov:close")


def test_the_default_overlay_key_moves_off_a_letter_on_other_layouts(qapp, app_dir, monkeypatch):
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(main.Engine, name, lambda self, n: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    monkeypatch.setattr(winkeys, "key_char", lambda vk: "ö" if vk == 0xC0 else "")  # German
    Config().save()
    w = main.MainWindow()
    try:
        w.soundctl._load_thread.join(15)
        assert w.cfg.overlay_hotkey == "alt+`" and w.cfg.overlay_key_checked
        w.cfg.overlay_hotkey = "`"               # picked again on purpose: left alone
        w.hkctl._fit_overlay_key()
        assert w.cfg.overlay_hotkey == "`"
    finally:
        w.close()
        w.soundctl._load_thread.join(15)
        w.deleteLater()


def test_a_us_layout_keeps_the_backtick(window):  # noqa: F811
    assert window.cfg.overlay_hotkey == "`" and window.cfg.overlay_key_checked


def test_a_blocked_ptt_key_up_is_tried_again(window, monkeypatch):  # noqa: F811
    """An admin window in front makes Windows drop the key-up: the app must keep
    trying, not forget it holds the key (the game's PTT would stay stuck down)."""
    ok = {"up": False}
    ups = []
    monkeypatch.setattr(winkeys, "release", lambda k: ups.append(k) or ok["up"])
    window._ptt_held = "v"
    assert window.hkctl._release_ptt() is False and window._ptt_held == "v"
    ok["up"] = True
    assert window.hkctl._release_ptt() is True and window._ptt_held is None
    assert ups == ["v", "v"]


def test_the_ptt_key_is_let_go_when_the_ticks_stop(monkeypatch):
    """Windows never lets go of a key a program pressed when it freezes or crashes:
    a frozen UI thread left the game's push-to-talk (the mic) open."""
    keys = []
    monkeypatch.setattr(winkeys, "press", lambda k: keys.append(("press", k)) or True)
    monkeypatch.setattr(winkeys, "release", lambda k: keys.append(("release", k)) or True)
    monkeypatch.setattr(winkeys, "_ptt_watch", [object()])   # no real watch thread
    assert winkeys.ptt_down("v")
    beat = winkeys._ptt["beat"]
    winkeys._let_go_stale(beat + winkeys.HOLD_STALE_S / 2)   # still ticking
    assert winkeys.ptt_held() == "v"
    winkeys._let_go_stale(beat + winkeys.HOLD_STALE_S + 1)   # stuck
    assert winkeys.ptt_held() is None and keys == [("press", "v"), ("release", "v")]


def test_a_sound_brought_back_gives_up_a_key_an_action_took_meanwhile(window, qapp):  # noqa: F811
    """F9 went to Stop all while the pad was on the Undo bar / in Recently deleted:
    the pad comes back without it, rather than showing a key that never plays it."""
    from conftest import process_events

    from soundboard.core import trash
    assert process_events(qapp, lambda: all(m.id in window.audio for m in window.cfg.sounds))
    for sid, done in (("s0", window.rmctl.undo_remove), ("s1", None)):
        window.meta(sid).hotkey = "f9"
        window.rmctl.remove_sound(sid)
        window.hkctl.set_global_hotkey("stop_hotkey", "f9")
        if done is None:   # from Recently deleted
            window.rmctl._finish_removals()
            window.rmctl._wait_bin()
            [it] = trash.items(trash.SOUND)
            assert window.rmctl._restore_deleted(trash.take(it.id))
        else:
            done()
        assert window.meta(sid).hotkey == "" and window.cfg.stop_hotkey == "f9"
        window.cfg.stop_hotkey = ""


def test_the_sounds_tab_quick_hotkeys_menu(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMenu
    window.hkctl.set_global_hotkey("stop_hotkey", "f9")
    menu = QMenu()
    window.hkctl._fill_quick_hotkeys(menu)
    texts = [a.text() for a in menu.actions()]
    assert "Stop everything\tF9" in texts and texts[-1] == "All hotkeys"

    class Picked:   # the key capture, answered with F10
        result_combo = "f10"

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True
    monkeypatch.setattr(hotkeycontrol, "HotkeyDialog", Picked)
    monkeypatch.setattr(hotkeycontrol, "free_dialog", lambda d: None)
    next(a for a in menu.actions() if a.text().startswith("Stop")).trigger()
    assert window.cfg.stop_hotkey == "f10"
    pages = []
    monkeypatch.setattr(window.setctl, "open_settings", pages.append)
    menu.actions()[-1].trigger()
    assert pages == ["hotkeys"]


def test_tab_explanations_are_in_each_tabs_right_click_menu(window, monkeypatch):  # noqa: F811
    shown = []
    monkeypatch.setattr(TabHelpPopup, "exec", lambda box: shown.append(box.windowTitle()))
    for page, title in ((window.apps, "Send a program's sound"),
                        (window.sounds_page, "Your sounds")):
        menu = window.tabctl.tab_menu(window.tabs.indexOf(page))
        about = menu.actions()[0]
        assert about.text() == "About this tab"
        about.trigger()
        assert shown[-1] == title


def test_every_tab_has_an_about_this_tab(window):  # noqa: F811
    """Community's right-click had no About this tab: every other tab did."""
    for i in range(window.tabs.count()):
        menu = window.tabctl.tab_menu(i)
        assert menu.actions()[0].text() == "About this tab", window.tabs.widget(i)


def test_auto_ptt_goes_down_with_the_sound_not_on_the_next_tick(window, qapp, monkeypatch):  # noqa: F811
    """Minimised, the tick runs every TICK_IDLE_MS: pressing the game's PTT key there
    let the start of every sound out before the key was held (a game that only sends
    while it's held cut it). The key goes down as the sound starts."""
    from conftest import process_events
    assert process_events(qapp, lambda: "s0" in window.audio)
    keys = []
    monkeypatch.setattr(winkeys, "press", lambda k: keys.append(("press", k)) or True)
    monkeypatch.setattr(winkeys, "release", lambda k: keys.append(("release", k)) or True)
    window.timer.stop()                 # no tick from here: only the play itself
    window.cfg.ptt_key = "v"
    window.engine.sending = True

    class _Out:   # an open "send to others" output, so the sound really starts
        def stop(self):
            pass
        close = stop
    monkeypatch.setattr(window.engine, "main_stream", _Out())
    window.playctl.play("s0")
    assert keys == [("press", "v")] and window._ptt_held == "v"


def test_the_overlay_page_names_its_hotkey(window, qapp):  # noqa: F811
    """Settings > Overlay is built after Hotkeys: its hotkey button still says the key
    (it was blank)."""
    from soundboard.ui.settings.keys import pretty_key
    window.cfg.overlay_hotkey = "alt+`"
    d = window.setctl.open_settings("hotkeys")
    d.show_page("overlay")
    qapp.processEvents()
    buttons = d.hk_buttons["overlay_hotkey"]
    assert buttons and all(b.text() == pretty_key("alt+`") for b in buttons)


def test_narrow_hotkey_rows_put_the_key_under_the_words(window, qapp):  # noqa: F811
    """Settings > Hotkeys in a narrow window: each key button goes under its words (beside
    them, the words got a word a line); wide, back beside them."""
    from PySide6.QtWidgets import QApplication
    window.show()
    d = window.setctl.open_settings("hotkeys")
    b = d.hk_buttons["stop_hotkey"][0] if "stop_hotkey" in d.hk_buttons \
        else next(iter(d.hk_buttons.values()))[0]
    for width, under in ((440, True), (1280, False)):
        window.resize(width, 700)
        for _ in range(20):
            QApplication.processEvents()
        row = b.parentWidget()
        words = row.layout().itemAt(0).layout().itemAt(0).widget()
        assert (b.y() > words.y() + words.height() - 1) == under, width
