"""Start over: put parts of the app back to how they were on the first day, with a
restore point saved first so it can all be undone (Settings > General).

A reset or a restore doesn't happen under the running window: the window saves its
settings when it closes, which would put back everything just reset. It's written
down (reset-pending.json), the app restarts, and the next start-up does it before
the window reads the settings.

A restore point is a folder in %APPDATA%\\OnionBoard\\restore-points\\:

    point.json      when, what it was saved before, which parts were reset
    config.json     the settings, hotkeys and pad list as they were
    sounds/         the sounds a reset took off the board (audio)
    thumbs/         ...and their pad pictures
    deleted/        Recently deleted, if the reset emptied it (soundboard.trash)

so restoring one puts back what the reset took away, files and all. The newest
MAX_POINTS are kept; an older point's audio goes to the Windows Recycle Bin.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field, fields
from pathlib import Path

from soundboard import library, trash
from soundboard.i18n import _
from soundboard.library import Config

log = logging.getLogger(__name__)

MAX_POINTS = 5
SETTINGS, HOTKEYS, SOUND_KEYS, SOUNDS, BIN, PROGRAMS, DEVICES = (
    "settings", "hotkeys", "sound_keys", "sounds", "bin", "programs", "devices")
# what each part is called, in English (shown through part_name(): this module can be
# imported before the language is picked, so nothing here is translated at import)
NAMES = {SETTINGS: "Settings", HOTKEYS: "Hotkeys", SOUND_KEYS: "Sound hotkeys",
         SOUNDS: "Sounds", BIN: "Recently deleted", PROGRAMS: "Programs",
         DEVICES: "Audio devices"}
PARTS = tuple(NAMES)


def part_name(part: str) -> str:
    """What `part` is called in the language showing (the guide, the restore point
    list, the toast)."""
    return {SETTINGS: _("Settings"), HOTKEYS: _("Hotkeys"), SOUND_KEYS: _("Sound hotkeys"),
            SOUNDS: _("Sounds"), BIN: _("Recently deleted"), PROGRAMS: _("Programs"),
            DEVICES: _("Audio devices")}.get(part, NAMES.get(part, part))
DEVICE_FIELDS = ("main_device", "mon_device", "mic_device", "obs_device", "also_send",
                 "mon_follows_default", "route")
PROGRAM_FIELDS = ("apps", "apps_paths", "apps_hidden")
# what "Settings" leaves alone: the other parts, what the user made (sounds,
# categories, triggers, radio favourites) and the app's own bookkeeping
KEEP = {"version", "sounds", "categories", "category", "category_hotkeys", "screen",
        "setup_done", "ptt_key", "update_checked", "update_pending", "update_skip",
        "stats_id", "stats_sent", "stats_heard", "mic_first",
        *DEVICE_FIELDS, *PROGRAM_FIELDS}
RADIO_KEEP = ("favorites", "recent")


def hotkey_fields() -> list[str]:
    return [f.name for f in fields(Config) if f.name.endswith("_hotkey")]


def folder() -> Path:
    return library.APP_DIR / "restore-points"


def _pending_path() -> Path:
    return library.APP_DIR / "reset-pending.json"


@dataclass
class Point:
    id: str
    when: float
    label: str                    # "Before reset", "Before restoring" (kept in English)
    parts: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return folder() / self.id

    @property
    def title(self) -> str:
        """The label in the language showing."""
        return {"Before reset": _("Before reset"),
                "Before restoring": _("Before restoring")}.get(self.label, self.label)

    def describe(self) -> str:
        """"Settings, Hotkeys" / "Everything as it was"."""
        return (", ".join(part_name(p) for p in self.parts if p in NAMES)
                or _("Everything as it was"))


# --------------------------------------------------------------------------- schedule
def schedule_reset(parts) -> None:
    """Reset `parts` at the next start-up (the caller restarts the app)."""
    parts = [p for p in PARTS if p in set(parts)]
    _write_pending({"reset": parts})


def schedule_restore(point_id: str) -> None:
    _write_pending({"restore": str(point_id)})


def _write_pending(d: dict) -> None:
    library.APP_DIR.mkdir(parents=True, exist_ok=True)
    _pending_path().write_text(json.dumps(d), encoding="utf-8")


def run_pending() -> str:
    """At start-up, before the window reads the settings: do a reset or restore that
    was asked for. Returns what to tell the user ("" for nothing). Never raises: a
    failure is logged and the app starts as it was."""
    p = _pending_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError):
        log.warning("couldn't read %s", p, exc_info=True)
        raw = {}
    p.unlink(missing_ok=True)   # first: a reset that crashes mustn't run on every start
    try:
        if isinstance(raw, dict) and isinstance(raw.get("reset"), list):
            return reset([str(x) for x in raw["reset"]])
        if isinstance(raw, dict) and isinstance(raw.get("restore"), str):
            return restore(raw["restore"])
    except Exception:  # noqa: BLE001 - start up anyway, on the settings as they are
        log.exception("the reset / restore failed")
        return _("Couldn't finish that: nothing was changed. The log has the details.")
    return ""


# --------------------------------------------------------------------------- reset
def reset(parts: list[str]) -> str:
    parts = [p for p in PARTS if p in set(parts)]
    if not parts:
        return ""
    cfg = Config.load()
    if cfg.read_only:
        return _("Couldn't reset: the settings file was locked. Nothing was changed.")
    point = _new_point("Before reset", parts, cfg)
    if BIN in parts:
        with trash._lock:
            if trash.folder().exists():
                shutil.move(str(trash.folder()), point.path / "deleted")
    if SOUNDS in parts:
        _keep_sounds(cfg, point)
        cfg.sounds, cfg.categories, cfg.category = [], [], ""
    if SETTINGS in parts:
        fresh = Config()
        radio = {k: cfg.radio[k] for k in RADIO_KEEP if k in cfg.radio}
        no_count = "usage_stats" in cfg.net_off
        for f in fields(Config):
            if f.name not in KEEP and not f.name.endswith("_hotkey"):
                setattr(cfg, f.name, getattr(fresh, f.name))
                _forget_newer(cfg, f.name)
        cfg.radio = radio
        if no_count:   # a reset never switches the usage count (back) on
            cfg.net_off.append("usage_stats")
    if HOTKEYS in parts:
        fresh = Config()
        for name in hotkey_fields():
            setattr(cfg, name, getattr(fresh, name))
        cfg.category_hotkeys, cfg.ptt_key = {}, ""
        cfg.overlay_key_checked = False
    if SOUND_KEYS in parts:
        for m in cfg.sounds:
            m.hotkey = ""
    if PROGRAMS in parts:
        cfg.apps, cfg.apps_paths, cfg.apps_hidden = {}, {}, []
    if DEVICES in parts:
        fresh = Config.first_start()   # (what others hear: straight into the mic)
        for name in DEVICE_FIELDS:
            setattr(cfg, name, getattr(fresh, name))
            _forget_newer(cfg, name)
        cfg.setup_done = False   # the quick setup guide picks them again
    if not cfg.save():
        return _("Couldn't save the reset settings. Your restore point is in "
                 "Settings > General.")
    log.info("reset %s (restore point %s)", parts, point.id)
    return _("Reset: {parts}. Changed your mind? Settings > General > Restore points.",
             parts=", ".join(part_name(p) for p in parts))


def _forget_newer(cfg: Config, name: str) -> None:
    """A reset setting is reset for a newer version too: its choice this one doesn't
    know (library._with_raw) isn't written back over the default."""
    getattr(cfg, "_raw_kept", {}).pop(name, None)


def _keep_sounds(cfg: Config, point: Point) -> None:
    """Move the board's audio and pictures into the restore point (only files the app
    keeps itself: a sound linked from elsewhere stays where it is)."""
    for m in cfg.sounds:
        for attr, home, sub in (("file", library.SOUNDS_DIR, "sounds"),
                                ("image", library.THUMBS_DIR, "thumbs")):
            p = Path(getattr(m, attr) or "")
            if getattr(m, attr) and p.parent == home and p.exists():
                try:
                    trash._move(p, point.path / sub)
                except OSError:
                    log.warning("couldn't keep %s in the restore point", p, exc_info=True)
        library.unlink_cache(m.id)


# --------------------------------------------------------------------------- restore
def restore(point_id: str) -> str:
    point = next((p for p in points() if p.id == point_id), None)
    if point is None:
        return _("That restore point is gone.")
    now = Config.load()
    if now.read_only:
        return _("Couldn't restore: the settings file was locked. Nothing was changed.")
    old = Config.from_raw(json.loads((point.path / "config.json").read_text(encoding="utf-8")))
    _new_point("Before restoring", [], now, keep=point.id)   # so this can be undone too
    moved: list[tuple[Path, Path]] = []   # (where it was in the point, where it is now)
    whole = True   # everything came out of the point: it can go
    try:
        for sub, home in (("sounds", library.SOUNDS_DIR), ("thumbs", library.THUMBS_DIR)):
            src = point.path / sub
            if src.is_dir():
                home.mkdir(parents=True, exist_ok=True)
                for f in src.iterdir():
                    if (home / f.name).exists():   # left in the point, not lost with it
                        log.warning("%s is in the library already; kept in the point", f.name)
                        whole = False
                        continue
                    shutil.move(str(f), home / f.name)
                    moved.append((f, home / f.name))
        # the pad list as it was, minus sounds whose audio has gone since (deleted after
        # the point was saved: they're in Recently deleted), plus sounds added since
        ids = {m.id for m in old.sounds}
        old.sounds = [m for m in old.sounds if Path(m.file).exists()]
        old.sounds += [m for m in now.sounds if m.id not in ids]
        library.merge_tags(now.categories, old.categories)   # appends the new ones
        saved = old.save()
    except Exception:
        if not _put_back(moved):
            log.exception("the restore failed partway")
            return _("Couldn't finish restoring, and some of its sounds couldn't be put "
                     "back in the restore point: they're in your library's sounds folder. "
                     "The log has the details.")
        raise   # put back as it was: "nothing was changed" is true
    if not saved:
        if not _put_back(moved):
            return _("Couldn't save the restored settings, and some of its sounds are in "
                     "your library's sounds folder now. The log has the details.")
        return _("Couldn't save the restored settings. Nothing was changed.")
    bin_note = ""
    if (point.path / "deleted").is_dir():
        try:   # the settings are restored now: a bin that won't come in stays in the point
            done = trash.adopt(point.path / "deleted")
        except Exception:  # noqa: BLE001
            log.exception("couldn't bring Recently deleted back from %s", point.id)
            done = False
        if not done:
            whole = False
            bin_note = " " + _("Some of Recently deleted couldn't be brought back: it's "
                               "kept in this restore point.")
    if whole:
        _remove(point.path, recycle=False)
    else:   # kept (and listed): what's left in it isn't lost
        log.warning("restored %s, but kept it: some of it is still only in there", point.id)
    log.info("restored %s", point.id)
    return _("Restored: {parts} from {ago}.", parts=point.describe(),
             ago=trash.ago(point.when)) + bin_note


def _put_back(moved: list[tuple[Path, Path]]) -> bool:
    """Undo a restore's moves (newest first). False if any file couldn't go back."""
    ok = True
    for was, now in reversed(moved):
        try:
            was.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(now), was)
        except OSError:
            log.warning("couldn't put %s back in the restore point", now, exc_info=True)
            ok = False
    return ok


# --------------------------------------------------------------------------- points
def points() -> list[Point]:
    """The restore points, newest first."""
    out = []
    try:
        dirs = [d for d in folder().iterdir() if d.is_dir()]
    except OSError:
        return []
    for d in dirs:
        try:
            raw = json.loads((d / "point.json").read_text(encoding="utf-8"))
            out.append(Point(d.name, float(raw["when"]), str(raw.get("label", "")),
                             [str(p) for p in raw.get("parts", []) if p in NAMES]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(out, key=lambda p: p.when, reverse=True)


def delete_point(point_id: str) -> None:
    p = next((p for p in points() if p.id == point_id), None)
    if p is not None:
        _remove(p.path)


def _new_point(label: str, parts: list[str], cfg: Config, keep: str = "") -> Point:
    """Save the settings as they are now, and make room: only MAX_POINTS are kept
    (and `keep`, the one being restored)."""
    point = Point(f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}", time.time(),
                  label, list(parts))
    point.path.mkdir(parents=True)
    (point.path / "config.json").write_text(json.dumps(cfg.to_raw(), indent=2),
                                            encoding="utf-8")
    (point.path / "point.json").write_text(
        json.dumps({"when": point.when, "label": label, "parts": point.parts}),
        encoding="utf-8")
    for old in [p for p in points() if p.id not in (point.id, keep)][MAX_POINTS - 1:]:
        _remove(old.path)
    return point


def _remove(path: Path, recycle: bool = True) -> None:
    """Delete a restore point: audio still in it goes to the Windows Recycle Bin."""
    if recycle and library.USE_RECYCLE_BIN:
        for sub in ("sounds", "deleted"):
            for f in (path / sub).glob("*"):
                if f.is_file() and f.suffix.lower() in library.AUDIO_EXTS:
                    library.recycle(f)
    shutil.rmtree(path, ignore_errors=True)
