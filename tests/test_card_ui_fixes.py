"""Information and dialog actions align with their neighboring controls."""
from PySide6.QtWidgets import QDialogButtonBox

from soundboard.ui.deleted import DeletedDialog
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


def test_information_is_centered_on_tabs_and_scoped(window, qapp):  # noqa: F811
    window.show()
    window.tabs.setCurrentWidget(window.apps)
    qapp.processEvents()
    bar = window.tabs.tabBar()
    button = window.btn_info
    assert button.isVisible()
    assert abs(button.mapTo(window, button.rect().center()).y()
               - bar.mapTo(window, bar.rect().center()).y()) <= 2
    window.tab_info["triggers"] = ("Triggers", "Look for a picture")
    window.tabs.setCurrentWidget(window.triggers)
    qapp.processEvents()
    assert button.isVisible()
    window.tabs.setCurrentWidget(window.sounds_page)
    assert not button.isVisible()
