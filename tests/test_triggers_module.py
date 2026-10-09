"""The "triggers" add-on kind (soundboard.modules): its module.json is checked (the
host interface version above all), its package is loaded from the module's own
folder once per run, and a module zip is installed only if it stays inside its
own folder, replacing the old copy only once the new one is known to be good.
Made-up add-ons only."""
import json
import sys
import zipfile

import pytest

from soundboard import modules
from soundboard.modules import ModuleError


def make_module(folder, *, package="fakewatch", version="1.0", api=1, entry=None,
                imports=(), body="", mid="onion-watch", board=None):
    """A triggers add-on in `folder`: module.json and a package whose entry has
    create(host) (`board`: the entry's whole source instead)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "module.json").write_text(json.dumps({
        "id": mid, "name": "Onion Watch", "version": version, "kind": "triggers",
        "api_version": api, "package": package, "entry": entry or f"{package}.board",
        "imports": list(imports)}), encoding="utf-8")
    pkg = folder / package
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (pkg / "board.py").write_text(board if board is not None else (
        "from . import __version__\n" + body +
        "\ndef create(host):\n    return ('tab for', host, __version__)\n"), encoding="utf-8")
    return folder


@pytest.fixture
def pkgname(request):
    """A package name of the test's own, forgotten again afterwards."""
    name = f"fakewatch_{abs(hash(request.node.name)) % 10**8}"
    yield name
    modules._forget(name)


def test_a_triggers_module_is_read_with_its_interface_version(tmp_path, pkgname):
    make_module(tmp_path / "onion-watch", package=pkgname, imports=["numpy"])
    (m,) = modules.discover([tmp_path])
    assert (m.kind, m.api_version, m.package, m.imports, m.error) == (
        "triggers", 1, pkgname, ["numpy"], "")


@pytest.mark.parametrize("change, why", [
    ({"api": modules.TRIGGERS_API[1] + 1}, "needs a newer Onion Board"),
    ({"api": modules.TRIGGERS_API[0] - 1}, "too old for this Onion Board"),
    ({"entry": "os.path"}, "isn't a module of"),
    ({"entry": "fake.board;import os"}, "isn't a module of"),
])
def test_a_triggers_module_it_cannot_host_is_refused_with_a_reason(tmp_path, change, why):
    make_module(tmp_path / "onion-watch", package="fake", **change)
    (m,) = modules.discover([tmp_path])
    assert why in m.error
    with pytest.raises(ModuleError, match=why.split(" ")[0]):
        modules.load_package(m)


def test_a_triggers_module_without_its_package_is_refused(tmp_path):
    folder = make_module(tmp_path / "onion-watch", package="fake")
    (folder / "fake" / "__init__.py").unlink()
    (m,) = modules.discover([tmp_path])
    assert "package 'fake' not found" in m.error


def test_its_package_loads_from_its_folder_once_per_run(tmp_path, pkgname):
    make_module(tmp_path / "onion-watch", package=pkgname, version="1.0")
    (m,) = modules.discover([tmp_path])
    entry = modules.load_package(m)
    assert entry.create("host") == ("tab for", "host", "1.0") and m.loaded
    assert sys.modules[pkgname].__file__.startswith(str(tmp_path))
    (again,) = modules.discover([tmp_path])
    assert modules.load_package(again) is entry            # the same copy, reused
    # a new version on disk can't replace the running one: say so
    make_module(tmp_path / "onion-watch", package=pkgname, version="2.0")
    (newer,) = modules.discover([tmp_path])
    with pytest.raises(ModuleError, match="restart Onion Board to use Onion Watch 2.0"):
        modules.load_package(newer)


def test_a_module_needing_what_the_app_lacks_is_refused_before_loading(tmp_path, pkgname):
    make_module(tmp_path / "onion-watch", package=pkgname,
                imports=["numpy", "no_such_module_here"])
    (m,) = modules.discover([tmp_path])
    with pytest.raises(ModuleError, match="needs no_such_module_here"):
        modules.load_package(m)
    assert pkgname not in sys.modules


def test_a_module_that_breaks_while_loading_leaves_nothing_behind(tmp_path, pkgname):
    make_module(tmp_path / "onion-watch", package=pkgname, body="raise RuntimeError('oops')\n")
    (m,) = modules.discover([tmp_path])
    with pytest.raises(ModuleError, match="failed to load: oops"):
        modules.load_package(m)
    assert not any(n == pkgname or n.startswith(pkgname + ".") for n in sys.modules)
    assert not m.loaded


# ---------------------------------------------------------------- installing a zip

def zip_of(folder, dest, extra=()):
    """Zip `folder` as <folder name>/..., plus (name, bytes) extras."""
    with zipfile.ZipFile(dest, "w") as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, f"{folder.name}/{p.relative_to(folder).as_posix()}")
        for name, data in extra:
            z.writestr(name, data)
    return dest


def test_a_module_zip_installs_and_replaces_the_old_copy(tmp_path):
    base = tmp_path / "appdata" / "modules"
    src = make_module(tmp_path / "src1" / "onion-watch", package="fake", version="1.0")
    info = modules.install_zip(zip_of(src, tmp_path / "v1.zip"), "onion-watch", "triggers", base)
    assert info.version == "1.0" and info.path == base / "onion-watch" and not info.error
    cache = base / "onion-watch" / "fake" / "__pycache__"
    (cache / "old.cpython-313.pyc").write_bytes(b"stale")   # left by the old copy
    src2 = make_module(tmp_path / "src2" / "onion-watch", package="fake", version="2.0")
    info = modules.install_zip(zip_of(src2, tmp_path / "v2.zip"), "onion-watch", "triggers",
                               base)
    assert info.version == "2.0"
    assert not (cache / "old.cpython-313.pyc").exists()   # a clean copy, compiled afresh
    assert list(cache.glob("board.*.pyc"))
    assert sorted(p.name for p in base.parent.iterdir()) == ["modules"]   # no staging left
    assert [m.version for m in modules.discover([base])] == ["2.0"]


@pytest.mark.parametrize("name", ["onion-watch/../evil.py", "evil.py", "../onion-watch/x.py",
                                  "onion-watch\\..\\evil.py", "/onion-watch/x.py",
                                  "C:/onion-watch/x.py"])
def test_a_zip_writing_outside_its_folder_is_refused(tmp_path, name):
    base = tmp_path / "appdata" / "modules"
    src = make_module(tmp_path / "src" / "onion-watch", package="fake")
    z = zip_of(src, tmp_path / "bad.zip", [(name, b"print('hi')")])
    with pytest.raises(ModuleError, match="outside its own folder"):
        modules.install_zip(z, "onion-watch", "triggers", base)
    assert not (tmp_path / "evil.py").exists() and not base.exists()


def test_a_zip_with_a_link_in_it_is_refused(tmp_path):
    src = make_module(tmp_path / "src" / "onion-watch", package="fake")
    z = zip_of(src, tmp_path / "link.zip")
    with zipfile.ZipFile(z, "a") as zz:
        link = zipfile.ZipInfo("onion-watch/fake/link")
        link.external_attr = (0o120777 << 16)
        zz.writestr(link, "C:/Windows")
    with pytest.raises(ModuleError, match="link"):
        modules.install_zip(z, "onion-watch", "triggers", tmp_path / "modules")


@pytest.mark.parametrize("mid, kind, why", [
    ("something-else", "triggers", "isn't the onion-watch add-on"),
    ("onion-watch", "effects", "isn't the onion-watch add-on"),
])
def test_a_zip_of_another_add_on_is_refused(tmp_path, mid, kind, why):
    src = make_module(tmp_path / "src" / "onion-watch", package="fake", mid=mid)
    if kind != "triggers":
        d = json.loads((src / "module.json").read_text())
        d["kind"] = kind
        (src / "module.json").write_text(json.dumps(d))
    with pytest.raises(ModuleError, match=why):
        modules.install_zip(zip_of(src, tmp_path / "x.zip"), "onion-watch", "triggers",
                            tmp_path / "modules")


def test_a_bad_new_copy_leaves_the_working_one_alone(tmp_path):
    base = tmp_path / "modules"
    good = make_module(tmp_path / "good" / "onion-watch", package="fake", version="1.0")
    modules.install_zip(zip_of(good, tmp_path / "good.zip"), "onion-watch", "triggers", base)
    too_new = make_module(tmp_path / "new" / "onion-watch", package="fake", version="9.0",
                          api=modules.TRIGGERS_API[1] + 1)
    with pytest.raises(ModuleError, match="needs a newer Onion Board"):
        modules.install_zip(zip_of(too_new, tmp_path / "new.zip"), "onion-watch", "triggers",
                            base)
    assert [m.version for m in modules.discover([base])] == ["1.0"]
    for junk in (b"not a zip", b""):
        (tmp_path / "junk.zip").write_bytes(junk)
        with pytest.raises(ModuleError, match="isn't a zip file"):
            modules.install_zip(tmp_path / "junk.zip", "onion-watch", "triggers", base)
    assert [m.version for m in modules.discover([base])] == ["1.0"]


def test_all_its_files_load_up_front_so_an_update_on_disk_cant_break_the_running_copy(
        tmp_path, pkgname):
    folder = make_module(tmp_path / "onion-watch", package=pkgname, body=(
        "def later():\n"
        f"    from {pkgname}.ui.extra import VALUE\n"
        "    return VALUE\n"))
    (folder / pkgname / "ui").mkdir()
    (folder / pkgname / "ui" / "__init__.py").write_text("", encoding="utf-8")
    (folder / pkgname / "ui" / "extra.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    (folder / pkgname / "ui" / "broken.py").write_text("raise RuntimeError('x')\n",
                                                       encoding="utf-8")
    (m,) = modules.discover([tmp_path])
    entry = modules.load_package(m)                          # a broken file doesn't stop it
    assert f"{pkgname}.ui.extra" in sys.modules
    folder.rename(tmp_path / "gone")                         # replaced while running
    assert entry.later() == "old"                            # a lazy import still works


# What each released Onion Watch lists in its module.json "imports" from outside the
# standard library and PySide6. The built app has no pip: dropping one of these from
# build.ps1 breaks the Triggers tab for everyone still on that release (0.5.6 needs
# scipy.ndimage). Add each new release's list here.
RELEASED_WATCH_IMPORTS = {
    "0.5.6": ["numpy", "scipy.fft", "scipy.ndimage"],
    "0.6.0": ["numpy"],
}


def test_the_build_ships_what_every_released_onion_watch_imports():
    from pathlib import Path
    import re
    build = (Path(__file__).resolve().parent.parent / "build.ps1").read_text(encoding="utf-8")
    hidden = set(re.findall(r"--hidden-import\s+(\S+)", build))
    excluded = set(re.findall(r"--exclude-module\s+(\S+)", build))
    for version, needs in RELEASED_WATCH_IMPORTS.items():
        for name in needs:
            assert not any(name == x or name.startswith(x + ".") for x in excluded), (
                f"build.ps1 excludes {name}, which Onion Watch {version} needs")
            if name.startswith("scipy."):   # scipy parts ship only when named
                assert name in hidden, f"build.ps1 doesn't ship {name} (Onion Watch {version})"


def test_an_add_on_gets_its_compiled_files_once_and_only_while_nothing_plays(tmp_path, pkgname):
    """The packaged app never writes __pycache__ itself: without them the Triggers
    tab's first open compiled Onion Watch on the UI thread and a sound skipped."""
    import importlib.util
    make_module(tmp_path / "onion-watch", package=pkgname)
    (m,) = modules.discover([tmp_path])
    src = tmp_path / "onion-watch" / pkgname / "board.py"
    pyc = importlib.util.cache_from_source(str(src))
    playing = iter([True, False])   # a sound plays at first: the file waits for it
    waits = []

    def wait():
        waits.append(1)
        return next(playing, False)
    import soundboard.modules as mod
    sleep, mod.time.sleep = mod.time.sleep, lambda s: None
    try:
        assert modules.precompile([m], wait) == 2   # __init__ and board
    finally:
        mod.time.sleep = sleep
    assert len(waits) == 3   # first file: playing, then free; second: free
    assert __import__("os").path.exists(pyc)
    assert modules.precompile([m], lambda: True) == 0   # up to date: nothing to do
    assert modules.load_package(m).create("host")[2] == "1.0"


def test_an_installed_add_on_comes_compiled(tmp_path):
    src = make_module(tmp_path / "src" / "onion-watch", package="fakewatch_inst")
    z = tmp_path / "w.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in src.rglob("*"):
            zf.write(p, p.relative_to(src.parent).as_posix())
    modules.install_zip(z, "onion-watch", "triggers", tmp_path / "modules")
    assert list((tmp_path / "modules" / "onion-watch" / "fakewatch_inst").glob(
        "__pycache__/board.*.pyc"))
