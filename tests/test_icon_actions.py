"""U5: folder actions are one consistent, icon-only family (panel.icon_button).

Every plain "open this folder" action is a quiet icon-only button whose folder icon
is backed by a tooltip and a matching screen-reader name (DESIGN section 4), instead
of a word button here and an icon button there."""
from PySide6.QtWidgets import QPushButton

from soundboard.ui import panel
from soundboard.settings import SettingsDialog
from test_mainwindow import window  # noqa: F401 - the real window, offscreen


def _assert_icon_only_folder(btn: QPushButton):
    assert btn.text() == "", btn.text()               # icon only, no words
    assert btn.objectName() == "iconbutton"
    assert not btn.icon().isNull()                    # a folder is drawn
    assert btn.toolTip()                              # the words moved to the tooltip
    assert btn.accessibleName() == btn.toolTip()      # and name it for a screen reader
    assert btn.minimumSizeHint().height() >= 24       # not a smaller click target


def test_icon_button_is_a_named_icon_only_button(qapp):
    b = panel.icon_button("folder", "Open folder")
    assert b.property("quiet")
    _assert_icon_only_folder(b)


def test_settings_videos_folder_is_an_icon_button(window):  # noqa: F811
    dlg = SettingsDialog(window, "data")
    _vh, _change, show, _label = dlg._data_video_rows
    _assert_icon_only_folder(show)
    dlg.close()


def test_addons_folder_is_an_icon_button(qapp):
    from soundboard.ui.voicepanel import ModulesList
    listed = ModulesList()
    folder = [b for b in listed.findChildren(QPushButton)
              if b.objectName() == "iconbutton"]
    assert len(folder) == 1
    _assert_icon_only_folder(folder[0])
    listed.deleteLater()


def test_crash_report_folder_is_an_icon_button(qapp):
    from soundboard import applog
    from soundboard.ui import crashdialog
    dlg = crashdialog.CrashDialog(applog.Report(title="ValueError: x", text="BODY"), None)
    _assert_icon_only_folder(dlg.folder_btn)
    dlg.close()
