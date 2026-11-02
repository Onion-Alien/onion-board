"""Picture sheets of Bun for checking a mascot change by eye (see docs/MASCOT.md).

    .venv\\Scripts\\python scripts\\pictures\\bun_sheet.py outfits   # every theme's outfit
    .venv\\Scripts\\python scripts\\pictures\\bun_sheet.py poses     # outfits x every pose
    .venv\\Scripts\\python scripts\\pictures\\bun_sheet.py owls      # Hoot (Triggers tab) per theme
    .venv\\Scripts\\python scripts\\pictures\\bun_sheet.py owl       # Hoot posed, a few outfits
    .venv\\Scripts\\python scripts\\pictures\\bun_sheet.py live      # the real animated widgets,
                                                         # frozen at moments of each act

Offscreen, no windows. Sheets go to %TEMP%\\bun-sheets (or --out DIR). `poses` and
`live` take --themes "Royal,Deep Fried,..." (default: a mix of hats, glasses and capes).
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR",
                      os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from soundboard.ui.bun import bunny  # noqa: E402
from soundboard.ui.kit import theme  # noqa: E402

MIX = ["Royal", "Midnight", "Deep Fried", "Vampire", "Hacker", "Sunset", "Arctic",
       "Comic Sans", "Bubblegum", "Brainrot"]
POSES = [
    ("idle", {}), ("blink", {"blink": 1.0}), ("talking", {"mouth": 1.0}),
    ("sad", {"sad": 1.0}), ("angry+bat", {"angry": 1.0, "prop": "bat", "swing": 0.5}),
    ("ears flick", {"ears": 14}), ("mic", {"prop": "mic"}),
    ("hammer", {"prop": "hammer", "swing": 1.0}),
    ("asleep", {"nightcap": True, "blink": 1.0}), ("smug", {"smug": True}),
    ("star", {"prop": "star"}),
]


def use_theme(name: str):
    theme.current_name = name
    theme.T.clear()
    theme.T.update(theme.tokens(name))


def grid(rows: list[tuple[str, list[tuple[str, QPixmap | None]]]], cw: int, ch: int,
         draw=None) -> QImage:
    """One row per theme on its own background, a labelled column per picture. A None
    picture calls draw(painter, rect, column) instead."""
    lw, n = 110, max(len(c) for _, c in rows)
    img = QImage(lw + cw * n, 24 + ch * len(rows), QImage.Format.Format_RGB32)
    img.fill(QColor("#0b0b0f"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    p.setPen(QColor("#ffd34d"))
    for j, (label, _) in enumerate(rows[0][1]):
        p.drawText(QRectF(lw + j * cw, 2, cw, 20), Qt.AlignmentFlag.AlignCenter, label)
    for i, (name, cells) in enumerate(rows):
        use_theme(name)
        y = 24 + i * ch
        p.fillRect(0, y, img.width(), ch - 2, QColor(theme.T["bg"]))
        p.setPen(QColor(theme.T["text_hi"]))
        p.drawText(QRectF(6, y, lw - 8, ch), Qt.AlignmentFlag.AlignVCenter, name)
        for j, (_, pm) in enumerate(cells):
            cell = QRectF(lw + j * cw, y, cw, ch)
            if pm is None:
                draw(p, cell.adjusted(8, 6, -8, -8), j)
                continue
            if pm.width() > cw - 6 or pm.height() > ch - 6:
                pm = pm.scaled(cw - 6, ch - 6, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(round(cell.x() + (cw - pm.width()) / 2),
                         round(y + (ch - pm.height()) / 2), pm)
    p.end()
    return img


OWL_POSES = [
    ("idle", {}), ("look", {"look": 1.0, "look_y": 0.6}), ("blink", {"blink": 1.0}),
    ("sad", {"sad": 1.0, "tufts": 20}), ("plead", {"plead": 1.0, "clasp": 1.0}),
    ("tear", {"tear": 0.4, "sad": 0.6}), ("joy", {"flap": 1.0, "tufts": -12}),
]


def owl(themes) -> QImage:
    """Hoot (the Triggers tab's owl) in every theme's outfit, then a few posed."""
    from soundboard.style.owl import draw_owl

    def draw(p, rect, j):
        draw_owl(p, rect, **OWL_POSES[j][1])
    rows = [(n, [(label, None) for label, _ in OWL_POSES]) for n in themes]
    return grid(rows, 120, 150, draw)


def owls(_themes) -> QImage:
    from soundboard.style.owl import draw_owl
    return outfits(_themes, lambda p, rect: draw_owl(p, rect))


def outfits(_themes, draw=None) -> QImage:
    cols = 6
    names = list(theme.THEMES)
    rows = [names[i:i + cols] for i in range(0, len(names), cols)]
    cw, ch = 200, 250
    img = QImage(cw * cols, ch * len(rows), QImage.Format.Format_RGB32)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
    for i, name in enumerate(names):
        use_theme(name)
        x, y = (i % cols) * cw, (i // cols) * ch
        p.fillRect(x + 1, y + 1, cw - 2, ch - 2, QColor(theme.T["bg"]))
        rect = QRectF(x + 20, y + 14, cw - 40, ch - 54)
        (draw or (lambda q, r: bunny.draw_bunny(q, r, None)))(p, rect)
        p.setPen(QColor(theme.T["text_hi"]))
        p.drawText(QRectF(x, y + ch - 36, cw, 24), Qt.AlignmentFlag.AlignCenter, name)
    p.end()
    return img


def poses(themes) -> QImage:
    def draw(p, rect, j):
        kw = dict(POSES[j][1])
        bunny.draw_bunny(p, rect, kw.pop("prop", None), **kw)
    return grid([(n, [(label, None) for label, _ in POSES]) for n in themes], 120, 150, draw)


class _Clock:
    """Stands in for time.monotonic so each frame is taken at a known moment."""
    t = 1000.0

    def __call__(self):
        return self.t


def live(themes) -> QImage:
    clock = _Clock()
    real = time.monotonic
    time.monotonic = clock
    from soundboard.ui.bun import bunnywidget, scribebun
    from soundboard.ui.setup import setupshow
    bunnywidget.local_hour = lambda: 3   # inside his nap hours
    app = QApplication.instance()

    def frames(w, steps):
        out = []
        for dt, act, label in steps:
            if act:
                act()
            n = max(1, int(dt * 30))
            for _ in range(n):            # step the widget's own clock, 30 fps
                clock.t += dt / n
                (getattr(w, "_step", None) or w._tick)()
            app.processEvents()
            out.append((label, w.grab()))
        return out

    def row(name):
        theme.apply(app, name)
        cells = []
        b = bunnywidget.BunnyWidget("mic", height=90, pad=20)
        b.show()
        cells += frames(b, [(0.5, None, "idle"), (0.3, lambda: b.set_level(0.3), "talking"),
                            (0.4, b.burst, "notes"), (0.3, b.build, "dash"),
                            (0.8, None, "dust cloud"), (1.5, None, "hammer"),
                            (0.6, lambda: b.stop_building(True), "cheer")])
        sad = bunnywidget.BunnyWidget(height=90, pad=20, sad=0.8, lines=("Feed me!",))
        sad.show()
        cells += frames(sad, [(3.5, None, "sad + begging")])
        nap = bunnywidget.BunnyWidget(height=90, pad=20, naps=True)
        nap.show()
        cells += frames(nap, [(2.0, None, "asleep")])
        cross = bunnywidget.BunnyWidget(height=90, pad=20, pong=True)
        cross.show()
        cells += frames(cross, [(0.2, lambda: [cross.poke() for _ in range(5)], "cross"),
                                (0.1, cross.fetch_bat, "bat dash"),
                                (2.6, None, "bat back")])
        robo = bunnywidget.BunnyWidget(height=90, pad=20, robot=True)
        robo.show()
        cells += frames(robo, [(0.3, None, "robot")])
        show = setupshow.SetupShow(height=58)
        show.resize(260, 110)
        cells += frames(show, [(0.1, show.start, "setup show"),
                               (2.5, None, "show building")])
        sc = scribebun.ScribeBunny()
        sc.show()
        cells += frames(sc, [(0.3, sc.reset, "scribe wait"),
                             (1.0, lambda: sc.set_progress(0.5), "scribe writing"),
                             (0.4, lambda: sc.finish(False), "scribe failed")])
        cells.append(("smug box", bunny.bunny_pixmap(84, smug=True)))
        for w in (b, sad, nap, cross, robo, show, sc):
            w.close()
        return name, cells

    try:
        rows = [row(name) for name in themes]
    finally:
        time.monotonic = real
    return grid(rows, 170, 170)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet", choices=("outfits", "poses", "live", "owls", "owl"))
    ap.add_argument("--themes", default=",".join(MIX))
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "bun-sheets"))
    a = ap.parse_args()
    QApplication.instance() or QApplication([])
    themes = [t.strip() for t in a.themes.split(",") if t.strip() in theme.THEMES]
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"{a.sheet}.png")
    sheets = {"outfits": outfits, "poses": poses, "live": live, "owls": owls, "owl": owl}
    sheets[a.sheet](themes).save(path)
    print(path)


if __name__ == "__main__":
    main()
