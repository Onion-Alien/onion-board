"""The measured process: the real Onion Board, started the way soundboard.core.app.main
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

    from soundboard.sounds import library
    if not Path(library.APP_DIR).resolve().is_relative_to(profile):
        link.send("error", text=f"the app's data folder isn't in the run's profile: refusing "
                                f"({library.APP_DIR})")
        link.hard_exit(3)

    from soundboard.mic import directmic
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

    from soundboard.core import updates

    def offline(*_a, **_k):
        raise OSError("perf run: offline")
    updates._get = updates._open = offline
    updates.start_install = no_admin

    from soundboard.control import winkeys
    winkeys.Hotkeys.register = lambda self, mapping: None   # no global hotkeys
    winkeys.press = lambda *a, **k: False                    # no key presses (push-to-talk)

    from soundboard.control import midi

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

    from soundboard.core import autostart
    from soundboard.mic import cableformat
    from soundboard.win import shellicon
    autostart.winreg = None
    shellicon.shortcut_folders = lambda: []
    cableformat.cable_ends = lambda names_hint=None: []
    cableformat.set_rate = lambda end, rate=None: False

    from soundboard.audio import appaudio
    from soundboard.mic import voicesdk
    from soundboard.core import tips
    voicesdk.foreground_process = lambda: (0, "")
    tips.fullscreen_in_front = lambda: False
    appaudio.default_output_name = lambda: None
    appaudio.endpoint_names = lambda kind: None
    appaudio.recording_apps = lambda device: []
    # the Apps tab lists state["apps"] (made-up programs), never the PC's own
    state["apps"] = []

    def listed(strict=False, alive=None, meters=None):
        if alive is not None:
            alive.update({a.pid: a.exe.lower() for a in state["apps"]})
        return list(state["apps"])
    appaudio.list_apps = listed
    appaudio._list_apps = lambda *a, **k: []
    appaudio.running = lambda: {a.pid: a.exe.lower() for a in state["apps"]}

    from soundboard.style import owl
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
    from soundboard.sounds import library
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
    c.tutorials_on = False   # a tab's one-time how-to (its Bun animates) isn't steady state
    c.tray = not conf.get("real_window")
    c.lite_mode = os.environ.get("PERF_LITE") == "1"   # --env PERF_LITE=1: lite mode on
    if conf.get("triggers") is not None:
        c.screen = conf["triggers"]
    c.save()
    if conf.get("watch_zip"):
        from soundboard.addons import modules
        modules.install_zip(Path(conf["watch_zip"]), "onion-watch", "triggers",
                            library.APP_DIR / "modules")


# ------------------------------------------------------------------ in-process counts

class Counts:
    """Paint and timer events across the app (an application-wide event filter).
    It runs in the measured process, so it costs a little itself: --no-event-counts
    leaves it out."""

    def __init__(self, app):
        from PySide6.QtCore import QEvent, QObject
        from collections import Counter
        paint, timer = QEvent.Paint, QEvent.Timer
        self.paints = self.timers = 0
        self.by_class: Counter[str] = Counter()   # paints per widget class (the top ones
        counts = self                             # say what keeps repainting)
        self.skip = None                          # the stall meter's timer

        class F(QObject):
            def eventFilter(self, obj, ev):
                t = ev.type()
                if t == paint:
                    counts.paints += 1
                    counts.by_class[type(obj).__name__] += 1
                elif t == timer and obj is not counts.skip:
                    counts.timers += 1
                return False
        self.f = F()
        app.installEventFilter(self.f)

    def reset(self):
        self.paints = self.timers = 0
        self.by_class.clear()


class StallMeter:
    """How long the UI thread went without running its event loop: a 4 ms precise timer
    notes the gap between its ticks, and a gap past the tick is a stall (a click, a
    key or a repaint that came in then waited that long). Its own timer events aren't
    in Counts' timers_per_s."""

    EVERY_MS = 4
    BIG_MS = (50, 100, 250)

    def __init__(self, app):
        from PySide6.QtCore import QTimer, Qt
        self.timer = QTimer(app)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.last = time.perf_counter()
        self.reset()
        self.timer.start(self.EVERY_MS)

    def reset(self):
        self.last = time.perf_counter()
        self.stalls: list[float] = []   # ms past the tick, each over 16 ms (a frame)

    def _tick(self):
        now = time.perf_counter()
        late = (now - self.last) * 1000 - self.EVERY_MS
        self.last = now
        if late > 16:
            self.stalls.append(late)

    def summary(self) -> dict:
        s = sorted(self.stalls, reverse=True)
        out = {"stall_max_ms": round(s[0]) if s else 0,
               "stalls_top_ms": [round(x) for x in s[:5]],
               "stall_total_ms": round(sum(s))}
        for b in self.BIG_MS:
            out[f"stalls_over_{b}"] = sum(1 for x in s if x > b)
        return out


class UiSampler:
    """The UI thread's Python stack, sampled every 2 ms from a thread of its own:
    which calls the UI thread spends its time under (Qt's own painting and layout
    show up under the Python call that started them, or as the event loop)."""

    EVERY_S = 0.002

    # a sample this long after the stall meter's last tick is in a stall
    STALL_S = float(os.environ.get("PERF_STALL_MS", "30")) / 1000

    def __init__(self, meter: StallMeter | None = None):
        from collections import Counter
        self.leaf: Counter[str] = Counter()     # the innermost app function
        self.under: Counter[str] = Counter()    # every app function on the stack
        self.stalled: Counter[str] = Counter()  # innermost app call, only inside stalls
        self.stalled_under: Counter[str] = Counter()
        self.meter = meter
        self.n = self.n_stalled = 0
        # the UI thread's frames this thread took hold of, let go of on the UI thread:
        # one that returned meanwhile owns its locals, and its last reference dropped
        # here freed the UI's Qt objects on this thread (a native crash, see uigc)
        self._held: list = []
        self._held_lock = threading.Lock()
        from PySide6.QtCore import QTimer
        self._drop = QTimer()
        self._drop.timeout.connect(self._let_go)
        self._drop.start(50)
        self._ui = threading.main_thread().ident
        self._pkg = str(Path(__file__).resolve().parent.parent / "soundboard")
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, name="perf-sampler", daemon=True)
        self._t.start()

    @staticmethod
    def _where(f) -> str:
        c = f.f_code
        return f"{Path(c.co_filename).name}:{c.co_firstlineno}({c.co_name})"

    def _run(self):
        tick = getattr(getattr(__import__("ctypes"), "windll", None), "winmm", None)
        if tick is not None:   # Windows' timer: 15.6 ms steps without it
            tick.timeBeginPeriod(1)
        try:
            self._sample()
        finally:
            if tick is not None:
                tick.timeEndPeriod(1)

    def _let_go(self):
        with self._held_lock:
            held, self._held = self._held, []
        del held   # (here, on the UI thread)

    def _sample(self):
        while not self._stop.wait(self.EVERY_S):
            frames = sys._current_frames()
            f = frames.get(self._ui)
            if f is None:
                with self._held_lock:
                    self._held.append(frames)
                del frames
                continue
            self.n += 1
            seen, leaf, walked = set(), None, [frames]
            while f is not None:
                walked.append(f)
                if f.f_code.co_filename.startswith(self._pkg):
                    w = self._where(f)
                    leaf = leaf or w
                    seen.add(w)
                f = f.f_back
            with self._held_lock:
                self._held.append(walked)
            del frames, walked
            self.leaf[leaf or "(event loop / Qt / perf)"] += 1
            for w in seen:
                self.under[w] += 1
            m = self.meter
            if m is not None and time.perf_counter() - m.last > self.STALL_S:
                self.n_stalled += 1
                self.stalled[leaf or "(Qt / perf)"] += 1
                for w in seen:
                    self.stalled_under[w] += 1

    def stop(self) -> str:
        self._stop.set()
        self._t.join(1.0)
        self._drop.stop()
        self._let_go()
        n = max(1, self.n)
        out = [f"{self.n} samples, every {self.EVERY_S * 1000:.0f} ms", "", "innermost app call:"]
        out += [f"  {c * 100 / n:5.1f}%  {k}" for k, c in self.leaf.most_common(30)]
        out += ["", "anywhere on the stack:"]
        out += [f"  {c * 100 / n:5.1f}%  {k}" for k, c in self.under.most_common(40)]
        if self.meter is not None:
            ns = max(1, self.n_stalled)
            out += ["", f"inside UI stalls ({self.n_stalled} samples, "
                        f"~{self.n_stalled * self.EVERY_S * 1000:.0f} ms), innermost app call:"]
            out += [f"  {c * 100 / ns:5.1f}%  {k}" for k, c in self.stalled.most_common(30)]
            out += ["", "inside UI stalls, anywhere on the stack:"]
            out += [f"  {c * 100 / ns:5.1f}%  {k}"
                    for k, c in self.stalled_under.most_common(50)]
        return "\n".join(out) + "\n"


class Child:
    def __init__(self, conf: dict, state: dict):
        self.conf = conf
        self.state = state
        self.secs = float(conf.get("secs", 4.0))
        self.app = self.w = self.counts = self.meter = None
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

        from soundboard.style import appstate as kit_appstate
        from soundboard.ui.kit import appstate
        # (both: Hoot and the style kit ask their own)
        appstate.active = kit_appstate.active = (lambda: True) if front else (lambda: False)
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
            d["paints_by_class"] = {k: round(n / wall, 1)
                                    for k, n in self.counts.by_class.most_common(8)}
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
        if self.meter is not None:
            self.meter.reset()
        t0 = time.perf_counter()
        extra = None
        # --env PERF_CPROFILE=idle_front,dialogs: those scenarios' UI-thread Python
        # profile (top by own time) goes to logs/cprofile-<name>.txt
        prof = None
        if name in os.environ.get("PERF_CPROFILE", "").split(","):
            import cProfile
            prof = cProfile.Profile()
            prof.enable()
        # --env PERF_SAMPLE=idle_front: the UI thread's stack every 2 ms (cProfile
        # can't keep to one thread), what it was doing to logs/samples-<name>.txt
        sampler = None
        if name in os.environ.get("PERF_SAMPLE", "").split(","):
            sampler = UiSampler(self.meter)
        try:
            extra = fn()
        except Exception as e:  # noqa: BLE001 - one broken scenario mustn't end the run
            import traceback
            self.errors.append(f"{name}: {type(e).__name__}: {e}")
            link.send("error", text=f"{name}: {traceback.format_exc()[-1500:]}")
        wall = time.perf_counter() - t0
        if self.meter is not None:
            extra = {**self.meter.summary(), **(extra or {})}
        if prof is not None:
            prof.disable()
            self._write_profile(name, prof)
        if sampler is not None:
            logs = Path(self.conf["profile"]).parent.parent / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            (logs / f"samples-{name}.txt").write_text(sampler.stop(), encoding="utf-8")
        link.mark("end", name=name)
        self.stats(name, wall, extra)

    def _write_profile(self, name: str, prof):
        import io
        import pstats
        logs = Path(self.conf["profile"]).parent.parent / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        st = pstats.Stats(prof, stream=buf)
        st.sort_stats("tottime").print_stats(40)
        st.sort_stats("cumulative").print_stats(40)
        (logs / f"cprofile-{name}.txt").write_text(buf.getvalue(), encoding="utf-8")

    def iteration(self, i: int, **extra):
        from PySide6.QtCore import QObject
        from PySide6.QtWidgets import QApplication
        qobjects = len(self.w.findChildren(QObject)) + len(QApplication.topLevelWidgets())
        link.mark("iter", i=i, py_objects=len(gc.get_objects()), qobjects=qobjects, **extra)

    # -- start
    def start_app(self):
        from soundboard.core import app as sbapp
        from soundboard.core import applog
        from soundboard import i18n
        from soundboard.sounds import library
        applog.setup(library.APP_DIR)
        sbapp.tune_runtime_for_audio()
        i18n.startup(library.APP_DIR)
        from PySide6.QtWidgets import QApplication
        link.mark("app_start")
        self.app = app = QApplication([sys.argv[0]])
        from soundboard.core.singleinstance import (claim_single_instance,
                                                    listen_for_second_launch)
        claim_single_instance()
        app.instance_server = listen_for_second_launch(app, lambda: self.w)
        from soundboard.ui.kit import a11y, quietbox
        quietbox.install(app)
        applog.ui_ready()
        app.setStyle("Fusion")
        a11y.install(app)
        from soundboard.ui.kit import theme
        app.setWindowIcon(theme.app_icon())
        if self.conf.get("real_window"):
            self._park_windows_off_screen()
        if self.conf.get("event_counts", True):
            self.counts = Counts(app)
        if self.conf.get("stalls"):   # (the use tier: its 4 ms timer costs a little)
            self.meter = StallMeter(app)
            if self.counts is not None:
                self.counts.skip = self.meter.timer
        from soundboard.ui.window.mainwindow import MainWindow
        self.w = w = MainWindow()
        app.aboutToQuit.connect(w.shutdown)
        if self.conf.get("real_window"):
            from PySide6.QtCore import Qt
            w.setAttribute(Qt.WA_ShowWithoutActivating)
            w.move(-9000, 200)
        w.show()
        from soundboard.core.hangwatch import HangWatch
        from soundboard.core.uigc import UiCollector
        app.hangwatch = HangWatch(parent=app)
        app.collector = UiCollector(parent=app)
        self.foreground(True)
        loaded = self.run_until(lambda: not w.soundctl._load_thread.is_alive(), 60)
        if self.conf.get("watch_zip") and w.triggers.needed_now():
            self.run_until(lambda: not w.triggers.pending, 30)
        # what soundboard.core.app.main builds behind the loading screen: Settings and a
        # spare Edit sound, then their first show (without it every Edit measured a build)
        w.setctl.preload_dialogs()
        w.setctl.warm_settings()
        w.setctl.warm_triggers()
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

    def sc_settle(self):
        """The start-up's work in the background through (the kept Settings' pages
        built one at a time), then a second more."""
        ctl = self.w.setctl
        self.foreground(True)
        self.run_until(lambda: ctl._settings_kept is not None
                       and not getattr(ctl, "_preload_pages", [None]), 30.0, 0.25)
        self.run_for(1.0)

    def sc_idle_settled(self):
        self.w.tabs.setCurrentIndex(0)
        self.foreground(True)
        self.run_for(self.secs)

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
        extra = {"first_paint_ms": self.first_paint_ms()}
        self.run_for(1.0)
        return extra

    def first_paint_ms(self) -> float:
        """How long the whole window takes to paint once (a grab), in ms."""
        t0 = time.perf_counter()
        self.w.grab()
        return round((time.perf_counter() - t0) * 1000, 1)

    def sc_shown_after_rest(self):
        """Shown again after tray_rested gave its memory back: pages read back."""
        return self.sc_shown_again()

    def sc_import_sounds(self):
        w = self.w
        files = self.conf["import_files"]
        before = len(w.cfg.sounds)
        t0 = time.perf_counter()
        w.impctl.import_files(list(files))
        ok = self.run_until(lambda: len(w.cfg.sounds) >= before + len(files)
                            and not getattr(w.impctl, "_pending_imports", 0), 120, 0.1)
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
            w.playctl.play(sid, now=True)
        self.run_for(self.secs)
        w.playctl.stop_all()
        self.run_for(0.5)

    def sc_play_rapid(self):
        w = self.w
        sids = self._sids()
        for k in range(20):
            w.playctl.play(sids[k % len(sids)], now=True)
            self.run_for(0.05)
        self.run_for(1.0)
        w.playctl.stop_all()
        self.run_for(1.0)

    def sc_fx_preview(self):
        from soundboard.audio import soundfx
        w = self.w
        presets = [p for p in soundfx.PRESETS if p != "None (original)"]
        for k, sid in enumerate(self._sids()[:5]):
            w.playctl.preview(sid, fx=soundfx.PRESETS[presets[k % len(presets)]])
            self.run_for(0.8)
        w.playctl.drop_preview()
        w.playctl.stop_all()
        self.run_for(1.0)
        held = sum(getattr(a, "nbytes", 0) for a in getattr(w, "_fx_cache", {}).values()) \
            if hasattr(w, "_fx_cache") else None
        return {"fx_cache_mb": None if held is None else round(held / 2**20, 1)}

    def sc_tabs_tour(self):
        """Every tab shown once, then back to Sounds. tab_open_ms: the switch and its
        first paint; tab_switch_ms: the switch alone (the rest is Qt drawing it)."""
        from PySide6.QtWidgets import QApplication

        from soundboard.ui.window.tabcontrol import TAB_KEYS
        w = self.w
        first, switch = {}, {}
        order = [i for i in range(w.tabs.count()) if w.tabs.isTabVisible(i) and i != 0] + [0]
        for i in order:
            name = TAB_KEYS[i] if i < len(TAB_KEYS) else type(w.tabs.widget(i)).__name__
            t0 = time.perf_counter()
            w.tabs.setCurrentIndex(i)
            t1 = time.perf_counter()
            QApplication.processEvents()
            first[name] = round((time.perf_counter() - t0) * 1000)
            switch[name] = round((t1 - t0) * 1000)
            self.run_for(max(0.6, self.secs / 4))
        self.run_for(0.5)
        return {"tab_open_ms": first, "tab_switch_ms": switch}

    def sc_dialogs(self):
        from PySide6.QtWidgets import QApplication
        w = self.w
        took = {}
        for k in range(2):   # Settings is a page in the window: opened, drawn, closed
            t0 = time.perf_counter()
            w.setctl.open_settings("privacy" if k == 0 else "devices")
            QApplication.processEvents()
            took[f"settings_{k}"] = round(time.perf_counter() - t0, 2)
            self.run_for(0.3)
            w.setctl.close_settings()
            self.run_for(0.3)
        sids = self._sids()
        for k in range(2):   # Edit isn't modal: each one is shown, drawn, then closed
            t0 = time.perf_counter()
            d = w.editctl.edit(sids[k % len(sids)])
            QApplication.processEvents()
            took[f"edit_{k}"] = round(time.perf_counter() - t0, 2)
            self.run_for(0.3)
            d.reject()
            self.run_for(0.3)
        # two at once: the second one has no spare to take, so it's built (~250 ms here)
        first = w.editctl.edit(sids[0])
        self.run_for(0.3)
        t0 = time.perf_counter()
        second = w.editctl.edit(sids[1 % len(sids)])
        QApplication.processEvents()
        took["edit_second_open"] = round(time.perf_counter() - t0, 2)
        self.run_for(0.3)
        for d in (second, first):
            if d is not None:
                d.reject()
        self.run_for(0.5)
        # after a theme change (the spare is made again for the new theme)
        was = w.cfg.theme
        w.themectl.apply_theme("Light" if was != "Light" else "Dark")
        self.run_for(1.0)
        t0 = time.perf_counter()
        d = w.editctl.edit(sids[0])
        QApplication.processEvents()
        took["edit_after_theme"] = round(time.perf_counter() - t0, 2)
        self.run_for(0.3)
        d.reject()
        w.themectl.apply_theme(was)
        self.run_for(1.0)
        # the spare Edit made again after the switch (themecontrol.SPARE_AFTER_MS): it's
        # this scenario's, and left to the next one it looked like the voice changer's
        # UI cost (~1 s on a slower PC)
        self.run_until(lambda: w.setctl._spare_editor is not None, 5.0)
        self.run_for(0.2)
        return {"dialog_s": took}

    # -- using the app (the use tier): what each thing a user does blocks the UI
    # thread for (StallMeter), on a board of --sounds sounds
    def _pads(self):
        """The pads showing, in board order."""
        return [p for p in self.w.grid.pads if p.isVisibleTo(self.w)]

    def _home(self):
        w = self.w
        if w.setctl.settings_open():
            w.setctl.close_settings()
        self._tab("sounds")
        self.foreground(True)
        self.run_for(0.3)

    @staticmethod
    def _click(widget, button=None):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(widget, button or Qt.MouseButton.LeftButton)

    def sc_pad_click(self):
        """Pads clicked one at a time: time from the click to the first block with
        sound in it (first_sound_ms), and the UI stall around each."""
        from perf import fakeaudio
        self._home()
        pads = self._pads()
        heard = []
        for k in range(10):
            fakeaudio.listen()
            self._click(pads[(k * 7) % len(pads)])
            self.run_until(lambda: fakeaudio.heard_ms() is not None, 1.5, 0.002)
            heard.append(fakeaudio.heard_ms())
            self.run_for(0.4)
            self.w.playctl.stop_all()
            self.run_for(0.2)
        got = sorted(h for h in heard if h is not None)
        return {"first_sound_ms": heard,
                "first_sound_p50_ms": got[len(got) // 2] if got else None,
                "first_sound_max_ms": got[-1] if got else None}

    def sc_pad_spam(self):
        """Pads spam-clicked: 40 clicks 40 ms apart over different pads."""
        self._home()
        pads = self._pads()
        for k in range(40):
            self._click(pads[(k * 5) % len(pads)])
            self.run_for(0.04)
        self.run_for(1.0)
        self.w.playctl.stop_all()
        self.run_for(0.5)

    def sc_tabs_again(self):
        """Every tab once more (tabs_tour opened them the first time)."""
        out = self.sc_tabs_tour()
        return {"tab_again_ms": out["tab_open_ms"], "tab_again_switch_ms": out["tab_switch_ms"]}

    def sc_settings_pages(self):
        """Settings opened, each page shown in turn, closed; twice."""
        from PySide6.QtWidgets import QApplication
        w = self.w
        self._home()
        took: dict[str, list[int]] = {}

        def timed(key, fn):
            t0 = time.perf_counter()
            out = fn()
            QApplication.processEvents()
            took.setdefault(key, []).append(round((time.perf_counter() - t0) * 1000))
            return out
        for _round in range(2):
            dlg = timed("open", lambda: w.setctl.open_settings("audio"))
            self.run_for(0.2)
            for key in list(dlg._page_keys):
                timed(key, lambda k=key, d=dlg: d.show_page(k))
                self.run_for(0.15)
            timed("close", w.setctl.close_settings)
            self.run_for(0.3)
        return {"page_ms": took}

    def sc_menus(self):
        """A pad's right-click menu, the live controls pop-up, and the drop-downs on
        Settings' Audio page. *_ms: from the click to its own event loop running (the
        menu up) or to the pop-up drawn."""
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtWidgets import QApplication, QComboBox, QMenu
        w = self.w
        self._home()
        took: dict[str, list[int]] = {}
        t0 = [0.0]

        def up():   # the menu's exec() runs: it's built and shown
            took.setdefault("pad_menu", []).append(round((time.perf_counter() - t0[0]) * 1000))
            QTimer.singleShot(150, close_menus)

        def close_menus():
            for tl in QApplication.topLevelWidgets():
                if isinstance(tl, QMenu) and tl.isVisible():
                    tl.close()
        pads = self._pads()
        for k in range(4):
            QTimer.singleShot(0, up)
            t0[0] = time.perf_counter()
            w.padctl.pad_menu(pads[(k * 3) % len(pads)].meta.id, QPoint(200, 200))
            self.run_for(0.2)

        def timed(key, fn):
            t = time.perf_counter()
            fn()
            QApplication.processEvents()
            took.setdefault(key, []).append(round((time.perf_counter() - t) * 1000))
        btn = getattr(w, "speed_btn", None)
        for _k in range(4 if btn is not None else 0):
            timed("live_controls", btn.click)
            self.run_for(0.3)
            btn.pop.hide()
            self.run_for(0.2)
        dlg = w.setctl.open_settings("audio")
        self.run_for(0.3)
        combos = [c for c in dlg.findChildren(QComboBox) if c.isVisibleTo(dlg) and c.count() > 1]
        for c in combos[:4]:
            timed("dropdown", c.showPopup)
            self.run_for(0.25)
            c.hidePopup()
            self.run_for(0.2)
        w.setctl.close_settings()
        self.run_for(0.3)
        return {"menu_ms": took, "dropdowns": len(combos[:4])}

    def sc_search_typing(self):
        """Typing in the Sounds tab's search box at ~8 keys a second, then deleting it."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        w = self.w
        self._home()
        box = w.search
        box.setFocus()
        shown = []
        for text in ("sound 1", "zz", "s"):
            for ch in text:
                QTest.keyClick(box, ch)
                self.run_for(0.12)
            self.run_for(0.4)
            shown.append((box.text(), sum(1 for p in w.pads.values()
                                          if not p.property("filtered"))))
            for _ch in text:
                QTest.keyClick(box, Qt.Key.Key_Backspace)
                self.run_for(0.12)
            self.run_for(0.4)
        box.clear()
        self.run_for(0.5)
        return {"pads_shown": shown}

    def sc_resize_sweep(self):
        """The window's edge dragged narrower and wider: 1700 -> 440 -> 1700 px wide, a
        step every frame (16 ms), then let go (fitcontrol.live: what Windows' drag
        messages switch on)."""
        w = self.w
        self._home()
        was = w.size()
        h = max(720, was.height())
        widths = list(range(1700, 439, -40)) + list(range(440, 1701, 40))
        w.fitctl.live(True)
        for x in widths:
            w.resize(x, h)
            self.run_for(0.016)
        w.fitctl.live(False)
        self.run_for(0.3)
        w.resize(was)
        self.run_for(0.5)
        return {"steps": len(widths)}

    def sc_scroll_board(self):
        """The board scrolled from top to bottom and back, a wheel notch (120 px) a
        frame."""
        self._home()
        bar = self.w._pads_scroll.verticalScrollBar()
        steps = 0
        for target in (bar.maximum(), 0):
            while bar.value() != target and steps < 400:
                bar.setValue(bar.value() + (120 if target else -120))
                steps += 1
                self.run_for(0.016)
        self.run_for(0.3)
        return {"steps": steps, "scroll_px": bar.maximum()}

    def sc_sliders(self):
        """Sliders dragged while a sound plays: the sounds' volume, then the live
        controls' first two (speed, pitch), end to end and back, a step a frame."""
        from PySide6.QtWidgets import QSlider
        w = self.w
        self._home()
        w.playctl.play(self._sids()[0], now=True)
        dragged = []

        def drag(sl):
            lo, hi, was = sl.minimum(), sl.maximum(), sl.value()
            step = max(1, (hi - lo) // 60)
            sl.setSliderDown(True)
            for v in [*range(was, hi, step), *range(hi, lo, -step), *range(lo, was, step)]:
                sl.setSliderPosition(v)
                self.run_for(0.016)
            sl.setSliderPosition(was)
            sl.setSliderDown(False)
            self.run_for(0.2)
        vol = getattr(w, "vol_sound", None)
        for sl in (vol.findChildren(QSlider) if vol is not None else [])[:1]:
            drag(sl)
            dragged.append("sound volume")
        btn = getattr(w, "speed_btn", None)
        if btn is not None:
            btn.click()
            self.run_for(0.3)
            for sl in [s for s in btn.pop.findChildren(QSlider) if s.isVisibleTo(btn.pop)][:2]:
                drag(sl)
                dragged.append(sl.accessibleName() or sl.objectName() or "live slider")
            btn.reset()
            btn.pop.hide()
        w.playctl.stop_all()
        self.run_for(0.5)
        return {"dragged": dragged}

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
        from soundboard.ui.window.tabcontrol import TAB_INDEX
        self.w.tabs.setCurrentIndex(TAB_INDEX[key])

    def sc_apps_tab_shown(self):
        self._tab("apps")
        self._apps_at = time.perf_counter()
        self.run_for(self.secs)

    def sc_apps_tab_wait(self):
        """The Apps tab stays open past the empty page Bun's moving time (not compared:
        it only gets apps_tab_rested past it)."""
        from soundboard.ui.apps import appspanel
        rest = getattr(appspanel, "BUN_REST_S", 30.0)   # (main before it: 30 s too)
        self.run_for(max(0.0, rest + 3 - (time.perf_counter() - getattr(self, "_apps_at", 0))))
        bun = getattr(getattr(self.w, "apps", None), "bun", None)
        return {"bun_resting": getattr(bun, "resting", None)}

    def sc_apps_tab_rested(self):
        self.run_for(self.secs)

    def sc_apps_tab_left(self):
        self._tab("sounds")
        self.run_for(self.secs)

    # -- each tab left open (the tabs tier): open_<key> shows it and lets its first
    # build and first seconds pass, tab_<key> measures it sitting there
    SETTLE_S = 3.0

    def _open_page(self, key: str) -> dict | None:
        from soundboard.ui.window.tabcontrol import TAB_INDEX
        w = self.w
        if w.bunctl.bun_up():   # (back from Bun mode first)
            w.bunctl.leave_bun_mode(False)
            self.run_for(0.2)
        if w.setctl.settings_open():
            w.setctl.close_settings()
            self.run_for(0.2)
        self.foreground(True)
        if key == "settings":
            w.setctl.open_settings()
        elif key == "bunmode":   # the window goes, the floating Bun comes
            w.bunctl.enter_bun_mode()
        elif key == "apps_card":
            # one program card (the way the owner usually has the tab): a quiet player
            from soundboard.audio import appaudio
            self.state["apps"] = [appaudio.App(48_000, "fakeplayer.exe",
                                               title="Fake player")]
            self._tab("apps")
        else:
            i = TAB_INDEX[key]
            if key == "triggers":   # off at first (+ More tabs): on, as a user would turn
                w.tabctl.set_tab_on(key, True)   # it on (no add-on: Hoot's page, which
                online = w.tabctl.needs_online   # offline mode, the run's, would hide)
                w.tabctl.needs_online = lambda k: k != "triggers" and online(k)
                w.tabs.setTabVisible(i, w.tabctl.tab_shown(key))
            if not w.tabs.isTabVisible(i):
                return {"skipped": True}
            w.tabs.setCurrentIndex(i)
        self.run_for(self.SETTLE_S)
        return None

    def sc_wait_store(self):
        """The Community tab stays open past its Bun's moving time (not compared: it's
        tab_store_rested past it)."""
        from soundboard.ui.store import storelook
        self.run_for(getattr(storelook, "BUN_REST_S", 30.0) + 2)
        bun = getattr(getattr(self.w, "store", None), "bun", None)
        return {"bun_resting": getattr(bun, "resting", None)}

    def sc_wait_triggers(self):
        """... and the Triggers tab past Hoot's (tab_triggers_rested)."""
        from soundboard.ui.triggers import triggerstab
        self.run_for(getattr(triggerstab, "HOOT_REST_S", 30.0) + 2)
        hoot = getattr(getattr(self.w, "triggers", None), "hoot", None)
        return {"hoot_resting": getattr(hoot, "resting", None)}

    def _sit(self, key: str) -> dict:
        self.run_for(self.secs)
        out = {"page": key, "settings_open": self.w.setctl.settings_open()}
        if key.endswith("_rested"):
            key = key[:-len("_rested")]
        if key == "apps_card":
            out["cards"] = len(getattr(self.w.apps, "rows", {}))
        return out

    def sc_tab_sounds_behind(self):
        self.foreground(False)
        self.run_for(self.secs)
        self.foreground(True)

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
        w.routectl.set_route("mic")
        self.run_for(self.secs)
        route = w.cfg.route
        w.routectl.set_route("cable")
        self.state["direct"] = "missing"
        self.run_for(0.5)
        return {"route_was": route}

    def sc_leak_loop(self):
        from soundboard.audio import soundfx
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
                w.playctl.play(sid, now=True)
            self.run_for(0.3)
            w.playctl.preview(sids[i % len(sids)], fx=fx)
            self.run_for(0.4)
            w.playctl.stop_all()
            self.close_dialogs_soon(250)
            w.setctl.open_settings("privacy")
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
        return {"memory_parts": self.memory_parts()}

    def sc_tray_rested(self):
        """In the tray past memtrim.AFTER_S: memory given back to Windows."""
        self.w.hide()
        tick = self.w.tickctl
        try:
            from soundboard.core import memtrim
            self.run_until(lambda: getattr(tick, "_given_back", False),
                           memtrim.AFTER_S + 5, 0.25)
        except ImportError:   # (a checkout from before it)
            self.run_for(35.0)
        self.run_for(self.secs)
        return {"memory_parts": self.memory_parts()}

    def memory_parts(self) -> dict:
        """Where the RAM goes, in MB: the sounds' audio read into RAM and on disk
        (mapped), the engine's resampled copies, the pads' pictures, and Python's own
        objects."""
        import sys as _sys

        import numpy as np

        from soundboard.audio import mapped
        from soundboard.sounds import thumbs
        mb = 1 << 20
        w = self.w
        in_ram = on_disk = 0
        for a in getattr(w, "audio", {}).values():
            if isinstance(a, np.ndarray):
                if mapped.is_mapped(a):
                    on_disk += a.nbytes
                else:
                    in_ram += a.nbytes
        return {
            "sounds_in_ram": round(in_ram / mb, 1),
            "sounds_mapped": round(on_disk / mb, 1),
            "resampled": round(getattr(w.engine, "_cache_bytes", 0) / mb, 1),
            "pictures": round((thumbs._bytes + thumbs._fitted_bytes) / mb, 1),
            "python_blocks": round(_sys.getallocatedblocks() * 64 / mb, 1),
            "py_objects": len(gc.get_objects()),
        }

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


def _tab_scenarios():
    from perf.runner import TAB_KEYS
    for key in [*TAB_KEYS, "store_rested", "triggers_rested", "bunmode"]:
        setattr(Child, f"sc_open_{key}", lambda self, k=key: self._open_page(k))
        setattr(Child, f"sc_tab_{key}", lambda self, k=key: self._sit(k))


_tab_scenarios()


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
