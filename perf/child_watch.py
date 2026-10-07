"""The measured process for standalone Onion Watch: its real window, started the way
onionwatch.app.main starts it, on a throwaway profile (ONIONWATCH_HOME, set by the
runner), offscreen, with a stand-in screen and silent fake audio. Started by
perf.runner with an Onion Watch checkout first on PYTHONPATH, never by hand:

    python -m perf.child_watch <child.json>

Stubbed: the update check and the usage count (switched off and offline), message
boxes, and sockets beyond this PC.
"""
from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path

from perf import link
from perf.child_board import Counts, _loopback_only, stand_in_screen


def isolate(conf: dict):
    _loopback_only()
    import sounddevice as sd

    from perf import fakeaudio
    fakeaudio.install(sd, 1)

    from onionwatch import screenwatch, settings
    if not Path(settings.APP_DIR).resolve().is_relative_to(Path(conf["profile"]).resolve()):
        link.send("error", text=f"Onion Watch's data folder isn't in the run's profile: "
                                f"refusing ({settings.APP_DIR})")
        os._exit(3)
    stand_in_screen(screenwatch)

    from onionwatch import updates, usage

    def offline(*_a, **_k):
        raise OSError("perf run: offline")
    updates.check = offline
    usage.maybe_send = lambda *a, **k: None

    from PySide6.QtWidgets import QMessageBox
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Cancel)
    for name in ("warning", "information", "critical"):
        setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))

    cfg = settings.Config(screen=conf["triggers"], usage_count=False, update_check=False,
                          notify=False)
    cfg.save()


class WatchChild:
    def __init__(self, conf: dict):
        self.conf = conf
        self.secs = float(conf.get("secs", 4.0))
        self.app = self.w = self.counts = None
        self.errors: list[str] = []

    def run_for(self, secs: float):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(max(0, int(secs * 1000)), loop.quit)
        loop.exec()

    def start(self):
        from PySide6.QtWidgets import QApplication
        link.mark("app_start")
        self.app = app = QApplication([sys.argv[0]])
        app.setApplicationName("Onion Watch")
        app.setQuitOnLastWindowClosed(False)
        app.setStyle("Fusion")
        from onionwatch import theme
        app.setWindowIcon(theme.app_icon())
        if self.conf.get("event_counts", True):
            self.counts = Counts(app)
        from onionwatch.ui.mainwindow import MainWindow
        self.w = w = MainWindow()
        app.aboutToQuit.connect(w.shutdown)
        w.show()
        self.run_for(0.5)
        link.mark("ready", sounds=0, watch=True)

    def stats(self, name: str, wall: float, extra: dict | None):
        import threading

        from PySide6.QtWidgets import QApplication

        from perf import fakeaudio
        d = {"name": name, "streams": fakeaudio.summaries(),
             "widgets": len(QApplication.allWidgets()), "py_objects": len(gc.get_objects())}
        if self.counts is not None:
            d["paints_per_s"] = round(self.counts.paints / wall, 1)
            d["timers_per_s"] = round(self.counts.timers / wall, 1)
        names = {t.native_id: f"python: {t.name}" for t in threading.enumerate() if t.native_id}
        names[threading.main_thread().native_id] = "ui (main thread)"
        names.update(fakeaudio.native_ids())
        d["thread_names"] = names
        d.update(extra or {})
        link.send("stats", **d)

    def phase(self, name: str, fn):
        from perf import fakeaudio
        gc.collect()
        if self.counts is not None:
            self.counts.reset()
        fakeaudio.reset_all()
        link.mark("start", name=name)
        t0 = time.perf_counter()
        extra = None
        try:
            extra = fn()
        except Exception as e:  # noqa: BLE001 - one broken scenario mustn't end the run
            import traceback
            self.errors.append(f"{name}: {type(e).__name__}: {e}")
            link.send("error", text=f"{name}: {traceback.format_exc()[-1500:]}")
        wall = time.perf_counter() - t0
        link.mark("end", name=name)
        self.stats(name, wall, extra)

    def _watcher(self) -> dict:
        wt = getattr(self.w.triggers, "watcher", None)
        if wt is None:
            return {}
        return {"check_ms": round(float(getattr(wt, "check_ms", 0) or 0), 1),
                "gap_s": round(float(getattr(wt, "gap", 0) or 0), 3)}

    # -- scenarios
    def sc_ow_shown(self):
        self.run_for(self.secs)

    def sc_ow_tray(self):
        self.w.hide()
        self.run_for(self.secs)

    def sc_ow_watching_tray(self):
        self.w.triggers.set_watching(True)
        self.run_for(self.secs * 1.5)
        out = self._watcher()
        self.w.triggers.set_watching(False)
        self.run_for(0.3)
        return out


def main():
    link.open_line()
    conf = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    link.mark("hello", pid=os.getpid(), exe=sys.executable)
    isolate(conf)
    child = WatchChild(conf)
    child.start()
    for name in conf["scenarios"]:
        fn = getattr(child, f"sc_{name}", None)
        if fn is None:
            link.send("error", text=f"no scenario called {name}")
            continue
        child.phase(name, fn)
    link.send("done", errors=child.errors)
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
