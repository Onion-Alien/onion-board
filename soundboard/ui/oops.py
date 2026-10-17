"""The one way the app says "that didn't work": a red-edged card with sad Bun, what went
wrong in plain words, and what to do about it (try again; if it keeps happening, close
the app and open it again; still broken, report it), with a Try again button and a quiet
"Report a problem" (which only opens the bug form in the browser, feedback.py).

`OopsPanel` sits in a page in place of what couldn't be shown (search results, the
store's list, the radio's stations, a voice that won't switch on). The tours' red card
(coach.py) says the same words with `with_hint()`.

`tone=""` is the same card without the red, for "nothing here yet" (no program making
sound to share): nothing broke, so it isn't shown as an error.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.i18n import _

log = logging.getLogger(__name__)

BUN_H = 72        # sad Bun's height on the card
COMPACT_BUN_H = 56   # ... and beside the words (compact)
MAX_W = 420       # the card's width at most
MIN_W = 320       # ... and at least, when it's only a title and a line


def hint() -> str:
    """What to do when something didn't work."""
    return _("Try again. If it keeps happening, close Onion Board and open it again. "
             "Still broken? Report it and we'll fix it.")


def with_hint(line: str) -> str:
    """`line` (what didn't work), then what to do about it."""
    return f"{line}\n\n{hint()}" if line else hint()


_LINK = re.compile(r'\s*<a href="([^"]+)">[^<]*</a>\s*$')


def split_report(rich: str) -> tuple[str, str]:
    """An error's rich text without its trailing "Report it" link (errors.report_link),
    and that link's pre-filled report ("" when it had none)."""
    m = _LINK.search(rich or "")
    return (rich[:m.start()], m.group(1)) if m else (rich or "", "")


def report(window: QWidget | None, url: str = ""):
    """Report a problem: the bug form in the browser (`url`: one already filled in
    with what went wrong), with the app's version."""
    from soundboard import __version__, feedback, usage
    from soundboard.ui import busy
    usage.used("oops-report")
    busy.open_url(url or feedback.problem_url(__version__), window=window,
                  failed=_("Couldn't open your browser. The page is"))


class OopsPanel(QFrame):
    """Sad Bun over a title, a line, what to do, and Try again / Report a problem.
    Centred in whatever holds it; `show_problem()` fills it, `retry` is what Try again
    does (None: no Try again button)."""

    def __init__(self, parent: QWidget | None = None, *, tone: str = "error",
                 compact: bool = False):
        """`compact`: Bun beside the words, the words and buttons on the left, for a
        strip across a page (the Voice tab's) rather than a card in its middle."""
        from soundboard.ui.bunnywidget import BunnyWidget
        super().__init__(parent)
        self.setObjectName("oops")
        self.compact = compact
        if not compact:
            self.setMaximumWidth(MAX_W)
        self._retry: Callable[[], object] | None = None
        self._report_url = ""
        self.bun = BunnyWidget(height=COMPACT_BUN_H if compact else BUN_H, pad=10 if compact
                               else 14, sad=1.0)
        self.bun.sulk = True
        self.bun.setMinimumSize(1, 1)   # (no say in its holder's minimum size)
        self.bun.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if compact:
            h = QHBoxLayout(self)
            self._lay: QHBoxLayout | QVBoxLayout = h
            h.setContentsMargins(12, 10, 16, 12)
            h.setSpacing(12)
            h.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignTop)
            v = QVBoxLayout()
            v.setSpacing(4)
            h.addLayout(v, 1)
        else:
            v = self._lay = QVBoxLayout(self)
            v.setContentsMargins(18, 12, 18, 16)
            v.setSpacing(8)
            v.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignHCenter)
        align = Qt.AlignmentFlag.AlignLeft if compact else Qt.AlignmentFlag.AlignCenter
        self.title = QLabel()
        self.title.setObjectName("oopstitle")
        self.title.setWordWrap(True)
        self.title.setAlignment(align)
        v.addWidget(self.title)
        self.line = QLabel()
        self.line.setObjectName("oopsline")
        self.line.setWordWrap(True)
        self.line.setAlignment(align)
        self.line.setTextFormat(Qt.TextFormat.RichText)   # (callers escape plain words)
        self.line.setOpenExternalLinks(True)
        v.addWidget(self.line)
        self.what = QLabel()
        self.what.setObjectName("hint")
        self.what.setWordWrap(True)
        self.what.setAlignment(align)
        v.addWidget(self.what)
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)
        if not compact:
            row.addStretch(1)
        self.btn_report = QPushButton(_("Report a problem"))
        self.btn_report.setProperty("quiet", True)
        self.btn_report.clicked.connect(lambda: report(self.window(), self._report_url))
        row.addWidget(self.btn_report)
        self.btn_retry = QPushButton(_("Try again"))
        self.btn_retry.setObjectName("primary")
        self.btn_retry.clicked.connect(self._pressed_retry)
        row.addWidget(self.btn_retry)
        row.addStretch(1)
        if compact:   # Try again first, where the eye starts
            row.removeWidget(self.btn_report)
            row.insertWidget(1, self.btn_report)
        v.addLayout(row)
        self.set_tone(tone)

    def set_tone(self, tone: str):
        """"error": the red edge and title, Report a problem; "": plain (nothing broke)."""
        if self.property("tone") != tone:
            for w in (self, self.title):
                w.setProperty("tone", tone)
                w.style().unpolish(w)
                w.style().polish(w)
        self.btn_report.setVisible(tone == "error")
        self.what.setVisible(tone == "error")
        self.what.setText(hint())

    def show_problem(self, title: str, line: str = "", retry: Callable[[], object] | None = None,
                     *, button: str = "", tone: str = "error", fixable: bool = True):
        """Fill it: `title`, the `line` under it (rich text: escape plain words; an
        error's "Report it" link becomes the Report a problem button), and Try again
        (`button` to word it otherwise) doing `retry`. `fixable=False`: nothing the user
        can do (a server that's down), so no "close and open it again" and no Report."""
        self.set_tone(tone)
        if not fixable:
            self.what.hide()
            self.btn_report.hide()
        if not self.compact:   # without the long "what to do" lines it'd shrink to the title
            self.setMinimumWidth(0 if fixable else MIN_W)
        self.title.setText(title)
        line, self._report_url = split_report(line)
        self.line.setText(line)
        self.line.setVisible(bool(line))
        self._retry = retry
        self.btn_retry.setText(button or _("Try again"))
        self.btn_retry.setVisible(retry is not None)

    def fit_height(self, room: int):
        """Bun only when `room` (the holder's height) has space for him and the words."""
        bun = self.bun.sizeHint().height() + self._lay.spacing()
        self.bun.setVisible(room >= self._words_h() + bun)

    def _words_h(self) -> int:
        w = max(200, min(MAX_W, self.width() or MAX_W))
        h = self.height_for(w)
        if self.bun.isVisible():
            h -= self.bun.sizeHint().height() + self._lay.spacing()
        return h

    def height_for(self, w: int) -> int:
        """How tall it is at width `w` (the words wrap)."""
        lay = self._lay
        lay.activate()
        return (lay.totalHeightForWidth(w) if lay.hasHeightForWidth()
                else self.sizeHint().height())

    def _pressed_retry(self):
        if self._retry is None:
            return
        from soundboard import usage
        usage.used("oops-retry")
        try:
            self._retry()
        except Exception:  # noqa: BLE001 - a broken retry stays on the card
            log.warning("oops: retry", exc_info=True)


class _Page(QWidget):
    """A page holding one OopsPanel in its middle: Bun only while there's the height
    for him (the words always stay)."""

    def __init__(self, panel: OopsPanel):
        super().__init__()
        self.setObjectName("oopspage")
        self.panel = panel
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.addStretch(1)
        v.addWidget(panel, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(1)
        # no say in its holder's minimum size (a stack sizes to its biggest page): a
        # short tab squeezes it, and Bun steps out first (fit_height)
        self.setMinimumSize(1, 1)

    def resizeEvent(self, e):   # noqa: N802 - Qt
        super().resizeEvent(e)
        try:
            self.panel.fit_height(self.height() - 32)
        except Exception:  # noqa: BLE001 - never raise from a Qt override (AGENT-RULES)
            log.exception("oops: resize")


def centred(panel: OopsPanel) -> QWidget:
    """`panel` in the middle of a page of its own (a stack's page)."""
    return _Page(panel)
