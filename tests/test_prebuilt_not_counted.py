"""Settings and Edit sound are built ahead at start (SettingsControl.preload_dialogs);
building them isn't using them, so it sends no usage count: only a real open does, once."""
from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401

from soundboard.core import usage


def _record(monkeypatch):
    said: list[str] = []
    monkeypatch.setattr(usage, "used", said.append)
    return said


def _counted(said, prefix):
    return [k for k in said if k.startswith(prefix)]


def test_made_ahead_counts_nothing(window, monkeypatch):  # noqa: F811
    said = _record(monkeypatch)
    window.setctl.preload_dialogs()
    QApplication.processEvents()
    assert window.setctl._settings_kept is not None and window.setctl._spare_editor is not None
    assert not _counted(said, "settings-page-")
    assert "edit-opened" not in said


def test_real_opens_count_once(window, monkeypatch):  # noqa: F811
    window.setctl.preload_dialogs()
    said = _record(monkeypatch)
    sid = window.cfg.sounds[0].id
    d = window.editctl.edit(sid)   # the one made ahead, now really opened
    assert said.count("edit-opened") == 1
    window.editctl.edit(sid)   # the same one raised again: not a second open
    assert said.count("edit-opened") == 1
    d.reject()

    window.setctl.open_settings("audio")
    assert _counted(said, "settings-page-") == ["settings-page-audio"]
    window.setctl._settings_dlg.show_page("hotkeys")   # another page: counted once
    assert _counted(said, "settings-page-") == ["settings-page-audio", "settings-page-hotkeys"]
    window.setctl.close_settings()
