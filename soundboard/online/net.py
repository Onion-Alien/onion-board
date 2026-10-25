"""Every outgoing connection the app makes, in one place (Settings >
Connection), so all of it can go through a proxy with nothing leaking around it.

Modes:
  "direct"  connect straight to each site, as before.
  "proxy"   everything goes through the proxy in cfg.net_proxy:
            socks5h://host:port (socks5:// and a bare host:port mean the same) or
            http://host:port, either with user:password@ if it needs one.
  "tor"     everything goes through the app's own Tor (soundboard.online.tor), a SOCKS port
            on 127.0.0.1 that's only there once Tor has connected. A connection
            made before that waits for it (up to TOR_WAIT_S), then fails: it never
            goes direct. soundboard.online.tor plugs itself in with set_tor_gate().

How each kind of traffic gets here:
  * urllib (updates, yt-dlp updater, Myinstants, translation models, add-ons, custom
    voices): urlopen() below, whose connections are made by connect().
  * Qt Multimedia's FFmpeg (radio streams), yt-dlp (and the ffmpeg it may start), Qt's
    network managers (Radio Browser, thumbnails) and child processes (pip, the live
    voice helper): a small HTTP proxy on 127.0.0.1 (the relay) that needs a per-launch
    secret and makes its onward connections with connect(). FFmpeg reads its address
    from the http_proxy environment variable, so a stream's redirects, HLS playlists
    and segments and ICY titles all go through it too.
connect() hands host names to the proxy unresolved (no DNS lookup on this PC), and
fails with a readable ProxyError rather than ever falling back to a direct
connection. Loopback (127.0.0.1, ::1, localhost) always stays direct.

Switches (Settings > Privacy & security): every feature that goes online (FEATURES)
can be switched off, and Offline mode switches them all off. Every request names its
feature (urlopen(feature=…), connect(feature=…), the relay's user name), and one that
doesn't, or names one that's off, is refused with FeatureOff before anything is
looked up or connected, in every mode. That's why the relay runs in Direct mode too:
FFmpeg and Qt connect from C++, and the relay is the only place they can be stopped.

Every connection made here, and every one refused, is listed in soundboard.online.netlog
(Settings > Connection > Network activity), in memory only.

The code lives in the modules beside this one; this one gathers their names, so
`net.X` and `from soundboard.online.net import X` keep working:

- netconfig: the modes, the switches and their names, the proxy address, the setting's state
- netconnect: connect() (direct, SOCKS5 / HTTP proxy, Tor), the Test button
- nethttp: urlopen(), counted responses, TLS, redirects, capped reads
- netrelay: the loopback relay for FFmpeg, yt-dlp, Qt and child processes, and their env
"""
from __future__ import annotations

import sys
import types
# the modules the code used when it was all here, still reached through net by tests
import base64  # noqa: F401
import collections  # noqa: F401
import hashlib  # noqa: F401
import http.client  # noqa: F401
import ipaddress  # noqa: F401
import logging  # noqa: F401
import os  # noqa: F401
import secrets  # noqa: F401
import select  # noqa: F401
import socket  # noqa: F401
import ssl  # noqa: F401
import struct  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import urllib.error  # noqa: F401
import urllib.parse  # noqa: F401
import urllib.request  # noqa: F401
import weakref  # noqa: F401
from collections.abc import Callable  # noqa: F401
from dataclasses import dataclass  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401
from soundboard.core import errors  # noqa: F401
from soundboard import without_app_blas  # noqa: F401
from soundboard.online import netlog  # noqa: F401
from soundboard.i18n import _  # noqa: F401
from soundboard.online import netconfig, netconnect, nethttp, netrelay
from soundboard.online.netconfig import (  # noqa: F401
    active, allowed, any_allowed, check, configure, configure_features, configure_from,
    CONNECT_TIMEOUT_S, describe, DIRECT, DIRECT_LOGIN, ENV_KEYS, explain, _failed, feature_name,
    FeatureOff, FEATURES, generation, HEAD_LIMIT, HOME_OK, home_url, is_loopback, known,
    last_failure, LeadsHome, _listeners, _lock, LOOPBACK_NAMES, mode, MODES, _nams, NEVER_THIS_PC,
    _notify, off_message, _off_sentence, offline, on_change, parse, PIPE_SEND_S, PROXY, Proxy,
    proxy, ProxyError, RELAY_HEADER, RELAY_MARK, RELAY_WAITING_MAX, set_tor_gate, site_name,
    SITES, switched_off, TEST, TEST_HOST,
    TOR, TOR_HANDSHAKE_S, _tor_proxy, TOR_WAIT_S, web_url, WHERE)
from soundboard.online.netconnect import (  # noqa: F401
    connect, _connect_away, _drop_live, _http_connect, _live, _live_lock, _open, _recv_exact,
    _route, _route_name, _socks5, _socks_reply, test, _timeout, _track_live, _via, _why)
from soundboard.online.nethttp import (  # noqa: F401
    content_length, _Counted, _HTTPConnection, _HTTPHandler, _HTTPSConnection, _HTTPSHandler,
    _Logged, _LoggedBase, _opener, read_capped, _RedirectHandler, _refuse_home, _Response,
    _tls_context, TLS_KEEP_S, _tls_lock, _tls_text, TooBig, urlopen)
from soundboard.online.netrelay import (  # noqa: F401
    _apply_nam, apply_qt, child_env, _local_target, own_env, qt_proxy, _Relay, _relay_drop_all,
    relay_seen, _relay_start, relay_url, _set_env, _sniff, _without_proxy_vars, ytdlp_proxy)

log = logging.getLogger(__name__)

# dependencies first: a name one of them imports from another is found in its home first
_PARTS = (netconfig, netconnect, nethttp, netrelay)
# what their code sets again (`global`): never copied here, always read where it lives
_LIVE = {"_bad": netconfig, "_env_saved": netrelay, "_generation": netconfig,
    "_last_failure": netconfig, "_mode": netconfig, "_off": netconfig, "_offline": netconfig,
    "_proxy": netconfig, "_relay": netrelay, "_tls": nethttp, "_tor_gate": netconfig}
_UNSET = object()


class _Net(types.ModuleType):
    """Setting a name here sets it where its code reads it too, as it did when it all
    lived in this module (tests swap functions and constants out:
    `net.urlopen = ...; net.NEVER_THIS_PC = frozenset()`), and the state its code changes is read
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


sys.modules[__name__].__class__ = _Net
