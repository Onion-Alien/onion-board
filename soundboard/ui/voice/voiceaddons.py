"""The Voice tab's add-ons: finding them again (when one is installed or removed, and
when going on or offline), and the Custom voices dialog. Mixed into VoicePanel
(voicepanel.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard.addons import modules as mods
from soundboard.core import langnames
from soundboard.online import net
from soundboard.speech import piper, spoken
from soundboard.ui.kit import fit
from soundboard.i18n import _

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what VoicePanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


class CustomVoices(QDialog):
    """Custom voices (a TTS server on this PC, Piper voice packs), opened from the
    button at the top of AI voices: SpeechPanel's custom voices part, in a small
    dialog of its own. Opening it asks the voice servers again whether they answer."""

    def __init__(self, parent: QWidget, title: QLabel, box: QWidget, check):
        super().__init__(parent)
        fit.watch(self)
        self.setWindowTitle(title.text())
        self._check = check
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(12)
        title.setProperty("head", True)
        v.addWidget(title)
        v.addWidget(box)
        row = QHBoxLayout()
        b = QPushButton(_("Done"))
        b.clicked.connect(self.accept)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.setFixedWidth(560)

    def open_by(self, button: QWidget):
        """Open under `button` (its right edge with the button's): the button sits at
        the right end of the AI voices card. A hidden button: the window's middle."""
        self._check()
        self.adjustSize()
        if button.isVisible():
            at = button.mapToGlobal(QPoint(button.width(), button.height() + 6))
            screen = (QApplication.screenAt(at) or button.screen()).availableGeometry()
            x = min(max(screen.left(), at.x() - self.width()), screen.right() - self.width() + 1)
            y = min(at.y(), screen.bottom() - self.height() + 1)
            self.move(x, max(screen.top(), y))
        self.open()
        self.raise_()


class VoiceAddons(_Panel):
    """VoicePanel's add-on scan."""

    def rescan_modules(self, found: list | None = None, ai_voices: list | None = None):
        """`found` / `ai_voices`: already read from disk."""
        self.modules = mods.discover() if found is None else found
        mods.load_effects(self.modules)
        self.fx.add_new_effects()
        self.chain.configure(self.fx.spec())
        self.speech.set_modules(self.modules)
        self.ai.set_modules(self.modules, ai_voices)
        self._check_voices_need()
        sp = self.speech
        t = sp.translating()
        if t is not None and sp.ctl.live:   # talking already: the right voice from the next line
            sp.ctl.live_voice = sp._voice_for(t) or None
        self._emit_active()   # the language's bar row and the AI voices' Languages cards
        self._follow_offline()

    def _check_voices_need(self, *_args):
        """Whether the languages' own voices can be read yet (no AI voices add-on, or
        one that can't read them: a Windows voice reads meanwhile). At start too, not
        only on a rescan: else a language named its own voice and said nothing.

        One that only needs updating is updated by itself (once a run) as soon as a
        downloaded language has a voice: pressing Update AI voices on another tab was
        a step nobody would find."""
        m = self.ai.module
        need = ("get" if m is None or not m.installed
                else "update" if not piper.can_read(m) else "")
        sp = self.speech
        if need and self.ai.installing():
            need = "updating"
        elif need == "update" and not self._voices_updated:
            lang = next((x for x in sp.langs if x.voice and sp._is_ready(x)), None)
            if (lang is not None and not net.offline() and net.allowed("addons")
                    and self.ai.update_for(_("✓ The {language} voice is ready.",
                                             language=langnames.of(lang)))):
                self._voices_updated = True
                need = "updating"
        sp.voices_need = need
        sp._refresh_translation()

    def _ai_install_started(self):
        """AI voices coming in: a language waiting for them says so, and when it's done."""
        sp = self.speech
        m = sp._lang_on()
        if m is not None and m.voice and sp._is_ready(m) and not self.ai._done_note:
            self.ai._done_note = _("✓ The {language} voice is ready.",
                                   language=langnames.of(m))
        self._check_voices_need()

    def _follow_offline(self):
        """Offline mode: the AI voices and Languages tabs only while they're ready to
        use (getting or installing them goes online). Languages also needs speech
        recognition to hear the app's language."""
        off = net.offline()
        self.clean.follow_offline()
        if (bar := getattr(self, "setups_bar", None)) is not None:   # (not made yet at start)
            bar.follow_offline()
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
