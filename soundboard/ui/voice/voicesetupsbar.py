"""The Voice tab's Mixes tab: your saved mixes of a voice changer voice, an AI voice and
a language (voicesetups), as cards that list what's in them. Click one to turn the whole
mix on; the + card (Save what's on) keeps what you have on now; Import a code adds one a
friend sent (any share code). The tab shows once you have a mix (the Voice tab's own Save what's on,
beside its tabs, makes the first). The same mixes go on sounds from Edit sound →
Effects → Voice."""
from __future__ import annotations

import html
import re
from collections.abc import Callable

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QShowEvent
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard.core import usage
from soundboard.mic import voicesetups
from soundboard.i18n import _
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.panel import Flow, hint_label
from soundboard.ui.voice.voicetiles import TILE_ART, VoiceTile

UNDO_MS = 10000
NOTE_MS = 6000   # a "Saved" / "is on" line goes again after this
CARD_W = 172     # px: a combo's card (two fit side by side in the narrowest window)
PART_ART = 26    # px: the picture of one part of a combo


def _wraps(text: str) -> str:
    """A very long word may break anywhere, or the card would cut it off."""
    return re.sub(r"\S{15,}", lambda m: "\u200b".join(m.group()), text)


class ComboCard(QPushButton):
    """A saved combo's card: its name, then each thing in it, a picture and words, so
    it can't be taken for a single voice. `even_to`: the height of its row's tallest
    card. (Its height is its size hint, not a fixed one: a change of theme puts the
    style sheet's minimum height for buttons back, and Flow lays cards out by hint.)"""

    def __init__(self, name: str, parts: list[tuple[QIcon, str]]):
        super().__init__()
        self.even_to = 0
        self.setObjectName("combocard")
        self.setFixedWidth(CARD_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(name)
        v = self.box = QVBoxLayout(self)
        v.setContentsMargins(10, 9, 10, 10)
        v.setSpacing(6)
        title = QLabel(_wraps(name))
        title.setObjectName("comboname")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        v.addWidget(title)
        for icon, words in parts:
            row = QHBoxLayout()
            row.setSpacing(6)
            pic = QLabel()
            pic.setFixedSize(PART_ART, PART_ART)
            pic.setPixmap(icon.pixmap(QSize(PART_ART, PART_ART), self.devicePixelRatioF()))
            pic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
            text = QLabel(_wraps(words))
            text.setObjectName("combopart")
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            text.setMinimumHeight(PART_ART)
            text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(text, 1)
            v.addLayout(row)
        v.addStretch(1)

    def wanted_height(self) -> int:
        for label in self.findChildren(QLabel):
            label.ensurePolished()
        return self.box.totalHeightForWidth(CARD_W)

    def sizeHint(self) -> QSize:
        return QSize(CARD_W, max(self.wanted_height(), self.even_to))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class SetupsBar(QWidget):
    """The Mixes tab's cards. `capture()` gives the setup that's on now ({} if nothing
    is), `apply(setup)` turns one on, `icon_for(setup)` its picture, `describe(setup)`
    its parts in words, `parts_of(setup)` each part's picture and words;
    `copy_code(name)` puts one on the clipboard as a share code
    (False if it can't be one) and `import_code()` asks for a code and adds what's in
    it. `head_tools`: Import a code and Share, for the card's head. `changed`: a mix
    was added, renamed or deleted."""
    changed = Signal()

    def __init__(self, store: voicesetups.Store, capture: Callable[[], dict],
                 apply: Callable[[dict], None], icon_for: Callable[[dict], QIcon],
                 describe: Callable[[dict], str],
                 parts_of: Callable[[dict], list[tuple[QIcon, str]]],
                 copy_code: Callable[[str], bool] | None = None,
                 import_code: Callable[[], object] | None = None):
        super().__init__()
        self.store, self.capture, self.apply = store, capture, apply
        self.icon_for, self.describe, self.parts_of = icon_for, describe, parts_of
        self.copy_code = copy_code
        self._undo: tuple[str, dict] | None = None
        self.share: Callable[[str], None] | None = None   # Share to the store (its name)
        self.title = QLabel(_("Voice combos"))   # the card's head shows it (VoiceCards._section)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(hint_label(_("One click turns a whole combo on: its voice changer voice, "
                                 "AI voice and language.")))
        self.cards = QWidget()
        self.flow = Flow(self.cards, gap=8)
        v.addWidget(self.cards)
        # the + card after the last mix: keeps what's on now (as AI voices' Make your own)
        self.btn_save = VoiceTile(_("Save what's on"))
        self.btn_save.setCheckable(False)
        self.btn_save.star.hide()
        icons.set_icon(self.btn_save, "plus", "muted", size=TILE_ART, gap=False)
        self.btn_save.setIconSize(QSize(TILE_ART, TILE_ART))
        self.btn_save.setProperty("combo", True)
        self.btn_save.setFixedWidth(CARD_W)
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setToolTip(_("Keep the voice changer voice, AI voice and language you "
                                   "have on now under a name: one click turns them all on "
                                   "again, and you can put it on sounds (Edit sound → "
                                   "Effects → Voice)"))
        self.btn_save.clicked.connect(self._save)
        # Import a code and Share: at the far end of the card's head
        self.head_tools = QWidget()
        ht = QHBoxLayout(self.head_tools)
        ht.setContentsMargins(0, 0, 0, 0)
        ht.setSpacing(6)
        self.btn_import = QPushButton(_("Import a code"), self.head_tools)
        self.btn_import.setObjectName("voicecat")
        icons.set_icon(self.btn_import, "download", "muted")
        self.btn_import.setToolTip(_("Add a voice someone sent you as a code (it starts "
                                     "with “OB”)"))
        if import_code is not None:
            self.btn_import.clicked.connect(lambda: import_code())
        self.btn_import.setVisible(import_code is not None)
        ht.addWidget(self.btn_import)
        self.btn_share = QPushButton(_("Share"), self.head_tools)
        self.btn_share.setObjectName("voicecat")
        icons.set_icon(self.btn_share, "upload", "muted")
        self.btn_share.setToolTip(_("Share one of your voice combos: to the store for "
                                    "everyone, or as a code to send a friend"))
        self.btn_share.clicked.connect(self._share_menu)
        ht.addWidget(self.btn_share)
        under = QHBoxLayout()
        under.setSpacing(8)
        self.note = QLabel()
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        under.addWidget(self.note, 1)
        self.btn_undo = QPushButton(_("Undo"))
        self.btn_undo.clicked.connect(self._undo_delete)
        self.btn_undo.hide()
        under.addWidget(self.btn_undo)
        v.addLayout(under)
        v.addStretch(1)
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(lambda: self._say(""))
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.timeout.connect(self._forget_undo)
        self.buttons: dict[str, ComboCard] = {}
        self.note.hide()
        store.listeners.append(self.refresh)
        self.destroyed.connect(lambda *_a: self._unlisten())
        self.refresh()

    def _unlisten(self):
        try:
            self.store.listeners.remove(self.refresh)
        except ValueError:
            pass

    def refresh(self):
        for b in self.buttons.values():
            self.flow.removeWidget(b)
            b.hide()
            b.deleteLater()
        self.buttons = {}
        self.flow.removeWidget(self.btn_save)
        for name, setup in self.store.setups.items():
            b = ComboCard(name, self.parts_of(setup))
            b.setToolTip(_("{parts}. Click to turn it all on; right-click to delete it.",
                           parts=self.describe(setup)))
            b.clicked.connect(lambda __=False, n=name: self._use(n))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, n=name, w=b: self._menu(n, w.mapToGlobal(pos)))
            self.flow.addWidget(b)
            self.buttons[name] = b
        self.flow.addWidget(self.btn_save)
        self.btn_save.show()
        self._even_cards()
        self.changed.emit()

    def _even_cards(self):
        """Every card as tall as the tallest, so the rows line up."""
        tall = max((b.wanted_height() for b in self.buttons.values()), default=0)
        tall = max(tall, self.btn_save.sizeHint().height())
        for b in self.buttons.values():
            b.even_to = tall
            b.updateGeometry()
        self.btn_save.setFixedHeight(tall)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self._even_cards()   # (the theme's text sizes reach the cards once they're in the tab)

    def _say(self, text: str, keep: bool = False):
        """A line under the cards; it goes again after NOTE_MS unless `keep`. While the
        Mixes tab isn't showing (Save what's on beside the tabs) a corner card says it."""
        if text and not self.isVisible() and self.window() is not self:
            busy.toast(self.window(), html.escape(text), "ok")
        self.note.setText(text)
        self.note.setVisible(bool(text) or not self.btn_undo.isHidden())
        if text and not keep:
            self._note_timer.start(NOTE_MS)

    def _use(self, name: str):
        setup = self.store.setups.get(name)
        if setup is not None:
            self.apply(setup)
            self._say(_("“{name}” is on.", name=name))

    def _save(self):
        setup = self.capture()
        if not setup:
            self._say(_("Nothing is on: turn on a voice changer voice, an AI voice "
                        "or a language first."))
            return
        name, ok = QInputDialog.getText(self, _("Save what's on"), _("Name"),
                                        text=setup.get("name", ""))
        if not ok or not voicesetups.clean_name(name):
            return
        saved = self.store.put(name, setup)
        if saved:
            usage.used("voice-setup-saved")
        self._say(_("Saved “{name}”.", name=saved) if saved
                  else _("Couldn't save it (100 voice combos at most)."))

    def _menu(self, name: str, at):
        m = QMenu(self)
        m.addAction(icons.icon("edit"), _("Rename"), lambda: self._rename(name))
        if self.copy_code is not None:
            m.addAction(icons.icon("copy"), _("Copy share code"), lambda: self._copy(name))
        if self.share is not None:
            m.addAction(icons.icon("upload"), _("Share to the store…"),
                        lambda: self.share and self.share(name))
        m.addAction(icons.icon("trash", "danger_text"), _("Delete"),
                    lambda: self._delete(name))
        m.exec(at)

    def _share_menu(self):
        """Share's menu: each voice combo, with to the store and as a code under it."""
        m = QMenu(self)
        for name, setup in self.store.setups.items():
            sub = m.addMenu(self.icon_for(setup), name.replace("&", "&&"))
            if self.share is not None:
                sub.addAction(icons.icon("upload"), _("Share to the store…"),
                              lambda n=name: self.share and self.share(n))
            if self.copy_code is not None:
                sub.addAction(icons.icon("copy"), _("Copy share code"),
                              lambda n=name: self._copy(n))
        if m.isEmpty():
            m.addAction(_("Save what's on first, then share it here.")).setEnabled(False)
        m.exec(self.btn_share.mapToGlobal(self.btn_share.rect().bottomLeft()))

    def _copy(self, name: str):
        if self.copy_code is not None and self.copy_code(name):
            usage.used("voice-code-shared")
            self._say(_("Copied “{name}” as a share code", name=name))

    def _rename(self, name: str):
        if name not in self.store.setups:
            return
        new, ok = QInputDialog.getText(self, _("Rename"), _("New name:"), text=name)
        new = voicesetups.clean_name(new)
        if not ok or not new or new == name:
            return
        if self.store.taken(new, but=name):
            self._say(_("You already have a voice combo called “{name}”.", name=new))
            return
        if self.store.rename(name, new):
            usage.used("voice-setup-renamed")
            self._say(_("Saved “{name}”.", name=new))

    def _delete(self, name: str):
        setup = self.store.setups.get(name)
        if setup is None:
            return
        self._undo = (name, setup)   # before the store tells the tab: it stays for Undo
        self.store.remove(name)
        self.btn_undo.show()
        self._say(_("Deleted “{name}”.", name=name), keep=True)
        self._undo_timer.start(UNDO_MS)

    def _undo_delete(self):
        if self._undo is not None:
            name, setup = self._undo
            self.store.put(name, setup)
            self._say(_("“{name}” is back.", name=name))
        self._forget_undo()

    def undo_pending(self) -> bool:
        """A deleted mix that Undo can still bring back."""
        return self._undo is not None

    def _forget_undo(self):
        had = self._undo is not None
        self._undo = None
        self.btn_undo.hide()
        if had:
            self.changed.emit()   # (the tab may go now: its last mix is gone for good)
        if not self._note_timer.isActive():
            self._say("")
