"""The Voice tab's My setups row, above every part of the tab: your saved mixes of a
voice changer voice, an AI voice and a language (voicesetups). Click one to turn the
whole mix on; Save what's on keeps what you have on now. The same setups go on sounds
from Edit sound → Effects → Voice."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard import voicesetups
from soundboard.i18n import _
from soundboard.ui import icons
from soundboard.ui.panel import Flow

UNDO_MS = 10000
NOTE_MS = 6000   # a "Saved" / "is on" line goes again after this


class SetupsBar(QWidget):
    """`capture()` gives the setup that's on now ({} if nothing is), `apply(setup)` turns
    one on, `icon_for(setup)` its picture, `describe(setup)` its parts in words."""

    def __init__(self, store: voicesetups.Store, capture: Callable[[], dict],
                 apply: Callable[[dict], None], icon_for: Callable[[dict], QIcon],
                 describe: Callable[[dict], str]):
        super().__init__()
        self.store, self.capture, self.apply = store, capture, apply
        self.icon_for, self.describe = icon_for, describe
        self._undo: tuple[str, dict] | None = None
        self.share: Callable[[str], None] | None = None   # Share to the store (its name)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        title = QLabel(_("My setups"))
        title.setObjectName("section")
        title.setProperty("head", True)
        row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        self.chips = QWidget()
        self.flow = Flow(self.chips, gap=6)
        row.addWidget(self.chips, 1)
        v.addLayout(row)
        # the + right after the last setup, in the same row (wraps with them)
        self.btn_save = QPushButton(_("Save what's on"))
        self.btn_save.setObjectName("voicecat")
        icons.set_icon(self.btn_save, "plus", "muted")
        self.btn_save.setToolTip(_("Keep the voice changer voice, AI voice and language you "
                                   "have on now under a name: one click turns them all on "
                                   "again, and you can put it on sounds (Edit sound → "
                                   "Effects → Voice)"))
        self.btn_save.clicked.connect(self._save)
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
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(lambda: self._say(""))
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.timeout.connect(self._forget_undo)
        self.buttons: dict[str, QPushButton] = {}
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
            b = QPushButton(name.replace("&", "&&"))
            b.setObjectName("voicecat")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(self.icon_for(setup))
            b.setAccessibleName(name)
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

    def _say(self, text: str, keep: bool = False):
        """A line under the row; it goes again after NOTE_MS unless `keep`."""
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
        self._say(_("Saved “{name}”.", name=saved) if saved
                  else _("Couldn't save it (100 setups at most)."))

    def _menu(self, name: str, at):
        m = QMenu(self)
        m.addAction(icons.icon("edit"), _("Rename"), lambda: self._rename(name))
        if self.share is not None:
            m.addAction(icons.icon("upload"), _("Share to the store…"),
                        lambda: self.share and self.share(name))
        m.addAction(_("Delete"), lambda: self._delete(name))
        m.exec(at)

    def _rename(self, name: str):
        if name not in self.store.setups:
            return
        new, ok = QInputDialog.getText(self, _("Rename"), _("New name:"), text=name)
        new = voicesetups.clean_name(new)
        if not ok or not new or new == name:
            return
        if self.store.taken(new, but=name):
            self._say(_("You already have a setup called “{name}”.", name=new))
            return
        if self.store.rename(name, new):
            self._say(_("Saved “{name}”.", name=new))

    def _delete(self, name: str):
        setup = self.store.remove(name)
        if setup is None:
            return
        self._undo = (name, setup)
        self.btn_undo.show()
        self._say(_("Deleted “{name}”.", name=name), keep=True)
        self._undo_timer.start(UNDO_MS)

    def _undo_delete(self):
        if self._undo is not None:
            name, setup = self._undo
            self.store.put(name, setup)
            self._say(_("“{name}” is back.", name=name))
        self._forget_undo()

    def _forget_undo(self):
        self._undo = None
        self.btn_undo.hide()
        if not self._note_timer.isActive():
            self._say("")
