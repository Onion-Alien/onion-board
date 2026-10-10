"""Paths through folder links Windows refuses to follow.

Newer Windows 11 builds turn down some file operations (making a folder, stat)
on a path that passes through a junction or a drive mounted as a folder it
doesn't trust: error 448, "The path cannot be traversed because it contains an
untrusted mount point". Importing then failed for every file when the sounds
folder (or %APPDATA%) sat behind such a link, or when the file did. The fix:
spell the path out through the links' targets, so nothing is traversed."""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

UNTRUSTED_MOUNT_POINT = 448   # ERROR_UNTRUSTED_MOUNT_POINT
_MAX_LINKS = 40


def is_untrusted(e: BaseException) -> bool:
    return isinstance(e, OSError) and getattr(e, "winerror", None) == UNTRUSTED_MOUNT_POINT


def without_links(p: str | Path, _depth: int = 0) -> Path:
    """`p` with every junction / symlink / folder mount on the way replaced by
    where it points. Parts that can't be read are kept as they are."""
    p = Path(os.path.abspath(p))
    if os.name != "nt" or _depth > _MAX_LINKS:
        return p
    out = Path(p.anchor)
    for part in p.parts[1:]:
        nxt = out / part
        try:
            linked = nxt.is_symlink() or nxt.is_junction()
            target = os.readlink(nxt) if linked else ""
        except (OSError, ValueError):
            target = ""
        if target:
            if target.startswith("\\\\?\\") and target[5:7] == ":\\":
                target = target[4:]   # \\?\D:\... -> D:\... (a volume GUID path stays)
            t = Path(target)
            nxt = without_links(t if t.is_absolute() else out / t, _depth + 1)
        out = nxt
    return out


def first_link(p: str | Path) -> tuple[Path, str] | None:
    """The first junction / symlink / folder mount on the way to `p`, and where it
    points: the one to name when Windows won't go through."""
    p = Path(os.path.abspath(p))
    out = Path(p.anchor)
    for part in p.parts[1:]:
        out = out / part
        try:
            if out.is_symlink() or out.is_junction():
                return out, os.readlink(out).removeprefix("\\\\?\\")
        except (OSError, ValueError):
            return None
    return None


def usable(p: str | Path) -> Path:
    """`p` as it is, unless Windows won't go through a link on its way: then the
    same place, spelled out through the links' targets."""
    p = Path(p)
    try:
        os.stat(p)
        return p
    except OSError as e:
        if not is_untrusted(e):
            return p   # missing etc.: whoever uses it says so
    real = without_links(p)
    log.info("Windows won't follow a link in %s; using %s", p, real)
    return real


def usable_dir(p: str | Path) -> Path:
    """Like usable() for a folder that may not exist yet: checks its nearest
    existing parent, and spells out the whole path if that's what Windows wants."""
    p = Path(p)
    probe = p
    while not _exists(probe) and probe.parent != probe:
        probe = probe.parent
    try:
        os.stat(probe)
        return p
    except OSError as e:
        if not is_untrusted(e):
            return p
    real = without_links(p)
    log.info("Windows won't follow a link in %s; using %s", p, real)
    return real


def _exists(p: Path) -> bool:
    try:
        os.stat(p)
        return True
    except OSError as e:
        return is_untrusted(e)   # it's there, Windows just won't go through
