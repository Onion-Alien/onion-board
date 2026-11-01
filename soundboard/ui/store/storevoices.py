"""The Store tab's Voices: community voice changer voices, AI voices and setups
(soundboard.online.storevoices), one row each, and the Share a voice window.

Everything a row shows comes from storevoices.voice_from (checked plain text and
in-range numbers) and is put on labels as plain text, never markup."""
from __future__ import annotations

import html
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from soundboard.core import usage
from soundboard.mic import savedvoices, voicesetups
from soundboard import voicefx
from soundboard.online import store, storevoices as sv
from soundboard.i18n import _
from soundboard.speech import aivoicelist as avl
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.kit.panel import HoverCard
from soundboard.ui.store.storeshare import error_text
from soundboard.ui.store.storetab import SoundRow

if TYPE_CHECKING:
    from soundboard.ui.voice.voicepanel import VoicePanel

log = logging.getLogger(__name__)

def kind_name(kind: str) -> str:
    return {"fx": _("Voice changer"), "ai": _("AI voice"), "setup": _("Voice combo")}.get(kind, "")


def kind_chips() -> list[tuple[str, str]]:
    """The Voices list's filter chips: (kind, text); "" is all of them."""
    return [("", _("All")), ("fx", _("Voice changer")), ("ai", _("AI voices")),
            ("setup", _("Voice combos"))]


def meta_line(v: sv.Voice) -> str:
    """The row's second line: what kind it is, what it uses, and its words."""
    parts = [kind_name(v.kind)]
    if v.kind == "setup":
        used = []
        if v.effects:
            used.append(voicefx.shown(v.fx) if v.fx in voicefx.PRESETS
                        else (v.fx or _("My own mix")))
        if v.ai:
            used.append(v.ai.get("name", ""))
        if v.language:
            from soundboard.core import langnames
            used.append(langnames.name(v.language, v.language))
        if used:
            parts.append(" + ".join(u for u in used if u))
    if v.about:
        parts.append(v.about)
    return " · ".join(p for p in parts if p)


class VoiceRow(SoundRow):
    """One community voice's card: hear it, vote on it, get it, or report it (a sound's
    card, with its own picture, second line and Get words)."""

    def __init__(self, v: sv.Voice, tab):   # noqa: D107 - not SoundRow's: no sound file
        HoverCard.__init__(self)
        self._build(v, tab, meta_line(v), _("Hear it (only you)"), _("Add it to your voices"),
                    _("Report this voice"))
        self.btn_queue.hide()   # (a sample to you: nothing to wait for)


class VoiceHooks:
    """What the Store's Voices need from the rest of the app. `panel()` is the Voice tab
    (None when it's switched off: then the voices' own files are used, and the tab
    reads them when it's next made)."""

    def __init__(self, panel: Callable[[], VoicePanel | None]):
        self.panel = panel
        self.last = ""   # the name take() last added a voice under

    def _stores(self):
        p = self.panel()
        if p is not None:
            return p.fx.store, p.ai.store, p.setups
        return savedvoices.Store(), avl.Store(), voicesetups.Store()

    def ai_module(self):
        p = self.panel()
        if p is not None:
            return p.ai.module
        from soundboard.addons import aiaddon
        return aiaddon.installed()

    def take(self, v: sv.Voice) -> str:
        """Add a community voice to yours; what happened, in words."""
        saved, ai_store, setups = self._stores()
        p = self.panel()
        self.last = ""
        if v.kind == "fx":
            name = self.last = sv.take_fx(v, saved)
            if not name:
                return _("You have the most saved voices there can be: delete one first.")
            if p is not None:
                p.fx._fill_saved()   # noqa: SLF001 - its list of your voices
            return _("Added “{name}” to your voice changer voices (Mine).", name=name)
        if v.kind == "ai":
            got = sv.take_ai(v, ai_store)
            if got is None:
                return _("You have the most AI voices of your own there can be: delete "
                         "one first.")
            self.last = got["name"]
            if p is not None:
                p.ai._resync()   # noqa: SLF001 - writes it into the add-on too
            return _("Added “{name}” to your AI voices (Mine).", name=got["name"])
        name = self.last = sv.take_setup(v, setups, ai_store)
        if not name:
            return _("Couldn't keep that voice combo (100 at most).")
        if p is not None and v.ai.get("mix"):
            p.ai._resync()   # noqa: SLF001
        return _("Added “{name}” to My voice combos.", name=name)

    def shareable(self) -> list[tuple[str, dict]]:
        """Your own voices that can be shared: (what the list shows, the payload)."""
        saved, ai_store, setups = self._stores()
        out = []
        for name, effects in saved.voices.items():
            p = sv.pack_fx(name, effects)
            if sv.can_share(p):
                out.append((f"{kind_name('fx')}: {name}", p))
        for vo in ai_store.voices:
            p = sv.pack_ai(vo)
            if sv.can_share(p):
                out.append((f"{kind_name('ai')}: {vo['name']}", p))
        for name, setup in setups.setups.items():
            ai = setup.get("ai") or {}
            p = sv.pack_setup(name, setup, ai_store.get(ai.get("id", "")) if ai else None)
            if sv.can_share(p):
                out.append((f"{kind_name('setup')}: {name}", p))
        return out


def _label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("hint")
    return lab


class ShareVoiceDialog(QDialog):
    """Share one of your voices: pick it, name it, say what it's for, Share."""
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work
    _sent = Signal(str)   # "" when it went, else why not

    def __init__(self, install: str, items: list[tuple[str, dict]], parent=None,
                 pick: str = ""):
        super().__init__(parent)
        self.install, self.items = install, items
        self.setWindowTitle(_("Share a voice"))
        self._sent.connect(self._on_sent)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        from soundboard.ui.store.storetab import _title
        v.addWidget(_title(_("Share a voice")))
        intro = QLabel(_("Anyone can find it under Store → Voices and add it to theirs. "
                         "Only its settings are shared, never your voice."))
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        v.addWidget(intro)
        self.pick = QComboBox()
        self.pick.setAccessibleName(_("Which voice"))
        for label, _p in items:
            self.pick.addItem(label)
        i = next((k for k, (label, _p) in enumerate(items) if label == pick), 0)
        self.pick.setCurrentIndex(i)
        self.pick.currentIndexChanged.connect(self._picked)
        v.addWidget(self.pick)
        v.addWidget(_label(_("Name")))
        self.name = QLineEdit()
        self.name.setMaxLength(sv.MAX_NAME)
        self.name.setPlaceholderText(_("Name"))
        self.name.setAccessibleName(_("Name"))
        v.addWidget(self.name)
        v.addWidget(_label(_("What's it good for? (optional)")))
        self.about = QLineEdit()
        self.about.setMaxLength(sv.MAX_ABOUT)
        self.about.setPlaceholderText(_("What's it good for? (optional)"))
        self.about.setAccessibleName(_("What's it good for? (optional)"))
        v.addWidget(self.about)
        self.error = QLabel()
        self.error.setObjectName("hint")
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.hide()
        from soundboard.ui.kit import theme
        theme.set_tone(self.error, "error")
        v.addWidget(self.error)
        row = QHBoxLayout()
        # or just to a friend: the same voice as a line of text to paste them
        self.btn_code = QPushButton(_("Copy share code"))
        icons.set_icon(self.btn_code, "copy")
        self.btn_code.clicked.connect(self.copy_code)
        row.addWidget(self.btn_code)
        row.addStretch(1)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.btn_send = QPushButton(_("Share"))
        self.btn_send.setObjectName("primary")
        icons.set_icon(self.btn_send, "upload", "on_accent", "on_accent")
        self.btn_send.clicked.connect(self.send)
        self.btn_send.setDefault(True)
        row.addWidget(self.btn_send)
        v.addLayout(row)
        self.name.textChanged.connect(self._named)
        self._picked(self.pick.currentIndex())
        self.resize(420, self.sizeHint().height())
        fit.watch(self)

    def _named(self, _text: str = ""):
        ok = bool(sv.plain(self.name.text(), sv.MAX_NAME)) and bool(self.items)
        self.btn_send.setEnabled(ok)
        self.btn_code.setEnabled(ok)

    def _picked(self, i: int):
        if 0 <= i < len(self.items):
            p = self.items[i][1]
            self.name.setText(p.get("name", ""))
            self.about.setText(p.get("about", ""))

    def payload(self) -> dict | None:
        i = self.pick.currentIndex()
        if not 0 <= i < len(self.items):
            return None
        p = dict(self.items[i][1])
        p["name"] = sv.plain(self.name.text(), sv.MAX_NAME)
        p["about"] = sv.plain(self.about.text(), sv.MAX_ABOUT)
        return p if p["name"] else None

    def copy_code(self) -> str:
        """The picked voice, under the name typed, as a share code on the clipboard."""
        p = self.payload()
        if p is None:
            return ""
        code = sv.share_code(p)
        QGuiApplication.clipboard().setText(code)
        usage.used("voice-code-shared")
        busy.flash(self.btn_code, _("✓ Copied"))
        return code

    def send(self):
        p = self.payload()
        if p is None or self.btn_send.property("busy"):
            return
        busy.set_busy(self.btn_send, True)
        self.error.hide()
        install = self.install

        def run():
            try:
                sv.share(install, p)
                busy.emit(self._sent, "")
            except Exception as e:  # noqa: BLE001 - said in the window, never a crash
                busy.emit(self._sent, error_text(e))
        threading.Thread(target=run, daemon=True, name="store-share-voice").start()

    def _on_sent(self, err: str):
        busy.set_busy(self.btn_send, False)
        if err:
            self.error.setText(err)
            self.error.show()
            return
        usage.used("store-voice-shared")
        busy.toast(self.parentWidget() or self, html.escape(
            _("Shared “{name}”: it's in Store → Voices now.", name=self.name.text())), "ok")
        self.accept()


def open_share(parent: QWidget, install: str, hooks: VoiceHooks, pick: str = ""):
    """The Share a voice window, or a line saying there's nothing to share yet (or that
    the store's down)."""
    if store.is_down():
        busy.toast(parent, html.escape(store.down_share()), "warn")
        return None
    items = hooks.shareable()
    if not items:
        busy.toast(parent, html.escape(_("Make a voice of your own first: Voice tab → "
                                         "Voice changer → Edit voice, or Save what's "
                                         "on under My voice combos.")), "warn", 8000)
        return None
    dlg = ShareVoiceDialog(install, items, parent, pick)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dlg.show()
    return dlg

