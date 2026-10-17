"""bootmark.py: the start-up breadcrumb that catches a start that never made it."""
from __future__ import annotations

import os

from soundboard import bootmark


def test_a_leftover_breadcrumb_names_the_run(tmp_path):
    assert bootmark.read(tmp_path) == ("", 0)   # nothing to say
    path = bootmark.mark("1.9.28", tmp_path)
    assert path == tmp_path / bootmark.NAME
    assert bootmark.read(tmp_path) == ("1.9.28", os.getpid())
    bootmark.clear(tmp_path)
    assert bootmark.read(tmp_path) == ("", 0)
    assert not (tmp_path / bootmark.NAME).exists()


def test_start_reads_the_last_run_before_leaving_this_one(tmp_path):
    bootmark.mark("1.9.27", tmp_path)     # the run before, still here
    bootmark.start("1.9.28", tmp_path)    # this run: read then replace
    assert bootmark.previous() == ("1.9.27", os.getpid())
    assert bootmark.read(tmp_path) == ("1.9.28", os.getpid())
    bootmark.clear(tmp_path)              # this run reached its running state
    bootmark.start("1.9.28", tmp_path)    # so the next run has nothing to explain
    assert bootmark.previous() == ("", 0)


def test_a_broken_or_odd_file_is_ignored(tmp_path):
    for text in ("not json", "", "{}", '{"version": ""}', '{"version": "<script>"}',
                 '{"version": 12}'):
        (tmp_path / bootmark.NAME).write_text(text, encoding="utf-8")
        assert bootmark.read(tmp_path) == ("", 0)


def test_clear_is_harmless_when_there_is_nothing(tmp_path):
    bootmark.clear(tmp_path)
    bootmark.clear(tmp_path)


def test_every_one_off_command_leaves_no_breadcrumb():
    """Each command app.main() handles and exits before the breadcrumb is cleared (the
    installer's --install-addon, say) is in main.py's _ONE_OFF, or the next normal start
    counts a startup-failed for a run that only did its job."""
    import re
    from pathlib import Path

    from soundboard import app
    assert list(app.ONE_OFF_COMMANDS) == list(bootmark.ONE_OFF)
    root = Path(__file__).resolve().parent.parent
    assert "bootmark.ONE_OFF" in (root / "main.py").read_text(encoding="utf-8")
    # nothing else in main() looks at a "--flag" before the breadcrumb is cleared, however
    # it's written (a one-off command there would leave a breadcrumb behind)
    src = (root / "soundboard" / "app.py").read_text(encoding="utf-8")
    body = src[src.index("\ndef main():"):]
    early = body[:body.index("from soundboard import bootmark")]
    assert "ONE_OFF_COMMANDS" in early
    assert not re.findall(r'"--[a-z-]+"', early), re.findall(r'"--[a-z-]+"', early)


def test_the_installers_mark_says_files_are_being_replaced(tmp_path):
    """installer/OnionBoard.iss leaves installing.txt beside the exe while it replaces the
    files; a fresh one means "installing now", one left by a setup that died doesn't."""
    assert not bootmark.installing(tmp_path)
    mark = tmp_path / bootmark.INSTALLING
    mark.write_text("setup", encoding="utf-8")
    made = mark.stat().st_mtime
    assert bootmark.installing(tmp_path, now=made + 5)
    assert not bootmark.installing(tmp_path, now=made + bootmark.INSTALLING_STALE_S + 1)
    assert not bootmark.installing()   # from source (not frozen): never


def _run_main(monkeypatch, tmp_path, argv, app_module):
    """main.py as the installed app (frozen, OnionBoard.exe in tmp_path), with
    soundboard.app swapped for `app_module` so nothing real starts."""
    import runpy
    import sys
    from pathlib import Path
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "OnionBoard.exe"))
    monkeypatch.setattr(sys, "argv", ["OnionBoard.exe", *argv])
    monkeypatch.setitem(sys.modules, "soundboard.app", app_module)
    started = []
    monkeypatch.setattr(bootmark, "start", lambda *a, **k: started.append(a))
    root = Path(__file__).resolve().parent.parent
    runpy.run_path(str(root / "main.py"), run_name="__main__")
    return started


def test_started_while_the_installer_replaces_files_it_quits_quietly(monkeypatch, tmp_path):
    """A double-click while an update installed loaded half-copied libraries: Python's
    "Unhandled exception in script" box (ImportError: shiboken6/libshiboken does not
    exist), one per click. Now it quits at once; the installer opens it when it's done."""
    import types

    import pytest
    ran = []
    app = types.ModuleType("soundboard.app")
    app.main = lambda: ran.append(1)
    (tmp_path / bootmark.INSTALLING).write_text("setup", encoding="utf-8")
    with pytest.raises(SystemExit) as out:
        _run_main(monkeypatch, tmp_path, [], app)
    assert out.value.code == 0 and ran == []
    # the installer's own helper commands still run while it installs
    assert _run_main(monkeypatch, tmp_path, ["--usage-count", "off"], app) == [] and ran == [1]
    # no installer: the app starts as always
    (tmp_path / bootmark.INSTALLING).unlink()
    ran.clear()
    assert _run_main(monkeypatch, tmp_path, [], app) and ran == [1]


def test_files_replaced_while_it_loads_quit_quietly_too(monkeypatch, tmp_path):
    """The mark came while the heavy import ran: its error isn't shown either (without
    the mark, it is: a real broken install must still say so)."""
    import types

    import pytest

    class Half(types.ModuleType):   # its import fails half-way, like half-copied Qt
        def __getattr__(self, name):
            raise ImportError("shiboken6/libshiboken does not exist")

    def mark_then(*a, **k):
        (tmp_path / bootmark.INSTALLING).write_text("setup", encoding="utf-8")
    monkeypatch.setattr(bootmark, "start", mark_then)
    import runpy
    import sys
    from pathlib import Path
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "OnionBoard.exe"))
    monkeypatch.setattr(sys, "argv", ["OnionBoard.exe"])
    monkeypatch.setitem(sys.modules, "soundboard.app", Half("soundboard.app"))
    main_py = str(Path(__file__).resolve().parent.parent / "main.py")
    with pytest.raises(SystemExit) as out:
        runpy.run_path(main_py, run_name="__main__")
    assert out.value.code == 0
    (tmp_path / bootmark.INSTALLING).unlink()
    monkeypatch.setattr(bootmark, "start", lambda *a, **k: None)
    with pytest.raises(ImportError):
        runpy.run_path(main_py, run_name="__main__")


def test_the_installer_marks_the_files_and_clears_it_before_opening_the_app():
    from pathlib import Path
    iss = (Path(__file__).resolve().parent.parent / "installer" / "OnionBoard.iss"
           ).read_text(encoding="utf-8")
    assert "{app}" + chr(92) + bootmark.INSTALLING in iss
    steps = iss[iss.index("procedure CurStepChanged"):]
    assert steps.index("StartInstallingMark") < steps.index("CheckInternalNotInUse")
    assert "EndInstallingMark" in iss[iss.index("procedure DeinitializeSetup"):]
    # both [Run] lines that open the app clear it first (or the app they open quits)
    run = iss[iss.index("[Run]"):iss.index("[UninstallRun]")]
    opens = [ln for ln in run.splitlines() if not ln.startswith(";") and (
        "postinstall" in ln or "Check: Relaunch" in ln)]
    assert len(opens) == 2 and all("BeforeInstall: EndInstallingMark" in ln for ln in opens)


def test_the_check_comes_before_anything_a_half_copied_install_can_fail(monkeypatch, tmp_path):
    """Started while the installer copies files, even bootmark (and what it imports) may
    be half there: the mark is checked first, with only os, sys and time."""
    import runpy
    import sys
    from pathlib import Path

    import pytest
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "OnionBoard.exe"))
    monkeypatch.setattr(sys, "argv", ["OnionBoard.exe"])
    import soundboard
    monkeypatch.setitem(sys.modules, "soundboard.bootmark", None)   # importing it fails
    monkeypatch.delattr(soundboard, "bootmark", raising=False)
    (tmp_path / bootmark.INSTALLING).write_text("setup", encoding="utf-8")
    main_py = str(Path(__file__).resolve().parent.parent / "main.py")
    with pytest.raises(SystemExit) as out:
        runpy.run_path(main_py, run_name="__main__")
    assert out.value.code == 0


def test_installmark_needs_nothing_but_os_sys_and_time():
    """The installer copies Python itself first (python3*.dll, VCRUNTIME, base_library.zip):
    the check can't need any other library, which may not be copied yet."""
    import ast
    from pathlib import Path

    from soundboard import installmark
    tree = ast.parse(Path(installmark.__file__).read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
             for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree)
              if isinstance(n, ast.ImportFrom) and n.module}
    assert names <= {"__future__", "os", "sys", "time"}, names
    assert bootmark.ONE_OFF is installmark.ONE_OFF


def test_the_installer_copies_python_first_and_the_exe_last_moving_the_old_aside():
    """A copy stuck on the launcher's "Failed to load Python DLL" box (or started again
    the moment it was closed) kept OnionBoard.exe open: the silent update gave up (Abort)
    and rolled back, leaving no _internal. Now the old exe is renamed out of the way
    (Windows allows that while it runs) after closing what runs from {app}."""
    from pathlib import Path
    bs = chr(92)
    iss = (Path(__file__).resolve().parent.parent / "installer" / "OnionBoard.iss"
           ).read_text(encoding="utf-8")
    files = iss[iss.index("[Files]"):iss.index("[Icons]")]
    lines = [ln for ln in files.splitlines() if ln.startswith("Source:") and "dist" in ln]
    first, rest, last = lines[:3], lines[3], lines[-1]
    assert len(lines) == 5
    excludes = rest.split("Excludes:")[1]
    for want in ("*.dll", "*.pyd", "base_library.zip"):
        assert any(f"_internal{bs}{want}" in ln for ln in first)
        assert f"{bs}_internal{bs}{want}" in excludes   # not copied a second time
    assert f"{bs}{{#AppExeName}}.exe" in excludes
    assert "{#AppExeName}.exe" in last and "BeforeInstall: MoveOldExeAside" in last
    move = iss[iss.index("procedure MoveOldExeAside"):]
    move = move[:move.index("\nend;\n")]
    assert "BoardProcesses(True)" in move and "RenameFile(Exe, Old)" in move
    # the moved exe goes at the end, else at the next install or by the uninstaller
    assert "DeleteOldExe" in iss[iss.index("procedure CurStepChanged"):]
    for section in ("[InstallDelete]", "[UninstallDelete]"):
        part = iss[iss.index(section):]
        part = part[:part.index("\n[", 1)]
        assert "{#AppExeName}.exe.old*" in part, section
