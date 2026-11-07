"""Build the audio maths (native/dsp/obdsp.cpp) into build/dsp/obdsp.dll (libobdsp.so on
Linux), with the same g++ as the mic effect. `--fuzz` also builds the fuzz DLL (any
undefined behaviour a fault) and native/dsp/fuzzhost.cpp, which
scripts/buildtools/fuzz_dsp.py runs.

No -march: it has to run on any 64-bit PC, so SSE2 is what it gets. No fast-math and no
fused multiply-adds: its float sums match the Python versions' to the last rounding.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "directmic"))
from build_directmic import find_gxx  # noqa: E402

SRC = ROOT / "native" / "dsp"
OUT = ROOT / "build" / "dsp"
WIN = sys.platform == "win32"
NAME = "obdsp.dll" if WIN else "libobdsp.so"
FUZZ_NAME = "obdsp_fuzz.dll" if WIN else "libobdsp_fuzz.so"
FLAGS = ["-O3", "-Wall", "-Wextra", "-fno-exceptions", "-fno-rtti", "-ffp-contract=off",
         "-fno-math-errno", "-fopenmp-simd", "-std=c++17"]
LINK = (["-static", "-static-libgcc", "-static-libstdc++", "-Wl,--no-insert-timestamp"]
        if WIN else ["-fPIC", "-static-libgcc", "-static-libstdc++"])
FUZZ = ["-g", "-fsanitize=undefined,float-cast-overflow", "-fsanitize-trap=all",
        "-fno-omit-frame-pointer"]


def build(fuzz: bool = False) -> int:
    gxx = find_gxx()
    if not gxx:
        print("g++ not found: install MinGW-w64 (winget install BrechtSanders.WinLibs.POSIX.UCRT)"
              " or set MINGW_GXX", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [[gxx, *FLAGS, *LINK, "-s", "-shared", "-o", str(OUT / NAME), str(SRC / "obdsp.cpp")]]
    if fuzz:
        jobs.append([gxx, *FLAGS, *FUZZ, *LINK, "-shared", "-o", str(OUT / FUZZ_NAME),
                     str(SRC / "obdsp.cpp")])
        jobs.append([gxx, *FLAGS, *LINK, "-s", "-o", str(OUT / "fuzzhost.exe"),
                     str(SRC / "fuzzhost.cpp")])
    for cmd in jobs:
        r = subprocess.run(cmd, cwd=SRC)
        if r.returncode:
            return r.returncode
    print(f"built {OUT / NAME} ({(OUT / NAME).stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(build("--fuzz" in sys.argv))
