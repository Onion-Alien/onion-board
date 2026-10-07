"""perf/ (the real-use performance suite): its maths, budgets, report and the Windows
process readers on this process. Fast and headless; the suite itself runs with
`python -m perf` (see perf/README.md)."""
import os
import sys

import pytest

from perf import link, stats, winproc


def test_percentile_and_slope():
    assert stats.percentile([], 50) is None
    assert stats.percentile([7], 99) == 7.0
    assert stats.percentile([1, 2, 3, 4, 5], 50) == 3.0
    assert stats.percentile([0, 10], 90) == pytest.approx(9.0)
    assert stats.slope([0, 1, 2, 3], [5, 7, 9, 11]) == pytest.approx(2.0)
    assert stats.slope([1, 1], [1, 2]) is None
    assert stats.slope([1], [1]) is None


def _sample(t, cycles, private_mb, **kw):
    s = {"t": t, "cycles": cycles, "cpu_user": 0.0, "cpu_kernel": 0.0,
         "private": private_mb * stats.MB, "wset": private_mb * 2 * stats.MB,
         "threads": 10, "handles": 300, "gdi": 20, "user": 15, "write_bytes": 0,
         "read_bytes": 0, "write_ops": 0, "page_faults": 0}
    s.update(kw)
    return s


def test_phase_metrics_cpu_peaks_and_disk():
    a = _sample(0.0, 0, 100)
    mid = _sample(1.0, 0, 180, threads=14)
    b = _sample(2.0, 1_000_000_000, 120, write_bytes=3 * stats.MB, write_ops=5)
    m = stats.phase_metrics(a, b, [mid], hz=1e9)
    assert m["cpu_pct"] == 50.0                 # 1 s of cycles in 2 s
    assert m["private_mb"] == 120.0 and m["private_mb_start"] == 100.0
    assert m["private_mb_peak"] == 180.0
    assert m["threads"] == 10 and m["threads_peak"] == 14
    assert m["disk_write_mb"] == 3.0 and m["write_ops"] == 5


def test_slopes_skip_warm_up():
    pts = [{"i": 0, "private": 500}] + [{"i": i, "private": 100 + 4 * i} for i in range(1, 6)]
    got = stats.slopes(pts, "i", {"private_mb": ("private", 1)})
    assert got["private_mb"] == 4.0
    assert stats.group_pct({"qt": 5e8, "tiny": 1}, 1.0, 1e9) == {"qt": 50.0}


def test_budgets_tolerance_and_missing():
    report = {"tier": "quick", "scenarios": {
        "idle_front": {"cpu_pct": 12.0, "private_mb": 200.0},
        "tray": {"cpu_pct": 3.0}}}
    budgets = {"tolerance": 0.25, "quick": {
        "idle_front": {"cpu_pct": 10, "private_mb": 300},   # 12 <= 12.5: fine
        "tray": {"cpu_pct": 2, "threads": 5},               # 3 > 2.5; threads not measured
        "never_ran": {"cpu_pct": 0}}}
    over = stats.check_budgets(report, budgets)
    assert len(over) == 1 and over[0].startswith("tray: cpu_pct = 3.0")


def test_markdown_compare_and_problems():
    report = {"tier": "quick", "scenarios": {"tray": {
        "run": "board", "cpu_pct": 1.5, "private_mb": 150.0, "gdi": 3, "user": 4,
        "cpu_by_group": {"qt": 1.0}}}, "errors": ["board: oops"], "over_budget": []}
    before = {"started": "x", "scenarios": {"tray": {"cpu_pct": 3.0, "private_mb": 200.0}}}
    md = stats.markdown(report, before)
    assert "| tray | 3.0 → 1.5 | 200 → 150 |" in md
    assert "qt 1.0" in md and "oops" in md and "within its budget" in md


def test_make_budgets_rounds_up_and_takes_the_highest():
    from perf import make_budgets
    a = {"scenarios": {"tray": {"cpu_pct": 1.2, "private_mb": 613.4, "threads": 39,
                                "notes": "text is skipped"}}}
    b = {"scenarios": {"tray": {"cpu_pct": 4.1, "private_mb": 600.0, "threads": 41}}}
    got = make_budgets.limits([a, b])["tray"]
    assert got == {"cpu_pct": 5, "private_mb": 620, "threads": 41}
    assert make_budgets.up(0.2, 0.5, 1) == 1 and make_budgets.up(3.66, 0.5, 0) == 4


def test_link_parse():
    assert link.parse('@@perf {"ev": "start", "name": "x"}') == {"ev": "start", "name": "x"}
    assert link.parse("hello") is None
    assert link.parse("@@perf [1]") is None
    assert link.parse("@@perf {bad") is None


def test_thread_groups():
    assert winproc.group_of("libopenblas64_.dll") == "openblas"
    assert winproc.group_of("Qt6Core.dll") == "qt"
    assert winproc.group_of("OnionBoard.exe", "OnionBoard.exe") == "main"
    assert winproc.group_of("foo.dll") == "other: foo"
    mods = [(1000, 100, "a.dll"), (5000, 10, "b.dll")]
    assert winproc.owner_of(1050, mods) == "a.dll"
    assert winproc.owner_of(5010, mods) == "?"
    assert winproc.owner_of(None, mods) == "?"


@pytest.mark.skipif(sys.platform != "win32", reason="reads Windows processes")
def test_reads_this_process():
    with winproc.Proc(os.getpid()) as p:
        s = p.sample([])
        t = p.sample([], winproc.processes())
        assert p.alive()
    assert t.threads == s.threads
    assert s.private > 10 * stats.MB and s.wset > 0
    assert s.threads >= 1 and s.handles > 10
    assert s.cycles > 0
    assert os.getpid() not in winproc.descendants(os.getpid())
