"""Download the audio of a web link, with yt-dlp.

Used by the Sounds tab's link bar ("Add as sound" / "Play once"): yt-dlp fetches the
best audio stream the site offers (YouTube, SoundCloud, and the other sites it supports) into
a temporary folder, and the file is then imported like a dropped file (so m4a /
webm audio needs ffmpeg, as it does for a dropped file). Nothing is converted to
MP3 on the way: the library stores it losslessly as a FLAC of what was decoded.

yt-dlp is imported lazily: it's a big package and only needed on click.

Keeping it working: YouTube changes often and yt-dlp follows within days, but the
built app can't pip-install. So a newer yt-dlp is fetched from PyPI and unpacked into
%APPDATA%\\OnionBoard\\yt-dlp\\current, but only a version the project approved:
pins/yt-dlp.json on the repo's main branch (APPROVED_URL) lists them, each with the
SHA-256 of its yt-dlp and yt-dlp-ejs wheels. A weekly job adds new releases to it once
their PyPI attestations check out (scripts/pinbump/ytdlp.py), and merging its PR
approves one. The app also waits until a version has been on PyPI for MIN_AGE_S, so a
bad release gets caught and pulled first. The wheels are checked against the list's
hashes, not PyPI's. When downloads broke and nothing approved fixes them yet, Force
update (force_newest) takes PyPI's newest right away, after a warning in Settings,
checked only against PyPI's SHA-256. An import hook (_Finder) makes the copy win over
the bundled one.
That only happens when the user asks (Settings → Updates: Update now / Reinstall), or,
if they opted in (off by default: it's code the app runs), once a day and when a
download fails. "Reinstall" deletes the copy and its cache and fetches a fresh one.
A copy older than the bundled yt-dlp (the app itself was updated) is dropped at startup.

An update never leaves downloads worse off than the built-in copy: it takes the
newest approved release (never one older than the built-in copy) whose wheel says it
runs on this app's Python (one that needs a newer Python is skipped, not installed),
and a downloaded copy that fails to import is dropped on first use, remembered as bad
(never fetched again) and the built-in one used instead.

The code lives in the modules beside this one; this one gathers their names, so
`ytdl.X` and `from soundboard.online.ytdl import X` keep working:

- ytsites: the sites and their switches, the errors, the shared lock, `Result`, Tor retries
- ytupdate: the approved yt-dlp versions, updating, the import hook, Reinstall
- ytfetch: downloading a link's audio, looking one up, yt-dlp's options and errors
- ytsearch: YouTube / SoundCloud search and Myinstants
"""
from __future__ import annotations

import sys
import types
# the modules the code used when it was all here, still reached through ytdl by tests
import calendar  # noqa: F401
import contextlib  # noqa: F401
import hashlib  # noqa: F401
import html  # noqa: F401
import importlib.abc  # noqa: F401
import importlib.machinery  # noqa: F401
import io  # noqa: F401
import json  # noqa: F401
import logging  # noqa: F401
import re  # noqa: F401
import shutil  # noqa: F401
import tempfile  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import urllib.parse  # noqa: F401
import urllib.request  # noqa: F401
import zipfile  # noqa: F401
from collections.abc import Callable  # noqa: F401
from dataclasses import dataclass  # noqa: F401
from pathlib import Path  # noqa: F401
from soundboard.online import jsengine, net, ytworker  # noqa: F401
from soundboard.sounds import library, sourceinfo  # noqa: F401
from soundboard.online import quality  # noqa: F401
from soundboard.core import updates  # noqa: F401
from soundboard.sounds.library import MAX_SECONDS  # noqa: F401
from soundboard.core import errors  # noqa: F401
from soundboard.i18n import _  # noqa: F401
from soundboard.online import ytsites, ytupdate, ytfetch, ytsearch
from soundboard.online.ytsites import (  # noqa: F401
    blocked_by_site, BROWSER_HEADERS, DownloadError, FEATURE, FetchError, _gate, IMAGE_EXTS, _lock,
    MAX_BYTES, MYINSTANTS, _over_tor, PLAYLIST, PROGRESS_EVERY_S, Result, RETRY_CHECK_AFTER,
    RETRY_CLIENTS,
    RETRY_PAUSE_S, _SharedLock, silent_over_tor, site_allowed, site_feature, _site_name, site_of,
    SOURCES, SwitchedOff, TIKTOK_SUFFIX, _TOR_BLOCKED, _TOR_SILENT, TOR_TRIES, TorBlocked,
    _TRY_AGAIN, UPDATE_FEATURE, VIDEO_EXTS, VIDEO_MAX_BYTES)
from soundboard.online.ytupdate import (  # noqa: F401
    active_version, Approved, approved, _approved_entry, APPROVED_MAX, APPROVED_URL, auto_update,
    bundled_version, cache_dir, CHECK_EVERY, due, _Finder, _finder, force_newest, _get, _install,
    install, MIN_AGE_S, _moved_at, override_version, PACKAGES, _pick, _pkg_dir, _purge, _py_ok,
    PYPI, _pypi_file, _pypi_json, PYPI_MAX, _pypi_wheel, reset, root, _save_state, _state, _tidy,
    TIDY_AFTER_S, update, vtuple, _wheel, WHEEL_HOST, WHEEL_MAX)
from soundboard.online.ytfetch import (  # noqa: F401
    as_link, as_links, _check, clean_title, _count_used, _direct_leaf, _direct_title, _download,
    download_audio, _download_direct, DOWNLOAD_QUIET_S, downloadable, _drop_broken, _extract,
    _as_result, _found, lookup, lookup_all, MAX_LINKS, _opts, Playlist, probe, _readable, _remote,
    _run, _run_helper, save_video, _sendable,
    _went_nowhere, _worth_another_try, _ydl)
from soundboard.online.ytsearch import (  # noqa: F401
    _count, _myinstants, _myinstants_page, _playlist_hit, search, _soundcloud_hit,
    _youtube_hit)

log = logging.getLogger(__name__)

# dependencies first: a name one of them imports from another is found in its home first
_PARTS = (ytsites, ytupdate, ytfetch, ytsearch)
# what their code sets again (`global`): never copied here, always read where it lives
_LIVE = {}
_UNSET = object()


class _Ytdl(types.ModuleType):
    """Setting a name here sets it where its code reads it too, as it did when it all
    lived in this module (tests swap functions and constants out:
    `ytdl._get = ...; ytdl.RETRY_PAUSE_S = 0`), and the state its code changes is read
    from where it lives."""

    def __getattr__(self, name: str):
        part = _LIVE.get(name)
        if part is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        return getattr(part, name)

    def __setattr__(self, name: str, value) -> None:
        if name in _LIVE:
            setattr(_LIVE[name], name, value)
            return
        if not name.startswith("__"):
            old = self.__dict__.get(name, _UNSET)
            for part in _PARTS:
                got = part.__dict__.get(name, _UNSET)
                if got is not _UNSET and (got is old or old is _UNSET):
                    setattr(part, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Ytdl
