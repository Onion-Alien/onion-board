"""Application entry point: logging, runtime tuning, single instance, the window."""
from __future__ import annotations

import ctypes
import gc
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# (Up to 1.9.7 QT_WIDGETS_RHI=1 was set here so the Radio tab's 3D globe could show
# without rebuilding the window. It gave every window its own Direct3D device, 16
# driver threads and ~30 MB each, never freed; the globe is gone and windows draw
# the ordinary way again.)
from PySide6.QtWidgets import QApplication

from soundboard import __version__
from soundboard.core import applog
from soundboard.sounds.library import APP_DIR, migrate_from_soundboard
from soundboard.core.singleinstance import (bring_to_front, claim_single_instance,
                                            comes_to_front, listen_for_second_launch)

log = logging.getLogger(__name__)


SWITCH_S = 0.0002   # the GIL's switch interval while the app runs (tune_runtime_for_audio)


def tune_runtime_for_audio():
    """Two cheap knobs that keep the audio callbacks from waiting on the UI thread.

    The interpreter lets a thread hold the GIL for 5 ms before forcing a switch; a
    WASAPI callback at low latency has about 10 ms to produce its block. And it
    doesn't wait once: numpy lets go of the GIL in every operation on more than 500
    values (a stereo block is 960), and each time another thread busy in Python (the
    window painting, a station list being read, Onion Watch) takes it, the callback
    waits a whole interval to get it back. At 1 ms the send output's callback took 15 ms
    instead of 0.5 whenever anything else ran Python: a stutter in what others
    hear. At 0.2 ms it takes ~1 ms, and the busy thread loses nothing it would
    otherwise keep (test_engine: test_callback_keeps_pace_beside_busy_python).

    The garbage collector's gen-0 threshold is 700 allocations; numpy blocks in
    the callbacks are Python objects, so every few blocks a collection ran *on the
    audio thread*. Raising the threshold makes collections rarer till main() hands
    them to the UI thread (uigc.UiCollector, which keeps each pause short: the audio
    threads still wait one out).
    """
    sys.setswitchinterval(SWITCH_S)
    gc.set_threshold(50_000, 20, 20)


RESTART_FLAGS = 8   # RESTART_NO_REBOOT: after a crash, a hang or an update, not a reboot
RESTARTED_ARG = "--restarted"   # on the line Windows starts it again with


def restart_cmdline(argv: list[str], frozen: bool) -> str:
    """What Windows starts the app again with after an installer closed it: the same
    arguments, minus the one-off ones (as in MainWindow.restart_app), and with the
    window shown: it was most likely open, and coming back hidden looks like it's gone."""
    from soundboard.core.autostart import TRAY_ARG
    args = list(argv[1:] if frozen else argv)
    if not frozen and args:   # python main.py: the script by full path, any cwd works
        args[0] = os.path.abspath(args[0])
    if "--restart-after" in args:
        i = args.index("--restart-after")
        del args[i:i + 2]
    args = [a for a in args if a not in (TRAY_ARG, "--resume-setup", RESTARTED_ARG)]
    return subprocess.list2cmdline([*args, RESTARTED_ARG])


def register_restart():
    """Ask Windows to start the app again when it ends without being quit: an installer
    closing it to update it (Inno Setup's CloseApplications restarts the apps that
    asked), a crash, or Windows closing it as Not Responding. Windows only does it for a
    run of 60 s or more, so a crash at start can't loop. Not after a reboot."""
    try:
        ctypes.windll.kernel32.RegisterApplicationRestart(
            ctypes.c_wchar_p(restart_cmdline(sys.argv, getattr(sys, "frozen", False))),
            RESTART_FLAGS)
    except Exception:  # noqa: BLE001 - only a nicety
        log.debug("RegisterApplicationRestart failed", exc_info=True)


def wait_for_exit(pid: list[str], seconds: float = 30.0):
    """Wait for the copy that restarted us to finish quitting (it still holds the
    single-instance lock and is saving its settings)."""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x00100000, False, int(pid[0]))   # SYNCHRONIZE
        if h:
            k32.WaitForSingleObject(ctypes.c_void_p(h), int(seconds * 1000))
            k32.CloseHandle(ctypes.c_void_p(h))
    except (ValueError, IndexError, OSError, AttributeError):
        log.debug("couldn't wait for the old copy", exc_info=True)


def end_process(code: int):
    """End this process at once with `code`, running nothing else first. os._exit
    alone isn't enough on Windows: ExitProcess still runs every DLL's detach code
    and static destructors, and with other threads still alive (Onion Watch's
    watcher, the speech worker, an FFT pool) PySide6's crashed in them, so a clean
    quit ended in an access violation and a Windows "stopped working" report.
    TerminateProcess skips all of that; the settings are already saved."""
    applog.flush()   # the log is written on a thread: its last lines first
    try:
        sys.stdout and sys.stdout.flush()
        sys.stderr and sys.stderr.flush()
    except (OSError, ValueError):
        pass
    if sys.platform == "win32":
        try:
            k32 = ctypes.WinDLL("kernel32")
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint)
            k32.TerminateProcess(k32.GetCurrentProcess(), code & 0xFFFFFFFF)
        except (OSError, AttributeError):
            pass
    os._exit(code)


# %TEMP% folders of ours that can be left behind: a download the app was closed (or
# crashed) in the middle of (a sound, a links pack, a pack's samples), and an add-on
# self-test. Only these exact prefixes.
TEMP_LEFTOVERS = ("sb-ytdl-", "sb-linkpack-", "sb-linkpreview-", "onionboard-selftest-")
TEMP_MAX_AGE_S = 24 * 3600
# ytsites.temp_folder: "<prefix><the app's process id>-..."
_TEMP_OWNER = re.compile(r"(?:sb-ytdl|sb-linkpack|sb-linkpreview)-(\d+)-")


def _owner_gone(name: str) -> bool:
    """The app that made this download folder isn't running any more (a pid reused
    since by another program counts as running: the folder waits for the day)."""
    m = _TEMP_OWNER.match(name)
    if not m or int(m.group(1)) == os.getpid() or sys.platform != "win32":
        return False
    from soundboard.audio import appprocs
    return not appprocs.is_running(int(m.group(1)))


def clean_temp_leftovers(now: float | None = None) -> int:
    """Delete TEMP_LEFTOVERS folders in %TEMP% whose app is gone or untouched for a day
    (a running download's is newer). Returns how many went. Run off the UI thread."""
    import shutil
    import tempfile
    import time
    from pathlib import Path
    now = time.time() if now is None else now
    gone = 0
    try:
        for p in Path(tempfile.gettempdir()).iterdir():
            if not p.name.startswith(TEMP_LEFTOVERS):
                continue
            try:
                if (p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                        or not p.is_dir()
                        or (now - p.stat().st_mtime < TEMP_MAX_AGE_S
                            and not _owner_gone(p.name))):
                    continue
                shutil.rmtree(p, ignore_errors=True)
                gone += not p.exists()
            except OSError:
                continue
    except OSError:
        log.debug("couldn't look through the temp folder", exc_info=True)
    if gone:
        log.info("removed %d old temp folder(s)", gone)
    return gone


def packs_dedupe():
    """Free packs an older version stored twice (backup.drop_duplicate_packs), off the
    UI thread."""
    from soundboard.core import backup
    try:
        backup.drop_duplicate_packs()
    except Exception:  # noqa: BLE001 - tidying up must never hurt the running app
        log.debug("couldn't tidy duplicate sound packs", exc_info=True)


def modules_prune():
    """Leftover add-on copies (modules.prune_leftovers), off the UI thread."""
    from soundboard.addons import modules
    try:
        modules.prune_leftovers()
    except Exception:  # noqa: BLE001 - tidying up must never hurt the running app
        log.debug("couldn't tidy old add-on copies", exc_info=True)


def start_ytdlp_check(cfg):
    """The daily "is there a newer yt-dlp?" check, off the UI thread (see ytdl.py), and
    the app's own FFmpeg and Tor brought to the versions this release names."""
    import threading

    from soundboard.online import netlog, ytdl
    netlog.cause(ytdl.UPDATE_FEATURE, "Automatic daily check for a newer downloader "
                                      "(yt-dlp), after start-up")
    threading.Thread(target=ytdl.auto_update, args=(cfg.ytdlp_auto_optin,), daemon=True,
                     name="ytdlp-update").start()
    threading.Thread(target=helpers_follow_app, daemon=True, name="helpers-update").start()


def helpers_follow_app():
    """FFmpeg and Tor update with the app: a copy the app downloaded for an older
    version of itself is replaced by the one this version names (pinned and checked
    against its SHA-256, so it's as safe as the app update itself). Tor waits while
    Connection is set to Tor (it's carrying the app's traffic); Update Tor does it."""
    from soundboard.online import ffmpegget, net, netlog, tor, torget
    try:
        netlog.cause(ffmpegget.FEATURE, "FFmpeg follows the app update (its own copy)")
        h = ffmpegget.update_own()
        if h is not None:
            log.info("FFmpeg after following the app: %s %s", h.state, h.version)
    except Exception as e:  # noqa: BLE001 - offline etc.: try again next start
        log.info("couldn't update the app's FFmpeg: %s", e)
    try:
        if (torget.outdated() and net.allowed(torget.FEATURE)
                and net.mode() != net.TOR):
            netlog.cause(torget.FEATURE, "Tor follows the app update")
            torget.get(before_unpack=tor.shutdown)
    except Exception as e:  # noqa: BLE001 - offline etc.: try again next start
        log.info("couldn't update Tor: %s", e)


def selftest() -> int:
    """`OnionBoard.exe --selftest`: prove a (pruned) build can load everything it
    ships, without a window, a device, a hotkey or a network request. build.ps1
    runs it after trimming Qt (scripts/buildtools/prune_build.py), so a missing DLL fails the
    build instead of a user's first launch. Prints OK and returns 0."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    # scipy.fft: the app itself doesn't use scipy, but Onion Watch's matcher does, and
    # build.ps1 ships only that part of it
    for mod in ("numpy", "scipy.fft", "sounddevice", "soundfile", "soxr", "yt_dlp",
                # yt-dlp's browser impersonation (TikTok links): its libcurl DLL loads,
                # and this yt-dlp accepts that curl_cffi version
                "curl_cffi.curl", "yt_dlp.networking._curlcffi"):
        __import__(mod)
    from PySide6.QtMultimedia import QMediaPlayer
    _app = QApplication(sys.argv)   # kept until the checks below have run
    from soundboard.ui.window import mainwindow  # noqa: F401
    from soundboard.ui.setup import setupwizard  # noqa: F401
    from soundboard.ui.kit import crashdialog  # noqa: F401
    from soundboard.audio import engine  # noqa: F401
    from soundboard.ui.kit import theme  # noqa: F401
    from soundboard.online import radio  # noqa: F401
    theme.app_icon()
    QMediaPlayer()   # loads the FFmpeg multimedia plugin
    from soundboard.online import jsengine  # YouTube's player challenge (build.ps1 bundles it)
    if getattr(sys, "frozen", False) and jsengine.bundled() is None:
        print("FAIL: the bundled QuickJS (qjs.exe) is missing or won't start",
              file=sys.stderr)
        return 1
    from soundboard.voicefx import cleanmic   # Clean mic's RNNoise (build.ps1 bundles it)
    if getattr(sys, "frozen", False) and not cleanmic.available():
        print(f"FAIL: the bundled RNNoise (rnnoise.dll) won't load: {cleanmic.why()}",
              file=sys.stderr)
        return 1
    print(f"OK: Onion Board {__version__} self-test passed")
    return 0


def get_tor() -> int:
    """`OnionBoard.exe --get-tor`: the installer's "Private connection (Tor)" box.
    Downloads Tor into %APPDATA%\\OnionBoard\\tor\\bin (soundboard.online.torget, the same
    routine as Settings' Get Tor button) the way the saved Connection setting says, so
    a proxy set there is used. No window. Returns 0 when Tor is there (already, or
    now), 1 if it couldn't be got."""
    applog.setup(APP_DIR)
    from soundboard.sounds import library
    from soundboard.online import net, tor, torget
    if torget.installed():
        return 0
    cfg = library.Config.load()
    tor.configure_from(cfg)   # updating an older Tor in Tor mode: through that Tor
    net.configure_from(cfg)
    try:
        torget.get(before_unpack=tor.shutdown)
    except torget.GetError as e:
        log.warning("--get-tor: %s", e)
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    finally:
        tor.shutdown()
    print(f"OK: Tor {torget.VERSION} is in {torget.bin_dir()}")
    return 0


def install_addon(module_id: str) -> int:
    """`OnionBoard.exe --install-addon live-voice`: the installer's live voice box. Runs
    the add-on's install (soundboard.addons.modules.install, the same as the Voice tab's
    Install button), getting a Python for it first when the PC has no good one
    (soundboard.online.pyget), the way the saved Connection setting says. No window. Returns
    0 when it's set up (already, or now), 1 if it couldn't be."""
    applog.setup(APP_DIR)
    from soundboard.sounds import library
    from soundboard.online import net, tor
    from soundboard.addons import modules
    info = modules.find(module_id)
    if info is None or info.error:
        print(f"FAIL: no usable add-on {module_id!r}", file=sys.stderr)
        return 1
    if info.installed:
        return 0
    cfg = library.Config.load()
    tor.configure_from(cfg)
    net.configure_from(cfg)
    try:
        ok = modules.install(info, print)
    finally:
        tor.shutdown()
    if not ok:
        log.warning("--install-addon %s failed", module_id)
        print("FAIL", file=sys.stderr)
        return 1
    print(f"OK: {module_id} is set up")
    return 0


def set_offline() -> int:
    """`OnionBoard.exe --set-offline`: the installer's "Offline mode" box (or
    /OFFLINE=1). Switches on Offline mode in config.json before the app's first start,
    so it never goes online, not even once. Other settings are kept; nothing
    connects. No window. Returns 0 once it's saved, 1 if it couldn't be."""
    migrate_from_soundboard()   # an old %APPDATA%\Soundboard moves only while there's no config
    applog.setup(APP_DIR)
    from soundboard.sounds import library
    cfg = library.Config.load()
    if cfg.read_only:   # locked: saving would overwrite the newest settings with a backup
        print("FAIL: config.json is locked by another program", file=sys.stderr)
        return 1
    cfg.net_offline = True
    if not cfg.save():
        print(f"FAIL: couldn't save {library.CONFIG_PATH}", file=sys.stderr)
        return 1
    log.info("--set-offline: Offline mode is on")
    print("OK: Offline mode is on")
    return 0


def keep_netlog() -> int:
    """`OnionBoard.exe --keep-netlog`: the installer's /KEEPNETLOG=1 (its box
    moved to the app's Settings). Switches on netlog_keep in config.json before
    the app's first start, so its first connections are kept too. Other settings are
    kept; nothing connects. No window. Returns 0 once it's saved, 1 if it couldn't be."""
    migrate_from_soundboard()
    applog.setup(APP_DIR)
    from soundboard.sounds import library
    cfg = library.Config.load()
    if cfg.read_only:
        print("FAIL: config.json is locked by another program", file=sys.stderr)
        return 1
    cfg.netlog_keep = True
    if not cfg.save():
        print(f"FAIL: couldn't save {library.CONFIG_PATH}", file=sys.stderr)
        return 1
    log.info("--keep-netlog: network activity is kept between starts")
    print("OK: network activity is kept between starts")
    return 0


def set_usage_count(on: bool, heard: str = "") -> int:
    """`OnionBoard.exe --usage-count on|off [--heard-from <answer>]`: the installer's
    "Count me in" box. Off adds the usage count to the switched-off features in
    config.json before the app's first start, after one anonymous "opt-out/installer"
    if it was on until now (usage.opt_out: no ID); on takes it out
    (only a box the user saw: a silent update never passes on). `heard` is the
    installer's "Where did you hear about Onion Board?", kept for the first-start
    event. Other settings are kept; nothing connects. No window. Returns 0 once it's
    saved, 1 if it couldn't be."""
    migrate_from_soundboard()
    applog.setup(APP_DIR)
    from soundboard.sounds import library
    cfg = library.Config.load()
    if cfg.read_only:
        print("FAIL: config.json is locked by another program", file=sys.stderr)
        return 1
    if not on and "usage_stats" not in cfg.net_off:   # on until now: say so once
        try:
            from soundboard.online import net
            from soundboard.core import usage
            net.configure_from(cfg)
            if net.mode() != net.TOR:   # Tor isn't running: don't start it
                log.info("--usage-count off: opt-out %s",
                         "sent" if usage.opt_out("installer") else "not sent")
        except Exception:  # noqa: BLE001 - never in the installer's way
            log.warning("--usage-count off: opt-out failed", exc_info=True)
    cfg.net_off = [k for k in cfg.net_off if k != "usage_stats"] + ([] if on else ["usage_stats"])
    if heard:
        cfg.stats_heard = heard[:200]
    if not cfg.save():
        print(f"FAIL: couldn't save {library.CONFIG_PATH}", file=sys.stderr)
        return 1
    log.info("--usage-count: %s", "on" if on else "off")
    print(f"OK: the anonymous usage count is {'on' if on else 'off'}")
    return 0


def uninstall_count() -> int:
    """`OnionBoard.exe --uninstall-count`: the uninstaller's one "uninstall/<version>"
    for the anonymous usage count, only if it's switched on (and not Offline mode),
    through the saved Connection setting. No window. Always returns 0: an uninstall
    never waits on, or fails for, this."""
    try:
        applog.setup(APP_DIR)
        from soundboard.sounds import library
        from soundboard.core import usage
        from soundboard.online import net
        cfg = library.Config.load()
        if not cfg.stats_id:   # never counted (switched off, or from before the count)
            return 0
        net.configure_from(cfg)
        if net.mode() == net.TOR:   # Tor isn't running: don't start it
            return 0
        sent = usage.send_now(cfg, usage.uninstall_event())
        log.info("--uninstall-count: %s", "sent" if sent else "not sent")
    except Exception:  # noqa: BLE001 - never in the uninstaller's way
        log.warning("--uninstall-count failed", exc_info=True)
    return 0


def selftest_addon(path: str) -> int:
    """`OnionBoard.exe --selftest-addon OnionWatch-module.zip`: prove this build can
    run the Onion Watch add-on (it has no pip, so the add-on may only use what the
    build ships). Installs the zip into a temp folder, loads it the way the Triggers
    tab does, builds its tab on a stand-in board, and lists windows and screens with
    it. No window, no device, no network. Prints OK and returns 0. The temp folder
    goes afterwards (a build check runs this often)."""
    import shutil
    import tempfile
    from pathlib import Path
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    _app = QApplication(sys.argv)   # noqa: F841 - kept while the tab is built
    tmp = Path(tempfile.mkdtemp(prefix="onionboard-selftest-"))
    try:
        return _selftest_addon_in(Path(path), tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest_addon_in(path, tmp) -> int:
    import importlib

    from soundboard.addons import modules
    from soundboard.ui.kit import theme
    info = modules.install_zip(path, "onion-watch", "triggers", tmp / "modules")
    entry = modules.load_package(info)

    class Host:   # the stand-in board: onionwatch.host.Host, nothing played
        api_version = modules.TRIGGERS_API[1]
        name, default_sound = "Onion Board", ""
        audio_exts = frozenset({".wav"})
        screen, data_dir = {}, tmp

        def save(self): pass
        def sounds(self): return []
        def add_sound(self, path, done): done(None)
        def play(self, sid, loop=False, tag=""): return False
        def stop_tag(self, tag): pass
        def ringing(self): return []
        def palette(self): return dict(theme.T)
        def notify(self, title, body): pass

    tab = entry.create(Host())
    pkg = info.package

    def lazy(*subs):   # the lazy ones; newer Onion Watch keeps them in engine/ and ui/triggers/
        for sub in subs[:-1]:
            name = f"{pkg}.{sub}"
            try:
                return importlib.import_module(name)
            except ModuleNotFoundError as e:   # only "not at this path": a missing library fails
                if e.name is None or not name.startswith(e.name):
                    raise
        return importlib.import_module(f"{pkg}.{subs[-1]}")

    lazy("ui.triggers.windowpicker", "ui.windowpicker")
    lazy("ui.triggers.snip", "ui.snip")
    wins = lazy("engine.windows", "windows").list_windows()
    sw = lazy("engine.screenwatch", "screenwatch")
    mons = sw.monitors()
    # its matcher, on a made-up screen: a piece of it is found where it was cut
    import numpy as np
    screen = np.random.default_rng(0).random((90, 160), np.float32) * 255
    score, at = sw.match(screen, screen[30:50, 40:80])
    tab.shutdown()
    if score < 0.99 or tuple(at) != (40, 30):
        print(f"FAILED: Onion Watch's matcher found its picture at {at} ({score:.3f})")
        return 1
    # its FFTs are scipy.fft's when this build ships it (newer Onion Watch: imgops)
    ops = sys.modules.get(f"{pkg}.engine.imgops") or sys.modules.get(f"{pkg}.imgops")
    fft = "?" if ops is None else ("scipy.fft" if ops._sfft is not None else "numpy")
    print(f"OK: Onion Watch {info.version} runs in Onion Board {__version__} "
          f"({len(wins)} windows, {len(mons)} screens seen, matching with {fft} FFTs)")
    return 0


def ui_scale_startup(app_dir: Path) -> int:
    """Size the whole interface by config.json's `ui_scale` (Settings > Appearance >
    Interface size): earlystart.interface_size, which also runs before the early
    loading screen's QApplication."""
    from soundboard.core import earlystart
    pct = earlystart.interface_size(app_dir)
    log.info("interface size: %d%%", pct)
    return pct


LOAD_WAIT_S = 3.0    # longest the loading screen waits for the sounds (a big first load)
PAINT_WAIT_S = 0.5   # ...and for Windows to put the window on screen for its first paint
LITE_HINT_MS = 40_000     # a slower PC is told about lite mode this long after start
TRAY_PRELOAD_MS = 20_000   # started into the tray: Settings and Edit sound built after this


def wait_for_sounds(app, w, cap_s: float = LOAD_WAIT_S):
    """The sounds (SoundsControl._load_all's thread) finish loading behind the loading
    screen: ~0.4 s for 50 sounds that otherwise ran right after the window showed,
    sharing Python with the first paint and the first clicks. Events are handled
    meanwhile, so each pad gets its sound as it loads. A big library shows the window
    after `cap_s` and loads the rest as before."""
    import time
    loader = getattr(w.soundctl, "_load_thread", None)
    end = time.monotonic() + cap_s
    while loader is not None and loader.is_alive() and time.monotonic() < end:
        app.processEvents()
        loader.join(0.01)   # (not a busy loop: the loader gets Python meanwhile)
    app.processEvents()   # the last sounds' results


def first_paint(app, w, cap_s: float = PAINT_WAIT_S):
    """The window's first layout and paint (~0.1 s), done while the loading screen is
    still up rather than as the first thing after it goes."""
    import time
    end = time.monotonic() + cap_s
    handle = w.windowHandle()
    while handle is not None and not handle.isExposed() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()   # layouts asked for while it was built
    w.repaint()


def _usage_count_cmd(rest: list[str]) -> int:
    j = rest.index("--heard-from") if "--heard-from" in rest else -1
    heard = rest[j + 1] if 0 <= j < len(rest) - 1 else ""
    return set_usage_count(rest[:1] == ["on"], heard)


def _selftest_addon_cmd(rest: list[str]) -> int:
    try:
        return selftest_addon(rest[0])
    except Exception as e:  # noqa: BLE001 - a FAILED line, not the frozen exe's error box
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def quit_running() -> int:
    """`OnionBoard.exe --quit-running`: the uninstaller's first step, before the count.
    The Onion Board that's open is asked to quit (it saves its settings). 0 once none is
    running, 1 if one still is (the uninstaller then ends it)."""
    try:
        applog.setup(APP_DIR)
        from PySide6.QtCore import QCoreApplication
        from soundboard.core import singleinstance
        _app = QCoreApplication.instance() or QCoreApplication(sys.argv)  # noqa: F841
        closed = singleinstance.ask_running_to_quit()
        log.info("--quit-running: %s", "none running" if closed else "still running")
        return 0 if closed else 1
    except Exception:  # noqa: BLE001 - the uninstaller ends it instead
        log.warning("--quit-running failed", exc_info=True)
        return 1


# The one-off commands main() runs and exits; each gets the arguments after its flag.
# Its keys must be bootmark.ONE_OFF (main.py skips the breadcrumb for those):
# tests/test_bootmark.py checks both, so add a new one-off command here, never as its
# own `if` in main().
def _discord_restore_cmd(rest):
    from soundboard.mic import discordtalk
    return discordtalk.cli(rest)


ONE_OFF_COMMANDS = {
    "--selftest": lambda rest: selftest(),
    "--get-tor": lambda rest: get_tor(),
    "--install-addon": lambda rest: install_addon(rest[0] if rest else ""),
    "--set-offline": lambda rest: set_offline(),
    "--keep-netlog": lambda rest: keep_netlog(),
    "--usage-count": _usage_count_cmd,
    "--uninstall-count": lambda rest: uninstall_count(),
    "--selftest-addon": _selftest_addon_cmd,
    "--discord-restore": _discord_restore_cmd,
    "--quit-running": lambda rest: quit_running(),
}


def main():
    for stream in (sys.stdout, sys.stderr):   # a path with emoji or Cyrillic in it, sent
        if stream is not None and hasattr(stream, "reconfigure"):   # to a file or pipe,
            stream.reconfigure(errors="replace")   # pyright: ignore[reportAttributeAccessIssue]  # hasattr
    for flag, run in ONE_OFF_COMMANDS.items():   # first match wins, in this order
        if flag in sys.argv:
            sys.exit(run(sys.argv[sys.argv.index(flag) + 1:]))
    from soundboard.core import bootmark, earlystart, exitwatch, threadnames
    threadnames.install()   # first: every thread after this has its name in Windows too
    migrate_from_soundboard()
    last_run = earlystart.last_run   # main.py's early loading screen read it, then armed
    if last_run is None:
        last_run = exitwatch.read_last(APP_DIR)   # the last run's black box, before arming wipes it
    log_path = applog.setup(APP_DIR)
    applog.install_hooks(log_path, __version__)
    if earlystart.last_run is None:
        exitwatch.arm_early(APP_DIR)   # faulthandler on before the window is built (native crashes)
    from soundboard.sounds.library import MIGRATION_ERRORS
    for msg in MIGRATION_ERRORS:
        log.error("%s", msg)
    tune_runtime_for_audio()
    from soundboard.online import ytworker
    ytworker.enabled = True   # web searches and downloads off the audio's GIL
    from soundboard.audio import renderworker
    renderworker.enabled = True   # slow effects renders (an AI voice) too
    from soundboard import i18n
    i18n.startup(APP_DIR)   # before any window or module-level text is made
    import threading
    threading.Thread(target=clean_temp_leftovers, daemon=True, name="temp-clean").start()
    if earlystart.up():   # main.py made the QApplication for the early loading screen
        log.info("interface size: %d%% (loading screen up early)", earlystart.scale)
    else:
        earlystart.app_id()
        ui_scale_startup(APP_DIR)
    made = QApplication.instance()   # by main.py, for the early loading screen
    app = made if isinstance(made, QApplication) else QApplication(sys.argv)
    if i18n.is_rtl():   # Arabic: the whole app mirrored, add-on tabs included
        from PySide6.QtCore import Qt as _Qt
        app.setLayoutDirection(_Qt.LayoutDirection.RightToLeft)
    from soundboard.ui.kit import theme as _theme
    i18n.use_fonts(_theme.font_families())
    # same-width digits everywhere, so a number that changes doesn't make its text jump
    from PySide6.QtGui import QFont as _QFont
    _font = app.font()
    _font.setFeature(_QFont.Tag("tnum"), 1)
    app.setFont(_font)
    i18n.translate_qt_buttons(app)   # OK, Cancel, Yes… in Qt's own dialogs
    from soundboard.ui.kit import quietbox
    quietbox.install(app)   # no Windows ding from tips and warnings
    from soundboard.ui.kit import modals
    modals.install(app)   # dialogs: no white flash, a click outside closes them
    from soundboard.ui.kit.widgets import install_click_focus
    install_click_focus(app)   # a click leaves no focus ring: that's for the keyboard
    from soundboard.ui.kit import weblinks
    weblinks.install()   # links open the browser without the relay's proxy settings
    applog.ui_ready()
    if "--restart-after" in sys.argv:   # restarted by the app (Settings > Reset)
        wait_for_exit(sys.argv[sys.argv.index("--restart-after") + 1:][:1])
    # (taken in main.py for the early loading screen: the lock is this copy's)
    if not earlystart.locked() and not claim_single_instance():
        log.info("another Onion Board is running; asked it to come to the front")
        bootmark.clear(APP_DIR)   # a normal end, not a start that failed
        sys.exit(0)
    register_restart()   # only the copy that runs: a second launch just exits
    # listen at once, not after the ~1 s of imports below: a second launch meanwhile
    # would otherwise find nobody answering (the window is looked up when asked)
    holder = {}
    server = listen_for_second_launch(app, lambda: holder.get("w"))
    app.instance_server = server   # pyright: ignore[reportAttributeAccessIssue]  # kept alive on the app
    from soundboard.core.autostart import TRAY_ARG
    from soundboard.ui.bun import splash
    # a cold start can take seconds: show Bun meanwhile (from main.py, he's up already)
    if TRAY_ARG not in sys.argv and not earlystart.shown():
        bootmark.watch_stall(APP_DIR)   # a slow one writes down where it waited
        splash.show()
    from soundboard.online import ffmpegget
    ffmpegget.start_check()   # meanwhile: is FFmpeg there and does it start? (never waited on)
    from soundboard.ui.kit.wheelguard import AppStyle
    app.setStyle(AppStyle("Fusion"))   # also: the wheel never changes a dropdown or tab
    from soundboard.ui.kit import a11y
    a11y.install(app)   # screen-reader names for icon-only controls, as focus moves
    from soundboard.ui.kit import numberbox
    numberbox.install(app)   # a typed number counts without Enter; Enter presses no button
    from soundboard.ui.kit import theme
    app.setWindowIcon(theme.app_icon())   # every window, and the taskbar button

    from soundboard.core import reset
    reset_note = reset.run_pending()   # a reset / restore asked for: before the settings load
    from soundboard.ui.window.mainwindow import MainWindow  # after the QApplication exists
    from soundboard.ui.window import invitecontrol
    try:
        w = holder["w"] = MainWindow()
    except Exception:  # noqa: BLE001 - tell the user why nothing appeared, then quit
        splash.close()
        applog.report(where="starting up", fatal=True)   # saved and counted as error/
        bootmark.clear(APP_DIR)   # that report is the trace: not a silent start failure
        sys.exit(1)
    # Windows logging off / shutting down while the window is hidden in the tray never
    # calls closeEvent: still let go of push-to-talk and save the settings
    app.aboutToQuit.connect(w.shutdown)
    from soundboard.core import updates, usage
    unclean = usage.mark_running(APP_DIR)   # the last run ended without closing itself?
    usage.started(w.cfg)   # this launch, and updated/<from>-to-<to> after an update
    if splash.rare():   # a rare loading screen came up (Golden Bun and the rest)
        usage.used(f"splash-{splash.rare()}")
    failed_ver, failed_pid = bootmark.previous()   # a start that never got this far
    failed_at = bootmark.previous_at()
    bootmark.clear(APP_DIR)   # running.txt (just written) is the marker from here on
    if unclean:   # work out why (Windows' log, the native-crash stacks) off this thread
        def why(unclean=unclean):
            try:
                event, _path = exitwatch.check_last(APP_DIR, *last_run, unclean)
            except Exception:  # noqa: BLE001 - still count it, without the why
                log.warning("couldn't tell why the last run ended", exc_info=True)
                event = unclean
            if event:   # "": Windows or a power cut ended it, not the app's problem
                usage.note(event)
        threading.Thread(target=why, daemon=True, name="last-exit").start()
    elif failed_ver:   # died while loading, before running.txt or the window existed
        native = last_run[1]
        def why_failed(ver=failed_ver, pid=failed_pid, native=native, at=failed_at):
            try:
                usage.note(usage.startup_failed(APP_DIR, ver, pid, native, at))
            except Exception:  # noqa: BLE001 - still count it, without the why
                log.warning("couldn't tell why the last start failed", exc_info=True)
                usage.note(f"startup-failed/{ver}")
        threading.Thread(target=why_failed, daemon=True, name="last-start").start()
    exitwatch.start(APP_DIR, lambda: (  # for the next start
        hw.stuck() if (hw := getattr(app, "hangwatch", None)) is not None else 0.0))
    # a newer version: downloaded and installed behind the loading screen, and the
    # installer opens the new one (not started with Windows into the tray: no splash)
    updating = TRAY_ARG not in sys.argv and w.updctl.update_at_start()
    show = (not (TRAY_ARG in sys.argv and w.can_hide())   # started with Windows: tray only
            or server.show_requested)    # ...unless launched again since
    if updating:
        show = False
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: (w.quit_app(), app.quit()))   # (never shown)
    if TRAY_ARG not in sys.argv and not updating:   # Bun is up: the sounds load behind it
        wait_for_sounds(app, w)
        w.setctl.preload_dialogs()   # Settings and Edit sound, built behind it too
    elif not updating:   # started with Windows into the tray: no loading screen to hide
        from PySide6.QtCore import QTimer   # them behind, so a while after sign-in
        QTimer.singleShot(TRAY_PRELOAD_MS, w.setctl.preload_dialogs)
    if show and not w.bunctl.start_as_bun():   # quit as Bun last time: Bun, not the window
        if not w.cfg.setup_done:
            w.setup_backdrop()   # the first launch: the guide's backdrop from the first frame
        w.show()
        if TRAY_ARG not in sys.argv:
            first_paint(app, w)
            w.setctl.warm_settings()
            w.setctl.warm_triggers()
        if comes_to_front(sys.argv, server.show_requested):
            bring_to_front(w)   # the splash never takes the focus: take it now
    splash.close(goodbye=bool(show))   # Bun waves as the window comes up
    took, stall = bootmark.stop_stall()
    if stall is not None:
        log.warning("slow start: %.0f s before the window was up; where it waited is in %s",
                    took, stall.name)
    from PySide6.QtCore import QTimer
    if "--resume-setup" in sys.argv:   # back after the restart the cable asked for
        QTimer.singleShot(400, lambda: w.run_setup(resumed=True))
    elif not w.cfg.setup_done:   # first launch: the setup wizard
        QTimer.singleShot(400, w.run_setup)
    if unclean and RESTARTED_ARG in sys.argv:   # Windows started it again after a crash
        from soundboard.i18n import _
        from soundboard.core import usage
        usage.used("crash-restarted")
        QTimer.singleShot(900, lambda: w.toast(
            _("Onion Board closed unexpectedly, so it started again."), "warn"))
    if reset_note:
        QTimer.singleShot(900, lambda: w.toast(reset_note, "ok" if reset.last_ok else "warn"))
    QTimer.singleShot(30_000, lambda: start_ytdlp_check(w.cfg))
    # old add-on copies: once the add-ons are loaded (so the ones in use are known)
    QTimer.singleShot(20_000, lambda: threading.Thread(
        target=modules_prune, daemon=True, name="addon-leftovers").start())
    QTimer.singleShot(25_000, lambda: threading.Thread(
        target=packs_dedupe, daemon=True, name="pack-dupes").start())
    if "--resume-setup" not in sys.argv and w.cfg.setup_done:
        # the installer's "from Soundpad" box; with the setup guide up, run_setup
        # starts it once the guide is closed
        QTimer.singleShot(500, w.impctl.import_queued)
        QTimer.singleShot(700, lambda: invitecontrol.welcome(w))   # "{name} invited you"
        QTimer.singleShot(LITE_HINT_MS, w.themectl.suggest_lite)   # a slower PC: once
    QTimer.singleShot(600, w.updctl.after_update)   # "Updated to …" after an update restarted it
    # new versions (updates.py): unless unticked, as it starts (what that finds installs
    # itself) and then at most every hour (updates.EVERY_S), also for an app left
    # running for days
    # (already asked behind the loading screen: its answer went to the card)
    QTimer.singleShot(8_000, lambda: w.updctl.start_checked
                      or w.updctl.check_updates(launch=True))
    QTimer.singleShot(60_000, w.send_usage)   # the anonymous daily count (usage.py)
    w.tick_usage()   # how long it's open, for the daily count: from now
    open_timer = QTimer(w)
    open_timer.timeout.connect(w.tick_usage)
    open_timer.start(usage.OPEN_TICK_S * 1000)
    update_timer = QTimer(w)
    update_timer.timeout.connect(w.updctl.check_updates)
    update_timer.start(updates.EVERY_S * 1000)
    recheck = QTimer(w)
    recheck.timeout.connect(w.send_usage)
    recheck.start(6 * 3600 * 1000)
    # a bug saved mid-run (no window pops up for it, applog.py): its count goes out a
    # minute later, a burst of them in one send, not at the next start
    problem_send = QTimer(w)
    problem_send.setSingleShot(True)
    problem_send.setInterval(60_000)
    problem_send.timeout.connect(w.send_usage)
    applog.on_problem(lambda _rep: problem_send.isActive() or problem_send.start())
    from soundboard.core.hangwatch import HangWatch
    # a frozen window gets its stack logged
    app.hangwatch = HangWatch(parent=app)   # pyright: ignore[reportAttributeAccessIssue]  # kept alive on the app
    from soundboard.core.uigc import UiCollector
    # garbage collection on this thread only
    app.collector = UiCollector(parent=app, quiet=w.engine.quiet)   # pyright: ignore[reportAttributeAccessIssue]  # kept alive on the app
    code = app.exec()
    # w.shutdown already ran (aboutToQuit). Python's own teardown after this -- Qt,
    # the web view, COM, audio objects -- can hang with the window gone, leaving an
    # invisible copy that still holds the single-instance lock, so every new launch
    # says "already running". Nothing left needs it: flush the log and end here.
    logging.shutdown()
    end_process(code)
