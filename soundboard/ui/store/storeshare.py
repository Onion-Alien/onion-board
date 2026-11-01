"""The Store tab's *Share a sound* window (`ShareDialog`): a file or a link, then a thank-you."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from soundboard.core import errors, usage
from soundboard.online import store
from soundboard.i18n import _
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.kit.panel import hint_label

log = logging.getLogger("soundboard.ui.store.storetab")


def error_text(e: BaseException) -> str:
    """A failed store call in words: the store's own message, else the error made plain."""
    return str(e) if isinstance(e, store.StoreError) else errors.plain(e)


def _title(text: str) -> QLabel:
    """A small dialog's one big line (as the Send feedback box's)."""
    lab = QLabel(text)
    f = lab.font()
    f.setPointSizeF(f.pointSizeF() * 1.3)
    f.setBold(True)
    lab.setFont(f)
    lab.setWordWrap(True)
    return lab


class ShareDialog(QDialog):
    """Share a sound with the store: a file (name it, agree it's yours to give away as
    CC0) or a link to a video or sound site (only the link is kept). Two pages: the
    form, then "Thanks, it'll show once it's checked". `link` (and `name`) open it on
    the link, filled in: a sound of yours downloaded from one."""
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work
    _sent = Signal(str)   # worker -> UI: the error, "" when it went

    def __init__(self, install: str, parent=None, link: str = "", name: str = ""):
        super().__init__(parent)
        self.install = install
        self.path = ""
        self.sent = False   # shared: the thanks page is up
        self._closed = False
        self.setWindowTitle(_("Share a sound"))
        self.setMaximumWidth(520)
        self._sent.connect(self._on_sent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        self.pages = QStackedWidget()
        lay.addWidget(self.pages)

        form = QWidget()
        v = QVBoxLayout(form)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_title(_("Share a sound with everyone")))
        # a file or a link: two choice tiles, the picked one in the accent
        modes = QHBoxLayout()
        modes.setSpacing(8)
        self.mode_btns: dict[str, QPushButton] = {}
        for key, text, icon in (("file", _("A file"), "folder"), ("link", _("A link"), "link")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            icons.set_icon(b, icon, "text", "on_accent")
            b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            modes.addWidget(b)
            self.mode_btns[key] = b
        modes.addStretch(1)
        v.addLayout(modes)
        self.mode_hint = hint_label("")
        v.addWidget(self.mode_hint)
        self.file_box = QWidget()
        pick = QHBoxLayout(self.file_box)
        pick.setContentsMargins(0, 0, 0, 0)
        pick.setSpacing(8)
        self.btn_file = QPushButton(_("Choose a file"))
        icons.set_icon(self.btn_file, "folder")
        self.btn_file.clicked.connect(self.choose)
        pick.addWidget(self.btn_file)
        self.file_lbl = QLabel(_("No file picked"))
        self.file_lbl.setObjectName("hint")
        self.file_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        pick.addWidget(self.file_lbl, 1)
        v.addWidget(self.file_box)
        self.link = QLineEdit(link)
        self.link.setPlaceholderText(_("Paste a link: https://www.youtube.com/watch?v=…"))
        self.link.setAccessibleName(_("Link"))
        self.link.textChanged.connect(self._ready)
        v.addWidget(self.link)
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.name.setPlaceholderText(_("Name (what it is)"))
        self.name.setAccessibleName(_("Name"))
        self.name.textChanged.connect(self._ready)
        v.addWidget(self.name)
        self.tags = QLineEdit()
        self.tags.setMaxLength(200)
        self.tags.setPlaceholderText(_("Tags, with commas (optional): meme, horn, game"))
        self.tags.setAccessibleName(_("Tags"))
        self.tags.textChanged.connect(self._ready)
        v.addWidget(self.tags)
        self.agree = QCheckBox(_("This sound is mine to give away"))
        self.agree.toggled.connect(self._ready)
        v.addWidget(self.agree)
        self.terms = terms = hint_label(_(
            "I made or recorded it myself, and I give it away as CC0: anyone may use it for "
            "anything, for free. No songs, clips from shows or games, or other people's "
            "sounds: those are removed.") + " " + _(
            "Is a sound in the store yours? Email {email} and it comes down.",
            email=store.CONTACT))
        terms.setContentsMargins(26, 0, 0, 4)   # under the box's text, not its tick
        terms.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)   # the email
        v.addWidget(terms)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setObjectName("hint")
        self.error.hide()
        v.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_send = QPushButton(_("Share"))
        self.btn_send.setObjectName("primary")
        self.btn_send.clicked.connect(self.send)
        buttons.addWidget(self.btn_send)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        v.addLayout(buttons)
        v.addStretch(1)   # room left over (the other choice's parts hidden) goes below
        self.pages.addWidget(form)

        done = QWidget()
        dv = QVBoxLayout(done)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(10)
        dv.addWidget(_title(_("Thanks for sharing!")))
        dv.addWidget(hint_label(_("It shows in the store once it's been checked, usually "
                                  "within a few days.")))
        db = QHBoxLayout()
        ok = QPushButton(_("Done"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        db.addWidget(ok)
        db.addStretch(1)
        dv.addLayout(db)
        dv.addStretch(1)
        self.pages.addWidget(done)
        if name:
            self.name.setText(name[:60])
        self.set_mode("link" if link else "file")
        fit.watch(self)

    def set_mode(self, mode: str):
        """Share a file, or a link."""
        self.mode = "link" if mode == "link" else "file"
        is_link = self.mode == "link"
        self.mode_btns[self.mode].setChecked(True)
        self.file_box.setVisible(not is_link)
        self.agree.setVisible(not is_link)
        self.terms.setVisible(not is_link)
        self.link.setVisible(is_link)
        self.mode_hint.setText(
            _("A YouTube, TikTok, SoundCloud or other video link. Only the link is kept: "
              "whoever adds it gets it from that site. It shows once it's been checked.")
            if is_link else
            _("MP3, OGG, WAV or FLAC, up to 4 MB. It shows in the store once it's been "
              "checked."))
        self._show_error("")
        self._ready()
        if self.isVisible():   # the other choice's parts went: as tall as this one needs
            QTimer.singleShot(0, self, self._shrink)

    def sizeHint(self) -> QSize:
        return QSize(500, super().sizeHint().height())

    def choose(self):
        path, _f = QFileDialog.getOpenFileName(
            self, _("Choose a sound to share"), str(Path.home()),
            _("Sounds") + " (*.mp3 *.ogg *.wav *.flac)")
        if path:
            self.set_file(path)

    def set_file(self, path: str):
        self.path = path
        self.file_lbl.setText(Path(path).name)
        self.file_lbl.setToolTip(path)
        if not self.name.text().strip():
            self.name.setText(Path(path).stem.replace("_", " ")[:60])
        why = store.check_file(path)
        self._show_error(why)
        self._ready()

    def _show_error(self, text: str):
        self.error.setText(text)
        self.error.setVisible(bool(text))
        if text:
            from soundboard.ui.kit import theme
            theme.set_tone(self.error, "error")

    def _ready(self):
        if not hasattr(self, "btn_send"):   # (still being built)
            return
        # a name or tags the store would refuse say so as they're typed
        words = store.check_words(self.name.text(), self.tags.text())
        if getattr(self, "mode", "file") == "link":
            url = self.link.text().strip()
            ok = bool(store.link_ok(url) and self.name.text().strip() and not words)
            why = words or _("Paste a link and name it first")
            # a pasted link the store won't take says so at once
            self._show_error(words if not url or store.link_ok(url) else _(
                "The store takes links to YouTube, TikTok, SoundCloud and other video "
                "and sound sites."))
        else:
            bad_file = store.check_file(self.path) if self.path else ""
            ok = bool(self.path and self.name.text().strip() and self.agree.isChecked()
                      and not bad_file and not words)
            why = words or _("Pick a file, name it and tick the box first")
            self._show_error(bad_file or words)
        busy.set_busy(self.btn_send, not ok)   # greyed until it can go (never disabled)
        self.btn_send.setToolTip("" if ok else why)

    def send(self):
        if busy.is_busy(self.btn_send):
            return
        release = busy.hold(self.btn_send, _("Sharing…"))
        self._release = release
        path, name, tags, install = self.path, self.name.text(), self.tags.text(), self.install
        link = self.link.text().strip() if self.mode == "link" else ""

        def run():
            try:
                if link:
                    store.share_link(install, link, name, tags)
                else:
                    store.upload(install, path, name, tags)
                busy.emit(self._sent, "")
            except Exception as e:  # noqa: BLE001
                log.info("couldn't share a sound: %s", e)
                busy.emit(self._sent, error_text(e))
        threading.Thread(target=run, daemon=True, name="store-share").start()

    def _on_sent(self, err: str):
        if self._closed:
            return
        self._release()
        if err:
            self._show_error(err)
            return
        usage.used("store-shared")
        self.sent = True
        # the stack is as tall as its tallest page: the form goes, so the short thanks
        # page shrinks the window (there's no way back to the form from it)
        form = self.pages.widget(0)
        assert form is not None
        self.pages.setCurrentIndex(1)
        self.pages.removeWidget(form)
        form.hide()
        form.deleteLater()
        lay = self.layout()
        assert lay is not None
        # measured once Qt has given the form's room back (after this event)
        QTimer.singleShot(0, self, self._shrink)

    def _shrink(self):
        """As short as the thanks page: Qt keeps a shown dialog's height, so the
        height is pinned to what's needed for a moment, then let go."""
        lay = self.layout()
        if lay is None:
            return
        lay.activate()
        h = lay.totalMinimumSize().height()
        self.setFixedHeight(h)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.resize(self.width(), h)

    def done(self, r: int):
        self._closed = True
        super().done(r)
