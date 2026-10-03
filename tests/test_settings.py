"""The Settings window's layout: pages scroll instead of squashing their rows."""
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea

from conftest import process_events
from soundboard import net
from soundboard.settings import SettingsDialog
from soundboard.ui import busy
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_a_short_window_scrolls_a_page_instead_of_squashing_it(window, qapp):  # noqa: F811
    d = SettingsDialog(window, "hotkeys")
    d.show()
    d.resize(2000, 700)             # wide and short, like a maximized window on a small screen
    for _ in range(5):
        qapp.processEvents()
    sa = d.tabs.currentWidget()
    assert isinstance(sa, QScrollArea)
    page = sa.widget()
    assert page.height() > sa.viewport().height()          # it scrolls
    for wdg in page.findChildren(QLabel) + page.findChildren(QPushButton):
        if wdg.isVisibleTo(page) and wdg.text():
            want = wdg.heightForWidth(wdg.width()) if wdg.hasHeightForWidth() else -1
            assert wdg.height() >= max(want, wdg.minimumSizeHint().height()), wdg.text()
    d.close()


def test_support_opens_the_project_page_not_an_address_in_the_app(window, monkeypatch):  # noqa: F811
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    d = SettingsDialog(window, "general")
    btn = next(b for b in d.findChildren(QPushButton) if "Support" in b.text())
    btn.click()
    assert opened == ["https://github.com/Onion-Alien/onion-board#support-onion-board"]
    d.close()


def test_each_page_opens_by_name_and_holds_its_cards(window):  # noqa: F811
    where = {"privacy": ("PRIVACY & SECURITY", "CONNECTION", "WHEN YOU ASK"),
             "audio": ("DEVICES", "YOUR MIC", "WHO'S LISTENING", "AUDIO BUFFERING"),
             "hotkeys": ("HOTKEY SOUNDS",),
             "general": ("WINDOW", "RUNNING IN THE BACKGROUND", "BACKUP", "ADD-ONS",
                         "FEEDBACK AND PROBLEMS",
                         "SUPPORT ONION BOARD"),
             "updates": ("APP UPDATES", "DOWNLOADER (YT-DLP)"),
             "remote": ("REMOTE CONTROL (STREAM DECK, SCRIPTS)",)}
    for page, titles in where.items():
        d = SettingsDialog(window, page)
        shown = {lb.text() for lb in d.tabs.currentWidget().widget().findChildren(QLabel)}
        assert set(titles) <= shown, page
        d.close()
    d = SettingsDialog(window, "nonsense")
    assert d.tabs.currentIndex() == 0
    d.close()


def test_audio_page_picks_input_and_output_through_the_window(window, monkeypatch):  # noqa: F811
    window._fill_combo(window.cb_mic, ["Mic A", "Headset Mic"], "Mic A")
    window._fill_combo(window.cb_mon, ["Speakers", "Headset"], "Speakers")
    picked = []
    monkeypatch.setattr(window, "on_device",
                        lambda cb, attr: picked.append((attr, cb.currentData())))
    d = SettingsDialog(window, "audio")
    mic, mon = d.dev_combos[0][0], d.dev_combos[1][0]
    assert [mic.itemText(i) for i in range(mic.count())] == ["— none —", "Mic A", "Headset Mic"]
    assert mon.currentText() == "Speakers"
    mic.activated.emit(2)
    mon.activated.emit(2)
    assert picked == [("mic_device", "Headset Mic"), ("mon_device", "Headset")]
    assert window.cb_mon.currentText() == "Headset"   # the Setup tab follows
    d.close()


def test_feedback_and_problem_buttons_only_open_the_browser(window, monkeypatch):  # noqa: F811
    from soundboard import __version__, feedback
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    d = SettingsDialog(window, "general")
    monkeypatch.setattr(feedback, "FORM_URL", "https://forms.example.com/r/x")
    d.feedback_btn.click()
    d.problem_btn.click()
    assert opened[0] == f"https://forms.example.com/r/x?version={__version__}"
    assert opened[1].startswith("https://github.com/Onion-Alien/onion-board/issues/new?labels=bug")
    assert __version__ in opened[1]
    monkeypatch.setattr(feedback, "FORM_URL", "")       # no form: feedback goes to GitHub too
    d.feedback_btn.click()
    assert opened[2] == opened[1]
    d.close()


def test_onion_watch_can_be_removed_from_settings(window, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from soundboard import watchaddon
    tab = window.triggers
    d = SettingsDialog(window, "general")
    assert not d.addon_remove.isVisibleTo(d) and "isn't installed" in d.addon_label.text()
    d.close()
    monkeypatch.setattr(tab, "info", SimpleNamespace(version="9.9"))
    monkeypatch.setattr(watchaddon, "removable", lambda info, base: True)
    removed = []

    def fake_remove():
        removed.append(True)
        tab.info = None
    monkeypatch.setattr(tab, "remove", fake_remove)
    d = SettingsDialog(window, "general")
    assert d.addon_remove.isVisibleTo(d) and "9.9 is installed" in d.addon_label.text()
    d.addon_remove.click()
    assert removed and not d.addon_remove.isVisibleTo(d)
    d.close()


def test_connection_choice_applies_at_once_and_fails_closed(window, qapp, monkeypatch):  # noqa: F811
    from soundboard import net
    monkeypatch.setattr(window, "_save_later", lambda: None)
    d = SettingsDialog(window)
    try:
        assert d.tabs.currentIndex() == 0 and d._page_keys[0] == "privacy"
        assert d.net_direct.isChecked() and not d.net_addr.isEnabled()
        d.net_via.setChecked(True)                 # no address yet: nothing goes online
        assert window.cfg.net_mode == "proxy" and net.active() and net.proxy() is None
        assert "nothing goes online" in d.net_note.text()
        d.net_addr.setText("socks5h://127.0.0.1:9050")
        d.net_addr.editingFinished.emit()
        assert window.cfg.net_proxy == "socks5h://127.0.0.1:9050"
        assert net.proxy().port == 9050 and "127.0.0.1:9050" in d.net_note.text()
        tested = []
        monkeypatch.setattr(net, "test", lambda text: tested.append(text) or "It works: yes.")
        d.net_test.click()
        assert process_events(qapp, lambda: "It works" in d.net_note.text())
        assert tested == ["socks5h://127.0.0.1:9050"]
        d.net_direct.setChecked(True)
        assert window.cfg.net_mode == "direct" and not net.active()
    finally:
        d.close()
        net.configure(net.DIRECT)


def test_privacy_switches_match_their_twins_on_other_pages(window, monkeypatch):  # noqa: F811
    """Update checks and yt-dlp's auto-update are on the Updates page too: ticking one
    ticks the other, and the setting changes once."""
    from PySide6.QtWidgets import QCheckBox
    monkeypatch.setattr(window, "_save_later", lambda: None)
    monkeypatch.setattr(window, "check_updates", lambda *a, **k: None)
    d = SettingsDialog(window)
    try:
        def boxes(text):
            return [b for b in d.findChildren(QCheckBox) if b.text().startswith(text)]
        mine, theirs = boxes("Check once a day")[0], boxes("Tell me when a new")[0]
        assert mine.isChecked() == theirs.isChecked() == window.cfg.update_check
        mine.setChecked(not mine.isChecked())
        assert theirs.isChecked() == mine.isChecked() == window.cfg.update_check
        auto, twin = boxes("Automatically")[0], boxes("Update it automatically")[0]
        twin.setChecked(True)
        assert auto.isChecked() and window.cfg.ytdlp_auto_optin
        d.plays_box.setChecked(True)
        assert window.cfg.radio["count_plays"] is True
        remote = next(b for b in d.findChildren(QPushButton) if b.text() == "Remote settings")
        remote.click()
        assert d._page_keys[d.tabs.currentIndex()] == "remote"
    finally:
        d.close()


def test_privacy_and_general_pages_fit_their_window(window, qapp):  # noqa: F811
    """No row wider than the window: a checkbox or radio button can't wrap, and one too
    long made the whole General page wider than its view, pushing Remove Onion Watch
    and the ends of the hints off the right edge. (Offscreen text is drawn wider than
    on Windows, so passing here leaves room.)"""
    d = SettingsDialog(window)
    d.show()
    d.resize(860, 700)
    try:
        for key in ("privacy", "general"):
            d.tabs.setCurrentIndex(d._page_keys.index(key))
            for _ in range(3):
                qapp.processEvents()
            sa = d.tabs.currentWidget()
            assert sa.widget().minimumSizeHint().width() <= sa.viewport().width(), key
        assert "&&" in d.tabs.tabText(0)        # "&" alone would underline the next letter
    finally:
        d.close()


def test_each_switch_writes_its_setting_and_applies_at_once(window, monkeypatch):  # noqa: F811
    """Settings > Privacy & security: one switch per feature (and per sound site),
    saved in net_off and applied to soundboard.net straight away; sub-options grey out
    under a switch that's off, and Offline mode greys out everything under it."""
    monkeypatch.setattr(window, "_save_later", lambda: None)
    monkeypatch.setattr(window, "check_updates", lambda *a, **k: None)
    d = SettingsDialog(window)
    try:
        assert set(net.FEATURES) <= set(d.net_boxes)
        for key, box in d.net_boxes.items():
            assert box.isChecked() and net.allowed(key)
            box.setChecked(False)
            assert key in window.cfg.net_off and not net.allowed(key)
            box.setChecked(True)
            assert key not in window.cfg.net_off and net.allowed(key)
        d.net_boxes["radio"].setChecked(False)
        assert not d._net_subs["radio"].isEnabled() and d._net_subs["app_update"].isEnabled()
        d.net_boxes["app_update"].setChecked(False)   # the Updates page follows
        assert not d.upd_btn.isEnabled() and "switched off" in d.upd_btn.toolTip()
        d.net_boxes["ytdlp_update"].setChecked(False)
        assert not any(b.isEnabled() for b in d.ytdlp_btns)
        d.offline_box.setChecked(True)
        assert window.cfg.net_offline and not net.any_allowed()
        assert not d._net_body.isEnabled()
        d.offline_box.setChecked(False)
        assert d._net_body.isEnabled() and net.allowed("voices") and not net.allowed("radio")
    finally:
        d.close()
        window.cfg.net_off, window.cfg.net_offline = [], False
        net.configure_features()


def test_switching_radio_off_swaps_the_tab_and_stops_a_station(window, monkeypatch):  # noqa: F811
    from soundboard.ui.radiopanel import RadioOff, RadioTab
    stopped = []
    monkeypatch.setattr(window.radio, "is_active", lambda: True)
    monkeypatch.setattr(window.radio, "shutdown", lambda: stopped.append(1))
    told = []
    monkeypatch.setattr(window, "toast", lambda text, kind="": told.append(text))
    net.configure_features(["radio"])
    try:
        assert isinstance(window.radio, RadioOff) and stopped == [1]
        assert told and "Radio was switched off" in told[0]
        assert window.radio_page.currentWidget() is window.radio
    finally:
        net.configure_features()
    assert isinstance(window.radio, RadioTab)   # back on: built again
