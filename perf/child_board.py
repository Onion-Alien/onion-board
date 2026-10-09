"""The measured process: the real Onion Board, started the way soundboard.app.main
starts it, on a throwaway profile, with stand-in devices, stepped through the
scenarios the runner asked for. Started by perf.runner, never by hand:

    python -m perf.child_board <child.json>

Isolation (all set up before the window exists):
- APPDATA / LOCALAPPDATA / TEMP point into the run's folder (the runner sets them);
  the app's data folder is checked to be in there before anything is written.
- Qt's offscreen platform (no window on any screen), unless the run is the opt-in
  real-window one (then every window is parked far off every monitor, never
  activated, no tray icon).
- sounddevice's streams are perf.fakeaudio's: real callbacks, no real device.
- Global hotkeys, key presses, MIDI, autostart, shortcuts, device formats, the
  mic effect's admin step and registry, message boxes, the foreground game, and the
  update check are all stubbed; Offline mode is on and Python sockets may only reach
  this PC (127.0.0.1), so nothing goes online.
"""
from __future__ import annotations

import gc
import importlib.abc
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

import soundboard  # noqa: F401  # first, as in main.py: it sets env (BLAS threads) numpy reads

from perf import link

T_START = time.perf_counter()


# ------------------------------------------------------------------ isolation

def _loopback_only():
    import socket
    real = socket.socket.connect, socket.socket.connect_ex
    ok = ("127.0.0.1", "::1", "localhost")

    def check(addr):
        if isinstance(addr, tuple) and addr and addr[0] not in ok:
            raise OSError(10013, f"perf run: no network ({addr[0]})")

    def connect(self, addr):
        check(addr)
        return real[0](self, addr)

    def connect_ex(self, addr):
        check(addr)
        return real[1](self, addr)
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex


class _PatchOnImport(importlib.abc.MetaPathFinder):
    """Run `fn(module)` right after a module named `<pkg>.<leaf>` is first run, every
    time it is (the board forgets and reloads an add-on's modules)."""

    def __init__(self, leaf: str, fn):
        self.leaf, self.fn = leaf, fn

    def find_spec(self, fullname, path, target=None):
        if fullname.rpartition(".")[2] != self.leaf or "." not in fullname:
            return None
        sys.meta_path.remove(self)
        try:
            spec = importlib.util.find_spec(fullname)
        finally:
            sys.meta_path.insert(0, self)
        if spec is None or spec.loader is None:
            return None
        run, fn = spec.loader.exec_module, self.fn

        def exec_module(module):
            run(module)
            fn(module)
        spec.loader.exec_module = exec_module
        return spec


def stand_in_screen(sw, width=1920, height=1080):
    """Onion Watch's captures, faked: one 1920x1080 monitor showing three changing
    made-up game frames (never the real screen)."""
    import numpy as np
    rng = np.random.default_rng(11)
    full = []
    for _ in range(3):
        base = rng.random((height // 16 + 1, width // 16 + 1)).astype(np.float32) * 0.7 + 0.1
        full.append(np.kron(base, np.ones((16, 16), np.float32))[:height, :width].copy())
    mon = sw.Monitor(0, 0, width, height, True)

    class StandIn:
        lost = False
        fallback = False
        want_color = False
        color = None
        raw = None

        def __init__(self, src=None, w=width, h=height, tries=1, *_, **__):
            self.src = src or mon
            self.source = (width, height)
            self.n = 0
            self.resize(w, h)

        def resize(self, w, h):
            self.w, self.h = int(w), int(h)
            ys = (np.arange(self.h) * height // max(1, self.h)).clip(0, height - 1)
            xs = (np.arange(self.w) * width // max(1, self.w)).clip(0, width - 1)
            self.frames = [f[ys][:, xs].copy() for f in full]

        def grab(self, *_a, **_k):
            self.n += 1
            return self.frames[(self.n // 4) % 3]

        def full_gray(self, y0, y1, x0, x1):
            return full[(self.n // 4) % 3][y0:y1, x0:x1].copy()

        def close(self):
            pass

    sw.monitors = lambda: [mon]
    sw.open_grabber = StandIn
    sw.Grabber = StandIn
    if hasattr(sw, "DupGrabber"):
        sw.DupGrabber = StandIn
    return StandIn


def watcher_stats(wt) -> dict:
    """An Onion Watch screenwatch.Watcher's last check: how long it took, the gap to
    the next, and why it isn't checking if it isn't."""
    if wt is None:
        return {}
    out = {"check_ms": round(float(getattr(wt, "check_ms", 0) or 0), 1),
           "gap_s": round(float(getattr(wt, "gap", 0) or 0), 3)}
    for k in ("error", "failed"):
        if getattr(wt, k, None):
            out[f"watch_{k}"] = str(getattr(wt, k))[:300]
    return out


def isolate(conf: dict):
    profile = Path(conf["profile"]).resolve()
    _loopback_only()
    import sounddevice as sd

    from perf import fakeaudio
    fakeaudio.install(sd, conf.get("mic_channels", 1))
    # the device rescan: nothing to do. _terminate still clears the count, or
    # sounddevice's exit handler (`while _initialized: _terminate()`) never ends
    sd._initialize = lambda: None
    sd._terminate = lambda: setattr(sd, "_initialized", 0)

    from soundboard import library
    if not Path(library.APP_DIR).resolve().is_relative_to(profile):
        link.send("error", text=f"the app's data folder isn't in the run's profile: refusing "
                                f"({library.APP_DIR})")
        link.hard_exit(3)

    from soundboard import directmic
    mic_dir = profile / "Mic"
    mic_dir.mkdir(parents=True, exist_ok=True)
    directmic.data_dir = lambda: mic_dir
    directmic.ring_path = lambda: mic_dir / "ring2.bin"
    directmic.installed_on = lambda: []
    state = {"direct": "missing"}
    directmic.status = lambda mic_name=None: state["direct"]

    def no_admin(*_a, **_k):
        raise RuntimeError("perf run: no admin steps")
    directmic._elevated = no_admin

    from soundboard import updates

    def offline(*_a, **_k):
        raise OSError("perf run: offline")
    updates._get = updates._open = offline
    updates.start_install = no_admin

    from soundboard import winkeys
    winkeys.Hotkeys.register = lambda self, mapping: None   # no global hotkeys
    winkeys.press = lambda *a, **k: False                    # no key presses (push-to-talk)

    from soundboard import midi

    class NoMidi:
        def __init__(self):
            self.on_message = self.on_closed = lambda *_: None

        def devices(self):
            return []

        def open(self, index, key):
            raise OSError("no MIDI in perf runs")

        def close(self, handle):
            pass
    midi.WinMM = NoMidi

    from soundboard import autostart, cableformat, shellicon
    autostart.winreg = None
    shellicon.shortcut_folders = lambda: []
    cableformat.cable_ends = lambda names_hint=None: []
    cableformat.set_rate = lambda end, rate=None: False

    from soundboard import appaudio, tips, voicesdk
    voicesdk.foreground_process = lambda: (0, "")
    tips.fullscreen_in_front = lambda: False
    appaudio.default_output_name = lambda: None
    appaudio.endpoint_names = lambda kind: None
    appaudio.recording_apps = lambda device: []

    from soundboard.ui import owl
    owl.OwlWidget._mouse = lambda self: None   # the real cursor isn't over a hidden window

    from PySide6.QtWidgets import QMessageBox
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Cancel)
    for name in ("warning", "information", "critical"):
        setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))

    if conf.get("watch_package"):
        def screen(module):
            if module.__name__.split(".")[0] == conf["watch_package"]:
                stand_in_screen(module)
        sys.meta_path.insert(0, _PatchOnImport("screenwatch", screen))
    return state


def write_config(conf: dict):
    from soundboard import library
    sounds = [library.SoundMeta(id=s["id"], name=s["name"], file=s["file"])
              for s in conf["sounds"]]
    c = library.Config(sounds=sounds)
    c.main_device = "CABLE Input (VB-Audio Virtual Cable)"
    c.mon_device = "Headphones (Fake Audio)"
    c.mic_device = ("Microphone (Fake Mono Mic)" if conf.get("mic_channels", 1) == 1
                    else "Microphone (Fake Stereo Mic)")
    c.route = "cable"
    c.setup_done = True
    c.net_offline = True
    c.tabs_off = []
    c.tray = not conf.get("real_window")
    if conf.get("triggers") is not None:
        c.screen = conf["triggers"]
    c.save()
    if conf.get("watch_zip"):
        from soundboard import modules
        modules.install_zip(Path(conf["watch_zip"]), "onion-watch", "triggers",
                            library.APP_DIR / "modules")


# ------------------------------------------------------------------ in-process counts

class Counts:
    """Paint and timer events across the app (an application-wide event filter).
    It runs in the measured process, so it costs a little itself: --no-event-counts
    leaves it out."""

    def __init__(self, app):
        from PySide6.QtCore import QEvent, QObject
        paint, timer = QEvent.Paint, QEvent.Timer
        self.paints = self.timers = 0
        counts = self

        class F(QObject):
            def eventFilter(self, obj, ev):
                t = ev.type()
                if t == paint:
                    counts.paints += 1
                elif t == timer:
                    counts.timers += 1
                return False
        self.f = F()
        app.installEventFilter(self.f)

    def reset(self):
        self.paints = self.timers = 0


class Child:
    def __init__(self, conf: dict, state: dict):
        self.conf = conf
        self.state = state
        self.secs = float(conf.get("secs", 4.0))
        self.app = self.w = self.counts = None
        self.errors: list[str] = []
        self._t0 = 0.0

    # -- time
    def run_for(self, secs: float):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(max(0, int(secs * 1000)), loop.quit)
        loop.exec()

    def run_until(self, cond, timeout: float, step: float = 0.05) -> bool:
        end = time.perf_counter() + timeout
        while not cond():
            if time.perf_counter() > end:
                return False
            self.run_for(step)
        return True

    def close_dialogs_soon(self, after_ms: int):
        """A modal dialog's exec() is about to block: close it after a while."""
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QDialog

        def close():
            for tl in QApplication.topLevelWidgets():
                if tl is not self.w and isinstance(tl, QDialog) and tl.isVisible():
                    tl.reject()
        QTimer.singleShot(after_ms, close)

    def foreground(self, front: bool):
        """In front (one of its windows has focus) or behind another program."""
        from PySide6.QtCore import Qt

        from soundboard.ui import appstate
        appstate.active = (lambda: True) if front else (lambda: False)
        self.app.applicationStateChanged.emit(Qt.ApplicationActive if front
                                              else Qt.ApplicationInactive)

    # -- what gets reported
    def thread_names(self) -> dict:
        from perf import fakeaudio
        names = {t.native_id: "python: " + (t.name.split("-")[0] if t.name.startswith("Thread-")
                                             else t.name)
                 for t in threading.enumerate() if t.native_id}
        names[threading.main_thread().native_id] = "ui (main thread)"
        names.update(fakeaudio.native_ids())
        return names

    def stats(self, name: str, wall: float, extra: dict | None = None):
        from PySide6.QtCore import QObject, QTimer
        from PySide6.QtWidgets import QApplication

        from perf import fakeaudio
        d = {"name": name}
        if self.counts is not None:
            d["paints_per_s"] = round(self.counts.paints / wall, 1)
            d["timers_per_s"] = round(self.counts.timers / wall, 1)
        d["streams"] = fakeaudio.summaries()
        if self.w is not None:
            eng = getattr(self.w, "engine", None)
            if eng is not None and hasattr(eng, "xruns"):
                d["engine_xruns"] = sum(eng.xruns.values())
            d["qobjects"] = len(self.w.findChildren(QObject))
            d["active_timers"] = sum(1 for t in self.w.findChildren(QTimer) if t.isActive())
        d["widgets"] = len(QApplication.allWidgets())
        d["windows_alive"] = len(QApplication.topLevelWidgets())
        d["py_objects"] = len(gc.get_objects())
        d["thread_names"] = self.thread_names()
        if extra:
            d.update(extra)
        link.send("stats", **d)

    def phase(self, name: str, fn):
        from perf import fakeaudio
        gc.collect()
        if self.counts is not None:
            self.counts.reset()
        fakeaudio.reset_all()
        link.mark("start", name=name, thread_names=self.thread_names())
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

    def iteration(self, i: int, **extra):
        from PySide6.QtCore import QObject
        from PySide6.QtWidgets import QApplication
        qobjects = len(self.w.findChildren(QObject)) + len(QApplication.topLevelWidgets())
        link.mark("iter", i=i, py_objects=len(gc.get_objects()), qobjects=qobjects, **extra)

    # -- start
    def start_app(self):
        from soundboard import app as sbapp
        from soundboard import applog, i18n, library
        applog.setup(library.APP_DIR)
        sbapp.tune_runtime_for_audio()
        i18n.startup(library.APP_DIR)
        from PySide6.QtWidgets import QApplication
        link.mark("app_start")
        self.app = app = QApplication([sys.argv[0]])
        from soundboard.singleinstance import claim_single_instance, listen_for_second_launch
        claim_single_instance()
        app.instance_server = listen_for_second_launch(app, lambda: self.w)
        from soundboard.ui import a11y, quietbox
        quietbox.install(app)
        applog.ui_ready()
        app.setStyle("Fusion")
        a11y.install(app)
        from soundboard import theme
        app.setWindowIcon(theme.app_icon())
        if self.conf.get("real_window"):
            self._park_windows_off_screen()
        if self.conf.get("event_counts", True):
            self.counts = Counts(app)
        from soundboard.ui.mainwindow import MainWindow
        self.w = w = MainWindow()
        app.aboutToQuit.connect(w.shutdown)
        if self.conf.get("real_window"):
            from PySide6.QtCore import Qt
            w.setAttribute(Qt.WA_ShowWithoutActivating)
            w.move(-9000, 200)
        w.show()
        from soundboard.hangwatch import HangWatch
        from soundboard.uigc import UiCollector
        app.hangwatch = HangWatch(parent=app)
        app.collector = UiCollector(parent=app)
        self.foreground(True)
        loaded = self.run_until(lambda: not w._load_thread.is_alive(), 60)
        if self.conf.get("watch_zip") and w.triggers.needed_now():
            self.run_until(lambda: not w.triggers.pending, 30)
        self.run_for(0.3)
        link.mark("ready", loaded=loaded, sounds=len(w.cfg.sounds),
                  watch=w.triggers.panel is not None)

    def _park_windows_off_screen(self):
        """Real-window run: every window, dialogs too, opens far left of every monitor
        and never takes the focus."""
        from PySide6.QtCore import QEvent, QObject, Qt

        class Park(QObject):
            def eventFilter(self, obj, ev):
                if ev.type() in (QEvent.Polish, QEvent.Show) and getattr(obj, "isWindow", None) \
                        and obj.isWindow():
                    obj.setAttribute(Qt.WA_ShowWithoutActivating)
                    if obj.x() > -8000:
                        obj.move(-9000 + max(0, obj.x()) % 500, 200)
                return False
        self._park = Park()
        self.app.installEventFilter(self._park)

    # -- scenarios
    def sc_idle_front(self):
        self.w.tabs.setCurrentIndex(0)
        self.foreground(True)
        self.run_for(self.secs)

    def sc_idle_behind(self):
        self.foreground(False)
        self.run_for(self.secs)
        self.foreground(True)

    def sc_minimised(self):
        self.w.showMinimized()
        self.run_for(self.secs)
        self.w.showNormal()
        self.run_for(0.2)

    def sc_tray(self):
        self.w.hide()
        self.run_for(self.secs)

    def sc_shown_again(self):
        self.w.show()
        self.foreground(True)
        self.run_for(1.0)

    def sc_import_sounds(self):
        w = self.w
        files = self.conf["import_files"]
        before = len(w.cfg.sounds)
        t0 = time.perf_counter()
        w.import_files(list(files))
        ok = self.run_until(lambda: len(w.cfg.sounds) >= before + len(files)
                            and not getattr(w, "_pending_imports", 0), 120, 0.1)
        took = time.perf_counter() - t0
        self.run_for(0.5)
        w._save_now()
        self.run_for(0.3)
        return {"imported": len(w.cfg.sounds) - before, "import_s": round(took, 2),
                "finished": ok}

    def _sids(self):
        return [m.id for m in self.w.cfg.sounds]

    def sc_play_overlap(self):
        w = self.w
        for sid in self._sids()[:3]:
            w.play(sid, now=True)
        self.run_for(self.secs)
        w.stop_all()
        self.run_for(0.5)

    def sc_play_rapid(self):
        w = self.w
        sids = self._sids()
        for k in range(20):
            w.play(sids[k % len(sids)], now=True)
            self.run_for(0.05)
        self.run_for(1.0)
        w.stop_all()
        self.run_for(1.0)

    def sc_fx_preview(self):
        from soundboard import soundfx
        w = self.w
        presets = [p for p in soundfx.PRESETS if p != "None (original)"]
        for k, sid in enumerate(self._sids()[:5]):
            w.preview(sid, fx=soundfx.PRESETS[presets[k % len(presets)]])
            self.run_for(0.8)
        w.drop_preview()
        w.stop_all()
        self.run_for(1.0)
        held = sum(getattr(a, "nbytes", 0) for a in getattr(w, "_fx_cache", {}).values()) \
            if hasattr(w, "_fx_cache") else None
        return {"fx_cache_mb": None if held is None else round(held / 2**20, 1)}

    def sc_tabs_tour(self):
        from PySide6.QtWidgets import QApplication
        w = self.w
        first = {}
        for i in range(w.tabs.count()):
            if not w.tabs.isTabVisible(i):
                continue
            t0 = time.perf_counter()
            w.tabs.setCurrentIndex(i)
            QApplication.processEvents()
            first[type(w.tabs.widget(i)).__name__] = round((time.perf_counter() - t0) * 1000)
            self.run_for(max(0.6, self.secs / 4))
        w.tabs.setCurrentIndex(0)
        self.run_for(0.5)
        return {"tab_open_ms": first}

    def sc_dialogs(self):
        w = self.w
        took = {}
        for k in range(2):
            self.close_dialogs_soon(500)
            t0 = time.perf_counter()
            w.open_settings("privacy" if k == 0 else "devices")
            took[f"settings_{k}"] = round(time.perf_counter() - t0, 2)
        for k, sid in enumerate(self._sids()[:2]):
            self.close_dialogs_soon(500)
            t0 = time.perf_counter()
            w.edit(sid)
            took[f"edit_{k}"] = round(time.perf_counter() - t0, 2)
        self.run_for(0.5)
        return {"dialog_s": took}

    def sc_voice_preset(self, preset: str = "Robot"):
        w = self.w
        w.voice.fx.pick(preset)
        self.run_for(self.secs)
        w.voice.fx.btn_power.setChecked(False)
        self.run_for(0.5)
        return {"preset": preset}

    def sc_voice_heavy(self):
        out = {}
        for p in ("Talkbox", "Demon", "High voice"):
            from soundboard import voicefx
            if p in voicefx.PRESETS:
                self.sc_voice_preset(p)
                out[p] = True
        return {"presets": list(out)}

    def sc_mic_check_front(self):
        self.foreground(True)
        self.w.on_mic_check(True)
        self.run_for(self.secs / 2)

    def sc_mic_check_behind(self):
        self.foreground(False)
        self.run_for(self.secs / 2)
        self.w.on_mic_check(False)
        self.foreground(True)
        self.run_for(0.3)

    def _tab(self, key: str):
        from soundboard.ui.mainwindow import TAB_INDEX
        self.w.tabs.setCurrentIndex(TAB_INDEX[key])

    def sc_apps_tab_shown(self):
        self._tab("apps")
        self.run_for(self.secs)

    def sc_apps_tab_left(self):
        self._tab("sounds")
        self.run_for(self.secs)

    def sc_stereo_mic(self):
        e = self.w.engine
        e.set_mic_device("Microphone (Fake Stereo Mic)")
        self.run_for(self.secs)
        self.w.voice.fx.pick("Robot")
        self.run_for(self.secs)
        self.w.voice.fx.btn_power.setChecked(False)
        e.set_mic_device(self.w.cfg.mic_device)
        self.run_for(0.5)

    def sc_route_mic(self):
        w = self.w
        self.state["direct"] = "ready"
        w.set_route("mic")
        self.run_for(self.secs)
        route = w.cfg.route
        w.set_route("cable")
        self.state["direct"] = "missing"
        self.run_for(0.5)
        return {"route_was": route}

    def sc_leak_loop(self):
        from soundboard import soundfx
        w = self.w
        sids = self._sids()
        n = int(self.conf.get("leak_iterations", 6))
        # The first few rounds build things once (Settings' pages, the tabs, effect
        # filters) and grow the heap by ~40 MB; counted, they read as a leak of over
        # 1 MB a round. After them private memory only steps up now and then as the
        # heap settles, and Python and Qt object counts stay flat.
        warm = int(self.conf.get("leak_warmup", 5))
        fx = soundfx.PRESETS.get("Bass boosted")
        for i in range(-warm, n + 1):
            if i == 0:
                self.iteration(0)
                continue
            for sid in sids[i % len(sids):][:3]:
                w.play(sid, now=True)
            self.run_for(0.3)
            w.preview(sids[i % len(sids)], fx=fx)
            self.run_for(0.4)
            w.stop_all()
            self.close_dialogs_soon(250)
            w.open_settings("privacy")
            for key in ("voice", "apps", "triggers", "sounds"):
                self._tab(key)
                self.run_for(0.12)
            w._rebuild_pads()
            self.run_for(0.2)
            gc.collect()
            if i > 0:
                self.iteration(i)
        return {"iterations": n, "warmup": warm}

    def sc_soak(self):
        w = self.w
        w.hide()
        every = float(self.conf.get("soak_every_s", 10))
        n = max(2, int(float(self.conf.get("soak_minutes", 30)) * 60 / every))
        self.iteration(0)
        for i in range(1, n + 1):
            self.run_for(every)
            self.iteration(i)
        return {"iterations": n, "every_s": every}

    def sc_idle_end(self):
        self.w.hide()
        self.run_for(self.secs)

    # -- triggers (the Onion Watch add-on)
    def _panel(self):
        p = self.w.triggers.panel
        return getattr(p, "panel", None)

    def sc_trig_idle_off(self):
        """Installed, watching off, tab never opened: the add-on isn't even loaded."""
        self.w.tabs.setCurrentIndex(0)
        self.run_for(self.secs)
        return {"loaded": self._panel() is not None}

    def sc_trig_watch_hidden(self):
        """Watching on, the tab never opened: loaded the way a start with watching on
        loads it."""
        t0 = time.perf_counter()
        self.w.load_triggers()
        load_s = round(time.perf_counter() - t0, 2)
        tp = self._panel()
        if tp is not None:
            tp.set_watching(True)
        self.run_for(self.secs * 1.5)
        return {"load_s": load_s, **self._watcher()}

    def _watcher(self):
        return watcher_stats(getattr(self._panel(), "watcher", None))

    def sc_trig_tab_shown(self):
        from PySide6.QtWidgets import QApplication
        self._tab("triggers")
        t0 = time.perf_counter()
        QApplication.processEvents()
        took = round((time.perf_counter() - t0) * 1000)
        self.run_for(self.secs)
        return {"tab_show_ms": took, **self._watcher()}

    def sc_trig_tray_watching(self):
        self._tab("sounds")
        self.w.hide()
        self.run_for(self.secs)
        out = self._watcher()
        tp = self._panel()
        if tp is not None:
            tp.set_watching(False)
        self.run_for(0.3)
        return out


def main():
    link.open_line()
    conf = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    link.mark("hello", pid=os.getpid(), exe=sys.executable)
    state = isolate(conf)
    write_config(conf)
    child = Child(conf, state)
    child.start_app()
    for name in conf["scenarios"]:
        fn = getattr(child, f"sc_{name}", None)
        if fn is None:
            link.send("error", text=f"no scenario called {name}")
            continue
        child.phase(name, fn)
    link.send("done", errors=child.errors)
    try:
        child.w.shutdown()
    except Exception:  # noqa: BLE001 - the measuring is over; only the exit is left
        pass
    sys.stderr.flush()
    link.hard_exit(0)


if __name__ == "__main__":
    main()
