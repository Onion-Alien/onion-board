"""Settings at its narrowest: rows wrap instead of making a page wider than the window.
Checked by what can wrap, not in pixels: CI's fallback font is much wider than Windows'."""
import pytest
from PySide6.QtGui import QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QLabel, QPushButton, QWidget

from conftest import process_events
from soundboard.ui.kit.panel import Flow
from soundboard.ui.kit.wrapbutton import WrapButton, WrapCheck, WrapLabel, two_lines
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


def test_the_video_folder_wraps_at_its_slashes_and_copies_as_it_is(window, qapp):  # noqa: F811
    """A path has few spaces: its last piece ran past the card's edge at 440 px."""
    d = SettingsDialog(window, "data")
    label = d.data_folder
    path = r"C:\Some Folder\Videos\OnionBoardSavedVideos\ForEveryGameIPlay"
    label.set_path(path)
    assert label.toolTip() == path
    doc = QTextDocument()
    doc.setDefaultFont(label.font())
    doc.setDocumentMargin(0)
    doc.setPlainText(label.text())
    width = doc.idealWidth() // 3
    doc.setTextWidth(width)
    assert doc.idealWidth() <= width and doc.firstBlock().layout().lineCount() > 1
    label.setSelection(0, len(label.text()))
    QApplication.clipboard().setText(label.selectedText())   # what Ctrl+C or its menu copy
    QApplication.processEvents()
    assert QApplication.clipboard().text() == path
    d.close()


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


def test_the_audio_pages_long_parts_can_wrap(window, qapp):  # noqa: F811
    """Settings > Audio at 440 px: the big button on the mic card and its headline, Who's
    listening's and Voices' rows and a mic's pills ran past the window's edge (German
    worst). A page wider than the window also took the tab chips past it."""
    assert isinstance(window.btn_install, WrapButton) and isinstance(window.mic_line, WrapLabel)
    d = window.setctl.open_settings("audio")
    qapp.processEvents()
    d.audio_tabs.open_tab("listening")
    dest = next(c for c in d.findChildren(QWidget) if type(c).__name__ == "DestPanel")
    for box in (dest.chk_auto, dest.chk_mono, dest.chk_level, dest.chk_gate, dest.chk_discord):
        assert isinstance(box, WrapCheck)
    assert any(isinstance(lab, WrapLabel) for lab in dest.findChildren(QLabel))
    d.close()


def test_a_wrapping_label_asks_for_one_line_then_narrows(qapp):
    label = WrapLabel("A sentence long enough to go onto a second line")
    assert label.sizeHint().width() == label.fontMetrics().horizontalAdvance(label.text()) + 2
    assert label.minimumSizeHint().width() < label.sizeHint().width()
    assert label.heightForWidth(label.sizeHint().width() // 2) > label.sizeHint().height()


def test_a_mics_pills_go_under_its_name_when_narrow(qapp):
    from soundboard.ui.setup.audiorecovery import MicRow
    card = QWidget()
    card.confirm = lambda *a: None
    row = MicRow(card, {"name": "Microphone (a long device name, a long device name)",
                        "state": "none", "active": True}, "Microphone (a long device name, "
                 "a long device name)", True)
    assert any(f.indexOf(row.name) >= 0 and f.indexOf(row.in_use) >= 0
               for f in row.findChildren(Flow))
    card.deleteLater()


def test_a_search_leaves_no_hole_in_the_audio_pages_cards(window, qapp):  # noqa: F811
    """The first search on Settings > Audio: sizes kept from while a tab was hidden gave
    Who's listening about 200 px of nothing under its heading."""
    window.show()
    window.resize(1300, 850)
    d = window.setctl.open_settings("audio")
    QTest.qWait(50)
    d.search_box.setText("discord")
    QTest.qWait(500)   # (it waits for the typing to stop)
    tabs = d.audio_tabs
    card = tabs.pages[tabs.keys.index("listening")].findChild(QFrame, "setcard")
    assert card.isVisibleTo(d)
    heading = card.layout().itemAt(0)
    assert heading.geometry().height() <= heading.sizeHint().height()
    assert card.height() == card.sizeHint().height()
    d.close()


def test_speakers_rescan_sits_right_after_its_title(window, qapp):  # noqa: F811
    """On Settings' audio page as on the Setup tab: beside the heading, on one line, not
    alone at the far end of the card."""
    window.resize(1100, 800)
    window.show()
    d = window.setctl.open_settings("audio")
    qapp.processEvents()
    title = next(lb for lb in window.findChildren(QLabel)
                 if lb.text() == "Speakers and headphones" and lb.isVisibleTo(d))
    ref = next(b for b in title.parentWidget().findChildren(QPushButton)
               if b.accessibleName() == "Re-scan devices")
    process_events(qapp, lambda: title.width() > 0 and ref.x() > 0, 2)
    assert not title.wordWrap()
    assert 0 <= ref.x() - title.geometry().right() <= 16
