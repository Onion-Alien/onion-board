"""Every outgoing connection the app makes, in one place (Settings > Privacy >
Connection), so all of it can go through a proxy with nothing leaking around it.

Modes:
  "direct"  connect straight to each site, as before.
  "proxy"   everything goes through the proxy in cfg.net_proxy:
            socks5h://host:port (socks5:// and a bare host:port mean the same) or
            http://host:port, either with user:password@ if it needs one.
Phase 3 adds "tor": the app's own Tor, which plugs in here by being a SOCKS port
(configure(TOR, "socks5h://127.0.0.1:<its port>")); nothing else has to change.

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
"""
from __future__ import annotations

import base64
import http.client
import ipaddress
import logging
import os
import secrets
import select
import socket
import ssl
import struct
import threading
import time
import urllib.parse
import urllib.request
import weakref
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

DIRECT, PROXY = "direct", "proxy"
MODES = (DIRECT, PROXY)
CONNECT_TIMEOUT_S = 20.0
TEST_HOST = ("api.github.com", 443)   # the Test button's target: the update check's host
RELAY_USER = "onionboard"
HEAD_LIMIT = 64 * 1024              # a request head bigger than this isn't FFmpeg / Qt
# set while a proxy is on, for FFmpeg and child processes (pip, the live-voice helper)
ENV_KEYS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")
LOOPBACK_NAMES = ("localhost", "localhost.")


class ProxyError(OSError):
    """A connection that couldn't be made the way the Connection setting says. The
    message is fit to show the user. An OSError so urllib and every caller's existing
    network-error handling catches it."""


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
        raise ValueError("Type the proxy's address, e.g. socks5h://127.0.0.1:9050")
    if "://" not in t:
        t = "socks5h://" + t
    u = urllib.parse.urlsplit(t)
    scheme = u.scheme.lower()
    kinds = {"socks5h": "socks5", "socks5": "socks5", "socks": "socks5", "http": "http"}
    if scheme not in kinds:
        raise ValueError(f"{u.scheme}:// proxies aren't supported: use socks5h:// or http://")
    try:
        port = u.port
    except ValueError:
        port = None
    if not u.hostname or not port or (u.path not in ("", "/")) or u.query or u.fragment:
        raise ValueError("That isn't a proxy address: it should look like "
                         "socks5h://127.0.0.1:9050 or http://host:8080")
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
_env_saved: dict[str, str | None] | None = None
_listeners: list = []           # weak callbacks, called after a change (UI thread)
_nams: weakref.WeakSet = weakref.WeakSet()
_last_failure: tuple[float, str] = (0.0, "")


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
    global _mode, _proxy, _bad, _last_failure
    if new_mode not in MODES:   # unknown (a newer version's mode): fail closed
        new_mode = PROXY
    p, bad = None, ""
    if new_mode != DIRECT:
        try:
            p = parse(proxy_url)
        except ValueError as e:
            bad = str(e)
    with _lock:
        changed = (new_mode, p, bad) != (_mode, _proxy, _bad)
        _mode, _proxy, _bad = new_mode, p, bad
        if new_mode != DIRECT:
            _relay_start()
        _set_env()
    if not changed:
        return
    _last_failure = (0.0, "")
    log.info("connection: %s", describe())
    _relay_drop_all()
    for nam in list(_nams):
        _apply_nam(nam)
    for ref in list(_listeners):
        fn = ref()
        if fn is None:
            _listeners.remove(ref)
            continue
        try:
            fn()
        except Exception:  # noqa: BLE001 - one listener mustn't stop the others
            log.exception("connection listener failed")


def configure_from(cfg) -> None:
    configure(getattr(cfg, "net_mode", DIRECT), getattr(cfg, "net_proxy", ""))


def describe() -> str:
    """For the log and Settings: never includes a password."""
    if _mode == DIRECT:
        return "direct"
    if _proxy is None:
        return f"{_mode}, but the address isn't usable ({_bad})"
    return f"{_mode} via {'SOCKS5' if _proxy.kind == 'socks5' else 'HTTP'} {_proxy.where}"


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
    """`msg` (Qt's or FFmpeg's error), or why the proxy failed a connection made for
    the job that started at `since` (time.monotonic())."""
    return (last_failure(since) if active() else "") or msg


def _failed(msg: str) -> ProxyError:
    global _last_failure
    _last_failure = (time.monotonic(), msg)
    return ProxyError(msg)


# --------------------------------------------------------------------------- connect

def connect(host: str, port: int, timeout: float | None = CONNECT_TIMEOUT_S,
            via: Proxy | None = None) -> socket.socket:
    """A TCP connection to host:port the way the Connection setting says (or through
    `via`, for the Test button). Through a proxy the name is resolved by the proxy.
    Raises ProxyError (an OSError) with a readable message; never goes direct when a
    proxy is set."""
    host = str(host).strip("[]")
    if via is None:
        if not active() or is_loopback(host):
            return socket.create_connection((host, port), timeout)
        if _proxy is None:
            raise _failed(f"Not connecting: the proxy address in Settings > Privacy isn't "
                          f"usable ({_bad})")
        via = _proxy
    try:
        sock = socket.create_connection((via.host, via.port), timeout)
    except OSError as e:
        raise _failed(f"Couldn't reach the proxy at {via.where} ({_why(e)}). Nothing "
                      "was sent without it.") from None
    try:
        if via.kind == "socks5":
            _socks5(sock, via, host, port)
        else:
            _http_connect(sock, via, host, port)
    except ProxyError as e:
        sock.close()
        raise _failed(str(e)) from None
    except OSError as e:
        sock.close()
        raise _failed(f"The proxy at {via.where} stopped answering ({_why(e)})") from None
    return sock


def _why(e: OSError) -> str:
    if isinstance(e, TimeoutError | socket.timeout):
        return "timed out"
    return e.strerror or str(e) or type(e).__name__


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProxyError("the proxy closed the connection")
        buf += chunk
    return buf


SOCKS_REPLIES = {1: "the proxy failed", 2: "the proxy's rules don't allow it",
                 3: "the network is unreachable from the proxy",
                 4: "the site is unreachable from the proxy",
                 5: "the site refused the connection", 6: "it timed out",
                 7: "the proxy doesn't support that", 8: "the proxy doesn't support that"}


def _socks5(sock: socket.socket, p: Proxy, host: str, port: int):
    """RFC 1928 CONNECT, with the host name sent as is (the proxy resolves it), and
    RFC 1929 user/password when the address has one."""
    methods = b"\x00\x02" if (p.user or p.password) else b"\x00"
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    ver, method = _recv_exact(sock, 2)
    if ver != 5:
        raise ProxyError(f"{p.where} isn't a SOCKS5 proxy")
    if method == 2:
        u, pw = p.user.encode()[:255], p.password.encode()[:255]
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(pw)]) + pw)
        if _recv_exact(sock, 2)[1] != 0:
            raise ProxyError(f"the proxy at {p.where} turned down the user name / password")
    elif method != 0:
        raise ProxyError(f"the proxy at {p.where} wants a login"
                         + ("" if p.user else ": add user:password@ to its address"))
    try:
        ip = ipaddress.ip_address(host)
        addr = (b"\x01" + ip.packed) if ip.version == 4 else (b"\x04" + ip.packed)
    except ValueError:
        name = host.encode("idna")
        if not 0 < len(name) < 256:
            raise ProxyError(f"{host!r} isn't a host name") from None
        addr = b"\x03" + bytes([len(name)]) + name
    sock.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", port))
    ver, rep, _rsv, atyp = _recv_exact(sock, 4)
    if ver != 5:
        raise ProxyError(f"{p.where} isn't a SOCKS5 proxy")
    if rep != 0:
        raise ProxyError(f"Couldn't reach {host} through the proxy: "
                         f"{SOCKS_REPLIES.get(rep, f'error {rep}')}")
    if atyp == 1:
        _recv_exact(sock, 4 + 2)
    elif atyp == 4:
        _recv_exact(sock, 16 + 2)
    elif atyp == 3:
        _recv_exact(sock, _recv_exact(sock, 1)[0] + 2)
    else:
        raise ProxyError(f"{p.where} sent a SOCKS5 answer that makes no sense")


def _http_connect(sock: socket.socket, p: Proxy, host: str, port: int):
    target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    head = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
    if p.user or p.password:
        cred = base64.b64encode(f"{p.user}:{p.password}".encode()).decode()
        head += f"Proxy-Authorization: Basic {cred}\r\n"
    sock.sendall((head + "\r\n").encode("latin-1", "replace"))
    reply = b""
    while b"\r\n\r\n" not in reply:
        chunk = sock.recv(4096)
        if not chunk:
            raise ProxyError(f"the proxy at {p.where} closed the connection")
        reply += chunk
        if len(reply) > HEAD_LIMIT:
            raise ProxyError(f"{p.where} isn't an HTTP proxy")
    status = reply.split(b"\r\n", 1)[0].decode("latin-1", "replace").split(" ", 2)
    if len(status) < 2 or not status[0].startswith("HTTP/"):
        raise ProxyError(f"{p.where} isn't an HTTP proxy")
    if status[1] == "407":
        raise ProxyError(f"the proxy at {p.where} wants a login"
                         + ("" if p.user else ": add user:password@ to its address"))
    if not status[1].startswith("2"):
        raise ProxyError(f"Couldn't reach {host} through the proxy: it said "
                         f"{' '.join(status[1:]).strip()}")
    # a proxy sends nothing after its answer until the client speaks: nothing to keep


def test(proxy_url: str, target: tuple[str, int] = TEST_HOST,
         timeout: float = CONNECT_TIMEOUT_S) -> str:
    """The Test button: reach `target` through the typed proxy (not the saved one).
    The answer for the user; raises ValueError / ProxyError with one."""
    p = parse(proxy_url)
    t = time.monotonic()
    sock = connect(target[0], target[1], timeout, via=p)
    sock.close()
    return f"It works: the proxy reached {target[0]} in {time.monotonic() - t:.1f} s."


# --------------------------------------------------------------------------- urllib

def _timeout(t):
    return t if isinstance(t, int | float) else None   # socket._GLOBAL_DEFAULT_TIMEOUT


class _HTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = connect(self.host, self.port, _timeout(self.timeout))


class _HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        sock = connect(self.host, self.port, _timeout(self.timeout))
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


def _opener() -> urllib.request.OpenerDirector:
    """http / https only, connections made by connect(): no ftp:// or file:// handler,
    and environment proxies are ignored (a redirect can't step around the setting)."""
    o = urllib.request.OpenerDirector()
    for h in (urllib.request.UnknownHandler(), _HTTPHandler(),
              _HTTPSHandler(context=ssl.create_default_context()),
              urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPRedirectHandler(),
              urllib.request.HTTPErrorProcessor()):
        o.add_handler(h)
    return o


def urlopen(req, timeout: float = 30):
    """urllib.request.urlopen, the way the Connection setting says."""
    if not active():
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - callers pass http(s)
    return _opener().open(req, timeout=timeout)


# --------------------------------------------------------------------------- yt-dlp

def ytdlp_proxy() -> str | None:
    """yt-dlp's "proxy" option: None when direct (yt-dlp behaves as before), else the
    relay. The relay (not the SOCKS proxy itself) because yt-dlp hands its proxy to
    ffmpeg for some downloads, and ffmpeg can't speak SOCKS: it would go direct."""
    return relay_url() if active() else None


# --------------------------------------------------------------------------- Qt

def apply_qt(nam) -> None:
    """Put a QNetworkAccessManager on the setting, now and after every change."""
    _nams.add(nam)
    _apply_nam(nam)


def qt_proxy():
    from PySide6.QtNetwork import QNetworkProxy
    if not active():
        return QNetworkProxy(QNetworkProxy.DefaultProxy)
    r = _relay_start()
    p = QNetworkProxy(QNetworkProxy.HttpProxy, "127.0.0.1", r.port, RELAY_USER, r.secret)
    # names go to the relay unresolved; the relay hands them on to the proxy
    p.setCapabilities(p.capabilities() | QNetworkProxy.HostNameLookupCapability)
    return p


def _apply_nam(nam):
    try:
        nam.setProxy(qt_proxy())
        nam.clearConnectionCache()   # a kept-alive connection mustn't carry on the old way
    except RuntimeError:             # its C++ side is gone
        _nams.discard(nam)


# --------------------------------------------------------------------------- relay

class _Relay:
    """An HTTP proxy on 127.0.0.1 for the parts of the app that can't call connect()
    themselves (FFmpeg, Qt, yt-dlp and child processes). It takes CONNECT host:port
    (https) and absolute-URL GETs (http), both only with the per-launch secret, and
    makes the onward connection with connect()."""

    def __init__(self):
        self.secret = secrets.token_urlsafe(18)
        self._auth = base64.b64encode(f"{RELAY_USER}:{self.secret}".encode()).decode()
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(64)
        self.port = self.srv.getsockname()[1]
        self._open: set[socket.socket] = set()
        self._open_lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True, name="net-relay").start()

    def url(self) -> str:
        cred = f"{RELAY_USER}:{self.secret}"
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
        with self._open_lock:
            socks, self._open = list(self._open), set()
        for s in socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    def _track(self, *socks):
        with self._open_lock:
            self._open.update(socks)

    def _untrack(self, *socks):
        with self._open_lock:
            self._open.difference_update(socks)
        for s in socks:
            try:
                s.close()
            except OSError:
                pass

    def _serve(self, c: socket.socket):
        up = None
        self._track(c)
        try:
            c.settimeout(CONNECT_TIMEOUT_S)
            head, rest = self._read_head(c)
            if head is None:
                return
            lines = head.split("\r\n")
            parts = lines[0].split(" ")
            headers = [ln for ln in lines[1:] if ln]
            if not self._authorised(headers):
                c.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                          b"Proxy-Authenticate: Basic realm=\"onionboard\"\r\n"
                          b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                return
            if len(parts) != 3:
                return self._refuse(c, 400, "bad request")
            method, target, version = parts
            if method.upper() == "CONNECT":
                host, _, port = target.rpartition(":")
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
            if _local_target(host):
                # nothing the app fetches through the proxy lives on this PC or the
                # home network; a stream redirecting there is refused
                return self._refuse(c, 403, str(_failed(
                    f"Not connecting to {host}: it's on this PC or your home network")))
            try:
                up = connect(host, int(port))
            except OSError as e:
                return self._refuse(c, 502, str(e))
            self._track(up)
            if method.upper() == "CONNECT":
                c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            if first or rest:
                up.sendall(first + rest)
            self._pipe(c, up)
        except OSError:
            pass
        finally:
            self._untrack(*(s for s in (c, up) if s is not None))

    def _authorised(self, headers: list[str]) -> bool:
        for h in headers:
            name, _, value = h.partition(":")
            if name.strip().lower() == "proxy-authorization":
                kind, _, cred = value.strip().partition(" ")
                return kind.lower() == "basic" and secrets.compare_digest(
                    cred.strip().encode(), self._auth.encode())
        return False

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
            c.sendall(f"HTTP/1.1 {code} {reason}\r\nContent-Type: text/plain; charset=utf-8"
                      f"\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                      .encode() + body)
        except OSError:
            pass

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket):
        a.settimeout(None)
        b.settimeout(None)
        pair = {a: b, b: a}
        while True:
            ready, _, _ = select.select(list(pair), [], [], 60)
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                pair[s].sendall(data)


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


def relay_url() -> str:
    """The relay's address with its secret (never log it)."""
    return _relay_start().url()


def _set_env():
    """FFmpeg (radio) and child processes find the relay in http_proxy & co. while a
    proxy is on; the user's own values come back when it's off."""
    global _env_saved
    if active():
        if _env_saved is None:
            _env_saved = {k: os.environ.get(k) for k in ENV_KEYS}
        url = relay_url()
        os.environ["http_proxy"] = url
        os.environ["https_proxy"] = url
        os.environ["all_proxy"] = url
        os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
    elif _env_saved is not None:
        for k, v in _env_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _env_saved = None
