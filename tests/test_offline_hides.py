"""Offline mode hides what only works online (the Radio tab, Triggers without Onion
Watch, the web search, downloads, updates…) instead of leaving it greyed out, says
it's offline in the header, and brings it all back when it's switched off."""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

from soundboard.online import net
from soundboard.sounds import packs
from soundboard.ui.settings.settings import SettingsDialog
from soundboard.ui.window.tabcontrol import TAB_INDEX


def offline(mw, on: bool):
    mw.cfg.net_offline = on
    net.configure_features(mw.cfg.net_off, on)
    QApplication.processEvents()


def test_main_window_hides_the_online_tabs_and_says_offline(window, monkeypatch):  # noqa: F811
    # shown and roomy: the search box only takes the room the toolbar can spare (a
    # never-shown window measures as too narrow, and test fonts run wide)
    window.resize(1920, 1080)
    window.show()
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
        d.connection._net_sync()
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
        d.connection._net_sync()
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
        d.connection._net_sync()
        assert card.isHidden()   # neither add-on is installed in the test profile
        offline(window, False)
        d.connection._net_sync()
        assert not card.isHidden() and not d.watch_buttons["get"].isHidden()
        assert not d.watch_buttons["report"].isHidden()
    finally:
        d.close()
        offline(window, False)


def test_on_air_card_says_proxy_and_tor(window, monkeypatch):  # noqa: F811
    from soundboard.online import tor

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
    from soundboard.control import remote

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


def test_add_menu_drops_from_a_link_and_gets_it_back(window):  # noqa: F811
    link = next(a for a in window._add_menu.actions() if a.text() == "From a link")
    assert link.isVisible() and "a link" in window.btn_add.toolTip()
    offline(window, True)
    try:
        window.netctl._follow_switches()
        assert not link.isVisible()
        assert "link" not in window.btn_add.toolTip()
        shown = [a.text() for a in window._add_menu.actions() if a.isVisible()]
        assert shown == ["Sound files", "A whole folder", "Record"]   # the rest stay
    finally:
        offline(window, False)
    window.netctl._follow_switches()
    assert link.isVisible() and "a link" in window.btn_add.toolTip()


def test_community_tab_goes_and_comes_back(window):  # noqa: F811
    i = TAB_INDEX["store"]
    window.tabctl.set_tab_on("store", True)
    window.tabs.setCurrentIndex(i)
    offline(window, True)
    try:
        window.netctl._follow_switches()
        assert not window.tabs.isTabVisible(i)
        assert window.tabs.currentIndex() == 0   # was on Community: back to Sounds
        assert window.tabctl.needs_online("store")
        window.tabctl.set_tab_on("store", False)
        assert "store" not in window.tabctl._more_tab_keys()   # + More tabs doesn't offer it
        window.tabctl.set_tab_on("store", True)
        assert not window.tabs.isTabVisible(i)   # switched on while offline: still hidden
    finally:
        offline(window, False)
    window.netctl._follow_switches()
    assert window.tabs.isTabVisible(i)


def test_free_sound_packs_needs_a_pack_already_here_offline(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(packs.Pack, "downloaded", lambda self: False)
    window.btn_more.menu().aboutToShow.emit()
    assert window._packs_act.isVisible()   # online: always
    offline(window, True)
    try:
        window.btn_more.menu().aboutToShow.emit()
        assert not window._packs_act.isVisible()
        monkeypatch.setattr(packs.Pack, "downloaded", lambda self: True)
        window.btn_more.menu().aboutToShow.emit()
        assert window._packs_act.isVisible()   # a pack here can still be added
    finally:
        offline(window, False)


def test_packs_page_lists_only_the_packs_here_offline(window, monkeypatch):  # noqa: F811
    here = packs.built_in()[0]
    monkeypatch.setattr(packs.Pack, "downloaded", lambda self: self.id == here.id)
    offline(window, True)
    try:
        window.impctl.show_packs()
        page = window.impctl._packs_page
        for _ in range(30):
            QApplication.processEvents()
        assert page.btn_share.isHidden()
        assert [c.pack.id for c in page.cards] == [here.id]
        page.reject()
    finally:
        offline(window, False)
    window.impctl.show_packs()
    page = window.impctl._packs_page
    assert not page.btn_share.isHidden()
    page.reject()


def test_picture_from_a_link_goes_offline(window):  # noqa: F811
    from soundboard.ui.sounds.dialogs import EditDialog
    m = window.meta("s0")
    d = EditDialog(m, window.hotkeys, lambda *a: None, window)
    assert not d.btn_pic_link.isHidden()
    d.close()
    offline(window, True)
    try:
        d = EditDialog(m, window.hotkeys, lambda *a: None, window)
        assert d.btn_pic_link.isHidden() and not d.btn_pic_file.isHidden()
        d.close()
    finally:
        offline(window, False)


def test_share_to_the_store_goes_from_voice_combos(window, monkeypatch):  # noqa: F811
    from soundboard.ui.voice import voicesetupsbar
    bar = window.voice.setups_bar
    seen = []

    class Shown(QMenu):
        def exec(self, *_a):
            seen.append([a.text() for a in self.actions()])

    monkeypatch.setattr(voicesetupsbar, "QMenu", Shown)
    bar.share = lambda _n: None
    bar.copy_code = lambda _n: True
    offline(window, True)
    try:
        window.voice._follow_offline()
        assert bar.btn_share.toolTip() == "Copy share code"
        bar._menu("a combo", QPoint(0, 0))
        assert seen[-1] and "Share to the store…" not in seen[-1]
        assert "Copy share code" in seen[-1]
    finally:
        offline(window, False)
    window.voice._follow_offline()
    assert "store" in bar.btn_share.toolTip()
    bar._menu("a combo", QPoint(0, 0))
    assert "Share to the store…" in seen[-1]


def test_clean_mics_strong_has_no_dead_download(window, monkeypatch):  # noqa: F811
    from soundboard.voicefx import deepfilter
    clean = window.voice.clean
    strong = clean.b_strength["strong"]
    monkeypatch.setattr(deepfilter, "downloaded", lambda: False)
    clean.s["strength"] = "normal"
    clean._show()
    assert not strong.isHidden()
    offline(window, True)
    try:
        window.voice._follow_offline()
        assert strong.isHidden()
        presets = clean.settings.b_preset
        assert presets["loud"].isHidden() and presets["voice"].isHidden()   # they need Strong
        assert not presets["normal"].isHidden() and not presets["quiet"].isHidden()
        clean._pick("strong")   # a voice combo saved with Strong can still ask for it
        assert clean.b_get.isHidden() and "Offline mode" in clean.lbl_get.text()
        offline(window, False)
        window.voice._follow_offline()   # back online with the offer open: Download's back
        assert not strong.isHidden() and not presets["loud"].isHidden()
        assert not clean.b_get.isHidden() and "download" in clean.lbl_get.text()
        clean.get_box.hide()
        monkeypatch.setattr(deepfilter, "downloaded", lambda: True)
        offline(window, True)
        window.voice._follow_offline()
        assert not strong.isHidden()   # it's here: it works offline
    finally:
        offline(window, False)
        window.voice._follow_offline()


def test_twitch_card_goes_offline(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QFrame

    from soundboard.ui.settings import twitchcard
    card = QFrame()
    monkeypatch.setattr(twitchcard, "twitch_card", lambda _page: card)
    monkeypatch.setattr(window, "_save_later", lambda: None)
    d = SettingsDialog(window, "remote")
    try:
        d.show_page("remote")
        QApplication.processEvents()
        assert not card.isHidden()
        offline(window, True)
        d.privacy._offline_sync()
        assert card.isHidden()
        offline(window, False)
        d.privacy._offline_sync()
        assert not card.isHidden()
    finally:
        d.close()
        offline(window, False)


def _menu_words(monkeypatch, mod) -> list:
    """Menus in `mod` open as a QMenu that notes its words instead of blocking."""
    seen = []

    class Shown(QMenu):
        def exec(self, *_a):
            words = []
            for a in self.actions():
                words.append(a.text())
                if a.menu() is not None:
                    words += [s.text() for s in a.menu().actions()]
            seen.append(words)

    monkeypatch.setattr(mod, "QMenu", Shown)
    return seen


def test_share_to_the_store_goes_from_a_pad_from_a_link(window, monkeypatch):  # noqa: F811
    from test_sourceinfo import SRC

    from soundboard.ui.window import padcontrol
    seen = _menu_words(monkeypatch, padcontrol)
    window.meta("s0").source = dict(SRC)
    window.padctl.pad_menu("s0", QPoint(0, 0))
    assert "Share to the store" in seen[-1]
    offline(window, True)
    try:
        window.padctl.pad_menu("s0", QPoint(0, 0))
        assert "Share to the store" not in seen[-1]
        assert "Copy link" in seen[-1]   # a saved link is still yours to copy
    finally:
        offline(window, False)


def test_share_to_the_store_goes_from_a_saved_voice(window, monkeypatch):  # noqa: F811
    from soundboard.ui.voice import voicefxsaved
    seen = _menu_words(monkeypatch, voicefxsaved)
    fx = window.voice.fx
    fx.store.voices["Mine"] = {}
    try:
        fx._tile_menu("Mine", QPoint(0, 0))
        assert "Share to the store…" in seen[-1]
        offline(window, True)
        fx._tile_menu("Mine", QPoint(0, 0))
        assert "Share to the store…" not in seen[-1]
        assert "Copy share code" in seen[-1]
    finally:
        offline(window, False)
        del fx.store.voices["Mine"]
