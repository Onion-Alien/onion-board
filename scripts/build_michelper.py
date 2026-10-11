"""Build the mic helper (soundboard/michelper.py) into build/michelper/obmichelper/:
obmichelper.exe, a small PyInstaller build of the mic effect's admin part only (no Qt,
no numpy), with its own copy of the effect DLL and stamp.txt saying which. build.ps1
runs it after scripts/build_directmic.py and bundles the folder with the app as
michelper\\; from source, soundboard.michelper finds it here.

Usage: python scripts/build_michelper.py [--clean]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DLL = ROOT / "build" / "directmic" / "obmic.dll"
OUT = ROOT / "build" / "michelper"
WORK = ROOT / "build" / "michelper-work"
# everything else the app ships: the helper imports none of it
EXCLUDE = ("numpy", "PySide6", "shiboken6", "scipy", "sounddevice", "soundfile", "soxr",
           "yt_dlp", "curl_cffi", "tkinter")


def version_file() -> Path:
    """The .exe's version resource: Windows (and security tools) see what it is."""
    sys.path.insert(0, str(ROOT))
    import soundboard
    from scripts import version_info
    text = version_info.render(soundboard.__version__)
    text = text.replace("StringStruct('FileDescription', 'Onion Board')",
                        "StringStruct('FileDescription', 'Onion Board mic helper')")
    text = text.replace("'OnionBoard.exe'", "'obmichelper.exe'")
    text = text.replace("StringStruct('InternalName', 'OnionBoard')",
                        "StringStruct('InternalName', 'obmichelper')")
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "version_info.txt"
    out.write_text(text, encoding="utf-8")
    return out


def build(clean: bool = False) -> int:
    if not DLL.is_file():
        print(f"no {DLL}: run scripts/build_directmic.py first", file=sys.stderr)
        return 1
    sys.path.insert(0, str(ROOT))
    from soundboard import michelper
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
           "--name", "obmichelper", "--distpath", str(OUT), "--workpath", str(WORK),
           "--specpath", str(WORK), "--version-file", str(version_file()),
           "--add-binary", f"{DLL}{os.pathsep}directmic", "--paths", str(ROOT)]
    if clean:
        cmd.append("--clean")
    for mod in EXCLUDE:
        cmd += ["--exclude-module", mod]
    # PyInstaller finds DLLs on PATH too: only Windows' own (as build.ps1 does)
    env = {**os.environ, "PATH": os.pathsep.join(
        str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / p)
        for p in ("System32", "", r"System32\Wbem"))}
    r = subprocess.run([*cmd, str(ROOT / "soundboard" / "michelper.py")], cwd=ROOT, env=env)
    if r.returncode:
        return r.returncode
    folder = OUT / "obmichelper"
    r = subprocess.run([str(folder / michelper.EXE_NAME), "--selftest"], timeout=60)
    if r.returncode:
        print(f"the built mic helper failed its self-test ({r.returncode})", file=sys.stderr)
        return 1
    (folder / michelper.STAMP).write_text(michelper.make_stamp(DLL), encoding="ascii")
    shutil.rmtree(WORK / "obmichelper", ignore_errors=True)
    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    print(f"built {folder} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(build("--clean" in sys.argv))
