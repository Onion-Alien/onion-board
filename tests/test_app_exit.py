"""app.end_process: quitting ends the process with the app's code, at once, even with
other threads and a QApplication still alive (BUGS-2026-10-04b NEW-1: os._exit ran
PySide6's DLL teardown under live threads and crashed on quit)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = textwrap.dedent("""
    import threading, time
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    from soundboard.app import end_process

    app = QApplication([])
    w = QWidget(); w.show()
    stop = threading.Event()
    for i in range(3):   # never-ending, non-daemon: a normal exit would wait forever
        threading.Thread(target=lambda: [QTimer() for _ in iter(lambda: stop.wait(0.01), True)],
                         name="busy%d" % i).start()
    time.sleep(0.2)
    end_process(CODE)
    print("still here")
""")


def run(code: int) -> subprocess.CompletedProcess:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-c", CHILD.replace("CODE", str(code))], cwd=ROOT,
                          env=env, capture_output=True, text=True, timeout=60)


def test_ends_with_its_code_beside_live_threads():
    for code in (0, 3):
        r = run(code)
        assert r.returncode == code, (r.returncode, r.stderr[-2000:])
        assert "still here" not in r.stdout
