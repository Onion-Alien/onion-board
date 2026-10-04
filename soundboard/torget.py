"""Getting Tor: the Tor Project's Tor Expert Bundle, downloaded when the user asks for
it (Settings > Connection > Get Tor, or the installer's "Private
connection (Tor)" box, which runs `OnionBoard.exe --get-tor`). The app doesn't ship it.

The tarball comes from dist.torproject.org through net.urlopen (feature
"tor_download", with its own switch in Settings), so it follows the Connection setting
(a proxy, or a Tor that's already here when updating it). It's
checked against the SHA-256 pinned below before anything is unpacked, and only the
parts the app runs are kept, in %APPDATA%\\OnionBoard\\tor\\bin (about 28 MB):
tor.exe, lyrebird.exe (obfs4 / Snowflake bridges), pt_config.json (the built-in
bridge lines) and the licence texts. Skipped: the GeoIP databases (only needed to pick
exit countries), conjure-client.exe and tor-gencert.exe. scripts/fetch_tor.py unpacks
the same files into vendor/tor for running from source.

To move to a newer Tor release: take the new tarball's line from that release's
sha256sums-signed-build.txt, verify that file's signature once
(gpg --verify sha256sums-signed-build.txt.asc, signed by the Tor Browser developers'
key EF6E 286D DA85 EA2A 4BA7 DE68 4E2C 6E87 9329 8290), then update VERSION and
SHA256. A copy with an older stamp is offered as "Update Tor" in Settings.
"""
from __future__ import annotations

import hashlib
import io
import logging
import shutil
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from soundboard import library, net
from soundboard import errors

log = logging.getLogger(__name__)

VERSION = "15.0.24"
TARBALL = f"tor-expert-bundle-windows-x86_64-{VERSION}.tar.gz"
URL = f"https://dist.torproject.org/torbrowser/{VERSION}/{TARBALL}"
SHA256 = "e9dc6ccc93cd6afa507193f4de284d6424233ff5102155cd2c94b259e8a22b65"
MAX_BYTES = 100_000_000       # the tarball is about 22 MB; anything far bigger isn't it
CHUNK = 256 * 1024
TIMEOUT_S = 60.0
# member in the tarball -> where it goes in the bin folder
KEEP = {
    "tor/tor.exe": "tor.exe",
    "tor/pluggable_transports/lyrebird.exe": "pluggable_transports/lyrebird.exe",
    "tor/pluggable_transports/pt_config.json": "pluggable_transports/pt_config.json",
    "docs/tor.txt": "docs/tor.txt",
    "docs/lyrebird.txt": "docs/lyrebird.txt",
    "docs/libevent.txt": "docs/libevent.txt",
    "docs/openssl.txt": "docs/openssl.txt",
    "docs/zlib.txt": "docs/zlib.txt",
}
STAMP = "VERSION"
FEATURE = "tor_download"   # soundboard.net's switch for this download
BLOCKED_HINT = ("Where Tor is blocked, downloading it often is too: a proxy (Connection "
                "> Through a proxy) may get through.")


class GetError(Exception):
    """Tor couldn't be downloaded or unpacked; the message is for the user."""


def bin_dir() -> Path:
    """Where the downloaded Tor lives: %APPDATA%\\OnionBoard\\tor\\bin."""
    return library.APP_DIR / "tor" / "bin"


def stamp_text() -> str:
    return f"{VERSION} {SHA256}"


def installed(dest: Path | None = None) -> bool:
    """This version of Tor, complete, is in `dest` (the bin folder by default)."""
    dest = dest or bin_dir()
    try:
        ok = (dest / STAMP).read_text("ascii").strip() == stamp_text()
    except OSError:
        return False
    return ok and all((dest / rel).is_file() for rel in KEEP.values())


def download(progress: Callable[[int, int], None] | None = None) -> bytes:
    """The tarball, checked against SHA256. `progress(done, total)` is called as it
    arrives (total 0 when the server doesn't say). Raises GetError."""
    req = urllib.request.Request(URL, headers={"User-Agent": "OnionBoard"})
    h = hashlib.sha256()
    buf = io.BytesIO()
    try:
        with net.urlopen(req, timeout=TIMEOUT_S, feature=FEATURE) as r:
            total = int(r.headers.get("Content-Length") or 0)
            if total > MAX_BYTES:
                raise GetError(f"The download is {total / 1e6:.0f} MB, far bigger than "
                               "Tor: not taking it.")
            while chunk := r.read(CHUNK):
                h.update(chunk)
                buf.write(chunk)
                if buf.tell() > MAX_BYTES:
                    raise GetError("The download kept going far past Tor's size: "
                                   "not taking it.")
                if progress:
                    progress(buf.tell(), total)
    except net.ProxyError as e:   # FeatureOff included: switched off, nothing sent
        raise GetError(errors.plain(e)) from None
    except urllib.error.HTTPError as e:
        raise GetError(f"dist.torproject.org said {e.code} {e.reason}. {BLOCKED_HINT}") from None
    except (urllib.error.URLError, OSError) as e:
        why = getattr(e, "reason", None) or e
        raise GetError(f"Couldn't reach dist.torproject.org ({why}). {BLOCKED_HINT}") from None
    got = h.hexdigest()
    if got != SHA256:
        log.warning("tor download: SHA-256 %s, expected %s", got, SHA256)
        raise GetError("The download isn't the Tor it should be (its checksum doesn't "
                       "match), so it wasn't used. Something between you and the Tor "
                       "Project changed it, or it was cut short: try again later.")
    return buf.getvalue()


def unpack(data: bytes, dest: Path | None = None) -> Path:
    """Unpack the kept files from a checked tarball into `dest` (the bin folder by
    default), replacing what's there. Only the named members are read, each written to
    a fixed path, so nothing in the tarball picks where a file goes."""
    dest = dest or bin_dir()
    tmp = dest.with_name(dest.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for name, rel in KEEP.items():
                try:
                    member = tar.getmember(name)
                except KeyError:
                    raise GetError(f"{name} is missing from {TARBALL}") from None
                src = tar.extractfile(member) if member.isfile() else None
                if src is None:
                    raise GetError(f"{name} in {TARBALL} isn't a file")
                out = tmp / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(src.read())
        (tmp / STAMP).write_text(stamp_text() + "\n", "ascii")
        old = dest.with_name(dest.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if dest.exists():
            dest.rename(old)   # fails while tor.exe in it is running
        tmp.rename(dest)
        shutil.rmtree(old, ignore_errors=True)
    except GetError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except (OSError, tarfile.TarError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise GetError(f"Couldn't unpack Tor into {dest} ({getattr(e, 'strerror', '') or e}). "
                       "If Tor is running, switch Connection away from Tor and try again; "
                       "an antivirus may also have blocked tor.exe.") from None
    return dest


def get(progress: Callable[[int, int], None] | None = None,
        before_unpack: Callable[[], None] | None = None) -> Path:
    """Download, check and unpack Tor into the bin folder; the folder. Raises GetError.
    `before_unpack` runs between the two (the app stops a running Tor there, which may
    have carried the download)."""
    from soundboard import tor   # it imports this module
    if not net.allowed(FEATURE):
        raise GetError(net.off_message(FEATURE))
    if net.mode() == net.TOR and not tor.available():
        raise GetError("Connection is set to Tor, but there's no Tor here yet to carry "
                       "the download. Pick Direct or Through a proxy, then Get Tor.")
    log.info("downloading Tor %s (%s)", VERSION, net.describe())
    data = download(progress)
    if before_unpack:
        before_unpack()
    dest = unpack(data)
    log.info("Tor %s unpacked into the tor\\bin folder", VERSION)
    return dest
