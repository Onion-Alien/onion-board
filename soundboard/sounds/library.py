"""Sound library: decoding, loudness analysis, the decoded-audio cache and config.

The code lives in the modules beside this one; this one gathers their names, so
`library.X` and `from soundboard.sounds.library import X` keep working:

- paths: the app folder and the sounds, cache, pictures and config.json in it
- config: the settings (`Config`, `SoundMeta`), what a saved value may be, loading them
- saving: writing config.json (atomically, with backups, on a background thread)
- tags: sound categories and subcategories
- levels: int16 / float32 audio, loudness levelling, peaks, trimming silence
- cachefiles: the decoded-audio cache (each sound as int16 .npy, with its effects)
- decoding: reading audio files (libsndfile, else ffmpeg), loading a sound as it plays
- files: the sound files: names, folders, import, recording, delete, tidy
"""
from __future__ import annotations

import logging
import sys
import types
# the modules the code used when it was all here, still reached through library by tests
# (library.os.fsync, library.np.save, conftest's own_module(library, "time"), ...)
import collections, contextlib, hashlib, itertools, json, math, os, re, shutil  # noqa: E401, F401
import struct, subprocess, tempfile, threading, time, uuid  # noqa: E401, F401
from pathlib import Path  # noqa: F401

import numpy as np  # noqa: F401
import soundfile as sf  # noqa: F401
import soxr  # noqa: F401

from soundboard.audio import mapped  # noqa: F401
from soundboard.audio.engine import SR  # noqa: F401
from soundboard.core import profile  # noqa: F401
from soundboard.win import winpath  # noqa: F401
from soundboard.sounds import cachefiles, config, decoding, files, levels, paths, saving, tags
from soundboard.sounds import sourceinfo  # noqa: F401
from soundboard.sounds.paths import (  # noqa: F401
    APP_DIR, CACHE_DIR, CONFIG_PATH, OLD_APP_DIR, RESOURCE_DIR, SOUNDS_DIR, THUMBS_DIR)
from soundboard.sounds.levels import (  # noqa: F401
    I16, level_gain, LEVEL_WIN, peaks, silence_bounds, TARGET_RMS_DB, to_float32, to_int16,
    trim_silence, _under_full_scale)
from soundboard.sounds.saving import (  # noqa: F401
    atomic_write_text, CONFIG_BACKUPS, _rotate_backups, ROTATE_EVERY_S, _rotated, Saver, _write,
    _write_privacy)
from soundboard.sounds.tags import (  # noqa: F401
    CATEGORY_MAX, clean_tags, group_pack_tags, in_view, merge_tags, one_line, plain_name,
    SOUND_NAME_MAX, split_tag, sub_names, SUB_SEP, sub_tag)
from soundboard.sounds.config import (  # noqa: F401
    AUDIO_EXTS, BASIC_TABS_OFF, clean_fade, clean_hotkey, clean_programs, clean_setting,
    clean_wait, Config, CONFIG_VERSION, field_names, fits_type, LIST_ROWS, LOAD_TRIES,
    MAX_COOLDOWN_S, MAX_DELAY_S, MAX_FADE_S, migrate_from_soundboard, MIGRATION_ERRORS, MIGRATIONS,
    MODES, NET_MODES, NEWER_CHOICES, PAD_COLORS, PAD_SORTS, PAD_VIEWS, PAD_WIDTH_RANGE, PRESS_MODE,
    PRIVACY_KEYS, ROUTES, scrub_old_configs, SETTING_RANGES, SIDE_KEYS, sorted_sounds, SoundMeta,
    TOR_BRIDGES,
    TOUR_TABS, UI_SCALES, VOLUME_MAX, _with_raw)
from soundboard.sounds.cachefiles import (  # noqa: F401
    CACHE_GRACE_S, cache_keep, cache_path, Cancelled, load_cached, _npy_header, prune_cache,
    render_cached, REVERSE_CHUNK, store_cached, unlink_cache)
from soundboard.sounds.decoding import (  # noqa: F401
    decode, decode_int16, _ffmpeg, _ffmpeg_source, FFMPEG_TIMEOUT, _ffmpeg_words, load_original,
    load_sound, MAX_SECONDS, MP3_QUALITY, original_frames, original_length, original_peaks,
    PEAK_CHUNK, PEAK_READS, _read, _sf_pieces, stored_ext, _stream, STREAM_S, write_stored)
from soundboard.sounds.files import (  # noqa: F401
    delete_file, discard, DOWNLOADS, drop_unfinished, duplicate, file_stem, fingerprint,
    _folder_of, import_file, loose_sounds, MY_SOUNDS, new_file, owns, RECORDINGS, recycle,
    save_clip, site_folder, _SITES, tidy_files, _undo_tidy, USE_RECYCLE_BIN)

log = logging.getLogger(__name__)

# dependencies first: a name one of them imports from another is found in its home first
_PARTS = (paths, levels, saving, tags, config, cachefiles, decoding, files)
_UNSET = object()


class _Library(types.ModuleType):
    """Setting a name here sets it where its code reads it too, as it did when it all
    lived in this module: tests point the folders at a temporary one
    (`library.SOUNDS_DIR = ...`) and swap functions out (`library._ffmpeg = ...`)."""

    def __setattr__(self, name: str, value) -> None:
        if not name.startswith("__"):
            old = self.__dict__.get(name, _UNSET)
            for part in _PARTS:
                got = part.__dict__.get(name, _UNSET)
                if got is not _UNSET and (got is old or old is _UNSET):
                    setattr(part, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Library
