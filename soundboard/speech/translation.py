"""Translation models and voices for Speak another language (the "translation" add-ons).

Each language is an add-on (modules/translate-xx/module.json) that names one
model package: an Argos Translate `.argosmodel` zip with a CTranslate2 model and a
SentencePiece tokenizer. Nothing is fetched until the user presses Download for
that language. Then:

    url --stream--> translation\\xx.part   (sha256 checked against module.json)
        --unpack--> translation\\xx\\model\\…, sentencepiece.model

Only those files are taken from the zip, under names chosen here, so an archive
can't write anywhere else. The live-voice helper loads the folder with
`--translate <folder>` and translates each sentence on this PC.

Its "voice" (a Piper voice that reads the translated lines out loud, through the AI
voices add-on's reader.py) comes with it, into translation\\xx\\voice\\ (voice.onnx
and voice.onnx.json, each checked against its sha256). A language downloaded before
it had a voice isn't counted as downloaded until the voice is in too: Download then
fetches just the voice.
"""
from __future__ import annotations

import logging
import shutil
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from soundboard.sounds import library
from soundboard.online import net
from soundboard.core import errors
from soundboard.i18n import _

log = logging.getLogger(__name__)

CHUNK = 1 << 16
TIMEOUT_S = 30
DEFAULT_CAP = 300_000_000   # when module.json lists no size (the models are ~100 MB)
MODEL_FILES = ("model.bin", "config.json", "shared_vocabulary.json", "shared_vocabulary.txt")
VOICE_FILE = "voice.onnx"


class Cancelled(Exception):
    pass


def base_dir() -> Path:
    return library.APP_DIR / "translation"


def model_dir(info) -> Path:
    """Where a language's model lives once downloaded (%APPDATA%\\OnionBoard\\translation\\xx)."""
    return base_dir() / info.language


def model_ready(info) -> bool:
    d = model_dir(info)
    return (d / "model" / "model.bin").is_file() and (d / "sentencepiece.model").is_file()


def voice_file(info) -> Path:
    """The language's Piper voice (its .onnx.json lies beside it)."""
    return model_dir(info) / "voice" / VOICE_FILE


def voice_ready(info) -> bool:
    """Its voice is in (or it lists none)."""
    f = voice_file(info)
    return not info.voice or (f.is_file() and f.with_name(VOICE_FILE + ".json").is_file())


def is_downloaded(info) -> bool:
    return model_ready(info) and voice_ready(info)


def _parts(info) -> list[tuple[str, str, int, Path]]:
    """What's still to fetch: (url, sha256, bytes, where it goes)."""
    todo = []
    if not model_ready(info):
        d = info.download
        todo.append((d["url"], d["sha256"], int(d.get("bytes", 0) or 0),
                     base_dir() / f"{info.language}.part"))
    v = info.voice
    if v and not voice_ready(info):
        f = voice_file(info)
        todo.append((v["url"], v["sha256"], int(v.get("bytes", 0) or 0), f))
        todo.append((v["config_url"], v["config_sha256"], int(v.get("config_bytes", 0) or 0),
                     f.with_name(VOICE_FILE + ".json")))
    return todo


def size_mb(info) -> int:
    """What Download still has to fetch: the model and its voice, or just the voice for
    a language downloaded before it had one."""
    todo = _parts(info) or _parts_all(info)
    return max(1, round(sum(n for _u, _s, n, _p in todo) / 1e6))


def _parts_all(info) -> list[tuple[str, str, int, Path]]:
    """Everything a language downloads (for its size once it's all in)."""
    d, v = info.download, info.voice
    return [("", "", int(d.get("bytes", 0) or 0), Path())] + (
        [("", "", int(v.get("bytes", 0) or 0), Path())] if v else [])


def max_bytes(listed: int) -> int:
    """The most a download may be: half again its listed size, so a bad mirror or an
    endless reply is cut off instead of filling the disk."""
    return listed * 3 // 2 if listed > 0 else DEFAULT_CAP


def download(info, on_progress: Callable[[int, int], object] = lambda done, total: None,
             cancelled: Callable[[], bool] = lambda: False) -> None:
    """Fetch, check and unpack what a language still lacks: its model, its voice or
    both. Blocking: call from a worker thread. Raises RuntimeError (with a message for
    the user) or Cancelled."""
    todo = _parts(info)
    total = sum(n for _u, _s, n, _p in todo)
    before = 0
    for url, want, size, dest in todo:
        model = dest.suffix == ".part"
        tmp = dest if model else dest.with_name(dest.name + ".part")
        log.info("downloading the %s %s from %s", info.language,
                 "translation model" if model else "voice", url)
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard"})
            with (net.urlopen(req, timeout=TIMEOUT_S, feature="voices") as r,
                  open(tmp, "wb") as f):
                got = net.read_capped(
                    r, f, max_bytes(size), chunk=CHUNK, total=size,
                    progress=lambda done, _t, b=before: on_progress(b + done, total),
                    check=_stop_if(cancelled))
                length = net.content_length(r.headers)
            if length and tmp.stat().st_size < length:
                # the connection ended part-way (urllib reads that as the end of the
                # file): say so, not "checksum"
                raise ConnectionAbortedError("the download stopped part-way")
            if got != want.lower():
                raise RuntimeError("the download didn't match its checksum, so it wasn't used")
            if model:
                keep = _keep_voice(info)   # unpacking replaces the whole folder
                try:
                    _unpack(tmp, model_dir(info))
                finally:
                    _put_back(info, keep)
            else:
                tmp.replace(dest)
        except net.TooBig:
            raise RuntimeError(_("the download is far bigger than it should be")) from None
        except OSError as e:
            raise RuntimeError(f"download failed: {errors.plain(e)}") from e
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass            # a leftover .part is overwritten by the next try
        before += size
    log.info("translation %s ready", info.language)


def _keep_voice(info) -> Path | None:
    """The voice folder, moved aside while the model is unpacked over its folder."""
    v = model_dir(info) / "voice"
    if not v.is_dir():
        return None
    keep = base_dir() / f"{info.language}.voice"
    shutil.rmtree(keep, ignore_errors=True)
    v.rename(keep)
    return keep


def _put_back(info, keep: Path | None) -> None:
    if keep is not None and keep.is_dir():
        model_dir(info).mkdir(parents=True, exist_ok=True)
        keep.rename(model_dir(info) / "voice")


def _stop_if(cancelled: Callable[[], bool]) -> Callable[[], None]:
    def check():
        if cancelled():
            raise Cancelled
    return check


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
    """The language's model, and what a download cut short by a crash or End task left
    (its .part, the half-unpacked .new folder)."""
    d = model_dir(info)
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(d.with_name(d.name + ".new"), ignore_errors=True)
    shutil.rmtree(base_dir() / f"{info.language}.voice", ignore_errors=True)
    try:
        (base_dir() / f"{info.language}.part").unlink(missing_ok=True)
    except OSError:
        pass
