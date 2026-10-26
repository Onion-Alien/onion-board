"""urllib for soundboard.online.net: urlopen() over connect(), each response counted in
the activity list, TLS, redirects that may not lead home, and capped reads."""
from __future__ import annotations

import hashlib
import http.client
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import TYPE_CHECKING

from soundboard.core import errors
from soundboard.online import netlog
from soundboard.i18n import _
from soundboard.online import netconfig
from soundboard.online.netconfig import (FeatureOff, HOME_OK, ProxyError, _failed, allowed, check,
    is_loopback, known, off_message)
from soundboard.online.netconnect import _open, _timeout, _track_live


class _Counted:
    """A response's file, counting what's read into its activity entry. `stale` says
    why the connection mustn't carry on (the setting changed, or its switch went off)
    and makes every read raise ProxyError from then on."""

    def __init__(self, fp, entry: netlog.Entry, stale: Callable[[], str] | None = None):
        self._fp, self._entry, self._stale = fp, entry, stale

    def _guard(self):
        why = self._stale() if self._stale is not None else ""
        if why:
            raise _failed(why)

    def _do(self, fn, *a):
        self._guard()
        try:
            data = fn(*a)
        except (OSError, ValueError):   # e.g. cut off by _drop_live
            self._guard()
            raise
        self._guard()
        return data

    def _count(self, data):
        if data:
            self._entry.add_received(len(data))
        return data

    def read(self, *a):
        return self._count(self._do(self._fp.read, *a))

    def read1(self, *a):
        return self._count(self._do(self._fp.read1, *a))

    def readline(self, *a):
        return self._count(self._do(self._fp.readline, *a))

    def readinto(self, b):
        n = self._do(self._fp.readinto, b)
        if n:
            self._entry.add_received(n)
        return n

    def close(self):
        self._fp.close()
        self._entry.closed()

    def __getattr__(self, name):
        return getattr(self._fp, name)


class _Response(http.client.HTTPResponse):
    def __init__(self, sock, *a, entry: netlog.Entry | None = None,
                 stale: Callable[[], str] | None = None, **kw):
        super().__init__(sock, *a, **kw)
        if entry is not None:   # (a file-like wrapper, as http.client reads it)
            self.fp = _Counted(self.fp, entry, stale)   # pyright: ignore[reportAttributeAccessIssue]


# _Logged is mixed into HTTP(S)Connection: type checked as one
_LoggedBase = http.client.HTTPConnection if TYPE_CHECKING else object


class _Logged(_LoggedBase):
    """An http.client connection that adds its requests, answers and bytes to its
    activity entry (netlog)."""
    entry: netlog.Entry | None = None
    answered = False   # a response has the entry now: its close() closes it
    asking = ("", "")  # the request line: put before the (lazy) connect
    gen = -1           # the Connection setting's generation() it connected under
    feature = ""

    def __init__(self, *a, feature: str = "", direct: bool = False, **kw):
        super().__init__(*a, **kw)
        self.feature, self.direct = feature, direct

    def _dial(self):
        """connect()'s socket and activity entry, the way the Connection setting says."""
        self.gen = netconfig._generation
        return _open(self.host, self.port, _timeout(self.timeout), feature=self.feature,
                     direct=self.direct, away=self.feature not in HOME_OK)

    def _stale(self) -> str:
        """Why this connection mustn't carry on, or "": its switch went off, or the
        Connection setting changed since it connected (it goes the old way). A
        connection on this PC isn't routed, so it's never stale."""
        if is_loopback(self.host):
            return ""
        if not allowed(self.feature):
            return off_message(self.feature)
        if self.gen != netconfig._generation:
            return _("Stopped: the connection setting changed while this was "
                     "downloading, so it didn't carry on the old way. Try again.")
        return ""

    def putrequest(self, method, url, *a, **kw):
        self.asking = (method, url)
        if self.entry is not None:
            self.entry.request(method, url)
        return super().putrequest(method, url, *a, **kw)

    def _opened(self, entry: netlog.Entry):
        self.entry = entry
        if self.asking[0]:
            entry.request(*self.asking)
        if self.sock is not None and not is_loopback(self.host):
            _track_live(self.sock, self.feature)

    def send(self, data):
        super().send(data)   # connects first, if it hasn't yet
        if self.entry is not None and isinstance(data, bytes | bytearray | memoryview):
            self.entry.add_sent(len(data))

    def getresponse(self):
        entry = self.entry
        def make(sock, *a, **kw):
            return _Response(sock, *a, entry=entry, stale=self._stale, **kw)
        # a factory, not the class: http.client only calls it
        self.response_class = make   # pyright: ignore[reportAttributeAccessIssue]
        r = super().getresponse()
        self.answered = True
        if entry is not None:
            entry.response(r.status, r.reason)
        return r

    def close(self):
        super().close()
        if self.entry is not None and not self.answered:
            self.entry.closed()   # no response will close it


class _HTTPConnection(_Logged, http.client.HTTPConnection):
    def connect(self):
        self.sock, entry = self._dial()
        self._opened(entry)


class _HTTPSConnection(_Logged, http.client.HTTPSConnection):
    def connect(self):
        sock, entry = self._dial()
        self.sock = sock
        self._opened(entry)
        try:
            ctx = self._context   # pyright: ignore[reportAttributeAccessIssue]  # http.client's
            self.sock = ctx.wrap_socket(sock, server_hostname=self.host)
        except BaseException as e:
            sock.close()
            assert self.entry is not None   # _opened set it
            self.entry.failed(f"secure connection failed ({errors.plain(e)})")
            raise
        if not is_loopback(self.host):
            _track_live(self.sock, self.feature)   # the TLS socket now (sock is detached)
        assert self.entry is not None   # _opened set it
        self.entry.set_tls(_tls_text(self.sock))


def _tls_text(sock: ssl.SSLSocket) -> str:
    """The TLS version, cipher and certificate, in a line."""
    out = f"{sock.version() or 'TLS'}, {(sock.cipher() or ('?',))[0]}"
    try:
        cert = sock.getpeercert() or {}
    except ValueError:
        return out

    def name(part, key):
        return next((v for rdn in cert.get(part, ()) for k, v in rdn if k == key), "")
    subject = name("subject", "commonName")
    issuer = name("issuer", "organizationName") or name("issuer", "commonName")
    if subject:
        out += f"; certificate for {subject}"
    if issuer:
        out += f", issued by {issuer}"
    return out


class _HTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, feature: str, direct: bool = False):
        super().__init__()
        self.feature, self.direct = feature, direct

    def http_open(self, req):
        return self.do_open(_HTTPConnection, req, feature=self.feature, direct=self.direct)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, feature: str, context, direct: bool = False):
        super().__init__(context=context)
        self.feature, self.direct = feature, direct

    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req,
                            context=self._context,   # pyright: ignore[reportAttributeAccessIssue]
                            feature=self.feature, direct=self.direct)


TLS_KEEP_S = 3600   # the shared TLS context is made again after this long
_tls: tuple[ssl.SSLContext | None, float] = (None, 0.0)   # (context, made at)
_tls_lock = threading.Lock()


def _tls_context() -> ssl.SSLContext:
    """The TLS settings stock urllib uses (http.client._create_https_context): ALPN
    http/1.1 and post-handshake auth on top of the defaults. Without them the
    handshake looks different, and Cloudflare (in front of Myinstants) answered every
    search with 403 though the request itself was the same.

    One context for every request, made again after TLS_KEEP_S (so a certificate
    Windows adds is picked up): making one reads Windows' certificate store, ~20 ms of
    CPU on a fast PC, and it was made for every request (ten downloads, a search)."""
    global _tls
    with _tls_lock:
        ctx, at = _tls
        now = time.monotonic()
        if ctx is None or not 0 <= now - at < TLS_KEEP_S:
            ctx = ssl.create_default_context()
            ctx.set_alpn_protocols(["http/1.1"])
            ctx.post_handshake_auth = True
            _tls = (ctx, now)
        return ctx


def _port(u: urllib.parse.SplitResult) -> int:
    """A URL's port (443 / 80 by default), or 0 when it isn't a number."""
    try:
        return u.port or (443 if u.scheme.lower() == "https" else 80)
    except ValueError:
        return 0


def _refuse_home(feature: str, u: urllib.parse.SplitResult) -> ProxyError:
    """The error (logged, and kept for explain()) for a request to this PC or the
    home network that `feature` may not make."""
    host = (u.hostname or "").strip("[]")
    why = _("Not connecting to {host}: it's on this PC or your home network", host=host)
    port = _port(u)
    netlog.blocked(feature, host, port, why)
    return _failed(why)


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    """A site's redirect never leads into this PC or the home network (except for
    HOME_OK features), and one to this PC is still checked against the switches:
    connect() lets loopback through unchecked only because the caller named it."""

    def __init__(self, feature: str):
        super().__init__()
        self.feature = feature

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlsplit(newurl)
        host = u.hostname or ""
        if netrelay._local_target(host):
            if self.feature not in HOME_OK:
                raise _refuse_home(self.feature, u)
            check(self.feature)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        old = urllib.parse.urlsplit(req.full_url)
        if new is not None and (old.scheme, old.hostname, old.port) != (u.scheme, host, u.port):
            # a key (a voice server's Bearer) or cookie is for the site it was given to:
            # never sent on to another one, nor over plain http after https
            for name in ("Authorization", "Cookie", "Proxy-Authorization"):
                new.headers.pop(name.capitalize(), None)
                new.unredirected_hdrs.pop(name.capitalize(), None)
        return new


def _opener(feature: str, direct: bool = False) -> urllib.request.OpenerDirector:
    """http / https only, connections made by connect() for `feature`: no ftp:// or
    file:// handler, and environment proxies are ignored (they point at the relay, and
    a redirect can't step around the setting, or into this PC / the home network)."""
    o = urllib.request.OpenerDirector()
    for h in (urllib.request.UnknownHandler(), _HTTPHandler(feature, direct),
              _HTTPSHandler(feature, _tls_context(), direct),
              urllib.request.HTTPDefaultErrorHandler(), _RedirectHandler(feature),
              urllib.request.HTTPErrorProcessor()):
        o.add_handler(h)
    return o


def urlopen(req, timeout: float = 30, feature: str | None = None, direct: bool = False):
    """urllib.request.urlopen for `feature` (a key of FEATURES), the way the Connection
    setting says. Raises FeatureOff, before anything is looked up, when that's switched
    off or no feature is named (a URL on this PC is always allowed). Any other address
    on the home network (192.168.x, .lan…) is refused, except for HOME_OK features,
    and so is a redirect into this PC or the home network. `direct` connects
    straight to the site whatever the Connection setting (the switches still hold):
    only for a click on "Try this one without Tor" (the user's own choice for that one
    request). Going direct, a name that leads into this PC / the home network
    (looked up once, connected to the checked address) is refused too."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if urllib.parse.urlsplit(url).scheme.lower() == "file":   # a file on this PC
        o = urllib.request.OpenerDirector()
        o.add_handler(urllib.request.FileHandler())
        return o.open(req, timeout=timeout)
    u = urllib.parse.urlsplit(url)
    if not known(feature) or not is_loopback(u.hostname or ""):
        try:
            check(feature)
        except FeatureOff as e:
            port = _port(u)
            netlog.blocked(feature, u.hostname or "", port, str(e))
            raise
    assert feature is not None   # check() raised for None
    if (feature not in HOME_OK and not is_loopback(u.hostname or "")
            and netrelay._local_target(u.hostname or "")):
        raise _refuse_home(feature, u)
    try:
        return _opener(feature, direct).open(req, timeout=timeout)
    except urllib.error.URLError as e:
        if isinstance(e.reason, FeatureOff):   # a redirect to somewhere switched off
            raise e.reason from None
        raise


class TooBig(Exception):
    """A download is bigger than its cap: ``listed`` is the size its Content-Length
    gave when that's what said so, 0 when the bytes themselves kept going past it.
    Not an OSError, so callers' network-error handling doesn't swallow it."""

    def __init__(self, listed: int = 0):
        super().__init__(f"over the size cap ({listed or 'kept going'})")
        self.listed = listed


def content_length(headers) -> int:
    """Content-Length as a number; 0 (unknown) when it's missing or isn't one."""
    try:
        return max(int(str(headers.get("Content-Length") or 0).strip()), 0)
    except ValueError:
        return 0


def read_capped(r, out, max_bytes: int, *, chunk: int = 1 << 16, total: int = 0,
                progress: Callable[[int, int], object] | None = None,
                check: Callable[[], object] | None = None) -> str:
    """Copy the response ``r`` into the file ``out``, never more than ``max_bytes``;
    returns the SHA-256 (hex) of what was written. Raises TooBig before reading when
    its Content-Length (or the ``total`` given) is over the cap, and as soon as the
    bytes pass it, so a bad mirror can't fill the disk. ``check`` runs before each
    chunk (raise from it to stop: cancelled, switched off); ``progress(done, total)``
    after. The caller deletes the partial file."""
    total = content_length(r.headers) or total
    if total > max_bytes:
        raise TooBig(total)
    h = hashlib.sha256()
    done = 0
    while data := r.read(chunk):
        if check is not None:
            check()
        done += len(data)
        if done > max_bytes:
            raise TooBig()
        h.update(data)
        out.write(data)
        if progress is not None:
            progress(done, total)
    return h.hexdigest()


# imported last: they import this module
from soundboard.online import netrelay  # noqa: E402
