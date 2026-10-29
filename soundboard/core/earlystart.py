"""The loading screen as early as it can come: called by main.py right after the start-up
breadcrumb, before app.py and its heavy imports (the sound library, numpy, soundfile,
the window's modules: about 0.6 s of a start, more on a cold one) and before the setup
app.main() does ahead of the window. Until Bun showed, nothing was on screen for a second
or two, and people launched the app a second time.

Only the copy that's going to run shows him: it takes the single-instance lock first
(singleinstance.take_lock, no Qt). A second launch finds the lock taken, shows nothing
and goes on as before: app.main() asks the running copy to come to the front.

Not for a start with Windows (--tray: no loading screen at all) or a restart (--restart-
after: the old copy still holds the lock until it has quit). Anything going wrong here
leaves it to app.main(), which puts the loading screen up later, as it always did.
"""
from __future__ import annotations

import json
import logging
import os
import sys

log = logging.getLogger(__name__)

# sounds/config.py's UI_SCALES (Settings > Appearance > Interface size), spelled out so
# this needs nothing of the sound library; tests/test_earlystart.py keeps them the same
UI_SCALES = (80, 90, 100, 110, 125, 150)

_locked = False   # this copy took the single-instance lock here
_app = False      # ...and made the QApplication (language, interface size set before it)
scale = 100       # the interface size set for this run, for app.main() to log
last_run = None   # exitwatch.read_last's answer, read before arming faulthandler here


def locked() -> bool:
    """show() took the single-instance lock: this copy is the one that runs."""
    return _locked


def up() -> bool:
    """show() made the QApplication: the language, the interface size, the taskbar's
    ID, faulthandler and the thread names are set already."""
    return _app


def show(argv: list[str], app_dir) -> bool:
    """Bun on screen now, if this copy is the one that runs. True when he is."""
    global _locked, _app, scale, last_run
    from soundboard.core.autostart import TRAY_ARG   # (small: no Qt)
    if TRAY_ARG in argv or "--restart-after" in argv:
        return False
    try:
        from soundboard.sounds import paths
        if paths.OLD_APP_DIR.is_dir() and not paths.CONFIG_PATH.exists():
            return False   # settings still in the old Soundboard folder: app.main() moves them
        from soundboard.core import singleinstance
        if not singleinstance.take_lock():
            return False   # another copy runs: app.main() brings it to the front
        _locked = True
        from soundboard.core import exitwatch, threadnames
        threadnames.install()   # first: every thread after this has its name in Windows too
        last_run = exitwatch.read_last(app_dir)   # the last run's black box, before arming
        exitwatch.arm_early(app_dir)   # a native crash while Qt loads: native-crash.txt
        from soundboard import i18n
        i18n.startup(app_dir)   # "Starting…" in the user's language
        scale = interface_size(app_dir)
        app_id()
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(argv)
        _app = True
        if i18n.is_rtl():
            from PySide6.QtCore import Qt
            app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        from soundboard.core import bootmark
        from soundboard.ui.bun import splash
        bootmark.watch_stall(app_dir)   # a slow one writes down where it waited
        splash.show()
        return True
    except Exception:  # noqa: BLE001 - app.main() shows it later instead
        log.debug("early loading screen failed", exc_info=True)
        return False


def shown() -> bool:
    """The loading screen itself is up (not only the lock taken)."""
    if not _app:
        return False
    splash = sys.modules.get("soundboard.ui.bun.splash")
    return splash is not None and splash._splash is not None


def interface_size(app_dir) -> int:
    """Size the whole interface by config.json's `ui_scale`: Qt can only scale before the
    QApplication is made, so a change shows after a restart. QT_SCALE_FACTOR set from
    outside wins (scripts, tests)."""
    if "QT_SCALE_FACTOR" in os.environ:
        return 100
    try:
        raw = json.loads((app_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 100
    pct = raw.get("ui_scale", 100) if isinstance(raw, dict) else 100
    if pct not in UI_SCALES or isinstance(pct, bool):
        return 100
    if pct != 100:
        os.environ["QT_SCALE_FACTOR"] = str(pct / 100)
    return pct


def app_id() -> None:
    """The taskbar button's identity, before any window: the shortcuts' AppUserModelID."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OnionBoard.App")
    except Exception:  # noqa: BLE001
        log.debug("SetCurrentProcessExplicitAppUserModelID failed", exc_info=True)
