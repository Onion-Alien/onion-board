"""The mic effect: what others hear goes straight into your real mic, no virtual cable.
Setup -> Devices -> Send my sounds to -> "My mic".

How: a small Windows audio effect (native/directmic/obmic.cpp, an "APO" like Equalizer
APO's) runs inside Windows' audio engine on one microphone, in front of every app that
records it. Discord and games keep using the normal mic, so there's nothing to pick
there, and nothing is injected into any game. Soundpad works this way.

Board <-> effect: a shared file, %ProgramData%\\OnionBoard\\MicPlugin\\ring2.bin (the
folder lets the audio engine's account and signed-in users read and write it):

  header (HEADER bytes; little-endian; offsets in bytes)
  0   u32 magic "OBMC"          4   u32 version (2)
  8   u32 rate (48000)          12  u32 capacity: frames in the main ring (power of 2)
  16  u64 frames written (board)                24  u64 board's last write (GetTickCount64)
  32  u32 enabled (board)       36  u32 mode (board): 0 add, 1 replace
  40  f32 gain (board)          44  f32 mic gain (board, add mode; 0 = muted)
  48  u32 mic capacity: frames in the clean-mic ring (power of 2)
  52  i32 publisher: the slot owner writing the clean mic
  56  u64 clean-mic frames written (effect)    64  u32 the clean mic's rate
  68  u32 lead (board): ring frames the effect reads behind the board (0 = 20 ms)
  72  u64 the clean mic's last block (GetTickCount64)
  80  u32 the running effect's version
  84  u32 the process id of the board writing (another board backs off; the effect
      doesn't read it)
  256 SLOTS slots of 64 bytes, one per app recording the mic (SLOT below)
  HEADER: f32[capacity] what others hear, mono, at `rate`
  then:   f32[mic capacity][2] the clean mic, at the mic's rate

The effect publishes the clean mic (after the mic's own driver effect, before anything
of the board's); the board's mic comes from there, so its meter, mic check and voice
changer never hear its own sounds come back. Each block of clean mic in, the board
renders the same stretch of what others hear and writes it out: it runs on the mic's
clock, so the two never drift apart. In replace mode (the default) that is the whole
send mix, your processed voice included, and the effect puts it in place of the mic
(about 20 ms later); add mode adds only the sounds on top of the mic. The board late
with a block: the effect fills in with the clean mic from the moment that block was
to be made from (`set_sync`), so the voice carries on. The board gone: the effect
crossfades back to the plain mic. Nobody recording
the mic: the effect doesn't run, and the board keeps time on its own clock.

Installing needs admin once (Windows' prompt): `install()` runs this app again as admin
(`--direct-mic install <endpoint>`), which copies the effect DLL to Program Files,
registers it, puts it on the mic (keeping any effect the mic's driver had, which the
effect then runs first) and restarts Windows' audio service. `uninstall()` puts every
mic back as it was. The DLL that's installed is always this app's own copy, never a path
from the command line, so the admin step can't be pointed at another DLL.

After that first prompt the admin steps go through the mic helper (soundboard/
michelper.py: a SYSTEM scheduled task running a frozen copy of the admin part,
micadmin.py, with its own DLL), with no prompt; `_elevated` tries it first and falls
back to Windows' prompt.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import time
import types
from typing import Any
from pathlib import Path

from soundboard.i18n import _

# its parts, each building on the ones before; all they have is reached through
# this module too (directmic.status, directmic.admin_install, ...): see _Parts
from soundboard.mic import micadmin, micbase, micring, micstate
from soundboard.mic.micbase import *  # noqa: F403
from soundboard.mic.micring import *  # noqa: F403
from soundboard.mic.micstate import *  # noqa: F403
from soundboard.mic.micadmin import *  # noqa: F403

from soundboard.mic.micbase import FLAG, bundled_dll, data_dir
from soundboard.mic.micstate import endpoint_for, mic_lookup
from soundboard.mic.micadmin import AUDIO_STUCK, EFFECT_NOT_STARTED, MIC_SHUT, MIC_SILENT


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------- the app's side

def relaunch_params(args: list[str]) -> str:
    parts = []
    if not getattr(sys, "frozen", False):
        parts.append(f'"{Path(__file__).resolve().parents[2] / "main.py"}"')
    return " ".join(parts + [FLAG] + args)


def _elevated(args: list[str], wait_s: float = 300.0, *,
              ask_windows: bool = True) -> int | None:
    """Run the admin command `args`: through the mic helper when it's set up (no
    prompt), else this app's admin copy (Windows asks first; not with `ask_windows`
    False: the app's own repair, which nobody clicked). Its exit code, or None if the
    prompt was turned down, not allowed, or it didn't finish. The audio stop/start and
    the dependent services can take a while on a slow PC, so allow generously.
    The helper's step raising (1) is tried once more through Windows' prompt, when
    asking is allowed: on PCs where the helper's run (as SYSTEM) failed every time, the
    same step run as the user's own admin had set the mic up (helper_fallback says why
    the helper's failed). Turned down, it stays the helper's 1."""
    global _helper_raised
    from soundboard.mic import michelper
    _helper_raised = None
    try:
        code = _via_helper(args, wait_s)
        if code == 1 and ask_windows:
            _helper_raised = raised_why(data_dir().parent / "michelper.log")
            log.warning("the mic helper's step failed (code 1): asking Windows instead")
        elif code is not None or not ask_windows:
            return code
        asked = run_elevated(sys.executable,
                             relaunch_params(args + michelper.for_user(args)), wait_s,
                             progress=data_dir().parent / "directmic-admin.log")
        return 1 if asked is None and code == 1 else asked
    finally:
        # what the UI shows follows the helper as it is now: the prompt's step may
        # have set it up, and another account may have removed it meanwhile
        _helper_check("after a step")


_helper_raised: tuple[str, str, str] | None = None   # set by _elevated


def helper_fallback() -> tuple[str, str, str] | None:
    """raised_why() of the helper's log when the last step's helper run raised and
    Windows' prompt was asked instead (_elevated), once; None if it didn't."""
    global _helper_raised
    why, _helper_raised = _helper_raised, None
    return why


def _helper_check(via: str = "check") -> bool:
    """michelper.ready() again, so michelper.will_ask() is current (on a worker).
    False if the check itself failed."""
    from soundboard.mic import michelper
    try:
        michelper.ready(via=via)
        return True
    except Exception:  # noqa: BLE001 - only the texts' "click Yes" depends on it
        log.warning("couldn't check the mic helper", exc_info=True)
        return False


def _via_helper(args: list[str], wait_s: float) -> int | None:
    """`args` run by the mic helper, or None to ask Windows instead. Setting up needs a
    helper with this app's effect DLL; taking it off works with any helper."""
    from soundboard.mic import michelper
    try:
        if not michelper.allowed(args):
            return None
        usable = michelper.ready(same_dll=args[0] in ("install", "reinstall"),
                                 via="before a step")
        return michelper.ask(args, wait_s) if usable else None
    except Exception:  # noqa: BLE001 - Windows' prompt still works
        log.warning("the mic helper failed", exc_info=True)
        return None


# run_elevated's "no answer came" codes (each reads as unfinished(); counted apart):
UNFINISHED = -1    # it started (its log changed), then went silent for wait_s
NOT_STARTED = -2   # Windows couldn't start it (an error other than a No)
NO_ANSWER = -3     # silent from the start: the prompt still open, or it never got going
UNFINISHED_CODES = (UNFINISHED, NOT_STARTED, NO_ANSWER)


PROMPT_CAP_S = 900.0   # an admin step still writing its log is waited for up to this


def wait_for(done, wait_s: float, progress: Path | None, cap_s: float = PROMPT_CAP_S,
             poll_s: float = 1.0) -> bool:
    """Wait for `done(seconds)` (blocks up to that long; True once finished) while
    `progress` (an admin log) keeps changing, up to `cap_s`: a slow PC still at work
    isn't cut off at a fixed time. False once it has been silent for `wait_s`."""
    start = last = time.monotonic()
    mark = _file_mark(progress)
    while True:
        if done(poll_s):
            return True
        now = time.monotonic()
        seen = _file_mark(progress)
        if seen != mark:
            mark, last = seen, now
        if now - start > cap_s or now - last > wait_s:
            return False


def _file_mark(path: Path | None) -> tuple[int, int] | None:
    try:
        st = path.stat() if path is not None else None
    except OSError:
        return None
    return None if st is None else (st.st_size, st.st_mtime_ns)


def run_elevated(exe: str, params: str, wait_s: float = 90.0,
                 progress: Path | None = None) -> int | None:
    """Run `exe` as admin, hidden (Windows asks first). Its exit code; None if the
    prompt was turned down (ERROR_CANCELLED: a No, or a PC that denies admin rights to
    this account); one of UNFINISHED_CODES if it couldn't start otherwise (NOT_STARTED)
    or didn't finish (silent for `wait_s`: the log `progress` didn't change either;
    NO_ANSWER if it never changed, the prompt may still be open: nobody clicked No)."""
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x40,
                             lpVerb="runas", lpFile=exe, lpParameters=params, nShow=0)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    before = _file_mark(progress)
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        error = ctypes.get_last_error()
        log.info("%s %s not run (error %s)", Path(exe).name, params[-40:], error)
        return None if error == 1223 else NOT_STARTED   # ERROR_CANCELLED: turned down
    try:
        handle = info.hProcess
        if not wait_for(lambda t: kernel32.WaitForSingleObject(handle, int(t * 1000)) == 0,
                        wait_s, progress, max(PROMPT_CAP_S, wait_s)):
            log.info("%s %s didn't finish (silent for %.0f s)", Path(exe).name,
                     params[-40:], wait_s)
            return UNFINISHED if _file_mark(progress) != before else NO_ANSWER
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def declined() -> str:
    """What install/uninstall return when Windows' admin prompt was turned down."""
    return _("Windows' admin prompt was turned down (or didn't finish).")


def unfinished() -> str:
    """What install/uninstall return when the admin step didn't finish (or couldn't
    start): not a No, so the card never says one was clicked."""
    return _("Windows' admin step didn't finish. If its prompt is still open, answer it; "
             "then try again.")


def mic_silent() -> str:
    """What a step returns when it was done, but the mic still sends only silence after
    every restart of Windows' audio (MIC_SILENT)."""
    return _("Your mic sends no sound. Is your headset switched off, or its mic muted? "
             "Turn it on or unmute it. Still nothing? Restart your PC, then try again.")


def no_helper() -> str:
    """What install returns when the mic helper couldn't do it and Windows wasn't asked."""
    return _("Onion Board's mic helper didn't answer.")


def no_mic() -> str:
    """What install returns when the mic isn't plugged in (or Windows doesn't list it)."""
    return _("That mic isn't plugged in (or Windows doesn't list it).")


def mic_gone() -> str:
    """What install returns when Windows doesn't know the picked mic at all."""
    return _("Windows doesn't know that mic any more. Pick your mic again (Setup tab → Devices).")


def mic_unsure() -> str:
    """What install returns when two mics start like the picked mic's name."""
    return _("Two mics have names like that one. Pick yours again (Setup tab → Devices).")


def no_effect() -> str:
    """What install returns when this copy has no mic effect DLL bundled."""
    return _("This copy of Onion Board has no mic effect in it.")


# why a set-up failed, as counted (usage MIC_FAILS): the admin step's prompt left
# unanswered (NO_ANSWER), it couldn't start (NOT_STARTED) or it stopped half-way
# (UNFINISHED); the mic silent after it; the mic helper not answering (only the app's
# own repair, which never asks Windows); no such mic; no effect in this copy; or the
# admin step's own exit code: 1 it raised, 2 the mic isn't listed to admins, 3 the effect
# file missing or empty, 4 another copy at it, 5 its data folder couldn't be secured,
# 6 Windows' audio wouldn't stop, 8 the effect didn't start on its mic, 9 a mic stopped
# opening. Never the message, the mic or a path.
FAIL_CODES = (1, 2, 3, 4, 5, 6, EFFECT_NOT_STARTED, MIC_SHUT)
# no such mic, and why (mic_lookup): unplugged or off, two that look alike, unknown.
# Plain "no-mic" is a set-up given no mic at all (and what 2.2 and older counted).
NO_MIC_KINDS = ("no-mic-off", "no-mic-unsure", "no-mic-gone")
FAIL_KINDS = ("unanswered", "no-start", "stuck", "silent", "no-helper", "no-mic",
              *NO_MIC_KINDS, "no-effect", *(f"code-{c}" for c in FAIL_CODES), "code-other")
_UNFINISHED_KIND = {NO_ANSWER: "unanswered", NOT_STARTED: "no-start", UNFINISHED: "stuck"}


class Failure(str):
    """install()'s reason in plain words, with `kind`: a fixed word from FAIL_KINDS
    (or "said-no") to count, so nothing matches the translated message."""
    kind: str

    def __new__(cls, text: str, kind: str):
        self = super().__new__(cls, text)
        self.kind = kind
        return self


# exit code 1 (the admin step raised): which part of it, by the deepest of these in the
# admin log's last traceback, what Windows said (RAISED_WHAT) and its error number
# (RAISED_ERR). Counted as these fixed words (usage MIC_RAISED), never the log's text.
# Only Windows 10 PCs failed so far.
RAISED_AT = {"_register_com": "register", "_install_endpoint": "mic-settings",
             "_uninstall_endpoint": "mic-settings", "_strip_endpoint": "mic-settings",
             "_fx_values": "mic-settings", "capture_endpoints": "mic-settings",
             "installed_on": "mic-settings", "_BackupKey": "mic-settings",
             "_make_ring": "ring", "secure_data_dirs": "ring", "_secure_dir": "ring",
             "_clean_base": "ring", "_put_on": "files", "_remove": "files",
             "_audio_service": "audio", "_audio_off": "audio", "_running_dependents": "audio",
             "_enable_privileges": "rights"}
RAISED_WHERE = (*dict.fromkeys(RAISED_AT.values()), "other")
RAISED_WHAT = ("denied", "in-use", "missing", "other")
# the Windows error numbers worth telling apart: not found (2, 3), denied (5), in use
# (32, 33), bad parameter (87), a mapped file (1224), a privilege not held (1314)
RAISED_CODES = (2, 3, 5, 32, 33, 87, 1224, 1314)
RAISED_ERR = (*(f"err-{n}" for n in RAISED_CODES), "err-other", "err-none")


def admin_logs() -> list[Path]:
    """The logs an admin step writes to: its own (Windows' prompt) and the mic
    helper's (a step the helper ran logs there), newest first."""
    base = data_dir().parent
    logs = [base / "directmic-admin.log", base / "michelper.log"]

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    return sorted(logs, key=mtime, reverse=True)


def _log_tail(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 64 * 1024))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def raised_why(log_path: Path | None = None) -> tuple[str, str, str]:
    """(where, what, err) the admin step's last exception was, from the tail of its log
    (users may read it): RAISED_WHERE, RAISED_WHAT and RAISED_ERR words, ("other",
    "other", "err-none") when no log can tell. Without `log_path`, the newest of
    admin_logs() that has one."""
    for path in [log_path] if log_path else admin_logs():
        tail = _log_tail(path)
        start = tail.rfind("Traceback (most recent call last):")
        if start >= 0:
            break
    else:
        return "other", "other", "err-none"
    lines = tail[start:].splitlines()[1:]
    funcs = [m.group(1) for m in map(re.compile(r'\s*File ".*", line \d+, in (\S+)').match,
                                     lines) if m]
    where = next((RAISED_AT[f] for f in reversed(funcs) if f in RAISED_AT), "other")
    last = next((s for s in lines if s and not s[0].isspace()), "")
    what = ("denied" if re.match(r"PermissionError|.*\[(WinError 5|Errno 13)\]", last) else
            "in-use" if re.match(r".*\[WinError (32|33)\]", last) else
            "missing" if re.match(r"FileNotFoundError|.*\[WinError [23]\]", last) else
            "other")
    m = re.match(r".*\[WinError (\d+)\]", last)
    err = ("err-none" if not m else
           f"err-{m.group(1)}" if int(m.group(1)) in RAISED_CODES else "err-other")
    return where, what, err


# exit code 6 (Windows' audio wouldn't stop): which of its two services was still up,
# from the AUDIO_STUCK line the admin step logs (stuck_why)
STUCK_WHICH = ("audio", "builder", "both", "other")


def stuck_why(log_path: Path | None = None) -> str:
    """Which of Windows' audio services the last step that got exit code 6 couldn't
    stop: a STUCK_WHICH word ("other" when no log says)."""
    for path in [log_path] if log_path else admin_logs():
        tail = _log_tail(path)
        at = tail.rfind(AUDIO_STUCK)
        if at >= 0:
            up = tail[at + len(AUDIO_STUCK):].partition("\n")[0].lower()
            audio, builder = "audiosrv" in up, "audioendpointbuilder" in up
            return ("both" if audio and builder else "audio" if audio else
                    "builder" if builder else "other")
    return "other"


def fail_kind(err: str) -> str:
    """Which of FAIL_KINDS install()'s result `err` is ("code-other" for any other text)."""
    kind = getattr(err, "kind", "")
    return kind if kind in FAIL_KINDS else "code-other"


def install(mic_name: str | None, *, clean: bool = False,
            ask_windows: bool = True) -> str | None:
    """Put the effect on the mic called `mic_name` (Windows asks for admin, unless the
    mic helper does it, or `ask_windows` is False). None when done, else what went
    wrong, in plain words."""
    guid = endpoint_for(mic_name)
    if guid is None:
        why = mic_lookup(mic_name)[1] or "gone"
        text = {"off": no_mic, "unsure": mic_unsure}.get(why, mic_gone)()
        return Failure(text, f"no-mic-{why}")
    return install_on(guid, clean=clean, ask_windows=ask_windows)


def install_on(guid: str | None, *, clean: bool = False,
               ask_windows: bool = True) -> str | None:
    """install() for the mic with endpoint GUID `guid` (it comes off any other mic)."""
    if guid is None:
        return Failure(no_mic(), "no-mic")
    if not bundled_dll().is_file():
        return Failure(no_effect(), "no-effect")
    code = _elevated(["reinstall" if clean else "install", guid], ask_windows=ask_windows)
    if code is None:
        return Failure(declined(), "said-no") if ask_windows else \
            Failure(no_helper(), "no-helper")
    if code in UNFINISHED_CODES:
        return Failure(unfinished(), _UNFINISHED_KIND[code])
    if code == MIC_SILENT:
        return Failure(mic_silent(), "silent")
    if code:
        return Failure(_("Installing failed (code {code}). The log is in {folder}.",
                         code=code, folder=data_dir().parent),
                       f"code-{code}" if code in FAIL_CODES else "code-other")
    return None


def cleanup(guid: str) -> str | None:
    """admin_cleanup() on the mic with endpoint GUID `guid` (Windows asks first)."""
    code = _elevated(["cleanup", guid])
    if code is None:
        return declined()
    if code in UNFINISHED_CODES:
        return unfinished()
    return _("Cleaning up failed (code {code}).", code=code) if code else None


def uninstall(guid: str | None = None) -> str | None:
    """Take the effect off every mic, or only off the mic with endpoint GUID `guid`."""
    code = _elevated(["uninstall", guid] if guid else ["uninstall"])
    if code is None:
        return declined()
    if code in UNFINISHED_CODES:
        return unfinished()
    if code == MIC_SILENT:
        return mic_silent()
    return _("Removing failed (code {code}).", code=code) if code else None


# ---------------------------------------------------------------------- one module

# The mic effect was one module, and the app, the mic helper and the tests still use it
# as one: what a part has is read here (directmic.admin_install, the private names
# too), and a name set here (a test's monkeypatch) is set in every part that has the
# same thing, so it reaches the code that uses it wherever that code now lives.
_PARTS = (micbase, micring, micstate, micadmin)
_UNSET = object()


def __getattr__(name: str) -> Any:
    for part in _PARTS:
        if name in vars(part):
            return vars(part)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _Parts(types.ModuleType):
    def __setattr__(self, name: str, value):
        old = getattr(self, name, _UNSET)
        if old is not _UNSET:
            for part in _PARTS:
                if vars(part).get(name, _UNSET) is old:
                    setattr(part, name, value)
        if name in vars(self) or not any(name in vars(part) for part in _PARTS):
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Parts
