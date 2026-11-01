"""Which add-on installs were cut off: the app closed or crashed while one ran.

Each install (AI voices, speech recognition, a translation language, Onion Watch,
Onion Pocket) leaves a small file named after it in %APPDATA%\\OnionBoard\\installing
while it runs, and takes it away however it ends. One still there at the next start
means that install never finished: the window offers to do it again
(ui/window/addonnotice.py). Only the add-on's own key is written, nothing else."""
from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Callable, Iterator
from pathlib import Path

from soundboard.sounds import library

log = logging.getLogger(__name__)

AI_VOICES = "ai-voices"
LIVE_VOICE = "live-voice"
WATCH = "onion-watch"
POCKET = "onion-pocket"
TRANSLATION = "translation-"   # + the language model's module id
_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,80}")


def folder() -> Path:
    return library.APP_DIR / "installing"


def _file(key: str) -> Path | None:
    return folder() / key if _KEY.fullmatch(key) else None


@contextlib.contextmanager
def running(key: str) -> Iterator[None]:
    """Marks `key`'s install as running for the `with` block. A mark that can't be
    written only means a cut-off install isn't offered again: never an error."""
    f = _file(key)
    if f is not None:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.touch()
        except OSError as e:
            log.info("can't mark the %s install as running: %s", key, e)
    try:
        yield
    finally:
        forget(key)


def forget(key: str) -> None:
    f = _file(key)
    if f is not None:
        try:
            f.unlink(missing_ok=True)
        except OSError as e:
            log.info("can't clear the %s install mark: %s", key, e)


def cut_off() -> list[str]:
    """The installs a closed (or crashed) app left unfinished, oldest first."""
    try:
        marks = [p for p in folder().iterdir() if p.is_file() and _KEY.fullmatch(p.name)]
    except OSError:
        return []
    try:
        marks.sort(key=lambda p: p.stat().st_mtime)
    except OSError:
        pass
    return [p.name for p in marks]


def marked(key: str, work: Callable[[], object]) -> Callable[[], None]:
    """`work` (a thread's target) with `key`'s install marked as running."""
    def run() -> None:
        with running(key):
            work()
    return run
