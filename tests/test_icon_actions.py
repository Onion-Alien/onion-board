"""Folder actions are one consistent, icon-only family (panel.icon_button).

Every plain "open this folder" action is a quiet icon-only button whose folder icon
is backed by a screen-reader name (DESIGN section 4), instead of a word button here
and an icon button there. No tooltip that only says "Open folder": the picture says
it; one that adds something (the crash report's) leads with the name."""
from PySide6.QtWidgets import QLabel, QPushButton

from soundboard.ui.kit import panel
from soundboard.ui.settings.settings import SettingsDialog
from test_mainwindow import window  # noqa: F401 - the real window, offscreen


def _assert_icon_only_folder(btn: QPushButton, more: bool = False):
    assert btn.text() == "", btn.text()               # icon only, no words
    assert btn.objectName() == "iconbutton"
    assert not btn.icon().isNull()                    # a folder is drawn
    assert btn.accessibleName() == "Open folder"      # a screen reader hears what it does
    if more:   # a tooltip only to say more, leading with the name
        assert btn.toolTip().startswith(btn.accessibleName() + "\n")
    else:
        assert btn.toolTip() == ""
    assert btn.minimumSizeHint().height() >= 24       # not a smaller click target


def test_icon_button_is_a_named_icon_only_button(qapp):
    b = panel.icon_button("folder", "Open folder", hover=False)
    assert b.property("quiet")
    _assert_icon_only_folder(b)
    b = panel.icon_button("info", "What do these do?")   # a picture that needs words
    assert b.toolTip() == b.accessibleName() == "What do these do?"


def test_settings_videos_folder_is_an_icon_button(window):  # noqa: F811
    dlg = SettingsDialog(window, "data")
    _vh, _change, show, _label = dlg._data_video_rows
    _assert_icon_only_folder(show)
    dlg.close()


def test_addons_folder_is_an_icon_button(qapp):
    from soundboard.ui.voice.voicepanel import ModulesList
    listed = ModulesList()
    folder = [b for b in listed.findChildren(QPushButton)
              if b.objectName() == "iconbutton"]
    assert len(folder) == 1
    _assert_icon_only_folder(folder[0])
    listed.deleteLater()


def test_crash_report_folder_is_an_icon_button(qapp):
    from soundboard.core import applog
    from soundboard.ui.kit import crashdialog
    dlg = crashdialog.CrashDialog(applog.Report(title="ValueError: x", text="BODY"), None)
    _assert_icon_only_folder(dlg.folder_btn, more=True)
    dlg.close()


def _assert_reset(btn: QPushButton):
    """The reset family: the same small quiet "Reset" with the reset arrow everywhere
    (it was "Reset" as a link, "Reset" as a button and "Reset all")."""
    assert btn.text() == "Reset"
    assert btn.objectName() == "reset"
    assert not btn.icon().isNull()
    assert btn.toolTip() or btn.accessibleName()     # says what goes back


def test_resets_are_one_family(window):  # noqa: F811
    from soundboard.ui.voice.voicepanel import EffectRow
    _assert_reset(panel.reset_button("Back to how it was"))
    pop = window.speed_btn.pop
    resets = [b for b in pop.findChildren(QPushButton) if b.text() == "Reset"]
    assert len(resets) == 1
    # Live controls has a larger Reset target than the inline effect links.
    live_reset = resets[0]
    assert live_reset.objectName() == "liveReset"
    assert live_reset.minimumWidth() >= 96 and live_reset.minimumHeight() >= 36
    assert not live_reset.icon().isNull()
    assert live_reset.toolTip()
    rows = window.voice.fx.findChildren(EffectRow) or window.voice.findChildren(EffectRow)
    assert rows
    _assert_reset(rows[0].btn_reset)
    from soundboard.ui.sounds.dialogs import EditDialog
    d = EditDialog(window.meta("s1"), window.hotkeys, window.playctl.preview, window,
                   advanced=True)
    resets = [b for b in d.findChildren(QPushButton) if b.text() == "Reset"]
    assert resets
    _assert_reset(resets[0])
    assert any(b.text() == "Save a copy" for b in d.findChildren(QPushButton))
    d.reject()


def test_sound_modes_help_is_an_info_icon(window, qapp):  # noqa: F811
    from PySide6.QtTest import QTest
    window.show()
    window.tabs.setCurrentWidget(window.setup_page)
    QTest.qWait(100)
    b = window.dest_panel.help_btn
    assert b.text() == "" and b.objectName() == "infobutton" and not b.icon().isNull()
    assert b.toolTip() == b.accessibleName() == "What do these do?"
    assert b.width() >= 24 and b.height() >= 24        # not a smaller click target
    # beside the card's heading, on its line (DESIGN section 4)
    heading = next(lbl for lbl in b.parentWidget().findChildren(QLabel)
                   if lbl.objectName() == "section")
    assert heading.text() == "Who's listening"
    fm = heading.fontMetrics()           # centred on the heading's cap height (heading_row)
    cap_centre = heading.geometry().top() + fm.ascent() - (fm.capHeight() + 1) / 2
    assert abs(b.geometry().center().y() - cap_centre) <= 1.5


def test_sound_modes_have_their_pictures(window):  # noqa: F811
    """Game, Voice chat, Clean and Advanced show the sidebar mode button's pictures."""
    for b in window.dest_panel.buttons.values():
        assert not b.icon().isNull() and b.text()
