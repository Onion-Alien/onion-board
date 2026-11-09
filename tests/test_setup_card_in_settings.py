"""Setup's Your mic card shows at the top of Settings > Audio too: the same card, moved
there when that page shows and home when Setup shows (never just for leaving: each move
restyles the whole card)."""
from conftest import process_events
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen
import pytest


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_settings_audio_borrows_the_setup_card_and_setup_takes_it_back(window, qapp):
    home = window.how_home
    window.show()
    window.tabs.setCurrentIndex(0)   # (not Setup)
    dlg = window.setctl.open_settings("audio")
    process_events(qapp, lambda: home.card.parentWidget() is not home, 2)
    assert home.away() and home.card.isVisibleTo(dlg)
    dlg.show_page("hotkeys")   # another page: it stays (nothing else shows it)
    assert home.away()
    dlg.show_page("audio")
    process_events(qapp, lambda: home.card.isVisible(), 2)
    assert home.away() and home.card.isVisible()
    window.setctl.close_settings()   # onto a tab without it: it stays
    assert home.away()
    window.setctl.open_settings("audio")   # a kept Settings, opened again: still there
    process_events(qapp, lambda: home.card.isVisible(), 2)
    assert home.away() and home.card.isVisible()
    window.tabs.setCurrentWidget(window.setup_page)   # Setup shows: home
    process_events(qapp, lambda: not home.away(), 2)
    assert not home.away() and not home.card.isHidden()
