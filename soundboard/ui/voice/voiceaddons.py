"""The Voice tab's add-ons: the list of installed add-ons and finding them again (in the
background, and when going on or offline). Mixed into VoicePanel (voicepanel.py)."""
from __future__ import annotations

import html
import threading
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.addons import modules as mods
from soundboard.core import langnames
from soundboard.online import net
from soundboard.speech import spoken, translation
from soundboard.ui.kit import busy
from soundboard.ui.kit.panel import hint_label, icon_button, section_label
from soundboard.ui.voice.speechpanel import LIVE_MODULE, SpeechPanel
from soundboard.i18n import _

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what VoicePanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


class ModulesList(QWidget):
    """`refresh` asks for a rescan (the Voice tab does it off the UI thread); the
    button stays on "Checking…" until the next show_modules()."""
    refresh = Signal()
    shown = Signal()

    def __init__(self, voices_title: QLabel | None = None, voices: QWidget | None = None):
        """`voices_title` and `voices`: the custom voices part, under the list."""
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.title = section_label(_("Add-ons"))
        v.addWidget(self.title)
        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        v.addLayout(self.list)
        row = QHBoxLayout()
        b = self.b_refresh = QPushButton(_("Refresh"))
        b.clicked.connect(self._refresh)
        o = icon_button("folder", _("Open folder"), hover=False)
        o.clicked.connect(lambda: SpeechPanel._open_folder(btn=o))
        row.addWidget(b)
        row.addWidget(o)
        row.addStretch(1)
        v.addLayout(row)
        if voices is not None:
            if voices_title is not None:
                v.addWidget(voices_title)
            v.addWidget(voices)

    def _refresh(self):
        if busy.is_busy(self.b_refresh):
            return   # already checking: a double click mustn't start it twice
        busy.hold_until(self.b_refresh, _("Checking…"), self.shown, lambda: _("✓ Up to date"))
        self.refresh.emit()

    def show_modules(self, infos: list[mods.ModuleInfo]):
        while self.list.count():
            item = self.list.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()
        e = html.escape   # error text is often "<class ...>"-shaped

        def row(text: str, tip: str):
            lbl = hint_label(text)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setToolTip(tip)
            self.list.addWidget(lbl)
        # the Voice tab's own add-ons only: Onion Watch lives on the Triggers tab (and
        # Settings → Add-ons), and the languages share one line
        voice = [m for m in infos if m.kind not in ("triggers", "remote")]
        langs = [m for m in voice if m.kind == "translation" and not m.error]
        for m in voice:
            if m in langs:
                continue
            if m.error:
                state = f"⚠ {m.error}"
            elif m.kind == "service" and m.broken:
                state = _("stopped working: needs a repair")
            elif m.kind == "service" and not m.installed:
                state = (_("not set up yet: press Install speech recognition above")
                         if m.id == LIVE_MODULE and not net.offline() else _("not set up yet"))
            elif m.kind == "effects":
                state = _("on") if m.loaded else _("not loaded")
            else:
                state = _("ready")
            row(f"<b>{e(m.name)}</b> {e(m.version)} · {e(state)}",
                f"{m.description}" + chr(10) + str(m.path))
        if langs:
            have = [langnames.of(m) for m in langs if m.installed]
            more = [langnames.of(m) for m in langs if not m.installed]
            parts = [_("{languages} downloaded", languages=", ".join(have))] if have else []
            if more and not net.offline():   # Offline mode: nothing can be downloaded
                parts.append(_("{languages} can be downloaded under Speak in",
                               languages=", ".join(more)))
            row(_("<b>Languages</b> · {state}", state=e("; ".join(parts))),
                chr(10).join(_("{language}: {size} MB", language=langnames.of(m),
                               size=translation.size_mb(m))
                             for m in langs))
        if not voice:
            self.list.addWidget(hint_label(_("No voice add-ons installed.")))
        self.shown.emit()


class VoiceAddons(_Panel):
    """VoicePanel's add-on scan."""

    def rescan_modules(self, found: list | None = None, ai_voices: list | None = None):
        """`found` / `ai_voices`: already read from disk by _rescan_in_background."""
        self.modules = mods.discover() if found is None else found
        mods.load_effects(self.modules)
        self.fx.add_new_effects()
        self.chain.configure(self.fx.spec())
        self.speech.set_modules(self.modules)
        self.ai.set_modules(self.modules, ai_voices)
        m = self.ai.module
        self.speech.voices_need = (
            "get" if m is None or not m.installed
            else "update" if not (m.path / "reader.py").is_file() else "")
        self.speech._refresh_translation()
        sp = self.speech
        t = sp.translating()
        if t is not None and sp.ctl.live:   # talking already: the right voice from the next line
            sp.ctl.live_voice = sp._voice_for(t) or None
        self._emit_active()   # the language's bar row and the AI voices' Languages cards
        self._follow_offline()
        self.addons.show_modules(self.modules)

    def _rescan_in_background(self):
        """The add-ons' Refresh button: the folder scan and voices.json read on a
        worker (17 ms of disk on a slow drive), the rest back on the UI thread."""
        if self._scanning:
            return
        self._scanning = True

        def work():
            from soundboard.speech import aivoice
            from soundboard.ui.voice.aivoicepanel import read_voices
            found = voices = None
            try:
                found = mods.discover()
                voices = read_voices(next((m for m in found if m.id == aivoice.MODULE_ID
                                           and not m.error), None))
            except Exception:  # noqa: BLE001 - scanned again on the UI thread instead
                found = voices = None
            busy.emit(self._scanned, found, voices)
        threading.Thread(target=work, daemon=True, name="addon-scan").start()

    def _follow_offline(self):
        """Offline mode: the AI voices and Languages tabs only while they're ready to
        use (getting or installing them goes online). Languages also needs speech
        recognition to hear the app's language."""
        off = net.offline()
        shown = {"ai": not off or self.ai.ready(),
                 "speak": spoken.heard() and (not off or self.speech.recognition_ready()
                                              or self.speech.installs._installing)}
        for key, on in shown.items():
            self._tabs[key].setVisible(on)
            if not on and self._tab == key:
                self.show_tab("fx")
            self._cards[key].setVisible(on and self._tab == key)

    def _ai_net_changed(self):
        if not self.ai._installing:   # (its buttons come back when that's done)
            self.ai._refresh()
        self._follow_offline()
        self.addons.show_modules(self.modules)   # its lines name downloads

    def _apply_scan(self, found, voices):
        self._scanning = False
        try:
            self.rescan_modules(found, voices)
        except Exception:
            self.addons.shown.emit()   # never leave Refresh stuck on "Checking…"
            raise
