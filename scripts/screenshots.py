"""Render the README screenshots into docs/screenshots/.

    .venv\\Scripts\\python scripts/screenshots.py [--theme Dark]

Runs on Qt's offscreen platform: no window appears, no audio device is opened, no
hotkey is registered. Everything shown is made up here -- demo sounds synthesized
with numpy, generic device names, a fake list of programs -- so nothing from the
machine it runs on (its sound library, headset, open windows) ends up in a picture.
The Radio tab isn't captured: its globe is a web view, which renders blank offscreen.
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["ONIONBOARD_INSTANCE"] = "screenshots"
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", r"C:\Windows"))
                                            / "Fonts"))   # offscreen has no fonts otherwise
os.environ.setdefault("QT_SCALE_FACTOR", "1.5")           # crisper pictures
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--mute-audio"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.chdir(ROOT)

import conftest  # noqa: E402,F401 - swaps sounddevice's output stream for a silent one
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundboard import appaudio, autostart, engine, library, winkeys  # noqa: E402

OUTS = ["CABLE Input (VB-Audio Virtual Cable)", "Headphones (USB Audio Device)",
        "Speakers (Realtek(R) Audio)"]
INS = ["CABLE Output (VB-Audio Virtual Cable)", "Microphone (USB Audio Device)"]
PROGRAMS = [("spotify.exe", "Spotify Premium", True),
            ("chrome.exe", "Lo-fi beats to relax to - YouTube - Google Chrome", True),
            ("vlc.exe", "movie-night.mkv - VLC media player", False)]
SOUNDS = [("Airhorn", "F1", "Memes"), ("Vine Boom", "F2", "Memes"),
          ("Sad Trombone", "F3", "Reactions"), ("Bruh", "F4", "Reactions"),
          ("Drumroll", "", "Music"), ("Applause", "", "Reactions"),
          ("Rimshot", "ctrl+1", "Music"), ("Wow", "", "Reactions"),
          ("Crickets", "", "Memes"), ("Victory Fanfare", "ctrl+2", "Music"),
          ("Oof", "", "Memes"), ("Record Scratch", "", "Music"),
          ("Dun Dun Dunn", "", "Memes"), ("Laugh Track", "", "Reactions"),
          ("Bonk", "F5", "Memes")]


class _Stream:
    """Stands in for an open device stream so the setup check reads "working"."""
    active = True

    def __getattr__(self, _name):
        return lambda *a, **k: None


def fake_machine(tmp: Path):
    for name, path in dict(APP_DIR=tmp, SOUNDS_DIR=tmp / "sounds", CACHE_DIR=tmp / "cache",
                           THUMBS_DIR=tmp / "thumbs", CONFIG_PATH=tmp / "config.json").items():
        setattr(library, name, path)
    library.USE_RECYCLE_BIN = False
    autostart.winreg = None
    winkeys.Hotkeys.register = lambda self, m: None
    winkeys.exclusive_fullscreen = lambda: False
    engine.list_devices = lambda kind: [{"index": i, "name": n} for i, n in
                                        enumerate(INS if kind == "input" else OUTS)]
    engine.default_device_name = lambda kind: INS[1] if kind == "input" else OUTS[1]
    for setter, attr in (("set_main_device", "main_stream"), ("set_mon_device", "mon_stream"),
                         ("set_mic_device", "mic_stream")):
        setattr(engine.Engine, setter, lambda self, n, _a=attr: setattr(self, _a, _Stream()))
    appaudio.list_apps = lambda: [
        appaudio.App(pid=1000 + i, exe=exe, title=title, active=on, peak=0.4 if on else 0.0,
                     devices=[OUTS[1]], session_pids={1000 + i})
        for i, (exe, title, on) in enumerate(PROGRAMS)]


def demo_config(tmp: Path, theme: str):
    rng = np.random.default_rng(1)
    sounds = []
    for i, (name, key, tag) in enumerate(SOUNDS):
        path = tmp / f"{i}.wav"
        t = np.arange(int(library.SR * (0.6 + rng.random() * 3))) / library.SR
        y = np.sin(2 * np.pi * (180 + 60 * i) * t) * np.exp(-t * 1.5) * 0.4
        sf.write(path, np.stack([y, y], 1), library.SR)
        sounds.append(library.SoundMeta(id=f"s{i}", name=name, file=str(path), hotkey=key,
                                        color=library.PAD_COLORS[i % len(library.PAD_COLORS)],
                                        tags=[tag]))
    library.Config(sounds=sounds, categories=["Memes", "Reactions", "Music"],
                   setup_done=True, theme=theme).save()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="Dark")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    app.setStyle("Fusion")
    tmp = Path(tempfile.mkdtemp())
    fake_machine(tmp)
    demo_config(tmp, args.theme)

    def spin(seconds=0.8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents(QEventLoop.AllEvents, 20)
            time.sleep(0.01)

    def save(widget, name):
        widget.grab().save(str(args.out / f"{name}.png"))
        print("saved", name)

    from soundboard.settings import SettingsDialog
    from soundboard.ui import mainwindow
    from soundboard.ui.setupwizard import SetupWizard

    w = mainwindow.MainWindow()
    w._load_thread.join(15)
    w.resize(1180, 720)
    w.show()
    w._update_status()
    spin(1.5)
    for page, name in ((w.sounds_page, "sounds"), (w.apps, "apps"), (w.voice, "voice"),
                       (w.setup_page, "setup")):
        w.tabs.setCurrentWidget(page)
        spin()
        save(w, name)
    w.tabs.setCurrentWidget(w.sounds_page)

    d = SettingsDialog(w, "hotkeys")
    d.show()
    spin()
    save(d, "settings-hotkeys")
    d.close()

    wz = SetupWizard(w)
    wz.show()
    spin(1.5)
    save(wz, "setup-guide")
    wz.close()

    w.overlay.open()
    spin()
    save(w.overlay.window, "overlay")
    os._exit(0)   # skip teardown: the fake streams and threads needn't shut down cleanly


if __name__ == "__main__":
    main()
