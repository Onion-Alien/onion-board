"""Test helpers for soundboard.net: a minimal SOCKS5 server and an HTTP CONNECT proxy
on 127.0.0.1 that map made-up host names (*.test) to local test servers and log every
target they're asked for, and a guard that fails any connection or DNS lookup that
leaves this PC without going through them."""
from __future__ import annotations

import contextlib
import ipaddress
import select
import socket
import struct
import threading


class _Base:
    def __init__(self, hosts: dict[str, tuple[str, int]] | None = None):
        self.hosts = dict(hosts or {})   # "radio.test" -> ("127.0.0.1", port)
        self.asked: list[tuple[str, int]] = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(32)
        self.port = self.srv.getsockname()[1]
        self._conns: list[socket.socket] = []
        threading.Thread(target=self._accept, daemon=True).start()

    def map(self, name: str, port: int, host: str = "127.0.0.1"):
        self.hosts[name] = (host, port)

    def hosts_asked(self) -> set[str]:
        return {h for h, _ in self.asked}

    def close(self):
        self.srv.close()
        for c in self._conns:
            with contextlib.suppress(OSError):
                c.close()

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self._conns.append(c)
            threading.Thread(target=self._guarded, args=(c,), daemon=True).start()

    def _guarded(self, c):
        try:
            self._serve(c)
        except (OSError, ValueError):   # ValueError: select() on a socket stop() closed
            pass
        finally:
            with contextlib.suppress(OSError):
                c.close()

    def _target(self, host: str, port: int) -> socket.socket | None:
        self.asked.append((host, port))
        if host not in self.hosts:
            return None
        return socket.create_connection(self.hosts[host], timeout=5)

    @staticmethod
    def _pipe(a, b):
        a.settimeout(None)
        b.settimeout(None)
        pair = {a: b, b: a}
        try:
            while True:
                ready, _, _ = select.select(list(pair), [], [], 30)
                if not ready:
                    return
                for s in ready:
                    data = s.recv(65536)
                    if not data:
                        return
                    pair[s].sendall(data)
        finally:
            b.close()


def _exact(c, n):
    buf = b""
    while len(buf) < n:
        chunk = c.recv(n - len(buf))
        if not chunk:
            raise OSError("closed")
        buf += chunk
    return buf


class Socks5(_Base):
    """RFC 1928 CONNECT only; with `login` set, RFC 1929 user/password is required."""

    def __init__(self, hosts=None, login: tuple[str, str] | None = None):
        self.login = login
        super().__init__(hosts)

    def url(self) -> str:
        auth = f"{self.login[0]}:{self.login[1]}@" if self.login else ""
        return f"socks5h://{auth}127.0.0.1:{self.port}"

    def _serve(self, c):
        ver, n = _exact(c, 2)
        methods = _exact(c, n)
        want = 2 if self.login else 0
        if ver != 5 or want not in methods:
            c.sendall(b"\x05\xff")
            return
        c.sendall(bytes([5, want]))
        if self.login:
            _exact(c, 1)
            user = _exact(c, _exact(c, 1)[0]).decode()
            pw = _exact(c, _exact(c, 1)[0]).decode()
            ok = (user, pw) == self.login
            c.sendall(b"\x01" + (b"\x00" if ok else b"\x01"))
            if not ok:
                return
        _ver, cmd, _rsv, atyp = _exact(c, 4)
        if atyp == 1:
            host = str(ipaddress.ip_address(_exact(c, 4)))
        elif atyp == 4:
            host = str(ipaddress.ip_address(_exact(c, 16)))
        else:
            host = _exact(c, _exact(c, 1)[0]).decode("idna")
        port = struct.unpack(">H", _exact(c, 2))[0]
        up = self._target(host, port) if cmd == 1 else None
        if up is None:
            c.sendall(b"\x05\x04\x00\x01" + bytes(6))   # host unreachable
            return
        c.sendall(b"\x05\x00\x00\x01" + bytes(6))
        self._pipe(c, up)


class HttpConnect(_Base):
    """An HTTP proxy that only does CONNECT."""

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self, c):
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = c.recv(4096)
            if not chunk:
                return
            buf += chunk
        method, target, _v = buf.split(b"\r\n", 1)[0].decode().split(" ")
        host, _, port = target.rpartition(":")
        up = self._target(host.strip("[]"), int(port)) if method == "CONNECT" else None
        if up is None:
            c.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        c.sendall(b"HTTP/1.1 200 OK\r\n\r\n")
        self._pipe(c, up)


def _loopback(host) -> bool:
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return str(host).lower() == "localhost"


@contextlib.contextmanager
def no_leaks(monkeypatch):
    """Any connection from Python to somewhere other than this PC, and any DNS lookup
    of a name other than localhost, fails the test (the proxy and the test servers all
    live on 127.0.0.1). Qt / FFmpeg connect from C++, which this can't see: their tests
    use *.test names that only the fake proxy can resolve."""
    leaks: list[str] = []
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_gai = socket.getaddrinfo

    def check(addr):
        if isinstance(addr, tuple) and not _loopback(addr[0]):
            leaks.append(f"connect {addr!r}")
            raise AssertionError(f"leaked a direct connection to {addr!r}")

    def connect(self, addr):
        check(addr)
        return real_connect(self, addr)

    def connect_ex(self, addr):
        check(addr)
        return real_connect_ex(self, addr)

    def getaddrinfo(host, *a, **k):
        if host is not None and not _loopback(host):
            try:
                ipaddress.ip_address(host if isinstance(host, str) else host.decode())
            except ValueError:
                leaks.append(f"dns {host!r}")
                raise socket.gaierror(f"leak: looked up {host!r} on this PC") from None
        return real_gai(host, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    try:
        yield leaks
    finally:
        monkeypatch.setattr(socket.socket, "connect", real_connect)
        monkeypatch.setattr(socket.socket, "connect_ex", real_connect_ex)
        monkeypatch.setattr(socket, "getaddrinfo", real_gai)
