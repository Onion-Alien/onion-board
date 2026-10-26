"""Connections for soundboard.online.net: connect() straight to a site, through a SOCKS5 /
HTTP proxy or through Tor, the Test button, and the open sockets a change cuts off."""
from __future__ import annotations

import base64
import ipaddress
import socket
import struct
import threading
import time
import weakref
from collections.abc import Callable

from soundboard.core import errors
from soundboard.online import netlog
from soundboard.i18n import _
from soundboard.online import netconfig
from soundboard.online.netconfig import (CONNECT_TIMEOUT_S, FeatureOff, HEAD_LIMIT, LeadsHome,
    Proxy, ProxyError, TEST, TEST_HOST, TOR, TOR_HANDSHAKE_S, _failed, _tor_proxy, active, check,
    is_loopback, known, parse)


# urlopen()'s open sockets to sites -> the feature: a change of the setting (or a
# switch) cuts them off, as it does the relay's
_live: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_live_lock = threading.Lock()


# --------------------------------------------------------------------------- connect

def connect(host: str, port: int, timeout: float | None = CONNECT_TIMEOUT_S,
            via: Proxy | None = None, feature: str | None = None,
            direct: bool = False) -> socket.socket:
    """A TCP connection to host:port for `feature` (a key of FEATURES, or TEST), the
    way the Connection setting says (or through `via`, for the Test button). Through a
    proxy the name is resolved by the proxy. Raises FeatureOff when the feature is
    switched off (or missing), before any lookup; this PC (loopback) is always
    allowed. Raises ProxyError (an OSError) with a readable message; never goes
    direct when a proxy or Tor is set, unless `direct` (the user's "Try this one
    without Tor" click; the switch is checked all the same)."""
    return _open(host, port, timeout, via, feature, direct)[0]


def _open(host: str, port: int, timeout: float | None = CONNECT_TIMEOUT_S,
          via: Proxy | None = None, feature: str | None = None, direct: bool = False,
          how: str = netlog.APP, away: bool = False) -> tuple[socket.socket, netlog.Entry]:
    """connect(), and its entry in the activity list (netlog) for the caller to add
    to (bytes, requests) and close. `away`: going direct, a name that leads into this
    PC / the home network is refused with LeadsHome (see _connect_away)."""
    host = str(host).strip("[]")
    entry = netlog.begin(feature, host, port, how)
    try:
        if not known(feature) or not (via is None and is_loopback(host)):
            check(feature)   # before the Tor gate: a switched-off feature never starts Tor
    except FeatureOff as e:
        entry.refused(str(e))
        raise
    except BaseException as e:   # never leave it "Connecting…" for good
        entry.failed(str(e) or type(e).__name__)
        raise
    try:
        sock, route = _route(host, port, timeout, via, direct, away)
    except LeadsHome as e:
        entry.route = _route_name(via, direct, host)
        entry.refused(str(e))
        raise
    except BaseException as e:   # OSError, or e.g. a host name IDNA can't encode
        entry.route = _route_name(via, direct, host)
        entry.failed(str(e) if isinstance(e, ProxyError)
                     else _why(e) if isinstance(e, OSError) else str(e) or type(e).__name__)
        raise
    entry.connected(route)
    return sock, entry


def _route_name(via: Proxy | None, direct: bool, host: str) -> str:
    """How a connection to `host` goes, in words (never with a login)."""
    if via is None:
        if is_loopback(host):
            return "this PC"
        if direct and active():
            return "direct (Try this one without Tor)"
        if not active():
            return "direct"
        if netconfig._mode == TOR:
            return "Tor"
        via = netconfig._proxy
        if via is None:
            return "proxy (address not usable)"
    return f"{'SOCKS5' if via.kind == 'socks5' else 'HTTP'} proxy {via.where}"


def _route(host: str, port: int, timeout: float | None, via: Proxy | None,
           direct: bool, away: bool = False) -> tuple[socket.socket, str]:
    if via is None:
        if direct or not active() or is_loopback(host):
            if away and not is_loopback(host):
                return _connect_away(host, port, timeout), _route_name(via, direct, host)
            return (socket.create_connection((host, port), timeout),
                    _route_name(via, direct, host))
        if netconfig._mode == TOR:
            # a Tor circuit can take longer to open than a proxy's connection
            return _via(_tor_proxy(), host, port, timeout, "Tor",
                        handshake=max(timeout or 0, TOR_HANDSHAKE_S)), "Tor"
        if netconfig._proxy is None:
            raise _failed(_("Not connecting: the proxy address in Settings > Connection "
                            "isn't usable ({error})", error=netconfig._bad))
        via = netconfig._proxy
    return _via(via, host, port, timeout), _route_name(via, direct, host)


def _connect_away(host: str, port: int, timeout: float | None) -> socket.socket:
    """A direct connection to `host` that never lands on this PC or the home network:
    the name is looked up once, refused (LeadsHome) if any address it gives is local,
    and the connection goes to those checked addresses. Never to a second lookup of
    the name, which could answer differently (DNS rebinding: a public address for the
    check, then the router's). The name itself stays in what the client sends (the
    Host header, TLS SNI): those bytes pass through unchanged."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM,
                               proto=socket.IPPROTO_TCP)
    ips = [str(info[4][0]) for info in infos]
    if any(netrelay._local_target(ip) for ip in ips):
        raise LeadsHome(_("Not connecting to {host}: it leads to this PC or your home "
                          "network", host=host))
    error: OSError = OSError(f"no address for {host}")
    for ip in dict.fromkeys(ips):   # in the resolver's order, each once
        try:
            return socket.create_connection((ip, port), timeout)
        except OSError as e:
            error = e
    raise error


def _via(via: Proxy, host: str, port: int, timeout: float | None,
         name: str = "", handshake: float | None = None) -> socket.socket:
    try:
        sock = socket.create_connection((via.host, via.port), handshake or timeout)
    except OSError as e:
        raise _failed(_("Couldn't reach {name} ({error}). Nothing was sent without it.",
                        name=name, error=_why(e)) if name else
                      _("Couldn't reach the proxy at {address} ({error}). Nothing was sent "
                        "without it.", address=via.where, error=_why(e))) from None
    try:
        if via.kind == "socks5":
            _socks5(sock, via, host, port)
        else:
            _http_connect(sock, via, host, port)
    except ProxyError as e:
        sock.close()
        raise _failed(errors.plain(e)) from None
    except OSError as e:
        sock.close()
        raise _failed(_("{name} stopped answering ({error})", name=name, error=_why(e))
                      if name else
                      _("The proxy at {address} stopped answering ({error})",
                        address=via.where, error=_why(e))) from None
    sock.settimeout(timeout)
    return sock


def _why(e: OSError) -> str:
    if isinstance(e, TimeoutError | socket.timeout):
        return _("timed out")
    return e.strerror or str(e) or type(e).__name__


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProxyError(_("the proxy closed the connection"))
        buf += chunk
    return buf


def _socks_reply(code: int) -> str:
    """A SOCKS5 reply code in words."""
    if code in (7, 8):
        return _("the proxy doesn't support that")
    return {1: _("the proxy failed"), 2: _("the proxy's rules don't allow it"),
            3: _("the network is unreachable from the proxy"),
            4: _("the site is unreachable from the proxy"),
            5: _("the site refused the connection"), 6: _("it timed out")}.get(
        code, _("error {code}", code=code))


def _socks5(sock: socket.socket, p: Proxy, host: str, port: int):
    """RFC 1928 CONNECT, with the host name sent as is (the proxy resolves it), and
    RFC 1929 user/password when the address has one."""
    methods = b"\x00\x02" if (p.user or p.password) else b"\x00"
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    ver, method = _recv_exact(sock, 2)
    if ver != 5:
        raise ProxyError(_("{address} isn't a SOCKS5 proxy", address=p.where))
    if method == 2:
        u, pw = p.user.encode()[:255], p.password.encode()[:255]
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(pw)]) + pw)
        if _recv_exact(sock, 2)[1] != 0:
            raise ProxyError(_("the proxy at {address} turned down the user name / "
                               "password", address=p.where))
    elif method != 0:
        raise ProxyError(_("the proxy at {address} wants a login", address=p.where)
                         if p.user else
                         _("the proxy at {address} wants a login: add user:password@ to "
                           "its address", address=p.where))
    try:
        ip = ipaddress.ip_address(host)
        addr = (b"\x01" + ip.packed) if ip.version == 4 else (b"\x04" + ip.packed)
    except ValueError:
        name = host.encode("idna")
        if not 0 < len(name) < 256:
            raise ProxyError(_("{host} isn't a host name", host=repr(host))) from None
        addr = b"\x03" + bytes([len(name)]) + name
    sock.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", port))
    ver, rep, _rsv, atyp = _recv_exact(sock, 4)
    if ver != 5:
        raise ProxyError(_("{address} isn't a SOCKS5 proxy", address=p.where))
    if rep != 0:
        raise ProxyError(_("Couldn't reach {host} through the proxy: {error}",
                           host=host, error=_socks_reply(rep)))
    if atyp == 1:
        _recv_exact(sock, 4 + 2)
    elif atyp == 4:
        _recv_exact(sock, 16 + 2)
    elif atyp == 3:
        _recv_exact(sock, _recv_exact(sock, 1)[0] + 2)
    else:
        raise ProxyError(_("{address} sent a SOCKS5 answer that makes no sense",
                           address=p.where))


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
            raise ProxyError(_("the proxy at {address} closed the connection",
                               address=p.where))
        reply += chunk
        if len(reply) > HEAD_LIMIT:
            raise ProxyError(_("{address} isn't an HTTP proxy", address=p.where))
    status = reply.split(b"\r\n", 1)[0].decode("latin-1", "replace").split(" ", 2)
    if len(status) < 2 or not status[0].startswith("HTTP/"):
        raise ProxyError(_("{address} isn't an HTTP proxy", address=p.where))
    if status[1] == "407":
        raise ProxyError(_("the proxy at {address} wants a login", address=p.where)
                         if p.user else
                         _("the proxy at {address} wants a login: add user:password@ to "
                           "its address", address=p.where))
    if not status[1].startswith("2"):
        raise ProxyError(_("Couldn't reach {host} through the proxy: it said {answer}",
                           host=host, answer=" ".join(status[1:]).strip()))
    # a proxy sends nothing after its answer until the client speaks: nothing to keep


def test(proxy_url: str, target: tuple[str, int] = TEST_HOST,
         timeout: float = CONNECT_TIMEOUT_S) -> str:
    """The Test button: reach `target` through the typed proxy (not the saved one).
    The answer for the user; raises ValueError / ProxyError with one."""
    p = parse(proxy_url)
    t = time.monotonic()
    sock, entry = _open(target[0], target[1], timeout, via=p, feature=TEST)
    sock.close()
    entry.closed()
    return _("It works: the proxy reached {host} in {seconds} s.", host=target[0],
             seconds=f"{time.monotonic() - t:.1f}")


# --------------------------------------------------------------------------- urllib

def _timeout(t):
    return t if isinstance(t, int | float) else None   # socket._GLOBAL_DEFAULT_TIMEOUT


def _track_live(sock: socket.socket, feature: str) -> None:
    with _live_lock:
        _live[sock] = feature


def _drop_live(which: Callable[[str], bool]) -> None:
    """Cut off urlopen()'s open connections of the features `which` picks: a read
    waiting on one returns, and its response raises ProxyError (see _Counted)."""
    with _live_lock:
        socks = [s for s, f in list(_live.items()) if which(f)]
    for s in socks:
        try:
            socket.socket.shutdown(s, socket.SHUT_RDWR)   # the TCP one, under any TLS
        except (OSError, ValueError):   # closed already
            pass


# imported last: they import this module
from soundboard.online import netrelay  # noqa: E402
