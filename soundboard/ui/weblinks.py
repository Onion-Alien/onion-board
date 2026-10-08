"""Web links open in the user's browser without the app's relay settings.

The app points FFmpeg at its relay through http_proxy & co. in its own environment
(net._set_env). A program the app starts gets a copy of that environment, so a
browser that wasn't running yet when a link was clicked would take the relay as its
proxy for everything, and every site would ask for the relay's login. Every
QDesktopServices.openUrl() for http(s)/mailto comes here instead: the opener is started
with net.own_env(), the user's own proxy variables, so the browser starts as if the
user had opened it.
"""
from __future__ import annotations

import logging
import subprocess
import sys

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices

from soundboard import net

log = logging.getLogger(__name__)

SCHEMES = ("http", "https", "mailto")


def opener(url: str) -> list[str]:
    """The command that hands `url` to the default browser / mail program."""
    if sys.platform == "win32":
        # not explorer.exe: it can't take a link with ?/& in it and opens the
        # Documents folder instead (Send feedback, Report a problem)
        return ["rundll32.exe", "url.dll,FileProtocolHandler", url]
    if sys.platform == "darwin":
        return ["open", url]
    return ["xdg-open", url]


def open_clean(url: str) -> bool:
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen(opener(url), env=net.own_env(), close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
        return True
    except OSError:
        log.warning("couldn't open a link", exc_info=True)
        return False


class _Handler(QObject):
    @Slot(QUrl)
    def open(self, url: QUrl) -> None:
        open_clean(bytes(url.toEncoded()).decode("ascii"))


_handler: _Handler | None = None


def install() -> None:
    global _handler
    if _handler is None:
        _handler = _Handler()
    for scheme in SCHEMES:
        QDesktopServices.setUrlHandler(scheme, _handler, "open")
