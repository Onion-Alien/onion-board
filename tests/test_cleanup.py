"""The cleanup tool (soundboard/cleanup.py): it removes only Onion Board's own things,
keeps the user's sounds unless asked, and never drops the mic notes while the effect
is still on a mic."""
from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

if sys.platform == "win32":
    from soundboard import cleanup, directmic as dm, michelper


def _app(d):
    (d / "_internal").mkdir(parents=True)
    (d / "OnionBoard.exe").write_bytes(b"MZ")
    return d


def test_only_a_folder_with_the_app_counts(tmp_path):
    assert cleanup.is_app_dir(_app(tmp_path / "a" / "OnionBoard"))
    empty = tmp_path / "a" / "Other"
    empty.mkdir()
    assert not cleanup.is_app_dir(empty)
    assert not cleanup.is_app_dir(tmp_path / "missing")


def test_shortcuts_only_into_the_app_folder(tmp_path, monkeypatch):
    app = _app(tmp_path / "Programs" / "OnionBoard")
    desk = tmp_path / "Desktop"
    desk.mkdir()
    ours = desk / "Onion Board.lnk"
    ours.write_bytes(b"L\0\0\0" + (str(app) + "\\OnionBoard.exe").encode("utf-16-le"))
    theirs = desk / "Soundboard.lnk"   # another app's, same kind of name
    theirs.write_bytes(b"L\0\0\0" + r"C:\Games\Soundboard\Soundboard.exe".encode("utf-16-le"))
    monkeypatch.setattr(cleanup, "shortcut_dirs", lambda: [desk])
    assert cleanup.shortcuts([app]) == [ours]


def test_sounds_stay_unless_asked(tmp_path, monkeypatch):
    sounds = tmp_path / "Roaming" / "OnionBoard"
    sounds.mkdir(parents=True)
    monkeypatch.setattr(cleanup, "appdata_dir", lambda: sounds)
    monkeypatch.setattr(cleanup, "install_dirs", lambda hives=(): [])
    monkeypatch.setattr(cleanup, "_uninstall_entries", lambda hive: [])
    monkeypatch.setattr(cleanup, "run_values", lambda: [])
    monkeypatch.setattr(cleanup, "link_targets", lambda: [])
    monkeypatch.setattr(cleanup, "close_apps", lambda dirs: None)
    cleanup.user_part(remove_sounds=False)
    assert sounds.exists()
    cleanup.user_part(remove_sounds=True)
    assert not sounds.exists()


def _admin_fakes(monkeypatch, tmp_path, uninstall_code):
    deleted = []
    monkeypatch.setattr(dm, "_enable_privileges", lambda *a: None)
    monkeypatch.setattr(dm, "_admin_lock", lambda: 1)
    monkeypatch.setattr(dm, "_release", lambda h: None)
    monkeypatch.setattr(dm, "installed_on", lambda: ["{guid}"])
    monkeypatch.setattr(dm, "anything_installed", lambda: True)
    monkeypatch.setattr(dm, "admin_uninstall", lambda only=None: uninstall_code)
    monkeypatch.setattr(dm, "install_dir", lambda: tmp_path / "Onion Board Mic")
    monkeypatch.setattr(cleanup, "mics_with_effect", lambda: [])
    monkeypatch.setattr(cleanup, "install_dirs", lambda hives=(): [])
    monkeypatch.setattr(cleanup, "_uninstall_entries", lambda hive: [])
    monkeypatch.setattr(cleanup, "close_apps", lambda dirs: None)
    monkeypatch.setattr(cleanup, "programdata_dir", lambda: tmp_path / "ProgramData")
    monkeypatch.setattr(cleanup.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(michelper, "leftover", lambda: False)
    monkeypatch.setattr(michelper, "_helper_dirs", lambda: [])
    monkeypatch.setattr(cleanup, "_delete_tree", lambda hive, path, view=0: deleted.append(path))
    return deleted


def test_notes_kept_while_the_effect_is_still_on_a_mic(tmp_path, monkeypatch):
    deleted = _admin_fakes(monkeypatch, tmp_path, uninstall_code=6)   # audio wouldn't stop
    assert cleanup.admin_part() == 1
    assert cleanup.STATE_ROOT not in deleted   # a later run puts the mic back from them


def test_notes_go_once_the_effect_is_off(tmp_path, monkeypatch):
    deleted = _admin_fakes(monkeypatch, tmp_path, uninstall_code=0)
    assert cleanup.admin_part() == 0
    assert cleanup.STATE_ROOT in deleted


def test_dry_run_changes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(cleanup, "machine_items", lambda: ["The mic effect on: Mic"])
    monkeypatch.setattr(cleanup, "user_items", lambda remove_sounds: [])
    monkeypatch.setattr(cleanup, "setup_logging", lambda console: None)
    monkeypatch.setattr(cleanup, "admin_part", lambda: pytest.fail("changed something"))
    monkeypatch.setattr(cleanup, "user_part", lambda r: pytest.fail("changed something"))
    assert cleanup.main(["--dry-run"]) == 0
    assert "The mic effect on: Mic" in capsys.readouterr().out
