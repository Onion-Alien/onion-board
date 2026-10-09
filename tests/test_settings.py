"""The Settings window's layout: pages scroll instead of squashing their rows."""
from contextlib import contextmanager

import pytest

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QScrollArea

from conftest import process_events
from soundboard import net
from soundboard.settings import SettingsDialog
from soundboard.ui import busy
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


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
    d = SettingsDialog(window, "help")
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
             "help": ("Add-ons", "Feedback and problems",
                         "Support Onion Board"),
             "updates": ("App updates", "Downloader (yt-dlp)"),
             "remote": ("Remote control (Stream Deck, scripts)", "Set it up the easy way")}
    for page, titles in where.items():
        d = SettingsDialog(window, page)
        shown = {lb.text() for lb in d.tabs.currentWidget().widget().findChildren(QLabel)}
        assert set(titles) <= shown, page
        d.close()
    d = SettingsDialog(window, "nonsense")
    assert d.tabs.currentIndex() == 0
    d.close()


def test_the_cog_builds_only_the_page_it_opens_and_the_rest_when_shown(window):  # noqa: F811
    """Building all twelve pages under the app's style sheet took a second or two on
    every click of the cog: the window builds the others when they're first picked."""
    from soundboard import net
    net.configure_features(["app_update"], False)   # its button is on a page built later
    with windows_shown() as shown:
        d = SettingsDialog(window, "audio", lazy=True)
    assert shown == []
    built = [i for i in range(d.tabs.count()) if d.tabs.widget(i).widget() is not None]
    assert built == [d._page_keys.index("audio")]
    assert d.size().height() >= 600   # sized for the tall pages it hasn't built yet
    d.categories.setCurrentRow(d._page_keys.index("updates"))
    page = d.tabs.currentWidget().widget()
    assert page is not None and "App updates" in {lb.text() for lb in page.findChildren(QLabel)}
    assert not d.upd_btn.isEnabled()   # greyed by Privacy, though that page isn't built
    d.close()
    d = SettingsDialog(window, "nonsense", lazy=True)
    assert d.tabs.currentIndex() == 0 and d.tabs.widget(0).widget() is not None
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
    d = SettingsDialog(window, "help")
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
    from soundboard import feedback
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    d = SettingsDialog(window, "help")
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

    from soundboard import watchaddon
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


def test_update_preferences_have_one_home_and_privacy_links_to_it(window, monkeypatch):  # noqa: F811
    """Privacy grants network permission; update scheduling has one home in Updates."""
    from PySide6.QtWidgets import QCheckBox
    monkeypatch.setattr(window, "_save_later", lambda: None)
    monkeypatch.setattr(window, "check_updates", lambda *a, **k: None)
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
                d.categories.setCurrentRow(d._page_keys.index(key))
                for _ in range(3):
                    qapp.processEvents()
                sa = d.tabs.currentWidget()
                assert sa.widget().minimumSizeHint().width() <= sa.viewport().width(), key
                assert d.tabs.currentIndex() == d.categories.currentRow()
        assert "&&" in d.tabs.tabText(0)        # "&" alone would underline the next letter
    finally:
        d.close()


def test_theme_previews_reflow_when_settings_is_resized(window, qapp):  # noqa: F811
    from soundboard.settings import ThemeGrid

    d = SettingsDialog(window, "appearance")
    d.show()
    try:
        grid = d.findChildren(ThemeGrid)[0]
        for width, expected in ((1020, 4), (720, 2), (1200, 5), (720, 2)):
            d.resize(width, 760)
            for _ in range(5):
                qapp.processEvents()
            assert grid.columns == expected
            assert all(c.geometry().right() < grid.width() for c in grid.cards)
            assert len({id(c) for c in grid.cards}) == grid.grid.count()
            # spread out evenly: the last card in a full row ends at the right edge
            last = grid.cards[expected - 1].geometry()
            assert grid.width() - 1 - last.right() < expected
            assert grid.cards[0].geometry().left() == 0
    finally:
        d.close()


def test_each_switch_writes_its_setting_and_applies_at_once(window, monkeypatch):  # noqa: F811
    """Settings > Privacy & security: one switch per feature (and per sound site),
    saved in net_off and applied to soundboard.net straight away; sub-options grey out
    under a switch that's off, and Offline mode hides everything under it."""
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
        assert d._net_body.isHidden()   # Offline mode: hidden, not left greyed out
        d.offline_box.setChecked(False)
        assert not d._net_body.isHidden() and net.allowed("voices") and not net.allowed("radio")
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


def test_remote_page_copies_an_ai_prompt_with_the_key_only_when_ticked(window):  # noqa: F811
    from PySide6.QtWidgets import QApplication, QCheckBox
    window.cfg.api_enabled, window.cfg.api_token = True, "key-for-the-ai-test"
    d = SettingsDialog(window, "remote")
    try:
        ai = next(b for b in d.findChildren(QPushButton) if b.text() == "Copy AI prompt")
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
        window.apply_remote()


def test_about_shows_the_version_and_only_opens_pages(window, monkeypatch):  # noqa: F811
    from soundboard.ui.mainwindow import version_text
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


def test_live_tabs_comes_first_on_appearance_tint_or_dot(window, qapp):  # noqa: F811
    d = SettingsDialog(window, "appearance")
    assert d.live_green.isChecked() == window.cfg.live_tab_green
    card = d.live_green.parentWidget()
    assert card.findChild(QLabel).text() == "Live tabs"
    # right under the language, above the themes
    assert card.parentWidget().layout().itemAt(1).widget() is card
    d.live_dot.click()
    assert window.cfg.live_tab_green is False
    d.live_green.click()
    assert window.cfg.live_tab_green is True


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
    heads = [lb for lb in page.findChildren(QLabel) if lb.objectName() == "section"]
    assert heads
    for h in heads:
        h.setText("HELLO")                     # one shape: no letter's own bearing to compare
        qapp.processEvents()
        assert _ink_left(h) is not None and _ink_left(h) <= 1, h.text()
    d.close()


def test_highlight_colour_slides_saves_and_resets(window, qapp, monkeypatch):  # noqa: F811
    from soundboard import theme
    d = SettingsDialog(window, "appearance")
    # a colour change restyles only what's drawn in it: the whole app took seconds
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
        monkeypatch.undo()
        window.set_live_color("")
        d.close()


def test_language_comes_first_on_appearance_and_opens_the_picker(window, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QTimer
    from soundboard import i18n
    monkeypatch.setattr(i18n, "windows_language", lambda: "de-DE")
    restarts = []
    monkeypatch.setattr(window, "restart_app", lambda: restarts.append(1))
    d = SettingsDialog(window, "appearance")
    btn = d.lang_button
    card = btn.parentWidget()
    assert card.parentWidget().layout().itemAt(0).widget() is card    # first on the page
    # the title in Windows' language too: found by someone who can't read English
    assert card.findChild(QLabel).text() == "Language · Sprache"
    assert btn.text().startswith("English") and not d.lang_restart.isVisibleTo(d)
    seen = []

    def in_the_picker():
        dlg = d.lang_dialog
        seen.append(dlg.search.hasFocus() or True)
        dlg.search.setText("germ")                                   # English name
        assert [t.code for t in dlg.visible_tiles()] == ["de"]
        dlg.search.returnPressed.emit()                              # Enter picks it
    QTimer.singleShot(0, in_the_picker)
    btn.click()
    assert seen and window.cfg.language == "de" and not restarts   # saved, no surprise restart
    assert btn.text().startswith("Deutsch")
    # what happens next, in the language picked
    assert d.lang_note.text() == "Onion Board zeigt nach einem Neustart Deutsch an."
    assert d.lang_restart.text() == "Jetzt neu starten" and d.lang_restart.isVisibleTo(d)
    d.lang_restart.click()
    assert restarts == [1]
    d.close()


def test_a_board_reopened_shows_the_picked_language_on_the_button(window):  # noqa: F811
    window.cfg.language = "ja"
    d = SettingsDialog(window, "appearance")
    assert d.lang_button.text().startswith("日本語") and d.lang_restart.isVisibleTo(d)
    d.close()


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
        assert all(not d.categories.item(i).isHidden() for i in range(d.categories.count()))
        d._apply_search("no such words here")
        assert all(d.categories.item(i).isHidden() for i in range(d.categories.count()))
    finally:
        d.close()
