"""The relay for soundboard.online.net: a loopback HTTP proxy (per-launch secret, the
feature as its user name) for FFmpeg, yt-dlp, Qt's network managers and child
processes, and the environment those get."""
from __future__ import annotations

import base64
import collections
import ipaddress
import os
import secrets
import select
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from soundboard import without_app_blas
from soundboard.online import netlog
from soundboard.i18n import _
from soundboard.online import netconfig
from soundboard.online.netconfig import (CONNECT_TIMEOUT_S, DIRECT, DIRECT_LOGIN, ENV_KEYS,
    HEAD_LIMIT, LeadsHome, NEVER_THIS_PC, PIPE_SEND_S, RELAY_HEADER, _failed, _lock, _nams,
    allowed, is_loopback, off_message)
from soundboard.online import netconnect


_env_saved: dict[str, str | None] | None = None


# --------------------------------------------------------------------------- yt-dlp

def ytdlp_proxy(feature: str, direct: bool = False) -> str:
    """yt-dlp's "proxy" option for `feature` (sounds_web): the relay, in every mode.
    The relay (not the SOCKS proxy itself) because yt-dlp hands its proxy to ffmpeg
    for some downloads, and ffmpeg can't speak SOCKS: it would go direct. `direct`:
    the relay connects straight to the site (the user's "Try this one without Tor";
    the switch still holds)."""
    return relay_url(feature, direct)


# --------------------------------------------------------------------------- Qt

def apply_qt(nam, feature: str) -> None:
    """Put a QNetworkAccessManager on the setting, for `feature`, now and after every
    change: it always goes through the relay, which refuses it when that's off."""
    _nams[nam] = feature
    _apply_nam(nam)


def qt_proxy(feature: str):
    from PySide6.QtNetwork import QNetworkProxy
    r = _relay_start()
    p = QNetworkProxy(QNetworkProxy.ProxyType.HttpProxy, "127.0.0.1", r.port, feature, r.secret)
    # names go to the relay unresolved; the relay hands them on (to the proxy)
    p.setCapabilities(p.capabilities() | QNetworkProxy.Capability.HostNameLookupCapability)
    return p


def _apply_nam(nam):
    try:
        nam.setProxy(qt_proxy(_nams.get(nam, "")))
        nam.clearConnectionCache()   # a kept-alive connection mustn't carry on the old way
    except RuntimeError:             # its C++ side is gone
        _nams.pop(nam, None)


# --------------------------------------------------------------------------- relay

class _Relay:
    """An HTTP proxy on 127.0.0.1 for the parts of the app that can't call connect()
    themselves (FFmpeg, Qt, yt-dlp and child processes), running in every mode. It
    takes CONNECT host:port (https) and absolute-URL GETs (http), both only with the
    per-launch secret. The login's user name is the feature asking (radio,
    sounds_web…): one that's switched off is refused here, and the onward connection
    is made with connect() for it. DIRECT_LOGIN + the feature asks for that connection
    to go straight to the site (the user's "Try this one without Tor")."""

    def __init__(self):
        self.secret = secrets.token_urlsafe(18)
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(64)
        self.port = self.srv.getsockname()[1]
        self._open: dict[socket.socket, str] = {}   # socket -> the feature it's for
        self._open_lock = threading.Lock()
        # what was asked for lately: (feature, host, "ok" | "off" | "local" | "failed");
        # for the tests and the log, never with the secret
        self.seen: collections.deque = collections.deque(maxlen=500)
        threading.Thread(target=self._accept, daemon=True, name="net-relay").start()

    def url(self, feature: str, direct: bool = False) -> str:
        cred = f"{DIRECT_LOGIN if direct else ''}{feature}:{self.secret}"
        return f"http://{cred}@127.0.0.1:{self.port}"

    def _accept(self):
        while True:
            try:
                c, _addr = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True,
                             name="net-relay-conn").start()

    def drop_all(self):
        self.drop(lambda _feature: True)

    def drop(self, which: Callable[[str], bool]):
        """Close the open connections of the features `which` picks."""
        with self._open_lock:
            socks = [s for s, f in self._open.items() if which(f)]
            for s in socks:
                del self._open[s]
        for s in socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    def _track(self, feature: str, *socks):
        with self._open_lock:
            for s in socks:
                self._open[s] = feature

    def _untrack(self, *socks):
        with self._open_lock:
            for s in socks:
                self._open.pop(s, None)
        for s in socks:
            try:
                s.close()
            except OSError:
                pass

    def _serve(self, c: socket.socket):
        up = entry = None
        self._track("", c)
        try:
            c.settimeout(CONNECT_TIMEOUT_S)
            head, rest = self._read_head(c)
            if head is None:
                return
            lines = head.split("\r\n")
            parts = lines[0].split(" ")
            headers = [ln for ln in lines[1:] if ln]
            feature = self._authorised(headers)
            direct = feature is not None and feature.startswith(DIRECT_LOGIN)
            if direct and feature is not None:
                feature = feature[len(DIRECT_LOGIN):]
            if feature is None:
                c.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                          b"Proxy-Authenticate: Basic realm=\"onionboard\"\r\n"
                          b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                return
            self._track(feature, c)
            if len(parts) != 3:
                return self._refuse(c, 400, "bad request")
            method, target, version = parts
            if method.upper() == "CONNECT":
                host, __, port = target.rpartition(":")
                first = b""
            else:
                u = urllib.parse.urlsplit(target)
                if u.scheme.lower() != "http" or not u.hostname:
                    return self._refuse(c, 400, "only http:// URLs and CONNECT")
                host, port = u.hostname, str(u.port or 80)
                path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
                keep = [h for h in headers if h.split(":", 1)[0].strip().lower() not in
                        ("proxy-authorization", "proxy-connection", "connection",
                         "keep-alive")]
                first = (f"{method} {path} {version}\r\n" + "".join(f"{h}\r\n" for h in keep)
                         + "Connection: close\r\n\r\n").encode("latin-1") + rest
                rest = b""
            host = host.strip("[]")
            if not port.isdigit() or not host:
                return self._refuse(c, 400, "bad target")
            if not allowed(feature):
                # switched off: refused before anything is looked up or connected
                self.seen.append((feature, host, "off"))
                netlog.blocked(feature, host, int(port), off_message(feature), netlog.RELAY)
                return self._refuse(c, 403, str(_failed(off_message(feature))))
            if _local_target(host) and not (netconfig._mode == DIRECT and is_loopback(host)
                                                      and feature not in NEVER_THIS_PC):
                # nothing the app fetches through the relay lives on this PC or the
                # home network; a stream redirecting there is refused. (In Direct mode
                # this PC stays reachable, as it was before the relay ran in it, except
                # for the features in NEVER_THIS_PC.)
                self.seen.append((feature, host, "local"))
                why = _("Not connecting to {host}: it's on this PC or your home network",
                        host=host)
                netlog.blocked(feature, host, int(port), why, netlog.RELAY)
                return self._refuse(c, 403, str(_failed(why)))
            try:
                # going direct, the name is looked up on this PC anyway: one that leads
                # into this PC / the home network (a stream redirecting there) is
                # refused, and the connection goes to the address that was checked
                up, entry = netconnect._open(host, int(port), feature=feature, direct=direct,
                                             how=netlog.RELAY, away=True)
            except LeadsHome as e:
                self.seen.append((feature, host, "local"))
                return self._refuse(c, 403, str(_failed(str(e))))
            except OSError as e:
                self.seen.append((feature, host, "failed"))
                return self._refuse(c, 502, str(e))
            self.seen.append((feature, host, "ok"))
            self._track(feature, up)
            if method.upper() == "CONNECT":
                c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                entry.request(method, path)
            if first or rest:
                up.sendall(first + rest)
                entry.add_sent(len(first + rest))
            tunnel = method.upper() == "CONNECT"
            if tunnel and rest:   # the client didn't wait for the 200
                _sniff(entry, rest, from_site=False)
            self._pipe(c, up, entry, tunnel=tunnel and not rest)
        except (OSError, ValueError):   # ValueError: select() on a socket drop() closed
            pass
        finally:
            self._untrack(*(s for s in (c, up) if s is not None))
            if entry is not None:
                entry.closed()

    def _authorised(self, headers: list[str]) -> str | None:
        """The feature the login names, if it carries this launch's secret."""
        for h in headers:
            name, _, value = h.partition(":")
            if name.strip().lower() == "proxy-authorization":
                kind, _, cred = value.strip().partition(" ")
                if kind.lower() != "basic":
                    return None
                try:
                    user, _, pw = base64.b64decode(cred.strip(), validate=True).decode(
                        "utf-8").partition(":")
                except (ValueError, UnicodeDecodeError):
                    return None
                if not secrets.compare_digest(pw.encode(), self.secret.encode()):
                    return None
                return user
        return None

    @staticmethod
    def _read_head(c: socket.socket) -> tuple[str | None, bytes]:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = c.recv(4096)
            if not chunk or len(buf) > HEAD_LIMIT:
                return None, b""
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        return head.decode("latin-1"), rest

    @staticmethod
    def _refuse(c: socket.socket, code: int, why: str):
        reason = {400: "Bad Request", 403: "Forbidden", 502: "Bad Gateway"}[code]
        body = why.encode("utf-8", "replace")[:500]
        try:
            # RELAY_HEADER: the relay's own answer, not the site's (a 502 here is "couldn't
            # connect", where a site's 502 is the site being down: radio tells them apart)
            c.sendall(f"HTTP/1.1 {code} {reason}\r\nContent-Type: text/plain; charset=utf-8"
                      f"\r\n{RELAY_HEADER}: {code}"
                      f"\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                      .encode() + body)
        except OSError:
            pass

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket, entry: netlog.Entry | None = None,
              tunnel: bool = False):
        """Carry bytes both ways between the client `a` and the site `b`, counting them
        into `entry`. What a tunnel carries is the client's own: the relay only tells
        whether it's encrypted (TLS) and, for plain HTTP, reads the status line."""
        # recv only runs once select says there's data; the timeout is for sendall: a
        # side that stopped reading (a client gone without closing) held this thread and
        # the site's connection for good
        a.settimeout(PIPE_SEND_S)
        b.settimeout(PIPE_SEND_S)
        pair = {a: b, b: a}
        first = {a: tunnel, b: True}   # the first bytes each way not yet looked at
        while True:
            ready, _, _ = select.select(list(pair), [], [], 60)
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                pair[s].sendall(data)
                if entry is None:
                    continue
                (entry.add_sent if s is a else entry.add_received)(len(data))
                if first[s]:
                    first[s] = False
                    _sniff(entry, data, from_site=s is b)


def _sniff(entry: netlog.Entry, data: bytes, from_site: bool) -> None:
    """Note what the first bytes of a relayed connection are: TLS (the app can't read
    what's inside), a request line through a tunnel, or the site's HTTP status."""
    if data[:1] == b"\x16":
        if not from_site:
            entry.set_tls("TLS, encrypted end to end (the relay can't read it)")
        return
    line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = line.split(" ", 2)
    if len(parts) < 2:
        return
    if from_site and parts[0].startswith(("HTTP/", "ICY")):
        entry.response(parts[1], parts[2] if len(parts) > 2 else "")
    elif not from_site and parts[-1].startswith("HTTP/") and len(parts) == 3:
        entry.request(parts[0], parts[1])


def _local_target(host: str) -> bool:
    """An address (not a name: names are the proxy's to resolve) on this PC or the home
    network."""
    if is_loopback(host) or host.lower().endswith((".localhost", ".local", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    ip = getattr(ip, "ipv4_mapped", None) or ip
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified
            or ip.is_multicast or ip.is_reserved)


_relay: _Relay | None = None


def _relay_start() -> _Relay:
    global _relay
    with _lock:
        if _relay is None:
            _relay = _Relay()
        return _relay


def _relay_drop_all():
    if _relay is not None:
        _relay.drop_all()


def relay_url(feature: str, direct: bool = False) -> str:
    """The relay's address with `feature`'s login (never log it: it has the secret)."""
    return _relay_start().url(feature, direct)


def relay_seen() -> list[tuple[str, str, str]]:
    """What the relay was asked for lately: (feature, host, "ok" | "off" | "local" |
    "failed"). For tests and troubleshooting."""
    return list(_relay.seen) if _relay is not None else []


def _set_env():
    """FFmpeg finds the relay in http_proxy & co., with the radio's login: the only
    FFmpeg in this process is the radio player. The user's own values are kept for
    own_env().

    No no_proxy: FFmpeg would connect straight to anything it lists, so a station
    redirecting to 127.0.0.1 / localhost would step around the relay (and its switch
    and home-network checks). Nothing else in this process reads these variables:
    urlopen() ignores them, Qt is given the relay itself (apply_qt), and the child
    processes that go online get child_env(), which keeps this PC direct."""
    global _env_saved
    if _env_saved is None:
        _env_saved = {k: os.environ.get(k) for k in ENV_KEYS}
    url = relay_url("radio")
    os.environ["http_proxy"] = url
    os.environ["https_proxy"] = url
    os.environ["all_proxy"] = url
    os.environ.pop("no_proxy", None)


def _without_proxy_vars(env: dict[str, str]) -> dict[str, str]:
    keys = {k.upper() for k in ENV_KEYS}
    return {k: v for k, v in env.items() if k.upper() not in keys}


def own_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """`env` (this process's by default) with the user's own proxy variables instead
    of the relay's: for a program that outlives the app (the update installer)."""
    out = _without_proxy_vars(dict(os.environ if env is None else env))
    for k, v in (_env_saved or {}).items():
        if v is not None:
            out[k] = v
    return out


def child_env(feature: str, env: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for a child process that goes online for `feature` (pip for
    add-ons, the live-voice helper for voices): the relay with that feature's login,
    so the Connection setting and its switch hold. Switched off, the relay refuses it,
    and HF_HUB_OFFLINE=1 tells Hugging Face downloads (the speech model) not to try.
    The app's own OPENBLAS_NUM_THREADS is left out (soundboard/__init__.py)."""
    out = _without_proxy_vars(dict(os.environ if env is None else env))
    without_app_blas(out)    # its own numpy / torch: not the app's thread cap
    url = relay_url(feature)
    out.update(http_proxy=url, https_proxy=url, all_proxy=url,
               no_proxy="localhost,127.0.0.1,::1")
    if not allowed(feature):
        out["HF_HUB_OFFLINE"] = "1"
    return out
