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
    shown = answer_cards(monkeypatch, "Just the sounds")
    assert quietbox.ask(None, "Import backup", "It has settings too.",
                        [("Sounds and settings", "primary"), ("Just the sounds", ""),
                         ("Cancel", "")]) == 1
    assert shown == [("Import backup", ["Sounds and settings", "Just the sounds", "Cancel"])]
    answer_cards(monkeypatch)   # Esc, the ✕ or a click outside
    assert quietbox.ask(None, "Import backup", "", [("Sounds and settings", "primary"),
                                                    ("Cancel", "")]) == quietbox.DISMISSED


def test_a_card_is_the_shared_frame_with_verb_buttons(qapp):
    from soundboard.ui.kit import modalframe
    box = quietbox.ModalCard("Update available", "Faster loading.", subtitle="9.9.0 is out",
                             icon="download")
    go = box.add_button("Update now", "primary")
    later = box.add_button("Later")
    page = box.add_button("Release page", left=True)
    box.set_default(go)
    assert isinstance(box, modalframe.ModalDialog) and box.frame.icon is not None
    assert box.heading.text() == "Update available" and box.body.text() == "Faster loading."
    assert box.subtitle.text() == "9.9.0 is out" and not box.subtitle.isHidden()
    assert go.objectName() == "primary" and go.isDefault() and not later.isDefault()
    assert not box.close_btn.autoDefault()   # Enter never presses the ✕
    foot = box.frame.footer
    order = [foot.itemAt(i).widget() for i in range(foot.count())]
    assert order.index(page) < order.index(go) < order.index(later)   # Release page left
    box.deleteLater()


def test_a_card_widens_to_fit_its_buttons(qapp):
    box = quietbox.ModalCard("Update", "x", width=120)   # (narrower than its row)
    for words in ("Download page", "Install log", "Later"):
        box.add_button(words)
    box.show()
    qapp.processEvents()
    assert all(b.width() >= b.minimumSizeHint().width() for b in box.buttons)
    box.close()
    box.deleteLater()


def test_split_takes_the_question_as_the_heading():
    assert quietbox.split("Remove “Boom”?\n\nIt goes to Recently deleted.") == (
        "Remove “Boom”?", "It goes to Recently deleted.")
    assert quietbox.split("One line only.") == ("One line only.", "")
