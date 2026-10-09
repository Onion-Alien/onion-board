"""Offline mode hides what only works online (the Radio tab, Triggers without Onion
Watch, the web search, downloads, updates…) instead of leaving it greyed out, says
it's offline in the header, and brings it all back when it's switched off."""
from PySide6.QtWidgets import QApplication

from soundboard import net
from soundboard.settings import SettingsDialog
from soundboard.ui.mainwindow import TAB_INDEX
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def offline(mw, on: bool):
    mw.cfg.net_offline = on
    net.configure_features(mw.cfg.net_off, on)
    QApplication.processEvents()


def test_main_window_hides_the_online_tabs_and_says_offline(window, monkeypatch):  # noqa: F811
    for key in ("radio", "triggers", "apps"):
        window.set_tab_on(key, True)
    bar = window.tabs
    try:
        assert window.btn_offline.isHidden() and bar.isTabVisible(TAB_INDEX["radio"])
        window.tabs.setCurrentIndex(TAB_INDEX["radio"])
        offline(window, True)
        assert not window.btn_offline.isHidden()
        assert not bar.isTabVisible(TAB_INDEX["radio"])
        assert bar.currentIndex() == 0   # was on Radio: back to the Sounds tab
        # no Onion Watch in the test profile: the Triggers tab is only its Get button
        assert not bar.isTabVisible(TAB_INDEX["triggers"])
        assert bar.isTabVisible(TAB_INDEX["apps"])   # works offline: stays
        assert window.btn_yt.isHidden()
        assert window.search.placeholderText() == "Search your sounds"
        # + More tabs doesn't offer them either
        window.set_tab_on("apps", False)
        assert window._more_tab_keys() == ["apps"]
        offline(window, False)
        assert window.btn_offline.isHidden()
        assert bar.isTabVisible(TAB_INDEX["radio"]) and bar.isTabVisible(TAB_INDEX["triggers"])
        assert not window.btn_yt.isHidden()
        assert "paste a link" in window.search.placeholderText()
    finally:
        offline(window, False)


def test_offline_start_hides_them_from_the_first_paint(window):  # noqa: F811
    window.set_tab_on("radio", True)
    offline(window, True)
    try:
        window.set_tab_on("radio", False)
        window.set_tab_on("radio", True)   # switched on while offline: still hidden
        assert not window.tabs.isTabVisible(TAB_INDEX["radio"])
    finally:
        offline(window, False)
    assert window.tabs.isTabVisible(TAB_INDEX["radio"])


def test_cable_install_button_goes_but_the_mic_setup_stays(window):  # noqa: F811
    window.cfg.route = "cable"
    window._update_flow()
    shown_online = not window.btn_install.isHidden()
    offline(window, True)
    try:
        assert window.btn_install.isHidden()   # it downloads VB-Cable
        window.cfg.route = "mic"
        window._update_flow()
        assert window.btn_install.isEnabled()   # setting up the mic goes nowhere online
    finally:
        window.cfg.route = "cable"
        offline(window, False)
    window._update_flow()
    assert (not window.btn_install.isHidden()) == shown_online


def test_settings_hides_online_pages_and_cards(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_save_later", lambda: None)
    window.set_tab_on("radio", True)
    keys = None
    d = SettingsDialog(window, "connection")
    try:
        keys = d._page_keys
        conn = d.tabs.widget(keys.index("connection")).widget()
        conn_card = next(c for c in d._offline_cards if c.parentWidget() is conn)
        assert not conn_card.isHidden()
        offline(window, True)
        d._net_sync()
        assert conn_card.isHidden()   # proxy / Tor: no use offline
        for page in ("data", "updates"):
            assert d.categories.item(keys.index(page)).isHidden()
        assert not d.categories.item(keys.index("privacy")).isHidden()
        d.tabs.setCurrentIndex(keys.index("tabs"))
        QApplication.processEvents()
        assert not d.tab_boxes["radio"].isEnabled()
        assert "Offline mode" in d.tab_boxes["radio"].toolTip()
        assert d.tab_boxes["apps"].isEnabled()
        # a search doesn't bring them back
        d.search_box.setText("proxy")
        d._apply_search("proxy")
        assert conn_card.isHidden() and d.categories.item(keys.index("updates")).isHidden()
        d.search_box.setText("")
        d._apply_search("")
        assert conn_card.isHidden()
        offline(window, False)
        d._net_sync()
        assert not conn_card.isHidden()
        assert not d.categories.item(keys.index("updates")).isHidden()
        assert d.tab_boxes["radio"].isEnabled()
    finally:
        d.close()
        offline(window, False)


def test_settings_opened_offline_on_a_hidden_page_lands_on_privacy(window):  # noqa: F811
    offline(window, True)
    d = SettingsDialog(window, "updates")
    try:
        assert d._page_keys[d.tabs.currentIndex()] == "privacy"
        assert d._net_body.isHidden() and d.offline_box.isChecked()
    finally:
        d.close()
        offline(window, False)


def test_addons_without_one_installed_goes_offline(window):  # noqa: F811
    window.set_tab_on("triggers", True)
    d = SettingsDialog(window, "help")
    try:
        card = d._addons_card_w
        assert not card.isHidden() and not d.watch_buttons["get"].isHidden()
        offline(window, True)
        d._net_sync()
        assert card.isHidden()   # neither add-on is installed in the test profile
        offline(window, False)
        d._net_sync()
        assert not card.isHidden() and not d.watch_buttons["get"].isHidden()
        assert not d.watch_buttons["report"].isHidden()
    finally:
        d.close()
        offline(window, False)
