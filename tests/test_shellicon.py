"""The app icon outside its windows (Jump List, taskbar pin, Desktop / Start menu
shortcuts) follows the theme. Windows calls are faked: no real window property,
shortcut or icon cache is touched."""
import struct
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QImage

from soundboard import engine, shellicon, theme, winkeys
from soundboard.ui import mainwindow as main
from soundboard.ui import setupwizard


def test_ico_has_every_size_as_a_valid_png(qapp):
    data = shellicon.ico_bytes("#22c55e", "#0ea5e9")
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind, count) == (0, 1, len(shellicon.ICO_SIZES))
    for i, size in enumerate(shellicon.ICO_SIZES):
        w, h, _pal, _r, planes, bpp, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * i)
        assert (w or 256, h or 256, planes, bpp) == (size, size, 1, 32)
        png = data[offset:offset + length]
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        img = QImage.fromData(png, "PNG")
        assert (img.width(), img.height()) == (size, size)
    # the last entry ends the file: nothing missing, nothing extra
    assert offset + length == len(data)


def test_icon_file_is_named_by_its_picture(qapp, tmp_path):
    a = shellicon.write_icon("#22c55e", "#0ea5e9", tmp_path)
    again = shellicon.write_icon("#22c55e", "#0ea5e9", tmp_path)
    b = shellicon.write_icon("#7c5cff", "#ff4d8d", tmp_path)
    assert a == again and a != b   # a new look gets a new name: no stale icon cache
    assert a.read_bytes() == shellicon.ico_bytes("#22c55e", "#0ea5e9")
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([a.name, b.name])


@pytest.mark.windows   # Windows paths ignore case
def test_is_ours_matches_only_this_copy(tmp_path):
    exe = str(tmp_path / "OnionBoard" / "OnionBoard.exe")
    assert shellicon.is_ours(exe, "", frozen=True, exe=exe)
    assert shellicon.is_ours(exe.upper(), "--tray", frozen=True, exe=exe)
    assert not shellicon.is_ours(str(tmp_path / "Other.exe"), "", frozen=True, exe=exe)
    main_py = str(tmp_path / "code" / "main.py")
    py = str(tmp_path / "code" / ".venv" / "Scripts" / "pythonw.exe")
    assert shellicon.is_ours(py, f'"{main_py}"', frozen=False, main=main_py)
    assert shellicon.is_ours(py, f"{main_py} --tray", frozen=False, main=main_py)
    other = str(tmp_path / "elsewhere" / "main.py")
    assert not shellicon.is_ours(py, f'"{other}"', frozen=False, main=main_py)
    assert not shellicon.is_ours(str(tmp_path / "node.exe"), f'"{main_py}"',
                                 frozen=False, main=main_py)
    assert not shellicon.is_ours("", "", frozen=False, main=main_py)


class FakeLink:
    """Stands in for shellicon.ShellLink: a dict per .lnk path."""
    store: dict = {}

    def __init__(self, path: Path):
        if path not in self.store:
            raise OSError("not a shortcut")
        self.path = path
        self.closed = False

    def target(self):
        return self.store[self.path]["target"]

    def arguments(self):
        return self.store[self.path]["args"]

    def icon(self):
        return self.store[self.path]["icon"]

    def set_icon(self, path, index):
        if self.store[self.path].get("read_only"):
            raise OSError("access denied")
        self.store[self.path]["icon"] = (path, index)

    def close(self):
        self.closed = True


def test_only_the_apps_own_shortcuts_get_the_theme_icon(tmp_path, monkeypatch):
    monkeypatch.setattr(shellicon.sys, "frozen", True, raising=False)
    exe = tmp_path / "Programs" / "OnionBoard" / "OnionBoard.exe"
    monkeypatch.setattr(shellicon.sys, "executable", str(exe))
    old = (str(exe), 0)
    desk, start, pinned, public, other = (tmp_path / n for n in
                                          ("desk", "start", "pinned", "public", "other"))
    links = {
        desk / "Onion Board.lnk": dict(target=str(exe), args="", icon=old),
        start / "Onion Board.lnk": dict(target=str(exe), args="", icon=old),
        # same name, another program: left alone
        other / "Onion Board.lnk": dict(target=str(tmp_path / "x.exe"), args="", icon=old),
        # ours but Windows won't let us save it (all-users, no admin): skipped
        public / "Onion Board.lnk": dict(target=str(exe), args="", icon=old,
                                         read_only=True),
        # another shortcut of ours in the same folder, under another name: left alone
        desk / "Onion Board (old).lnk": dict(target=str(exe), args="", icon=old),
    }
    for p in links:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"lnk")
    (pinned / "Onion Board.lnk").parent.mkdir()
    (pinned / "Onion Board.lnk").write_bytes(b"not a shortcut")   # unreadable: skipped
    monkeypatch.setattr(FakeLink, "store", {k: dict(v) for k, v in links.items()})
    icon = tmp_path / "icons" / "onionboard-abc.ico"
    told = []
    changed = shellicon.update_shortcuts(icon, [desk, start, pinned, public, other],
                                         open_link=FakeLink, notify=told.extend)
    assert sorted(changed) == sorted([desk / "Onion Board.lnk", start / "Onion Board.lnk"])
    assert told == changed   # Explorer is told about exactly those
    s = FakeLink.store
    for p in changed:
        assert s[p]["icon"] == (str(icon), 0)
    for p in (other / "Onion Board.lnk", public / "Onion Board.lnk",
              desk / "Onion Board (old).lnk"):
        assert s[p]["icon"] == old
    # already right: nothing rewritten, nobody notified
    told.clear()
    assert shellicon.update_shortcuts(icon, [desk, start], open_link=FakeLink,
                                      notify=told.extend) == []
    assert told == []


def test_tests_never_see_the_real_shortcut_folders():
    assert shellicon.shortcut_folders() == []   # conftest's lock


@pytest.fixture
def win(qapp, app_dir, monkeypatch):
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    monkeypatch.setattr(setupwizard, "resume_after_restart", lambda on: None)
    w = main.MainWindow()
    w._load_thread.join(15)
    yield w
    w._quitting = True
    w.close()
    w._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_theme_change_refreshes_the_shell_icon(qapp, win, monkeypatch):
    calls = []
    monkeypatch.setattr(shellicon, "follow_theme",
                        lambda w, c1, c2: calls.append((w, c1, c2)))
    win.apply_theme("Mint")
    try:
        assert calls == [(win, theme.THEMES["Mint"]["accent"],
                          theme.THEMES["Mint"]["accent2"])]
        # the playing glow swaps the window icon often: that never rewrites files
        win._glow_icons(1.0, 1e9, force=True)
        assert len(calls) == 1
    finally:
        win.apply_theme("Dark")


def test_follow_theme_writes_the_icon_and_points_the_window_at_it(qapp, tmp_path,
                                                                  monkeypatch):
    """What happens on a real desktop, with the Windows calls faked."""
    monkeypatch.setattr(shellicon, "_native", lambda: True)
    monkeypatch.setattr(shellicon, "icon_dir", lambda: tmp_path)
    monkeypatch.setattr(shellicon, "_state", {"icon": None, "hwnd": None,
                                              "shortcuts_for": None})
    put, started = [], []
    monkeypatch.setattr(shellicon, "set_window", lambda h, icon: put.append((h, icon)) or True)
    monkeypatch.setattr(shellicon, "_shortcuts_worker", lambda: started.append(1))

    class Win:
        def windowHandle(self):
            return object()

        def winId(self):
            return 4242

    shellicon.follow_theme(Win(), "#22c55e", "#0ea5e9")
    icon = shellicon._state["icon"]
    assert icon is not None and icon.parent == tmp_path and icon.exists()
    assert put == [(4242, icon)]
    import time
    deadline = time.monotonic() + 5
    while not started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started == [1]
    # same colours again (a restart, the same theme picked): nothing redone
    shellicon.follow_theme(Win(), "#22c55e", "#0ea5e9")
    assert len(put) == 1
    shellicon.on_show(Win())   # same window handle: already set
    assert len(put) == 1
