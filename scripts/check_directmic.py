"""Check the mic effect's C++ (native/directmic/) without running it: g++ with extra
warnings as errors, GCC's static analyzer, and cppcheck. Exit 0 = nothing found.

    .venv\\Scripts\\python scripts\\check_directmic.py [--need-cppcheck]

Nothing is built or changed (g++ only parses and analyses), so the shipped obmic.dll's
bytes can't move. cppcheck is skipped with a note when it isn't installed (WinLibs
ships it next to g++); --need-cppcheck makes that a failure (CI). The analyzer needs
g++ 14 or newer (older ones can't analyse C++) and is skipped on an older one.

What's switched off, and why:
- cppcheck dangerousTypeCast / invalidPointerCast: Windows hands the effect plain bytes
  (WAVEFORMATEX, APOInitSystemEffects, the shared ring file) that are cast to their
  structs and float samples on purpose; every cast is size-checked first.
- the analyzer's va-list-leak: logv() takes a va_list its callers start and end.
- a finding that's right but deliberate is marked on its line with
  `// cppcheck-suppress <id>` and a reason.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_directmic import SRC, find_gxx  # noqa: E402

# on top of build_directmic's -Wall -Wextra; all quiet on today's code, so a new one fails
STRICT = ["-Wall", "-Wextra", "-Werror", "-Wshadow", "-Wcast-qual", "-Wduplicated-cond",
          "-Wduplicated-branches", "-Wlogical-op", "-Wnull-dereference", "-Wformat=2",
          "-Wundef"]
# each source with the switches it's built with (obmic.cpp twice: the shipped DLL and
# the fuzz build, which has extra code)
SOURCES = [("obmic.cpp", []), ("obmic.cpp", ["-DOBMIC_FUZZ"]), ("testhost.cpp", []),
           ("fuzzhost.cpp", [])]
CPPCHECK_OFF = ["dangerousTypeCast", "invalidPointerCast"]


def gcc_major(gxx: str) -> int:
    out = subprocess.run([gxx, "-dumpversion"], capture_output=True, text=True).stdout
    m = re.match(r"(\d+)", out.strip())
    return int(m.group(1)) if m else 0


def run(cmd: list[str], label: str) -> bool:
    print(f"== {label}", flush=True)
    r = subprocess.run(cmd, cwd=SRC, timeout=600)
    if r.returncode:
        print(f"   FAILED: {label}", flush=True)
    return r.returncode == 0


def find_cppcheck(gxx: str | None) -> str | None:
    if gxx:
        beside = Path(gxx).with_name("cppcheck.exe")
        if beside.is_file():
            return str(beside)
    for p in (shutil.which("cppcheck"), r"C:\Program Files\Cppcheck\cppcheck.exe"):
        if p and Path(p).is_file():
            return p
    return None


def main(argv: list[str]) -> int:
    ok = True
    gxx = find_gxx()
    if not gxx:
        print("g++ not found: install MinGW-w64 (winget install BrechtSanders.WinLibs.POSIX.UCRT)"
              " or set MINGW_GXX", file=sys.stderr)
        return 1
    major = gcc_major(gxx)
    print(f"g++ {major}: {gxx}")
    for src, extra in SOURCES:
        ok &= run([gxx, "-O2", "-fsyntax-only", *STRICT, *extra, src],
                  f"warnings: {src} {' '.join(extra)}".rstrip())
    if major >= 14:
        # -c, not -fsyntax-only: the analyzer runs after parsing; the object is thrown away
        for src, extra in SOURCES[:2]:
            ok &= run([gxx, "-O1", "-c", "-o", "NUL" if sys.platform == "win32" else "/dev/null",
                       "-fanalyzer", "-Werror", "-Wno-analyzer-va-list-leak", *extra, src],
                      f"analyzer: {src} {' '.join(extra)}".rstrip())
    else:
        print(f"== analyzer skipped: g++ {major} can't analyse C++ (needs 14+)")
    cppcheck = find_cppcheck(gxx)
    if cppcheck:
        base = [cppcheck, "--enable=warning,performance,portability", "--inline-suppr",
                "--std=c++17", "--platform=win64", "--error-exitcode=1", "--quiet",
                "-D_WIN32", "-D_WIN64", "-D__x86_64__", "-D__SEH__", "-D__GNUC__",
                *(f"--suppress={s}" for s in CPPCHECK_OFF)]
        for src, extra in SOURCES:
            ok &= run([*base, *extra, src], f"cppcheck: {src} {' '.join(extra)}".rstrip())
    elif "--need-cppcheck" in argv:
        print("cppcheck not found", file=sys.stderr)
        ok = False
    else:
        print("== cppcheck skipped: not installed")
    print("all clean" if ok else "problems found (above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
