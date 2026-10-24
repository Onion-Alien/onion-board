"""Keeping yt-dlp working for soundboard.online.ytdl: the approved versions
(pins/yt-dlp.json), fetching and checking their wheels into %APPDATA%, the import
hook that makes that copy win over the bundled one, Force update, Reinstall and
the daily check."""
from __future__ import annotations

import calendar
import hashlib
import importlib.abc
import importlib.machinery
import io
import json
import logging
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from soundboard.online import net, ytworker
from soundboard.sounds import library
from soundboard.core import updates
from soundboard.core import errors
from soundboard.i18n import _
from soundboard.online.ytsites import DownloadError, SwitchedOff, UPDATE_FEATURE, _lock

log = logging.getLogger("soundboard.online.ytdl")


PACKAGES = ("yt_dlp", "yt_dlp_ejs")
APPROVED_URL = f"https://raw.githubusercontent.com/{updates.REPO}/main/pins/yt-dlp.json"
APPROVED_MAX = 1 << 20            # the list is a few KB
MIN_AGE_S = 3 * 24 * 3600         # an approved version waits this long after its release
PYPI = "https://pypi.org/pypi/"   # Force update only: PyPI's newest, not yet approved
PYPI_MAX = 5 * 1024 * 1024
WHEEL_HOST = "https://files.pythonhosted.org/"
CHECK_EVERY = 24 * 3600          # automatic update check
WHEEL_MAX = 30 * 1024 * 1024


# ---------------------------------------------------------------------- the updated copy

def root() -> Path:
    return library.APP_DIR / "yt-dlp"


def _pkg_dir() -> Path:
    return root() / "current"


def cache_dir() -> Path:
    return root() / "cache"


def _state() -> dict:
    try:
        return json.loads((root() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(**kw):
    s = _state() | kw
    try:
        root().mkdir(parents=True, exist_ok=True)
        (root() / "state.json").write_text(json.dumps(s), encoding="utf-8")
    except OSError:
        log.warning("couldn't save yt-dlp update state", exc_info=True)


def vtuple(v: str) -> tuple[int, ...]:
    """'2026.08.19' / '2026.8.19.123' -> comparable ints ('' -> ())."""
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def bundled_version() -> str:
    """The yt-dlp that shipped with the app (or is pip-installed, from source)."""
    try:
        from importlib.metadata import version
        return version("yt-dlp")
    except Exception:  # noqa: BLE001 - frozen without metadata, or not installed
        return ""


def override_version() -> str:
    """The downloaded copy's version, if there is one."""
    return _state().get("version", "") if (_pkg_dir() / "yt_dlp").is_dir() else ""


def active_version() -> tuple[str, bool]:
    """(version in use, is it the downloaded copy?)."""
    ov = override_version()
    return (ov, True) if ov else (bundled_version(), False)


class _Finder(importlib.abc.MetaPathFinder):
    """Serves yt_dlp / yt_dlp_ejs from the downloaded copy when there is one. First on
    sys.meta_path, so it also wins over PyInstaller's importer in the built app."""

    def find_spec(self, name, path=None, target=None):
        top = name.partition(".")[0]
        if top not in PACKAGES:
            return None
        base = _pkg_dir()
        if "." in name:
            parent = sys.modules.get(name.rpartition(".")[0])
            search = list(getattr(parent, "__path__", None) or ())
            if not search or not str(search[0]).startswith(str(base)):
                return None   # the parent is the bundled copy: leave it alone
        elif (base / top).is_dir():
            search = [str(base)]
        else:
            return None
        return importlib.machinery.PathFinder.find_spec(name, search)


_finder = _Finder()


def install():
    """Put the import hook in place (idempotent), dropping a stale downloaded copy."""
    if _finder not in sys.meta_path:
        _tidy()
        ov, bv = override_version(), bundled_version()
        if ov and bv and vtuple(ov) < vtuple(bv):
            log.info("dropping downloaded yt-dlp %s: the app ships %s", ov, bv)
            shutil.rmtree(_pkg_dir(), ignore_errors=True)
        sys.meta_path.insert(0, _finder)


TIDY_AFTER_S = 600   # an update unpacks and swaps in seconds: older folders are leftovers


def _moved_at(d: Path) -> float:
    """When update() moved the copy `d` (old-<time_ns>) aside: its name says (the
    folder's own times are the copy's, from when it was unpacked)."""
    try:
        return int(d.name.removeprefix("old-")) / 1e9
    except ValueError:
        return d.stat().st_mtime


def _tidy():
    """Clear what an update cut short left behind: a half-unpacked new-* folder, and
    old-* copies (one is put back first if the swap stopped before `current` was).
    Only ones older than TIDY_AFTER_S: this also runs in each download helper as it
    starts (ytworker, a process of its own), maybe while the app is updating, and a
    fresh new-* or old-* is that update's own."""
    try:
        cutoff = time.time() - TIDY_AFTER_S
        olds = sorted((d for d in root().glob("old-*") if _moved_at(d) < cutoff),
                      key=_moved_at)
        news = [d for d in root().glob("new-*") if d.stat().st_mtime < cutoff]
        bads = list(root().glob("bad-*"))   # a broken copy _drop_broken() couldn't delete
        if olds and not _pkg_dir().exists():
            olds.pop().rename(_pkg_dir())
            log.info("put back the yt-dlp copy an update had moved aside")
        for d in olds + news + bads:
            shutil.rmtree(d, ignore_errors=True)
    except OSError:
        log.warning("couldn't tidy %s", root(), exc_info=True)


def _purge():
    """Forget imported yt-dlp modules so the next import picks up the new copy."""
    for name in [n for n in sys.modules if n.partition(".")[0] in PACKAGES]:
        del sys.modules[name]
    importlib.invalidate_caches()
    ytworker.drop_all()   # the helper process holds the old copy too


def _get(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard (yt-dlp updater)"})
    with net.urlopen(req, timeout=30, feature=UPDATE_FEATURE) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise DownloadError(_("{url} is unexpectedly large", url=url))
    return data


def _py_ok(spec: str | None, have: tuple[int, ...] = tuple(sys.version_info[:3])) -> bool:
    """Does this Python satisfy a wheel's requires_python (">=3.10", ">=3.9,!=3.11.*")?
    One it can't read counts as no: skipping a release is safe, a broken one isn't."""
    def pad(t):
        return (tuple(t) + (0, 0, 0))[:3]
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(~=|==|!=|<=|>=|<|>)\s*(\d+(?:\.\d+)*)(\.\*)?", part)
        if not m:
            return False
        op, want, star = m.group(1), vtuple(m.group(2)), bool(m.group(3))
        if op == "~=":
            ok = tuple(have[:len(want) - 1]) == want[:-1] and pad(have) >= pad(want)
        elif star:
            same = tuple(have[:len(want)]) == want
            ok = same if op == "==" else not same if op == "!=" else False
        else:
            a, b = pad(have), pad(want)
            ok = {"==": a == b, "!=": a != b, "<=": a <= b, ">=": a >= b,
                  "<": a < b, ">": a > b}[op]
        if not ok:
            return False
    return True


@dataclass
class Approved:
    """One version from the approved list, with its wheels (yt-dlp's first)."""
    version: str
    uploaded: float          # when it went up on PyPI (a timestamp)
    wheels: list[dict]       # {"filename", "url", "sha256", "requires_python", ...}


def _approved_entry(e) -> Approved | None:
    """One of the list's versions, or None when it's one the app mustn't take: not a
    final release, a wheel that isn't a pure-Python one on PyPI's file host, a hash that
    isn't a SHA-256."""
    try:
        version = str(e["version"])
        uploaded = calendar.timegm(time.strptime(str(e["uploaded"])[:19],
                                                 "%Y-%m-%dT%H:%M:%S"))   # UTC
        wheels = list(e["wheels"])
        ok = (re.fullmatch(r"\d+(\.\d+)+", version) and wheels
              and wheels[0].get("name") == "yt-dlp"
              and all(str(w["url"]).startswith(WHEEL_HOST)
                      and str(w["filename"]).endswith("-py3-none-any.whl")
                      and str(w["url"]).endswith("/" + str(w["filename"]))
                      and re.fullmatch(r"[0-9a-f]{64}", str(w["sha256"])) for w in wheels))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None
    return Approved(version, uploaded, wheels) if ok else None


def approved() -> list[Approved]:
    """The versions the project approved (APPROVED_URL) that the app may take. Raises
    DownloadError when the list can't be read; net.FeatureOff when updating yt-dlp is
    switched off or the app is in Offline mode."""
    raw = _get(APPROVED_URL, APPROVED_MAX)
    try:
        versions = json.loads(raw)["versions"]
        if not isinstance(versions, list):
            raise TypeError(versions)
    except (ValueError, KeyError, TypeError) as e:
        raise DownloadError(_("The list of approved yt-dlp versions couldn't be read")) from e
    return [a for e in versions if (a := _approved_entry(e))]


def _pick(versions: list[Approved], now: float | None = None) -> Approved | None:
    """The newest approved version this app can run: out for MIN_AGE_S, every wheel
    for this Python, never failed here before. None if there's none."""
    bad = set(_state().get("bad") or ())
    cutoff = (time.time() if now is None else now) - MIN_AGE_S
    fits = [a for a in versions
            if a.version not in bad and a.uploaded <= cutoff
            and all(_py_ok(w.get("requires_python")) for w in a.wheels)]
    return max(fits, key=lambda a: vtuple(a.version), default=None)


def _wheel(w: dict) -> bytes:
    """One listed wheel, checked against the list's SHA-256."""
    data = _get(w["url"], WHEEL_MAX)
    if hashlib.sha256(data).hexdigest() != w["sha256"]:
        raise DownloadError(_("{file} failed its checksum", file=w["filename"]))
    return data


def update(force: bool = False) -> str:
    """Fetch the newest approved yt-dlp if it's newer than what's in use (or always,
    with force, unless it's older than the built-in one). Returns a short message for
    the user; raises DownloadError on failure (SwitchedOff when updating it is switched
    off in Settings > Privacy & security, or in Offline mode)."""
    if not net.allowed(UPDATE_FEATURE):
        raise SwitchedOff(net.off_message(UPDATE_FEATURE))
    pick = _pick(approved())
    latest = pick.version if pick else ""
    current, __ = active_version()
    _save_state(checked=time.time())
    if not pick:
        log.info("no approved yt-dlp is out long enough and runs here: keeping %s", current)
    bundled = bundled_version()
    if (not pick or (bundled and vtuple(latest) < vtuple(bundled))
            or (not force and current and vtuple(latest) <= vtuple(current))):
        return _("yt-dlp {version} is up to date.", version=current)
    return _install(latest, [_wheel(w) for w in pick.wheels])


def _install(latest: str, wheels: list[bytes]) -> str:
    """Unpack checked wheels into a new copy and swap it in for the one in use."""
    root().mkdir(parents=True, exist_ok=True)
    new = Path(tempfile.mkdtemp(prefix="new-", dir=root()))
    try:
        for data in wheels:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(new, [n for n in z.namelist() if n.split("/")[0] in PACKAGES])
        if not (new / "yt_dlp" / "__init__.py").is_file():
            raise DownloadError(_("the yt-dlp wheel didn't contain yt_dlp"))
        with _lock.exclusive():   # not while a download is using the old copy
            old = root() / f"old-{time.time_ns()}"
            if _pkg_dir().exists():
                _pkg_dir().rename(old)
            try:
                new.rename(_pkg_dir())
            except OSError as e:   # put the copy in use back, or downloads break
                if old.exists():
                    old.rename(_pkg_dir())
                raise DownloadError(_("couldn't swap in the new yt-dlp ({error})",
                                      error=errors.plain(e))) from e
            shutil.rmtree(old, ignore_errors=True)
            _save_state(version=latest)
            _purge()
    finally:
        shutil.rmtree(new, ignore_errors=True)
    log.info("yt-dlp updated to %s", latest)
    return _("Updated yt-dlp to {version}.", version=latest)


# ---- Force update: PyPI's newest, not yet approved (the user asked, after a warning)

def _pypi_file(files) -> dict | None:
    """A PyPI release's pure-Python wheel this app can use: not yanked, on PyPI's file
    host, for this Python."""
    for f in files or ():
        if (f.get("packagetype") == "bdist_wheel"
                and str(f.get("filename", "")).endswith("-py3-none-any.whl")
                and str(f.get("url", "")).startswith(WHEEL_HOST)
                and not f.get("yanked") and _py_ok(f.get("requires_python"))):
            return f
    return None


def _pypi_json(name: str, version: str = "") -> dict:
    path = f"{name}/{version}/json" if version else f"{name}/json"
    try:
        meta = json.loads(_get(PYPI + path, PYPI_MAX))
        meta["info"]["version"]   # noqa: B018 - it's there, or the answer is junk
        return meta
    except (ValueError, KeyError, TypeError) as e:
        raise DownloadError(_("PyPI sent an answer that couldn't be read")) from e


def _pypi_wheel(name: str, version: str) -> bytes:
    """One release's wheel, checked against the SHA-256 PyPI lists for it."""
    f = _pypi_file(_pypi_json(name, version).get("urls"))
    if f is None:
        raise DownloadError(_("no wheel for {package}", package=name))
    return _wheel({"url": f["url"], "filename": f["filename"],
                   "sha256": f["digests"]["sha256"]})


def force_newest() -> str:
    """Settings > Updates: Force update, for when downloads broke and no approved
    version fixes them yet. Installs PyPI's newest final yt-dlp that runs here (and
    its pinned yt-dlp-ejs) right away: not on the approved list, not 3 days old,
    checked only against PyPI's own SHA-256. Never older than the built-in copy or
    one that failed here; one already in use is left as it is."""
    if not net.allowed(UPDATE_FEATURE):
        raise SwitchedOff(net.off_message(UPDATE_FEATURE))
    bad = set(_state().get("bad") or ())
    releases = _pypi_json("yt-dlp").get("releases") or {}
    latest = max((v for v, files in releases.items()
                  if re.fullmatch(r"\d+(\.\d+)+", v) and v not in bad and _pypi_file(files)),
                 key=vtuple, default="")
    current, __ = active_version()
    _save_state(checked=time.time())
    if not latest or (current and vtuple(latest) <= vtuple(current)):
        return _("yt-dlp {version} is up to date.", version=current)
    meta = _pypi_json("yt-dlp", latest)
    pin = next((m.group(1) for r in meta["info"].get("requires_dist") or ()
                if (m := re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", r))), None)
    wheels = [_pypi_wheel("yt-dlp", latest)]
    if pin:
        wheels.append(_pypi_wheel("yt-dlp-ejs", pin))
    log.warning("force-installing yt-dlp %s from PyPI: not on the approved list", latest)
    return _install(latest, wheels)


def reset() -> str:
    """For when it's thoroughly broken: delete the downloaded copy and yt-dlp's cache,
    then download the latest again (falling back to the bundled one if that fails).
    Switched off, it does nothing (raises SwitchedOff): a reset that can't fetch a
    fresh copy would only throw the working one away."""
    if not net.allowed(UPDATE_FEATURE):
        raise SwitchedOff(net.off_message(UPDATE_FEATURE))
    with _lock.exclusive():
        shutil.rmtree(root(), ignore_errors=True)
        _purge()
    try:
        msg = update(force=True)
        if not override_version():   # nothing approved is newer than the built-in one
            return msg
        return _("Reinstalled yt-dlp {version}.", version=override_version())
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp reinstall failed: %s", e)
        v = bundled_version()
        if v:
            return _("Cleared, but couldn't download a fresh copy ({error}). "
                     "Using the built-in yt-dlp {version}.", error=errors.plain(e), version=v)
        return _("Cleared, but couldn't download a fresh copy ({error}). "
                 "Try again when you're online.", error=errors.plain(e))


def due(every: float = CHECK_EVERY) -> bool:
    return time.time() - float(_state().get("checked", 0)) >= every


def auto_update(enabled: bool):
    """The daily background check (call from a thread); switched off in Settings >
    Privacy & security, it skips itself."""
    if not enabled or not net.allowed(UPDATE_FEATURE) or not due():
        return
    try:
        log.info(update())
    except Exception as e:  # noqa: BLE001 - offline etc.: try again next time
        log.info("yt-dlp update check failed: %s", e)
