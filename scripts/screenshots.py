"""Render the README screenshots into docs/screenshots/.

    .venv\\Scripts\\python scripts/screenshots.py [--theme Dark]

Runs on Qt's offscreen platform: no window appears, no audio device is opened, no
hotkey is registered. Everything shown is made up here -- demo sounds synthesized
with numpy, generic device names, a fake list of programs -- so nothing from the
machine it runs on (its sound library, headset, open windows) ends up in a picture.
The Radio tab isn't captured: its globe is a web view, which renders blank offscreen.

The Triggers tab is the Onion Watch add-on. Set ONIONBOARD_ONION_WATCH_ZIP to an
OnionWatch-module.zip (Onion Watch's scripts/build_module.py) to capture it: it's
installed into the made-up profile, with one made-up screen. Without it the
triggers picture is left as it is.
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

winkeys.key_char = conftest.us_key_char   # hotkeys drawn as on a US keyboard

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
# Triggers tab: (name, picture (see trigger_picture), sound index, wait, live match %)
TRIGGERS = [("Died", "died", 2, 1.5, 12),
            ("Boss beaten", "victory", 9, 0.0, 91),
            ("Headshot", "headshot", 13, 0.0, 34)]


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


def install_onion_watch() -> bool:
    """Install the Onion Watch add-on (the Triggers tab) into the made-up profile from
    ONIONBOARD_ONION_WATCH_ZIP and load it with one made-up screen and a watcher that
    never reads the real one. False when there's no zip to install."""
    import importlib

    from soundboard import modules, watchaddon
    z = watchaddon.local_zip()
    if z is None:
        return False
    info = watchaddon.install(z)
    modules.load_package(info)
    sw = importlib.import_module(f"{info.package}.screenwatch")
    sw.monitors = lambda: [sw.Monitor(0, 0, 1920, 1080, True)]
    sw.Watcher.start = lambda self: None
    return True


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
                   setup_done=True, theme=theme, screen={"triggers": demo_triggers(tmp)}).save()


def trigger_picture(kind: str):
    """A made-up trigger picture, as if cut from a game's screenshot: the souls-like
    death / boss banners over promo.py's game scene, or a shooter's kill callout."""
    import promo
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
    full = QRectF(0, 0, 800, 400)            # cut close around it, as people do
    img = QImage(int(full.width()), int(full.height()), QImage.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    if kind == "headshot":
        g = QLinearGradient(full.topLeft(), full.bottomLeft())
        g.setColorAt(0, QColor("#3b4a55"))
        g.setColorAt(0.55, QColor("#6d6a5e"))
        g.setColorAt(0.56, QColor("#403a31"))
        g.setColorAt(1, QColor("#221f1b"))
        p.fillRect(full, g)
        p.setPen(QColor(0, 0, 0, 0))
        for x, wd, ht, shade in ((0.05, 0.18, 0.30, "#2e3439"), (0.30, 0.10, 0.22, "#353b40"),
                                 (0.62, 0.22, 0.36, "#2a3035"), (0.88, 0.14, 0.26, "#32383d")):
            p.fillRect(QRectF(full.width() * x, full.height() * (0.56 - ht),
                              full.width() * wd, full.height() * ht), QColor(shade))
        promo.draw_callout(p, full, "HEADSHOT", fill=0.56)
    else:
        promo.draw_scene(p, full, 6.0)
        p.fillRect(full, QColor(0, 0, 0, 70))
        if kind == "died":
            promo.draw_banner(p, full, "YOU DIED", promo.SOUL_RED, size=0.24, fill=0.8)
        else:
            promo.draw_banner(p, full, "VICTORY ACHIEVED", promo.SOUL_GOLD, size=0.24,
                              fill=0.92)
    p.end()
    return img


def demo_triggers(tmp: Path) -> list[dict]:
    out = []
    (tmp / "triggers").mkdir(exist_ok=True)
    for i, (name, kind, sound, wait, _live) in enumerate(TRIGGERS):
        path = tmp / "triggers" / f"t{i}.png"
        trigger_picture(kind).save(str(path))
        out.append({"id": f"t{i}", "name": name, "image": str(path), "sound": f"s{sound}",
                    "delay": wait, "cooldown": 5.0})
    return out


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
    watch = install_onion_watch()

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
    if watch:
        tr = w.triggers.panel.panel       # the add-on's triggers page
        tr.set_watching(True)             # Watcher.start is a no-op (install_onion_watch)
        tr.poll.stop()                    # show made-up live matches instead
        w.tabs.setCurrentWidget(w.triggers)
        for i, row in enumerate(tr.rows.values()):
            row.show_score(TRIGGERS[i][4] / 100)
        tr.rows["t1"].flash("Played!", 60000)
        spin()
        save(w, "triggers")
    else:
        print("triggers not captured: set ONIONBOARD_ONION_WATCH_ZIP to an OnionWatch-module.zip")
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
