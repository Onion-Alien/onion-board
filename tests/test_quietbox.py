"""No Windows ding from everyday message boxes (soundboard.ui.kit.quietbox)."""
import pytest
from PySide6.QtWidgets import QMessageBox

from soundboard.ui.kit import quietbox


@pytest.fixture
def quiet(qapp):
    from soundboard.ui.kit import wheelguard
    quietbox.install(qapp)
    yield
    wheelguard.AppStyle.hooks.remove(quietbox._polished)


@pytest.mark.parametrize("icon", [QMessageBox.Icon.Information, QMessageBox.Icon.Warning])
def test_info_and_warning_boxes_lose_the_sound_not_the_picture(quiet, icon):
    box = QMessageBox(icon, "Title", "Text")
    box.show()
    try:
        assert box.icon() == QMessageBox.Icon.NoIcon   # Qt plays nothing for NoIcon
        assert not box.iconPixmap().isNull()           # but the picture is still there
    finally:
        box.close()


def test_critical_keeps_its_sound(quiet):
    box = QMessageBox(QMessageBox.Icon.Critical, "Title", "Text")
    box.show()
    try:
        assert box.icon() == QMessageBox.Icon.Critical
    finally:
        box.close()



def test_question_boxes_get_the_app_icon_not_qts(quiet):
    """Qt's stock ? / ! bitmaps clashed with every theme: a question gets the app's
    painted badge too (and, like a note, no sound)."""
    box = QMessageBox(QMessageBox.Icon.Question, "Title", "Remove it?")
    box.show()
    try:
        assert box.icon() == QMessageBox.Icon.NoIcon
        assert not box.iconPixmap().isNull()
    finally:
        box.close()


def test_first_paragraph_becomes_the_heading(quiet):
    box = QMessageBox(QMessageBox.Icon.Question, "Remove sound",
                      "Remove “Boom”?\n\nRemoved sounds go to Recently deleted.")
    box.show()
    try:
        assert box.text() == "Remove “Boom”?"
        assert box.informativeText() == "Removed sounds go to Recently deleted."
    finally:
        box.close()


def test_rich_text_and_one_paragraph_boxes_keep_their_text(quiet):
    rich = QMessageBox(QMessageBox.Icon.Information, "T", "We brought <b>2</b>\n\nKeep?")
    one = QMessageBox(QMessageBox.Icon.Warning, "T", "It wasn't installed.")
    for box in (rich, one):
        box.show()
    try:
        assert rich.text() == "We brought <b>2</b>\n\nKeep?" and not rich.informativeText()
        assert one.text() == "It wasn't installed." and not one.informativeText()
    finally:
        rich.close()
        one.close()


def test_long_text_is_left_free_to_wrap(quiet):
    """A fixed minimum on a long line hid its width from QMessageBox, which then left
    it unwrapped (on a wide screen) and cut it off. Only short text gets the room."""
    from PySide6.QtWidgets import QLabel
    short = QMessageBox(QMessageBox.Icon.Question, "T", "Remove it?")
    long_ = QMessageBox(QMessageBox.Icon.Question, "T",
                        "Bulgarian isn't downloaded yet. Download and install it now? It's a "
                        "one-time 42 MB download, and Windows may ask to add its voice too.")
    for box in (short, long_):
        box.show()
    try:
        assert short.findChild(QLabel, "qt_msgbox_label").minimumWidth() == quietbox.TEXT_MIN
        label = long_.findChild(QLabel, "qt_msgbox_label")
        assert label.minimumWidth() == 0
        assert label.wordWrap() and label.height() >= label.heightForWidth(label.width())
    finally:
        short.close()
        long_.close()


def test_name_boxes_get_room_and_a_main_button(quiet):
    from PySide6.QtWidgets import QDialogButtonBox, QInputDialog
    dlg = QInputDialog()
    dlg.setLabelText("Name:")
    dlg.show()
    try:
        ok = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        assert ok.objectName() == "primary" and dlg.width() >= quietbox.INPUT_MIN
    finally:
        dlg.close()


# ---------------------------------------------------------------- the app's own cards
def test_ask_returns_the_button_clicked_and_esc_is_dismissed(qapp, monkeypatch):
    from conftest import answer_cards
    shown = answer_cards(monkeypatch, "Remove")
    assert quietbox.ask(None, "Remove sound", "Gone for 30 days.",
                        [("Remove", "danger"), ("Cancel", "")], default=1) == 0
    assert shown == [("Remove sound", ["Remove", "Cancel"])]
    answer_cards(monkeypatch)   # Esc, the ✕ or a click outside
    assert quietbox.ask(None, "Remove sound", "", [("Remove", "danger"),
                                                   ("Cancel", "")]) == quietbox.DISMISSED


def test_a_card_has_its_title_words_and_verb_buttons(qapp):
    box = quietbox.ModalCard("Remove sound", "Gone for 30 days.", icon="trash",
                             tone="danger_text")
    red = box.add_button("Remove", "danger")
    cancel = box.add_button("Cancel")
    box.set_default(cancel)
    assert box.heading.text() == "Remove sound" and box.body.text() == "Gone for 30 days."
    assert red.objectName() == "danger" and cancel.isDefault() and not red.isDefault()
    assert not box.close_btn.autoDefault()   # Enter never presses the ✕
    assert box.frame.mascot is not None      # the icon's badge, in the mascot's place
    box.deleteLater()


def test_get_text_gives_back_what_was_typed(qapp, monkeypatch):
    from PySide6.QtWidgets import QLineEdit

    def type_then_ok(box):
        box.findChild(QLineEdit).setText("Memes")
        box.buttons[0].click()
        return box.result()
    monkeypatch.setattr(quietbox.ModalCard, "exec", type_then_ok)
    assert quietbox.get_text(None, "New category", "Name:", ok="Add") == ("Memes", True)
    monkeypatch.setattr(quietbox.ModalCard, "exec", lambda box: box.reject() or 0)
    assert quietbox.get_text(None, "New category", "Name:") == ("", False)


def test_split_takes_the_question_as_the_heading():
    assert quietbox.split("Remove “Boom”?\n\nIt goes to Recently deleted.") == (
        "Remove “Boom”?", "It goes to Recently deleted.")
    assert quietbox.split("One line only.") == ("One line only.", "")
