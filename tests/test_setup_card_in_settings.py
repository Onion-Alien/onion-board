"""Setup's Send your sounds card shows at the top of Settings > Audio too: the same
card, moved there while that page shows and home to Setup otherwise."""
from conftest import process_events
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen
import pytest


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_settings_audio_borrows_the_setup_card_and_gives_it_back(window, qapp):
    home = window.how_home
    window.show()
    dlg = window.setctl.open_settings("audio")
    process_events(qapp, lambda: home.card.parentWidget() is not home, 2)
    assert home.card.parentWidget() is not home and home.card.isVisibleTo(dlg)
    dlg.show_page("hotkeys")   # another page: back on Setup
    assert home.card.parentWidget() is home
    dlg.show_page("audio")
    process_events(qapp, lambda: home.card.parentWidget() is not home, 2)
    assert home.card.parentWidget() is not home
    window.setctl.close_settings()
    assert home.card.parentWidget() is home and not home.card.isHidden()
    window.setctl.open_settings("audio")   # a kept Settings, opened again
    process_events(qapp, lambda: home.card.parentWidget() is not home, 2)
    assert home.card.parentWidget() is not home
    window.setctl.close_settings()
    assert home.card.parentWidget() is home
