"""Application entry point: logging, runtime tuning, single instance, the window."""
from __future__ import annotations

import ctypes
import gc
import logging
import os
import subprocess
import sys

# (Up to 1.9.6 QT_WIDGETS_RHI=1 was set here so the Radio tab's 3D globe could show
# without rebuilding the window. It gave every window its own Direct3D device, 16
# driver threads and ~30 MB each, never freed; the globe is gone and windows draw
# the ordinary way again.)
from PySide6.QtWidgets import QApplication

from soundboard import __version__, applog
from soundboard.library import APP_DIR, migrate_from_soundboard
from soundboard.singleinstance import claim_single_instance, listen_for_second_launch

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
    audio thread*. Raising the threshold makes collections rarer, and main() then
    runs them on the UI thread only (uigc.UiCollector), where a pause costs nothing.
    """
    sys.setswitchinterval(SWITCH_S)
    gc.set_threshold(50_000, 20, 20)


RESTART_ONLY_FOR_UPDATES = 1 | 2 | 8   # RESTART_NO_CRASH | NO_HANG | NO_REBOOT


def restart_cmdline(argv: list[str], frozen: bool) -> str:
    """What Windows starts the app again with after an installer closed it: the same
    arguments, minus the one-off ones (as in MainWindow.restart_app), and with the
    window shown: it was most likely open, and coming back hidden looks like it's gone."""
    from soundboard.autostart import TRAY_ARG
    args = list(argv[1:] if frozen else argv)
    if not frozen and args:   # python main.py: the script by full path, any cwd works
        args[0] = os.path.abspath(args[0])
    if "--restart-after" in args:
        i = args.index("--restart-after")
        del args[i:i + 2]
    args = [a for a in args if a not in (TRAY_ARG, "--resume-setup")]
    return subprocess.list2cmdline(args)


def register_restart():
    """Ask Windows to start the app again when an installer closes it to update it
    (Inno Setup's CloseApplications restarts the apps that asked: an update or a
    reinstall run while the app was open used to leave it closed, which looked like a
    crash). Not after a crash, a hang or a reboot."""
    try:
        ctypes.windll.kernel32.RegisterApplicationRestart(
            ctypes.c_wchar_p(restart_cmdline(sys.argv, getattr(sys, "frozen", False))),
            RESTART_ONLY_FOR_UPDATES)
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
# crashed) in the middle of, and an add-on self-test. Only these exact prefixes.
TEMP_LEFTOVERS = ("sb-ytdl-", "onionboard-selftest-")
TEMP_MAX_AGE_S = 24 * 3600


def clean_temp_leftovers(now: float | None = None) -> int:
    """Delete TEMP_LEFTOVERS folders in %TEMP% untouched for a day (a running
    download's is newer). Returns how many went. Run off the UI thread."""
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
                        or not p.is_dir() or now - p.stat().st_mtime < TEMP_MAX_AGE_S):
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


def start_ytdlp_check(cfg):
    """The daily "is there a newer yt-dlp?" check, off the UI thread (see ytdl.py)."""
    import threading

    from soundboard import netlog, ytdl
    netlog.cause(ytdl.UPDATE_FEATURE, "Automatic daily check for a newer downloader "
                                      "(yt-dlp), after start-up")
    threading.Thread(target=ytdl.auto_update, args=(cfg.ytdlp_auto_optin,), daemon=True,
                     name="ytdlp-update").start()


def selftest() -> int:
    """`OnionBoard.exe --selftest`: prove a (pruned) build can load everything it
    ships, without a window, a device, a hotkey or a network request. build.ps1
    runs it after trimming Qt (scripts/prune_build.py), so a missing DLL fails the
    build instead of a user's first launch. Prints OK and returns 0."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    # scipy.fft: the app itself doesn't use scipy, but Onion Watch's matcher does, and
    # build.ps1 ships only that part of it
    for mod in ("numpy", "scipy.fft", "sounddevice", "soundfile", "soxr", "yt_dlp"):
        __import__(mod)
    from PySide6.QtMultimedia import QMediaPlayer
    _app = QApplication(sys.argv)   # kept until the checks below have run
    from soundboard.ui import mainwindow, setupwizard, crashdialog  # noqa: F401
    from soundboard import engine, radio, theme  # noqa: F401
    theme.app_icon()
    QMediaPlayer()   # loads the FFmpeg multimedia plugin
    print(f"OK: Onion Board {__version__} self-test passed")
    return 0


def get_tor() -> int:
    """`OnionBoard.exe --get-tor`: the installer's "Private connection (Tor)" box.
    Downloads Tor into %APPDATA%\\OnionBoard\\tor\\bin (soundboard.torget, the same
    routine as Settings' Get Tor button) the way the saved Connection setting says, so
    a proxy set there is used. No window. Returns 0 when Tor is there (already, or
    now), 1 if it couldn't be got."""
    applog.setup(APP_DIR)
    from soundboard import library, net, tor, torget
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


def set_offline() -> int:
    """`OnionBoard.exe --set-offline`: the installer's "Offline mode" box (or
    /OFFLINE=1). Switches on Offline mode in config.json before the app's first start,
    so it never goes online, not even once. Other settings are kept; nothing
    connects. No window. Returns 0 once it's saved, 1 if it couldn't be."""
    migrate_from_soundboard()   # an old %APPDATA%\Soundboard moves only while there's no config
    applog.setup(APP_DIR)
    from soundboard import library
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
    """`OnionBoard.exe --keep-netlog`: the installer's "Keep a history of network
    activity" box (or /KEEPNETLOG=1). Switches on netlog_keep in config.json before
    the app's first start, so its first connections are kept too. Other settings are
    kept; nothing connects. No window. Returns 0 once it's saved, 1 if it couldn't be."""
    migrate_from_soundboard()
    applog.setup(APP_DIR)
    from soundboard import library
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
    config.json before the app's first start, so it never sends one; on takes it out
    (only a box the user saw: a silent update never passes on). `heard` is the
    installer's "Where did you hear about Onion Board?", kept for the first-start
    event. Other settings are kept; nothing connects. No window. Returns 0 once it's
    saved, 1 if it couldn't be."""
    migrate_from_soundboard()
    applog.setup(APP_DIR)
    from soundboard import library
    cfg = library.Config.load()
    if cfg.read_only:
        print("FAIL: config.json is locked by another program", file=sys.stderr)
        return 1
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
        from soundboard import library, net, usage
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

    from soundboard import modules, theme
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
    for sub in ("ui.windowpicker", "ui.snip", "windows", "screenwatch"):   # the lazy ones
        importlib.import_module(f"{pkg}.{sub}")
    wins = sys.modules[f"{pkg}.windows"].list_windows()
    sw = sys.modules[f"{pkg}.screenwatch"]
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
    ops = sys.modules.get(f"{pkg}.imgops")
    fft = "?" if ops is None else ("scipy.fft" if ops._sfft is not None else "numpy")
    print(f"OK: Onion Watch {info.version} runs in Onion Board {__version__} "
          f"({len(wins)} windows, {len(mons)} screens seen, matching with {fft} FFTs)")
    return 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--get-tor" in sys.argv:
        sys.exit(get_tor())
    if "--set-offline" in sys.argv:
        sys.exit(set_offline())
    if "--keep-netlog" in sys.argv:
        sys.exit(keep_netlog())
    if "--usage-count" in sys.argv:
        i = sys.argv.index("--usage-count")
        j = sys.argv.index("--heard-from") if "--heard-from" in sys.argv else -1
        heard = sys.argv[j + 1] if 0 <= j < len(sys.argv) - 1 else ""
        sys.exit(set_usage_count(sys.argv[i + 1:i + 2] == ["on"], heard))
    if "--uninstall-count" in sys.argv:
        sys.exit(uninstall_count())
    if "--selftest-addon" in sys.argv:
        try:
            sys.exit(selftest_addon(sys.argv[sys.argv.index("--selftest-addon") + 1]))
        except Exception as e:  # noqa: BLE001 - a FAILED line, not the frozen exe's error box
            print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(1)
    migrate_from_soundboard()
    log_path = applog.setup(APP_DIR)
    applog.install_hooks(log_path, __version__)
    from soundboard.library import MIGRATION_ERRORS
    for msg in MIGRATION_ERRORS:
        log.error("%s", msg)
    tune_runtime_for_audio()
    from soundboard import i18n
    i18n.startup(APP_DIR)   # before any window or module-level text is made
    import threading
    threading.Thread(target=clean_temp_leftovers, daemon=True, name="temp-clean").start()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OnionBoard.App")
    except Exception:  # noqa: BLE001
        log.debug("SetCurrentProcessExplicitAppUserModelID failed", exc_info=True)
    app = QApplication(sys.argv)
    from soundboard.ui import quietbox
    quietbox.install(app)   # no Windows ding from tips and warnings
    applog.ui_ready()
    if "--restart-after" in sys.argv:   # restarted by the app (Settings > Reset)
        wait_for_exit(sys.argv[sys.argv.index("--restart-after") + 1:][:1])
    if not claim_single_instance():
        log.info("another Onion Board is running; asked it to come to the front")
        sys.exit(0)
    register_restart()   # only the copy that runs: a second launch just exits
    # listen at once, not after the ~1 s of imports below: a second launch meanwhile
    # would otherwise find nobody answering (the window is looked up when asked)
    holder = {}
    app.instance_server = listen_for_second_launch(app, lambda: holder.get("w"))  # kept alive
    from soundboard.autostart import TRAY_ARG
    from soundboard.ui import splash
    if TRAY_ARG not in sys.argv:   # a cold start can take seconds: show Bun meanwhile
        splash.show()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QProxyStyle, QStyle

    class _Style(QProxyStyle):
        """Fusion, but a click anywhere on a slider's bar moves it there (not a page
        step towards it), on every slider in the app."""

        def styleHint(self, hint, opt=None, widget=None, ret=None):
            if hint == QStyle.SH_Slider_AbsoluteSetButtons:
                return Qt.LeftButton.value
            return super().styleHint(hint, opt, widget, ret)

    app.setStyle(_Style("Fusion"))
    from soundboard.ui import a11y
    a11y.install(app)   # screen-reader names for icon-only controls, as focus moves
    from soundboard import theme
    app.setWindowIcon(theme.app_icon())   # every window, and the taskbar button

    from soundboard import reset
    reset_note = reset.run_pending()   # a reset / restore asked for: before the settings load
    from soundboard.ui.mainwindow import MainWindow   # after the QApplication exists
    try:
        w = holder["w"] = MainWindow()
    except Exception:  # noqa: BLE001 - tell the user why nothing appeared, then quit
        splash.close()
        applog.report(where="starting up", fatal=True)
        sys.exit(1)
    # Windows logging off / shutting down while the window is hidden in the tray never
    # calls closeEvent: still let go of push-to-talk and save the settings
    app.aboutToQuit.connect(w.shutdown)
    from soundboard import usage
    usage.note(usage.mark_running(APP_DIR))   # the last run ended without closing itself?
    if (not (TRAY_ARG in sys.argv and w.can_hide())   # started with Windows: tray only
            or app.instance_server.show_requested):    # ...unless launched again since
        w.show()
    splash.close()
    from PySide6.QtCore import QTimer
    if "--resume-setup" in sys.argv:   # back after the restart the cable asked for
        QTimer.singleShot(400, lambda: w.run_setup(resumed=True))
    elif not w.cfg.setup_done:   # first launch: the setup wizard
        QTimer.singleShot(400, w.run_setup)
    if reset_note:
        QTimer.singleShot(900, lambda: w.toast(reset_note, "warn" if "Couldn't" in reset_note
                                               else "ok"))
    QTimer.singleShot(30_000, lambda: start_ytdlp_check(w.cfg))
    QTimer.singleShot(500, w.import_queued)   # the installer's "from Soundpad" box
    QTimer.singleShot(600, w.after_update)   # "Updated to …" after an update restarted it
    # new versions (updates.py): unless unticked, at most every 6 hours, also for an app
    # left running for days
    QTimer.singleShot(45_000, w.check_updates)
    QTimer.singleShot(60_000, w.send_usage)   # the anonymous daily count (usage.py)
    recheck = QTimer(w)
    recheck.timeout.connect(w.check_updates)
    recheck.timeout.connect(w.send_usage)
    recheck.start(6 * 3600 * 1000)
    from soundboard.hangwatch import HangWatch
    app.hangwatch = HangWatch(parent=app)   # a frozen window gets its stack logged
    from soundboard.uigc import UiCollector
    app.collector = UiCollector(parent=app)  # garbage collection on this thread only
    code = app.exec()
    # w.shutdown already ran (aboutToQuit). Python's own teardown after this -- Qt,
    # the web view, COM, audio objects -- can hang with the window gone, leaving an
    # invisible copy that still holds the single-instance lock, so every new launch
    # says "already running". Nothing left needs it: flush the log and end here.
    logging.shutdown()
    end_process(code)
