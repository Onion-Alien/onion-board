"""scripts/prune_build.py: what's cut from the PyInstaller output, on a fake tree
with a fake import table (no pefile, no real DLLs)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import prune_build as pb  # noqa: E402

# who imports whom, by file name (lower-case), standing in for the PE import table
IMPORTS = {
    "qtwidgets.pyd": ["qt6widgets.dll", "qt6core.dll"],
    "qtwebenginecore.pyd": ["qt6webenginecore.dll"],
    "qtquick.pyd": ["qt6quick.dll"],
    "qt6webenginecore.dll": ["qt6quick.dll", "qt6core.dll"],
    "qt6quick.dll": ["qt6qml.dll"],
    "qt6widgets.dll": ["qt6core.dll"],
    "qtwebengineprocess.exe": ["qt6webenginecore.dll"],
    "ffmpegmediaplugin.dll": ["avcodec-61.dll"],
    "avcodec-61.dll": ["avutil-59.dll"],
}


def fake_imports(path: Path) -> list[str]:
    return IMPORTS.get(path.name.lower(), [])


def make_tree(tmp_path: Path) -> Path:
    qt = tmp_path / "OnionBoard" / "_internal" / "PySide6"
    files = [
        "QtCore.pyd", "QtWidgets.pyd", "QtWebEngineCore.pyd", "QtQuick.pyd", "QtOpenGL.pyd",
        "Qt6Core.dll", "Qt6Widgets.dll", "Qt6WebEngineCore.dll", "Qt6Quick.dll", "Qt6Qml.dll",
        "Qt6Charts.dll", "Qt63DRender.dll", "avcodec-61.dll", "avutil-59.dll", "swscale-8.dll",
        "opengl32sw.dll", "MSVCP140.dll", "QtWebEngineProcess.exe",
        "plugins/multimedia/ffmpegmediaplugin.dll",
        "plugins/platforms/qwindows.dll", "plugins/platforms/qoffscreen.dll",
        "plugins/platforms/qminimal.dll",
        "plugins/qmltooling/qmldbg_debugger.dll", "plugins/imageformats/qjpeg.dll",
        "qml/QtQuick/qmldir",
        "resources/qtwebengine_resources.pak", "resources/qtwebengine_resources.debug.pak",
        "resources/qtwebengine_devtools_resources.pak", "resources/icudtl.dat",
        "translations/qt_de.qm", "translations/qtwebengine_locales/en-US.pak",
        "translations/qtwebengine_locales/de.pak",
    ]
    for f in files:
        p = qt / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    (tmp_path / "OnionBoard" / "_internal" / "shiboken6").mkdir()
    return tmp_path / "OnionBoard"


def test_plan_keeps_what_is_reachable_and_drops_the_rest(tmp_path):
    app = make_tree(tmp_path)
    drop, problems = pb.plan(app, imports_of=fake_imports)
    assert problems == []
    names = {p.name for p in drop}
    # cut: unused Python modules, unreachable Qt DLLs, QML, dev tools, locales, extras
    assert {"QtQuick.pyd", "QtOpenGL.pyd", "Qt6Charts.dll", "Qt63DRender.dll",
            "swscale-8.dll", "opengl32sw.dll", "qml", "qmltooling", "qminimal.dll",
            "qtwebengine_resources.debug.pak", "qtwebengine_devtools_resources.pak",
            "qt_de.qm", "de.pak"} <= names
    # kept: everything the app imports, and what those import (Quick via WebEngineCore)
    for keep in ("QtCore.pyd", "QtWidgets.pyd", "Qt6Quick.dll", "Qt6Qml.dll", "Qt6Core.dll",
                 "avcodec-61.dll", "avutil-59.dll", "qwindows.dll", "qoffscreen.dll",
                 "ffmpegmediaplugin.dll", "qjpeg.dll", "qtwebengine_resources.pak",
                 "icudtl.dat", "en-US.pak", "MSVCP140.dll", "QtWebEngineProcess.exe"):
        assert keep not in names, keep


def test_plan_reports_a_kept_file_that_would_lose_an_import(tmp_path):
    app = make_tree(tmp_path)
    # a DLL slated for removal by name that a kept module still needs
    bad = dict(IMPORTS, **{"qtwidgets.pyd": ["qt6widgets.dll", "opengl32sw.dll"]})
    _drop, problems = pb.plan(app, imports_of=lambda p: bad.get(p.name.lower(), []))
    assert problems and "opengl32sw.dll" in problems[0]


def test_main_dry_run_deletes_nothing(tmp_path, monkeypatch, capsys):
    app = make_tree(tmp_path)
    monkeypatch.setattr(pb, "_imports_pefile", fake_imports)
    assert pb.main([str(app), "--dry-run"]) == 0
    assert (app / "_internal" / "PySide6" / "qml").exists()
    assert "would free" in capsys.readouterr().out
    assert pb.main([str(app)]) == 0
    assert not (app / "_internal" / "PySide6" / "qml").exists()
    assert (app / "_internal" / "PySide6" / "Qt6Quick.dll").exists()
