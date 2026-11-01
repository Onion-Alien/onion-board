"""The Languages card's downloads and installs (`SpeechPanel.installs`).

Getting a language's Windows voice, a translation model's download, and installing or
updating speech recognition (the live-voice add-on). A QObject the panel owns, like
ui/window/controller.py's: its workers' answers and its timer stop with the panel. It builds
the buttons it drives; the panel puts them in its layout.
"""
from __future__ import annotations

import html
import threading
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout

from soundboard.core import applog
from soundboard.addons import modules as mods
from soundboard.core import langnames
from soundboard.online import net, netlog
from soundboard.speech import live, translation, winvoices
from soundboard.ui.bun.pilotbun import PilotBunny
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.glowbutton import GlowButton
from soundboard.ui.kit.panel import hint_label, icon_button
from soundboard.ui.voice.voicefxpanel import _enable
from soundboard.core import errors
from soundboard.i18n import _, ngettext

if TYPE_CHECKING:
    from soundboard.ui.voice.speechpanel import SpeechPanel


class SpeechInstalls(QObject):
    """Windows voices, translation downloads and the speech recognition install for
    one SpeechPanel (``p``)."""
    _install_line = Signal(str)
    _install_done = Signal(bool, str)   # ok, and what went wrong when it wasn't
    _dl_progress = Signal(int, int)
    _dl_done = Signal(str)          # "" when it worked, else what went wrong
    _voice_done = Signal(str, str)  # a Windows voice install: result, what went wrong

    def __init__(self, panel: SpeechPanel):
        super().__init__(panel)
        self.p = panel
        self._dl_cancel = False
        self._dl_busy: mods.ModuleInfo | None = None
        self._installing = False
        self._voice_installing: mods.ModuleInfo | None = None
        self._voice_note = ""        # how the last voice install went, until it's found
        self._loading_since = time.monotonic()   # a voice (re)load is in flight; 0 when not
        self._voices_asked = False   # Reload voices was pressed: say what it found
        self._voices_again = False   # a reload was asked for while one ran
        self._voice_wait = False     # sent to Windows settings for a voice; look on return
        self._install_line.connect(lambda t: self.lbl_install.setText(t[-160:]))
        self._install_done.connect(self._on_install_done)
        self._dl_progress.connect(self._on_dl_progress)
        self._dl_done.connect(self._on_dl_done)
        self._voice_done.connect(self._on_voice_installed)
        # a voice installed any way at all (here, in Settings, by a script) is noticed
        # by its registry token appearing, and the speech engine reloads to use it
        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(3000)
        self._voice_timer.timeout.connect(self._poll_voices)
        net.on_change(self._net_changed)   # Settings > Privacy's switches

        # ---- under "Speak in": download it, get its Windows voice
        self.tr_row = tb = QHBoxLayout()
        self.b_dl = QPushButton(_("Download"))
        icons.set_icon(self.b_dl, "plus")
        self.b_dl.clicked.connect(self._download)
        self.b_dl_cancel = QPushButton(_("Cancel"))
        self.b_dl_cancel.clicked.connect(self._cancel_download)
        self.b_voice_install = QPushButton(_("Install the voice"))
        icons.set_icon(self.b_voice_install, "plus")
        self._voice_install_tip = _("Windows asks for permission once, then downloads its "
                                    "free voice for this language. It's used as soon as "
                                    "it's in; no restart.")
        self.b_voice_install.setToolTip(self._voice_install_tip)
        self.b_voice_install.clicked.connect(self._install_voice)
        self.b_voices = QPushButton(_("Windows settings"))
        self.b_voices.setObjectName("small")
        self.b_voices.setToolTip(_("Do it by hand: Settings → Time & language → "
                                   "Speech → Add voices. It's picked up by itself once "
                                   "it's in."))
        self.b_voices.clicked.connect(self._get_voice)
        self.b_voices_check = QPushButton(_("Reload voices"))
        self.b_voices_check.setObjectName("small")
        self.b_voices_check.setToolTip(_("Restart the speech engine to pick up new Windows "
                                         "voices (it also does this by itself)"))
        self.b_voices_check.clicked.connect(self._recheck_voices_asked)
        self.b_dl_remove = QPushButton(_("Delete download"))
        self.b_dl_remove.setObjectName("small")
        self.b_dl_remove.clicked.connect(self._remove_download)
        for b in self.tr_buttons():
            tb.addWidget(b)
        tb.addStretch(1)

        # ---- what to install first, in its own inner area above the settings: Pilot
        # Bun beside the words and the button, like Robo-Bun on the AI voice card
        self.missing = QFrame()
        self.missing.setObjectName("voicebox")
        sv = QHBoxLayout(self.missing)
        sv.setContentsMargins(8, 8, 16, 8)
        sv.setSpacing(16)
        self.bun_pilot = PilotBunny()
        sv.addWidget(self.bun_pilot, 0, Qt.AlignmentFlag.AlignVCenter)
        mv = QVBoxLayout()
        mv.setSpacing(10)
        mv.addStretch(1)   # the words and the button stay together, centred beside him
        self.lbl_missing = hint_label("")
        mv.addWidget(self.lbl_missing)
        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self.b_install = GlowButton(_("Install speech recognition"))
        icons.set_icon(self.b_install, "plus")
        self.b_install.setToolTip(_("One-time download, about 300 MB."))
        self.b_install.clicked.connect(self._install)
        mrow.addWidget(self.b_install)
        b_open = icon_button("folder", _("Open folder"), hover=False)
        b_open.clicked.connect(lambda: panel._open_folder(panel.module, b_open))
        mrow.addWidget(b_open)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        mv.addStretch(1)
        sv.addLayout(mv, 1)
        # install / update progress: outside `missing`, which is hidden for an update
        self.lbl_install = hint_label("")
        self.lbl_install.hide()
        # under More options
        self.b_update = QPushButton(_("Update speech recognition"))
        self.b_update.setToolTip(_("Runs its install again: picks up what a newer Onion Board "
                                   "needs (translation, for one)."))
        self.b_update.clicked.connect(self._install)
        self.b_remove = QPushButton(_("Remove languages"))
        self.b_remove.setToolTip(_("Deletes speech recognition, its speech models and every "
                                   "downloaded language from this PC. Get them again any "
                                   "time."))
        self.b_remove.clicked.connect(self._remove)

    def tr_buttons(self) -> tuple[QPushButton, ...]:
        """The buttons under "Speak in", in their row's order."""
        return (self.b_dl, self.b_dl_cancel, self.b_voice_install, self.b_voices,
                self.b_voices_check, self.b_dl_remove)

    # ---- Windows voices
    def _install_voice(self):
        m = self.p._lang()
        if m is None or self._voice_installing is not None:
            return
        self._voice_installing, self._voice_note = m, ""
        self.p._refresh_translation()

        def work():
            try:
                busy.emit(self._voice_done, winvoices.install(m.language), "")
            except winvoices.Cancelled:
                busy.emit(self._voice_done, "cancelled", "")
            except RuntimeError as e:
                busy.emit(self._voice_done, "", errors.plain(e))
            except Exception as e:  # noqa: BLE001 - the button must come back
                applog.report(where="windows voice install")
                busy.emit(self._voice_done, "", errors.plain(e))

        threading.Thread(target=work, name="voice-install", daemon=True).start()

    def _on_voice_installed(self, result: str, err: str):
        m, self._voice_installing = self._voice_installing, None
        m = m or self.p._lang()
        name = langnames.of(m) if m is not None else ""
        if err:
            self._voice_note = _("⚠ Couldn't install the {language} voice: {error}. "
                                 "Press Install to try again, or add it in Windows settings.",
                                 language=name, error=errors.plain(err))
        elif result == "cancelled":
            self._voice_note = _("Windows' permission prompt was closed, so the {language} "
                                 "voice wasn't installed. Press Install to try again.",
                                 language=name)
        elif result == "restart":
            self._voice_note = _("The {language} voice is installed, but Windows wants the "
                                 "PC restarted to finish. After that it's picked up by "
                                 "itself.", language=name)
        else:
            self._voice_note = _("The {language} voice is installed; loading it… If it "
                                 "doesn't appear in a minute, press Reload voices or restart "
                                 "the PC.", language=name)
        self.p._refresh_translation()
        if not err and result != "cancelled":
            self._recheck_voices()

    def _get_voice(self):
        self._voice_wait = busy.open_url(
            "ms-settings:speech", self.b_voices, opened=_("✓ Opened Windows settings"),
            failed=_("Couldn't open Windows settings. Go to Settings → Time & language → "
                     "Speech → Add voices yourself"))

    def _app_state(self, state):
        # back from Windows settings: a voice may have just been installed
        if state == Qt.ApplicationState.ApplicationActive and self._voice_wait:
            self._recheck_voices()

    def _watch_voices(self, on: bool):
        if on and not self._voice_timer.isActive():
            self._voice_timer.start()
        elif not on:
            self._voice_timer.stop()

    def _loading(self) -> bool:
        # a load that never answered (it times out well before this) doesn't block forever
        return bool(self._loading_since) and time.monotonic() - self._loading_since < 90

    def _poll_voices(self):
        """Reload the speech engine when Windows' voice list changed since it loaded."""
        if not self._loading() and winvoices.fingerprint() != self.p._voice_fp:
            self._recheck_voices()

    def _recheck_voices_asked(self):
        self._voices_asked = not self._loading()
        self._recheck_voices()

    def _recheck_voices(self):
        """Look for Windows voices again, off the UI thread. Safe while talking: a line
        being spoken waits a second for the engine to come back."""
        if self._loading():
            self._voices_again = True   # run once more when this load is done
            return
        self._loading_since = time.monotonic()
        busy.set_busy(self.b_voices_check, True)
        self.b_voices_check.setText(_("Reloading…"))
        p = self.p

        def work():
            p._voice_fp = winvoices.fingerprint()
            voices = p.ctl.tts.refresh()
            busy.emit(p._voices, voices, p.ctl.tts.error)
        threading.Thread(target=work, name="tts-refresh", daemon=True).start()

    def voices_loaded(self, count: int, error: str, found: bool):
        """The panel filled its voice list (`count` voices; `found`: the picked language
        has its voice, or none is picked): Reload voices comes back."""
        self._loading_since = 0.0
        busy.set_busy(self.b_voices_check, False)
        self.b_voices_check.setText(_("Reload voices"))
        if self._voices_again:   # asked for while that load ran (e.g. a server was added)
            self._voices_again = False
            QTimer.singleShot(0, self, self._recheck_voices)
        if self._voices_asked:
            self._voices_asked = False
            busy.flash(self.b_voices_check,
                       ngettext("✓ {n} voice", "✓ {n} voices", count) if not error
                       else _("Couldn't load them"))
        if found:
            self._voice_wait = False
            self._voice_note = ""

    # ---- translation downloads
    def _download(self, m: mods.ModuleInfo | None = None):
        """Download `m`'s translation (a grey language card), else the language picked."""
        p = self.p
        m = m or p._lang()
        if m is None or self._dl_busy is not None:
            return
        self._dl_busy, self._dl_cancel = m, False
        busy.set_busy(self.b_dl, True)
        _enable(p.cb_lang, False, _("Waiting for the download to finish"))
        _enable(p.livevoice.b_live, False, _("Waiting for the download to finish"))
        p._refresh_translation()
        p.lbl_tr.setText(_("Downloading {language}… {percent}%",
                           language=langnames.of(m), percent=0))
        netlog.cause("voices",
                     f"You downloaded the {m.language_name or m.language} translation model")

        def work():
            try:
                translation.download(m, lambda *a: busy.emit(self._dl_progress, *a),
                                     lambda: self._dl_cancel)
                busy.emit(self._dl_done, "")
            except translation.Cancelled:
                busy.emit(self._dl_done, "cancelled")
            except RuntimeError as e:
                busy.emit(self._dl_done, errors.plain(e))
            except Exception as e:  # noqa: BLE001 - the UI must never stay on "Downloading…"
                applog.report(where="translation download")
                busy.emit(self._dl_done, errors.plain(e))

        threading.Thread(target=work, name="translation-download", daemon=True).start()

    def _cancel_download(self):
        self._dl_cancel = True
        busy.set_busy(self.b_dl_cancel, True)
        if self._dl_busy is not None:
            self.p.lbl_tr.setText(_("Cancelling…"))

    def _on_dl_progress(self, done: int, total: int):
        m = self._dl_busy
        if m is not None and not self._dl_cancel:
            self.p.lbl_tr.setText(
                _("Downloading {language}… {percent}%", language=langnames.of(m),
                  percent=done * 100 // total) if total else
                _("Downloading {language}… {size} MB", language=langnames.of(m),
                  size=done // 1_000_000))

    def _on_dl_done(self, err: str):
        p = self.p
        m, self._dl_busy = self._dl_busy, None
        busy.set_busy(self.b_dl, False)
        _enable(p.cb_lang, not p.ctl.live, _("Stop the computer voice to change this"))
        _enable(p.livevoice.b_live, not self._installing,
                _("Waiting for the install to finish"))
        busy.set_busy(self.b_dl_cancel, False)
        p._fill_langs()
        if err == "cancelled" and m is not None:
            busy.toast(p, html.escape(_("Download cancelled.")))
        elif err and m is not None:
            busy.toast(p, html.escape(_(
                "⚠ {language}: {error}. Check your internet connection and press "
                "Download again.", language=langnames.of(m), error=errors.plain(err).rstrip("."))
                .removeprefix("⚠ ")), "error")
        p.downloaded.emit()

    def _remove_download(self):
        p = self.p
        m = p._lang()
        if m is None or p.ctl.live:
            return
        if QMessageBox.question(
                p, _("Delete download"),
                _("Delete the downloaded {language} translation? You can download it again "
                  "any time.", language=langnames.of(m))) != QMessageBox.StandardButton.Yes:
            return

        def go():
            translation.remove(m)
            p._fill_langs()
            p.downloaded.emit()
            return not translation.model_dir(m).exists()

        def said(gone: bool):
            if gone:
                busy.toast(p, _("✓ Deleted the {language} download",
                                language=html.escape(langnames.of(m))), "ok")
            else:
                busy.toast(p, _("Couldn't delete all of it (a file is in use). Restart "
                                "Onion Board and try again."), "warn")
        busy.run_busy(self.b_dl_remove, _("Deleting…"), go, said)

    def _remove(self):
        p = self.p
        if p.module is None or p.ctl.live or self._installing or self._dl_busy is not None:
            return
        if QMessageBox.question(
                p, _("Remove languages"),
                _("Delete speech recognition and every downloaded language from this PC? "
                  "You can get them again any time.")) != QMessageBox.StandardButton.Yes:
            return
        m, langs = p.module, list(p.langs)

        def go():
            try:
                return live.remove_recognition(m, langs)
            except mods.ModuleError:   # a file in its environment is in use
                return False

        def said(gone: bool):
            p._ready.clear()
            p._fill_langs()
            self._refresh_module()
            p.downloaded.emit()
            if gone:
                busy.toast(p, _("Languages are removed."), "ok")
            else:
                busy.toast(p, _("Couldn't delete all of it (a file is in use). Restart "
                                "Onion Board and try again."), "warn")
        busy.run_busy(self.b_remove, _("Removing…"), go, said)

    def show_remove(self):
        """Remove languages, while there's anything of it on this PC: speech recognition,
        its speech models or a downloaded language (one can be there without the others)."""
        p = self.p
        m = p.module
        self.b_remove.setVisible(
            (m is not None and m.installed) or any(lang.installed for lang in p.langs)
            or bool(live.speech_model_dirs()))

    # ---- speech recognition (the live-voice add-on)
    def _net_changed(self):
        """Offline mode on or off: the install buttons follow (not mid-install)."""
        if not self._installing:
            self._refresh_module()

    def _refresh_module(self):
        p = self.p
        p._ready.clear()   # installed, repaired or rescanned: ask the disk again
        m = p.module
        ok = m is not None and m.installed
        p.show_lang_box(ok and bool(p.langs))
        p.livevoice.set_installed(ok)
        p.show_recognition(ok)
        self.missing.setVisible(not ok)
        self.b_install.setVisible(m is not None and not ok and not net.offline())
        self.b_update.setVisible(ok and not net.offline())   # pip: online; Install till in
        self.show_remove()
        if m is not None and not ok and net.offline():
            self.lbl_missing.setText(_("Speaking another language needs speech recognition "
                                       "installed first, which is a download. Offline mode "
                                       "is on, so it can't be installed now."))
        elif m is None:
            self.lbl_missing.setText(_(
                "The live-voice add-on is missing from this copy of Onion Board. Run the "
                "installer again (it comes with every install), then press Refresh below."))
        elif m.broken:   # the Python it was set up with is gone (soundboard.online.pyget)
            self.lbl_missing.setText(_("Speech recognition stopped working: the Python it "
                                       "was set up with is gone from this PC. Press Repair "
                                       "to set it up again."))
        elif not ok:
            self.lbl_missing.setText(_("Speaking another language needs speech recognition "
                                       "installed first (runs on this PC; what you say never "
                                       "leaves it)."))
        if not self._installing:
            fix = m is not None and m.broken
            self.b_install.setText(_("Repair") if fix else _("Install speech recognition"))
            icons.set_icon(self.b_install, "reload" if fix else "plus")

    def _install(self):
        m = self.p.module
        if m is None or self._installing:
            return          # one pip at a time: two into the same environment break it
        self._installing = True
        for b in (self.b_install, self.b_update, self.b_remove, self.p.livevoice.b_live):
            busy.set_busy(b, True)
        self.b_install.setText(_("Installing… (a few minutes)"))
        self.bun_pilot.set_flying(True)
        self.b_update.setText(_("Updating… (a few minutes)"))
        self.lbl_install.show()
        self.lbl_install.setText(_("starting…"))

        def work():
            try:
                ok = mods.install(m, lambda line: busy.emit(self._install_line, line))
                busy.emit(self._install_done, ok, "")
            except Exception as e:  # noqa: BLE001 - the buttons must come back
                if not isinstance(e, (mods.ModuleError, OSError)):   # a bug: report it
                    applog.report(where="module install")
                busy.emit(self._install_done, False, errors.plain(e))

        threading.Thread(target=work, name="module-install", daemon=True).start()

    def _on_install_done(self, ok: bool, err: str = ""):
        p = self.p
        b_live = p.livevoice.b_live
        self._installing = False
        for b in (self.b_install, self.b_update, self.b_remove, b_live):
            busy.set_busy(b, False)
        self.b_install.setEnabled(True)
        self.b_install.setText(_("Install speech recognition"))
        self.bun_pilot.set_flying(False)
        for b in (self.b_update, self.b_remove):
            _enable(b, not p.ctl.live, _("Stop the computer voice to change this"))
        self.b_update.setText(_("Update speech recognition"))
        _enable(b_live, self._dl_busy is None, _("Waiting for the download to finish"))
        if ok:
            self.lbl_install.hide()
            self._refresh_module()
            p.livevoice.lbl_state.setText(_("Installed. Pick a language and talk."))
        else:
            last = self.lbl_install.text()
            self.lbl_install.hide()
            self._refresh_module()   # Repair stays Repair
            busy.toast(p, html.escape(_(
                "⚠ Install failed: {error}. Press it again to retry; if it keeps failing, "
                "run install.bat in the add-on's folder to see why.",
                error=err or last).removeprefix("⚠ ")), "error")
