"""Radio tab back end: the station directory, the stream player and the map's data.

Stations come from Radio Browser (https://www.radio-browser.info), a free,
community-run open directory of ~60 000 internet radio stations with an open API
and no key. Most stations carry a latitude / longitude, which the map uses.
The app asks it for: the most-listened stations that have a location (the map,
cached for a day in radio_dir()), searches you type, and a "click" when you
start a station (the directory's own popularity count, which it asks clients to
send; Settings > Privacy & security turns it off). Nothing else about you is sent. With Radio
switched off in Settings > Privacy & security none of it goes online (FEATURE): the
tab shows an "off" panel instead and the relay refuses the directory and the streams.

The player is Qt Multimedia (FFmpeg): it opens the stream (MP3, AAC, Ogg, HLS…)
and decodes it, but never plays it itself. A QAudioBufferOutput hands the decoded
audio to the UI thread as 48 kHz stereo float, which goes into the engine
(`Engine.feed_radio`) like an app's captured audio (Apps tab), so it can go out
with your sounds.

The map is painted by Qt (ui/radio/flatmap.py). Its country outlines ship with the app
(ASSET_DIR), so opening it contacts nobody: no CDN learns who opened the Radio tab.
(Up to 1.9.7 an "HD" button swapped in a 3D globe, globe.gl in a web view. It went:
the web engine cost ~200 MB of the install, forced GPU drawing on every window and
kept Chromium in the app once opened.)

The code lives in the modules beside this one; this one gathers their names, so
`radio.X` and `from soundboard.online.radio import X` keep working:

- radiostation: Radio Browser's addresses, a station (`Station`), reading its answers
- radiomap: the map's country outlines and labels, station dots and town names
- radiodir: the directory client (`RadioDirectory`): the map's list, searches, clicks
- radioplayer: the stream player (`RadioPlayer`) and preloading its decoder
"""
from __future__ import annotations

import sys
import types
# the modules the code used when it was all here, still reached through radio by tests
import base64  # noqa: F401
import hashlib  # noqa: F401
import ipaddress  # noqa: F401
import json  # noqa: F401
import logging  # noqa: F401
import random  # noqa: F401
import re  # noqa: F401
import socket  # noqa: F401
import tempfile  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import unicodedata  # noqa: F401
from dataclasses import asdict, dataclass, field  # noqa: F401
from functools import cached_property  # noqa: F401
from pathlib import Path  # noqa: F401
from urllib.parse import quote  # noqa: F401
import numpy as np  # noqa: F401
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal  # noqa: F401
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QMediaMetaData, QMediaPlayer  # noqa: F401
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest  # noqa: F401
from soundboard.sounds import library  # noqa: F401
from soundboard.online import quality  # noqa: F401
from soundboard.online import net, netlog  # noqa: F401
from soundboard.i18n import _  # noqa: F401
from soundboard.audio.engine import SR  # noqa: F401
from soundboard.online import radiostation, radiomap, radiodir, radioplayer
from soundboard.online.radiostation import (  # noqa: F401
    API_BASES, _array, ASSET_DIR, CACHE_S, CONNECT_S, COUNTRIES, COUNTRIES_SRI, COUNTRY_NAMES,
    _DECODER, directory_down, directory_unreachable, FEATURE, fold, GLOBE_FIRST, GLOBE_LIMIT,
    _http, loads_gently, _local_ip, _name_is_local, _num, parse_stations, PLACES, PLAYLIST_EXTS,
    radio_dir, _refused, RETRIES, SEARCH_LIMIT, SEARCH_MAX_CHARS, search_text, _server_down, _skip,
    _SPACE, STALL_S, Station, station_off_air, _stations, STEADY_S, _stream_url, TIMEOUT_MS,
    TOR_CONNECT_S, TOR_RETRIES, USER_AGENT)
from soundboard.online.radiomap import (  # noqa: F401
    _centre, globe_points, _median, _outline_features, outline_labels, outline_rings, town_labels,
    TOWN_SPREAD, TOWNS_MAX)
from soundboard.online.radiodir import (  # noqa: F401
    _cache_lock, fits, _kbps_query, _kept, _let_go, _patience, RadioDirectory, _start_for,
    _the_nam)
from soundboard.online.radioplayer import (  # noqa: F401
    buffer_to_array, _close, _decoder_files, _image_section, _kernel32, preload_decoder,
    RadioPlayer, _tor_ready)

log = logging.getLogger(__name__)

# dependencies first: a name one of them imports from another is found in its home first
_PARTS = (radiostation, radiomap, radiodir, radioplayer)
# what their code sets again (`global`): never copied here, always read where it lives
_LIVE = {"_nam": radiodir, "_preloaded": radioplayer}
_UNSET = object()


class _Radio(types.ModuleType):
    """Setting a name here sets it where its code reads it too, as it did when it all
    lived in this module (tests swap functions and constants out:
    `radio.CONNECT_S = 12.0; radio.QTimer = ...`), and the state its code changes is read
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


sys.modules[__name__].__class__ = _Radio
