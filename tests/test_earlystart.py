"""core/earlystart.py: the loading screen from main.py, before app.py's heavy imports,
and only in the copy that's going to run."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

from soundboard.core import earlystart

ROOT = Path(__file__).resolve().parent.parent

# one copy of the app as far as main.py's early loading screen: what it shows, and whether
# app.py's heavy imports had to come first. It holds the lock until stdin closes.
_COPY = textwrap.dedent("""
    import sys
    sys.path.insert(0, {root!r})
    from pathlib import Path
    from soundboard.core import earlystart
    shown = earlystart.show([{main!r}] + sys.argv[1:], Path({prof!r}))
    splash = sys.modules.get("soundboard.ui.bun.splash")
    print(shown, earlystart.locked(), splash is not None and splash._splash is not None,
          "numpy" in sys.modules, "soundboard.sounds.library" in sys.modules,
          "soundboard.core.app" in sys.modules, flush=True)
    sys.stdin.read()
""")


def _copy(tmp_path, instance, *args):
    env = dict(os.environ, ONIONBOARD_INSTANCE=instance, ONIONBOARD_PROFILE_DIR=str(tmp_path),
               QT_QPA_PLATFORM="offscreen", ONIONBOARD_NO_STATS="1")
    code = _COPY.format(root=str(ROOT), main=str(ROOT / "main.py"), prof=str(tmp_path))
    p = subprocess.Popen([sys.executable, "-c", code, *args], env=env, text=True,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, cwd=str(ROOT))
    line = p.stdout.readline().split()
    return p, line


def _done(*procs):
    for p in procs:
        try:
            p.stdin.close()
            p.wait(20)
        except (OSError, subprocess.TimeoutExpired):
            p.kill()


@pytest.mark.windows   # Windows' named mutex
def test_the_first_copy_shows_bun_before_the_heavy_imports_and_a_second_shows_nothing(tmp_path):
    instance = f"onionboard-test-{os.getpid()}-{uuid.uuid4().hex}"
    first, said = _copy(tmp_path, instance)
    try:
        # shown, lock taken, splash up -- with no numpy, sound library or app.py loaded
        assert said == ["True", "True", "True", "False", "False", "False"], said
        second, said2 = _copy(tmp_path, instance)
        try:
            # the lock is taken: no loading screen (app.main() asks the first to the front)
            assert said2 == ["False", "False", "False", "False", "False", "False"], said2
        finally:
            _done(second)
    finally:
        _done(first)


@pytest.mark.windows
@pytest.mark.parametrize("arg", ["--tray", "--restart-after"])
def test_no_early_loading_screen_into_the_tray_or_on_a_restart(tmp_path, arg):
    """--tray: started with Windows, no loading screen at all. --restart-after: the old
    copy still holds the lock until it has quit; app.main() waits for it first."""
    instance = f"onionboard-test-{os.getpid()}-{uuid.uuid4().hex}"
    p, said = _copy(tmp_path, instance, arg, "123")
    try:
        assert said[:3] == ["False", "False", "False"], said
    finally:
        _done(p)


def test_main_py_shows_it_right_after_the_breadcrumb_before_app_py():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    crumb = src.index("bootmark.start(__version__)")
    early = src.index("earlystart.show(")
    heavy = src.index("from soundboard.core.app import main")
    assert crumb < early < heavy


def test_interface_sizes_match_the_settings():
    from soundboard.sounds.config import UI_SCALES
    assert earlystart.UI_SCALES == UI_SCALES


def test_the_splash_leaves_the_apps_switch_interval_alone():
    """Up before app.py tuned the GIL's switch interval for the audio, the splash must
    not put the old, coarser one back when it closes."""
    from soundboard.ui.bun import splash
    s = object.__new__(splash.NativeSplash)
    before = sys.getswitchinterval()
    try:
        s._switch = 0.005
        sys.setswitchinterval(splash.SWITCH_S)
        s._mine = sys.getswitchinterval()
        sys.setswitchinterval(0.0002)   # app.py's tune_runtime_for_audio, meanwhile
        s._switch_back()
        assert sys.getswitchinterval() == pytest.approx(0.0002)
        sys.setswitchinterval(splash.SWITCH_S)   # nobody else touched it: put back
        s._switch_back()
        assert sys.getswitchinterval() == pytest.approx(0.005)
    finally:
        sys.setswitchinterval(before)
