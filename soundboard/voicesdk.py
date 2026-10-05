"""Which voice chat engine the game you're playing uses, from the files it ships.

A voice SDK comes as its own library in the game's install folder, so the game in
the foreground can be matched to a *Who's listening* mode without touching the
game itself: its .exe path is read with the least access Windows has (the same
query Task Manager makes, which anti-cheat allows), and its install folder is
listed. Nothing is injected, no memory is read, no module list is taken.

    vivoxsdk.dll                      Vivox          (every game shipping it uses it
                                                      for voice; checked on five installs)
    opus_egpv.dll, PhotonVoice*.dll   Photon Voice   (its native Opus build / managed code)
    DissonanceVoip.dll,
    AudioPluginDissonance.dll         Dissonance

Not detectable, so never suggested: Epic Online Services (EOSSDK ships in games that
only use it for accounts or achievements, single-player ones included), Steam voice
(steam_api is in nearly every Steam game), Unreal's built-in voice and Discord.

Better than the game in front: the program actually recording the virtual cable's
far end (Listeners). Windows lists who records a device the same way it lists who
plays (soundboard.appaudio.recording_apps), so a voice chat app is named by its exe
(VOICE_APPS) and a game by the files in its folder, as above.

The result is a suggestion by the picker, and the mode is switched for you only
when *Pick the mode by itself* is ticked there (`dest["auto"]`).
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

# file name (lower case) -> destination mode key
SIGNATURES = {
    "vivoxsdk.dll": "game",
    "opus_egpv.dll": "unity",
    "dissonancevoip.dll": "unity",
    "audioplugindissonance.dll": "unity",
}
PREFIXES = {"photonvoice": "unity"}   # PhotonVoice.dll, PhotonVoice.API.dll, …
# which wins when a game ships more than one (an Unreal game can carry a Vivox plugin
# next to Photon's): the one found first in this order
ORDER = ("game", "unity")
NAMES = {"game": "Vivox", "unity": "Photon or Dissonance"}   # for the hint
# voice chat programs that record the cable, by exe: (mode key, name for the hint).
# TeamSpeak and Mumble sit with Vivox's mode (Opus mono, a high-pass ~80 Hz: see
# destination.BUILTIN). A browser recording the cable is a call in a web page (Meet,
# Discord in a browser): the browser mode, which Zoom and Teams share (on the bench it
# gets them their level back; their AI noise suppression is what hurts, and no mode
# fixes that: docs/GAME-VOICE.md).
VOICE_APPS = {
    "chrome.exe": ("webrtc", "Your browser"),
    "msedge.exe": ("webrtc", "Your browser"),
    "firefox.exe": ("webrtc", "Your browser"),
    "brave.exe": ("webrtc", "Your browser"),
    "opera.exe": ("webrtc", "Your browser"),
    "opera_gx.exe": ("webrtc", "Your browser"),
    "vivaldi.exe": ("webrtc", "Your browser"),
    "zoom.exe": ("webrtc", "Zoom"),
    "ms-teams.exe": ("webrtc", "Microsoft Teams"),
    "teams.exe": ("webrtc", "Microsoft Teams"),
    "discord.exe": ("discord", "Discord"),
    "discordptb.exe": ("discord", "Discord"),
    "discordcanary.exe": ("discord", "Discord"),
    "ts3client_win64.exe": ("game", "TeamSpeak"),
    "ts3client_win32.exe": ("game", "TeamSpeak"),
    "teamspeak.exe": ("game", "TeamSpeak"),
    "mumble.exe": ("game", "Mumble"),
}
# folders that hold game data, never a voice library: not worth listing on a slow disk
SKIP_DIRS = {"content", "paks", "movies", "videos", "streamingassets", "localization",
             "logs", "saved", "shadercache", "screenshots", "__pycache__", ".git"}
MAX_DEPTH = 12        # an Unreal plugin keeps its library ~10 folders below the game
MAX_ENTRIES = 20000   # most a scan lists, so a stray exe in a huge folder stays cheap


def install_root(exe: str | Path) -> Path:
    """The folder a game is installed in. An Unreal game's exe sits in
    <Project>/Binaries/Win64, three levels under it; anything else next to its exe."""
    d = Path(exe).parent
    if d.name.lower() == "win64" and d.parent.name.lower() == "binaries" \
            and len(d.parents) > 3:
        return d.parents[2]
    return d


def engine_of_files(names) -> str | None:
    """The mode key for a set of (lower-case) file names, or None."""
    found = set()
    for n in names:
        key = SIGNATURES.get(n) or next((k for p, k in PREFIXES.items()
                                         if n.startswith(p) and n.endswith(".dll")), None)
        if key:
            found.add(key)
    return next((k for k in ORDER if k in found), None)


def _system_dir() -> Path | None:
    win = os.environ.get("SystemRoot") or os.environ.get("windir")
    return Path(win).resolve() if win else None


def scan(exe: str | Path, max_entries: int = MAX_ENTRIES) -> str | None:
    """The voice engine the game at `exe` ships (a mode key), or None. Lists its
    install folder (MAX_DEPTH deep, at most max_entries entries); never raises."""
    try:
        root = install_root(exe)
        sysdir = _system_dir()
        if len(root.parts) < 2 or (sysdir and (root == sysdir or sysdir in root.parents)):
            return None
        names: set[str] = set()
        stack, seen = [(root, 0)], 0
        while stack:
            d, depth = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        seen += 1
                        if seen > max_entries:
                            return engine_of_files(names)
                        n = e.name.lower()
                        try:
                            is_dir = e.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        if is_dir:
                            if depth < MAX_DEPTH and n not in SKIP_DIRS:
                                stack.append((Path(e.path), depth + 1))
                        elif n.endswith(".dll"):
                            names.add(n)
            except OSError:
                continue
        return engine_of_files(names)
    except Exception:  # noqa: BLE001 - a suggestion must never break the app
        return None


_api = None


def _win32():
    """Private handles on user32 / kernel32 with their own prototypes: setting
    argtypes on ctypes.windll's shared function objects would change them under
    every other module that calls the same functions."""
    global _api
    if _api is None:
        import ctypes
        from ctypes import c_int, c_ulong, c_void_p
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        u.GetForegroundWindow.restype = c_void_p
        u.GetForegroundWindow.argtypes = ()
        u.GetWindowThreadProcessId.restype = c_ulong
        u.GetWindowThreadProcessId.argtypes = (c_void_p, ctypes.POINTER(c_ulong))
        k.OpenProcess.restype = c_void_p
        k.OpenProcess.argtypes = (c_ulong, c_int, c_ulong)
        k.QueryFullProcessImageNameW.restype = c_int
        k.QueryFullProcessImageNameW.argtypes = (c_void_p, c_ulong, ctypes.c_wchar_p,
                                                 ctypes.POINTER(c_ulong))
        k.CloseHandle.restype = c_int
        k.CloseHandle.argtypes = (c_void_p,)
        _api = u, k
    return _api


def foreground_process() -> tuple[int, str]:
    """(pid, exe path) of the window you're using, or (0, ''). This app's own
    windows count as none."""
    if sys.platform != "win32":
        return 0, ""
    try:
        import ctypes
        from ctypes import byref, c_ulong
        u, k = _win32()
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return 0, ""
        pid = c_ulong()
        u.GetWindowThreadProcessId(hwnd, byref(pid))
        if not pid.value or pid.value == os.getpid():
            return 0, ""
        # PROCESS_QUERY_LIMITED_INFORMATION: the least access there is, no memory
        h = k.OpenProcess(0x1000, False, pid.value)
        if not h:
            return 0, ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = c_ulong(len(buf))
            ok = k.QueryFullProcessImageNameW(h, 0, buf, byref(size))
        finally:
            k.CloseHandle(h)
        return (pid.value, buf.value) if ok else (0, "")
    except Exception:  # noqa: BLE001
        return 0, ""


def _is_system(path: str) -> bool:
    """Windows' own programs (the taskbar, Alt+Tab, the desktop): passing through
    them on the way from a game to this app shouldn't count as leaving the game.

    Runs on the UI thread every VOICE_POLL_MS, so it only compares strings: the
    foreground lookup already gives a full path, and resolving it on disk froze the
    window for 6 s when the game's drive was asleep."""
    win = os.environ.get("SystemRoot") or os.environ.get("windir")
    if not win or not path:
        return False
    try:
        sysdir = os.path.normcase(os.path.abspath(win)).rstrip("\\/") + os.sep
        return os.path.normcase(os.path.abspath(path)).startswith(sysdir)
    except (OSError, ValueError):
        return False


class Watcher:
    """The voice engine of the last program you had in front, while it runs.
    poll() is cheap (one foreground lookup); a new exe's folder is scanned once, on
    a thread, and cached by path. This app and Windows' own windows don't count, so
    the game you just switched away from is still the one suggested; any other
    program in front replaces it (with None if it ships no known voice engine)."""

    def __init__(self, foreground=None, scanner=None, alive=None):
        # looked up per call, so a test can stub the module's functions
        self._fg = foreground or (lambda: foreground_process())
        self._scan = scanner or (lambda path: scan(path))
        if alive is None:
            from soundboard.appaudio import is_running
            alive = is_running
        self._alive = alive
        self._cache: dict[str, str | None] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._pid = 0
        self.suggestion: str | None = None

    def _scan_bg(self, path: str):
        key = self._scan(path)
        with self._lock:
            self._cache[path] = key
            self._pending.discard(path)

    def poll(self) -> str | None:
        """Look at the foreground window once; returns the current suggestion."""
        pid, path = self._fg()
        if pid and path and not _is_system(path):
            with self._lock:
                known = path in self._cache
                key = self._cache.get(path)
                start = not known and path not in self._pending
                if start:
                    self._pending.add(path)
            if start:
                threading.Thread(target=self._scan_bg, args=(path,), daemon=True,
                                 name="voicesdk-scan").start()
            elif known:
                self._pid, self.suggestion = (pid, key) if key else (0, None)
        if self.suggestion and self._pid and not self._alive(self._pid):
            self._pid, self.suggestion = 0, None
        return self.suggestion


class Listeners:
    """Who records the cable's far end, as [(mode key, program name)], voice chat
    programs (VOICE_APPS) first, then games by their files. poll() is cheap: the
    sessions are listed (and a new game's folder scanned, once) on a thread, and it
    returns what the last look found."""

    def __init__(self, lister=None, scanner=None):
        if lister is None:
            from soundboard.appaudio import recording_apps
            lister = recording_apps
        self._list = lister
        self._scan = scanner or (lambda path: scan(path))
        self._cache: dict[str, str | None] = {}   # exe path -> mode key (games)
        self._busy = False
        self.found: tuple = ()

    def poll(self, device) -> tuple:
        """`device`: a recording device's name, or several (a tuple: straight into my
        mic looks at the mic and the cable's far end both)."""
        if not device:
            self.found = ()
        elif not self._busy:
            self._busy = True
            threading.Thread(target=self._look, args=(device,), daemon=True,
                             name="voicesdk-listeners").start()
        return self.found

    def look(self, device: str) -> tuple:
        """One look, on the calling thread (poll runs it on its own)."""
        voice, games = [], []
        devices = device if isinstance(device, tuple) else (device,)
        for app in [a for d in devices if d for a in self._list(d)]:
            hit = VOICE_APPS.get(app.exe.lower())
            if hit:
                voice.append(hit)
            elif app.path:
                if app.path not in self._cache:
                    self._cache[app.path] = self._scan(app.path)
                key = self._cache[app.path]
                if key:
                    games.append((key, app.name))
        return tuple(dict.fromkeys(voice + games))

    def _look(self, device: str):
        try:
            self.found = self.look(device)
        except Exception:  # noqa: BLE001 - only a hint
            self.found = ()
        finally:
            self._busy = False


__all__ = ["NAMES", "ORDER", "SIGNATURES", "VOICE_APPS", "Listeners", "Watcher",
           "engine_of_files", "foreground_process", "install_root", "scan"]
