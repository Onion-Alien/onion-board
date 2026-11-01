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
exit countries), conjure-client.exe and tor-gencert.exe. scripts/buildtools/fetch_tor.py unpacks
the same files into vendor/tor for running from source.

To move to a newer Tor release: take the new tarball's line from that release's
sha256sums-signed-build.txt, verify that file's signature once
(gpg --verify sha256sums-signed-build.txt.asc, signed by the Tor Browser developers'
key EF6E 286D DA85 EA2A 4BA7 DE68 4E2C 6E87 9329 8290), then update VERSION and
SHA256 (.github/workflows/pin-bumps.yml does this weekly and opens a PR). A copy
with an older stamp is offered as "Update Tor" in Settings.
"""
from __future__ import annotations

import io
import logging
import shutil
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from soundboard.sounds import library
from soundboard.online import net
from soundboard.core import errors
from soundboard.i18n import _

log = logging.getLogger(__name__)

VERSION = "15.0.25"
TARBALL = f"tor-expert-bundle-windows-x86_64-{VERSION}.tar.gz"
URL = f"https://dist.torproject.org/torbrowser/{VERSION}/{TARBALL}"
# dist.torproject.org keeps only the latest few versions; once this one is gone from it
# (404), the Tor Project's archive still has it. The same SHA256 is checked either way.
ARCHIVE_URL = f"https://archive.torproject.org/tor-package-archive/torbrowser/{VERSION}/{TARBALL}"
GONE = (404, 410)
SHA256 = "c1988c701de2f24f7d098d1d6d7f507b58f27740d097f29c246e0524d639b252"
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
FEATURE = "tor_download"   # soundboard.online.net's switch for this download


def blocked_hint() -> str:
    """Added to a failed download. A function: this module can be imported before the
    language is picked (app.main)."""
    return _("Where Tor is blocked, downloading it often is too: a proxy (Connection "
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


TIDY_AFTER_S = 600   # an unpack swaps in seconds: older leftovers are a past one's


def tidy(dest: Path | None = None) -> None:
    """Clear what an unpack cut short (the app ended mid-way: End task, a crash, the
    power) left beside the bin folder: a half-written bin.partial, and bin.old, put
    back first when the swap stopped before the new copy was in place (else Tor would
    be gone, and with Connection set to Tor nothing could fetch it again). Only ones
    older than TIDY_AFTER_S: a fresh one is an unpack still going (--get-tor)."""
    dest = dest or bin_dir()
    cutoff = time.time() - TIDY_AFTER_S
    old = dest.with_name(dest.name + ".old")
    tmp = dest.with_name(dest.name + ".partial")
    try:
        if old.is_dir() and old.stat().st_mtime < cutoff:
            if not dest.exists():
                old.rename(dest)
                log.info("put back the Tor an update had moved aside")
            else:
                shutil.rmtree(old, ignore_errors=True)
        if tmp.is_dir() and tmp.stat().st_mtime < cutoff:
            log.info("removing a half-unpacked Tor")
            shutil.rmtree(tmp, ignore_errors=True)
    except OSError:
        log.warning("couldn't tidy the tor folder", exc_info=True)


def outdated() -> bool:
    """A Tor downloaded by an older version of the app is here (not this release's)."""
    return (bin_dir() / STAMP).is_file() and not installed()


def download(progress: Callable[[int, int], None] | None = None) -> bytes:
    """The tarball, checked against SHA256: from dist.torproject.org, or from the
    archive once dist no longer has this version. `progress(done, total)` is called as
    it arrives (total 0 when the server doesn't say). Raises GetError."""
    try:
        return _download(URL, progress)
    except _Gone:
        log.info("tor download: Tor %s is gone from dist.torproject.org, using the archive",
                 VERSION)
    try:
        return _download(ARCHIVE_URL, progress)
    except _Gone as e:
        raise GetError(_("archive.torproject.org said {error}.", error=e) + " "
                       + blocked_hint()) from None


class _Gone(Exception):
    """The server says the file isn't there (404 / 410)."""


def _download(url: str, progress) -> bytes:
    host = urllib.parse.urlsplit(url).hostname
    req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard"})
    buf = io.BytesIO()
    try:
        with net.urlopen(req, timeout=TIMEOUT_S, feature=FEATURE) as r:
            got = net.read_capped(r, buf, MAX_BYTES, chunk=CHUNK, progress=progress)
    except net.TooBig as e:
        if e.listed:
            raise GetError(_("The download is {mb} MB, far bigger than Tor: not "
                             "taking it.", mb=f"{e.listed / 1e6:.0f}")) from None
        raise GetError(_("The download kept going far past Tor's size: "
                         "not taking it.")) from None
    except net.ProxyError as e:   # FeatureOff included: switched off, nothing sent
        raise GetError(errors.plain(e)) from None
    except urllib.error.HTTPError as e:
        if e.code in GONE:
            raise _Gone(f"{e.code} {e.reason}") from None
        raise GetError(_("{host} said {error}.", host=host, error=f"{e.code} {e.reason}")
                       + " " + blocked_hint()) from None
    except (urllib.error.URLError, OSError) as e:
        why = getattr(e, "reason", None) or e
        raise GetError(_("Couldn't reach {host} ({error}).", host=host, error=why)
                       + " " + blocked_hint()) from None
    if got != SHA256:
        log.warning("tor download: SHA-256 %s, expected %s", got, SHA256)
        raise GetError(_("The download isn't the Tor it should be (its checksum doesn't "
                         "match), so it wasn't used. Something between you and the Tor "
                         "Project changed it, or it was cut short: try again later."))
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
                    raise GetError(_("{name} is missing from {file}", name=name,
                                     file=TARBALL)) from None
                src = tar.extractfile(member) if member.isfile() else None
                if src is None:
                    raise GetError(_("{name} in {file} isn't a file", name=name,
                                     file=TARBALL))
                out = tmp / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(src.read())
        (tmp / STAMP).write_text(stamp_text() + "\n", "ascii")
        old = dest.with_name(dest.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if dest.exists():
            dest.rename(old)   # fails while tor.exe in it is running
        try:
            tmp.rename(dest)
        except OSError:
            if old.exists() and not dest.exists():
                old.rename(dest)   # put the working copy back
            raise
        shutil.rmtree(old, ignore_errors=True)
    except GetError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except (OSError, tarfile.TarError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise GetError(_("Couldn't unpack Tor into {folder} ({error}). If Tor is running, "
                         "switch Connection away from Tor and try again; an antivirus may "
                         "also have blocked tor.exe.", folder=dest,
                         error=getattr(e, "strerror", "") or e)) from None
    return dest


def get(progress: Callable[[int, int], None] | None = None,
        before_unpack: Callable[[], None] | None = None) -> Path:
    """Download, check and unpack Tor into the bin folder; the folder. Raises GetError.
    `before_unpack` runs between the two (the app stops a running Tor there, which may
    have carried the download)."""
    from soundboard.online import tor  # it imports this module
    if not net.allowed(FEATURE):
        raise GetError(net.off_message(FEATURE))
    if net.mode() == net.TOR and not tor.available():
        raise GetError(_("Connection is set to Tor, but there's no Tor here yet to carry "
                         "the download. Pick Direct or Through a proxy, then Get Tor."))
    log.info("downloading Tor %s (%s)", VERSION, net.describe(where=False))
    data = download(progress)
    with tor.hold():   # nothing restarts tor.exe from the folder while it's swapped
        if before_unpack:
            before_unpack()
        dest = unpack(data)
    log.info("Tor %s unpacked into the tor\\bin folder", VERSION)
    return dest
