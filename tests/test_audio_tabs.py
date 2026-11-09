"""Settings → Audio's tabs (AudioTabs): one group of cards at a time, a tab only with
something to show, a search that finds cards on every tab, links that land on the right one."""
import pytest
from conftest import process_events
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard.ui.settings.settings import SettingsDialog
from soundboard.ui.setup.audiorecovery import RecoveryCard
from soundboard.ui.setup.destpanel import DestPanel


@pytest.fixture
def page(window, qapp):  # noqa: F811
    window.cfg.route = "mic"
    d = SettingsDialog(window, "audio")
    d.resize(1000, 700)
    d.show()
    qapp.processEvents()
    yield d
    d.close()


def _chips(d):
    return [c.text() for c in d.audio_tabs.chips if not c.isHidden()]


def _showing(d):
    return [p for p in d.audio_tabs.pages if not p.isHidden()]


def test_one_tab_shows_at_a_time_and_each_holds_its_cards(page):
    tabs = page.audio_tabs
    assert _chips(page) == ["Mic and speakers", "Who's listening", "Voices", "Sound driver"]
    assert _showing(page) == [tabs.pages[0]] and tabs.chips[0].isChecked()
    assert tabs.pages[0].isAncestorOf(page.dev_combos[0][0])   # the output device
    assert tabs.pages[1].findChild(DestPanel) is not None
    assert tabs.pages[2].isAncestorOf(page.clean_card)
    assert tabs.pages[2].isAncestorOf(page.voices_card)
    assert tabs.pages[3].findChild(RecoveryCard) is not None
    for i, chip in enumerate(tabs.chips):
        chip.click()
        assert _showing(page) == [tabs.pages[i]] and chip.isChecked()


def test_the_your_mic_card_moves_only_when_a_place_for_it_shows(window, qapp):  # noqa: F811
    """It moves to its tab when that shows and home when Setup shows, never just for
    leaving: each move restyles the whole card (a stall on a slower PC)."""
    home = window.how_home
    window.show()
    window.tabs.setCurrentIndex(0)   # (not Setup)
    d = window.setctl.open_settings("audio")
    tabs = d.audio_tabs
    process_events(qapp, lambda: home.card.parentWidget() is not home, 2)
    assert tabs.pages[0].isAncestorOf(home.card)
    tabs.chips[1].click()
    assert tabs.pages[0].isAncestorOf(home.card)   # (stays: nothing else shows it)
    tabs.chips[0].click()
    assert tabs.pages[0].isAncestorOf(home.card)
    window.setctl.close_settings()
    assert tabs.pages[0].isAncestorOf(home.card)   # (closed onto a tab without it)
    window.setctl.open_settings()
    assert tabs.pages[0].isAncestorOf(home.card)   # (opened again: already there)
    window.tabs.setCurrentWidget(window.setup_page)   # (closes Settings, shows Setup)
    process_events(qapp, lambda: home.card.parentWidget() is home, 2)
    assert home.card.parentWidget() is home and home.card.isVisible()


def test_away_its_home_keeps_the_cards_size(window, qapp):  # noqa: F811
    """Setup (and the room the window needs) measure the same with the card visiting."""
    home = window.how_home
    window.show()
    window.tabs.setCurrentIndex(0)
    qapp.processEvents()
    before = (home.sizeHint(), home.minimumSizeHint(), home.heightForWidth(500))
    window.setctl.open_settings("audio")
    process_events(qapp, lambda: home.card.parentWidget() is not home, 2)
    window.setctl.close_settings()
    assert home.away()
    assert (home.sizeHint(), home.minimumSizeHint(), home.heightForWidth(500)) == before


@pytest.mark.parametrize("how", ["freed", "page rebuilt"])
def test_a_settings_freed_with_the_card_in_it_gives_it_back(window, qapp, how):  # noqa: F811
    from shiboken6 import isValid
    from soundboard.ui.window import settingscontrol
    home = window.how_home
    window.show()
    window.tabs.setCurrentIndex(0)
    d = window.setctl.open_settings("audio")
    process_events(qapp, lambda: home.card.parentWidget() is not home, 2)
    window.setctl.close_settings()
    assert home.away()
    if how == "freed":
        window.setctl._settings_kept = None
        settingscontrol.free_dialog(d)
    else:
        i = d._page_keys.index("audio")
        d._stale.add(i)
        d._rebuild_page(i)
    assert isValid(home.card) and home.card.parentWidget() is home


def test_the_driver_tab_goes_off_the_mic_route(page, window):  # noqa: F811
    """On the cable the Sound driver card goes, so its tab does; on it, you land on the first."""
    tabs = page.audio_tabs
    card = page.findChild(RecoveryCard)
    tabs.open_tab("driver")
    window.cfg.route = "cable"
    card._follow_route()
    assert "Sound driver" not in _chips(page)
    assert _showing(page) == [tabs.pages[0]] and tabs.chips[0].isChecked()
    tabs.open_tab("driver")                    # (a link to it: stays where it is)
    assert tabs.shown == 0
    window.cfg.route = "mic"
    card._follow_route()
    assert "Sound driver" in _chips(page)


def test_the_voices_tab_goes_with_the_voice_tab(page, window, qapp):  # noqa: F811
    window.tabctl.set_tab_on("voice", False)
    qapp.processEvents()
    assert "Voices" not in _chips(page)
    window.tabctl.set_tab_on("voice", True)
    qapp.processEvents()
    assert "Voices" in _chips(page) and not page.clean_card.isHidden()


def test_show_advanced_adds_its_cards_to_their_tabs(page):
    tabs = page.audio_tabs
    page._set_advanced(False)
    assert page.voices_card.isHidden()
    page._set_advanced(True)
    tabs.open_tab("voices")
    assert not page.voices_card.isHidden() and _showing(page) == [tabs.pages[2]]
    page._set_advanced(False)


@pytest.mark.parametrize("query, tab", [("buffering", 0), ("listening", 1),
                                        ("voice server", 2), ("discord", 3)])
def test_a_search_finds_a_card_on_any_tab_and_clearing_it_restores_the_tab(page, query, tab):
    tabs = page.audio_tabs
    tabs.open_tab("voices" if tab != 2 else "listening")
    was = tabs.shown
    page._apply_search(query)
    assert page._page_keys[page.tabs.currentIndex()] == "audio"
    assert tabs.bar.isHidden() and not tabs.pages[tab].isHidden()
    assert any(not c.isHidden() for c in tabs.pages[tab].findChildren(type(page.clean_card),
                                                                      "setcard"))
    page._apply_search("")
    assert not tabs.bar.isHidden() and _showing(page) == [tabs.pages[was]]
    assert tabs.chips[was].isChecked()


@pytest.mark.parametrize("key, i", [("listening", 1), ("driver", 3)])
def test_open_audio_lands_on_the_tab(window, qapp, key, i):  # noqa: F811
    window.cfg.route = "mic"
    d = window.setctl.open_audio(key)
    qapp.processEvents()
    assert d.audio_tabs.shown == i and d.audio_tabs.chips[i].isChecked()
    d.accept()
