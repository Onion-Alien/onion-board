"""Application entry point: logging, runtime tuning, single instance, the window."""
from __future__ import annotations

import ctypes
import gc
import logging
import os
import sys

# Render the window through the GPU from the start. The Radio tab's globe needs a GPU
# surface; without this, opening it the first time makes Qt destroy and rebuild the
# whole native window, which looks like the app closing and reopening.
# (Must be set before the QApplication exists. QT_WIDGETS_RHI=0 is the escape hatch
# on a machine whose GPU driver or remote-desktop session can't do it.)
os.environ.setdefault("QT_WIDGETS_RHI", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from soundboard import __version__, applog  # noqa: E402
from soundboard.library import APP_DIR, migrate_from_soundboard  # noqa: E402
from soundboard.singleinstance import claim_single_instance, listen_for_second_launch  # noqa: E402

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
    audio thread*. Raising the threshold makes collections rarer (and they still
    run mostly on the UI thread, where a pause costs nothing).
    """
    sys.setswitchinterval(SWITCH_S)
    gc.set_threshold(50_000, 20, 20)


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
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--mute-audio --disable-gpu")
    # scipy.fft: the app itself doesn't use scipy, but Onion Watch's matcher does, and
    # build.ps1 ships only that part of it
    for mod in ("numpy", "scipy.fft", "sounddevice", "soundfile", "soxr", "yt_dlp"):
        __import__(mod)
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _app = QApplication(sys.argv)   # kept until the loop below has run
    from soundboard.ui import mainwindow, setupwizard, crashdialog  # noqa: F401
    from soundboard import engine, radio, theme  # noqa: F401
    theme.app_icon()
    QMediaPlayer()   # loads the FFmpeg multimedia plugin
    view = QWebEngineView()   # starts Chromium: resources, locale, the helper exe
    loop = QEventLoop()
    result = {}
    view.loadFinished.connect(lambda ok: (result.__setitem__("ok", ok), loop.quit()))
    QTimer.singleShot(30_000, loop.quit)
    view.setHtml("<html><body><script>document.title='ready'</script></body></html>")
    loop.exec()
    if not result.get("ok"):
        print("FAIL: the web engine didn't load a page", file=sys.stderr)
        return 1
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


def selftest_addon(path: str) -> int:
    """`OnionBoard.exe --selftest-addon OnionWatch-module.zip`: prove this build can
    run the Onion Watch add-on (it has no pip, so the add-on may only use what the
    build ships). Installs the zip into a temp folder, loads it the way the Triggers
    tab does, builds its tab on a stand-in board, and lists windows and screens with
    it. No window, no device, no network. Prints OK and returns 0."""
    import importlib
    import tempfile
    from pathlib import Path
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    _app = QApplication(sys.argv)   # noqa: F841 - kept while the tab is built
    from soundboard import modules, theme
    tmp = Path(tempfile.mkdtemp(prefix="onionboard-selftest-"))
    info = modules.install_zip(Path(path), "onion-watch", "triggers", tmp / "modules")
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
    # new versions (updates.py): unless unticked, at most once a day, also for an app
    # left running for days
    QTimer.singleShot(45_000, w.check_updates)
    recheck = QTimer(w)
    recheck.timeout.connect(w.check_updates)
    recheck.start(6 * 3600 * 1000)
    from soundboard.hangwatch import HangWatch
    app.hangwatch = HangWatch(parent=app)   # a frozen window gets its stack logged
    code = app.exec()
    # w.shutdown already ran (aboutToQuit). Python's own teardown after this -- Qt,
    # the web view, COM, audio objects -- can hang with the window gone, leaving an
    # invisible copy that still holds the single-instance lock, so every new launch
    # says "already running". Nothing left needs it: flush the log and end here.
    logging.shutdown()
    end_process(code)
