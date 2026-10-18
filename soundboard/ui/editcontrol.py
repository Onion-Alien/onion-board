"""Editing sounds from the main window: the Edit sound windows (one per sound, a spare one
kept built), what happens when one closes (saved, or a copy saved), closing them when their
sound goes, Duplicate, Open file location, and rendering a sound again after its effects
change.

MainWindow makes one ``EditControl`` (``MainWindow.editctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import html
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from shiboken6 import isValid as qt_valid

from soundboard.core import errors
from soundboard.audio import renderworker, soundfx
from soundboard import voicefx
from soundboard.sounds import library, videos
from soundboard.i18n import _
from soundboard.sounds.library import SoundMeta, cache_keep, duplicate, load_sound, prune_cache
from soundboard.ui.kit import worker
from soundboard.ui.controller import Controller
from soundboard.ui.kit.crashdialog import free_dialog, rehome_crash_reports
from soundboard.ui.sounds.dialogs import EditDialog

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

PROGRESS_MS = 200      # an in-app render tells the UI how far it is at most this often
ETA_AFTER_S = 3.0      # time left is guessed once it has run this long...
ETA_AFTER_FRAC = 0.03  # ...and done this much of it
DONE_TOAST_S = 2.0     # a render that took longer says so when it's ready


@dataclass
class Render:
    """A sound's effects render in flight (EditControl._renders)."""
    gen: int
    old_fx: dict | None        # what Stop puts back (None: nothing to go back to)
    old_data: Any = None       # the audio that goes with old_fx, when it was loaded
    frac: float = 0.0          # how far, 0..1
    t0: float = field(default_factory=time.monotonic)

    def left(self) -> float | None:
        """Seconds still to go (a guess from the pace so far), or None: too soon."""
        spent = time.monotonic() - self.t0
        if spent < ETA_AFTER_S or self.frac < ETA_AFTER_FRAC:
            return None
        return spent * (1 - self.frac) / self.frac


class EditControl(Controller):
    """The Edit sound windows of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._editors: dict[str, EditDialog] = {}
        self._render_gen: dict[str, int] = {}   # sid -> newest effects render (_rerender)
        self._renders: dict[str, Render] = {}  # sid -> the render in flight, how far it is
        self._setup_store = None   # voicesetups.Store, read the first time the picker opens

    def edit(self, sid, tab: str = "sound"):
        """Edit sound beside the board, not over it: sounds, hotkeys and the other
        pads keep working. It's still a draft: nothing changes until Save, and Cancel
        (or Escape, or closing it) drops it. One window per sound: editing the same
        sound again raises the open one."""
        mw = self.mw
        d = self._editors.get(sid)
        if d is not None and qt_valid(d):
            if tab == "effects":
                d.tabs.setCurrentIndex(1)
            d.showNormal() if d.isMinimized() else d.show()
            d.raise_()
            d.activateWindow()
            return d
        m = mw.meta(sid)
        if m is None:
            return None
        # a closed one shows this sound instead: building one took ~200 ms every time
        d, mw.setctl._spare_editor = mw.setctl._spare_editor, None
        if d is not None and qt_valid(d):
            d.load(m, tab)
        else:
            d = self._new_editor(m, tab)
        self._editors[sid] = d
        self._show_render(sid)
        d.show()
        return d

    def _edit_done(self, sid: str, d: EditDialog, ok: int):
        """An Edit sound window closed: Save puts its draft on the sound (or a copy).
        It's kept for the next sound edited (the first one closed; any more are freed)."""
        mw = self.mw
        if self._editors.get(sid) is d:
            del self._editors[sid]
        mw.playctl.drop_preview()                        # a preview still rendering
        mw.engine.stop(f"{sid}:preview")         # and the one playing, either kind
        mw.engine.stop(f"{sid}~fx:preview")
        # the sound as it is now: gone (removed while the window was open: nothing to
        # save it onto), or the same sound in a new object (Undo put it back)
        m = mw.meta(sid)
        try:
            if ok and m is not None and d.as_copy:
                self._save_copy(m, d)
            elif ok and m is not None:
                self._save_edits(m, d)
        finally:
            if mw.setctl._spare_editor is None and d not in self._editors.values():
                rehome_crash_reports(d)
                mw.setctl._spare_editor = d
            else:   # freed once its finished signal is over (deleting it inside crashed)
                QTimer.singleShot(0, lambda: free_dialog(d))
        mw.hkctl.register_hotkeys()

    def _save_edits(self, m: SoundMeta, d: EditDialog):
        """Save puts the window's draft on the sound (its effects rendered again when
        they changed)."""
        mw = self.mw
        old_key, old_hotkey = soundfx.key(m.fx), m.hotkey
        old_fx = m.fx
        d.apply(m)
        if m.hotkey != old_hotkey:
            if mw.hkctl.keeps_stop_key(m.hotkey):
                m.hotkey = old_hotkey
            else:
                mw.hkctl.everyday_note(m.hotkey)
        mw.hkctl._clear_dupe_hotkey(m)
        mw.engine.set_gain(m.id, mw.gain_for(m))
        if soundfx.key(m.fx) != old_key:
            self._rerender(m, old_fx)
        mw._save_now()
        p = mw.pads.get(m.id)
        if p is not None:
            p.update()
        mw.searchctl.apply_filter(mw.search.text())

    def _save_open(self, d: EditDialog) -> bool:
        """Save with new effects that take a while to render (an AI voice, a long
        sound): saved now, and the window stays open to show the render (it can be
        closed: it keeps going). False: an ordinary Save, the window closes."""
        mw = self.mw
        m = mw.meta(d.meta.id)
        if m is None or self._editors.get(m.id) is not d:
            return False
        fx = d.effects.fx()
        key = soundfx.key(fx)
        if (key == soundfx.key(m.fx) or not key or not renderworker.worth_it(fx, m.duration)
                or library.cache_path(m.id, key).is_file()):
            return False
        self._save_edits(m, d)
        mw.hkctl.register_hotkeys()
        return self.rendering(m.id) is not None

    def _new_editor(self, m: SoundMeta, tab: str) -> EditDialog:
        mw = self.mw
        d = EditDialog(m, mw.hotkeys, mw.playctl.preview, mw, tab=tab,
                       others=lambda: list(mw._meta.values()), pick_voice=self.pick_voice,
                       save_hook=self._save_open, stop_render=self.stop_render)
        d.hotkeys_changed.connect(mw.hkctl.register_hotkeys)
        d.source_forgotten.connect(mw._save_now)
        d.finished.connect(lambda ok, d=d: self._edit_done(d.meta.id, d, ok))
        return d

    def voice_catalog(self):
        """What the voice picker shows (ui.voicepicker.Catalog): the voice changer's
        voices and your saved ones, the AI voices (when that add-on is set up), your
        setups, and the Voice tab's Favorites (a star here is a star there)."""
        from soundboard.speech import soundvoice
        from soundboard.ui.voice import art
        from soundboard.ui.sounds.voicepicker import Catalog
        mw = self.mw
        cat = Catalog()
        cat.fx = [(n, voicefx.shown(n), {t: {"on": True, **c} for t, c in fx.items()},
                   art.icon(art.voice_key(n)), False) for n, fx in voicefx.PRESETS.items()]
        tab = mw.voice if mw.tabctl.tab_on("voice") else None
        fxp = getattr(tab, "fx", None)
        if fxp is not None:
            cat.fx += [(n, n, dict(e), None, True) for n, e in fxp.store.voices.items()
                       if n not in voicefx.PRESETS]
            cat.fx_favs = list(fxp.favorites)
            cat.star_fx = fxp.set_favorite
        ai = getattr(tab, "ai", None)
        mod = getattr(ai, "module", None)
        if ai is not None and mod is not None:
            cat.ai = list(ai.voices)
            cat.ai_ready = mod.installed and all((mod.path / "model" / f).is_file()
                                                 for f in soundvoice.MODEL_FILES)
            cat.ai_favs = list(getattr(ai, "_favs", []))
            cat.star_ai = ai.set_favorite
        from soundboard.mic import voicesetups
        cat.setups = [(n, voicesetups.sound_voice(s)) for n, s in self._setups().setups.items()
                      if voicesetups.sound_voice(s)]   # (a language alone: not for sounds yet)
        return cat

    def _setups(self):
        """The voice setups: the Voice tab's own (one Store, so both stay in step), else
        read here the first time."""
        mw = self.mw
        if mw.tabctl.tab_on("voice") and getattr(mw.voice, "setups", None) is not None:
            return mw.voice.setups
        if self._setup_store is None:
            from soundboard.mic import voicesetups
            self._setup_store = voicesetups.Store()
        return self._setup_store

    def pick_voice(self, voice: dict, parent=None) -> dict | None:
        """Edit sound → Effects → Voice: the picker on `voice`; the new voice, or None."""
        from soundboard.ui.sounds.voicepicker import VoicePicker
        d = VoicePicker(self.voice_catalog(), voice,
                        lambda name, v: self._setups().put(name, v), parent)
        try:
            return d.voice if d.exec() else None
        finally:
            d.deleteLater()

    def _close_editors(self, sids):
        """The sounds are going: their open Edit sound windows close, unsaved (the
        Undo bar brings the sound back as it was)."""
        for sid in sids:
            d = self._editors.get(sid)
            if d is not None and qt_valid(d):
                d.reject()

    def duplicate_sound(self, sid: str) -> SoundMeta | None:
        """The pad menu's Duplicate: a copy right after the original, with its own
        file, so each can get its own effects, hotkey or category."""
        mw = self.mw
        m = mw.meta(sid)
        if m is None:
            return None
        try:
            new = duplicate(m, _("{name} (copy)", name=m.name)[:40])
        except OSError as e:
            errors.warn(mw, _("Couldn't copy the sound"), e)
            return None
        videos.copy_link(m.id, new.id)
        mw.catctl._tag_new(new)   # stays in sight in the category showing
        mw.cfg.sounds.insert(mw.cfg.sounds.index(m) + 1, new)
        mw._index()
        mw._save_now()
        mw._rebuild_pads()
        self._rerender(new)
        mw.toast(_("✓ Added “{name}”", name=html.escape(new.name)), "ok")
        return new

    def show_sound_file(self, sid: str):
        """The pad menu's Open file location: Explorer with the file picked
        (elsewhere, the folder it's in)."""
        mw = self.mw
        m = mw.meta(sid)
        if m is None:
            return
        path = Path(m.file)
        if not path.is_file():
            mw.toast(_("The file for “{name}” isn't there any more", name=html.escape(m.name)),
                       "warn")
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _save_copy(self, m: SoundMeta, d: EditDialog):
        """'Save a copy': the edits go onto a copy placed after the original."""
        mw = self.mw
        name = d.name.text().strip() or m.name
        try:
            new = duplicate(m, name if name != m.name else f"{name} (edit)")
        except OSError as e:
            errors.warn(mw, _("Couldn't copy the sound"), e)
            return
        videos.copy_link(m.id, new.id)
        d.apply(new)
        if new.name == m.name:
            new.name = f"{m.name} (edit)"[:40]
        if new.hotkey == m.hotkey:
            new.hotkey = ""   # the original keeps its hotkey
        if mw.hkctl.keeps_stop_key(new.hotkey):
            new.hotkey = ""
        mw.hkctl._clear_dupe_hotkey(new)
        mw.catctl._tag_new(new)   # stays in sight in the category showing
        mw.cfg.sounds.insert(mw.cfg.sounds.index(m) + 1, new)
        mw._index()
        mw._save_now()
        mw._rebuild_pads()
        self._rerender(new, m.fx, mw.audio.get(m.id))

    def _rerender(self, m: SoundMeta, old_fx: dict | None = None, old_data=None):
        """Load a sound again after its effects changed. They're rendered in the
        background (a slow one in its own process: renderworker); the pad shows how far
        it is until it's ready. old_fx: the effects before, which Stop goes back to (with
        old_data, their audio; the pad's own audio when not given)."""
        mw = self.mw
        prev = self._renders.get(m.id)
        if old_data is None and old_fx is not None:
            old_data = mw.audio.get(m.id)
        mw.engine.stop(m.id)
        mw.audio.pop(m.id, None)
        mw.engine.forget(m.id)
        gen = self._render_gen[m.id] = self._render_gen.get(m.id, 0) + 1
        if prev is not None:   # edited again while rendering: Stop still goes back to
            old_fx, old_data = prev.old_fx, prev.old_data   # how it was before both
        self._renders[m.id] = Render(gen, old_fx, old_data)
        p = mw.pads.get(m.id)
        if p:
            p.state = "rendering"
            p.render_frac, p.can_stop = 0.0, old_fx is not None
            p.update()
        self._show_render(m.id)
        key = soundfx.key(m.fx)
        told = [0.0]

        def cancel():
            return self._render_gen.get(m.id) != gen

        def progress(frac: float):   # (the rendering thread)
            now = time.monotonic()
            if now - told[0] >= PROGRESS_MS / 1000 or frac >= 1.0:
                told[0] = now
                mw.bridge.render_progress.emit(m.id, gen, float(frac))

        def run():
            try:
                data = None
                if (renderworker.enabled and renderworker.worth_it(m.fx, m.duration)
                        and library.load_cached(m.id, key) is None):
                    try:   # out of the app's process: no stutter, no lag
                        renderworker.render(m, cancel, progress)
                        data = library.load_cached(m.id, key)
                    except renderworker.Unavailable as e:
                        log.info("rendering %s in the app: %s", m.id, e)
                if data is None:
                    data = load_sound(m, cancel=cancel, progress=progress)
            except library.Cancelled:
                return worker.SKIP   # (it stopped partway: Stop, or a newer one)
            if self._render_gen.get(m.id) != gen:
                return worker.SKIP   # edited again meanwhile: a newer render is on its way
            mw.engine.prepare(m.id, data)
            prune()
            return m.id, data, ""

        def prune():
            worker.run(lambda: prune_cache(cache_keep(mw.soundctl._live_metas())), name="prune")

        def failed(e):
            prune()
            return m.id, None, errors.plain(e)
        worker.run(run, mw.bridge.loaded, "fx-render", error=failed, owner=mw)

    # ------------------------------------------------------------ renders in flight
    def rendering(self, sid: str) -> Render | None:
        """The sound's effects render in flight, or None."""
        r = self._renders.get(sid)
        return r if r is not None and r.gen == self._render_gen.get(sid) else None

    def render_words(self, sid: str) -> str:
        """How far its render is, in words: "42%, about 1:10 left"."""
        from soundboard.ui.kit.widgets import fmt_time
        r = self.rendering(sid)
        if r is None:
            return ""
        pct = int(r.frac * 100)
        left = r.left()
        if left is None:
            return _("{pct}%", pct=pct)
        return _("{pct}%, about {time} left", pct=pct, time=fmt_time(max(1.0, left)))

    def _on_progress(self, sid: str, gen: int, frac: float):
        r = self.rendering(sid)
        if r is None or r.gen != gen:
            return   # stopped, or replaced by a newer one (the signal is queued)
        r.frac = max(r.frac, min(1.0, frac))   # never backwards
        p = self.mw.pads.get(sid)
        if p is not None and p.state == "rendering":
            p.render_frac = r.frac
            p.describe()   # a screen reader hears how far (hidden pads aren't painted)
            p.update()
        self._show_render(sid)

    def _show_render(self, sid: str):
        """Its open Edit sound window shows the render (or stops showing one)."""
        d = self._editors.get(sid)
        if d is None or not qt_valid(d):
            return
        r = self.rendering(sid)
        if r is None:
            d.show_render(None)
        else:
            d.show_render(r.frac, self.render_words(sid), r.old_fx is not None)

    def _on_loaded(self, sid: str, data, err: str):
        """A sound (re)loaded: a render that was in flight for it is over."""
        r = self._renders.pop(sid, None)
        if r is None:
            return
        mw = self.mw
        p = mw.pads.get(sid)
        if p is not None:
            p.render_frac = None
            p.update()
        d = self._editors.get(sid)
        m = mw.meta(sid)
        if d is not None and qt_valid(d) and d.render_shown():
            if data is not None:
                d.show_render(None)
                d.reject()   # saved already: closing it now keeps everything
            else:
                d.show_render(None, _("Couldn't apply the effects: {why}", why=err or "?"))
        if data is not None and m is not None and time.monotonic() - r.t0 >= DONE_TOAST_S:
            mw.toast(_("✓ “{name}” is ready to play", name=html.escape(m.name)), "ok")

    def stop_render(self, sid: str) -> bool:
        """The ✕ on a render (the pad, its Edit window): it stops and the sound goes back
        to the effects it had, nothing of the new ones kept."""
        mw = self.mw
        r = self.rendering(sid)
        m = mw.meta(sid)
        if r is None or r.old_fx is None or m is None:
            return False
        del self._renders[sid]
        self._render_gen[sid] += 1   # the render in flight gives up (and leaves no file)
        m.fx = r.old_fx
        mw._save_now()
        p = mw.pads.get(sid)
        if p is not None:
            p.render_frac = None
        old = r.old_data
        if old is not None and len(old):   # the audio it had: straight back
            def back(data=old):
                mw.engine.prepare(sid, data)
                return sid, data, ""
            if p is not None:
                p.state = "loading"
                p.update()
            worker.run(back, mw.bridge.loaded, "fx-back", owner=mw,
                       error=lambda e: (sid, None, errors.plain(e)))
        else:
            self._rerender(m)   # (it wasn't loaded yet: load it as it was)
        self._show_render(sid)
        mw.toast(_("Stopped. “{name}” keeps its old effects", name=html.escape(m.name)), "ok")
        return True
