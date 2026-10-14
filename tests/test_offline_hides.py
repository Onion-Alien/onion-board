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
        window.tabctl.set_tab_on(key, True)
    bar = window.tabs
    try:
        assert window.netctl.card_lines() == [] and bar.isTabVisible(TAB_INDEX["radio"])
        window.tabs.setCurrentIndex(TAB_INDEX["radio"])
        offline(window, True)
        assert [line.words for line in window.netctl.card_lines()] == ["Offline"]   # in the card
        assert window.rail.output._lines == window.netctl.card_lines()
        assert not bar.isTabVisible(TAB_INDEX["radio"])
        assert bar.currentIndex() == 0   # was on Radio: back to the Sounds tab
        # no Onion Watch in the test profile: the Triggers tab is only its Get button
        assert not bar.isTabVisible(TAB_INDEX["triggers"])
        assert bar.isTabVisible(TAB_INDEX["apps"])   # works offline: stays
        assert window.btn_yt.isHidden()
        assert window.search.placeholderText() == "Search your sounds"
        # + More tabs doesn't offer them either
        window.tabctl.set_tab_on("apps", False)
        assert window.tabctl._more_tab_keys() == ["apps"]
        offline(window, False)
        assert window.netctl.card_lines() == [] and window.rail.output._lines == []
        assert bar.isTabVisible(TAB_INDEX["radio"]) and bar.isTabVisible(TAB_INDEX["triggers"])
        assert not window.btn_yt.isHidden()
        assert "paste a link" in window.search.placeholderText()
    finally:
        offline(window, False)


def test_offline_start_hides_them_from_the_first_paint(window):  # noqa: F811
    window.tabctl.set_tab_on("radio", True)
    offline(window, True)
    try:
        window.tabctl.set_tab_on("radio", False)
        window.tabctl.set_tab_on("radio", True)   # switched on while offline: still hidden
        assert not window.tabs.isTabVisible(TAB_INDEX["radio"])
    finally:
        offline(window, False)
    assert window.tabs.isTabVisible(TAB_INDEX["radio"])


def test_cable_install_button_goes_but_the_mic_setup_stays(window):  # noqa: F811
    window.cfg.route = "cable"
    window.statusctl._update_flow()
    shown_online = not window.btn_install.isHidden()
    offline(window, True)
    try:
        assert window.btn_install.isHidden()   # it downloads VB-Cable
        window.cfg.route = "mic"
        window.statusctl._update_flow()
        assert window.btn_install.isEnabled()   # setting up the mic goes nowhere online
    finally:
        window.cfg.route = "cable"
        offline(window, False)
    window.statusctl._update_flow()
    assert (not window.btn_install.isHidden()) == shown_online


def test_settings_hides_online_pages_and_cards(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_save_later", lambda: None)
    window.tabctl.set_tab_on("radio", True)
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
    window.tabctl.set_tab_on("triggers", True)
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


def test_on_air_card_says_proxy_and_tor(window, monkeypatch):  # noqa: F811
    from soundboard import tor

    def line():
        lines = window.rail.output._lines
        assert len(lines) == 1
        return lines[0].icon, lines[0].words, lines[0].tone

    try:
        net.configure(net.PROXY, "socks5h://127.0.0.1:9050")
        QApplication.processEvents()
        assert line() == ("shield", "Through proxy", "ok")
        net.configure(net.PROXY, "not a proxy::")
        assert line()[2] == "warn"
        net.configure(net.TOR)
        t = tor.manager()
        for state, words, tone in ((tor.STARTING, "Tor 40%", ""),
                                   (tor.READY, "Through Tor", "ok"),
                                   (tor.FAILED, "Tor failed", "warn")):
            monkeypatch.setattr(t, "state", state)
            monkeypatch.setattr(t, "progress", 40)
            window.netctl._on_tor()
            assert line() == ("tor", words, tone)
        clicked = []
        monkeypatch.setattr(window.setctl, "open_settings", clicked.append)
        window.rail.output.net[0].click()
        assert clicked == ["privacy"]
    finally:
        net.configure(net.DIRECT)
        QApplication.processEvents()
    assert window.rail.output._lines == []


def test_on_air_card_says_a_remote_listens(window, monkeypatch):  # noqa: F811
    from soundboard import remote

    ctl = remote.RemoteControl(lambda a, p: (200, {}), window)
    try:
        assert ctl.start(0, "k" * 32)
        for _ in range(3):
            QApplication.processEvents()   # (queued: it may come from another thread)
        assert [line.words for line in window.rail.output._lines] == ["Remote control on"]
        ctl.lan = True   # a phone remote's server says so instead
        window.netctl._net_follow()
        assert [(line.words, line.page) for line in window.rail.output._lines] == [
            ("Phone remote on", "remote")]
    finally:
        ctl.stop()
    for _ in range(3):
        QApplication.processEvents()
    assert window.rail.output._lines == []
