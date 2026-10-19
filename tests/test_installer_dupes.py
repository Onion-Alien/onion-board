"""scripts/buildtools/installer_dupes.py: identical files go into the installer once, and every
copy still installs where it was."""
from __future__ import annotations

import sys
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "buildtools"))
import installer_dupes as dupes  # noqa: E402


def _app(tmp_path: Path, files: dict[str, bytes]) -> Path:
    app = tmp_path / "OnionBoard"
    for rel, data in files.items():
        p = app / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return app


def test_copies_are_found_by_contents_and_point_at_one_kept_file(tmp_path):
    app = _app(tmp_path, {
        "OnionBoard.exe": b"exe",
        r"_internal\python313.dll": b"python",
        r"_internal\michelper\_internal\python313.dll": b"python",
        r"_internal\PySide6\VCRUNTIME140.dll": b"vc",
        r"_internal\michelper\_internal\VCRUNTIME140.dll": b"vc",
        r"_internal\a\same-name.txt": b"one",        # same name, other bytes: not a copy
        r"_internal\b\same-name.txt": b"two",
        r"_internal\c\renamed.bin": b"python",       # other name, same bytes: a copy
        r"_internal\empty1": b"", r"_internal\empty2": b"",
        r"modules\x\exe-bytes": b"exe",              # the exe is never part of a set
    })
    got = {str(c): str(k) for c, k in dupes.find_dupes(app)}
    assert got == {
        r"_internal\michelper\_internal\python313.dll": r"_internal\python313.dll",
        r"_internal\c\renamed.bin": r"_internal\python313.dll",
        r"_internal\PySide6\VCRUNTIME140.dll": r"_internal\michelper\_internal\VCRUNTIME140.dll",
    }


def test_python_itself_is_never_a_skipped_copy(tmp_path):
    """The .iss's first entries install the top of _internal by wildcard, with nothing
    to skip a copy from: such a file is always the one kept, or left as it is."""
    app = _app(tmp_path, {
        "OnionBoard.exe": b"exe",
        r"_internal\zz\VCRUNTIME140.dll": b"vc",
        r"_internal\VCRUNTIME140.dll": b"vc",
        r"_internal\libA.dll": b"same", r"_internal\libB.dll": b"same",
    })
    pairs = [(str(c), str(k)) for c, k in dupes.find_dupes(app)]
    assert pairs == [(r"_internal\zz\VCRUNTIME140.dll", r"_internal\VCRUNTIME140.dll")]
    assert dupes.is_early(PureWindowsPath(r"_internal\base_library.zip"))
    assert not dupes.is_early(PureWindowsPath(r"_internal\michelper\_internal\x.pyd"))


def test_the_include_lists_each_copy_and_skips_it_from_the_folder_entry(tmp_path):
    app = _app(tmp_path, {
        "OnionBoard.exe": b"exe",
        r"_internal\python313.dll": b"python",
        r"_internal\michelper\_internal\python313.dll": b"python",
        r"_internal\{odd}\x.txt": b"t", r"_internal\y.txt": b"t",
    })
    assert dupes.write(app, tmp_path / "out") == (2, len(b"python") + 1)
    text = (tmp_path / "out" / "dupes.iss").read_text("utf-8")
    bs = "\\"
    assert (f'#define DupExcludes ",{bs}_internal{bs}michelper{bs}_internal{bs}python313.dll,'
            f'{bs}_internal{bs}{{odd}}{bs}x.txt"') in text
    assert (f'Source: "..{bs}dist{bs}OnionBoard{bs}_internal{bs}python313.dll"; '
            f'DestDir: "{{app}}{bs}_internal{bs}michelper{bs}_internal"; '
            f'DestName: "python313.dll"; Flags: ignoreversion') in text
    # an Inno Setup constant's brace in a folder name is doubled
    assert (f'Source: "..{bs}dist{bs}OnionBoard{bs}_internal{bs}y.txt"; '
            f'DestDir: "{{app}}{bs}_internal{bs}{{{{odd}}"; DestName: "x.txt"') in text


def test_no_copies_writes_an_empty_list(tmp_path):
    app = _app(tmp_path, {"OnionBoard.exe": b"exe", r"_internal\a.dll": b"a"})
    assert dupes.write(app, tmp_path / "out") == (0, 0)
    assert '#define DupExcludes ""' in (tmp_path / "out" / "dupes.iss").read_text("utf-8")


def test_the_installer_includes_the_list_before_the_folder_entry():
    bs = "\\"
    iss = (ROOT / "installer" / "OnionBoard.iss").read_text("utf-8")
    files = iss[iss.index("[Files]"):iss.index("[Icons]")]
    inc = files.index(f'#include "..{bs}build{bs}installer{bs}dupes.iss"')
    folder = files.index(f'Source: "{dupes.SOURCE}{bs}*"')
    exe = files.index("BeforeInstall: MoveOldExeAside")
    assert files.index("base_library.zip") < inc < folder < exe
    assert files[folder:].splitlines()[0].endswith('base_library.zip{#DupExcludes}"')
    build = (ROOT / "build.ps1").read_text("utf-8")
    assert build.index(f"installer_dupes.py dist{bs}OnionBoard build{bs}installer") < \
        build.index("& $iscc")
