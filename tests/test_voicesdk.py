"""Voice engine detection (soundboard.voicesdk): made-up install folders, no real
games or processes."""
import threading
from pathlib import Path

from soundboard import voicesdk


def _touch(root: Path, *rel: str) -> None:
    for r in rel:
        p = root / r
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")


def test_unreal_game_with_vivox_next_to_its_exe(tmp_path):
    exe = "live/Game/Binaries/Win64/Game-Win64-Shipping.exe"
    _touch(tmp_path, exe, "live/Game/Binaries/Win64/vivoxsdk.dll")
    assert voicesdk.install_root(tmp_path / exe) == tmp_path / "live"
    assert voicesdk.scan(tmp_path / exe) == "game"


def test_vivox_deep_in_an_unreal_plugin(tmp_path):
    exe = "Shooter/Shooter/Binaries/Win64/Shooter-Win64-Shipping.exe"
    _touch(tmp_path, exe, "Shooter/Shooter/Plugins/Online/VivoxCore/Source/ThirdParty/"
                          "VivoxCoreLibrary/Windows/Release/x64/VivoxSDK.dll",
           "Shooter/Engine/Binaries/Win64/EOSSDK-Win64-Shipping.dll")
    assert voicesdk.scan(tmp_path / exe) == "game"


def test_eos_alone_is_not_a_voice_engine(tmp_path):
    # single-player games ship EOSSDK for accounts and achievements
    exe = "Solo/Solo/Binaries/Win64/Solo-Win64-Shipping.exe"
    _touch(tmp_path, exe, "Solo/Solo/Binaries/Win64/EOSSDK-Win64-Shipping.dll",
           "Solo/Engine/Binaries/ThirdParty/Steamworks/Win64/steam_api64.dll")
    assert voicesdk.scan(tmp_path / exe) is None


def test_unity_voice_engines(tmp_path):
    for name, lib in (("Ghosts", "Ghosts_Data/Plugins/x86_64/opus_egpv.dll"),
                      ("Hunt", "Hunt_Data/Managed/PhotonVoice.API.dll"),
                      ("Moon", "Moon_Data/Managed/DissonanceVoip.dll")):
        _touch(tmp_path / name, f"{name}.exe", lib, f"{name}_Data/Managed/Assembly-CSharp.dll")
        assert voicesdk.scan(tmp_path / name / f"{name}.exe") == "unity", name


def test_vivox_wins_over_unity_voice():
    assert voicesdk.engine_of_files({"opus_egpv.dll", "vivoxsdk.dll"}) == "game"
    assert voicesdk.engine_of_files({"photonvoice.txt"}) is None


def test_scan_skips_data_folders_and_stops_at_its_limit(tmp_path):
    _touch(tmp_path, "G/G.exe", "G/Content/vivoxsdk.dll")
    assert voicesdk.scan(tmp_path / "G" / "G.exe") is None
    _touch(tmp_path, "H/H.exe", *(f"H/a{i:02d}.txt" for i in range(50)), "H/z/vivoxsdk.dll")
    assert voicesdk.scan(tmp_path / "H" / "H.exe", max_entries=10) is None
    assert voicesdk.scan(tmp_path / "missing" / "x.exe") is None


def _join_scans():
    for t in threading.enumerate():
        if t.name == "voicesdk-scan":
            t.join(5)


class _Fg:
    def __init__(self):
        self.now = (0, "")

    def __call__(self):
        return self.now


def _watcher(engines, alive):
    fg = _Fg()
    w = voicesdk.Watcher(fg, lambda p: engines.get(p), lambda pid: pid in alive)

    def poll():
        w.poll()
        _join_scans()
        return w.poll()
    return w, fg, poll


def test_watcher_suggests_the_game_you_just_left_while_it_runs():
    alive = {10, 20}
    w, fg, poll = _watcher({"C:/Games/V/v.exe": "game", "C:/Apps/browser.exe": None}, alive)
    assert poll() is None
    fg.now = (10, "C:/Games/V/v.exe")
    assert poll() == "game"
    fg.now = (0, "")                     # this app in front (or nothing)
    assert poll() == "game"
    fg.now = (20, "C:/Apps/browser.exe")  # another program: no longer that game
    assert poll() is None
    fg.now = (10, "C:/Games/V/v.exe")
    assert poll() == "game"
    alive.discard(10)                    # the game closed
    fg.now = (0, "")
    assert poll() is None


def test_watcher_scans_each_exe_once():
    calls = []
    fg = _Fg()
    w = voicesdk.Watcher(fg, lambda p: calls.append(p) or "unity", lambda pid: True)
    fg.now = (5, "C:/Games/U/u.exe")
    for _ in range(4):
        w.poll()
        _join_scans()
    assert calls == ["C:/Games/U/u.exe"] and w.suggestion == "unity"


def test_is_system_never_touches_the_disk(monkeypatch):
    """It runs on the UI thread every few seconds: resolving the game's exe on a
    sleeping drive froze the window for 6 s."""
    import os

    def boom(*a, **k):
        raise AssertionError("disk access on the UI thread")

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(os.path, "realpath", boom)
    monkeypatch.setattr(Path, "resolve", boom)
    assert voicesdk._is_system(r"C:\Windows\explorer.exe")
    assert voicesdk._is_system(r"c:\windows\System32\dwm.exe")
    assert not voicesdk._is_system(r"C:\WindowsApps\game.exe")
    assert not voicesdk._is_system(r"E:\Games\Shooter\shooter.exe")
    assert not voicesdk._is_system("")


def test_listeners_name_voice_apps_first_and_scan_each_game_once():
    from soundboard.appaudio import App
    apps = [App(1, "game.exe", r"C:\Games\Thing\game.exe", active=True),
            App(2, "Discord.exe", r"C:\Apps\Discord\Discord.exe", active=True),
            App(3, "obs64.exe", r"C:\Apps\obs\obs64.exe", active=True)]
    scans = []

    def scanner(path):
        scans.append(path)
        return "game" if "Thing" in path else None

    lis = voicesdk.Listeners(lister=lambda device: apps, scanner=scanner)
    assert lis.look("CABLE Output") == (("discord", "Discord"), ("game", "Game"))
    assert lis.look("CABLE Output") == (("discord", "Discord"), ("game", "Game"))
    assert sorted(scans) == [r"C:\Apps\obs\obs64.exe", r"C:\Games\Thing\game.exe"]
    assert lis.poll(None) == ()                    # no cable: nobody to name
