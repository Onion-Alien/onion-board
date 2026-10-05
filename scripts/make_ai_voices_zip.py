"""Pack the optional AI voices add-on for its GitHub release (soundboard/aiaddon.py).

    python scripts/make_ai_voices_zip.py --model <folder from export_model.py> [--out dist]

AiVoices-module.zip holds one ai-voices/ folder: the add-on's code from
modules/ai-voices (no .venv, caches or dev tools' output) plus the voice model in
ai-voices/model/. Upload it to the "ai-voices" release; GitHub lists its SHA-256,
which the app checks before installing it.
"""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "modules" / "ai-voices"
MODEL_FILES = ("stream.onnx", "speaker.onnx", "voices.npz")
SKIP_DIRS = {".venv", "__pycache__", "model"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    a = ap.parse_args()
    missing = [f for f in MODEL_FILES if not (a.model / f).is_file()]
    if missing:
        raise SystemExit(f"{a.model} is missing {', '.join(missing)} (run tools/export_model.py)")
    a.out.mkdir(parents=True, exist_ok=True)
    z = a.out / "AiVoices-module.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(SRC.rglob("*")):
            rel = f.relative_to(SRC)
            if f.is_dir() or SKIP_DIRS & set(rel.parts) or f.suffix == ".pyc":
                continue
            zf.write(f, f"ai-voices/{rel.as_posix()}")
        for name in MODEL_FILES:
            zf.write(a.model / name, f"ai-voices/model/{name}")
    data = z.read_bytes()
    print(f"{z}  {len(data) / 1e6:.1f} MB  SHA-256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
