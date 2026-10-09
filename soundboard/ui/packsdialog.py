"""The Sounds tab's *Free packs* window: ready-made boards anyone can add in one click
(soundboard.packs), and where to share one of your own."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from soundboard import errors, net, packs, updates
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import hint_label
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)


def size_text(n: int) -> str:
    return _("{n} MB", n=max(1, round(n / 1e6))) if n else ""


def meta_line(p: packs.Pack) -> str:
    """"67 sounds · 28 MB · CC0 · by Onion Board"."""
    bits = [ngettext("{n} sound", "{n} sounds", p.sounds) if p.sounds else "",
            size_text(p.size), p.license,
            _("by {name}", name=p.author) if p.author else ""]
    return " · ".join(b for b in bits if b)


class PackCard(QFrame):
    def __init__(self, pack: packs.Pack):
        super().__init__()
        self.pack = pack
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        emoji = QLabel(pack.emoji)
        emoji.setStyleSheet("font-size: 22pt; background: transparent;")
        top.addWidget(emoji, 0, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name = QLabel(pack.name)
        self.name.setTextFormat(Qt.PlainText)
        self.name.setStyleSheet("font-weight: 600; font-size: 11pt; background: transparent;")
        names.addWidget(self.name)
        self.meta = QLabel(meta_line(pack))
        self.meta.setObjectName("muted")
        self.meta.setTextFormat(Qt.PlainText)
        self.meta.setWordWrap(True)
        names.addWidget(self.meta)
        top.addLayout(names, 1)
        self.btn = QPushButton()
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(lambda: self.window().add(self))
        top.addWidget(self.btn, 0, Qt.AlignTop)
        v.addLayout(top)
        if pack.description:
            about = hint_label(pack.description)
            about.setTextFormat(Qt.PlainText)
            v.addWidget(about)
        if pack.categories:
            cats = hint_label(_("Categories: {names}", names=", ".join(pack.categories)))
            cats.setTextFormat(Qt.PlainText)
            v.addWidget(cats)
        self.show_idle()

    def show_idle(self):
        added = self.pack.downloaded()
        self.btn.setText(_("Add again") if added else _("Add to my board"))
        self.btn.setToolTip(
            _("Adds its sounds again; ones already on your board are skipped") if added else
            _("Downloads the pack ({size}) and puts its sounds on your board, each "
              "category as its own tab", size=size_text(self.pack.size) or "?"))
        icons.set_icon(self.btn, "check" if added else "download", "on_accent")


class PacksDialog(QDialog):
    """`add(path)` puts a downloaded pack's sounds on the board (the window's own
    import, so it asks and reports the way dropping the zip does)."""
    _listed = Signal(object, str)              # packs, why the online list wasn't read
    _progress = Signal(object, int, int)       # card, done, total
    _fetched = Signal(object, object, str)     # card, path or None, error

    def __init__(self, add: Callable[[Path], None], parent=None, fetch_list: bool = True):
        super().__init__(parent)
        fit.watch(self)
        self._add = add
        self._busy: set[str] = set()   # pack ids downloading now
        self._closed = False
        self.setWindowTitle(_("Free sound packs"))
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(_(
            "Ready-made boards, free to use anywhere: in games, streams and videos. Add one "
            "and its sounds land on your board, each category as its own tab.")))
        self.note = hint_label("")
        self.note.hide()
        lay.addWidget(self.note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.list = QVBoxLayout(self.body)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(8)
        self.scroll.setWidget(self.body)
        self.scroll.setMinimumSize(440, 260)
        lay.addWidget(self.scroll, 1)
        share = QFrame()
        share.setObjectName("card")
        sv = QHBoxLayout(share)
        sv.setContentsMargins(14, 10, 14, 10)
        sv.setSpacing(10)
        sv.addWidget(hint_label(_(
            "Made a pack? Share it: every sound must be CC0 (free for anyone, no credit "
            "needed). Once it's checked, it shows up here for everyone.")), 1)
        self.btn_share = QPushButton(_("Share a pack"))
        icons.set_icon(self.btn_share, "browser")
        self.btn_share.setToolTip(_("Opens the sharing form on GitHub in your browser"))
        self.btn_share.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(packs.SHARE_URL)))
        sv.addWidget(self.btn_share, 0, Qt.AlignVCenter)
        lay.addWidget(share)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.cards: list[PackCard] = []
        self._listed.connect(self._show)
        self._progress.connect(self._on_progress)
        self._fetched.connect(self._on_fetched)
        self._show(packs.built_in(), "")
        if fetch_list and net.allowed(packs.FEATURE):
            threading.Thread(target=self._read_list, daemon=True, name="pack-list").start()
        elif fetch_list:
            self._say(net.off_message(packs.FEATURE))

    def _say(self, text: str):
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _read_list(self):
        try:
            self._listed.emit(packs.catalog(), "")
        except Exception as e:  # noqa: BLE001 - offline, switched off, a bad list…
            log.info("couldn't read the pack list: %s", e)
            self._listed.emit(None, errors.plain(e))

    def _show(self, found, err: str):
        if self._closed:
            return
        if err:
            self._say(_("Couldn't get the newest list of packs ({error}), so these are "
                        "the ones this version knows.", error=err))
        if found is None or self._busy:   # don't pull a card out from under a download
            return
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.cards = [PackCard(p) for p in found]
        for c in self.cards:
            self.list.addWidget(c)
        self.list.addStretch(1)

    def add(self, card: PackCard):
        p = card.pack
        if p.id in self._busy:
            return
        if not net.allowed(packs.FEATURE) and not p.downloaded():
            self._say(net.off_message(packs.FEATURE))
            return
        self._busy.add(p.id)
        busy.set_busy(card.btn, True)
        card.btn.setText(_("Downloading…"))

        def run():
            try:
                path = packs.download(
                    p, lambda done, total: self._progress.emit(card, done, total),
                    lambda: self._closed)
                self._fetched.emit(card, path, "")
            except updates.UpdateError as e:
                self._fetched.emit(card, None, str(e))
            except Exception as e:  # noqa: BLE001 - never a crash
                log.exception("pack %s download failed", p.id)
                self._fetched.emit(card, None, errors.plain(e))
        threading.Thread(target=run, daemon=True, name="pack-download").start()

    def _on_progress(self, card: PackCard, done: int, total: int):
        try:
            card.btn.setText(_("Downloading {pct}%", pct=done * 100 // total) if total
                             else _("Downloading…"))
        except RuntimeError:   # the window closed meanwhile
            pass

    def _on_fetched(self, card: PackCard, path, err: str):
        self._busy.discard(card.pack.id)
        if self._closed:
            return
        busy.set_busy(card.btn, False)
        card.show_idle()
        if path is None:
            self._say(_("Couldn't download {name}: {error}", name=card.pack.name, error=err))
            return
        self._say("")
        self._add(Path(path))
        busy.flash(card.btn, _("✓ Added"))

    def done(self, r: int):
        self._closed = True   # a download still going stops at its next chunk
        super().done(r)
