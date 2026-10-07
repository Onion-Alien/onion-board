"""Write perf/budgets.json from report.json files: every scenario's measured numbers,
rounded up, become its limits (the runner then allows `tolerance` on top).

    python -m perf.make_budgets quick=OUT1\\report.json full=OUT2\\report.json [...]

A tier given more than one report takes the highest number of each. Use it after a
round of perf fixes lands, on a quiet PC, then look over the diff before committing.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOLERANCE = 0.5
METRICS = {   # metric -> (round up to a multiple of, smallest limit)
    "cpu_pct": (1, 3), "private_mb": (10, 0), "wset_mb": (10, 0), "threads": (1, 0),
    "handles": (10, 0), "disk_write_mb": (1, 2), "startup_s": (0.5, 0),
    "private_mb_per_loop": (0.5, 1), "handles_per_loop": (1, 2),
    "threads_per_loop": (0.5, 0.5), "py_objects_per_loop": (10, 50),
    "private_mb_per_hour": (5, 10), "handles_per_hour": (10, 50),
    "wset_mb_peak": (10, 0), "private_mb_peak": (10, 0), "threads_peak": (1, 0),
    "handles_peak": (10, 0), "took_s": (1, 0), "folder_mb": (10, 0),
}


def up(v: float, step: float, floor: float) -> float:
    r = math.ceil(v / step) * step
    r = max(r, floor)
    return int(r) if float(r).is_integer() else round(r, 2)


def limits(reports: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for rep in reports:
        for scen, m in rep.get("scenarios", {}).items():
            for k, (step, floor) in METRICS.items():
                v = m.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    lim = up(max(v, 0), step, floor)
                    cur = out.setdefault(scen, {}).get(k)
                    out[scen][k] = lim if cur is None else max(cur, lim)
    return out


def dumps(budgets: dict) -> str:
    """JSON with one line per scenario, so a diff shows which limits moved."""
    parts = []
    for k, v in budgets.items():
        if isinstance(v, dict):
            rows = ",\n".join(f"  {json.dumps(s)}: {json.dumps(m)}" for s, m in v.items())
            parts.append(f" {json.dumps(k)}: {{\n{rows}\n }}")
        else:
            parts.append(f" {json.dumps(k)}: {json.dumps(v)}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def main(argv: list[str]) -> int:
    by_tier: dict[str, list[dict]] = {}
    for a in argv:
        tier, _, path = a.partition("=")
        by_tier.setdefault(tier, []).append(json.loads(Path(path).read_text(encoding="utf-8")))
    if not by_tier:
        print(__doc__)
        return 2
    path = HERE / "budgets.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    new = {"_note": "initial limits, set generously from origin/main before the perf "
                    "fixes landed (python -m perf.make_budgets); tighten as they land",
           "tolerance": old.get("tolerance", TOLERANCE)}
    new.update({k: v for k, v in old.items() if k not in new})
    for tier, reps in by_tier.items():
        new[tier] = limits(reps)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(new))
    print(f"wrote {path}: " + ", ".join(f"{t} ({len(new[t])} scenarios)" for t in by_tier))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
