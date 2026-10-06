"""Build the mic effect (native/directmic/obmic.cpp) into build/directmic/obmic.dll,
with MinGW-w64's g++ (no Visual Studio needed). `--testhost` also builds testhost.exe,
which loads the DLL like Windows' audio engine does (tests/test_directmic.py runs it).
`--fuzz` also builds obmic_fuzz.dll (sanitizer traps on, a test switch for the guard)
and fuzzhost.exe, which scripts/fuzz_directmic.py runs.

g++ is found on PATH, or set MINGW_GXX to its full path. The DLL links everything
statically, so it needs only DLLs every Windows 10/11 PC has.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "native" / "directmic"
OUT = ROOT / "build" / "directmic"
FLAGS = ["-O2", "-Wall", "-Wextra", "-static", "-static-libgcc", "-static-libstdc++",
         "-fno-exceptions", "-s"]
# the fuzz build: the same code, any undefined behaviour a fault (no runtime needed)
FUZZ_FLAGS = [f for f in FLAGS if f != "-s"] + [
    "-g", "-DOBMIC_FUZZ", "-fsanitize=undefined,float-cast-overflow,float-divide-by-zero",
    "-fsanitize-trap=all", "-fno-omit-frame-pointer"]


def find_gxx() -> str | None:
    env = os.environ.get("MINGW_GXX")
    if env and Path(env).is_file():
        return env
    found = shutil.which("g++")
    if found:
        return found
    # winget's WinLibs package
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for p in sorted(base.glob("BrechtSanders.WinLibs*/mingw64/bin/g++.exe")):
        return str(p)
    return None


def build(testhost: bool = False, fuzz: bool = False) -> int:
    gxx = find_gxx()
    if not gxx:
        print("g++ not found: install MinGW-w64 (winget install BrechtSanders.WinLibs.POSIX.UCRT)"
              " or set MINGW_GXX", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [[gxx, *FLAGS, "-shared", "-o", str(OUT / "obmic.dll"), str(SRC / "obmic.cpp"),
             "-lole32", "-ladvapi32", "-luuid"]]
    if testhost:
        jobs.append([gxx, *FLAGS, "-o", str(OUT / "testhost.exe"), str(SRC / "testhost.cpp"),
                     "-lole32", "-lwinmm", "-luuid"])
    if fuzz:
        jobs.append([gxx, *FUZZ_FLAGS, "-shared", "-o", str(OUT / "obmic_fuzz.dll"),
                     str(SRC / "obmic.cpp"), "-lole32", "-ladvapi32", "-luuid"])
        jobs.append([gxx, *FLAGS, "-o", str(OUT / "fuzzhost.exe"), str(SRC / "fuzzhost.cpp"),
                     "-lole32", "-luuid"])
    for cmd in jobs:
        r = subprocess.run(cmd, cwd=SRC)
        if r.returncode:
            return r.returncode
    print(f"built {OUT / 'obmic.dll'}")
    return 0


if __name__ == "__main__":
    sys.exit(build("--testhost" in sys.argv, "--fuzz" in sys.argv))
