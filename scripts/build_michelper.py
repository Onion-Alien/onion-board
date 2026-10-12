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
# build_bootloader.ps1 leaves this beside the bootloaders it compiled, with their SHA-256s.
# The stock ones from PyPI are in thousands of programs, some of them malware, so virus
# scanners flagged a helper built with one. A file that doesn't match (a stock wheel
# reinstalled over it, a PyInstaller upgrade) counts as stock: that works for any
# PyInstaller version, where a list of stock hashes would go stale at the next upgrade.
MARKER = "compiled-here.txt"
BOOTLOADERS = ("run.exe", "runw.exe")


def bootloader_hashes(folder: Path) -> str:
    import hashlib
    return "".join(f"{hashlib.sha256((folder / n).read_bytes()).hexdigest()}  {n}\n"
                   for n in BOOTLOADERS)


def stock_bootloader(folder: Path | None = None) -> str:
    """PyInstaller's version when its bootloader wasn't compiled here
    (scripts/build_bootloader.ps1), else ''."""
    import PyInstaller
    folder = folder or Path(PyInstaller.__file__).parent / "bootloader" / "Windows-64bit-intel"
    try:
        if (folder / MARKER).read_text(encoding="utf-8") == bootloader_hashes(folder):
            return ""
    except OSError:
        pass
    return PyInstaller.__version__


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
    if stock := stock_bootloader():
        # Not fatal: a dev build (or one on a machine without MinGW-w64's gcc) should
        # still produce a working helper. build.ps1 compiles a local bootloader before
        # we get here, so release builds are clean; only direct/no-compiler builds fall
        # back to the stock one, with this warning.
        print(f"warning: PyInstaller {stock} has its stock bootloader, which some virus"
              " scanners flag as a false positive. Run scripts/build_bootloader.ps1 for a"
              " clean build (needs MinGW-w64's gcc).", file=sys.stderr)
    sys.path.insert(0, str(ROOT))
    from soundboard import michelper
    # --console, not --windowed: a windowed build still drew a couple of antivirus false
    # positives on VirusTotal where a console one is clean. No window is shown either way
    # -- the helper only ever runs as a hidden SYSTEM scheduled task (see michelper.py),
    # which has no interactive desktop.
    spec_cmd = [sys.executable, "-m", "PyInstaller.utils.cliutils.makespec", "--onedir",
                "--console", "--name", "obmichelper", "--specpath", str(WORK),
                "--version-file", str(version_file()),
                "--icon", str(ROOT / "assets" / "onionboard.ico"),
                "--add-binary", f"{DLL}{os.pathsep}directmic", "--paths", str(ROOT)]
    for mod in EXCLUDE:
        spec_cmd += ["--exclude-module", mod]
    # PyInstaller finds DLLs on PATH too: only Windows' own (as build.ps1 does)
    env = {**os.environ, "PATH": os.pathsep.join(
        str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / p)
        for p in ("System32", "", r"System32\Wbem"))}
    r = subprocess.run([*spec_cmd, str(ROOT / "soundboard" / "michelper.py")], cwd=ROOT,
                       env=env, stdout=subprocess.DEVNULL)
    if r.returncode:
        return r.returncode
    # The Python part (PKG) as obmichelper.pkg beside the .exe, not appended to it: an
    # .exe with a PyInstaller archive on its end is what virus scanners flag (Bkav,
    # Panda: even Onion Watch's .exe), the bootloader alone isn't
    spec = WORK / "obmichelper.spec"
    text = spec.read_text(encoding="utf-8")
    end = "\n)\ncoll = COLLECT("
    if text.count(end) != 1:
        print(f"unexpected {spec}: no EXE(...) before COLLECT", file=sys.stderr)
        return 1
    spec.write_text(text.replace(end, "\n    append_pkg=False," + end), encoding="utf-8")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(OUT),
           "--workpath", str(WORK)]
    if clean:
        cmd.append("--clean")
    r = subprocess.run([*cmd, str(spec)], cwd=ROOT, env=env)
    if r.returncode:
        return r.returncode
    folder = OUT / "obmichelper"
    # It's a console build (a windowed one draws antivirus false positives), so run the
    # self-test with no console window; at runtime it only ever runs as a hidden SYSTEM
    # scheduled task, which has no desktop to show one on.
    r = subprocess.run([str(folder / michelper.EXE_NAME), "--selftest"], timeout=60,
                       creationflags=0x08000000)  # CREATE_NO_WINDOW
    if r.returncode:
        print(f"the built mic helper failed its self-test ({r.returncode})", file=sys.stderr)
        return 1
    (folder / michelper.STAMP).write_text(michelper.make_stamp(DLL), encoding="ascii")
    michelper.write_manifest(folder)   # last: it lists the stamp too
    shutil.rmtree(WORK / "obmichelper", ignore_errors=True)
    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    print(f"built {folder} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(build("--clean" in sys.argv))
