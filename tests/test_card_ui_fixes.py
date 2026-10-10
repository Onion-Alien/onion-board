"""Information and dialog actions align with their neighboring controls."""
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox

from soundboard.ui.deleted import DeletedDialog
from soundboard.ui.dialogs import TabHelpPopup
from test_mainwindow import window  # noqa: F401


def test_deleted_actions_share_one_row(qapp, app_dir):
    dialog = DeletedDialog("sound", "sounds", lambda _item: True)
    dialog.show()
    qapp.processEvents()
    close = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Close)
    centers = [w.mapTo(dialog, w.rect().center()).y()
               for w in (dialog.btn_back, dialog.btn_forget, close)]
    assert max(centers) - min(centers) <= 1
    dialog.close()
    dialog.deleteLater()


def test_information_button_is_on_the_rail_and_always_there(window, qapp):  # noqa: F811
    window.show()
    button = window.btn_info
    for page in (window.apps, window.triggers, window.sounds_page):
        window.tabs.setCurrentWidget(page)
        qapp.processEvents()
        assert button.isVisible() and window.rail.isAncestorOf(button)   # under the tabs


def test_help_cards_open_right_of_the_rail_inside_the_window(window, qapp, monkeypatch):  # noqa: F811
    # it used to line up its right edge with the ⓘ, so it hung off the window's left
    window.resize(1200, 800)
    window.show()
    qapp.processEvents()
    placed = []

    def inspect(box):
        placed.append((box.windowTitle(), box.geometry()))
        return 0

    monkeypatch.setattr(TabHelpPopup, "exec", inspect)
    window.btn_info.click()
    title, rect = placed[-1]
    assert title == "How Onion Board works"
    rail_right = window.rail.mapToGlobal(window.rail.rect().topRight()).x()
    assert rect.left() > rail_right and window.geometry().contains(rect.topLeft())


@pytest.mark.parametrize("page", ["radio_page", "triggers"])
def test_tab_help_is_a_dismissible_mascot_popup(window, qapp, monkeypatch, page):  # noqa: F811
    from soundboard.bunny import bunny_pixmap
    from soundboard.ui.owl import owl_image

    target = getattr(window, page)
    window.tab_info[page] = ("Tab help", "A plain explanation.")
    window.tabs.setTabEnabled(window.tabs.indexOf(target), True)
    window.tabs.setCurrentWidget(target)
    window.show()
    checked = []

    def inspect(box):
        assert box.windowType() == Qt.Popup
        assert box.heading.text() == "Tab help"
        assert box.body.text() == "A plain explanation."
        dpr = box.devicePixelRatioF()
        expected = (QPixmap.fromImage(owl_image(round(92 * dpr), look=0.0))
                    if page == "triggers" else bunny_pixmap(92, dpr=dpr))
        expected.setDevicePixelRatio(dpr)
        assert box.mascot.pixmap().toImage() == expected.toImage()
        checked.append(True)
        return 0

    monkeypatch.setattr(TabHelpPopup, "exec", inspect)
    window._show_tab_info(window.tabs.indexOf(target))
    assert checked == [True]


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
