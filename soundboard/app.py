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


def tune_runtime_for_audio():
    """Two cheap knobs that keep the audio callbacks from waiting on the UI thread.

    The interpreter lets a thread hold the GIL for 5 ms before forcing a switch; a
    WASAPI callback at low latency has about 10 ms to produce its block, so a 5 ms
    wait is half its budget. 1 ms leaves the UI slightly less efficient and the
    audio thread almost never waiting.

    The garbage collector's gen-0 threshold is 700 allocations; numpy blocks in
    the callbacks are Python objects, so every few blocks a collection ran *on the
    audio thread*. Raising the threshold makes collections rarer (and they still
    run mostly on the UI thread, where a pause costs nothing).
    """
    sys.setswitchinterval(0.001)
    gc.set_threshold(50_000, 20, 20)


def start_ytdlp_check(cfg):
    """The daily "is there a newer yt-dlp?" check, off the UI thread (see ytdl.py)."""
    import threading

    from soundboard import ytdl
    threading.Thread(target=ytdl.auto_update, args=(cfg.ytdlp_auto_optin,), daemon=True,
                     name="ytdlp-update").start()


def selftest() -> int:
    """`OnionBoard.exe --selftest`: prove a (pruned) build can load everything it
    ships, without a window, a device, a hotkey or a network request. build.ps1
    runs it after trimming Qt (scripts/prune_build.py), so a missing DLL fails the
    build instead of a user's first launch. Prints OK and returns 0."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--mute-audio --disable-gpu")
    # scipy: the app itself doesn't use it any more, but add-ons may (build.ps1)
    for mod in ("numpy", "scipy.signal", "sounddevice", "soundfile", "soxr", "yt_dlp"):
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
    mons = sys.modules[f"{pkg}.screenwatch"].monitors()
    tab.shutdown()
    print(f"OK: Onion Watch {info.version} runs in Onion Board {__version__} "
          f"({len(wins)} windows, {len(mons)} screens seen)")
    return 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--get-tor" in sys.argv:
        sys.exit(get_tor())
    if "--set-offline" in sys.argv:
        sys.exit(set_offline())
    if "--selftest-addon" in sys.argv:
        sys.exit(selftest_addon(sys.argv[sys.argv.index("--selftest-addon") + 1]))
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
    applog.ui_ready()
    if not claim_single_instance():
        log.info("another Onion Board is running; asked it to come to the front")
        sys.exit(0)
    # listen at once, not after the ~1 s of imports below: a second launch meanwhile
    # would otherwise find nobody answering (the window is looked up when asked)
    holder = {}
    app.instance_server = listen_for_second_launch(app, lambda: holder.get("w"))  # kept alive
    app.setStyle("Fusion")
    from soundboard.ui import a11y
    a11y.install(app)   # screen-reader names for icon-only controls, as focus moves
    from soundboard import theme
    app.setWindowIcon(theme.app_icon())   # every window, and the taskbar button

    from soundboard.ui.mainwindow import MainWindow   # after the QApplication exists
    try:
        w = holder["w"] = MainWindow()
    except Exception:  # noqa: BLE001 - tell the user why nothing appeared, then quit
        applog.report(where="starting up", fatal=True)
        sys.exit(1)
    # Windows logging off / shutting down while the window is hidden in the tray never
    # calls closeEvent: still let go of push-to-talk and save the settings
    app.aboutToQuit.connect(w.shutdown)
    from soundboard.autostart import TRAY_ARG
    if (not (TRAY_ARG in sys.argv and w.can_hide())   # started with Windows: tray only
            or app.instance_server.show_requested):    # ...unless launched again since
        w.show()
    from PySide6.QtCore import QTimer
    if "--resume-setup" in sys.argv:   # back after the restart the cable asked for
        QTimer.singleShot(400, lambda: w.run_setup(resumed=True))
    elif not w.cfg.setup_done:   # first launch: walk them through mic, headphones, cable
        QTimer.singleShot(400, w.run_setup)
    QTimer.singleShot(30_000, lambda: start_ytdlp_check(w.cfg))
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
    os._exit(code)
