"""The maths and the words: per-phase numbers from the samples, slopes, budgets, and
report.md. No Windows calls here, so it is tested on its own (tests/test_perf_metrics.py).
"""
from __future__ import annotations

import math

MB = 1024 * 1024


def percentile(values, q: float) -> float | None:
    """The q-th percentile (0..100) with linear interpolation; None for no values."""
    v = sorted(values)
    if not v:
        return None
    if len(v) == 1:
        return float(v[0])
    k = (len(v) - 1) * q / 100.0
    lo = math.floor(k)
    hi = min(lo + 1, len(v) - 1)
    return float(v[lo] + (v[hi] - v[lo]) * (k - lo))


def slope(xs, ys) -> float | None:
    """Least-squares slope of ys against xs; None with fewer than 2 distinct xs."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def rnd(v, nd: int = 1):
    return None if v is None else round(v, nd)


def phase_metrics(a: dict, b: dict, during: list[dict], hz: float) -> dict:
    """What a phase cost, from the samples at its start (`a`) and end (`b`) plus the
    ones taken in between (`during`, for peaks). Samples are Sample.as_dict()s; `hz`
    is cycles per second (winproc.cycles_per_second)."""
    wall = max(1e-9, b["t"] - a["t"])
    every = [a, *during, b]
    cpu_s = (b["cycles"] - a["cycles"]) / hz if hz else \
        (b["cpu_user"] + b["cpu_kernel"] - a["cpu_user"] - a["cpu_kernel"])
    times_s = b["cpu_user"] + b["cpu_kernel"] - a["cpu_user"] - a["cpu_kernel"]
    kernel_s = b["cpu_kernel"] - a["cpu_kernel"]
    return {
        "wall_s": rnd(wall, 2),
        "cpu_pct": rnd(100 * cpu_s / wall, 2),            # of one core
        "kernel_pct": rnd(100 * kernel_s / wall, 2),
        "cpu_times_pct": rnd(100 * times_s / wall, 2),    # GetProcessTimes (15.6 ms ticks)
        "private_mb": rnd(b["private"] / MB),
        "private_mb_start": rnd(a["private"] / MB),
        "private_mb_peak": rnd(max(s["private"] for s in every) / MB),
        "wset_mb": rnd(b["wset"] / MB),
        "wset_mb_peak": rnd(max(s["wset"] for s in every) / MB),
        "threads": b["threads"],
        "threads_peak": max(s["threads"] for s in every),
        "handles": b["handles"],
        "handles_peak": max(s["handles"] for s in every),
        "gdi": b["gdi"],
        "user": b["user"],
        "disk_write_mb": rnd((b["write_bytes"] - a["write_bytes"]) / MB, 2),
        "disk_read_mb": rnd((b["read_bytes"] - a["read_bytes"]) / MB, 2),
        "write_ops": b["write_ops"] - a["write_ops"],
        "page_faults_per_s": rnd((b["page_faults"] - a["page_faults"]) / wall, 0),
        "children": b.get("children", 0),
        "children_private_mb": rnd(b.get("children_private", 0) / MB),
        "children_wset_mb": rnd(b.get("children_wset", 0) / MB),
    }


def group_pct(cycles: dict[str, int], wall: float, hz: float) -> dict[str, float]:
    """Cycles per thread group as % of one core, biggest first, tiny ones dropped."""
    if not hz or wall <= 0:
        return {}
    out = {g: round(100 * c / hz / wall, 2) for g, c in cycles.items()}
    return dict(sorted(((g, v) for g, v in out.items() if v >= 0.01), key=lambda kv: -kv[1]))


def slopes(points: list[dict], x: str, keys: dict[str, tuple[str, float]],
           skip: int = 1) -> dict[str, float | None]:
    """Growth per unit of `x` for each key (name -> (sample field, divisor)), from the
    points after the first `skip` (warm-up: caches filling are not a leak)."""
    pts = points[skip:] if len(points) - skip >= 2 else points
    xs = [p[x] for p in pts]
    return {name: rnd(None if (s := slope(xs, [p[f] / div for p in pts])) is None else s, 3)
            for name, (f, div) in keys.items()}


def audio_summary(streams: dict[str, dict]) -> dict:
    """Worst stream's numbers, from the child's per-stream stats."""
    if not streams:
        return {}
    worst = lambda k: max((s.get(k) or 0) for s in streams.values())  # noqa: E731
    return {"late_p99_ms": rnd(worst("late_p99_ms"), 2), "late_max_ms": rnd(worst("late_max_ms"), 2),
            "cb_p50_ms": rnd(worst("cb_p50_ms"), 3), "cb_p99_ms": rnd(worst("cb_p99_ms"), 3),
            "late_blocks": sum(s.get("late_blocks", 0) for s in streams.values()),
            "xruns": sum(s.get("xruns", 0) for s in streams.values()),
            "blocks": sum(s.get("blocks", 0) for s in streams.values())}


# ------------------------------------------------------------------ budgets

def check_budgets(report: dict, budgets: dict) -> list[str]:
    """What's over budget, in plain words. budgets.json:
    {"tolerance": 0.25, "<tier>": {"<scenario>": {"<metric>": limit, ...}}}
    A metric is over when it's above limit * (1 + tolerance). A scenario that didn't
    run is skipped (its add-on wasn't given, say), a metric it doesn't have too."""
    tol = float(budgets.get("tolerance", 0.0))
    tier = budgets.get(report.get("tier", ""), {})
    over = []
    for scen, limits in tier.items():
        got = report.get("scenarios", {}).get(scen)
        if got is None:
            continue
        for metric, limit in limits.items():
            v = got.get(metric)
            if v is None or limit is None:
                continue
            allowed = limit * (1 + tol) if limit >= 0 else limit
            if v > allowed:
                over.append(f"{scen}: {metric} = {v} (budget {limit}, allowed up to "
                            f"{round(allowed, 2)})")
    return over


# ------------------------------------------------------------------ report.md

COLUMNS = (   # (heading, metric key, digits)
    ("CPU % core", "cpu_pct", 1),
    ("private MB", "private_mb", 0),
    ("RAM (WS) MB", "wset_mb", 0),
    ("threads", "threads", 0),
    ("handles", "handles", 0),
    ("GDI/USER", None, 0),
    ("disk write MB", "disk_write_mb", 1),
    ("audio late p99 ms", "late_p99_ms", 1),
    ("callback p99 ms", "cb_p99_ms", 2),
    ("late blocks", "late_blocks", 0),
)


def _fmt(v, nd: int) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}" if nd else f"{v:.0f}"
    return str(v)


def _cell(m: dict, key, nd, old: dict | None) -> str:
    if key is None:
        now = f"{m.get('gdi', '-')}/{m.get('user', '-')}"
        if old is not None:
            return f"{old.get('gdi', '-')}/{old.get('user', '-')} → {now}"
        return now
    now = _fmt(m.get(key), nd)
    if old is None:
        return now
    return f"{_fmt(old.get(key), nd)} → {now}"


def markdown(report: dict, before: dict | None = None) -> str:
    """report.md: a table per child process, one row per scenario."""
    lines = [f"# Performance report: {report.get('tier', '?')} tier", ""]
    info = report.get("machine", {})
    if info:
        lines.append(f"{info.get('cpus', '?')} logical CPUs, cycle counter "
                     f"{info.get('cycles_ghz', '?')} GHz, Python {info.get('python', '?')}, "
                     f"{report.get('started', '')}. Took {report.get('took_s', '?')} s.")
        lines.append("")
    if before is not None:
        lines.append(f"Each cell is before → after (before: {before.get('started', '?')}, "
                     f"{before.get('source', '?')}).")
        lines.append("")
    old_sc = (before or {}).get("scenarios", {})
    by_run: dict[str, list[str]] = {}
    for name, m in report.get("scenarios", {}).items():
        by_run.setdefault(m.get("run", ""), []).append(name)
    for run, names in by_run.items():
        lines += [f"## {run}", ""]
        note = report.get("runs", {}).get(run, {}).get("note")
        if note:
            lines += [note, ""]
        lines.append("| scenario | " + " | ".join(c[0] for c in COLUMNS) + " |")
        lines.append("|" + "---|" * (len(COLUMNS) + 1))
        for name in names:
            m = report["scenarios"][name]
            old = old_sc.get(name) if before is not None else None
            cells = [_cell(m, k, nd, old) for _h, k, nd in COLUMNS]
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
        for name in names:
            m = report["scenarios"][name]
            extra = []
            if m.get("seconds") is not None:
                extra.append(f"took {m['seconds']} s")
            if m.get("cpu_by_group"):
                extra.append("CPU by thread group (% of a core): " + ", ".join(
                    f"{g} {v}" for g, v in list(m["cpu_by_group"].items())[:7]))
            if m.get("threads_by_group"):
                extra.append("threads: " + ", ".join(
                    f"{g} {v}" for g, v in list(m["threads_by_group"].items())[:8]))
            if m.get("paints_per_s") is not None:
                extra.append(f"{m['paints_per_s']} paints/s, {m.get('timers_per_s')} timer "
                             f"events/s")
            for k in ("widgets", "qobjects", "py_objects", "children"):
                if m.get(k):
                    extra.append(f"{k.replace('_', ' ')} {m[k]}")
            if m.get("slopes"):
                extra.append("growth per " + m.get("slope_unit", "step") + ": " + ", ".join(
                    f"{k} {v}" for k, v in m["slopes"].items() if v is not None))
            if m.get("notes"):
                extra.append(m["notes"])
            if extra:
                lines.append(f"- **{name}**: " + "; ".join(extra) + ".")
        lines.append("")
    if report.get("frozen"):
        lines += ["## Built app (--selftest only)", "",
                  "| exe | exit code | took s | peak private MB | peak RAM (WS) MB | peak threads "
                  "| peak handles | children | folder MB |", "|---|---|---|---|---|---|---|---|---|"]
        for name, f in report["frozen"].items():
            lines.append(f"| {name} | {f.get('exit_code')} | {f.get('took_s')} | "
                         f"{f.get('private_mb_peak')} | {f.get('wset_mb_peak')} | "
                         f"{f.get('threads_peak')} | {f.get('handles_peak')} | "
                         f"{f.get('children_peak')} | {f.get('folder_mb')} |")
        lines.append("")
        for name, f in report["frozen"].items():
            if f.get("biggest"):
                lines.append(f"Biggest files of {name}: " + ", ".join(
                    f"{p} {mb} MB" for p, mb in f["biggest"]) + ".")
                lines.append("")
    if report.get("over_budget") is not None:
        if report["over_budget"]:
            lines += ["## Over budget", ""] + [f"- {o}" for o in report["over_budget"]] + [""]
        else:
            lines += ["Everything is within its budget.", ""]
    if report.get("errors"):
        lines += ["## Problems", ""] + [f"- {e}" for e in report["errors"]] + [""]
    return "\n".join(lines)
