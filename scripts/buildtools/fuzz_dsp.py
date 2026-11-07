"""Fuzz the audio maths: run native/dsp/fuzzhost.cpp against the fuzz DLL (both built by
`scripts/buildtools/build_dsp.py --fuzz`) on a few workers, each with its own seed. Exit
0 = no crash, hang, undefined behaviour or wrongly accepted call.

    .venv\\Scripts\\python scripts\\buildtools\\fuzz_dsp.py [seconds=60] [workers=2] [seed=1]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "dsp"
HOST = OUT / "fuzzhost.exe"
DLL = OUT / "obdsp_fuzz.dll"


def main(argv: list[str]) -> int:
    seconds = float(argv[0]) if argv else 60.0
    workers = int(argv[1]) if len(argv) > 1 else 2
    seed = int(argv[2]) if len(argv) > 2 else 1
    if not (HOST.is_file() and DLL.is_file()):
        print("build it first: scripts/buildtools/build_dsp.py --fuzz", file=sys.stderr)
        return 2
    procs = [subprocess.Popen([str(HOST), str(DLL), str(seconds), str(seed + n)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
             for n in range(workers)]
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
        print(f"worker {n} (seed {seed + n}): exit {p.returncode:#x}: {out.strip()[-300:]}")
        bad += p.returncode != 0
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
