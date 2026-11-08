"""Information and dialog actions align with their neighboring controls."""
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest

from soundboard.ui.sounds.deleted import DeletedDialog
from soundboard.ui.sounds.dialogs import TabHelpPopup
from test_mainwindow import window  # noqa: F401


def test_deleted_actions_share_one_row(qapp, app_dir):
    dialog = DeletedDialog("sound", "sounds", lambda _item: True)
    dialog.show()
    qapp.processEvents()
    centers = [w.mapTo(dialog, w.rect().center()).y()
               for w in (dialog.btn_back, dialog.btn_forget, dialog.btn_close)]
    assert max(centers) - min(centers) <= 1
    # the one that can't be undone stands apart on the left; Bring back, then Close
    assert dialog.btn_forget.x() < dialog.btn_back.x() < dialog.btn_close.x()
    assert dialog.btn_back.objectName() == "primary"
    assert dialog.btn_forget.objectName() == "danger"
    dialog.close()
    dialog.deleteLater()


def test_help_cards_open_right_of_the_rail_inside_the_window(window, qapp, monkeypatch):  # noqa: F811
    # it used to line up its right edge with the ⓘ, so it hung off the window's left
    window.rail.set_open(False)   # the offscreen screen is small: room for it beside
    window.resize(1200, 800)
    window.show()
    qapp.processEvents()
    placed = []

    def inspect(box):
        placed.append((box.windowTitle(), box.geometry()))
        return 0

    monkeypatch.setattr(TabHelpPopup, "exec", inspect)
    window.tipctl._show_tab_info(window.tabs.indexOf(window.sounds_page))
    title, rect = placed[-1]
    assert title == "Your sounds"
    rail_right = window.rail.mapToGlobal(window.rail.rect().topRight()).x()
    assert rect.left() > rail_right and window.geometry().contains(rect.topLeft())


@pytest.mark.parametrize("page", ["radio_page", "triggers"])
def test_tab_help_is_a_dismissible_mascot_popup(window, qapp, monkeypatch, page):  # noqa: F811
    from soundboard.ui.kit.modalframe import MASCOT, mascot_pixmap
    from soundboard.ui.sounds.tabhelp import tab_card

    target = getattr(window, page)
    window.tab_info[page] = ("Tab help", "A plain explanation.")
    window.tabs.setTabEnabled(window.tabs.indexOf(target), True)
    window.tabs.setCurrentWidget(target)
    window.show()
    checked = []
    key = "triggers" if page == "triggers" else "radio"

    def inspect(box):
        assert box.windowType() == Qt.Popup
        assert box.heading.text() == "Tab help"
        # the tab's own card: a subtitle and short points, not the paragraph
        subtitle, points = tab_card(key)
        assert box.subtitle.text() == subtitle and box.body.isHidden()
        assert [p.title.text() for p in box.points] == [t for _i, t, _x in points]
        dpr = box.devicePixelRatioF()
        expected = mascot_pixmap("owl" if page == "triggers" else "bun", MASCOT, dpr)
        assert box.mascot.pixmap().toImage() == expected.toImage()
        checked.append(True)
        return 0

    monkeypatch.setattr(TabHelpPopup, "exec", inspect)
    window.tipctl._show_tab_info(window.tabs.indexOf(target))
    assert checked == [True]


def test_every_tab_card_has_a_few_points_with_real_icons(qapp):
    from soundboard.ui.kit.iconshapes import SHAPES
    from soundboard.ui.sounds.tabhelp import tab_card
    from soundboard.ui.window.tabcontrol import TAB_KEYS

    for key in TAB_KEYS:
        subtitle, points = tab_card(key)
        assert subtitle and 2 <= len(points) <= 4, key
        assert all(icon in SHAPES and title for icon, title, _text in points), key


def test_help_card_has_room_and_one_main_button(qapp):
    """Nothing touches the panel's edge, Got it is its one filled button and closes it."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QPushButton
    popup = TabHelpPopup("Radio", key="radio")
    popup.show()
    qapp.processEvents()
    frame = popup.frame
    inside = frame.rect().adjusted(12, 12, -12, -12)
    for w in frame.findChildren(QPushButton) + popup.points + [popup.heading, popup.mascot]:
        r = QRect(w.mapTo(frame, QPoint(0, 0)), w.size())
        assert inside.contains(r), (w.objectName(), r.getRect())
    filled = [b for b in frame.findChildren(QPushButton) if b.objectName() == "primary"]
    assert filled == [popup.ok_btn] and popup.ok_btn.text() == "Got it"
    assert popup.ok_btn.hasFocus()
    popup.ok_btn.click()
    qapp.processEvents()
    assert not popup.isVisible() and popup.result() == 1
    popup.deleteLater()


@pytest.mark.parametrize("dismiss", ["outside", "escape"])
def test_help_card_dismisses_without_a_button(qapp, dismiss):
    popup = TabHelpPopup("Radio", "Choose a station and listen.")
    timed_out = []
    timer = QTimer()
    timer.setSingleShot(True)

    def timeout():
        timed_out.append(True)
        popup.reject()

    timer.timeout.connect(timeout)
    timer.start(1000)

    def dismiss_popup():
        if dismiss == "outside":
            QTest.mouseClick(popup, Qt.LeftButton, pos=QPoint(-10, -10))
        else:
            QTest.keyClick(popup, Qt.Key_Escape)

    QTimer.singleShot(50, dismiss_popup)
    popup.exec()
    timer.stop()
    assert not timed_out
    assert not popup.isVisible()
    popup.deleteLater()


def test_help_card_uses_shared_styles_and_returns_focus(qapp):
    """The help card's look comes from the style sheet (no local pixel sizes or
    colours), its close is a painted icon with a name, and the focus goes back."""
    from PySide6.QtWidgets import QPushButton, QWidget
    opener_host = QWidget()
    opener = QPushButton("About", opener_host)
    opener_host.show()
    opener.setFocus()
    qapp.processEvents()
    popup = TabHelpPopup("Radio", "Choose a station and listen.")
    assert popup.styleSheet() == ""
    assert all(not w.styleSheet() for w in popup.findChildren(QWidget))
    assert popup.heading.objectName() == "helptitle"
    assert popup.body.objectName() == "helpbody"
    b = popup.close_btn
    assert b.text() == "" and not b.icon().isNull()
    assert b.accessibleName() == b.toolTip() == "Close"
    popup.show()
    qapp.processEvents()
    popup.reject()
    qapp.processEvents()
    assert opener.hasFocus() or qapp.focusWidget() is opener
    popup.deleteLater()
    opener_host.deleteLater()


def test_help_card_stays_open_until_closed(qapp):
    """A part shown before it had a parent became a window of its own for a moment, and
    that closed the pop-up as soon as it opened."""
    from PySide6.QtWidgets import QApplication, QDialog
    before = set(QApplication.topLevelWidgets())
    popup = TabHelpPopup("Radio", key="radio")
    assert set(QApplication.topLevelWidgets()) - before == {popup}
    seen = []

    def look():
        seen.append(popup.isVisible() and popup.ok_btn.hasFocus())
        popup.ok_btn.click()

    QTimer.singleShot(150, look)
    assert QDialog.exec(popup) == 1
    assert seen == [True]
    popup.deleteLater()


def test_every_live_controls_popup_gets_the_themes_background(window, qapp):  # noqa: F811
    """The radio's came up in Qt's plain light grey under the theme's light words: its
    own background rule hadn't taken, so nothing on it could be read in a dark theme."""
    window.resize(1200, 800)
    window.show()
    qapp.processEvents()
    for b in (window.speed_btn, window.radio.fx_btn, window.apps.fx_btn):
        b._open()
        qapp.processEvents()
        assert b.pop.testAttribute(Qt.WidgetAttribute.WA_StyledBackground), b
        b.pop.hide()
