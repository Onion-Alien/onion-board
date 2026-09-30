"""Record the README's feature tour: the real app, driven by this script, showing
the Sounds tab playing, the Radio tab's globe spinning, a trigger catching "YOU
DIED" and the voice changer.

    .venv\\Scripts\\python scripts/tour.py --out docs\\screenshots\\tour.webp
        [--mp4 <file>]

--out is an animated WebP (sharp, full colour, a fraction of a GIF's size; GitHub
shows it like a GIF), or a GIF if the name ends in .gif.

Unlike screenshots.py this needs a real window (the globe is a web page, which
only draws on screen), so the window is made a frameless tool window parked far
off-screen: it never takes the focus, has no taskbar button and covers nothing.
Everything in it is made up the same way as the screenshots (demo sounds
synthesized with numpy, generic device names, fake programs; see screenshots.py);
audio goes to silent stand-in streams. The globe loads its stations from the
Radio Browser directory, like the app does. Needs ffmpeg on PATH.
"""
import argparse
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_SCALE_FACTOR"] = "1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import promo  # noqa: E402
import screenshots  # noqa: E402  (sets the offscreen platform: undone just below)

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["ONIONBOARD_INSTANCE"] = "tour"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--mute-audio --disable-backgrounding-occluded-windows --disable-renderer-backgrounding "
    "--disable-features=CalculateNativeWinOcclusion")

from PySide6.QtCore import QEventLoop, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundboard import engine  # noqa: E402

FPS = 15
OUT_W = 1100            # the GIF's width (the MP4 keeps the window's full size)
BAND = 64               # caption band above the window, in output pixels at OUT_W


def silent_outputs():
    """Open the main / headphone outputs on conftest's silent streams, so sounds
    really play (pads animate, meters move) without reaching any device."""
    real = {n: getattr(engine.Engine, n) for n in ("set_main_device", "set_mon_device")}
    engine.find_device = lambda kind, name: 0
    query = engine.sd.query_devices
    engine.sd.query_devices = lambda idx=None, kind=None: (
        {"name": "demo", "default_samplerate": 48000.0, "max_output_channels": 2,
         "max_input_channels": 2} if idx is not None else query())
    return real


class Recorder:
    def __init__(self, app, w):
        self.app, self.w = app, w
        self.frames: list[tuple[QImage, str]] = []

    def spin(self, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents(QEventLoop.AllEvents, 10)
            time.sleep(0.003)

    def record(self, seconds: float, caption: str, step=None, image=None):
        """Grab FPS frames a second for `seconds`, calling step(t) before each one;
        `image(t)` replaces the window with a drawn picture."""
        start = time.monotonic()
        n = int(seconds * FPS)
        for i in range(n):
            t = i / FPS
            while time.monotonic() - start < t:
                self.app.processEvents(QEventLoop.AllEvents, 5)
                time.sleep(0.002)
            if step:
                step(t)
            self.app.processEvents(QEventLoop.AllEvents, 5)
            img = image(t) if image else self.w.grab().toImage()
            self.frames.append((img, caption))


def compose(img: QImage, caption: str, w: int) -> QImage:
    """The caption band, then the window scaled to width w."""
    scale = w / img.width()
    band = round(BAND * w / OUT_W)
    h = band + round(img.height() * scale)
    h += h % 2
    out = QImage(w, h, QImage.Format_RGB888)
    out.fill(QColor("#0b0c11"))
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawImage(QRectF(0, band, w, h - band), img)
    f = QFont("Segoe UI")
    f.setPixelSize(round(band * 0.46))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#ececf3"))
    p.drawText(QRectF(0, 0, w, band), Qt.AlignCenter, caption)
    p.end()
    return out


def end_card(size) -> QImage:
    w, h = size.width(), size.height()
    img = QImage(w, h, QImage.Format_RGB888)
    img.fill(QColor("#0f1016"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    promo.draw_logo(p, QPointF(w / 2, h * 0.30), h * 0.20)
    promo.caption(p, QRectF(0, h * 0.44, w, h * 0.12), "Onion Board", h * 0.10)
    promo.caption(p, QRectF(0, h * 0.57, w, h * 0.08), "free soundboard for Windows",
                  h * 0.05, 1, promo.MUTED, bold=False)
    promo.caption(p, QRectF(0, h * 0.70, w, h * 0.08), "onion-alien.github.io/onion-board",
                  h * 0.05, 1, promo.GREEN)
    p.end()
    return img


def game_scene(size, t: float) -> QImage:
    img = QImage(size.width(), size.height(), QImage.Format_RGB888)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    # promo's timeline has YOU DIED at DIED_AT; start this clip just before it
    promo.draw_game(p, QRectF(0, 0, size.width(), size.height()), promo.DIED_AT - 0.5 + t)
    p.end()
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mp4", type=Path)
    args = ap.parse_args()

    app = QApplication([])
    app.setStyle("Fusion")
    tmp = Path(tempfile.mkdtemp())
    real = silent_outputs()
    screenshots.fake_machine(tmp)
    for name, fn in real.items():               # outputs: silent streams, not stubs
        setattr(engine.Engine, name, fn)
    screenshots.demo_config(tmp, "Dark")
    if not screenshots.install_onion_watch():   # the Triggers tab is the Onion Watch add-on
        raise SystemExit("set ONIONBOARD_ONION_WATCH_ZIP to an OnionWatch-module.zip first")

    from soundboard.ui import mainwindow
    w = mainwindow.MainWindow()
    w._load_thread.join(15)
    w.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
    w.setAttribute(Qt.WA_ShowWithoutActivating)
    w.resize(1180, 720)
    w.move(-8000, -8000)                        # off every screen
    w.show()
    rec = Recorder(app, w)
    rec.spin(1.0)
    w.tabs.setCurrentWidget(w.radio)            # let the globe load its stations
    rec.spin(12.0)
    w.tabs.setCurrentWidget(w.sounds_page)
    rec.spin(1.0)

    # 1. sounds
    plays = {0.4: "s0", 1.6: "s3", 2.8: "s9", 3.8: "s14"}

    def sounds(t):
        for at, sid in list(plays.items()):
            if t >= at:
                w.play(sid)
                plays.pop(at)
    rec.record(5.0, "Press a pad or a hotkey: Discord and your game hear it", sounds)

    # 2. radio
    w.tabs.setCurrentWidget(w.radio)
    rec.record(5.0, "Internet radio from all over the world, on a 3D globe")

    # 3. triggers: the game, then the tab that caught it
    size = w.grab().size()
    rec.record(2.4, "Triggers: pick a picture, like a game's “YOU DIED”…",
               image=lambda t: game_scene(size, t))
    tr = w.triggers.panel.panel                  # the add-on's triggers page
    tr.set_watching(True)                        # Watcher.start is a no-op (install_onion_watch)
    tr.poll.stop()
    w.tabs.setCurrentWidget(w.triggers)
    rows = list(tr.rows.values())

    def triggers(t):
        died = 0.15 + 0.8 * min(1.0, t / 0.6)
        rows[0].show_score(died)
        rows[1].show_score(0.21 + 0.02 * math.sin(t * 7))
        rows[2].show_score(0.33 + 0.02 * math.sin(t * 5))
        if t >= 0.8 and not rows[0].state.text().startswith("Played"):
            rows[0].flash("Played! 🔊 Sad Trombone", 60000)
            w.play(rows[0].t.sound)
    rec.record(4.0, "…and your sound plays the moment it shows up on screen", triggers)

    # 4. voice
    w.tabs.setCurrentWidget(w.voice)
    fx = w.voice.fx
    picks = {0.3: "Robot", 2.0: "Demon", 3.6: "Chipmunk"}

    def voice(t):
        if t >= 0.9 and not fx.btn_power.isChecked():
            fx.btn_power.setChecked(True)
        for at, name in list(picks.items()):
            if t >= at:
                fx.pick(name)
                picks.pop(at)
        fx.set_level(0.04 + 0.22 * abs(math.sin(t * 9)) * abs(math.sin(t * 1.7 + 0.5)))
        line = "gg ez, nice try"
        typed = line[:max(0, int((t - 2.6) * 9))]
        if w.voice.speech.ed.text() != typed:
            w.voice.speech.ed.setText(typed)
    rec.record(5.5, "Change your voice live, or type and a computer voice says it", voice)
    fx.btn_power.setChecked(False)

    # 5. where to get it
    card = end_card(size)
    rec.record(2.5, "Free · no account · no ads", image=lambda t: card)

    with tempfile.TemporaryDirectory() as out:
        full_w = size.width() - size.width() % 2
        for i, (img, cap) in enumerate(rec.frames):
            compose(img, cap, full_w).save(f"{out}/f{i:04d}.png")
        src = ["-framerate", str(FPS), "-i", f"{out}/f%04d.png"]
        if args.mp4:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
                            str(args.mp4)], check=True)
            print("wrote", args.mp4, flush=True)
        if args.out.suffix.lower() == ".gif":
            filt = (f"fps=12,scale={OUT_W}:-2:flags=lanczos,split[a][b];"
                    "[a]palettegen=max_colors=256:stats_mode=diff[p];"
                    "[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle")
            enc = ["-vf", filt]
        else:
            enc = ["-vf", f"fps=12,scale={OUT_W}:-2:flags=lanczos", "-c:v", "libwebp_anim",
                   "-quality", "80", "-compression_level", "6", "-preset", "picture"]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, *enc, "-loop", "0",
                        str(args.out)], check=True)
        print("wrote", args.out, f"({args.out.stat().st_size // 1024} KB,",
              f"{len(rec.frames)} frames)", flush=True)
    os._exit(0)   # skip teardown: the web view and fake streams needn't close cleanly


if __name__ == "__main__":
    main()
