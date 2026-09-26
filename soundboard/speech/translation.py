"""Translation models for the live computer voice (the "translation" add-ons).

Each language is an add-on (modules/translate-xx/module.json) that names one
model package: an Argos Translate `.argosmodel` zip with a CTranslate2 model and a
SentencePiece tokenizer. Nothing is fetched until the user presses Download for
that language. Then:

    url --stream--> translation\\xx.part   (sha256 checked against module.json)
        --unpack--> translation\\xx\\model\\…, sentencepiece.model

Only those files are taken from the zip, under names chosen here, so an archive
can't write anywhere else. The live-voice helper loads the folder with
`--translate <folder>` and translates each sentence on this PC.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from soundboard import library

log = logging.getLogger(__name__)

CHUNK = 1 << 16
TIMEOUT_S = 30
MODEL_FILES = ("model.bin", "config.json", "shared_vocabulary.json", "shared_vocabulary.txt")


class Cancelled(Exception):
    pass


def base_dir() -> Path:
    return library.APP_DIR / "translation"


def model_dir(info) -> Path:
    """Where a language's model lives once downloaded (%APPDATA%\\OnionBoard\\translation\\xx)."""
    return base_dir() / info.language


def is_downloaded(info) -> bool:
    d = model_dir(info)
    return (d / "model" / "model.bin").is_file() and (d / "sentencepiece.model").is_file()


def size_mb(info) -> int:
    return round(int(info.download.get("bytes", 0) or 0) / 1e6)


def download(info, on_progress: Callable[[int, int], None] = lambda done, total: None,
             cancelled: Callable[[], bool] = lambda: False) -> None:
    """Fetch, check and unpack a language's model. Blocking: call from a worker thread.
    Raises RuntimeError (with a message for the user) or Cancelled."""
    url, want = info.download["url"], info.download["sha256"].lower()
    total = int(info.download.get("bytes", 0) or 0)
    part = base_dir() / f"{info.language}.part"
    h = hashlib.sha256()
    done = 0
    log.info("downloading translation model %s from %s", info.language, url)
    try:
        base_dir().mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r, open(part, "wb") as f:  # noqa: S310
            total = int(r.headers.get("Content-Length") or total)
            while chunk := r.read(CHUNK):
                if cancelled():
                    raise Cancelled
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                on_progress(done, total)
        if h.hexdigest() != want:
            raise RuntimeError("the download didn't match its checksum, so it wasn't used")
        _unpack(part, model_dir(info))
    except OSError as e:
        raise RuntimeError(f"download failed: {e}") from e
    finally:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass            # a leftover .part is overwritten by the next try
    log.info("translation model %s ready", info.language)


def _unpack(zip_path: Path, dest: Path) -> None:
    """Take the model files out of the package (whatever its top folder is called)."""
    tmp = dest.with_name(dest.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "model").mkdir(parents=True)
    got = set()
    try:
        with zipfile.ZipFile(zip_path) as z:
            for member in z.infolist():
                parts = PurePosixPath(member.filename).parts
                if member.is_dir() or len(parts) < 2:
                    continue
                rel = parts[1:]              # drop the package's own top folder
                if rel == ("sentencepiece.model",):
                    out = tmp / "sentencepiece.model"
                elif len(rel) == 2 and rel[0] == "model" and rel[1] in MODEL_FILES:
                    out = tmp / "model" / rel[1]
                else:
                    continue                 # README, stanza sentence splitter, anything else
                with z.open(member) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
                got.add(out.relative_to(tmp).as_posix())
        if not {"model/model.bin", "sentencepiece.model"} <= got:
            raise RuntimeError("the download isn't a translation model")
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, NotImplementedError) as e:
        raise RuntimeError("the download isn't a translation model") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def remove(info) -> None:
    shutil.rmtree(model_dir(info), ignore_errors=True)
