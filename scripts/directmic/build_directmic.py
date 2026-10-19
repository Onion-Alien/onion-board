"""Build the mic effect (native/directmic/obmic.cpp) into build/directmic/obmic.dll,
with MinGW-w64's g++ (no Visual Studio needed). `--testhost` also builds testhost.exe,
which loads the DLL like Windows' audio engine does (tests/test_directmic.py runs it).
`--fuzz` also builds obmic_fuzz.dll (sanitizer traps on, a test switch for the guard)
and fuzzhost.exe, which scripts/directmic/fuzz_directmic.py runs.

g++ is found on PATH, or set MINGW_GXX to its full path. The DLL links everything
statically, so it needs only DLLs every Windows 10/11 PC has.

obmic.dll also gets a version resource (Windows' Details tab and security tools read
it): an unsigned, nameless audio effect looks more suspicious to anti-cheat and AV
heuristics than one that says what it is. The version comes from soundboard.__version__
and the text is a fixed string, so the same source still gives the same bytes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "native" / "directmic"
OUT = ROOT / "build" / "directmic"
# the resource strings: the same names the app's own OnionBoard.exe carries
# (scripts/buildtools/version_info.py), so Windows shows one consistent publisher
NAME = "Onion Board"
PUBLISHER = "Onion Alien"
COPYRIGHT = "Copyright (C) Onion Board contributors"
DESCRIPTION = "Onion Board microphone effect"
FLAGS = ["-O2", "-Wall", "-Wextra", "-static", "-static-libgcc", "-static-libstdc++",
         "-fno-exceptions", "-s",
         # the same source gives the same bytes: the app tells an older mic part by
         # its bytes (directmic.same_dll), and a link-time stamp or a path-based image
         # base made every build look like an update (an admin prompt each version)
         "-Wl,--no-insert-timestamp", "-Wl,--disable-auto-image-base"]
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


def find_windres(gxx: str) -> str | None:
    """windres (the resource compiler) sits next to g++ in a MinGW-w64 install."""
    beside = Path(gxx).with_name("windres.exe")
    if beside.is_file():
        return str(beside)
    return shutil.which("windres")


def version() -> str:
    """soundboard.__version__, read from the file (no import: this runs before Python
    is set up), the same one the app's OnionBoard.exe shows."""
    text = (ROOT / "soundboard" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", text, re.M)
    if not m:
        raise SystemExit("no __version__ in soundboard/__init__.py")
    return m.group(1)


def numbers(v: str) -> str:
    """'1.6.5' -> '1,6,5,0'; a suffix like '1.7.0b1' keeps only the numbers."""
    parts = [int(p) for p in re.findall(r"\d+", v.split("+")[0])[:3]]
    return ",".join(str(n) for n in parts + [0] * (4 - len(parts)))


def write_rc(path: Path, v: str) -> None:
    """A VERSIONINFO resource for obmic.dll: FileType 0x2 is a DLL. The translation
    (0409, 1200) matches the app's .exe, and no field is a timestamp, so two builds
    of the same version are byte-identical."""
    path.write_text(f"""\
#include <winver.h>
VS_VERSION_INFO VERSIONINFO
 FILEVERSION {numbers(v)}
 PRODUCTVERSION {numbers(v)}
 FILEFLAGSMASK 0x3fL
 FILEFLAGS 0x0L
 FILEOS 0x40004L
 FILETYPE 0x2L
 FILESUBTYPE 0x0L
BEGIN
    BLOCK "StringFileInfo"
    BEGIN
        BLOCK "040904b0"
        BEGIN
            VALUE "CompanyName", "{PUBLISHER}"
            VALUE "FileDescription", "{DESCRIPTION}"
            VALUE "FileVersion", "{v}"
            VALUE "InternalName", "obmic"
            VALUE "LegalCopyright", "{COPYRIGHT}"
            VALUE "OriginalFilename", "obmic.dll"
            VALUE "ProductName", "{NAME}"
            VALUE "ProductVersion", "{v}"
        END
    END
    BLOCK "VarFileInfo"
    BEGIN
        VALUE "Translation", 0x409, 1200
    END
END
""", encoding="utf-8")


def build(testhost: bool = False, fuzz: bool = False) -> int:
    gxx = find_gxx()
    if not gxx:
        print("g++ not found: install MinGW-w64 (winget install BrechtSanders.WinLibs.POSIX.UCRT)"
              " or set MINGW_GXX", file=sys.stderr)
        return 1
    windres = find_windres(gxx)
    if not windres:
        print("windres not found next to g++ (a full MinGW-w64 install has it)", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    rc = OUT / "obmic.rc"
    res = OUT / "obmic_res.o"
    write_rc(rc, version())
    r = subprocess.run([windres, "-O", "coff", "-o", str(res), str(rc)], cwd=SRC)
    if r.returncode:
        return r.returncode
    jobs = [[gxx, *FLAGS, "-shared", "-o", str(OUT / "obmic.dll"), str(SRC / "obmic.cpp"),
             str(res), "-lole32", "-ladvapi32", "-luuid"]]
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
