"""Build the cleanup tool (soundboard/core/cleanup.py) into dist/OnionBoardCleanup.exe: one
file people download from the `cleanup-tool` release to take everything of Onion Board
off their PC. Like the mic helper it carries only the admin part of the mic effect (no
Qt, no numpy, no effect DLL: it only ever removes it).

Usage: python scripts/build_cleanup.py [--clean]
Then: gh release upload cleanup-tool dist/OnionBoardCleanup.exe --clobber
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist"
WORK = ROOT / "build" / "cleanup-work"
NAME = "OnionBoardCleanup"
sys.path.insert(0, str(ROOT / "scripts"))
from build_michelper import EXCLUDE, stock_bootloader  # noqa: E402


def version_file() -> Path:
    sys.path.insert(0, str(ROOT))
    import soundboard
    from scripts import version_info
    text = version_info.render(soundboard.__version__)
    text = text.replace("StringStruct('FileDescription', 'Onion Board')",
                        "StringStruct('FileDescription', 'Onion Board cleanup')")
    text = text.replace("'OnionBoard.exe'", f"'{NAME}.exe'")
    text = text.replace("StringStruct('InternalName', 'OnionBoard')",
                        f"StringStruct('InternalName', '{NAME}')")
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "version_info.txt"
    out.write_text(text, encoding="utf-8")
    return out


def build(clean: bool = False) -> int:
    if stock := stock_bootloader():
        print(f"warning: PyInstaller {stock} has its stock bootloader, which some virus"
              " scanners flag. Run scripts/build_bootloader.ps1 first.", file=sys.stderr)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
           "--name", NAME, "--distpath", str(OUT), "--workpath", str(WORK),
           "--specpath", str(WORK), "--version-file", str(version_file()),
           "--icon", str(ROOT / "assets" / "onionboard.ico"), "--paths", str(ROOT)]
    if clean:
        cmd.append("--clean")
    for mod in EXCLUDE:
        cmd += ["--exclude-module", mod]
    # PyInstaller finds DLLs on PATH too: only Windows' own (as build.ps1 does)
    env = {**os.environ, "PATH": os.pathsep.join(
        str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / p)
        for p in ("System32", "", r"System32\Wbem"))}
    r = subprocess.run([*cmd, str(ROOT / "soundboard" / "core" / "cleanup.py")], cwd=ROOT, env=env)
    if r.returncode:
        return r.returncode
    exe = OUT / f"{NAME}.exe"
    r = subprocess.run([str(exe), "--dry-run"], timeout=120, capture_output=True,
                       text=True, creationflags=0x08000000)   # CREATE_NO_WINDOW
    if r.returncode or "Onion Board cleanup" not in r.stdout:
        print(f"the built cleanup tool failed its dry run ({r.returncode}):\n{r.stdout}"
              f"{r.stderr}", file=sys.stderr)
        return 1
    print(f"built {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(build("--clean" in sys.argv))
