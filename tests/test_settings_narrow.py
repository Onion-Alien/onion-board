"""Settings at its narrowest: rows wrap instead of making a page wider than the window.
Checked by what can wrap, not in pixels: CI's fallback font is much wider than Windows'."""
import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

from soundboard.ui.kit.panel import Flow
from soundboard.ui.kit.wrapbutton import WrapButton, WrapCheck, two_lines
from soundboard.ui.settings.settings import SettingsDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


@pytest.mark.parametrize("page, words", [("general", "Reset"), ("general", "Export everything"),
                                         ("connection", "Get Tor"), ("overlay", "Open overlay"),
                                         ("remote", "New key")])
def test_button_rows_wrap(window, page, words):  # noqa: F811
    d = SettingsDialog(window, page)
    button = next(b for b in d.findChildren(QPushButton) if b.text() == words)
    assert any(f.indexOf(button) >= 0 for f in d.findChildren(Flow))
    d.close()


def test_a_helper_programs_status_can_go_under_its_name(window):  # noqa: F811
    d = SettingsDialog(window, "updates")
    assert any(f.indexOf(d.ytdlp_state) >= 0 for f in d.findChildren(Flow))
    d.close()


def test_the_switch_and_add_a_device_can_go_onto_two_lines(window):  # noqa: F811
    for b in (window.seg_mic, window.seg_cable, window.seg_off):
        assert isinstance(b, WrapButton)
    assert window.seg_cable.minimumSizeHint().width() < window.seg_cable.sizeHint().width()
    assert window.route_switch.minimumSizeHint().width() < window.route_switch.sizeHint().width()


def test_a_long_tick_box_goes_onto_two_lines(qapp):
    box = WrapCheck("Offer to set up for new apps and more words")
    box.resize(box.minimumSizeHint().width(), 40)
    box.show()
    QApplication.processEvents()
    assert box.minimumSizeHint().width() < box.sizeHint().width()
    assert box.text() == "Offer to set up for new apps and more words"
    assert "\n" in QCheckBox.text(box)
    box.resize(box.sizeHint().width(), 40)
    QApplication.processEvents()
    assert "\n" not in QCheckBox.text(box)
    box.close()


def test_japanese_with_a_space_splits_evenly_and_keeps_latin_words_whole():
    first, second = two_lines("Twitch: チャンネルポイント、チャット").split("\n")
    assert first.startswith("Twitch:") and abs(len(first) - len(second)) <= 4


def test_the_mic_card_uses_the_pages_margins_only_while_visiting(window, qapp):  # noqa: F811
    card = window.how_home.card
    home = card.layout().contentsMargins()
    window.show()
    d = window.setctl.open_settings("audio")
    QApplication.processEvents()
    assert card.parentWidget() is not window.how_home
    assert card.layout().contentsMargins().left() == d.CARD_MARGINS[0]
    d.close()
    QApplication.processEvents()
    assert card.parentWidget() is window.how_home
    assert card.layout().contentsMargins() == home
