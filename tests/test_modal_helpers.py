"""The shared small modals (kit/modalframe.py): confirm, ask_text and notice, driven through
their real exec() with real key presses and clicks."""
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from soundboard.ui.kit import modalframe
from soundboard.ui.kit.modals import closes_on_click_outside


@pytest.fixture
def owner(qapp):
    w = QWidget()
    w.resize(900, 600)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    w.deleteLater()


def drive(monkeypatch, act):
    """Run `act(dlg)` once the helper's dialog is open; return what it saw."""
    seen = {}

    def opened(dlg):
        def go():
            seen["dlg"] = dlg
            seen["visible"] = dlg.isVisible()
            seen["focus"] = QApplication.focusWidget()
            act(dlg)
        QTimer.singleShot(120, go)
    monkeypatch.setattr(modalframe, "_opened", opened)
    return seen


@pytest.mark.parametrize("how, answer", [("verb", True), ("cancel", False), ("enter", False),
                                         ("escape", False), ("close", False)])
def test_confirm_answers_and_enter_is_the_safe_button(owner, monkeypatch, how, answer):
    def act(dlg):
        if how == "verb":
            QTest.mouseClick(dlg.yes_btn, Qt.MouseButton.LeftButton)
        elif how == "cancel":
            QTest.mouseClick(dlg.no_btn, Qt.MouseButton.LeftButton)
        elif how == "close":
            QTest.mouseClick(dlg.frame.close_btn, Qt.MouseButton.LeftButton)
        else:
            key = Qt.Key.Key_Return if how == "enter" else Qt.Key.Key_Escape
            QTest.keyClick(QApplication.focusWidget() or dlg, key)
    seen = drive(monkeypatch, act)
    got = modalframe.confirm(owner, "Delete the sound?", "It goes for good.", "Delete for good",
                             danger=True)
    assert got is answer
    dlg = seen["dlg"]
    assert seen["visible"] and seen["focus"] is dlg.no_btn
    assert dlg.yes_btn.objectName() == "danger" and dlg.no_btn.isDefault()
    assert dlg.yes_btn.text() == "Delete for good" and dlg.no_btn.text() == "Cancel"


def test_confirm_without_danger_fills_the_verb_and_stays_centred(owner, monkeypatch):
    def act(dlg):
        frame = dlg.frame.geometry().translated(dlg.pos())
        seen["middle"] = abs(frame.center().x() - owner.frameGeometry().center().x())
        dlg.reject()
    seen = drive(monkeypatch, act)
    assert not modalframe.confirm(owner, "Restart?", "Sounds stop for a moment.", "Restart")
    assert seen["dlg"].yes_btn.objectName() == "primary"
    assert seen["middle"] <= 2
    assert closes_on_click_outside(seen["dlg"])


def test_ask_text_saves_trimmed_text_and_cant_save_empty(owner, monkeypatch):
    def act(dlg):
        assert dlg.edit.selectedText() == "Old name"
        dlg.edit.clear()
        seen["empty_save"] = dlg.yes_btn.isEnabled()
        QTest.keyClick(dlg.edit, Qt.Key.Key_Return)   # nothing: it can't save empty
        seen["still_open"] = dlg.isVisible()
        QTest.keyClicks(dlg.edit, "  New name ")
        QTest.keyClick(dlg.edit, Qt.Key.Key_Return)
    seen = drive(monkeypatch, act)
    got = modalframe.ask_text(owner, "Rename the sound", "Name", "Old name", max_len=40,
                              hint="A short name")
    assert got == "New name"
    dlg = seen["dlg"]
    assert seen["focus"] is dlg.edit and not seen["empty_save"] and seen["still_open"]
    assert dlg.edit.maxLength() == 40 and dlg.edit.placeholderText() == "A short name"
    assert dlg.yes_btn.text() == "Save"
    assert not closes_on_click_outside(dlg)   # typed text isn't lost to a stray click


@pytest.mark.parametrize("how", ["cancel", "escape"])
def test_ask_text_cancel_is_none(owner, monkeypatch, how):
    def act(dlg):
        QTest.keyClicks(dlg.edit, "typed")
        if how == "cancel":
            QTest.mouseClick(dlg.no_btn, Qt.MouseButton.LeftButton)
        else:
            QTest.keyClick(dlg.edit, Qt.Key.Key_Escape)
    drive(monkeypatch, act)
    assert modalframe.ask_text(owner, "New category", "Name", verb="Add") is None


@pytest.mark.parametrize("kind, icon, tone", [("info", "info", "accent_text"),
                                              ("warning", "warn", "warn_text"),
                                              ("error", "alert", "error_text")])
def test_notice_shows_the_kinds_icon_and_one_button(owner, monkeypatch, kind, icon, tone):
    from soundboard.ui.kit import icons

    def act(dlg):
        QTest.keyClick(QApplication.focusWidget() or dlg, Qt.Key.Key_Return)
    seen = drive(monkeypatch, act)
    assert modalframe.notice(owner, "Couldn't save", "The disk is full.", kind=kind) is None
    dlg = seen["dlg"]
    assert seen["visible"] and seen["focus"] is dlg.yes_btn and dlg.yes_btn.text() == "Got it"
    assert icons._labels[dlg.frame.icon][:2] == (icon, tone)
    assert dlg.frame.mascot is None


def test_long_text_wraps_and_nothing_is_cut_off(owner, monkeypatch):
    """A long word-heavy text wraps inside the panel: every part fits in the frame."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QLabel, QPushButton

    bad = []

    def act(dlg):
        try:   # (an assert in here would leave the dialog open: collect, close, then check)
            frame = dlg.frame
            inside = frame.rect().adjusted(12, 12, -12, -12)
            for w in frame.findChildren(QLabel) + frame.findChildren(QPushButton):
                if w.isVisible():
                    r = QRect(w.mapTo(frame, QPoint(0, 0)), w.size())
                    if not inside.contains(r):
                        bad.append(("outside", w.text()[:20], r.getRect()))
                    if (isinstance(w, QLabel) and w.wordWrap()
                            and w.height() < w.heightForWidth(w.width()) - 1):
                        bad.append(("cut", w.text()[:20], w.height()))
        finally:
            dlg.reject()
    drive(monkeypatch, act)
    long = ("Donaudampfschifffahrtsgesellschaftskapitänsmütze " * 2
            + "Die Soundeinstellungen konnten nicht gespeichert werden, weil der "
              "Datenträger voll ist oder Onion Board keine Schreibrechte hat. " * 3)
    modalframe.confirm(owner, "Einstellungen zurücksetzen und alles neu einrichten?", long,
                       "Alles zurücksetzen", danger=True)
    assert not bad, bad


def test_parts_never_become_windows(qapp):
    """Nothing in a helper's dialog flashes up as a window of its own while it's built."""
    before = set(QApplication.topLevelWidgets())
    dlg = modalframe.ModalDialog(None, "Title", icon="warn", tone="warn")
    dlg.frame.add_text("Words")
    dlg.frame.add_button("Go", primary=True)
    assert set(QApplication.topLevelWidgets()) - before == {dlg}
    dlg.deleteLater()


def test_danger_verb_is_drawn_in_the_danger_colour(owner, monkeypatch):
    """The verb's danger look is on screen, not just its name (named after it was styled,
    it once stayed a plain grey button)."""
    from PySide6.QtGui import QColor
    from soundboard.ui.kit import theme

    def act(dlg):
        img = dlg.yes_btn.grab().toImage()
        seen["px"] = img.pixelColor(6, img.height() // 2)
        seen["empty_save_bg"] = None
        dlg.reject()
    seen = drive(monkeypatch, act)
    modalframe.confirm(owner, "Delete for good?", "It can't be brought back.", "Delete",
                       danger=True)
    want = QColor(theme.T["danger_bg"])
    px = seen["px"]
    assert max(abs(px.red() - want.red()), abs(px.green() - want.green()),
               abs(px.blue() - want.blue())) <= 12, (px.name(), want.name())


def test_confirm_keep_open_ignores_a_click_outside(owner, monkeypatch):
    def act(dlg):
        seen["closes"] = closes_on_click_outside(dlg)
        dlg.reject()
    seen = drive(monkeypatch, act)
    modalframe.confirm(owner, "Close Discord for a moment?", "Your call drops.", "Close it",
                       keep_open=True)
    assert seen["closes"] is False


@pytest.mark.parametrize("how, answer", [("pick", "Clean"), ("cancel", None),
                                         ("escape", None)])
def test_ask_choice_returns_the_picked_item(owner, monkeypatch, how, answer):
    def act(dlg):
        seen["start"] = dlg.combo.currentText()
        if how == "pick":
            dlg.combo.setCurrentIndex(2)
            QTest.keyClick(dlg.combo, Qt.Key.Key_Return)
        elif how == "cancel":
            QTest.mouseClick(dlg.no_btn, Qt.MouseButton.LeftButton)
        else:
            QTest.keyClick(dlg.combo, Qt.Key.Key_Escape)
    seen = drive(monkeypatch, act)
    got = modalframe.ask_choice(owner, "Copy a built-in mode", "Mode",
                                ["Game", "Voice chat", "Clean"], verb="Copy", current=1)
    assert got == answer
    dlg = seen["dlg"]
    assert seen["start"] == "Voice chat" and seen["focus"] is dlg.combo
    assert dlg.yes_btn.text() == "Copy" and dlg.yes_btn.isDefault()


def test_ask_choice_with_nothing_to_pick_is_none(owner, monkeypatch):
    def act(dlg):
        seen["can"] = dlg.yes_btn.isEnabled()
        QTest.keyClick(dlg.combo, Qt.Key.Key_Return)
        if dlg.isVisible():
            dlg.reject()
    seen = drive(monkeypatch, act)
    assert modalframe.ask_choice(owner, "Copy a mode", "Mode", []) is None
    assert seen["can"] is False


def test_empty_body_leaves_no_gap_and_a_picture_replaces_the_mascot(qapp):
    from PySide6.QtWidgets import QLabel
    frame = modalframe.ModalFrame("Close Discord for a moment?", mascot="bun")
    frame.add_button("Close it", primary=True)
    pic = QLabel("🎵")
    pic.setFixedSize(44, 44)
    frame.set_picture(pic)
    assert frame.mascot is None and frame.picture is pic and frame.lead == 44
    assert frame.header.indexOf(pic) == 0
    frame.show()
    qapp.processEvents()
    frame.resize(440, frame.heightForWidth(440))   # (as tall as its content, like a dialog)
    qapp.processEvents()
    head_bottom = max(w.geometry().bottom() for w in (frame.heading, pic))
    gap = frame._foot.geometry().top() - head_bottom
    assert gap <= 2, gap   # (the footer's own 20 px top margin is inside it)
    lbl = frame.add_text("Now with words")
    frame.hide()
    frame.show()
    qapp.processEvents()
    assert lbl.mapTo(frame, lbl.rect().topLeft()).x() == frame.heading.mapTo(
        frame, frame.heading.rect().topLeft()).x()
    frame.deleteLater()


def test_docked_frame_and_plain_rows_paint_no_band(qapp):
    """A docked frame has no edge; a "modalrow" QWidget and a slider in it are see-through
    (the app sheet gave every QWidget the window colour: a grey band on the panel)."""
    from PySide6.QtWidgets import QSlider, QWidget
    from soundboard.ui.kit import theme
    frame = modalframe.ModalFrame("Volume", mascot="", docked=True)
    row = QWidget()
    row.setObjectName("modalrow")
    row.setFixedHeight(30)
    frame.add_widget(row)
    slider = QSlider(Qt.Orientation.Horizontal)
    frame.add_widget(slider)
    frame.resize(440, 200)
    frame.show()
    qapp.processEvents()
    assert frame.property("docked") is True
    img = frame.grab().toImage()
    panel = QColor(theme.T["panel"])
    for w in (row, slider):
        p = w.mapTo(frame, w.rect().topLeft())
        px = img.pixelColor(p.x() + 2, p.y() + 2)
        assert max(abs(px.red() - panel.red()), abs(px.green() - panel.green()),
                   abs(px.blue() - panel.blue())) <= 14, (w.objectName(), px.name())
    frame.deleteLater()


def test_an_unanswered_box_fails_at_once_naming_it(owner):
    """conftest's guard: a helper nobody answered fails the test at once (it used to wait
    in exec() forever and take its xdist worker down)."""
    with pytest.raises(RuntimeError, match=r"modalframe\.confirm\('Delete for good\?'\)"):
        modalframe.confirm(owner, "Delete for good?", "Gone.", "Delete")
    with pytest.raises(RuntimeError, match=r"modal_answers"):
        modalframe.ask_text(owner, "Rename", "Name")


def test_modal_answers_answers_each_box_in_order(owner, modal_answers):
    modal_answers.add("confirm", True).add("confirm", False).add("ask_text", "  Boom ")
    modal_answers.add("ask_text", None).add("ask_choice", "Clean").add("notice")
    assert modalframe.confirm(owner, "Delete?", "Gone for good.", "Delete") is True
    assert modalframe.confirm(owner, "Restart?", "", "Restart") is False
    assert modalframe.ask_text(owner, "Rename", "Name", "Old") == "Boom"
    assert modalframe.ask_text(owner, "Rename", "Name", "Old") is None
    assert modalframe.ask_choice(owner, "Copy a mode", "Mode", ["Game", "Clean"]) == "Clean"
    assert modalframe.notice(owner, "Saved", "All done.") is None
    assert [k for k, _t, _w in modal_answers.seen] == ["confirm", "confirm", "ask_text",
                                                       "ask_text", "ask_choice", "notice"]
    assert modal_answers.seen[0] == ("confirm", "Delete?", "Gone for good.")
    with pytest.raises(RuntimeError, match="no answer left"):
        modalframe.notice(owner, "One more", "Nobody answers this.")


def test_a_long_button_row_widens_the_box_and_left_buttons_go_first(owner, modal_answers):
    """Four buttons (German is about 600 px) widen the box to fit, never past the screen;
    a left button sits before the gap."""
    from PySide6.QtCore import QPoint
    seen = {}

    def opened(dlg):
        def go():
            fr = dlg.frame
            seen["fits"] = all(
                b.mapTo(fr, QPoint(b.width(), 0)).x() <= fr.width() - 20
                and b.width() >= b.minimumSizeHint().width()
                for b in fr._foot.findChildren(QPushButton))
            seen["order"] = [fr.footer.itemAt(i).widget().text() if fr.footer.itemAt(i).widget()
                             else "|" for i in range(fr.footer.count())]
            seen["wide"] = dlg.width()
            dlg.reject()
        QTimer.singleShot(60, go)
    from PySide6.QtWidgets import QPushButton
    dlg = modalframe.ModalDialog(owner, "Ein Update ist da")
    dlg.frame.add_text("Version 9.9 ist fertig.")
    # (fits the 800 px offscreen screen even in the fallback font CI has; past the screen
    # it stops at the screen's width: test_a_box_never_grows_past_the_screen)
    for words, kw in (("Jetzt aktualisieren", {"primary": True}),
                      ("Diese Version überspringen", {}), ("Hinweise", {"left": True})):
        dlg.frame.add_button(words, **kw)
    opened(dlg)
    dlg.exec()
    cap = owner.screen().availableGeometry().width() - 24
    assert modalframe.DIALOG_W + 2 * modalframe.SHADOW < seen["wide"] <= cap
    # every button whole, unless the screen itself is too narrow (CI's fallback font draws
    # each letter as a wide box: there the row needs more than the 800 px offscreen screen)
    assert seen["fits"] or seen["wide"] == cap, seen
    assert seen["order"][0] == "Hinweise" and seen["order"][1] == "|"
    dlg.deleteLater()


def test_plain_rows_and_page_stacks_need_no_name(qapp):
    from PySide6.QtWidgets import QStackedWidget
    from soundboard.ui.kit import theme
    frame = modalframe.ModalFrame("Count me in", mascot="")
    row = QWidget()
    row.setFixedHeight(30)
    stack = QStackedWidget()
    stack.addWidget(QWidget())
    stack.setFixedHeight(30)
    for w in (row, stack):
        frame.body.addWidget(w)
    frame.add_button("Done", primary=True)
    frame.show()
    qapp.processEvents()
    frame.resize(440, frame.heightForWidth(440))
    qapp.processEvents()
    img = frame.grab().toImage()
    panel = QColor(theme.T["panel"])
    for w in (row, stack):
        p = w.mapTo(frame, w.rect().center())
        px = img.pixelColor(p.x(), p.y())
        assert max(abs(px.red() - panel.red()), abs(px.green() - panel.green()),
                   abs(px.blue() - panel.blue())) <= 14, (type(w).__name__, px.name())
    # the exact-class rule leaves the buttons their own fill
    btn = frame._foot.findChildren(modalframe.QPushButton)[0]
    c = btn.grab().toImage().pixelColor(4, btn.height() // 2)
    assert c != img.pixelColor(2, 2)
    frame.deleteLater()


def test_a_box_never_grows_past_the_screen(owner):
    dlg = modalframe.ModalDialog(owner, "Too many")
    for i in range(12):
        dlg.frame.add_button(f"A long button number {i}")
    seen = {}
    QTimer.singleShot(60, lambda: (seen.__setitem__("w", dlg.width()), dlg.reject()))
    dlg.exec()
    assert seen["w"] <= owner.screen().availableGeometry().width() - 24
    dlg.deleteLater()
