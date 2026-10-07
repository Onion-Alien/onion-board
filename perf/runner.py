"""python -m perf: runs Onion Board (and Onion Watch) for real in child processes on
throwaway profiles and measures what each scenario costs. See perf/README.md."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from perf import inputs, link, stats, winproc

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
SAMPLE_S = 0.25
CENSUS_EVERY = 4          # thread census every 4th sample (~1 s)

BOARD_QUICK = ["idle_front", "idle_behind", "minimised", "tray", "shown_again",
               "import_sounds", "play_overlap", "play_rapid", "fx_preview", "tabs_tour",
               "dialogs", "voice_preset", "mic_check_front", "mic_check_behind",
               "apps_tab_shown", "apps_tab_left", "route_mic", "leak_loop", "idle_end"]
BOARD_FULL = BOARD_QUICK[:-1] + ["stereo_mic", "voice_heavy", "idle_end"]
TRIGGERS = ["trig_idle_off", "trig_watch_hidden", "trig_tab_shown", "trig_tray_watching"]
WATCH = ["ow_shown", "ow_tray", "ow_watching_tray"]

TIERS = {
    "quick": {"secs": 4.0, "sounds": 20, "leak_iterations": 6, "trigger_counts": [50],
              "board": BOARD_QUICK, "timeout_s": 240},
    "full": {"secs": 8.0, "sounds": 100, "leak_iterations": 20, "trigger_counts": [0, 10, 50],
             "board": BOARD_FULL, "timeout_s": 600},
}


class Run:
    """One measured child process: starts it, samples it, answers its marks."""

    def __init__(self, name: str, cmd: list[str], env: dict, cwd: Path, hz: float,
                 log: Path, timeout_s: float, profile: Path | None = None):
        self.name, self.cmd, self.env, self.cwd = name, cmd, env, cwd
        self.hz, self.log, self.timeout_s, self.profile = hz, log, timeout_s, profile
        self.lock = threading.Lock()
        self.proc: winproc.Proc | None = None
        self.tracker: winproc.ThreadTracker | None = None
        self.samples: list[dict] = []
        self.marks: list[dict] = []
        self.scenarios: dict[str, dict] = {}
        self.errors: list[str] = []
        self.current: dict | None = None
        self.done = threading.Event()
        self.popen: subprocess.Popen | None = None
        self.t_launch = 0.0
        self._n = 0

    # -- measuring
    def snapshot(self) -> dict:
        p = self.proc
        kids = winproc.descendants(p.pid)
        s = p.sample(kids).as_dict()
        self._n += 1
        return s

    def _census(self) -> dict[int, int]:
        return self.tracker.look()

    def _sampler(self):
        k = 0
        while not self.done.is_set():
            time.sleep(SAMPLE_S)
            with self.lock:
                if self.proc is None or not self.proc.alive():
                    continue
                s = self.snapshot()
                self.samples.append(s)
                if self.current is not None:
                    self.current["during"].append(s)
                k += 1
                if k % CENSUS_EVERY == 0:
                    self._census()

    def _profile_mb(self):
        if self.profile is None:
            return None
        return round(winproc.folder_size(self.profile)[0] / winproc.MB, 1)

    def _on_mark(self, msg: dict):
        ev = msg["ev"]
        with self.lock:
            if ev == "hello":
                self.proc = winproc.Proc(int(msg["pid"]))
                main_exe = Path(msg.get("exe", "")).name
                self.tracker = winproc.ThreadTracker(self.proc, main_exe=main_exe)
                self.hello = self.snapshot()
                self.hello_cycles = self._census()
                return
            s = self.snapshot()
            cyc = self._census()
            names = msg.get("thread_names")
            if names:
                self.tracker.names.update({int(k): v for k, v in names.items()})
            if ev == "app_start":
                self.app_start = s
            elif ev == "ready":
                created = self.proc.created - 11644473600   # 1601 -> 1970
                now = time.time()
                m = stats.phase_metrics(self.hello, s, [], self.hz)
                m.update({
                    "run": self.name,
                    "seconds": round(now - created, 2),
                    "launch_to_ready_s": round(time.perf_counter() - self.t_launch, 2),
                    "python_to_app_s": round(self.app_start["t"] - self.hello["t"], 2),
                    "app_to_ready_s": round(s["t"] - self.app_start["t"], 2),
                    "startup_s": round(now - created, 2),
                    "cpu_by_group": stats.group_pct(winproc.cycles_by_group(
                        self.tracker, self.hello_cycles, cyc), s["t"] - self.hello["t"], self.hz),
                    "threads_by_group": self.tracker.census(),
                    "profile_mb": self._profile_mb(),
                    "notes": f"from process start to the window ready ({msg.get('sounds')} "
                             f"sounds{', Onion Watch loaded' if msg.get('watch') else ''})",
                })
                self.scenarios["cold_start"] = m
            elif ev == "start":
                self.current = {"name": msg["name"], "a": s, "cyc": cyc, "during": [],
                                "iters": [], "profile_mb": self._profile_mb()}
            elif ev == "iter" and self.current is not None:
                self.current["iters"].append({**s, "i": msg["i"],
                                              "py_objects": msg.get("py_objects", 0)})
            elif ev == "end" and self.current is not None:
                c, self.current = self.current, None
                m = stats.phase_metrics(c["a"], s, c["during"], self.hz)
                m["run"] = self.name
                m["cpu_by_group"] = stats.group_pct(
                    winproc.cycles_by_group(self.tracker, c["cyc"], cyc),
                    s["t"] - c["a"]["t"], self.hz)
                m["threads_by_group"] = self.tracker.census()
                prof = self._profile_mb()
                if prof is not None and c["profile_mb"] is not None:
                    m["profile_growth_mb"] = round(prof - c["profile_mb"], 1)
                if len(c["iters"]) >= 2:
                    self._slopes(m, c["iters"], c["name"])
                self.scenarios[c["name"]] = m

    def _slopes(self, m: dict, iters: list[dict], name: str):
        keys = {"private_mb": ("private", winproc.MB), "wset_mb": ("wset", winproc.MB),
                "handles": ("handles", 1), "gdi": ("gdi", 1), "user": ("user", 1),
                "threads": ("threads", 1), "py_objects": ("py_objects", 1)}
        if name == "soak":   # per hour, from the runner's clock
            t0 = iters[0]["t"]
            pts = [{**p, "h": (p["t"] - t0) / 3600} for p in iters]
            m["slopes"] = stats.slopes(pts, "h", keys, skip=1)
            m["slope_unit"] = "hour"
        else:
            m["slopes"] = stats.slopes(iters, "i", keys, skip=1)
            m["slope_unit"] = "loop"
        for k, v in m["slopes"].items():
            m[f"{k}_per_{m['slope_unit']}"] = v

    def _on_stats(self, msg: dict):
        name = msg.get("name")
        with self.lock:
            m = self.scenarios.get(name)
            if m is None:
                return
            names = msg.pop("thread_names", None) or {}
            self.tracker.names.update({int(k): v for k, v in names.items()})
            streams = msg.pop("streams", {}) or {}
            m.update(stats.audio_summary(streams))
            m["streams"] = streams
            for k, v in msg.items():
                if k not in ("ev", "t", "name"):
                    m[k] = v

    # -- running
    def _reader(self):
        out = self.popen.stdout
        for raw in iter(out.readline, b""):
            msg = link.parse(raw.decode("utf-8", "replace"))
            if msg is None:
                continue
            ev = msg["ev"]
            try:
                if ev in ("hello", "app_start", "ready", "start", "end", "iter"):
                    self._on_mark(msg)
                elif ev == "stats":
                    self._on_stats(msg)
                elif ev == "error":
                    self.errors.append(f"{self.name}: {msg.get('text', '')[-600:]}")
                elif ev == "done":
                    self.errors += [f"{self.name}: {e}" for e in msg.get("errors", [])
                                    if not any(e in x for x in self.errors)]
            except Exception as e:  # noqa: BLE001 - keep answering, or the child hangs
                self.errors.append(f"{self.name}: runner couldn't measure {ev}: {e!r}")
            finally:
                if msg.get("wait"):
                    try:
                        self.popen.stdin.write(b"ok\n")
                        self.popen.stdin.flush()
                    except OSError:
                        pass
            if ev == "done":
                break

    def run(self) -> dict:
        print(f"  {self.name}: starting", flush=True)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "wb") as err:
            self.t_launch = time.perf_counter()
            self.popen = subprocess.Popen(self.cmd, cwd=self.cwd, env=self.env,
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=err, creationflags=0x08000000)  # no console
            reader = threading.Thread(target=self._reader, daemon=True)
            sampler = threading.Thread(target=self._sampler, daemon=True)
            reader.start()
            sampler.start()
            reader.join(self.timeout_s)
            timed_out = reader.is_alive()
            self.done.set()
            sampler.join(2)
            if timed_out:
                self.errors.append(f"{self.name}: stopped after {self.timeout_s:.0f} s "
                                   f"(scenario: {self.current and self.current['name']})")
            for pid in ([self.proc.pid] if self.proc else []):
                if self.proc.alive():
                    try:
                        self.popen.wait(10 if not timed_out else 0.1)
                    except subprocess.TimeoutExpired:
                        pass
                    if self.proc.alive():
                        winproc.kill(pid)
            try:
                self.popen.wait(10)
            except subprocess.TimeoutExpired:
                self.popen.kill()
        if self.tracker is not None:
            self.tracker.close()
        if self.proc is not None:
            self.proc.close()
        took = round(time.perf_counter() - self.t_launch, 1)
        print(f"  {self.name}: done in {took} s, {len(self.scenarios)} scenarios"
              + (f", {len(self.errors)} problem(s)" if self.errors else ""), flush=True)
        return {"took_s": took, "exit_code": self.popen.returncode, "errors": self.errors,
                "log": str(self.log)}


# ------------------------------------------------------------------ setting runs up

def child_env(profile: Path, instance: str, real_window: bool, extra: dict) -> dict:
    for d in ("Roaming", "Local", "Temp"):
        (profile / d).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONSTARTUP", "QT_SCALE_FACTOR"):
        env.pop(k, None)
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    env.update({
        "APPDATA": str(profile / "Roaming"), "LOCALAPPDATA": str(profile / "Local"),
        "TEMP": str(profile / "Temp"), "TMP": str(profile / "Temp"),
        "QT_QPA_PLATFORM": "windows" if real_window else "offscreen",
        "QT_QPA_FONTDIR": fonts.as_posix(),
        "QTWEBENGINE_CHROMIUM_FLAGS": "--mute-audio" + ("" if real_window else " --disable-gpu"),
        "ONIONBOARD_INSTANCE": instance, "ONIONWATCH_INSTANCE": instance,
        "ONIONBOARD_NO_STATS": "1", "ONIONBOARD_LANG": "en", "ONIONWATCH_LANG": "en",
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
    })
    env.update(extra)
    return env


def build_watch_zip(src: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(src / "scripts" / "build_module.py"),
                        "--out", str(out)], cwd=src, capture_output=True, text=True, timeout=180)
    z = out / "OnionWatch-module.zip"
    if r.returncode != 0 or not z.is_file():
        raise RuntimeError(f"building Onion Watch's module failed: {r.stderr[-800:]}")
    return z


def board_run(name: str, out: Path, args, tier: dict, hz: float, scenarios: list[str],
              extra_conf: dict | None = None, watch_zip: Path | None = None,
              triggers: int | None = None) -> tuple[Run, dict]:
    profile = out / "profiles" / name
    data = out / "inputs"
    conf = {
        "profile": str(profile),
        "scenarios": scenarios,
        "secs": tier["secs"],
        "leak_iterations": tier["leak_iterations"],
        "sounds": inputs.board_sounds(data / "board", tier["sounds"]),
        "import_files": inputs.import_sounds(data / "import"),
        "mic_channels": 1,
        "real_window": args.real_window,
        "event_counts": not args.no_event_counts,
        "soak_minutes": args.minutes,
    }
    if watch_zip is not None:
        conf["watch_zip"] = str(watch_zip)
        conf["watch_package"] = "onionwatch"
        conf["triggers"] = inputs.triggers(data / "triggers", triggers or 0)
    conf.update(extra_conf or {})
    profile.mkdir(parents=True, exist_ok=True)
    conf_path = out / f"{name}.child.json"
    conf_path.write_text(json.dumps(conf, indent=1), encoding="utf-8")
    env = child_env(profile, f"perf-{os.getpid()}-{name}", args.real_window, args.env)
    run = Run(name, [sys.executable, "-m", "perf.child_board", str(conf_path)], env, ROOT, hz,
              out / "logs" / f"{name}.log", tier["timeout_s"] if name != "soak" else
              args.minutes * 60 + 300, profile)
    return run, run.run()


def watch_run(name: str, out: Path, args, tier: dict, hz: float, src: Path) -> tuple[Run, dict]:
    profile = out / "profiles" / name
    conf = {"profile": str(profile), "scenarios": WATCH, "secs": tier["secs"],
            "triggers": inputs.triggers(out / "inputs" / "triggers", 10),
            "event_counts": not args.no_event_counts}
    profile.mkdir(parents=True, exist_ok=True)
    conf_path = out / f"{name}.child.json"
    conf_path.write_text(json.dumps(conf, indent=1), encoding="utf-8")
    env = child_env(profile, f"perf-{os.getpid()}-{name}", False, args.env)
    env["ONIONWATCH_HOME"] = str(profile / "OnionWatch")
    env["PYTHONPATH"] = os.pathsep.join([str(src), str(ROOT)])
    run = Run(name, [sys.executable, "-m", "perf.child_watch", str(conf_path)], env, src, hz,
              out / "logs" / f"{name}.log", tier["timeout_s"], profile)
    return run, run.run()


# ------------------------------------------------------------------ the built app

def frozen(exe: Path, out: Path, timeout_s: float = 150) -> dict:
    """Run a built exe with --selftest only (no window, no device, no network), on a
    throwaway profile; sample it every 100 ms."""
    name = exe.stem
    profile = out / "profiles" / f"frozen-{name}"
    env = child_env(profile, f"perf-{os.getpid()}-frozen-{name}", False, {})
    env["ONIONWATCH_HOME"] = str(profile / "OnionWatch")
    t0 = time.perf_counter()
    p = subprocess.Popen([str(exe), "--selftest"], cwd=profile, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=0x08000000)
    peak = {"private_mb_peak": 0, "wset_mb_peak": 0, "threads_peak": 0, "handles_peak": 0,
            "children_peak": 0, "tree_wset_mb_peak": 0}
    timeline = []
    out_text = []
    reader = threading.Thread(target=lambda: out_text.append(p.stdout.read()), daemon=True)
    reader.start()
    try:
        proc = winproc.Proc(p.pid)
    except OSError as e:
        return {"error": str(e)}
    with proc:
        while p.poll() is None:
            if time.perf_counter() - t0 > timeout_s:
                winproc.kill(p.pid)
                break
            try:
                kids = winproc.descendants(p.pid)
                s = proc.sample(kids)
            except OSError:
                break
            row = {"t": round(s.t - t0, 2), "private_mb": round(s.private / winproc.MB),
                   "wset_mb": round(s.wset / winproc.MB), "threads": s.threads,
                   "handles": s.handles, "children": s.children,
                   "tree_wset_mb": round((s.wset + s.children_wset) / winproc.MB)}
            timeline.append(row)
            for k in ("private_mb", "wset_mb", "threads", "handles", "children", "tree_wset_mb"):
                peak[f"{k}_peak"] = max(peak[f"{k}_peak"], row[k])
            time.sleep(0.1)
        p.wait(10)
    reader.join(5)
    took = round(time.perf_counter() - t0, 2)
    folder = exe.parent
    size, files = winproc.folder_size(folder)
    text = (out_text[0] if out_text else b"").decode("utf-8", "replace").strip()
    return {"exe": str(exe), "exit_code": p.returncode, "took_s": took, **peak,
            "stdout": text[-300:], "folder_mb": round(size / winproc.MB, 1), "files": files,
            "biggest": [(n, round(b / winproc.MB, 1)) for n, b in
                        winproc.biggest_files(folder, 20)],
            "timeline": timeline[::5]}


# ------------------------------------------------------------------ main

def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="python -m perf", description=__doc__)
    ap.add_argument("--tier", choices=("quick", "full", "soak", "frozen"), default="quick")
    ap.add_argument("--out", type=Path, help="folder for the report, profiles and logs "
                    "(default: a new folder under %%TEMP%%\\onionboard-perf)")
    ap.add_argument("--watch-src", type=Path, help="an Onion Watch checkout: adds the Triggers "
                    "scenarios (its add-on built from here) and standalone Onion Watch")
    ap.add_argument("--compare", type=Path, help="an earlier report.json: adds before -> after")
    ap.add_argument("--budget", type=Path, default=HERE / "budgets.json")
    ap.add_argument("--no-budget", action="store_true", help="report only, never fail")
    ap.add_argument("--minutes", type=float, default=30.0, help="soak: how long in the tray")
    ap.add_argument("--app-dir", type=Path, help="frozen: the built app's folder "
                    "(OnionBoard.exe in it)")
    ap.add_argument("--watch-exe", type=Path, help="frozen: a built OnionWatch.exe")
    ap.add_argument("--real-window", action="store_true",
                    help="real Windows windows parked off every monitor (catches GPU / driver "
                    "costs). Opens real windows: only with the user's OK")
    ap.add_argument("--no-event-counts", action="store_true",
                    help="leave out the paint / timer counter (it costs a little CPU itself)")
    ap.add_argument("--only", default="", help="comma-separated runs to do: board, triggers, "
                    "watch (default: all that apply)")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                    help="extra environment for the measured app (e.g. OPENBLAS_NUM_THREADS=1)")
    args = ap.parse_args(argv)
    args.env = dict(e.split("=", 1) for e in args.env)
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if not winproc.supported():
        print("perf: the performance suite measures Windows processes; skipped on "
              f"{sys.platform}.")
        return 0
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = (args.out or Path(tempfile.gettempdir()) / "onionboard-perf" / f"{args.tier}-{stamp}")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    hz = winproc.cycles_per_second()
    report = {"tier": args.tier, "started": stamp, "source": str(ROOT.name),
              "machine": {"cpus": os.cpu_count(), "cycles_ghz": round(hz / 1e9, 3),
                          "python": sys.version.split()[0]},
              "env": args.env, "real_window": args.real_window,
              "runs": {}, "scenarios": {}, "errors": []}
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    want = (lambda r: not only or r in only)  # noqa: E731
    print(f"perf {args.tier}: writing to {out}", flush=True)

    def add(run: Run, info: dict, note: str = ""):
        report["runs"][run.name] = {**info, "note": note}
        report["scenarios"].update({f"{run.name}/{k}" if run.name != "board" else k: v
                                    for k, v in run.scenarios.items()})
        report["errors"] += info["errors"]

    if args.tier in ("quick", "full"):
        tier = TIERS[args.tier]
        if want("board"):
            add(*board_run("board", out, args, tier, hz, tier["board"]),
                note=f"{tier['sounds']} sounds, cable route, mono mic, offscreen"
                     + (" (real windows off-monitor)" if args.real_window else ""))
        if args.watch_src and (want("triggers") or want("watch")):
            src = args.watch_src.resolve()
            try:
                zipf = build_watch_zip(src, out / "watch-module")
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                report["errors"].append(f"Onion Watch: {e}")
                zipf = None
            if zipf is not None and want("triggers"):
                for n in tier["trigger_counts"]:
                    add(*board_run(f"triggers-{n}", out, args, tier, hz, TRIGGERS,
                                   watch_zip=zipf, triggers=n),
                        note=f"the board with the Onion Watch add-on built from {src.name}, "
                             f"{n} triggers, stand-in 1920x1080 screen")
            if want("watch"):
                add(*watch_run("watch", out, args, tier, hz, src),
                    note=f"standalone Onion Watch from {src.name}, 10 triggers, stand-in "
                         "screen, silent output")
        elif not args.watch_src:
            report["skipped"] = ("Triggers and standalone Onion Watch: no --watch-src given")
    elif args.tier == "soak":
        tier = dict(TIERS["quick"])
        add(*board_run("soak", out, args, tier, hz, ["soak"],
                       extra_conf={"soak_every_s": 10}),
            note=f"hidden in the tray for {args.minutes:g} minutes, sampled every 10 s")
    elif args.tier == "frozen":
        report["frozen"] = {}
        if args.app_dir:
            exe = args.app_dir / "OnionBoard.exe"
            if exe.is_file():
                print("  OnionBoard.exe --selftest", flush=True)
                report["frozen"]["OnionBoard.exe"] = frozen(exe, out)
            else:
                report["errors"].append(f"no OnionBoard.exe in {args.app_dir}")
        if args.watch_exe:
            if args.watch_exe.is_file():
                print("  OnionWatch.exe --selftest", flush=True)
                report["frozen"]["OnionWatch.exe"] = frozen(args.watch_exe, out)
            else:
                report["errors"].append(f"no {args.watch_exe}")
        if not report["frozen"]:
            report["errors"].append("frozen: give --app-dir and/or --watch-exe")
        for name, f in report["frozen"].items():   # budgets read them like scenarios
            report["scenarios"][f"frozen/{name}"] = {**f, "run": "frozen", "cpu_pct": None}

    report["took_s"] = round(time.perf_counter() - t0, 1)
    over = []
    if not args.no_budget and args.budget and args.budget.is_file():
        budgets = json.loads(args.budget.read_text(encoding="utf-8"))
        over = stats.check_budgets(report, budgets)
        report["over_budget"] = over
    before = None
    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    md = stats.markdown({**report, "scenarios": {k: v for k, v in report["scenarios"].items()
                                                 if not k.startswith("frozen/")}}, before)
    (out / "report.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nreport: {out / 'report.md'}")
    if over:
        print(f"\n{len(over)} over budget:")
        for o in over:
            print("  " + o)
        return 1
    return 1 if report["errors"] and not report["scenarios"] else 0
