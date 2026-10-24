"""Build the mic helper (soundboard/mic/michelper.py) into build/michelper/obmichelper/:
obmichelper.exe, a small PyInstaller build of the mic effect's admin part only (no Qt,
no numpy), with its own copy of the effect DLL and stamp.txt saying which. build.ps1
runs it after scripts/directmic/build_directmic.py and bundles the folder with the app as
michelper\\; from source, soundboard.mic.michelper finds it here.

Usage: python scripts/buildtools/build_michelper.py [--clean]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
# What the helper runs: never left out (the build stops if one can't load without EXCLUDE)
NEEDS = ("soundboard.mic.michelper", "soundboard.mic.directmic", "soundboard.mic.micbase",
         "soundboard.mic.micring", "soundboard.mic.micstate", "soundboard.mic.micadmin",
         "soundboard.audio.appaudio")
# Imports every module of the soundboard package with EXCLUDE refused, as in the helper,
# and prints those that fail. PyInstaller follows imports inside functions too, so
# directmic's lazy `engine` and `appaudio` (applog -> the crash dialog -> all of the UI)
# put the whole app in the helper: 276 modules, 6 MB, of which 18 can load there.
PROBE = """
import importlib, pathlib, sys
EXCLUDE = set(sys.argv[1:])
class Refuse:
    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] in EXCLUDE:
            raise ImportError(name)
sys.meta_path.insert(0, Refuse())
for p in sorted(pathlib.Path("soundboard").rglob("*.py")):
    parts = p.with_suffix("").parts
    name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
    try:
        importlib.import_module(name)
    except ImportError:
        print(name)
"""


def unloadable() -> list[str]:
    """The soundboard modules that can't be imported without EXCLUDE: in the helper an
    import of one raises ImportError whether it's bundled or not, so it's left out (with
    what only it imports). Every other module the helper reaches still ships."""
    r = subprocess.run([sys.executable, "-c", PROBE, *EXCLUDE], cwd=ROOT, text=True,
                       capture_output=True, timeout=300,
                       env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    if r.returncode:
        raise RuntimeError(f"probing the helper's imports failed:\n{r.stderr}")
    dead = r.stdout.split()
    if wrong := [m for m in NEEDS if m in dead]:
        raise RuntimeError(f"{', '.join(wrong)} can't load without {', '.join(EXCLUDE)}: "
                           "the helper needs it")
    return dead
BOOTLOADERS = ("run.exe", "runw.exe")


def bootloader_hashes(folder: Path) -> str:
    import hashlib
    return "".join(f"{hashlib.sha256((folder / n).read_bytes()).hexdigest()}  {n}\n"
                   for n in BOOTLOADERS)


def stock_bootloader(folder: Path | None = None) -> str:
    """PyInstaller's version when its bootloader wasn't compiled here
    (scripts/buildtools/build_bootloader.ps1), else ''."""
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
    from scripts.buildtools import version_info
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
        print(f"no {DLL}: run scripts/directmic/build_directmic.py first", file=sys.stderr)
        return 1
    if stock := stock_bootloader():
        # Not fatal: a dev build (or one on a machine without MinGW-w64's gcc) should
        # still produce a working helper. build.ps1 compiles a local bootloader before
        # we get here, so release builds are clean; only direct/no-compiler builds fall
        # back to the stock one, with this warning.
        print(f"warning: PyInstaller {stock} has its stock bootloader, which some virus"
              " scanners flag as a false positive. Run"
              " scripts/buildtools/build_bootloader.ps1 for a clean build (needs"
              " MinGW-w64's gcc).", file=sys.stderr)
    sys.path.insert(0, str(ROOT))
    from soundboard.mic import michelper
    # --console, not --windowed: a windowed build still drew a couple of antivirus false
    # positives on VirusTotal where a console one is clean. No window is shown either way
    # -- the helper only ever runs as a hidden SYSTEM scheduled task (see michelper.py),
    # which has no interactive desktop.
    spec_cmd = [sys.executable, "-m", "PyInstaller.utils.cliutils.makespec", "--onedir",
                "--console", "--name", "obmichelper", "--specpath", str(WORK),
                "--version-file", str(version_file()),
                "--icon", str(ROOT / "assets" / "onionboard.ico"),
                "--add-binary", f"{DLL}{os.pathsep}directmic", "--paths", str(ROOT)]
    for mod in (*EXCLUDE, *unloadable()):
        spec_cmd += ["--exclude-module", mod]
    # PyInstaller finds DLLs on PATH too: only Windows' own (as build.ps1 does)
    env = {**os.environ, "PATH": os.pathsep.join(
        str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / p)
        for p in ("System32", "", r"System32\Wbem"))}
    r = subprocess.run([*spec_cmd, str(ROOT / "soundboard" / "mic" / "michelper.py")], cwd=ROOT,
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
    # appaudio is imported only on the way (a mic's silence check): the self-test
    # doesn't reach it, so look in the archive for what the helper runs
    from PyInstaller.archive.readers import CArchiveReader
    have = CArchiveReader(str(folder / "obmichelper.pkg")).open_embedded_archive(
        "PYZ.pyz").toc
    if missing := [m for m in NEEDS if m not in have]:
        print(f"the built mic helper lacks {', '.join(missing)}", file=sys.stderr)
        return 1
    (folder / michelper.STAMP).write_text(michelper.make_stamp(DLL), encoding="ascii")
    michelper.write_manifest(folder)   # last: it lists the stamp too
    shutil.rmtree(WORK / "obmichelper", ignore_errors=True)
    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    print(f"built {folder} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(build("--clean" in sys.argv))
