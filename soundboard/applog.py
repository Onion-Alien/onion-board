"""Logging and crash reporting.

The app runs under pythonw.exe, so there is no console: without this, every
traceback, Qt warning and swallowed error simply vanishes. Everything goes to a
small rotating log in the app folder, unless "Keep an app log" is off (Settings >
Connection, config app_log): then the lines are kept in memory only, for a crash
report's log excerpt, and gone when the app closes (see keep()).

Any unhandled exception — on the UI thread, in a worker thread, or reported by
code that caught something it didn't expect (`report()`) — is logged, saved as a
crash report (`crash-reports\\`, personal paths scrubbed) and shown in a dialog
that asks the user to send that report to the developer. Nothing is ever sent
automatically: the dialog copies the report and opens the issue page, and the
user decides what to post.

Set ONIONBOARD_DEBUG=1 to log at DEBUG level.
"""
from __future__ import annotations

import collections
import errno
import json
import logging
import logging.handlers
import os
import platform
import queue
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

LOG_NAME = "onionboard.log"
REPORTS_DIR = "crash-reports"
KEEP_REPORTS = 10
LOG_TAIL_LINES = 60
MAX_DIALOGS = 3   # per run: a bug that fires every frame mustn't bury the user in popups
MAX_EXTRA = 20    # later errors listed on an open (or held-back) report
REPEAT_LOG_S = 60.0   # the same bug again: one short log line a minute at most
FORMAT = "%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s"

log = logging.getLogger("crash")

_state = {"log_path": None, "version": "?", "dialogs": 0, "seen": set(), "open": None,
          "bridge": None, "pending": None, "saved": set(), "repeats": {}}


@dataclass
class Report:
    title: str                  # "ValueError: bad thing"
    text: str                   # the full, scrubbed report
    fatal: bool = False
    path: Path | None = None    # where it was saved, if it was
    extra: list[str] = field(default_factory=list)   # later errors while it was open


class _Memory(logging.Handler):
    """The last LOG_TAIL_LINES lines, in memory only: the log while "Keep an app log"
    is off, so a crash report still says what led up to it."""

    def __init__(self):
        super().__init__()
        self.lines: collections.deque[str] = collections.deque(maxlen=LOG_TAIL_LINES)

    def emit(self, record):
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)


def wanted(app_dir: Path) -> bool:
    """Is "Keep an app log" on in app_dir's config.json? (On unless it says false:
    setup() runs before the config is loaded, and for the installer's helper runs.)"""
    try:
        cfg = json.loads((app_dir / "config.json").read_text(encoding="utf-8"))
        return cfg.get("app_log", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def setup(app_dir: Path, keep_log: bool | None = None) -> Path:
    """Send all logging to app_dir/onionboard.log (3 x 1 MB), or to memory only while
    "Keep an app log" is off (keep_log; None: as config.json says). Returns the log
    path, written or not."""
    app_dir.mkdir(parents=True, exist_ok=True)
    path = app_dir / LOG_NAME
    level = logging.DEBUG if os.environ.get("ONIONBOARD_DEBUG") else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    _state["log_path"] = path
    root.addHandler(_handler(path, wanted(app_dir) if keep_log is None else keep_log))
    if sys.stderr is not None:   # a console is attached (python.exe): mirror there too
        root.addHandler(logging.StreamHandler(sys.stderr))
    return path


class _Background(logging.handlers.QueueHandler):
    """onionboard.log, written on its own thread. A log line from the UI thread used to
    wait for the disk: a slow one (or an antivirus scan of the log) froze the window
    for 5 s in a warning's flush. The line is formatted here, on the caller's thread
    (a traceback needs its frames), and only the writing is handed over."""

    FLUSH_S = 2.0   # flush() waits at most this long for the writer to catch up

    def __init__(self, path: Path):
        super().__init__(queue.Queue())
        self.file = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        self.file.setFormatter(logging.Formatter("%(message)s"))   # already formatted
        self.listener = logging.handlers.QueueListener(self.queue, self.file)
        self.listener.start()

    def flush(self):
        """Wait (a little) until every line so far is in the file: a crash report
        reads the log's tail, and a test reads the file."""
        q, end = self.queue, time.monotonic() + self.FLUSH_S
        with q.all_tasks_done:
            while q.unfinished_tasks and time.monotonic() < end:
                q.all_tasks_done.wait(0.05)
        self.file.flush()

    def close(self):
        if self.listener is not None:
            self.listener.stop()   # writes what's queued, then the thread ends
            self.listener = None
        self.file.close()
        super().close()


def _handler(path: Path, keep_log: bool) -> logging.Handler:
    h = _Background(path) if keep_log else _Memory()
    h.setFormatter(logging.Formatter(FORMAT))
    return h


def flush():
    """Everything logged so far is in onionboard.log (or as far as FLUSH_S allows)."""
    for h in logging.getLogger().handlers:
        h.flush()


def keeping() -> bool:
    return not any(isinstance(h, _Memory) for h in logging.getLogger().handlers)


def keep(on: bool) -> None:
    """Settings' "Keep an app log": switch between onionboard.log and memory only.
    Switching off deletes the log and its older copies; this run's lines so far stay
    in memory, for a crash report."""
    path = _state["log_path"]
    if path is None or on == keeping():
        return
    root = logging.getLogger()
    old = next(h for h in root.handlers
               if isinstance(h, (_Memory, _Background)))
    new = _handler(Path(path), on)
    if not on:
        new.lines.extend(_log_tail(path, LOG_TAIL_LINES).splitlines())
    root.addHandler(new)
    root.removeHandler(old)
    old.close()
    if not on:
        for f in (Path(path), *Path(path).parent.glob(LOG_NAME + ".*")):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                log.warning("couldn't delete %s", f.name)
    log.info("app log %s", "kept in onionboard.log" if on else "in memory only")


def install_hooks(log_path: Path, version: str):
    """Route unhandled exceptions (main thread, worker threads, `__del__`s) and Qt's
    own messages into the log; offer a crash report for the first two kinds."""
    _state["log_path"], _state["version"] = log_path, version
    log.info("Onion Board %s starting (python %s)", version, sys.version.split()[0])

    def excepthook(t, v, tb):
        if issubclass(t, KeyboardInterrupt):
            sys.__excepthook__(t, v, tb)
            return
        report((t, v, tb))

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        report((args.exc_type, args.exc_value, args.exc_traceback),
               where=f"background task '{name}'")

    def unraisable_hook(u):
        # Errors in __del__ / weakref callbacks / GC: log them, never interrupt the user.
        log.error("Ignored exception in %r", u.object,
                  exc_info=(u.exc_type, u.exc_value, u.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    sys.unraisablehook = unraisable_hook

    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:   # tests without Qt
        return
    qlog = logging.getLogger("qt")
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.DEBUG,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}

    def qt_handler(kind, _ctx, msg):
        qlog.log(levels.get(kind, logging.WARNING), "%s", msg)

    qInstallMessageHandler(qt_handler)


def ui_ready():
    """Call once on the UI thread after the QApplication exists: from then on an
    error on any thread can bring up the report dialog (it's marshalled here)."""
    from PySide6.QtCore import QObject, Qt, Signal

    class _Bridge(QObject):
        show = Signal(object)
        plain = Signal(object)

    bridge = _Bridge()
    bridge.show.connect(_show_dialog, Qt.ConnectionType.QueuedConnection)
    bridge.plain.connect(_show_plain, Qt.ConnectionType.QueuedConnection)
    _state["bridge"] = bridge
    # a report held back while another program was in front (see _show_dialog).
    # focusWindowChanged, not applicationStateChanged: that one fires before
    # activeWindow() is set, so the report would be held back again, forever.
    from PySide6.QtWidgets import QApplication
    QApplication.instance().focusWindowChanged.connect(_show_pending)


def report(exc_info=None, where: str = "", fatal: bool = False) -> Report | None:
    """Log an exception, save a scrubbed crash report and offer it to the user.

    Safe to call from any thread and from inside an `except` block (with no
    argument it reports the exception being handled). Returns the Report, or
    None if there was nothing to report (or it was the same bug again). Never raises."""
    try:
        if exc_info is None:
            exc_info = sys.exc_info()
        elif isinstance(exc_info, BaseException):
            exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
        t, v, tb = exc_info
        if t is None:
            return None
        sig = _signature(t, tb)
        if not fatal and _environmental(v):
            _plain(exc_info, where, sig)
            return None
        saved = _state.setdefault("saved", set())
        if not fatal and sig in saved:
            # a paint handler or timer can throw every frame: the first report has
            # it all, so skip the traceback, log tail and file for the rest
            _repeat(t, v, where, sig)
            return None
        saved.add(sig)
        log.critical("Unhandled exception%s", f" in {where}" if where else "", exc_info=exc_info)
        rep = build_report(exc_info, where, fatal)
        rep.path = _save(rep)
        if fatal or not _late_callback(v):
            _offer(rep, sig)
        return rep
    except Exception:  # noqa: BLE001 - the crash reporter must never crash
        try:
            log.exception("crash reporter failed")
        except Exception:  # noqa: BLE001
            pass
        return None


def _late_callback(v) -> bool:
    """A timer or signal reached a window that was already closed and freed ("Internal
    C++ object (...) already deleted"). Still a bug, so it's saved and counted like any
    other, but the window is gone and the user lost nothing: no dialog for it."""
    return isinstance(v, RuntimeError) and "already deleted" in str(v)


# Windows errors that are the PC's state, not a bug: in use (32, 33), access denied (5),
# drive not ready (21), disk full (112), path too long (206), file damaged (1392)
_ENV_WINERRORS = {5, 21, 32, 33, 112, 206, 1392}
_ENV_ERRNOS = {errno.ENOSPC, errno.EACCES, errno.EPERM, errno.EROFS, errno.ENAMETOOLONG}


def _environmental(v) -> bool:
    """The PC's situation rather than a bug in the app: a full disk, a file another
    program holds, access denied, no memory, the network down. Said in plain words
    (_plain), not as a crash report: there's nothing for the developer to fix, and it
    would count as an error/<version> problem."""
    import socket
    if isinstance(v, MemoryError):
        return True
    if isinstance(v, (TimeoutError, ConnectionError, socket.gaierror)):
        return True
    return isinstance(v, OSError) and (getattr(v, "winerror", None) in _ENV_WINERRORS
                                       or v.errno in _ENV_ERRNOS)


def _plain(exc_info, where: str, sig: tuple):
    """An environmental error (_environmental): logged, and said once in plain words
    while the app is in front. No crash report is saved."""
    t, v, _tb = exc_info
    plain_seen = _state.setdefault("plain_seen", set())
    if sig in plain_seen:
        _repeat(t, v, where, sig)
        return
    plain_seen.add(sig)
    log.warning("%s%s (the PC's situation, not a bug: said in plain words)", t.__name__,
                f" in {where}" if where else "", exc_info=exc_info)
    if threading.current_thread() is threading.main_thread():
        _show_plain(v)
    elif _state["bridge"] is not None:
        _state["bridge"].plain.emit(v)


def _show_plain(v):
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox

        from soundboard import errors
        if QApplication.instance() is None or not _app_in_front():
            return   # never over a game: the log has it
        box = QMessageBox(QMessageBox.Icon.Warning, "Onion Board", errors.plain(v),
                          QMessageBox.StandardButton.Ok, QApplication.activeWindow())
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        box.show()
        _state["plain_box"] = box
    except Exception:  # noqa: BLE001 - the crash reporter must never crash
        log.exception("couldn't show the problem")


def build_report(exc_info, where: str = "", fatal: bool = False) -> Report:
    t, v, tb = exc_info
    # scrub before cutting: a cut can split the home path so scrub() no longer sees it
    title = scrub(f"{t.__name__}: {v}".strip().rstrip(":"))
    if len(title) > 200:
        title = title[:197] + "…"
    lines = [
        "Onion Board crash report",
        f"Version:  {_state['version']}",
        f"Time:     {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Windows:  {platform.platform()}",
        f"Python:   {sys.version.split()[0]}"
        + (" (installed build)" if getattr(sys, "frozen", False) else ""),
    ]
    if where:
        lines.append(f"Where:    {where}")
    if fatal:
        lines.append("Fatal:    yes (the app could not continue)")
    lines += ["", "Error", "-----", "".join(traceback.format_exception(t, v, tb)).rstrip()]
    tail = _scrub_owner_names(_log_tail(_state["log_path"], LOG_TAIL_LINES))
    if tail:
        lines += ["", f"Last {LOG_TAIL_LINES} log lines", "-------------------", tail]
    return Report(title=title, text=scrub("\n".join(lines)), fatal=fatal)


# -- privacy -----------------------------------------------------------------------

def scrub(text: str) -> str:
    """Replace the user's home folder, user name and computer name, so the report
    can go in a public issue as-is."""
    home = str(Path.home())
    variants = {home, home.replace("\\", "/"), home.replace("\\", "\\\\"),
                quote(home.replace("\\", "/"), safe="/:")}   # in a file:// URL
    short = _short_path(home)   # the 8.3 form (ABCDEF~1), as in %TEMP% on many PCs
    if short:
        variants |= {short, short.replace("\\", "/"), short.replace("\\", "\\\\")}
    for variant in sorted(variants, key=len, reverse=True):
        if len(variant) > 3:
            text = re.sub(re.escape(variant), "%USERPROFILE%", text, flags=re.IGNORECASE)
    text = _scrub_short_home(text, home)
    for var, placeholder in (("COMPUTERNAME", "<pc>"), ("USERNAME", "<user>")):
        name = os.environ.get(var, "")
        if len(name) >= 3:
            text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", placeholder, text,
                          flags=re.IGNORECASE)
    return text


def _short_path(path: str) -> str:
    """The 8.3 short form of path, or "" if it has none (or isn't there)."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
    except (AttributeError, OSError):
        return ""
    return buf.value if 0 < n < len(buf) and buf.value.lower() != path.lower() else ""


def _scrub_short_home(text: str, home: str) -> str:
    """8.3 forms of the profile folder that GetShortPathNameW didn't give us: the
    folder name without spaces etc., cut to k chars + "~" + a number (8 chars max)."""
    parent, _, name = home.replace("/", "\\").rpartition("\\")
    stem = re.sub(r"[^\w$-]", "", name)
    if not parent or not stem:
        return text
    sep = r"[\\/]{1,2}"
    parent_re = sep.join(re.escape(part) for part in parent.split("\\"))
    short_re = "|".join(rf"{re.escape(stem[:k])}~\d{{1,{7 - k}}}"
                        for k in range(min(len(stem), 6), 0, -1))
    return re.sub(rf"{parent_re}{sep}(?:{short_re})(?![\w~])", "%USERPROFILE%", text,
                  flags=re.IGNORECASE)


_NOT_NAMES = {"it", "that", "what", "there", "here", "let", "who", "he", "she"}


def _scrub_owner_names(text: str) -> str:
    """Windows names Bluetooth devices after their owner ("Headset (Alex's AirPods)")
    and the log records every device opened: keep only the "'s" in the log excerpt."""
    return re.sub(r"\b([\w.-]+)(['\u2019]s)\b",
                  lambda m: m.group(0) if m.group(1).lower() in _NOT_NAMES
                  else f"<name>{m.group(2)}", text)


# -- internals ---------------------------------------------------------------------

def _signature(t, tb) -> tuple:
    """Same error type thrown from the same line = the same bug."""
    frames = traceback.extract_tb(tb) if tb is not None else []
    last = frames[-1] if frames else None
    return (t.__name__, last.filename if last else "", last.lineno if last else 0)


def _repeat(t, v, where: str, sig: tuple):
    """Count a bug already reported this run; log one short line about it at most
    every REPEAT_LOG_S seconds, saying how often it came back since the last one."""
    repeats = _state.setdefault("repeats", {})
    count, last = repeats.get(sig, (0, None))
    count += 1
    now = time.monotonic()
    if last is not None and now - last < REPEAT_LOG_S:
        repeats[sig] = (count, last)
        return
    repeats[sig] = (0, now)
    msg = f"{t.__name__}: {v}"
    log.error("Same error again%s (%d time%s since the last line): %s",
              f" in {where}" if where else "", count, "" if count == 1 else "s",
              msg if len(msg) <= 200 else msg[:197] + "…")


def _add_extra(rep: Report, title: str):
    if len(rep.extra) < MAX_EXTRA:
        rep.extra.append(title)


def _log_tail(path: Path | None, n: int) -> str:
    for h in logging.getLogger().handlers:
        if isinstance(h, _Memory):   # "Keep an app log" is off
            return "\n".join(list(h.lines)[-n:])
    if path is None:
        return ""
    try:
        flush()
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 64_000))
            data = f.read().decode("utf-8", "replace")
        return "\n".join(data.splitlines()[-n:])
    except OSError:
        return ""


def _save(rep: Report) -> Path | None:
    if _state["log_path"] is None:
        return None
    try:
        folder = Path(_state["log_path"]).parent / REPORTS_DIR
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"crash-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        for i in range(100):   # two reports in the same second must both be kept
            path = folder / (f"{stem}-{i}.txt" if i else f"{stem}.txt")
            try:
                with open(path, "x", encoding="utf-8") as f:
                    f.write(rep.text)
                break
            except FileExistsError:
                continue
        else:
            return None
        for old in sorted(folder.glob("crash-*.txt"))[:-KEEP_REPORTS]:
            old.unlink(missing_ok=True)
        return path
    except OSError:
        log.warning("couldn't save the crash report", exc_info=True)
        return None


def save_freeze(seconds: float, stack: str) -> Path | None:
    """A frozen window (hangwatch.py): its stack, saved beside the crash reports."""
    from soundboard import __version__
    text = "\n".join([f"Onion Board froze for {seconds:.0f} s",
                      f"Version:  {__version__}",
                      f"Time:     {time.strftime('%Y-%m-%d %H:%M:%S')}",
                      f"Lasted:   {FREEZE_NOT_ENDED}",
                      "", "What it was doing", "-----------------", stack])
    return _save(Report(title="froze", text=scrub(text), fatal=False))


FREEZE_NOT_ENDED = "still frozen"   # until note_freeze_end; left if the app never came back


def note_freeze_end(path: Path | None, seconds: float):
    """Write how long a saved freeze lasted in all on its `Lasted:` line, once the
    window answers again. The file keeps its old time, so a report already counted
    (usage.py reads the ones newer than the last send) isn't counted again. Left
    saying FREEZE_NOT_ENDED: the app was ended while frozen (or never came back)."""
    if path is None:
        return
    try:
        st = path.stat()
        text = path.read_text(encoding="utf-8")
        new = text.replace(f"Lasted:   {FREEZE_NOT_ENDED}", f"Lasted:   {seconds:.0f} s", 1)
        if new == text:
            return
        path.write_text(new, encoding="utf-8")
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        log.debug("couldn't note how long the freeze lasted", exc_info=True)


def _offer(rep: Report, sig: tuple):
    """Show the dialog on the UI thread, at most once per distinct bug and
    MAX_DIALOGS per run. A dialog already open collects further errors instead."""
    open_rep = _state["open"]
    if open_rep is not None and not rep.fatal:
        _add_extra(open_rep, rep.title)
        return
    if not rep.fatal and (sig in _state["seen"] or _state["dialogs"] >= MAX_DIALOGS):
        return
    _state["seen"].add(sig)
    on_ui = threading.current_thread() is threading.main_thread()
    if on_ui:
        _show_dialog(rep)
    elif _state["bridge"] is not None:
        _state["bridge"].show.emit(rep)


def _show_dialog(rep: Report):
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            _native_box(rep)
            return
        # An error that didn't stop the app must not put a window over the user's game
        # (typically the app is in the tray while they play): hold it until they come
        # back to Onion Board. A fatal one is shown at once: the app is about to quit.
        if not rep.fatal and not _app_in_front():
            if _state["pending"] is None:
                _state["pending"] = rep
            else:
                _add_extra(_state["pending"], rep.title)
            log.info("crash report held back until Onion Board is in front: %s", rep.title)
            return
        from soundboard.ui.crashdialog import CrashDialog
        _state["dialogs"] += 1
        _state["open"] = rep
        dlg = CrashDialog(rep, _state["log_path"], parent=QApplication.activeWindow())
        def closed(*_a, rep=rep):
            if _state["open"] is rep:
                _state["open"] = None
        dlg.finished.connect(closed)
        # its parent (the window in front then, maybe a dialog) can be deleted with it
        # still open, and then finished never comes: later errors would be held forever
        if hasattr(dlg, "destroyed"):
            dlg.destroyed.connect(closed)
        _state["dialog"] = dlg   # keep it alive while it's shown
        if rep.fatal:
            dlg.exec()
        else:
            dlg.show()
            dlg.raise_()
    except Exception:  # noqa: BLE001 - never let the crash reporter itself crash
        _state["open"] = None
        log.exception("couldn't show the crash dialog")
        _native_box(rep)


def _app_in_front() -> bool:
    """Is one of this app's windows the active window? (False in the tray, or
    while a game or another program has the focus.)"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    return (app is not None and app.applicationState() == Qt.ApplicationActive
            and app.activeWindow() is not None)


def _show_pending(_state_=None):
    rep, _state["pending"] = _state["pending"], None
    if rep is not None and _app_in_front():
        _show_dialog(rep)
    elif rep is not None:
        _state["pending"] = rep


def _native_box(rep: Report):
    """Last resort (no Qt yet, or Qt itself is broken): a plain Windows message box."""
    if sys.platform != "win32" or "pytest" in sys.modules:
        return
    try:
        import ctypes
        where = f"\n\nA report was saved to:\n{rep.path}" if rep.path else ""
        ctypes.windll.user32.MessageBoxW(
            None, f"{rep.title}{where}\n\nPlease send it to the developer.",
            "Onion Board hit a problem", 0x10)
    except Exception:  # noqa: BLE001
        pass
