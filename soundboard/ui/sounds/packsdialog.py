"""The *Free sound packs* page (Sounds tab → Backup; in the tabs' place, like Settings):
ready-made boards anyone can add in one click (soundboard.sounds.packs). A search box and
filter chips over a grid of small cards; a card (or its Preview) opens a small window with
what's in it and a few of its sounds as pads to try first (to your headphones only). Every
pack's samples are fetched in the background once the page is up, so they're ready."""
from __future__ import annotations

import html
import logging
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QDesktopServices, QFont, QIcon, QPainter, QPainterPath, QPixmap)
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from soundboard.core import errors, updates
from soundboard.sounds import library, packs
from soundboard.online import net
from soundboard.audio.engine import SR
from soundboard.ui.bun import bunacts
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.kit.panel import HoverCard, hint_label, section_label
from soundboard.ui.kit.panellayouts import CardGrid, Flow
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)

PIC = 32          # px: a sample's picture on its button
SAMPLE_COLS = 3   # sample buttons a row
ART = 44          # px: a pack's emoji tile on its card (the pack's own view: ART_BIG)
ART_BIG = 64
PAD_H = 56        # px: a preview's pads
CARD_MIN_W = 250  # the cards: as many a row as fit at this width
CARD_GAP = 12
SEARCH_MAX_W = 480
# The page is filled a piece at a time (a pack's card, one sample's tile) with this
# long a rest between pieces. Built in one go it was ~80 ms of back-to-back Qt work,
# and the audio threads wait on the UI thread through all of it: with a few sounds
# playing, blocks came 10 ms late, a skip.
STEP_GAP_MS = 4
# plays a sample to your headphones only at a gain (None stops it); False when it
# couldn't (no headphones set)
Play = Callable[[np.ndarray | None, float], bool]
ALL, MINE = "", "\0mine"   # the filter chips that aren't a pack tag


def size_text(n: int) -> str:
    return _("{n} MB", n=max(1, round(n / 1e6))) if n else ""


def meta_line(p: packs.Pack, licence: bool = True) -> str:
    """"67 sounds · 28 MB · CC0 · by Onion Board"; a links pack "100 sounds · from
    Myinstants"."""
    bits = [ngettext("{n} sound", "{n} sounds", p.sounds) if p.sounds else ""]
    if p.links:
        bits.append(_("from Myinstants"))
    else:
        bits.append(size_text(p.size))
        if licence:
            bits.append(p.license)
    if licence and p.author:
        bits.append(_("by {name}", name=p.author))
    return " · ".join(b for b in bits if b)


def matches(p: packs.Pack, words: list[str]) -> bool:
    """Every word of a search is somewhere in the pack: its name, words, categories,
    kind or (a links pack) its sounds' names."""
    hay = " ".join([p.name, p.description, p.author, *p.categories, *p.tags,
                    *(k.name for k in p.links)]).casefold()
    return all(w in hay for w in words)


def emoji_art(emoji: str, size: int, dpr: float = 1.0) -> QPixmap:
    """A pack's emoji drawn as a picture `size` px square (a picture, not text: it
    doesn't follow the text size)."""
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    f = QFont("Segoe UI Emoji")
    f.setPixelSize(round(size * 0.62))
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, emoji)
    p.end()
    return pm


def art_label(emoji: str, size: int) -> QLabel:
    lbl = QLabel()
    lbl.setObjectName("packart")   # a soft accent tile (themesheet.py)
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setPixmap(emoji_art(emoji, size, lbl.devicePixelRatioF()))
    lbl.setAccessibleName("")
    return lbl


def rounded(png: bytes, size: int) -> QIcon | None:
    """A sample's tile picture, `size` px square with round corners."""
    src = QPixmap()
    if not png or not src.loadFromData(png):
        return None
    src = src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), 6, 6)
    p.setClipPath(path)
    p.drawPixmap((size - src.width()) // 2, (size - src.height()) // 2, src)
    p.end()
    return QIcon(out)


class ClampedLabel(QLabel):
    """Hint text cut to `lines` lines with "…" (a card's description)."""

    def __init__(self, text: str, lines: int = 2):
        super().__init__()
        self.setObjectName("hint")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._full, self._lines = text, lines
        self.setToolTip("")
        self._clamp()

    def _clamp(self):
        fm = self.fontMetrics()
        self.setFixedHeight(fm.lineSpacing() * self._lines + 2)
        w = self.width() if self.isVisible() else CARD_MIN_W - 28
        if w <= 0:
            return
        flags = int(Qt.TextFlag.TextWordWrap)
        room = fm.lineSpacing() * self._lines + 1
        text = self._full
        if fm.boundingRect(0, 0, w, 10_000, flags, text).height() > room:
            lo, hi = 0, len(text)
            while lo < hi:   # the longest start that fits with "…" after it
                mid = (lo + hi + 1) // 2
                if fm.boundingRect(0, 0, w, 10_000, flags,
                                   text[:mid].rstrip() + "…").height() <= room:
                    lo = mid
                else:
                    hi = mid - 1
            text = text[:lo].rstrip(" ,.;:") + "…"
        self.setText(text)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            try:
                self._clamp()
            except Exception:  # noqa: BLE001 - never raise from a Qt override
                log.debug("couldn't fit a pack's words", exc_info=True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        try:
            self._clamp()
        except Exception:  # noqa: BLE001 - never raise from a Qt override
            log.debug("couldn't fit a pack's words", exc_info=True)


class SampleButton(QPushButton):
    """One of a pack's sounds to try: its picture and name, lit while it plays."""

    def __init__(self):
        super().__init__()
        self.sample: packs.Sample | None = None
        self._name = ""
        self.setObjectName("voicetile")
        self.setProperty("art", True)
        self.setCheckable(True)
        self.setIconSize(QSize(PIC, PIC))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_sample(None)

    def set_sample(self, sample: packs.Sample | None):
        """None: an empty placeholder while the samples are fetched (no jump later)."""
        self.sample = sample
        self.setEnabled(sample is not None)
        self._name = sample.name if sample else ""
        pic = rounded(sample.picture, PIC) if sample else None
        if pic is None and sample is None:   # loading: an empty tile, as tall as a full one
            blank = QPixmap(PIC, PIC)
            blank.fill(Qt.GlobalColor.transparent)
            pic = QIcon(blank)
        self.setIcon(pic or icons.icon("play", "muted"))
        self.setAccessibleName(_("Hear {name}", name=self._name) if sample else "")
        self.setToolTip(plain_tip(_("Hear {name} (only you hear it)", name=self._name))
                        if sample else "")   # (the name comes from the pack)
        self._fit_name()

    def _fit_name(self):
        if not self.isVisible():   # not laid out yet: showing it resizes it
            self.setText(self._name.replace("&", "&&"))
            return
        room = self.width() - PIC - 30   # the picture, its gap and the padding
        shown = self.fontMetrics().elidedText(self._name, Qt.TextElideMode.ElideRight,
                                              max(0, room))
        self.setText(shown.replace("&", "&&"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        try:
            self._fit_name()
        except Exception:  # noqa: BLE001 - never raise from a Qt override
            log.debug("couldn't fit a sample's name", exc_info=True)


def _add_button(primary: bool) -> QPushButton:
    b = QPushButton()
    if primary:
        b.setObjectName("primary")
    return b


def _show_add(btn: QPushButton, pack: packs.Pack, short: bool = False):
    """A pack's Add button, idle: Add (to my board), or (added before) Add again. `short`:
    a card's, one word (the rest in its tooltip)."""
    added = pack.downloaded()
    btn.setText(_("Add again") if added else _("Add") if short else _("Add to my board"))
    btn.setToolTip(
        _("Adds its sounds again; ones already on your board are skipped") if added else
        ngettext("Downloads its {n} sound from Myinstants and puts it on your board",
                 "Downloads its {n} sounds from Myinstants and puts them on your board, "
                 "each category as its own tab", len(pack.links)) if pack.links else
        _("Downloads the pack ({size}) and puts its sounds on your board, each "
          "category as its own tab", size=size_text(pack.size) or "?"))
    icons.set_icon(btn, "check" if added else "download",
                   "on_accent" if btn.objectName() == "primary" else None)


def has_preview(p: packs.Pack) -> bool:
    """A few of its sounds can be tried: its preview zip, or a links pack's first links."""
    return bool(p.preview_url or p.links)


def sample_key(p: packs.Pack) -> tuple:
    """Which samples a pack's are (a changed preview, or first links, are new ones)."""
    return (p.id, p.preview_sha256, tuple(k.url for k in p.links[:packs.SAMPLES]))


class PackCard(HoverCard):
    """A pack in the grid: its picture, name, size and a line of what it's for, then
    Preview and Add. A click anywhere else opens its preview too."""
    opened = Signal(object)   # the card

    def __init__(self, pack: packs.Pack):
        super().__init__()
        self.pack = pack
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(pack.name)
        self.setToolTip(plain_tip(_("See what's in {name}", name=pack.name)))
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(art_label(pack.emoji, ART), 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.name = QLabel(pack.name)
        self.name.setObjectName("tabcardtitle")
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        names.addWidget(self.name)
        self.meta = QLabel(meta_line(pack, licence=False))
        self.meta.setObjectName("hint")
        self.meta.setTextFormat(Qt.TextFormat.PlainText)
        self.meta.setWordWrap(True)
        names.addWidget(self.meta)
        names.addStretch(1)
        top.addLayout(names, 1)
        v.addLayout(top)
        self.about = ClampedLabel(pack.description or "")
        v.addWidget(self.about)
        v.addStretch(1)
        foot = QHBoxLayout()   # (its kinds are the chips over the grid: not here too)
        foot.setSpacing(8)
        self.btn_preview = QPushButton(_("Preview"))
        self.btn_preview.setProperty("quiet", True)
        icons.set_icon(self.btn_preview, "play")
        self.btn_preview.setToolTip(_("Hear a few of its sounds first (only you hear them)"))
        self.btn_preview.clicked.connect(lambda: self.opened.emit(self))
        self.btn = _add_button(False)   # (a grid of accent buttons shouts: the preview's is)
        self.btn.clicked.connect(self._add)
        for b in (self.btn, self.btn_preview):   # the row split in two, evenly
            b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            foot.addWidget(b, 1)
        v.addLayout(foot)
        self.show_idle()

    def show_idle(self):
        _show_add(self.btn, self.pack, short=True)

    def _add(self, _checked: bool = False):
        w = self.parentWidget()
        while w is not None and not isinstance(w, PacksDialog):
            w = w.parentWidget()
        if w is not None:
            w.add(self.pack)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.opened.emit(self)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.opened.emit(self)
            return
        super().keyPressEvent(e)


class PreviewDialog(QDialog):
    """A pack's preview, over the page: what's in it, a few of its sounds as pads to
    press (to your headphones only) and Add."""

    def __init__(self, p: packs.Pack, can_hear: bool, parent=None):
        super().__init__(parent)
        self.pack = p
        self.setWindowTitle(p.name)
        self.setMaximumWidth(620)
        self.setMinimumWidth(560)   # three pads a row with room for a meme's name
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        art = art_label(p.emoji, ART_BIG)
        head.addWidget(art, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.name = QLabel(p.name)
        self.name.setObjectName("helptitle")
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.name.setWordWrap(True)
        names.addWidget(self.name)
        self.meta = hint_label(meta_line(p))
        self.meta.setTextFormat(Qt.TextFormat.PlainText)
        names.addWidget(self.meta)
        names.addStretch(1)
        head.addLayout(names, 1)
        v.addLayout(head)
        if p.description:
            about = QLabel(p.description)
            about.setTextFormat(Qt.TextFormat.PlainText)
            about.setWordWrap(True)
            v.addWidget(about)
        if p.categories:
            cats = hint_label(_("Categories: {names}", names=", ".join(p.categories)))
            cats.setTextFormat(Qt.TextFormat.PlainText)
            v.addWidget(cats)
        if p.links:
            v.addWidget(hint_label(_(
                "Its sounds are downloaded straight from Myinstants when you add it: Onion "
                "Board doesn't keep a copy. A sound that's gone from there is skipped.")))
        # a few of its sounds as pads (packs.samples): placeholders until they arrive,
        # so nothing grows under the mouse
        self.listen = QWidget()
        lv = QVBoxLayout(self.listen)
        lv.setContentsMargins(0, 4, 0, 0)
        lv.setSpacing(8)
        lv.addWidget(section_label(_("Hear a few first")))
        self.listen_hint = hint_label(_("Only you hear these."))
        lv.addWidget(self.listen_hint)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.samples: list[SampleButton] = []
        for i in range(packs.SAMPLES):
            b = SampleButton()
            b.setMinimumHeight(PAD_H)
            grid.addWidget(b, i // SAMPLE_COLS, i % SAMPLE_COLS)
            self.samples.append(b)
        lv.addLayout(grid)
        v.addWidget(self.listen)
        self.listen.setVisible(can_hear and has_preview(p))
        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addStretch(1)
        self.btn = _add_button(True)
        self.btn.setDefault(True)
        foot.addWidget(self.btn)
        self.btn_close = QPushButton(_("Close"))
        self.btn_close.clicked.connect(self.reject)
        foot.addWidget(self.btn_close)
        v.addLayout(foot)
        _show_add(self.btn, p)
        fit.watch(self)   # a long translation grows it
        self.fit_height()

    def fit_height(self):
        """As tall as what's in it, at its width (wrapped words included): no gap."""
        lay = self.layout()
        if lay is None:
            return
        lay.activate()
        w = max(self.width(), self.minimumWidth())
        h = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else lay.sizeHint().height()
        self.resize(w, max(h, lay.minimumSize().height()))

    def show_sample(self, found: list[packs.Sample] | None, i: int):
        """Its i-th sample's pad (none found: the pads go, and it says so)."""
        if not found:
            for b in self.samples:
                b.hide()
            self.listen_hint.setText(_("Couldn't load its sounds to try. Adding it still "
                                       "works."))
            QTimer.singleShot(0, self, self.fit_height)   # no gap where the pads were
            return
        b = self.samples[i]
        b.set_sample(found[i] if i < len(found) else None)
        b.setVisible(i < len(found))


class PacksDialog(QDialog):
    """`add(path)` puts a downloaded pack's sounds on the board (the window's own
    import, so it asks and reports the way dropping the zip does). `play` plays a
    pack's sample to your headphones (see Play); without it the samples don't show."""
    _listed = Signal(object, str)              # packs, why the online list wasn't read
    _progress = Signal(str, int, int, bool)    # pack id, done, total, counting links
    _fetched = Signal(object, object, str, int)   # pack, path or None, error, skipped
    _sampled = Signal(object, object)          # sample_key, its samples (None: failed)
    _decoded = Signal(object, object, float, int)   # button, audio or None, gain, serial

    def __init__(self, add: Callable[[Path], None], parent=None, fetch_list: bool = True,
                 play: Play | None = None):
        super().__init__(parent)
        self.setObjectName("packspage")   # (themesheet: in the window, no box of its own)
        fit.watch(self)
        self._add = add
        self._play = play
        self._busy: dict[str, str] = {}   # pack id -> its Add button's words while downloading
        self._shown_pct: dict[str, str] = {}   # ...and a card's, shorter
        self._samples: dict[tuple, list | None] = {}   # sample_key -> its samples (None: failed)
        self._sampling: set[tuple] = set()      # ...being fetched now
        self._preloads: deque[packs.Pack] = deque()   # previews still to fetch, in order
        self._preload_key: tuple | None = None   # the one being fetched now
        self._closed = False
        self.preview: PreviewDialog | None = None   # the open preview
        self._playing: SampleButton | None = None
        self._serial = 0               # the newest sample pressed: an older one never plays
        self._ends = QTimer(self)      # un-lights a sample once it has played out
        self._ends.setSingleShot(True)
        self._ends.timeout.connect(self._stop)
        # the packs shown, in order: a card, or a pack whose card isn't made yet (_step)
        self._slots: list[PackCard | packs.Pack] = []
        self._fills: deque[tuple[PreviewDialog, list | None, int]] = deque()   # pads to fill
        self._stepper = QTimer(self)
        self._stepper.setSingleShot(True)
        self._stepper.setTimerType(Qt.TimerType.PreciseTimer)
        self._stepper.timeout.connect(self._step)
        self._filter = ALL
        self.setWindowTitle(_("Free sound packs"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        # back to the board: the way out, first thing on the page (Escape does it too)
        self.btn_done = QPushButton(_("Back to my sounds"))
        icons.set_icon(self.btn_done, "nav_back")
        self.btn_done.clicked.connect(self.accept)
        head.addWidget(self.btn_done, 0, Qt.AlignmentFlag.AlignVCenter)
        self.bun = bunacts.ActBunny(bunacts.PAT)   # Bun with a parcel, beside the title
        head.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignVCenter)
        title = QLabel(_("Free sound packs"))
        title.setObjectName("helptitle")
        head.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)
        self.btn_share = QPushButton(_("Share a pack"))
        self.btn_share.setProperty("quiet", True)
        icons.set_icon(self.btn_share, "browser")
        self.btn_share.setToolTip(plain_tip(_(
            "Made a pack? Share it: every sound must be CC0 (free for anyone, no credit "
            "needed). Once it's checked, it shows up here for everyone.")))
        self.btn_share.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(packs.SHARE_URL)))
        head.addWidget(self.btn_share, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search packs and sounds"))
        self.search.setAccessibleName(_("Search packs and sounds"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", "muted"),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.setMaximumWidth(SEARCH_MAX_W)
        self.search.textChanged.connect(lambda _t: self._apply_filter())
        lay.addWidget(self.search)
        self.chips_box = QWidget()
        self.chips = Flow(self.chips_box, gap=8)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chip_btns: dict[str, QPushButton] = {}
        lay.addWidget(self.chips_box)
        self.note = hint_label("")
        self.note.hide()
        lay.addWidget(self.note)
        # the grid, or "nothing found" in its place
        self.views = QStackedWidget()
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(0)
        self.grid_box = QWidget()
        self.list = CardGrid(self.grid_box, min_w=CARD_MIN_W, gap=CARD_GAP)
        bv.addWidget(self.grid_box)
        bv.addStretch(1)
        self.scroll_area.setWidget(self.body)
        self.scroll_area.setMinimumSize(280, 200)
        # Keep the cards off the scroll bar
        self.scroll_area.verticalScrollBar().rangeChanged.connect(
            lambda _lo, hi: bv.setContentsMargins(0, 0, 10 if hi > 0 else 0, 0))
        self.views.addWidget(self.scroll_area)
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(12, 24, 12, 24)
        ev.setSpacing(8)
        self.empty_title = section_label("")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setTextFormat(Qt.TextFormat.PlainText)
        ev.addWidget(self.empty_title)
        empty_hint = hint_label(_("Try another word, or show every pack."))
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(empty_hint)
        er = QHBoxLayout()
        er.addStretch(1)
        self.btn_clear = QPushButton(_("Show every pack"))
        self.btn_clear.clicked.connect(self.clear_filter)
        er.addWidget(self.btn_clear)
        er.addStretch(1)
        ev.addLayout(er)
        ev.addStretch(1)
        self.views.addWidget(self.empty)
        lay.addWidget(self.views, 1)
        self._listed.connect(self._show)
        self._progress.connect(self._on_progress)
        self._fetched.connect(self._on_fetched)
        self._sampled.connect(self._on_sampled)
        self._decoded.connect(self._on_decoded)
        self._show(packs.built_in(), "")
        self.resize(780, self._tall())
        if fetch_list and net.allowed(packs.FEATURE):
            threading.Thread(target=self._read_list, daemon=True, name="pack-list").start()
        elif fetch_list:
            self._say(net.off_message(packs.FEATURE))

    def _tall(self) -> int:
        screen = (self.parentWidget() or self).screen()
        room = screen.availableGeometry().height() if screen is not None else 900
        return max(480, min(760, int(room * 0.85)))

    def _say(self, text: str):
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _read_list(self):
        try:
            busy.emit(self._listed, packs.catalog(), "")
        except Exception as e:  # noqa: BLE001 - offline, switched off, a bad list…
            log.info("couldn't read the pack list: %s", e)
            busy.emit(self._listed, None, errors.plain(e))

    # ------------------------------------------------------------------ the list
    def _show(self, found, err: str):
        if self._closed:
            return
        if err:
            busy.toast(self, html.escape(_(
                "Couldn't get the newest list of packs ({error}), so these are the ones "
                "this version knows.", error=err)), "warn")
        if found is None or self._busy:   # don't pull a card out from under a download
            return
        if found == [s.pack if isinstance(s, PackCard) else s for s in self._slots]:
            return   # the online list is the one shown (it usually is): nothing to redo
        # Keep the cards of packs that didn't change and make only the new ones: making
        # all of them again in the open window took about 250 ms of Qt work at once,
        # and the sound playing skipped (the audio threads wait on the UI thread).
        old = {c.pack.id: c for c in self.cards}
        slots: list[PackCard | packs.Pack] = []
        for p in found:
            c = old.get(p.id)
            if c is not None and c.pack == p:
                del old[p.id]
                slots.append(c)
            else:
                slots.append(p)   # its card is made by _step
        while self.list.count():
            self.list.takeAt(0)
        for c in old.values():   # packs no longer on offer (or changed)
            c.hide()
            c.deleteLater()
        self._slots = slots
        for c in self.cards:
            self.list.addWidget(c)
        self._fill_chips(found)
        self._make_next()   # the first new card at once: the page never opens empty
        self._apply_filter()
        self._stepper.start(STEP_GAP_MS)
        self._preload(found)

    @property
    def cards(self) -> list[PackCard]:
        """The packs' cards made so far, in order."""
        return [s for s in self._slots if isinstance(s, PackCard)]

    def card_for(self, pack_id: str) -> PackCard | None:
        return next((c for c in self.cards if c.pack.id == pack_id), None)

    def _step(self):
        """One piece of filling the page: the next pack's card, else one preview pad;
        then a rest (STEP_GAP_MS) for the audio threads before the next one."""
        if self._closed:
            return
        if not self._make_next():
            while self._fills:
                dlg, found, i = self._fills.popleft()
                if dlg is self.preview:   # not closed meanwhile
                    dlg.show_sample(found, i)
                    break
        if self._fills or any(not isinstance(s, PackCard) for s in self._slots):
            self._stepper.start(STEP_GAP_MS)

    def _make_next(self) -> bool:
        """Make the first pack's card still to be made, in its place; False: none left."""
        i = next((i for i, s in enumerate(self._slots) if not isinstance(s, PackCard)), -1)
        if i < 0:
            return False
        p = self._slots[i]
        assert isinstance(p, packs.Pack)
        c = PackCard(p)
        c.opened.connect(lambda card: self.open_pack(card.pack))
        self._insert(sum(isinstance(s, PackCard) for s in self._slots[:i]), c)
        self._slots[i] = c
        if p.id in self._busy:
            busy.set_busy(c.btn, True)
            c.btn.setText(self._shown_pct.get(p.id, "…"))
        c.setVisible(self._shows(p))
        return True

    def _insert(self, at: int, w: QWidget):
        """`w` into the grid at `at` (CardGrid only appends: the rest go after it)."""
        rest = []
        while self.list.count() > at:
            rest.append(self.list.takeAt(at))
        self.list.addWidget(w)
        for item in rest:
            self.list.addItem(item)

    # ------------------------------------------------------------------ filtering
    def _fill_chips(self, found: list[packs.Pack]):
        """All, each kind of pack (most packs first), On my board."""
        tags: dict[str, int] = {}
        for p in found:
            for t in p.tags:
                tags[t] = tags.get(t, 0) + 1
        keys = [ALL, *sorted(tags, key=lambda t: (-tags[t], t.casefold())), MINE]
        if keys == list(self.chip_btns):
            return
        for b in self.chip_btns.values():
            self.chip_group.removeButton(b)
            self.chips.removeWidget(b)
            b.hide()
            b.deleteLater()
        self.chip_btns = {}
        for k in keys:
            # "TV & movies": a lone & is a shortcut marker in a button's text
            b = QPushButton(_("All") if k == ALL else _("On my board") if k == MINE
                            else k.replace("&", "&&"))
            b.setObjectName("filterchip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=k: self.set_filter(k))
            self.chip_group.addButton(b)
            self.chips.addWidget(b)
            self.chip_btns[k] = b
        if self._filter not in self.chip_btns:
            self._filter = ALL
        self.chip_btns[self._filter].setChecked(True)
        self.chips.invalidate()

    def set_filter(self, key: str):
        self._filter = key if key in self.chip_btns else ALL
        self.chip_btns[self._filter].setChecked(True)
        self._apply_filter()

    def clear_filter(self):
        self.search.clear()
        self.set_filter(ALL)

    def _words(self) -> list[str]:
        return self.search.text().casefold().split()

    def _shows(self, p: packs.Pack) -> bool:
        if self._filter == MINE and not p.downloaded():
            return False
        if self._filter not in (ALL, MINE) and self._filter not in p.tags:
            return False
        return matches(p, self._words())

    def shown(self) -> list[packs.Pack]:
        """The packs the search and chip leave, made or not."""
        return [s.pack if isinstance(s, PackCard) else s for s in self._slots
                if self._shows(s.pack if isinstance(s, PackCard) else s)]

    def _apply_filter(self):
        for c in self.cards:
            c.setVisible(self._shows(c.pack))
        any_shown = bool(self.shown())
        if not any_shown:
            q = self.search.text().strip()
            self.empty_title.setText(_("No packs match “{text}”", text=q) if q
                                     else _("No packs here yet"))
        self.views.setCurrentIndex(0 if any_shown else 1)

    # ------------------------------------------------------------------ the preview
    def open_pack(self, p: packs.Pack):
        """A pack's preview, over the page (a card's Preview, or the card itself)."""
        self.close_pack()
        dlg = PreviewDialog(p, self._play is not None, self)
        self.preview = dlg
        if p.id in self._busy:
            busy.set_busy(dlg.btn, True)
            dlg.btn.setText(self._busy[p.id])
        dlg.btn.clicked.connect(lambda: self.add(p))
        for b in dlg.samples:
            b.clicked.connect(lambda on, b=b: self.hear(b, on))
        dlg.finished.connect(lambda _r, d=dlg: self._preview_closed(d))
        dlg.open()
        if self._play is not None and has_preview(p):
            key = sample_key(p)
            if key in self._samples:
                self._fill(dlg, self._samples[key])
            elif key not in self._sampling:
                self._fetch_samples(p)

    def close_pack(self):
        if self.preview is not None:
            self.preview.reject()

    def _preview_closed(self, dlg: PreviewDialog):
        if self.preview is dlg:
            self.preview = None
            self._stop()
        self._fills = deque(f for f in self._fills if f[0] is not dlg)
        dlg.deleteLater()

    def _fill(self, dlg: PreviewDialog, found: list | None):
        """Its samples onto the preview's pads, a pad a step (_step)."""
        for i in range(len(dlg.samples) if found else 1):
            self._fills.append((dlg, found, i))
        if not self._stepper.isActive():
            self._stepper.start(STEP_GAP_MS)

    # ------------------------------------------------------------------ samples
    def _preload(self, found: list[packs.Pack]):
        """Every pack's samples fetched in the background, one pack at a time, as soon
        as the page is up: a preview then opens with its pads ready, not loading. Each
        is fetched once ever (kept on disk), and a failure just waits for the preview."""
        if self._play is None:
            return
        self._preloads = deque(p for p in found if has_preview(p)
                               and sample_key(p) not in self._samples)
        if self._preload_key is None:
            self._preload_next()

    def _preload_next(self):
        self._preload_key = None
        while self._preloads and not self._closed:
            p = self._preloads.popleft()
            key = sample_key(p)
            if key not in self._samples and key not in self._sampling:
                self._preload_key = key
                self._fetch_samples(p)
                return

    def _fetch_samples(self, p: packs.Pack):
        """A pack's samples, fetched once (kept on disk: asking again is free)."""
        key = sample_key(p)
        self._sampling.add(key)

        def run():
            try:
                found = packs.samples(p, lambda: self._closed)
            except Exception as e:  # noqa: BLE001 - offline, switched off, a bad file
                log.info("no samples for pack %s: %s", p.id, e)
                found = None
            busy.emit(self._sampled, key, found)
        threading.Thread(target=run, daemon=True, name="pack-samples").start()

    def _on_sampled(self, key, found):
        """A pack's samples arrived: onto its preview now, if it's open."""
        self._sampling.discard(key)
        self._samples[key] = found or None
        if self._closed:
            return
        dlg = self.preview
        if dlg is not None and sample_key(dlg.pack) == key:
            self._fill(dlg, found)
        if key == self._preload_key:   # the next pack's, now this one's are in
            self._preload_next()

    def hear(self, b: SampleButton, on: bool):
        """A sample pressed: play it (decoded off the UI thread), or stop it."""
        if self._playing is not None and self._playing is not b:
            self._stop()
        self._serial += 1
        self._ends.stop()
        if not on or b.sample is None or self._play is None:
            self._stop()
            return
        self._playing = b
        smp, serial = b.sample, self._serial

        def run():
            try:
                data = library.decode(str(smp.audio))
                busy.emit(self._decoded, b, data, library.level_gain(data), serial)
            except Exception:  # noqa: BLE001 - a file gone or unreadable: no sound, no crash
                log.warning("couldn't decode pack sample %s", smp.audio, exc_info=True)
                busy.emit(self._decoded, b, None, 1.0, serial)
        threading.Thread(target=run, daemon=True, name="pack-sample").start()

    def _on_decoded(self, b: SampleButton, data, gain: float, serial: int):
        if self._closed or serial != self._serial or self._play is None:
            return   # closed, or another sample (or stop) pressed meanwhile
        if data is None or not self._play(data, gain):
            self._stop()
            if data is not None:
                msg = _("Pick your headphones in Settings → Audio to hear the samples.")
                self._say(msg)
                if self.preview is not None:
                    busy.toast(self.preview, html.escape(msg), "warn")
            return
        self._ends.start(int(len(data) / SR * 1000) + 150)

    def _stop(self):
        """Stop the sample playing, and un-light its button."""
        b, self._playing = self._playing, None
        self._ends.stop()
        if b is None:
            return
        try:
            b.setChecked(False)
        except RuntimeError:   # its preview was closed meanwhile
            pass
        if self._play is not None:
            self._play(None, 1.0)

    # ------------------------------------------------------------------ adding
    def _buttons(self, pack_id: str) -> list[QPushButton]:
        """The Add buttons of a pack: its card's, and its preview's while it's open."""
        out = [c.btn for c in self.cards if c.pack.id == pack_id]
        if self.preview is not None and self.preview.pack.id == pack_id:
            out.append(self.preview.btn)
        return out

    def add(self, p: packs.Pack | PackCard):
        if isinstance(p, PackCard):
            p = p.pack
        if p.id in self._busy:
            return
        if not net.allowed(packs.FEATURE) and not p.downloaded():
            why = net.off_message(packs.FEATURE)
            self._say(why)
            # the note above may already say it: the press itself gets an answer too
            busy.toast(self.preview or self, html.escape(why), "error")
            return
        self._busy[p.id] = _("Downloading…")
        self.bun.set_act(bunacts.RUN)   # running with it till it lands
        for b in self._buttons(p.id):
            busy.set_busy(b, True)
        self._show_progress(p.id)

        def run():
            try:
                if p.links:
                    path, skipped = packs.download_links(
                        p, lambda done, total: busy.emit(self._progress, p.id, done, total,
                                                         True),
                        lambda: self._closed)
                else:
                    path, skipped = packs.download(
                        p, lambda done, total: busy.emit(self._progress, p.id, done, total,
                                                         False),
                        lambda: self._closed), 0
                busy.emit(self._fetched, p, path, "", skipped)
            except updates.UpdateError as e:
                busy.emit(self._fetched, p, None, str(e), 0)
            except Exception as e:  # noqa: BLE001 - never a crash
                log.exception("pack %s download failed", p.id)
                busy.emit(self._fetched, p, None, errors.plain(e), 0)
        threading.Thread(target=run, daemon=True, name="pack-download").start()

    def _on_progress(self, pack_id: str, done: int, total: int, links: bool):
        if self._closed or pack_id not in self._busy:
            return
        self._busy[pack_id] = (
            _("{done} of {total}", done=done, total=total) if links and total else
            _("Downloading {pct}%", pct=done * 100 // total) if total else _("Downloading…"))
        self._shown_pct[pack_id] = (_("{done} of {total}", done=done, total=total)
                                    if links and total else
                                    _("{pct}%", pct=done * 100 // total) if total else "…")
        self._show_progress(pack_id)

    def _show_progress(self, pack_id: str):
        """A download's progress on its Add buttons: the preview's in words, a card's
        (half a card wide) just the number."""
        for b in self._buttons(pack_id):
            try:
                b.setText(self._busy[pack_id] if b.objectName() == "primary"
                          else self._shown_pct.get(pack_id, "…"))
            except RuntimeError:   # its card was remade meanwhile
                pass

    def _on_fetched(self, p: packs.Pack, path, err: str, skipped: int):
        self._busy.pop(p.id, None)
        self._shown_pct.pop(p.id, None)
        if self._closed:
            return
        if not self._busy:
            self.bun.set_act(bunacts.PAT)
        for b in self._buttons(p.id):
            busy.set_busy(b, False)
            _show_add(b, p, short=b.objectName() != "primary")
        if path is None:
            busy.toast(self.preview or self, html.escape(_(
                "Couldn't download {name}: {error}", name=p.name, error=err)), "error")
            return
        self._say("")
        self.close_pack()   # added: the board's own import reports it from here
        self._add(Path(path))
        self.bun.play(bunacts.OPEN)
        for b in self._buttons(p.id):
            busy.flash(b, _("✓ Added"))
        if skipped:
            busy.toast(self, html.escape(ngettext(
                "{n} sound is gone from Myinstants, so it was skipped.",
                "{n} sounds are gone from Myinstants, so they were skipped.", skipped)),
                "warn")
        if self._filter == MINE:
            self._apply_filter()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.preview is not None:
            self.close_pack()
            return
        super().keyPressEvent(e)

    def done(self, r: int):
        self.close_pack()
        self._stop()
        self._stepper.stop()
        self._closed = True   # a download still going stops at its next chunk
        super().done(r)
