"""Errors in plain words, and problems reported to us — not to the libraries we use.

The app leans on other people's code (yt-dlp, libsndfile, PortAudio, Windows…), and
their error messages are written for programmers: `[youtube] dQw4…: Sign in to
confirm your age. Use --cookies-from-browser…`, `Error opening 'x.mp3': Format not
recognised.`, or yt-dlp's own "please report this issue on github.com/yt-dlp/…".
A user shouldn't be sent to report our app's problems to another project, or be
told about command-line options they don't have.

`describe(e)` turns any exception (or an error string) into a `Problem`: a short
sentence to show, the original message (personal paths scrubbed) for a report, and
whether it's worth reporting — things the user can't fix themselves, like a
downloader hiccup or a bug, as opposed to a private video or a full disk.
`report_url()` / `report_link()` / `warn()` offer such a problem as a pre-filled
issue on this app's own GitHub; nothing is ever sent by the app itself.
"""
from __future__ import annotations

import errno
import logging
import re
from dataclasses import dataclass
from urllib.parse import quote

from soundboard.i18n import _

log = logging.getLogger(__name__)

OUR_PACKAGES = ("soundboard", "onionwatch", "__main__")


@dataclass
class Problem:
    text: str           # what to show the user
    detail: str = ""    # the original message, scrubbed, for a report
    reportable: bool = False   # not something the user can fix: ask them to tell us


# -- cleaning other projects' wording ----------------------------------------------

_NOISE = [
    # "...; please report this issue on https://github.com/yt-dlp/yt-dlp/issues?q= ,
    # filling out the appropriate issue template. Confirm you are on the latest
    # version using yt-dlp -U" — and other projects' "report a bug at <url>"
    re.compile(r"[;,.]?\s*(?:please\s+)?(?:report|file)\s+(?:this|a)\s+(?:issue|bug)\b.*$",
               re.I | re.S),
    re.compile(r"[;,.]?\s*Confirm you are on the latest version.*$", re.I | re.S),
    # command-line advice: "Use --cookies-from-browser or --cookies for …",
    # "See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#… for how to …"
    re.compile(r"[;,.]?\s*(?:Use|Try|Pass|Add|Run)\b[^.]*?\s--?[a-z][\w-]*[^.]*\.?", re.I),
    re.compile(r"[;,.]?\s*(?:See|Check|Visit|Read)\s+https?://\S+[^.]*\.?", re.I),
    re.compile(r"\(?\s*https?://(?:www\.)?github\.com/(?!Onion-Alien/)\S*\s*\)?", re.I),
    re.compile(r"\byt-dlp\s+-U\b", re.I),
]
_PREFIX = re.compile(r"^(?:ERROR:\s*|WARNING:\s*|\[[\w:.-]+\]\s*(?:[\w-]{6,}:\s*)?)+", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def clean(text: str) -> str:
    """Another library's message minus its colour codes, `[site] id:` prefix,
    "report this to us" lines, links to its own pages and command-line tips."""
    text = _ANSI.sub("", str(text or "")).strip()
    text = _PREFIX.sub("", text)
    for pat in _NOISE:
        text = pat.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" ;,:-")
    return text


def _upstream_wants_report(text: str) -> bool:
    return bool(re.search(r"(?:report|file)\s+(?:this|a)\s+(?:issue|bug)", text or "", re.I))


def _short(text: str, n: int = 160) -> str:
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _scrub(text: str) -> str:
    try:
        from soundboard.applog import scrub
        return scrub(text)
    except Exception:  # noqa: BLE001 - a report without scrubbing is still not sent
        return text


# -- known messages --------------------------------------------------------------

# (pattern on the cleaned message, plain words). First match wins. Functions, not
# tables: this module is imported before the language is picked (app.main), so the
# words are translated when they're used.
def _downloader() -> list[tuple[str, str]]:
    return [
        (r"private video|video is private", _("That video is private.")),
        (r"confirm your age|age.restricted|inappropriate for some users",
         _("That video is age-restricted, so it can't be downloaded without signing in.")),
        (r"not a bot|confirm you.?re not", _(
            "The site wants to check you're not a robot. It does that to an internet "
            "address it's had a lot of requests from (a VPN or a shared network can be "
            "one). Waiting a while usually clears it.")),
        (r"members.only|join this channel", _("That's a members-only video.")),
        (r"premieres in|live event will begin|this live event",
         _("That video hasn't started yet.")),
        (r"copyright", _("That video was taken down over a copyright claim.")),
        (r"not available in your country|geo.?restrict|in your (?:country|region|location)",
         _("That video is blocked in your country.")),
        (r"video (?:is )?unavailable|not available|has been removed|no longer available|"
         r"account .* terminated|does not exist", _("That video isn't available any more.")),
        (r"requested format is not available|no video formats|no formats found",
         _("There's no sound to download at that link.")),
        (r"unsupported url", _("That link isn't from a site sounds can be added from.")),
        (r"http error 404|not found", _("Nothing was found at that link (404).")),
        (r"http error 429|too many requests",
         _("The site is turning down too many requests. Try again in a few minutes.")),
        (r"http error 403|forbidden", _("The site refused the download (403).")),
        (r"http error 5\d\d", _("The site is having trouble right now. Try again later.")),
        (r"timed? ?out", _("The connection timed out. Check your internet and try again.")),
        (r"getaddrinfo|name resolution|unable to download webpage|connection (?:refused|reset|"
         r"aborted)|network is unreachable|no route to host|urlopen error",
         _("Couldn't reach the site. Check your internet connection.")),
        (r"sign in|login required|logged.in|cookies",
         _("That needs signing in to the site, which Onion Board doesn't do.")),
    ]


def _audio_file() -> list[tuple[str, str]]:
    return [
        (r"format not recognised|unknown format|not a valid|unsupported|file contains data",
         _("It isn't a sound file that can be read, or it's damaged.")),
        (r"system error|no such file", _("The file couldn't be opened.")),
    ]


def _audio_device() -> list[tuple[str, str]]:
    return [
        (r"invalid sample rate",
         _("That audio device doesn't support the sample rate needed.")),
        (r"invalid device|device unavailable|-9985|-9996", _(
            "That audio device isn't available (unplugged, or another app has it to "
            "itself).")),
        (r"unanticipated host error|-9999", _(
            "Windows' audio system refused (another app may have the device to itself).")),
        (r"invalid number of channels",
         _("That audio device doesn't support that many channels.")),
    ]


def _winerr(code: int) -> str:
    """Plain words for a Windows error number, or ""."""
    if code in (32, 33):
        return _("Another program is using that file. Close it and try again.")
    return {
        2: _("The file isn't there any more."),
        3: _("The folder isn't there any more."),
        5: _("Windows denied access (the file may be read-only, or an antivirus "
             "blocked it)."),
        112: _("The disk is full."),
        206: _("The file's path is too long."),
        448: _("Windows won't follow a folder link (a junction or a drive mounted as a "
               "folder) on the way to that file. Copy the file to a normal folder and "
               "try again."),
        1223: _("It was cancelled."),
        1392: _("The file is damaged and can't be read."),
        10054: _("The connection was dropped."),
        10060: _("The connection timed out. Check your internet and try again."),
        10061: _("The connection was refused."),
        11001: _("Couldn't reach the internet (the address couldn't be looked up)."),
    }.get(code, "")


def _errno(code: int) -> str:
    """Plain words for an errno, or ""."""
    if code in (errno.EACCES, errno.EPERM):
        return _winerr(5)
    return {
        errno.ENOENT: _("The file isn't there any more."),
        errno.ENOSPC: _("The disk is full."),
        errno.ENAMETOOLONG: _("The file's path is too long."),
        errno.EEXIST: _("Something with that name is already there."),
        errno.EISDIR: _("That's a folder, not a file."),
        errno.EROFS: _("That drive is read-only."),
    }.get(code, "")


def _match(table, text: str) -> str:
    for pat, words in table:
        if re.search(pat, text, re.I):
            return words
    return ""


def _module(e: BaseException) -> str:
    return type(e).__module__ or ""


def _ours(e: BaseException) -> bool:
    return _module(e).split(".")[0] in OUR_PACKAGES


def _os_error(e: OSError) -> str:
    import socket
    import ssl
    if isinstance(e, ssl.SSLError):
        return _("The secure connection failed.")
    if isinstance(e, socket.gaierror):
        return _winerr(11001)
    if isinstance(e, TimeoutError):
        return _winerr(10060)
    if getattr(e, "winerror", None) == 448 and e.filename:
        from soundboard import winpath
        if (link := winpath.first_link(e.filename)) is not None:
            return _("Windows won't follow the folder link “{link}” (it points to "
                     "“{target}”). Copy the file to a normal folder (like Desktop) and try "
                     "again, or make that folder a real folder instead of a link.",
                     link=link[0], target=link[1])
    words = _winerr(getattr(e, "winerror", None) or 0) or _errno(e.errno or 0)
    if words:
        return words
    if isinstance(e, ConnectionError):
        return _("The connection was refused or dropped.")
    if e.errno is None and not getattr(e, "winerror", None):
        return clean(str(e))   # an OSError("…") with our own message
    return clean(e.strerror or str(e))


# -- the API -----------------------------------------------------------------------

def describe(e: BaseException | str | None, downloader: bool = False) -> Problem:
    """Plain words for an exception (or an error message already turned into text).
    `downloader`: it came out of yt-dlp, whatever its type. The original message is
    never lost: it's in `.detail` (and so in a report) and, when the words differ,
    in the log."""
    p = _describe(e, downloader)
    raw = str(e or "")
    if p.detail and p.text != raw and not _logged(p):
        log.info("error shown as %r; original: %s", p.text, p.detail)
    return p


_LAST_LOGGED: list[str] = []


def _logged(p: Problem) -> bool:
    """Already logged recently (the same error is often described twice on its way
    to the screen): keeps the log from repeating itself."""
    key = p.detail
    if key in _LAST_LOGGED:
        return True
    _LAST_LOGGED.append(key)
    del _LAST_LOGGED[:-20]
    return False


def _describe(e: BaseException | str | None, downloader: bool) -> Problem:
    if e is None:
        return Problem(_("Something went wrong."))
    if isinstance(e, str):
        text = clean(e)
        return Problem(text or _("Something went wrong."), _scrub(e),
                       _upstream_wants_report(e))
    raw = str(e)
    detail = _scrub(f"{type(e).__module__}.{type(e).__name__}: {raw}")
    known = getattr(e, "problem", None)   # already described where it was raised
    if isinstance(known, Problem):
        return known
    mod = _module(e)
    cleaned = clean(raw)
    if _ours(e) and not downloader:
        # our own messages are written for people; ours to report only if asked
        return Problem(cleaned or _("Something went wrong."), detail,
                       bool(getattr(e, "reportable", False)))
    if downloader or mod.startswith("yt_dlp"):
        words = _match(_downloader(), cleaned)
        if words:
            return Problem(words, detail)
        return Problem(_("The downloader ran into a problem: {error}", error=_short(cleaned))
                       if cleaned else _("The downloader ran into a problem."), detail, True)
    # a device first: PortAudio's "Error opening OutputStream: ..." starts like
    # libsndfile's "Error opening 'x.mp3': ...", and isn't about a sound file
    if mod.startswith("sounddevice") or "PaErrorCode" in raw:
        words = _match(_audio_device(), cleaned)
        return Problem(words or _("The audio device reported a problem."), detail, not words)
    if mod.startswith("soundfile") or "libsndfile" in raw or raw.startswith("Error opening"):
        return Problem(_match(_audio_file(), cleaned)
                       or _("It isn't a sound file that can be read, or it's damaged."),
                       detail)
    import json
    import urllib.error
    import zipfile
    if isinstance(e, urllib.error.HTTPError):
        return Problem(_match(_downloader(), f"http error {e.code}")
                       or _("The server answered with an error ({code}).", code=e.code),
                       detail)
    if isinstance(e, urllib.error.URLError):
        reason = e.reason
        return (describe(reason) if isinstance(reason, BaseException) else
                Problem(_("Couldn't reach the server. Check your internet connection."),
                        detail))
    if isinstance(e, OSError):
        return Problem(_os_error(e) or _("Windows reported a problem."), detail)
    if isinstance(e, zipfile.BadZipFile):
        return Problem(_("It isn't a zip file, or it's damaged."), detail)
    if isinstance(e, json.JSONDecodeError):
        return Problem(_("The file is damaged (it couldn't be read)."), detail)
    if isinstance(e, UnicodeError):
        return Problem(_("The file has text in a format that couldn't be read."), detail)
    if isinstance(e, MemoryError):
        return Problem(_("Ran out of memory. Close some programs and try again."), detail)
    if isinstance(e, (TypeError, KeyError, AttributeError, IndexError, NameError,
                      AssertionError, ZeroDivisionError)):
        return Problem(_("Something went wrong inside Onion Board."), detail, True)
    if mod in ("builtins", "") and isinstance(e, (RuntimeError, ValueError)) and cleaned:
        # raised with a sentence (often by our own code): keep it, minus any noise
        return Problem(cleaned, detail, _upstream_wants_report(raw))
    return Problem(_("Something unexpected went wrong ({error}).",
                     error=_short(cleaned) if cleaned else type(e).__name__), detail, True)


def plain(e: BaseException | str | None) -> str:
    """Just the words: `describe(e).text`."""
    return describe(e).text


def report_url(p: Problem, where: str = "") -> str:
    """A new issue on this app's GitHub, filled in with the version and the problem.
    The user sees it in the browser and decides what to send."""
    from soundboard import __version__
    from soundboard.feedback import ISSUE_URL
    title = f"Problem: {where}" if where else "Problem: " + _short(p.text, 70)
    body = (f"**Onion Board version:** {__version__}\n"
            + _extra_versions(p.detail)
            + (f"**Where:** {where}\n" if where else "")
            + f"**What it said:** {p.text}\n\n"
            "**What were you doing?**\n\n\n"
            "<details><summary>Details</summary>\n\n```\n"
            + _short(p.detail, 1500) + "\n```\n</details>\n")
    return f"{ISSUE_URL}?labels=bug&title={quote(title)}&body={quote(body)}"


def _extra_versions(detail: str) -> str:
    if "yt_dlp" not in detail:
        return ""
    try:
        from soundboard import ytdl
        return f"**yt-dlp version:** {ytdl.active_version()[0]}\n"
    except Exception:  # noqa: BLE001
        return ""


def report_link(p: Problem, where: str = "") -> str:
    """` <a>Report it</a>` (rich text) for a reportable problem, else "". The label
    showing it needs `linkify(label)`."""
    if not p.reportable:
        return ""
    return " " + _("<a href=\"{url}\">Report it</a>", url=report_url(p, where))


def html(e: BaseException | str | None, before: str = "", where: str = "") -> str:
    """Rich text for a label: `before` + the plain words, escaped, + a report link."""
    import html as _html
    p = describe(e)
    return _html.escape(f"{before}{p.text}") + report_link(p, where)


def linkify(label) -> None:
    """Let a QLabel open its links (the "Report it" one) in the browser."""
    from PySide6.QtCore import Qt
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(label.textInteractionFlags()
                                  | Qt.TextInteractionFlag.LinksAccessibleByMouse)


def warn(parent, title: str, e: BaseException | str | None, before: str = "",
         after: str = "", where: str = "") -> None:
    """A warning box with the plain words; a reportable problem gets a *Report it*
    button that opens the pre-filled issue in the browser."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox
    p = describe(e)
    text = f"{before}{p.text}{after}"
    if not p.reportable:
        QMessageBox.warning(parent, title, text)
        return
    box = QMessageBox(QMessageBox.Icon.Warning, title,
                      text + "\n\n" + _(
                          "This looks like a problem in Onion Board. Reporting it opens a "
                          "page on our GitHub with the details filled in; you choose what "
                          "to send."), QMessageBox.StandardButton.NoButton, parent)
    report = box.addButton(_("Report it"), QMessageBox.ButtonRole.HelpRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is report:
        QDesktopServices.openUrl(QUrl(report_url(p, where or title)))
