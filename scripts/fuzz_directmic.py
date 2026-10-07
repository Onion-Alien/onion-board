"""Fuzz the mic effect: run native/directmic/fuzzhost.cpp against obmic_fuzz.dll (both
built by `scripts/build_directmic.py --fuzz`) on a few workers, each with its own seed
and folder, and sum up. Exit 0 = no crash, hang, caught fault or bad sample.

    .venv\\Scripts\\python scripts\\fuzz_directmic.py [seconds=120] [workers=2] [seed=1] [--low]

--low runs the workers at below-normal priority (for a PC that's busy with a game).
A finding prints its case seed: `fuzzhost <dll> <dir> --replay <seed>` runs that case
alone, verbosely. Nothing touches the PC's audio: the effect only sees files in a
temporary folder.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "directmic"
HOST = BUILD / "fuzzhost.exe"
DLL = BUILD / "obmic_fuzz.dll"
BELOW_NORMAL = 0x00004000


def main(argv: list[str]) -> int:
    low = "--low" in argv
    args = [a for a in argv if not a.startswith("--")]
    seconds = float(args[0]) if args else 120.0
    workers = int(args[1]) if len(args) > 1 else 2
    seed = int(args[2]) if len(args) > 2 else 1
    if not (HOST.is_file() and DLL.is_file()):
        print("build it first: scripts/build_directmic.py --fuzz", file=sys.stderr)
        return 2
    flags = BELOW_NORMAL if low and sys.platform == "win32" else 0
    with tempfile.TemporaryDirectory(prefix="obfuzz-") as tmp:
        procs = []
        for n in range(workers):
            work = Path(tmp) / f"w{n}"
            procs.append(subprocess.Popen(
                [str(HOST), str(DLL), str(work), str(seconds), str(seed + n)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=flags))
        bad = 0
        for n, p in enumerate(procs):
            try:
                out, _ = p.communicate(timeout=seconds + 60)
            except subprocess.TimeoutExpired:
                p.kill()
                out, _ = p.communicate()
                print(f"worker {n}: stuck past its time, stopped")
                bad += 1
                continue
            last = [ln for ln in out.splitlines() if ln.startswith(("done", "CRASH", "HANG",
                                                                    "FINDING"))]
            print(f"worker {n} (seed {seed + n}): exit {p.returncode}")
            for ln in last[-6:]:
                print("  " + ln)
            bad += p.returncode != 0
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
