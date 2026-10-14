"""Pictures of the app's UI in one call, offscreen (no window opens, nothing plays).

    .venv\\Scripts\\python scripts\\pictures\\ui_shots.py window settings:tabs --lang de
    .venv\\Scripts\\python scripts\\pictures\\ui_shots.py "w.voice" "w.tabs.tabBar()" --out shots

Each target becomes one PNG in --out (default: a ui_shots folder in the temp folder):
  window            the whole main window
  settings[:page]   the whole window with Settings open on that page (e.g. settings:tabs)
  <expression>      any widget, as Python on the main window `w` (e.g. w.voice)

It builds the window exactly as the tests do (tests/test_mainwindow.py's `window`
fixture: a temp settings folder, no devices, no hotkeys), by writing a throwaway test
next to the others, running it and deleting it again. Fonts come from the system's
font folder, so the text isn't boxes."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TEST = '''\
import pytest
from soundboard import i18n, theme
from test_mainwindow import window as main_window  # noqa: F401

TARGETS = {targets!r}
OUT = {out!r}
LANG = {lang!r}
THEME = {theme!r}
SIZE = {size!r}


@pytest.fixture
def lang_first():
    i18n.set_language(LANG)   # before the window is built: text is read once
    yield
    i18n.set_language("en")


@pytest.fixture
def window(lang_first, main_window):  # noqa: F811
    return main_window


def test_zz_ui_shots(window, qapp):
    from pathlib import Path
    from conftest import process_events
    w = window
    if THEME:
        theme.apply(qapp, THEME)
    w.resize(*SIZE)
    w.show()
    process_events(qapp, lambda: False, timeout=0.3)
    out = Path(OUT)
    out.mkdir(parents=True, exist_ok=True)
    for i, target in enumerate(TARGETS):
        name = f"{{i:02d}}_" + "".join(c if c.isalnum() else "_" for c in target)[:40]
        if target == "window":
            widget, close = w, None
        elif target.split(":")[0] == "settings":
            page = target.partition(":")[2] or "privacy"
            # Settings is a page in the window (never a window of its own): shoot the
            # window with it open, then go back to the tabs
            w.open_settings(page)
            widget, close = w, w._settings_dlg
        else:
            widget, close = eval(target, {{"w": w}}), None
        process_events(qapp, lambda: False, timeout=0.3)
        path = out / f"{{name}}.png"
        assert widget.grab().save(str(path)), path
        print("saved", path)
        if close is not None:
            close.accept()
'''


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--theme", default="", help="a name from theme.THEMES")
    ap.add_argument("--lang", default="en", help="a catalog in assets/lang, e.g. de")
    ap.add_argument("--size", default="1100x720", help="window size, WxH")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "ui_shots"))
    a = ap.parse_args(argv)
    size = tuple(int(n) for n in a.size.lower().split("x"))
    out = str(Path(a.out).resolve())
    test = ROOT / "tests" / "test_zz_ui_shots_tmp.py"
    test.write_text(TEST.format(targets=a.targets, out=out, lang=a.lang,
                                theme=a.theme, size=size), encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-n", "0",
                            "-p", "no:cacheprovider", str(test)], cwd=ROOT, env=env)
    finally:
        test.unlink(missing_ok=True)
    if r.returncode == 0:
        print("pictures in", out)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
