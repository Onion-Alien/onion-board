"""Turn generated pictures into the app's artwork (assets/art/<key>.png).

    .venv\\Scripts\\python scripts\\prepare_art.py <folder of pictures>

Each picture whose file name starts with a key from assets/art/README.md (e.g.
"voice-chipmunk.png", "voice-chipmunk (2).jpg", "lang-zh_final.webp") is
centre-cropped to a square, shrunk to 256 px and saved as assets/art/<key>.png.
Anything else in the folder is listed and skipped. Pictures already in assets/art
are replaced.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "assets" / "art"
SIDE = 256
EXTS = {".png", ".jpg", ".jpeg", ".webp"}

KEYS = ["voice-chipmunk", "voice-deep-voice", "voice-demon", "voice-robot", "voice-alien",
        "voice-ghost", "voice-walkie-talkie", "voice-old-telephone", "voice-megaphone",
        "voice-stadium-announcer", "voice-cave", "voice-podcast-voice", "voice-custom",
        "voice-computer", "lang-en", "lang-de", "lang-es", "lang-fr", "lang-ru", "lang-zh"]


def key_for(name: str) -> str:
    stem = name.lower()
    # the longest match first: "voice-deep-voice" before a hypothetical "voice-deep"
    return next((k for k in sorted(KEYS, key=len, reverse=True) if stem.startswith(k)), "")


def main(src: Path) -> int:
    QGuiApplication([])
    ART.mkdir(parents=True, exist_ok=True)
    done, skipped = [], []
    for f in sorted(src.iterdir()):
        if f.suffix.lower() not in EXTS:
            continue
        key = key_for(f.name)
        img = QImage(str(f))
        if not key or img.isNull():
            skipped.append(f.name)
            continue
        side = min(img.width(), img.height())
        img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
        img = img.scaled(SIDE, SIDE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        img.save(str(ART / f"{key}.png"))
        done.append(key)
    print(f"saved {len(done)} to {ART}: {', '.join(done) or '-'}")
    if skipped:
        print("skipped (no key at the start of the name, or not a picture):",
              ", ".join(skipped))
    missing = [k for k in KEYS if not (ART / f"{k}.png").exists()]
    if missing:
        print("still missing:", ", ".join(missing))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
