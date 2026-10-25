"""The connection setting and the switches (Settings > Privacy & security), kept for
soundboard.online.net: the modes, the features and their names, the proxy address, the
setting's state and who is told when it changes."""
from __future__ import annotations

import ipaddress
import logging
import threading
import time
import urllib.parse
import weakref
from collections.abc import Callable
from dataclasses import dataclass

from soundboard.core import errors
from soundboard.i18n import _

log = logging.getLogger("soundboard.online.net")


DIRECT, PROXY, TOR = "direct", "proxy", "tor"
MODES = (DIRECT, PROXY, TOR)
CONNECT_TIMEOUT_S = 20.0
TOR_WAIT_S = 120.0                  # a connection waits this long for Tor to connect
TOR_HANDSHAKE_S = 60.0              # Tor opening a circuit to the site
TEST_HOST = ("api.github.com", 443)   # the Test button's target: the update check's host
PIPE_SEND_S = 300.0                # a relayed side that takes nothing for this long is cut
HEAD_LIMIT = 64 * 1024              # a request head bigger than this isn't FFmpeg / Qt
# connections whose request head hasn't come yet: more are closed at once (a local
# program opening hundreds and sending a byte now and then held a thread each, forever)
RELAY_WAITING_MAX = 64
# the relay's address for FFmpeg (radio) and, with their own feature's login, for child
# processes (pip, the live-voice helper)
ENV_KEYS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")
RELAY_MARK = "ONIONBOARD_RELAY_ENV"   # what _set_env put in ENV_KEYS (not the user's)
LOOPBACK_NAMES = ("localhost", "localhost.")
RELAY_HEADER = "X-Onion-Relay"   # on the relay's own refusals (see _Relay._refuse)
DIRECT_LOGIN = "direct-"   # relay login "direct-<feature>": not through the proxy / Tor
# features with nothing on this PC: the relay refuses them 127.x / localhost in every
# mode (every station comes from Radio Browser, so one leading here is a redirect)
NEVER_THIS_PC = frozenset({"radio"})
# features whose urlopen() may reach this PC / the home network: a custom voice server
# is one the user typed in, often on their own PC or LAN. For every other feature only
# a URL the caller names on this PC is (the "explicit loopback" API); a redirect or a
# LAN address is refused.
HOME_OK = frozenset({"voice_servers"})

# Everything that goes online, by the key its requests carry: its switch in Settings >
# Privacy & security (cfg.net_off lists the ones switched off). The names as written
# (English); feature_name() gives them in the language picked.
FEATURES = {
    "sounds_web": "Find and download sounds online",
    "sound_packs": "Download free sound packs",
    "sound_store": "Sound store",
    "ytdlp_update": "Update the downloader (yt-dlp)",
    "radio": "Radio",
    "app_update": "Check for and download Onion Board updates",
    "addons": "Get and update add-ons",
    "voices": "Download voices and speech models",
    "voice_servers": "Custom voice servers",
    "setup_downloads": "Install the virtual cable from the app",
    "tor_download": "Download Tor from the app",
    "ffmpeg_download": "Install FFmpeg from the app",
    "usage_stats": "Anonymous usage count",
    "twitch": "Twitch: channel points, chat and alerts",
}
# "sounds_web.<site>": the sites sounds come from, each with its own switch under it
SITES = {"youtube": "YouTube", "soundcloud": "SoundCloud", "myinstants": "Myinstants",
         "other": "Other pasted links"}
TEST = "connection_test"   # the Test button: no switch of its own, but not while Offline
WHERE = "Settings > Privacy & security"


# Functions, not tables, for the words: this module can be imported before the
# language is picked (app.main), so they're translated when they're used.
def feature_name(key: str) -> str:
    """A FEATURES key's name in the language picked."""
    return {
        "sounds_web": _("Find and download sounds online"),
        "sound_packs": _("Download free sound packs"),
        "sound_store": _("Community"),
        "ytdlp_update": _("Update the downloader (yt-dlp)"),
        "radio": _("Radio"),
        "app_update": _("Check for and download Onion Board updates"),
        "addons": _("Get and update add-ons"),
        "voices": _("Download voices and speech models"),
        "voice_servers": _("Custom voice servers"),
        "setup_downloads": _("Install the virtual cable from the app"),
        "tor_download": _("Download Tor from the app"),
        "ffmpeg_download": _("Install FFmpeg from the app"),
        "usage_stats": _("Anonymous usage count"),
        "twitch": _("Twitch: channel points, chat and alerts"),
    }.get(key, FEATURES.get(key, key))


def site_name(key: str) -> str:
    """A SITES key's name in the language picked (the sites' own names stay)."""
    return _("Other pasted links") if key == "other" else SITES.get(key, key)


def _off_sentence(main: str) -> str:
    """ "… is switched off in Settings > Privacy & security." for a FEATURES key."""
    return {
        "sounds_web": _("Finding and downloading sounds online is switched off in "
                        "Settings > Privacy & security."),
        "sound_packs": _("Downloading free sound packs is switched off in "
                         "Settings > Privacy & security."),
        "sound_store": _("The sound store is switched off in Settings > Privacy & security."),
        "ytdlp_update": _("Updating the downloader (yt-dlp) is switched off in "
                          "Settings > Privacy & security."),
        "radio": _("Radio is switched off in Settings > Privacy & security."),
        "app_update": _("Checking for Onion Board updates is switched off in "
                        "Settings > Privacy & security."),
        "addons": _("Getting and updating add-ons is switched off in "
                    "Settings > Privacy & security."),
        "voices": _("Downloading voices and speech models is switched off in "
                    "Settings > Privacy & security."),
        "voice_servers": _("Custom voice servers are switched off in "
                           "Settings > Privacy & security."),
        "setup_downloads": _("Installing the virtual cable from the app is switched off in "
                             "Settings > Privacy & security. Install VB-Cable yourself "
                             "from vb-audio.com."),
        "tor_download": _("Downloading Tor from the app is switched off in "
                          "Settings > Privacy & security."),
        "ffmpeg_download": _("Installing FFmpeg from the app is switched off in "
                             "Settings > Privacy & security."),
        "usage_stats": _("The anonymous usage count is switched off in "
                         "Settings > Privacy & security."),
        "twitch": _("Twitch is switched off in Settings > Privacy & security."),
    }[main]


class ProxyError(OSError):
    """A connection that couldn't be made the way the Connection setting says. The
    message is fit to show the user. An OSError so urllib and every caller's existing
    network-error handling catches it."""


class FeatureOff(ProxyError):
    """Refused because what asked is switched off in Settings > Privacy & security (or
    Offline mode is on, or the request didn't say what it's for). Nothing was looked
    up or sent. The message is fit to show the user."""


class LeadsHome(ProxyError):
    """Refused because a name going direct was looked up and leads into this PC or the
    home network. Nothing was sent. The message is fit to show the user."""


@dataclass(frozen=True)
class Proxy:
    kind: str          # "socks5" (names resolved by the proxy) | "http" (CONNECT)
    host: str
    port: int
    user: str = ""
    password: str = ""

    @property
    def where(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    def url(self) -> str:
        """socks5h://… / http://… with any login (for yt-dlp-style consumers)."""
        auth = ""
        if self.user or self.password:
            auth = (f"{urllib.parse.quote(self.user, safe='')}:"
                    f"{urllib.parse.quote(self.password, safe='')}@")
        return f"{'socks5h' if self.kind == 'socks5' else 'http'}://{auth}{self.where}"


def parse(text: str) -> Proxy:
    """A proxy address as typed in Settings. Raises ValueError with a message for the
    user."""
    t = (text or "").strip()
    if not t:
        raise ValueError(_("Type the proxy's address, e.g. socks5h://127.0.0.1:9050"))
    if "://" not in t:
        t = "socks5h://" + t
    u = urllib.parse.urlsplit(t)
    scheme = u.scheme.lower()
    kinds = {"socks5h": "socks5", "socks5": "socks5", "socks": "socks5", "http": "http"}
    if scheme not in kinds:
        raise ValueError(_("{scheme}:// proxies aren't supported: use socks5h:// or "
                           "http://", scheme=u.scheme))
    try:
        port = u.port
    except ValueError:
        port = None
    if not u.hostname or not port or (u.path not in ("", "/")) or u.query or u.fragment:
        raise ValueError(_("That isn't a proxy address: it should look like "
                           "socks5h://127.0.0.1:9050 or http://host:8080"))
    return Proxy(kinds[scheme], u.hostname, port,
                 urllib.parse.unquote(u.username or ""), urllib.parse.unquote(u.password or ""))


def is_loopback(host: str) -> bool:
    """This PC, by name or address, without looking anything up."""
    h = (host or "").strip().strip("[]").lower()
    if h in LOOPBACK_NAMES:   # not *.localhost: that would need a lookup to be sure
        return True
    try:
        ip = ipaddress.ip_address(h.split("%")[0])
    except ValueError:
        return False
    ip = getattr(ip, "ipv4_mapped", None) or ip
    return ip.is_loopback


# --------------------------------------------------------------------------- state

_lock = threading.RLock()
_mode = DIRECT
_proxy: Proxy | None = None
_bad = ""                       # why the proxy address can't be used ("" = it can)
_listeners: list = []           # weak callbacks, called after a change (UI thread)
_nams: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()   # Qt manager -> feature
_off: frozenset[str] = frozenset()   # cfg.net_off: the features switched off
_offline = False                     # cfg.net_offline: all of them
_generation = 0                      # bumped by every change of the Connection setting
_last_failure: tuple[float, str] = (0.0, "")
_tor_gate: Callable[[float], Proxy] | None = None   # soundboard.online.tor: waits, then its port


def mode() -> str:
    return _mode


def active() -> bool:
    """Is anything other than a direct connection in use?"""
    return _mode != DIRECT


def proxy() -> Proxy | None:
    return _proxy


def configure(new_mode: str, proxy_url: str = "") -> None:
    """Switch the whole app's connection. Applies at once: later requests use it, Qt's
    network managers are switched, open relayed connections are closed and listeners
    (the radio player) reconnect."""
    global _mode, _proxy, _bad, _last_failure, _generation
    if new_mode not in MODES:   # unknown (a newer version's mode): fail closed
        new_mode = PROXY
    p, bad = None, ""
    if new_mode == PROXY:
        try:
            p = parse(proxy_url)
        except ValueError as e:
            bad = str(e)
    with _lock:
        changed = (new_mode, p, bad) != (_mode, _proxy, _bad)
        _mode, _proxy, _bad = new_mode, p, bad
        netrelay._relay_start()     # in every mode: it's where FFmpeg / Qt are switched off
        netrelay._set_env()
    if not changed:
        return
    _generation += 1
    _last_failure = (0.0, "")
    log.info("connection: %s", describe(where=False))
    netrelay._relay_drop_all()
    netconnect._drop_live(lambda _feature: True)
    for nam in list(_nams.keys()):
        netrelay._apply_nam(nam)
    _notify()


def generation() -> int:
    """Changes whenever the Connection setting does (not the switches)."""
    return _generation


def configure_features(off=(), offline: bool = False) -> None:
    """Which features are switched off (keys of FEATURES, or "sounds_web.<site>"), and
    Offline mode. Applies at once: relayed connections of what's now off are closed
    and listeners are told (a playing station stops)."""
    global _off, _offline
    new_off = frozenset(str(k) for k in (off or ()) if isinstance(k, str))
    with _lock:
        changed = (new_off, bool(offline)) != (_off, _offline)
        _off, _offline = new_off, bool(offline)
        netrelay._relay_start()
        netrelay._set_env()
    if not changed:
        return
    log.info("switched off: %s", "everything (Offline mode)" if _offline
             else ", ".join(sorted(_off)) or "nothing")
    if netrelay._relay is not None:
        netrelay._relay.drop(lambda feature: not allowed(feature))
    netconnect._drop_live(lambda feature: not allowed(feature))
    for nam in list(_nams.keys()):
        netrelay._apply_nam(nam)
    _notify()


def configure_from(cfg) -> None:
    configure(getattr(cfg, "net_mode", DIRECT), getattr(cfg, "net_proxy", ""))
    configure_features(getattr(cfg, "net_off", ()) or (), getattr(cfg, "net_offline", False))


def _notify():
    for ref in list(_listeners):
        fn = ref()
        if fn is None:
            _listeners.remove(ref)
            continue
        try:
            fn()
        except RuntimeError as e:   # a Qt widget whose window has been closed
            if "already deleted" not in str(e):
                log.exception("connection listener failed")
            elif ref in _listeners:
                _listeners.remove(ref)
        except Exception:  # noqa: BLE001 - one listener mustn't stop the others
            log.exception("connection listener failed")


# --------------------------------------------------------------------------- switches

def known(feature) -> bool:
    """A key a request can carry: a feature, one of sounds_web's sites, or TEST."""
    if not isinstance(feature, str):
        return False
    if feature == TEST:
        return True
    main, dot, sub = feature.partition(".")
    if main not in FEATURES:
        return False
    return not dot or (main == "sounds_web" and sub in SITES)


def allowed(feature) -> bool:
    """May `feature` go online? Unknown keys (and None) never may; nothing may in
    Offline mode. A site ("sounds_web.youtube") needs its feature on too."""
    if _offline or not known(feature):
        return False
    if feature == TEST:
        return True
    return feature.partition(".")[0] not in _off and feature not in _off


def web_url(url: str) -> str:
    """`url` when it's an http(s) link with a host, else "". For any address a web page
    or a site's answer names (a thumbnail, a preview picture): only web links go through
    the relay, Tor and the switches."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return ""
    return url.strip()


def home_url(url: str) -> bool:
    """Does `url` point at this PC or the home network (loopback, a private, link-local
    or .lan / .local address)? Without a lookup: for addresses a web page names."""
    try:
        return netrelay._local_target(urllib.parse.urlsplit(url.strip()).hostname or "")
    except ValueError:
        return False


def offline() -> bool:
    return _offline


def switched_off() -> frozenset[str]:
    return _off


def any_allowed() -> bool:
    """Is any feature allowed to go online (else nothing needs to connect at all)?"""
    return any(allowed(f) for f in FEATURES)


def off_message(feature) -> str:
    """Why `feature` isn't allowed, as a sentence for the user."""
    if _offline:
        return _("Onion Board is in Offline mode (Settings > Privacy & security), so "
                 "nothing goes online.")
    if not known(feature):
        return _("Not connecting: this request didn't say which setting in "
                 "Settings > Privacy & security allows it.")
    main, __, sub = feature.partition(".")
    if main not in _off and sub in SITES:
        return _("Getting sounds from {site} is switched off in "
                 "Settings > Privacy & security.", site=site_name(sub))
    return _off_sentence(main)


def check(feature) -> None:
    """Raise FeatureOff (and remember why, for explain()) unless `feature` may go
    online."""
    if not allowed(feature):
        msg = off_message(feature)
        _failed(msg)
        raise FeatureOff(msg)


def set_tor_gate(fn: Callable[[float], Proxy] | None) -> None:
    """soundboard.online.tor's gate: given a timeout, starts Tor if needed, waits for it to
    connect and returns its SOCKS port as a Proxy, or raises ProxyError."""
    global _tor_gate
    _tor_gate = fn


def _tor_proxy() -> Proxy:
    if _tor_gate is None:
        raise _failed(_("Not connecting: Tor isn't available. Pick another Connection in "
                        "Settings > Connection."))
    try:
        return _tor_gate(TOR_WAIT_S)
    except ProxyError as e:
        raise _failed(errors.plain(e)) from None


def describe(where: bool = True) -> str:
    """For Settings: never includes a password. `where` False leaves out the proxy's
    address too (the log: SECURITY.md says it never names the proxy)."""
    if _mode == DIRECT:
        return _("direct")
    if _mode == TOR:
        return _("through Tor")
    if _proxy is None:
        return _("{mode}, but the address isn't usable ({error})", mode=_mode, error=_bad)
    kind = "SOCKS5" if _proxy.kind == "socks5" else "HTTP"
    if not where:
        return f"{_mode} via {kind}"
    return _("{mode} via {kind} {address}", mode=_mode, kind=kind, address=_proxy.where)


def on_change(fn: Callable[[], None]) -> None:
    """Call `fn` after every change of the setting (held weakly: a bound method stops
    being called once its object is gone)."""
    ref = weakref.WeakMethod(fn) if hasattr(fn, "__self__") else (lambda f=fn: f)
    _listeners.append(ref)


def last_failure(since: float = 0.0) -> str:
    """Why the proxy last failed a connection, if that was after `since`
    (time.monotonic()): Qt and FFmpeg only report "proxy error", the reason is kept
    here."""
    t, msg = _last_failure
    return msg if msg and t >= since else ""


def explain(msg: str, since: float) -> str:
    """`msg` (Qt's or FFmpeg's error), or why the proxy (or a switch) failed a
    connection made for the job that started at `since` (time.monotonic())."""
    return last_failure(since) or msg


def _failed(msg: str) -> ProxyError:
    global _last_failure
    _last_failure = (time.monotonic(), msg)
    return ProxyError(msg)


# imported last: they import this module
from soundboard.online import netconnect  # noqa: E402
from soundboard.online import netrelay  # noqa: E402
