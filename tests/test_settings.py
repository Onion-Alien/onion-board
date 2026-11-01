"""The Settings window's layout: pages scroll instead of squashing their rows."""
import time
from contextlib import contextmanager

import pytest

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QScrollArea, QWidget

from conftest import process_events
from soundboard.online import net
from soundboard.ui.settings.settings import SettingsDialog, ThemeCard
from soundboard.ui.kit import busy
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_saved_clip_retention_setting_persists(window, qapp):  # noqa: F811
    window.setctl.open_settings("tabs")
    qapp.processEvents()
    d = window.setctl._settings_dlg
    assert not d.keep_clips.isChecked()
    d.keep_clips.click()
    assert window.cfg.app_clips_keep_forever
    window.cfg.save()
    from soundboard.sounds.library import Config
    assert Config.load().app_clips_keep_forever
    d.keep_clips.click()
    assert not window.cfg.app_clips_keep_forever


@contextmanager
def windows_shown():
    """The class names of the windows shown meanwhile (a widget shown before it has a
    parent pops up as a window of its own)."""
    shown = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
            if ev.type() == QEvent.Show and obj.isWidgetType() and obj.isWindow():
                shown.append(type(obj).__name__)
            return False
    spy = Spy()
    app = QApplication.instance()
    app.installEventFilter(spy)
    try:
        yield shown
    finally:
        app.removeEventFilter(spy)


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
    d = SettingsDialog(window, "about")
    btn = next(b for b in d.findChildren(QPushButton) if "Support" in b.text())
    btn.click()
    assert opened == ["https://github.com/Onion-Alien/onion-board#support-onion-board"]
    d.close()


def test_each_page_opens_by_name_and_holds_its_cards(window):  # noqa: F811
    where = {"privacy": ("What goes online", "Sounds and radio", "Voices",
                         "Updates and add-ons", "Setup downloads", "Network information"),
             "connection": ("Connection", "Network activity"),
             "audio": ("Devices", "Your mic", "Who's listening", "Audio buffering"),
             "hotkeys": ("Hotkey sounds",),
             "general": ("Window", "Running in the background", "Backup"),
             "help": ("Add-ons",),
             "about": ("Onion Board", "Get in touch", "Support Onion Board"),
             "updates": ("App updates", "Helper programs"),
             "remote": ("Remote control (Stream Deck, scripts)", "Set it up the easy way")}
    for page, titles in where.items():
        d = SettingsDialog(window, page)
        shown = {lb.text() for lb in d.tabs.currentWidget().widget().findChildren(QLabel)}
        assert set(titles) <= shown, page
        d.close()
    d = SettingsDialog(window, "nonsense")
    assert d.tabs.currentIndex() == 0
    d.close()


def _open_in_window(win, qapp, page, width=1020, height=720):
    """Settings as the cog opens it: a page in the shown window, `width` x `height`."""
    win.show()
    d = win.setctl.open_settings(page)
    size_settings(win, qapp, d, width, height)
    return d


def size_settings(win, qapp, d, width, height):
    """The window sized so the Settings page in it is `width` x `height`."""
    for _ in range(3):
        qapp.processEvents()
        win.resize(win.width() + width - d.width(),
                   win.height() + height - d.height())
    qapp.processEvents()


def test_the_cog_builds_only_the_page_it_opens_and_the_rest_when_shown(window):  # noqa: F811
    """Building all twelve pages under the app's style sheet took a second or two on
    every click of the cog: the window builds the others when they're first picked."""
    from soundboard.online import net
    net.configure_features(["app_update"], False)   # its button is on a page built later
    with windows_shown() as shown:
        d = SettingsDialog(window, "audio", lazy=True)
    assert shown == []
    built = [i for i in range(d.tabs.count()) if d.tabs.widget(i).widget() is not None]
    # (the Show advanced row's page is an empty one, made with the list)
    assert built == [d._page_keys.index("audio"), d._page_keys.index(d.ADVANCED)]
    d.categories.setCurrentRow(d._page_keys.index("updates"))
    page = d.tabs.currentWidget().widget()
    assert page is not None and "App updates" in {lb.text() for lb in page.findChildren(QLabel)}
    assert not d.upd_btn.isEnabled()   # greyed by Privacy, though that page isn't built
    d.close()
    d = SettingsDialog(window, "nonsense", lazy=True)
    assert d.tabs.currentIndex() == 0 and d.tabs.widget(0).widget() is not None
    d.close()


def test_closing_settings_before_the_updates_page_is_built_warns_nothing(window):  # noqa: F811
    """Closing unhooked the update signals the never-built Updates card hadn't hooked,
    and PySide printed "Failed to disconnect" warnings on every close."""
    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        d = SettingsDialog(window, "audio", lazy=True)
        d.done(0)
        d = SettingsDialog(window, "updates", lazy=True)
        d.done(0)
        d.done(0)   # twice: the second has nothing left to unhook
    assert not [w for w in caught if "disconnect" in str(w.message)]


def test_audio_page_picks_input_and_output_through_the_window(window, monkeypatch):  # noqa: F811
    window.routectl._fill_combo(window.cb_mic, ["Mic A", "Headset Mic"], "Mic A")
    window.routectl._fill_combo(window.cb_mon, ["Speakers", "Headset"], "Speakers")
    picked = []
    monkeypatch.setattr(window.routectl, "on_device",
                        lambda cb, attr: picked.append((attr, cb.currentData())))
    d = SettingsDialog(window, "audio")
    mic, mon = d.dev_combos[0][0], d.dev_combos[1][0]
    assert [mic.itemText(i) for i in range(mic.count())] == ["(none)", "Mic A", "Headset Mic"]
    assert mon.currentText() == "Speakers"
    mic.activated.emit(2)
    mon.activated.emit(2)
    assert picked == [("mic_device", "Headset Mic"), ("mon_device", "Headset")]
    assert window.cb_mon.currentText() == "Headset"   # the Setup tab follows
    d.close()


def test_the_device_boxes_are_filled_again_only_when_the_devices_change(window):  # noqa: F811
    """Each pick (and each time Settings opened) emptied and filled every device box:
    each shrank for a frame and the row beside it slid across and back. The same
    devices leave a box as it is; a new one fills it again."""
    window.routectl._fill_combo(window.cb_mic, ["Mic A", "Headset Mic"], "Mic A")
    d = SettingsDialog(window, "audio")
    mic = d.dev_combos[0][0]
    emptied = []
    mic.model().rowsRemoved.connect(lambda *_: emptied.append(1))
    d.audio._sync_devices()
    window.cb_mic.setCurrentIndex(2)
    d.audio._sync_devices()
    assert not emptied and mic.currentText() == "Headset Mic"
    window.routectl._fill_combo(window.cb_mic, ["Mic A", "Headset Mic", "USB Mic"], "USB Mic")
    d.audio._sync_devices()
    items = [mic.itemText(i) for i in range(mic.count())]
    assert emptied and items == ["(none)", "Mic A", "Headset Mic", "USB Mic"]
    assert mic.currentText() == "USB Mic"
    d.close()


def test_feedback_and_problem_buttons_only_open_the_browser(window, monkeypatch):  # noqa: F811
    from soundboard import __version__
    from soundboard.core import feedback
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    d = SettingsDialog(window, "about")
    monkeypatch.setattr(feedback, "FORM_URL", "https://forms.example.com/r/x")
    d.feedback_btn.click()      # asks "What would you improve?" first (test_feedbackdialog)
    assert d.feedback_box.isVisible() and not opened
    d.feedback_box.boxes["looks"].setChecked(True)
    d.feedback_box.send()
    d.feedback_box.form_btn.click()
    d.problem_btn.click()
    assert opened[0] == f"https://forms.example.com/r/x?version={__version__}&improve=looks"
    assert opened[1].startswith("https://github.com/Onion-Alien/onion-board/issues/new?labels=bug")
    assert __version__ in opened[1]
    monkeypatch.setattr(feedback, "FORM_URL", "")       # no form: feedback goes to GitHub too
    assert feedback.feedback_url(__version__) == feedback.problem_url(__version__)
    d.close()


def test_join_the_discord_comes_first_and_only_opens_the_browser(window, monkeypatch):  # noqa: F811
    from soundboard.core import feedback
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    d = SettingsDialog(window, "about")
    assert d.discord_btn.objectName() == "primary"

    def rows(lay):   # every layout under the card's, depth first
        yield lay
        for i in range(lay.count()):
            if lay.itemAt(i).layout() is not None:
                yield from rows(lay.itemAt(i).layout())
    row = next(r for r in rows(d.discord_btn.parentWidget().layout())
               if r.indexOf(d.discord_btn) >= 0)
    assert ([row.indexOf(b) for b in (d.discord_btn, d.feedback_btn, d.problem_btn)]
            == sorted(row.indexOf(b) for b in (d.discord_btn, d.feedback_btn, d.problem_btn)))
    d.discord_btn.click()
    assert opened == [feedback.DISCORD_URL]
    assert feedback.DISCORD_URL.startswith("https://discord.gg/")
    d.close()


def test_onion_watch_can_be_removed_from_settings(window, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from soundboard.addons import watchaddon
    tab = window.triggers
    d = SettingsDialog(window, "help")
    assert not d.addon_remove.isVisibleTo(d) and "isn't installed" in d.addon_label.text()
    d.close()
    monkeypatch.setattr(tab, "info", SimpleNamespace(version="9.9"))
    monkeypatch.setattr(watchaddon, "removable", lambda info, base: True)
    removed = []

    def fake_remove():
        removed.append(True)
        tab.info = None
    monkeypatch.setattr(tab, "remove", fake_remove)
    with windows_shown() as shown:
        d = SettingsDialog(window, "help")
    # its button was shown before it was in the dialog: a little blank window of its own
    # flashed up on every click of the cog
    assert shown == []
    assert d.addon_remove.isVisibleTo(d) and "9.9 is installed" in d.addon_label.text()
    d.addon_remove.click()
    assert removed and not d.addon_remove.isVisibleTo(d)
    d.close()


def test_connection_choice_applies_at_once_and_fails_closed(window, qapp, monkeypatch):  # noqa: F811
    from soundboard.online import net
    monkeypatch.setattr(window, "_save_later", lambda: None)
    d = SettingsDialog(window, "privacy")
    try:
        assert d._page_keys[d.tabs.currentIndex()] == "privacy"
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


def test_update_preferences_have_one_home_and_privacy_links_to_it(window, monkeypatch):  # noqa: F811
    """Privacy grants network permission; update scheduling has one home in Updates."""
    from PySide6.QtWidgets import QCheckBox
    monkeypatch.setattr(window, "_save_later", lambda: None)
    monkeypatch.setattr(window.updctl, "check_updates", lambda *a, **k: None)
    d = SettingsDialog(window)
    try:
        def boxes(text):
            return [b for b in d.findChildren(QCheckBox) if b.text().startswith(text)]
        assert len(boxes("Check for updates")) == len(boxes("Update automatically")) == 1
        d.upd_chk.setChecked(not d.upd_chk.isChecked())
        assert d.upd_chk.isChecked() == window.cfg.update_check
        d.ytdlp_auto_box.setChecked(True)
        assert window.cfg.ytdlp_auto_optin
        link = next(b for b in d.findChildren(QPushButton) if b.text() == "Update settings")
        link.click()
        assert d._page_keys[d.tabs.currentIndex()] == "updates"
        assert d.categories.currentRow() == d.tabs.currentIndex()
        d.plays_box.setChecked(True)
        assert window.cfg.radio["count_plays"] is True
        remote = next(b for b in d.findChildren(QPushButton) if b.text() == "Remote settings")
        remote.click()
        assert d._page_keys[d.tabs.currentIndex()] == "remote"
    finally:
        d.close()


def test_all_settings_pages_fit_their_window(window, qapp):  # noqa: F811
    """No row wider than the window: a checkbox or radio button can't wrap, and one too
    long made the whole General page wider than its view, pushing Remove Onion Watch
    and the ends of the hints off the right edge. (Offscreen text is drawn wider than
    on Windows, so passing here leaves room.)"""
    d = SettingsDialog(window)
    d.show()
    try:
        for width, height in ((720, 600), (860, 700), (1020, 760)):
            d.resize(width, height)
            for key in d._page_keys:
                if key == d.ADVANCED:   # (a switch, not a page)
                    continue
                d.categories.setCurrentRow(d._page_keys.index(key))
                for _ in range(3):
                    qapp.processEvents()
                sa = d.tabs.currentWidget()
                assert sa.widget().minimumSizeHint().width() <= sa.viewport().width(), key
                assert d.tabs.currentIndex() == d.categories.currentRow()
        # "&" alone would underline the next letter
        assert "&&" in d.tabs.tabText(d._page_keys.index("privacy"))
    finally:
        d.close()


def test_theme_previews_reflow_when_settings_is_resized(window, qapp):  # noqa: F811
    from soundboard.ui.settings.settings import ThemeGrid

    d = _open_in_window(window, qapp, "appearance")
    try:
        grid = d.findChildren(ThemeGrid)[0]
        for width, expected in ((1020, 4), (720, 2), (1200, 5), (720, 2)):
            size_settings(window, qapp, d, width, 760)
            for _ in range(5):
                qapp.processEvents()
            assert grid.columns == expected
            assert all(c.geometry().right() < grid.width() for c in grid.cards)
            assert len({id(c) for c in grid.cards}) == grid.grid.count()
            # spread out evenly: the last card in a full row ends at the right edge
            last = grid.cards[expected - 1].geometry()
            assert grid.width() - 1 - last.right() < expected
            assert grid.cards[0].geometry().left() == 0
            # every group shares those columns: its cards line up with the first group's
            xs = [c.geometry().left() for c in grid.cards]
            for other in d.findChildren(ThemeGrid):
                for i, c in enumerate(other.cards[:expected]):
                    assert c.geometry().left() == xs[i]
    finally:
        d.close()


def test_each_switch_writes_its_setting_and_applies_at_once(window, monkeypatch):  # noqa: F811
    """Settings > Privacy & security: one switch per feature (and per sound site),
    saved in net_off and applied to soundboard.online.net straight away; sub-options grey out
    under a switch that's off, and Offline mode hides everything under it."""
    monkeypatch.setattr(window, "_save_later", lambda: None)
    monkeypatch.setattr(window.updctl, "check_updates", lambda *a, **k: None)
    d = SettingsDialog(window)
    try:
        assert set(net.FEATURES) <= set(d.net_boxes)
        for key, box in d.net_boxes.items():
            assert box.isChecked() and net.allowed(key)
            box.setChecked(False)
            # Count me in waits for its last anonymous opt-out count first
            # (PrivacyPage._opt_out_wait checks every 100 ms)
            end = time.monotonic() + 5
            while net.allowed(key) and time.monotonic() < end:
                QApplication.processEvents()
                time.sleep(0.02)
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
        assert d._net_body.isHidden()   # Offline mode: hidden, not left greyed out
        d.offline_box.setChecked(False)
        assert not d._net_body.isHidden() and net.allowed("voices") and not net.allowed("radio")
    finally:
        d.close()
        window.cfg.net_off, window.cfg.net_offline = [], False
        net.configure_features()


def test_switching_radio_off_swaps_the_tab_and_stops_a_station(window, monkeypatch):  # noqa: F811
    from soundboard.ui.radio.radiopanel import RadioOff, RadioTab
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


def test_remote_page_copies_an_ai_prompt_with_the_key_only_when_ticked(window):  # noqa: F811
    from PySide6.QtWidgets import QApplication, QCheckBox
    window.cfg.api_enabled, window.cfg.api_token = True, "key-for-the-ai-test"
    d = SettingsDialog(window, "remote")
    try:
        # the links card's (the Twitch card has one of its own)
        ai = next(b for b in d.findChildren(QPushButton) if b.text() == "Copy AI prompt"
                  and "Twitch" not in b.toolTip())
        ai.click()
        text = QApplication.clipboard().text()
        assert "/api/play" in text and "key-for-the-ai-test" not in text
        next(b for b in d.findChildren(QCheckBox) if b.text().startswith("Put my key")
             ).setChecked(True)
        ai.click()
        assert "token=key-for-the-ai-test" in QApplication.clipboard().text()
    finally:
        d.close()
        window.cfg.api_enabled = False
        window.remctl.apply_remote()


def test_a_new_remote_key_says_made_only_once_it_is_saved(window, monkeypatch):  # noqa: F811
    """New key: saved on the saver's thread, never cfg.save() on the UI thread; "made"
    only once it's on disk. A failed save says so instead (after a restart the old key
    would be back, and a Stream Deck set up with the new one would stop working)."""
    from soundboard.sounds import library
    from soundboard.ui.window import remoteaccess
    flashed, toasts, ui_saves = [], [], []
    monkeypatch.setattr(busy, "flash", lambda btn, text, ms=0: flashed.append(text))
    monkeypatch.setattr(busy, "toast", lambda w, text, kind="", *a, **k: toasts.append(kind))
    monkeypatch.setattr(type(window.cfg), "save", lambda self: ui_saves.append(1) or True)
    monkeypatch.setattr(remoteaccess.RemoteAccess, "apply_remote", lambda self: "")
    window._save_failed_shown = False
    window.cfg.api_enabled, window.cfg.api_token = True, "the-old-key"
    d = SettingsDialog(window, "remote")
    try:
        new = next(b for b in d.findChildren(QPushButton) if b.text() == "New key")
        monkeypatch.setattr(library, "_write", lambda snap: False)   # disk full, say
        new.click()
        assert process_events(QApplication.instance(), lambda: "error" in toasts, 5)
        assert flashed == [] and window.cfg.api_token != "the-old-key"
        monkeypatch.setattr(library, "_write", lambda snap: True)
        new.click()
        assert process_events(QApplication.instance(), lambda: flashed, 5)
        assert flashed == ["✓ New key made"]
        assert ui_saves == []                # never the whole config on the UI thread
    finally:
        d.close()
        window.cfg.api_enabled = False


def test_about_shows_the_version_and_only_opens_pages(window, monkeypatch):  # noqa: F811
    from soundboard.ui.window.mainwindow import version_text
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    d = SettingsDialog(window, "about")
    page = d.tabs.currentWidget().widget()
    shown = {lb.text() for lb in page.findChildren(QLabel)}
    assert {"Onion Board", "Get in touch", "A note from me", "The boring bit"} <= shown
    assert d.about_version.text() == f"Version {version_text()}"
    for b in page.findChildren(QPushButton):
        b.click()
    assert opened and all(u.startswith("https://") for u in opened)
    assert any("/security/advisories/new" in u for u in opened)
    d.close()


def test_live_tabs_is_a_tab_of_the_look_box_tint_or_dot(window, qapp):  # noqa: F811
    d = SettingsDialog(window, "appearance")
    assert d.live_green.isChecked() == window.cfg.live_tab_green
    card = d.live_green.parentWidget()
    assert card.findChild(QLabel, "section").text() == "Live tabs"
    # one of the look box's tabs, the box right under the language
    names = [b.text() for b in d.look_tabs]
    assert names == ["Themes", "Look"]   # its own part of the Look tab
    assert d.look_pages[1].isAncestorOf(card)
    assert d.look_box.parentWidget().layout().itemAt(1).widget() is d.look_box
    d.live_dot.click()
    assert window.cfg.live_tab_green is False
    d.live_green.click()
    assert window.cfg.live_tab_green is True


def test_look_tab_in_three_groups_with_switches_by_their_titles(window, qapp):  # noqa: F811
    """The Look tab reads as three small groups (Colour, Size, Background), each
    a soft box, not five headings in one long list; on/off and the size dropdown sit at
    the end of their setting's heading line."""
    d = SettingsDialog(window, "appearance")
    page = d.look_pages[1]
    boxes = page.findChildren(QFrame, "lookgroup")
    assert len(boxes) == 3

    def titles(box):
        return [t.text() for t in box.findChildren(QLabel, "section")]
    assert titles(boxes[0]) == ["Highlight colour", "Live tabs"]
    assert titles(boxes[1]) == ["Interface size"]
    assert titles(boxes[2]) == ["Playing sound background"]
    assert [len(b.findChildren(QFrame, "lookrule")) for b in boxes] == [1, 0, 0]
    labels = [b.parentWidget().findChild(QLabel, "hint").text() for b in boxes]
    assert labels == ["Colour", "Size", "Background"]
    for control, title in ((d.ui_scale_combo, "Interface size"),
                           (d.playing_background_check, "Playing sound background")):
        head = control.parentWidget()   # the heading widget: icon, title, then the control
        assert head.findChild(QLabel, "section").text() == title
    d.close()


def test_lite_mode_is_on_general_under_window(window, qapp):  # noqa: F811
    """Lite mode is an option of its own Speed card on General, right under Window
    (it was at the end of Appearance's second tab, where people didn't find it)."""
    d = SettingsDialog(window, "general")
    card = d.lite_check.parentWidget()
    while card.objectName() != "setcard":
        card = card.parentWidget()
    page = card.parentWidget().layout()
    cards = [page.itemAt(i).widget() for i in range(page.count()) if page.itemAt(i).widget()]
    titles = [c.findChild(QLabel, "section").text() for c in cards[:2]]
    assert titles == ["Window", "Speed"] and cards[1] is card
    assert d.lite_check.text() == "Lite mode" and not d.lite_check.isChecked()
    d.lite_check.click()
    assert window.cfg.lite_mode is True
    d.lite_check.click()
    assert window.cfg.lite_mode is False
    d.close()


def test_theme_style_switches_textured_and_plain(window, qapp):  # noqa: F811
    """Textured (a new install's default) puts the theme's pattern on; Plain leaves the
    panels flat."""
    from soundboard.sounds import library
    from soundboard.ui.kit import theme
    assert library.Config().theme_texture is True
    window.themectl.apply_theme("Amber Terminal")
    d = SettingsDialog(window, "appearance")
    assert d.texture_on.isChecked() == window.cfg.theme_texture
    d.texture_off.click()
    assert window.cfg.theme_texture is False and not theme.textures_on
    assert "/tex-" not in qapp.styleSheet()
    d.texture_on.click()
    assert window.cfg.theme_texture is True and theme.textures_on
    assert "/tex-" in qapp.styleSheet()
    d.close()


def test_a_saved_plain_choice_stays_plain():
    """Only new installs get Textured: a config that says Plain keeps it."""
    from soundboard.sounds import library
    assert library.Config.from_raw({"theme_texture": False}).theme_texture is False
    assert library.Config.from_raw({}).theme_texture is True


@pytest.mark.parametrize("kind", sorted(
    __import__("soundboard.ui.kit.theme", fromlist=["TEXTURES"]).TEXTURES))
def test_every_texture_tile_is_see_through(qapp, kind):
    """Each tile lies over the card's own colour, so hover shades still show."""
    from soundboard.ui.kit import theme
    for name in ("Dark", "Light"):
        img = theme.texture_image(kind, theme.THEMES[name])
        assert not img.isNull()
        alphas = {img.pixelColor(x, y).alpha() for x in range(img.width())
                  for y in range(img.height())}
        assert min(alphas) < 255, (kind, name)


def test_textured_paints_the_glow_and_the_theme_cards_preview_it(qapp, window, monkeypatch):  # noqa: F811
    """Textured: the window gets a soft glow of the theme's accents (opaque, so scrolling
    can copy it) and each theme card shows its own pattern. Plain: flat, no pattern."""
    from PySide6.QtCore import QPointF, QRect
    from PySide6.QtGui import QImage, QPainter
    from soundboard.ui.kit import theme

    def corner(textured):
        img = QImage(400, 300, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        theme.paint_window_bg(p, QRect(0, 0, 400, 300), QPointF(0, 0), 400, 300,
                              tk=theme.THEMES["Dark"], textured=textured)
        p.end()
        c = img.pixelColor(40, 10)
        assert c.alpha() == 255
        return c.name()
    assert corner(False) == theme.THEMES["Dark"]["bg"]
    assert corner(True) != theme.THEMES["Dark"]["bg"]

    def card_colours(name):
        card = ThemeCard(name)
        card.resize(card.sizeHint())
        img = card.grab().toImage()
        return {img.pixelColor(x, y).name() for x in range(18, 52) for y in range(28, 40)}
    monkeypatch.setattr(theme, "textures_on", False)
    assert len(card_colours("Hacker")) == 1
    monkeypatch.setattr(theme, "textures_on", True)
    assert len(card_colours("Hacker")) > 1   # scanlines on the pads


def _ink_left(lbl) -> int | None:
    """The first column of a label's picture with text in it."""
    img = lbl.grab().toImage()
    bg = img.pixelColor(img.width() - 1, img.height() - 1)
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            diff = abs(c.red() - bg.red()) + abs(c.green() - bg.green())
            if diff + abs(c.blue() - bg.blue()) > 60:
                return x
    return None


def test_card_headings_line_up_with_the_text_under_them(qapp, window):  # noqa: F811
    """A heading's padding-top made Qt indent its text 3 px past the card's text."""
    d = SettingsDialog(window, "remote")
    d.show()
    process_events(qapp, lambda: False, timeout=0.2)
    page = d.tabs.currentWidget().widget()
    # (the ones shown only later, like Twitch's once it's connected, aren't drawn yet)
    heads = [lb for lb in page.findChildren(QLabel)
             if lb.objectName() == "section" and lb.isVisibleTo(page)]
    assert heads
    for h in heads:
        h.setText("HELLO")                     # one shape: no letter's own bearing to compare
        qapp.processEvents()
        assert _ink_left(h) is not None and _ink_left(h) <= 1, h.text()
    d.close()


def test_highlight_colour_slides_saves_and_resets(window, qapp, monkeypatch):  # noqa: F811
    from soundboard.ui.kit import theme
    d = SettingsDialog(window, "appearance")
    # a colour change restyles only what's drawn in it: the whole app took seconds
    real_stylesheet = theme.stylesheet
    monkeypatch.setattr(theme, "stylesheet", lambda *a: pytest.fail("whole-app restyle"))
    try:
        assert d.hue_now.text() == f"Now: {theme.current_name}'s own colour."
        d.hue_reset.click()                                 # nothing to undo: says so
        assert d.hue_reset.text() == "✓ Already the theme's" and not window.cfg.live_color
        d.hue_slider.setValue(200)                          # arrow keys: once they stop
        d.hue_slider.setValue(210)
        assert not window.cfg.live_color and d.hue_settle.isActive()
        d.hue_settle.timeout.emit()
        picked = window.cfg.live_color
        assert picked and theme.T["live"] == picked
        assert 200 <= QColor(picked).hsvHue() <= 220
        assert d.hue_now.text() == "Now: your own colour, in every theme."
        assert picked in window.btn_air.styleSheet()        # the Live button follows
        d.hue_slider.setSliderDown(True)                    # dragging: only the preview
        d.hue_slider.setValue(20)
        assert window.cfg.live_color == picked and not d.hue_settle.isActive()
        d.hue_slider.setSliderDown(False)                   # let go: applied
        assert 10 <= QColor(window.cfg.live_color).hsvHue() <= 30
        assert window.cfg.live_color in d.hue_swatch.styleSheet()
        d.hue_reset.click()
        assert d.hue_reset.text() == "✓ Back to the theme's"
        assert window.cfg.live_color == "" and theme.T["live"] == theme.T["accent"]
        assert theme.T["accent"] in window.btn_air.styleSheet()
    finally:
        # just this patch: monkeypatch's undo also dropped the fixtures' temp app folder,
        # so the reset below saved the test board into the real %APPDATA%\OnionBoard
        theme.stylesheet = real_stylesheet
        window.themectl.set_live_color("")
        d.close()


def test_language_comes_first_on_appearance_and_opens_the_picker(window, monkeypatch):  # noqa: F811
    from soundboard import i18n
    monkeypatch.setattr(i18n, "windows_language", lambda: "de-DE")
    restarts = []
    monkeypatch.setattr(window, "restart_app", lambda: restarts.append(1))
    d = SettingsDialog(window, "appearance")
    btn = d.lang_button
    card = btn.parentWidget()
    assert card.parentWidget().layout().itemAt(0).widget() is card    # first on the page
    # the title in Windows' language too: found by someone who can't read English
    assert card.findChild(QLabel, "section").text() == "Language · Sprache"
    assert btn.text().startswith("English") and not d.lang_restart.isVisibleTo(d)
    btn.click()                                  # a drop-down: nothing waits on it
    dlg = d.lang_dialog
    assert dlg.isVisible()
    dlg.search.setText("germ")                                   # English name
    assert [t.code for t in dlg.visible_tiles()] == ["de"]
    dlg.search.returnPressed.emit()                              # Enter picks it
    assert window.cfg.language == "de" and not restarts   # saved, no surprise restart
    assert btn.text().startswith("Deutsch")
    # what happens next, in the language picked
    assert d.lang_note.text() == "Onion Board zeigt nach einem Neustart Deutsch."
    assert d.lang_restart.text() == "Jetzt neu starten" and d.lang_restart.isVisibleTo(d)
    d.lang_restart.click()
    assert restarts == [1]
    d.close()


def test_a_board_reopened_shows_the_picked_language_on_the_button(window):  # noqa: F811
    window.cfg.language = "ja"
    d = SettingsDialog(window, "appearance")
    assert d.lang_button.text().startswith("日本語") and d.lang_restart.isVisibleTo(d)
    d.close()


def test_show_advanced_clicks_keep_the_page_row_highlighted(window, qapp):  # noqa: F811
    """Clicking Show advanced over and over switches it each time, and the page's own
    row keeps its highlight: the switch row never becomes the current one, not even
    between the press and the release. The search box has no right-click menu."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    d = SettingsDialog(window, "about")
    try:
        d.resize(900, 700)
        d.show()
        qapp.processEvents()
        about = d._page_keys.index("about")
        rows = []
        d.categories.currentRowChanged.connect(rows.append)
        vp = d.categories.viewport()
        pos = QPointF(d.categories.visualItemRect(d.categories.item(d._adv_row)).center())
        was = d._advanced
        for i in range(4):
            for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                QApplication.sendEvent(vp, QMouseEvent(
                    kind, pos, vp.mapToGlobal(pos), Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress
                    else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
                assert d.categories.currentRow() == about
            assert d._advanced == (was if i % 2 else not was)
        assert rows == []
        assert d.search_box.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu
    finally:
        d.close()


def _rows_back(d) -> bool:
    """Every row shown again after a search, but the advanced ones while folded."""
    return all(d.categories.item(i).isHidden() == (i > d._adv_row and not d._advanced)
               for i in range(d.categories.count()))


def test_search_hides_cards_and_pages_without_the_word(window, qapp):  # noqa: F811
    """Typing in the search box keeps only the cards with the word, hides the pages
    with none left, lands on the first page with one, and clearing brings it all back."""
    d = SettingsDialog(window, "privacy", lazy=True)
    try:
        d.search_box.setText("tray")
        d._apply_search("tray")
        shown = [d.categories.item(i).text() for i in range(d.categories.count())
                 if not d.categories.item(i).isHidden()]
        assert "General" in shown and "Hotkeys" not in shown
        assert d._page_keys[d.tabs.currentIndex()] == "general"
        page = d.tabs.currentWidget().widget()
        cards = page.findChildren(QFrame, "setcard")
        visible = [c for c in cards if not c.isHidden()]
        assert visible and len(visible) < len(cards)
        assert all("tray" in d._words_of(c) for c in visible)
        d._apply_search("")
        assert all(not c.isHidden() for c in cards)
        assert _rows_back(d)
        d._apply_search("no such words here")
        assert all(d.categories.item(i).isHidden() for i in range(d.categories.count()))
    finally:
        d.close()


@pytest.mark.parametrize("name", ["Synthwave", "Cherry Blossom", "Paper"])
def test_search_finds_painted_theme_names(window, qapp, name):  # noqa: F811
    from soundboard.ui.settings.settings import ThemeCard

    d = SettingsDialog(window, "general", lazy=True)
    try:
        d._apply_search(name.swapcase())
        assert d._page_keys[d.tabs.currentIndex()] == "appearance"
        page = d.tabs.currentWidget().widget()
        cards = page.findChildren(QFrame, "setcard")
        assert any(not card.isHidden() and
                   any(name.lower() in tile.name.lower()
                       for tile in card.findChildren(ThemeCard))
                   for card in cards)
        d._apply_search("")
        assert _rows_back(d)
    finally:
        d.close()


@pytest.mark.parametrize("query", ["theme", "themes", "color", "colors", "colour", "colours"])
def test_search_theme_and_colour_terms_shows_every_theme(window, qapp, query):  # noqa: F811
    from soundboard.ui.settings.settings import ThemeGrid

    d = _open_in_window(window, qapp, "general", width=1020)
    try:
        d._apply_search(query)
        for _ in range(10):
            qapp.processEvents()
        assert d._page_keys[d.tabs.currentIndex()] == "appearance"
        grids = d.tabs.currentWidget().widget().findChildren(ThemeGrid)
        assert grids
        assert all(grid.isVisible() for grid in grids)
        assert all(tile.isVisible() for grid in grids for tile in grid.cards)
        assert all(grid.columns == max(1, (grid.width() + 12) // 162) for grid in grids)
    finally:
        window.setctl.close_settings()


@pytest.mark.parametrize("query, tab", [("opacity", "Look"), ("interface size", "Look"),
                                        ("textured", "Themes"), ("synthwave", "Themes")])
@pytest.mark.parametrize("clicked_first", [False, True])
def test_search_shows_the_look_tab_with_the_words(window, qapp, query, tab,  # noqa: F811
                                                  clicked_first):
    """Also after every look tab was clicked once (ending on Look): the search
    still moves the box to the tab with the words, typed into the box as a person does."""
    d = SettingsDialog(window, "appearance" if clicked_first else "general", lazy=True)
    try:
        if clicked_first:
            d.show()
            for b in d.look_tabs:
                b.click()
                qapp.processEvents()
            d.search_box.setText("opacity")
            d._apply_search(d.search_box.text())
            d.search_box.setText(query)
        d._apply_search(query)
        assert d._page_keys[d.tabs.currentIndex()] == "appearance"
        shown = d.look_shown
        assert d.look_tabs[shown].text() == tab and d.look_tabs[shown].isChecked()
        assert all(p.isHidden() == (i != shown) for i, p in enumerate(d.look_pages))
    finally:
        d.close()


def test_switching_count_me_in_off_sends_one_opt_out_first(window, qapp, monkeypatch):  # noqa: F811
    """Count me in on -> off: the anonymous opt-out goes while the count is still
    allowed, and the switch takes hold right after; other switches never send it."""
    from soundboard.core import usage
    calls = []
    monkeypatch.setattr(usage, "opt_out",
                        lambda where: calls.append((where, net.allowed("usage_stats"))))
    monkeypatch.setattr(window, "_save_later", lambda: None)
    window.cfg.net_off = []
    net.configure_features()
    d = SettingsDialog(window)
    try:
        box = d.net_boxes["usage_stats"]
        box.setChecked(False)
        assert process_events(qapp, lambda: not net.allowed("usage_stats"))
        assert calls == [("settings", True)] and "usage_stats" in window.cfg.net_off
        d.net_boxes["radio"].setChecked(False)   # other switches never send it
        assert calls == [("settings", True)]
    finally:
        d.close()
        net.configure_features()


def test_count_me_in_eye_opens_the_table(window):  # noqa: F811
    """Count me in's hint stays short; its eye opens the table of what's sent, with
    an example and a reason on every row, and it never touches the switch."""
    from soundboard.ui.settings import countdialog
    d = SettingsDialog(window)
    try:
        box = d.net_boxes["usage_stats"]
        was = box.isChecked()
        assert len(d.NET_HINTS["usage_stats"]) < 120
        d.count_eye.click()
        dlg = d.count_dialog
        assert isinstance(dlg, countdialog.CountDialog) and dlg.isVisible()
        assert all(what and example and why for what, example, why in countdialog.rows())
        assert box.isChecked() == was
        dlg.close()
    finally:
        d.close()


@pytest.mark.parametrize("rtl", [False, True])
def test_tab_moves_from_the_category_list_into_the_page_and_out_again(window, qapp, rtl):  # noqa: F811
    """Keyboard and screen-reader users: Tab from the category list goes into the open
    page, on through it and out of it, and Shift+Tab comes back, on every page."""
    if rtl:
        qapp.setLayoutDirection(Qt.RightToLeft)
    try:
        d = _open_in_window(window, qapp, "privacy")
        window.activateWindow()
        for row in range(d.categories.count()):
            if d.categories.isRowHidden(row):
                continue
            d.categories.setCurrentRow(row)
            d.categories.setFocus()
            qapp.processEvents()
            QTest.keyClick(d.categories, Qt.Key_Tab)
            first = QApplication.focusWidget()
            page = d.tabs.currentWidget()
            assert first is not d.categories, d.categories.item(row).text()
            assert page.isAncestorOf(first), (d.categories.item(row).text(), first)
            QTest.keyClick(first, Qt.Key_Backtab)
            assert QApplication.focusWidget() is d.categories
            QTest.keyClick(d.categories, Qt.Key_Tab)
            for _ in range(400):   # no trap: Tab goes on through the page and out of it
                if not page.isAncestorOf(QApplication.focusWidget()):
                    break
                QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab)
            assert not page.isAncestorOf(QApplication.focusWidget()), (
                d.categories.item(row).text())
        d.categories.setFocus()
        QTest.keyClick(d.categories, Qt.Key_Backtab)
        assert QApplication.focusWidget() is d.search_box
        d.close()
    finally:
        qapp.setLayoutDirection(Qt.LeftToRight)


def test_search_lands_on_the_named_page_and_says_when_nothing_matches(window, qapp):  # noqa: F811
    d = SettingsDialog(window, "privacy", lazy=True)
    d.show()
    try:
        for i in range(d.categories.count()):   # a page's own name opens that page
            if i == d._adv_row:   # (a switch, not a page)
                continue
            name = d.categories.item(i).text()
            d.tabs.setCurrentIndex((i + 5) % d.tabs.count())
            d._apply_search(name)
            assert d.tabs.currentIndex() == i, name
        d._apply_search("hotkey")   # General mentions hotkeys too, but comes first
        assert d.categories.item(d.tabs.currentIndex()).text() == "Hotkeys"
        # "tor" is inside "history" and "monitor" on General: the card called Tor
        d.tabs.setCurrentIndex(d._page_keys.index("general"))
        d._apply_search("tor")
        assert d._page_keys[d.tabs.currentIndex()] == "connection"
        d._apply_search("zzqq nothing")
        assert d.no_match.isVisibleTo(d) and not d.tabs.isVisibleTo(d)
        assert "zzqq nothing" in d.no_match.text()
        d._apply_search("")
        assert d.tabs.isVisibleTo(d) and not d.no_match.isVisibleTo(d)
        assert _rows_back(d)
    finally:
        d.close()


@pytest.mark.parametrize("text", ["   ", ""])
def test_search_of_only_spaces_before_the_pages_are_built(window, qapp, text):  # noqa: F811
    """Spaces typed into a fresh Settings' search (or the box cleared before its timer)
    searched for no words with the lazy pages still unbuilt: an AssertionError."""
    d = SettingsDialog(window, "privacy", lazy=True)
    try:
        assert d._unbuilt
        d._apply_search(text)
        assert _rows_back(d)
        for word in ("Größe", "日本語", "مرحبا", "😀"):   # any language: no crash
            d._apply_search(word)
        d._apply_search(text)
        assert d.tabs.isVisibleTo(d) and not d.no_match.isVisibleTo(d)
    finally:
        d.close()


@pytest.mark.parametrize("width", [800, 1180])
@pytest.mark.parametrize("direction", [Qt.LeftToRight, Qt.RightToLeft])
def test_settings_title_close_after_the_back_arrow(window, qapp, width, direction):  # noqa: F811
    d = _open_in_window(window, qapp, "privacy", width, 720)
    d.setLayoutDirection(direction)
    qapp.processEvents()
    QTest.mouseMove(d.back_btn, d.back_btn.rect().center())
    qapp.processEvents()
    arrow, title = d.back_btn.geometry(), d.page_title.geometry()
    gap = (title.left() - arrow.right() - 1 if direction == Qt.LeftToRight
           else arrow.left() - title.right() - 1)
    assert 0 <= gap <= 4   # a word after the arrow, not across the row
    d.back_btn.click()
    assert not d.isVisible()


def test_pages_start_where_a_tabs_do(window, qapp):  # noqa: F811
    """The first card on every page starts where a tab's page does (the body's 10 px
    plus 8), whatever the heading beside it does."""
    d = _open_in_window(window, qapp, "privacy", 1020, 680)
    content = window._content.mapTo(window, QPoint(0, 0)).y()
    for row in range(d.categories.count()):
        d.categories.setCurrentRow(row)
        qapp.processEvents()
        page = d.tabs.currentWidget().widget()
        first = min((c for c in page.children() if isinstance(c, QWidget) and c.isVisible()),
                    key=lambda c: c.y())
        at = first.mapTo(window, QPoint(0, 0)).y()
        assert at == content + d.PAGE_TOP, d.categories.item(row).text()
    d.close()
    qapp.processEvents()
    assert window._body_lay.contentsMargins().top() == 10   # a tab's again


@pytest.mark.parametrize("theme", ["Dark", "Amber Terminal", "Retro 98", "Comic Sans"])
def test_heading_level_with_the_rails_name(window, qapp, theme):  # noqa: F811
    """ "Settings" (the rail's "Onion Board" size, a cog after it) has its capitals
    level with the rail's name, the arrow and cog centred on them, in every theme's
    font (where a font draws its capitals is measured: Consolas' and Tahoma's sit
    lower in the line, and the font's numbers put the cog up to 2 px off them)."""
    window.themectl.apply_theme(theme)
    d = _open_in_window(window, qapp, "privacy", 1020, 680)
    # (text lands on whole screen pixels: at 125% a 1 px lower row can move it 2, so
    # the nearest place can be a pixel off the name)
    process_events(qapp, lambda: abs(d.heading._caps_mid(d.page_title)
                                     - d.heading._caps_mid(window.wordmark)) <= 1, timeout=3)
    assert d.page_title.font().pointSizeF() == window.wordmark.font().pointSizeF()
    title = d.heading._caps_mid(d.page_title)
    assert abs(title - d.heading._caps_mid(window.wordmark)) <= 1
    for icon in (d.back_btn, d.title_cog):
        at = icon.mapTo(window, QPoint(0, 0)).y()
        # (both drawn to the screen pixel, `dy` below their box's middle)
        mid = (at + icon.height() / 2 + icon.dy) * icon.devicePixelRatioF()   # (screen px)
        assert abs(mid - title) <= 0.25, (theme, icon.objectName())
    d.close()


def test_live_tabs_choices_side_by_side_like_connection(window, qapp):  # noqa: F811
    """Comparable short choices look alike: Live tabs' two sit in one wrapping row,
    as Connection's and Network activity's do (offscreen fonts here are too wide to
    compare positions: the pictures check that)."""
    from soundboard.ui.kit.panel import Flow
    d = SettingsDialog(window, "appearance")
    card = d.live_green.parentWidget()
    flows = [f for f in card.layout().findChildren(Flow)
             if f.indexOf(d.live_green) >= 0 and f.indexOf(d.live_dot) >= 0]
    assert flows
    assert flows[0].indexOf(d.live_dot) < flows[0].indexOf(d.live_green)
    buttons = next(f for f in d.hue_reset.parentWidget().layout().findChildren(Flow)
                   if f.indexOf(d.hue_reset) >= 0)
    assert buttons.itemAt(0).widget() is d.hue_reset
    assert buttons.itemAt(1).widget().text() == "More colours"
    d.close()


def test_settings_cards_line_up(window, qapp):  # noqa: F811
    """An option's explanation sits under its box's text (General's one-click one
    sat at the card's edge); the overlay's Open overlay and Auto-hide choice are as wide
    as their words, right after what they belong to; the ducking label keeps one line."""
    from PySide6.QtWidgets import QComboBox, QPushButton
    d = SettingsDialog(window, "general")
    hint = next(lb for lb in d.findChildren(QLabel)
                if lb.text().startswith("Otherwise, double-click to play"))
    assert hint.contentsMargins().left() == 26
    d.close()
    d = _open_in_window(window, qapp, "overlay", 1000, 700)
    for _ in range(5):   # the rows settle their widths
        qapp.processEvents()
    test = next(b for b in d.findChildren(QPushButton) if b.text() == "Open overlay")
    assert test.width() <= test.sizeHint().width() + 2
    auto = d.ov_toggle_only[1]
    assert isinstance(auto, QComboBox) and auto.width() <= auto.sizeHint().width() + 2
    d.show_page("audio")
    qapp.processEvents()
    duck = next(lb for lb in d.findChildren(QLabel)
                if lb.text() == "While I talk, lower my sounds:")
    assert not duck.wordWrap()
    d.close()


def test_theme_cards_and_sliders_have_a_name_a_screen_reader_can_say(window):  # noqa: F811
    """A theme card draws its name and the Overlay sliders sat beside plain labels: a
    screen reader said nothing on any of them."""
    from PySide6.QtWidgets import QSlider
    from soundboard.ui.settings.settings import ThemeCard
    for page in ("appearance", "overlay"):
        d = SettingsDialog(window, page)
        body = d.tabs.currentWidget().widget()
        parts = body.findChildren(QSlider) + body.findChildren(ThemeCard)
        assert parts, page
        assert all(p.accessibleName() for p in parts), [type(p).__name__ for p in parts
                                                        if not p.accessibleName()]
        d.close()


@pytest.mark.parametrize("error", ["", "offline"])
def test_update_check_keeps_focus_and_blocks_repeat_clicks(window, qapp, monkeypatch, error):  # noqa: F811
    monkeypatch.setattr(net, "allowed", lambda key: True)
    calls = []
    monkeypatch.setattr(window.updctl, "check_updates", lambda **kw: calls.append(kw))
    d = _open_in_window(window, qapp, "updates")
    btn = d.upd_btn
    btn.setFocus()
    QTest.mouseClick(btn, Qt.LeftButton)
    assert busy.is_busy(btn) and btn.isEnabled() and d.focusWidget() is btn
    QTest.mouseClick(btn, Qt.LeftButton)
    QTest.keyClick(btn, Qt.Key_Space)
    d.connection._updates_check()  # programmatic calls also cannot overlap
    assert len(calls) == 1
    window.update_done.emit(None, error)
    assert not busy.is_busy(btn) and d.focusWidget() is btn
    assert ("Couldn't check" if error else "newest version") in d.upd_label.text()
    QTest.keyClick(btn, Qt.Key_Tab)
    assert d.focusWidget() is not btn  # keyboard navigation still works
    btn.setFocus()
    QTest.keyClick(btn, Qt.Key_Space)
    assert len(calls) == 2 and busy.is_busy(btn)
    window.update_done.emit(None, "")


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("error", [False, True])
def test_downloader_actions_keep_focus_and_block_overlap(window, qapp, monkeypatch, index, error):  # noqa: F811
    from soundboard.ui.settings import connection
    monkeypatch.setattr(net, "allowed", lambda key: True)
    workers = []

    class DeferredThread:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            workers.append(self.target)

    monkeypatch.setattr(connection, "threading", type("Threads", (), {"Thread": DeferredThread}))
    jobs = []

    def job(**kw):
        jobs.append(1)
        if error:
            raise OSError("offline")
        return "Done."

    monkeypatch.setattr(connection.ytdl, "update", job)
    monkeypatch.setattr(connection.ytdl, "reset", job)
    d = _open_in_window(window, qapp, "updates")
    btn = d.ytdlp_btns[index]
    btn.setFocus()
    QTest.mouseClick(btn, Qt.LeftButton)
    assert d.focusWidget() is btn
    assert all(b.isEnabled() and busy.is_busy(b) for b in d.ytdlp_btns)
    for b in d.ytdlp_btns:
        QTest.mouseClick(b, Qt.LeftButton)
    d.connection._ytdlp_run(job)
    assert len(workers) == 1
    btn.setFocus()
    workers.pop()()
    qapp.processEvents()
    assert jobs == [1] and d.focusWidget() is btn
    assert all(not busy.is_busy(b) for b in d.ytdlp_btns)
    assert ("Couldn't update" if error else "Done.") in d.ytdlp_note.text()
    QTest.keyClick(btn, Qt.Key_Space)
    assert len(workers) == 1
    workers.pop()()


def test_search_words_skip_widgets_kept_as_a_name(qapp):
    from PySide6.QtWidgets import QLabel, QWidget
    from soundboard.ui.settings.settings import SettingsDialog
    card = QWidget()
    holder = QWidget(card)
    holder.name = QLabel("Speaker", holder)   # a widget's own label kept as `name`
    named = QWidget(card)
    named.name = "Midnight"                    # a painted name
    words = SettingsDialog._words_of(card)
    assert "midnight" in words and "speaker" in words
    assert "pyside" not in words and "object at" not in words


def test_basics_first_and_show_advanced(window, qapp):  # noqa: F811
    """The everyday pages come first; the rest wait behind Show advanced, which opens
    by itself for a link to one of them and is remembered."""
    window.cfg.settings_advanced = False
    d = SettingsDialog(window, lazy=True)
    try:
        keys, cats, adv = d._page_keys, d.categories, d._adv_row
        assert keys[0] == "audio" and keys.index("privacy") > adv
        assert all(cats.item(i).isHidden() for i in range(adv + 1, cats.count()))
        assert not cats.item(adv).isHidden() and cats.item(d.tabs.currentIndex()).text() == "Audio"
        assert not cats.item(adv).flags() & Qt.ItemFlag.ItemIsSelectable
        d._row_clicked(cats.item(adv))
        assert d._advanced and window.cfg.settings_advanced
        assert not any(cats.item(i).isHidden() for i in range(cats.count()))
        assert keys[d.tabs.currentIndex()] == "audio"   # the page stays
        d._row_clicked(cats.item(adv))   # a double click's second click: still open
        assert d._advanced
        d.show_page("privacy")
        d._adv_clicked.invalidate()
        d._row_clicked(cats.item(adv))   # folding away the page you're on: back to Audio
        assert not d._advanced and keys[d.tabs.currentIndex()] == "audio"
        d.show_page("updates")   # a link to an advanced page opens them
        assert d._advanced and keys[d.tabs.currentIndex()] == "updates"
        assert cats.currentRow() == d.tabs.currentIndex()
    finally:
        d.close()


def test_every_card_heading_has_its_icon_on_one_line(window, qapp):  # noqa: F811
    """Every Settings card's heading has an icon in front (like the Mic effect card's), and
    a heading that fits stays on one line: sharing its row with a stretch, "Custom
    voices (text-to-speech)" wrapped at half the card's width."""
    window.resize(1180, 820)
    window.show()
    d = window.setctl.open_settings("audio")   # a page in the window, as the cog opens it
    try:
        for i, key in enumerate(d._page_keys):
            if key == d.ADVANCED:
                continue
            d.show_page(key)
            for _ in range(3):
                qapp.processEvents()
            for card in d.tabs.widget(i).widget().findChildren(QFrame, "setcard"):
                title = next((lb for lb in card.findChildren(QLabel, "section")), None)
                assert title is not None
                # (the Mic effect card paints its own: any picture beside the title)
                marks = [lb for lb in card.findChildren(QLabel)
                         if not lb.pixmap().isNull() and lb.y() <= title.y() + title.height()]
                assert marks, (key, title.text())
                if title.isVisible():
                    one = title.fontMetrics().horizontalAdvance(title.text())
                    room = card.width() - 28 - 26   # the card's margins, the icon and gap
                    if one < room:   # it fits: one line, as wide as its words
                        assert title.width() >= one, (key, title.text())
    finally:
        d.accept()


def test_helper_lookup_finishing_after_window_closed(qapp):
    """The helper rows' lookup runs on a worker; when the main window is gone before
    it answers (the app closing), its answer is dropped, not a "Signal source has
    been deleted" crash on the worker."""
    import threading
    from types import SimpleNamespace

    import shiboken6

    from soundboard.ui.settings.privacy import PrivacyPage
    mw = QObject()
    shown, go = [], threading.Event()
    page = SimpleNamespace(mw=mw, _helpers_show=shown.append)
    PrivacyPage._off_ui(page, lambda: go.wait(5) and {"ytdlp": ("1", False)},
                        "test-helper-lookup")
    worker = next(t for t in threading.enumerate() if t.name == "test-helper-lookup")
    shiboken6.delete(mw)   # takes the relay with it
    go.set()
    worker.join(5)
    process_events(qapp, lambda: False, timeout=0.3)
    assert shown == []


def test_downloads_card_shows_each_helper_program(window, qapp, monkeypatch, tmp_path):  # noqa: F811
    """yt-dlp, the JavaScript engine and Tor (only once it's here) each get a row like
    FFmpeg's: a version pill and a hint, looked up off the UI thread, and Update now /
    Update Tor doing what the Updates and Connection pages do. Offline mode hides those."""
    import threading

    from soundboard.online import jsengine, tor, torget, ytdl
    off_ui = []

    def version():
        off_ui.append(threading.current_thread() is not threading.main_thread())
        return ("2026.9.1", False)

    def engines():
        off_ui.append(threading.current_thread() is not threading.main_thread())
        return [jsengine.Engine("deno", "deno.exe", (2, 4, 1))]
    monkeypatch.setattr(ytdl, "active_version", version)
    monkeypatch.setattr(jsengine, "picked", engines)
    monkeypatch.setattr(tor, "available", lambda: False)
    monkeypatch.setattr(net, "allowed", lambda key: True)
    d = _open_in_window(window, qapp, "updates")
    try:
        assert process_events(qapp, lambda: "Checking…" not in (d.ytdlp_state.text(),
                                                                 d.js_state.text()))
        assert off_ui and all(off_ui)
        assert d.ytdlp_state.text() == "Working: version 2026.9.1"
        assert d.js_state.text() == "Working: Deno 2.4 (faster)"
        assert d.tor_row.isHidden()          # no Tor here: no row for it
        upd = d.ytdlp_btns[0]
        assert not upd.isHidden() and upd.isEnabled()

        # Update now: yt-dlp's row says how it went
        monkeypatch.setattr(ytdl, "update", lambda: "Updated yt-dlp to 2099.1.1.")
        upd.click()
        assert busy.is_busy(upd) and upd.isEnabled()
        monkeypatch.setattr(ytdl, "active_version", lambda: ("2099.1.1", True))
        assert process_events(qapp, lambda: d.ytdlp_state.text() == "Working: version 2099.1.1")
        assert not busy.is_busy(upd)
        assert d.ytdlp_note.text() == "Updated yt-dlp to 2099.1.1."

        # Tor found, an older copy: its row shows and offers the Connection page's download
        bin_dir = tmp_path / "tor" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / torget.STAMP).write_text("15.0.1 old", "ascii")
        monkeypatch.setattr(torget, "bin_dir", lambda: bin_dir)
        monkeypatch.setattr(tor, "available", lambda: True)
        monkeypatch.setattr(tor, "bundle_dir", lambda: bin_dir)
        d._helpers_refresh()
        assert process_events(qapp, lambda: not d.tor_row.isHidden())
        assert d.tor_state.text() == "Installed: version 15.0.1"
        assert d.tor_row_btn.text() == "Update Tor" and "newer Tor" in d.tor_note.text()
        got = []
        monkeypatch.setattr(torget, "get", lambda progress, before_unpack=None: got.append(1))
        d.tor_row_btn.click()
        assert process_events(qapp, lambda: got and not busy.is_busy(d.tor_row_btn))

        # Offline mode: what would go online is hidden; the versions stay
        net.configure_features(offline=True)
        d.privacy._offline_sync()
        assert all(b.isHidden() for b in d.ytdlp_btns) and d.tor_row_btn.isHidden()
        assert not d.tor_row.isHidden()
    finally:
        net.configure_features()
        d.accept()


def test_expert_audio_cards_wait_for_show_advanced(window, qapp):  # noqa: F811
    """Basic Audio is devices and who's listening: buffering, speech servers, recovery
    and the mic switch (the footer has it) come with Show advanced, or a search."""
    window.cfg.settings_advanced = False
    d = SettingsDialog(window, "audio", lazy=True)
    try:
        page = d._tab_page(d._page_keys.index("audio"))
        cards = [c for c in page.findChildren(QFrame, "setcard") if c.property("adv_card")]
        assert len(cards) >= 3 and all(c.isHidden() for c in cards)
        more = [b for b in page.findChildren(QPushButton) if b.text() == "More audio settings"]
        assert len(more) == 1 and not more[0].isHidden()
        d._apply_search("buffering")   # a search still finds one
        assert any(not c.isHidden() for c in cards)
        d._apply_search("")
        assert all(c.isHidden() for c in cards)
        more[0].click()
        assert d._advanced and all(not c.isHidden() for c in cards) and more[0].isHidden()
    finally:
        d.done(0)


def test_narrow_rail_icons_sit_in_the_middle_of_their_highlight(window, qapp):  # noqa: F811
    """Narrow, a category is an icon with no name: the icon is drawn in the middle of
    its row (the style put it at the left, twice the room on its right)."""
    from PySide6.QtGui import QIcon, QImage, QPixmap

    d = _open_in_window(window, qapp, "general", width=560)
    try:
        cats = d.categories
        assert cats.width() == 48 and not cats.item(0).text()
        red = QPixmap(20, 20)
        red.fill(QColor("red"))
        cats.item(0).setIcon(QIcon(red))
        rect = cats.visualItemRect(cats.item(0))
        img = cats.viewport().grab(rect).toImage().convertToFormat(QImage.Format.Format_RGB32)
        xs = [x for x in range(img.width()) for y in range(img.height())
              if img.pixelColor(x, y).red() > 200 and img.pixelColor(x, y).green() < 60]
        assert xs
        assert abs(min(xs) - (img.width() - 1 - max(xs))) <= 2
    finally:
        d.close()


def test_the_category_list_looks_like_the_rails_tabs(window):  # noqa: F811
    """Settings' list drew bigger, brighter icons and words than the main rail's tabs,
    a sub-menu louder than the menu: same icon size and weight now, muted till picked."""
    from PySide6.QtGui import QFontInfo
    from PySide6.QtWidgets import QToolButton

    from soundboard.ui.window.railsizes import ICON
    d = window.setctl.open_settings("audio")
    cats = d.categories
    tab = next(b for b in window.findChildren(QToolButton) if b.objectName() == "railtab")
    assert cats.iconSize().width() == tab.iconSize().width() == ICON
    assert cats.font().weight() == tab.font().weight()
    assert QFontInfo(cats.font()).pixelSize() == QFontInfo(tab.font()).pixelSize()
