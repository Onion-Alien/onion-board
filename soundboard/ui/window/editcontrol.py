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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog
from shiboken6 import isValid as qt_valid

from soundboard.audio.engine import SR
from soundboard.core import errors
from soundboard.audio import livefx, renderworker, soundfx
from soundboard import voicefx
from soundboard.sounds import library, videos
from soundboard.i18n import _
from soundboard.sounds.library import SoundMeta, cache_keep, duplicate, load_sound, prune_cache
from soundboard.ui.kit import worker
from soundboard.ui.window.controller import Controller
from soundboard.ui.kit.crashdialog import free_dialog, rehome_crash_reports
from soundboard.ui.sounds.dialogs import EditDialog
from soundboard.ui.sounds.editplayer import EditPlayer
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

PROGRESS_MS = 200      # an in-app render tells the UI how far it is at most this often
ETA_AFTER_S = 3.0      # time left is guessed once it has run this long...
ETA_AFTER_FRAC = 0.03  # ...and done this much of it
DONE_TOAST_S = 2.0     # a render that took longer says so when it's ready
LIVE_WAIT_MS = 450     # a playing sound is made again once its effects stop changing this long
                       # (only for what can't change live: the trim, voice effects…)
PAD_FOLLOW_MS = 250    # open Live controls look for the next song this often
PLAYHEAD_MS = 100      # the trim's playhead moves this often while a sound plays


@dataclass
class Render:
    """A sound's effects render in flight (EditControl._renders)."""
    gen: int
    old_fx: dict | None        # what Stop puts back (None: nothing to go back to)
    old_data: Any = None       # the audio that goes with old_fx, when it was loaded
    keep: bool = False         # the sound plays on meanwhile; the new audio takes over
    frac: float = 0.0          # how far, 0..1
    t0: float = field(default_factory=time.monotonic)

    def left(self) -> float | None:
        """Seconds still to go (a guess from the pace so far), or None: too soon."""
        spent = time.monotonic() - self.t0
        if spent < ETA_AFTER_S or self.frac < ETA_AFTER_FRAC:
            return None
        return spent * (1 - self.frac) / self.frac


def render_fx(m: SoundMeta, cancel, progress) -> Any:
    """The sound's audio with its effects (call off the UI thread): a slow render in
    its own process (renderworker), else here. Raises library.Cancelled when cancel()."""
    data = None
    key = soundfx.key(m.fx)
    if (renderworker.enabled and renderworker.worth_it(m.fx, m.duration)
            and library.load_cached(m.id, key) is None):
        try:   # out of the app's process: no stutter, no lag
            renderworker.render(m, cancel, progress)
            data = library.load_cached(m.id, key)
        except renderworker.Unavailable as e:
            log.info("rendering %s in the app: %s", m.id, e)
    if data is None:
        data = load_sound(m, cancel=cancel, progress=progress)
    return data


@dataclass
class Live:
    """A sound that plays while its Edit sound window changes the effects: what plays
    follows the window's draft (EditControl._live) until Save keeps it or Cancel puts
    the saved one back."""
    saved: Any             # its audio with the saved effects
    saved_key: str         # (soundfx.key of those)
    key: str               # the effects of what plays now (its audio and live stage)
    # its audio (mw.audio) has these effects baked in (soundfx.key); `clean`: none of
    # what runs live (soundfx.live_split) is among them, so any live stage goes on top
    base: str = ""
    clean: bool = False
    stage: tuple | None = None   # the live stage on it now (Engine.set_sound_live)
    gen: int = 0           # the newest render: an older one's answer is dropped
    want: str | None = None   # the base being rendered ("" = plain: a real one)
    fx: dict = field(default_factory=dict)   # the effects baked into its audio: its trim
                                              # says where in the file it is


class EditControl(Controller):
    """The Edit sound windows of one MainWindow (``mw``)."""
    live_ready = Signal(str, int, object)       # id, which change (gen), its audio|None
    live_progress = Signal(str, int, float)     # id, which change (gen), how far 0..1

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._live: dict[str, Live] = {}   # sid -> its playing draft (_live_apply)
        self._live_due: set[str] = set()    # sids whose effects changed: made again soon
        self._preview_due: set[str] = set()   # ...and whose preview follows them, then
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(LIVE_WAIT_MS)
        self._live_timer.timeout.connect(self._live_now)
        self._play_timer = QTimer(self)   # the trim's playhead, while a window is open
        self._play_timer.setInterval(PLAYHEAD_MS)
        self._play_timer.timeout.connect(self._show_playing)
        self.live_ready.connect(self._live_ready)
        self.live_progress.connect(self._live_progress)
        self._editors: dict[str, EditDialog] = {}
        self._render_gen: dict[str, int] = {}   # sid -> newest effects render (_rerender)
        self._renders: dict[str, Render] = {}  # sid -> the render in flight, how far it is
        self._setup_store = None   # voicesetups.Store, read the first time the picker opens
        # Live controls' knobs show every sound's layer plus the playing pad's own
        # effects (_pad_follow): that pad, and what its own effects put on the knobs
        self._pad: str | None = None
        self._pad_base: tuple = soundfx.NO_LIVE_VIEW
        self._pad_timer = QTimer(self)   # while they're open: the next song is followed
        self._pad_timer.setInterval(PAD_FOLLOW_MS)
        self._pad_timer.timeout.connect(self._pad_follow)

    def edit(self, sid, tab: str = "sound"):
        """Edit sound beside the board, not over it: sounds, hotkeys and the other
        pads keep working. It's still a draft: nothing changes until Save, and Cancel
        (or Escape, or closing it) drops it. One window per sound: editing the same
        sound again raises the open one."""
        mw = self.mw
        d = self._editors.get(sid)
        if d is not None and qt_valid(d):
            if tab != "sound":
                d.show_tab(tab)
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
            d.set_advanced(bool(getattr(mw.cfg, "edit_advanced", False)))   # as picked last
            d.load(m, tab)
        else:
            d = self._new_editor(m, tab)
        self._editors[sid] = d
        if d.player is not None:
            self._fill_player(d.player)
        self._play_timer.start()
        self._show_playing()
        self._show_render(sid)
        d.show()
        return d

    def _edit_done(self, sid: str, d: EditDialog, ok: int):
        """An Edit sound window closed: Save puts its draft on the sound (or a copy).
        It's kept for the next sound edited (the first one closed; any more are freed)."""
        mw = self.mw
        if self._editors.get(sid) is d:
            del self._editors[sid]
        d.effects.trim.show_playing(None)
        if not self._editors:
            self._play_timer.stop()
        mw.playctl.drop_preview()                        # a preview still rendering
        mw.engine.stop(f"{sid}:preview")         # and the one playing, either kind
        mw.engine.stop(f"{sid}~fx:preview")
        # the sound as it is now: gone (removed while the window was open: nothing to
        # save it onto), or the same sound in a new object (Undo put it back)
        m = mw.meta(sid)
        self._live_due.discard(sid)
        self._preview_due.discard(sid)
        try:
            if ok and m is not None and d.as_copy:
                self._save_copy(m, d)
            elif ok and m is not None:
                self._save_edits(m, d)
        finally:
            self._live_back(sid)   # not saved: what plays goes back to the saved effects
            if m is not None:      # ...and its volume (Save set the new one already)
                mw.engine.set_gain(sid, mw.gain_for(m))
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
        live = self._live.pop(m.id, None)   # what plays now: kept when it's what's saved
        if live is not None:   # its live stage stays on it until the render swaps in
            mw.engine.set_sound_live(m.id, None, now=False)
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
        new_key = soundfx.key(m.fx)
        now = mw.audio.get(m.id)
        if (live is not None and live.base == new_key and live.stage is None
                and now is not None):
            m.duration = len(now) / SR   # made already: it plays on as it is
        elif new_key != old_key:
            self._rerender(m, old_fx, live.saved if live else None, keep=True)
        elif live is not None and (live.base != live.saved_key or live.stage is not None):
            self._live_put(m.id, live, live.saved, live.saved_key)
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
                       save_hook=self._save_open, stop_render=self.stop_render,
                       advanced=bool(getattr(mw.cfg, "edit_advanced", False)))
        d.hotkeys_changed.connect(mw.hkctl.register_hotkeys)
        d.advanced_changed.connect(lambda on: mw.set_option("edit_advanced", on))
        d.source_forgotten.connect(mw._save_now)
        d.finished.connect(lambda ok, d=d: self._edit_done(d.meta.id, d, ok))
        d.effects.changed.connect(lambda d=d: self._fx_edited(d))
        d.effects.trim.seek_to.connect(lambda t, done, d=d: self._seek(d, t, done))
        d.effects.trim_replaced.connect(   # (another sound: a new trim)
            lambda d=d: d.effects.trim.seek_to.connect(
                lambda t, done, d=d: self._seek(d, t, done)))
        d.effects_reset.connect(lambda d=d: self._live_apply(d.meta.id))   # at once
        d.vol.valueChanged.connect(lambda _v, d=d: self._vol_edited(d))
        p = EditPlayer(mw, d)
        mw.vol_sound.changed.connect(p.set_volume)   # (freed with it: bound slots)
        mw.chk_monitor.toggled.connect(p.set_monitor)
        d.set_player(p)
        return d

    def players(self) -> list[EditPlayer]:
        """The players of the Edit sound windows open now (the board's player sets
        them as it sets its own)."""
        return [d.player for d in self._editors.values()
                if qt_valid(d) and d.player is not None]

    def _fill_player(self, p: EditPlayer):
        """An Edit sound window opened: its player as the board's is now."""
        mw = self.mw
        playctl = mw.playctl
        m = mw.meta(mw.current) if mw.current else None   # (np_name's is cut short)
        p.set_name(m.name if m else mw.np_name.text(), mw.np_name.toolTip())
        p.set_time(mw.np_time.text())
        p.set_icon(mw._pp_icon or "play")
        p.set_enabled(mw.btn_pp.isEnabled())
        p.set_seek(mw.seek.value())
        p.set_volume(mw.vol_sound.value())
        p.set_monitor(mw.chk_monitor.isChecked())
        p.set_chips(list(playctl._chip_groups), playctl._chip)
        p.mark_chip(mw.current)

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
        mw.soundctl.add_to_board(new, after=m)
        self._rerender(new)
        mw.toast(_("✓ Added “{name}”", name=html.escape(new.name)), "ok")
        return new

    # -------------------------------------------- Live controls on the playing pad
    def pad_opening(self):
        """Live controls open: their knobs follow the sound playing (_pad_follow)."""
        self._pad_timer.start()
        self._pad_follow(force=True)

    def pad_closed(self):
        """Closed: the knobs are every sound's layer again (the button's label too)."""
        self._pad_timer.stop()
        if self._pad is None:
            return
        self._pad, self._pad_base = None, soundfx.NO_LIVE_VIEW
        e = self.mw.engine
        self.mw.speed_btn.load(e.sound_speed, e.sound_pitch, e.sound_keep_pitch, e.sound_fx)
        self.mw.speed_btn.set_target(None)

    def _pad_follow(self, force: bool = False):
        """Live controls are one layer on every sound, kept from song to song; their
        knobs show it plus the playing pad's own effects (Edit sound), so they read what
        it sounds like. Bass +3 on the pad and +2 here shows +5; once a plain song
        plays, +2."""
        mw = self.mw
        sid = self.live_sound()
        m = mw.meta(sid) if sid else None
        base = soundfx.NO_LIVE_VIEW
        if (sid is not None and m is not None and sid != LINK_ID
                and mw.engine.state(sid) is not None):
            base = soundfx.live_view(self._playing_fx(sid, m))
        if base == soundfx.NO_LIVE_VIEW:
            sid = None
        if not force and (sid, base) == (self._pad, self._pad_base):
            return
        self._pad, self._pad_base = sid, base
        e = mw.engine
        speed, pitch, own = base
        amounts = dict(e.sound_fx)
        for q in livefx.PARAMS:
            amounts[q.key] = min(max(amounts.get(q.key, 0.0) + own.get(q.key, 0.0), q.lo),
                                 q.hi)
        sp = mw.speed_btn
        sp.load(e.sound_speed * speed, e.sound_pitch + pitch, e.sound_keep_pitch,
                livefx.clean(amounts))
        sp.set_target(m.name if sid is not None and m is not None else None)

    def _playing_fx(self, sid: str, m: SoundMeta) -> dict:
        """The effects `sid` plays with now: its Edit sound window's unsaved ones while
        they're what plays (_live_apply swapped them in), else the saved ones."""
        d, live = self._editors.get(sid), self._live.get(sid)
        if d is not None and qt_valid(d) and live is not None:
            draft = d.effects.fx()
            if soundfx.key(draft) == live.key:
                return draft
        return m.fx

    def speed_changed(self, speed: float, pitch: float, keep: bool):
        """Live controls' speed or pitch, less what the playing pad has of its own."""
        own_speed, own_pitch, _own = self._pad_base
        self.mw.playctl.on_live_speed(speed / own_speed, pitch - own_pitch, keep)

    def fx_changed(self, amounts: dict):
        """Live controls' effects, less what the playing pad has of its own."""
        own = self._pad_base[2]
        layer = dict(amounts)
        for q in livefx.PARAMS:
            layer[q.key] = min(max(amounts.get(q.key, 0.0) - own.get(q.key, 0.0), q.lo),
                               q.hi)
        self.mw.engine.sound_fx = livefx.clean(layer)

    def live_sound(self) -> str | None:
        """The sound Live controls' Save as new pad copies: the one in the player
        (a Community or web search song too: it isn't a pad, and the last pad played
        was copied instead), else the last one played while it's still playing, else
        the newest one playing, else the last one played."""
        mw = self.mw
        if mw.current and mw.meta(mw.current) is not None:
            return mw.current
        last = mw.playctl._last_sid
        playing = [sid for sid in mw.engine.playing() if mw.meta(sid) is not None]
        if last in playing or (not playing and last and mw.meta(last) is not None):
            return last
        return playing[-1] if playing else None

    def new_pad_name(self, name: str) -> str:
        """“Airhorn (modified)”, or “(modified 2)”… when that's taken. A long name is
        shortened so the suffix always fits in the 40 characters a name may have: cut
        off, every try came out as the same taken name and this never returned."""
        taken = {m.name.lower() for m in self.mw.cfg.sounds}
        n = 1
        while True:
            label = (lambda s: _("{name} (modified)", name=s)) if n == 1 else \
                (lambda s, n=n: _("{name} (modified {n})", name=s, n=n))
            new = label(name)
            if len(new) > 40:
                new = label(name[:max(1, len(name) - (len(new) - 40))])[:40]
            if new.lower() not in taken:
                return new
            n += 1

    def _ask_pad_name(self, default: str) -> str | None:
        name, ok = QInputDialog.getText(self.mw, _("Save as new pad"), _("Name:"),
                                        text=default)
        return name.strip()[:40] if ok and name.strip() else None

    def save_live_copy(self) -> SoundMeta | None:
        """Live controls' Save as new pad: a copy of the sound playing with Live
        controls' speed, pitch and effects saved onto it (soundfx.with_live), named by
        the user, right after the original. Live controls stay as they are."""
        mw = self.mw
        sp = mw.speed_btn
        sid = self.live_sound()
        m = mw.meta(sid) if sid else None
        if m is None:
            mw.toast(_("Play a sound first, then save it with your changes"), "warn")
            return None
        if sp.is_default() and not sp.fx_values():
            mw.toast(_("Change the speed, pitch or effects first"), "warn")
            return None
        name = self._ask_pad_name(self.new_pad_name(m.name))
        if not name:
            return None
        e = mw.engine   # the layer itself: the knobs may show the pad's own on top
        fx, capped = soundfx.with_live(m.fx, e.sound_speed, e.sound_pitch,
                                       e.sound_keep_pitch, e.sound_fx)
        link = m.id == LINK_ID
        try:
            new = self._save_link(m, name) if link else duplicate(m, name)
        except OSError as e:
            errors.warn(mw, _("Couldn't copy the sound"), e)
            return None
        if new is None:
            return None
        new.fx = {} if soundfx.is_neutral(fx) else fx
        if not link:
            videos.copy_link(m.id, new.id)
        # a link isn't on the board: at its end, as an added link is
        mw.soundctl.add_to_board(new, after=None if link else m)
        self._rerender(new)
        if capped:   # Redline goes further than a saved sound can
            mw.toast(_("✓ Added “{name}”, its speed and pitch kept to what a pad can save",
                       name=html.escape(new.name)), "ok")
        else:
            mw.toast(_("✓ Added “{name}”", name=html.escape(new.name)), "ok")
        return new

    def _save_link(self, m: SoundMeta, name: str) -> SoundMeta | None:
        """A Community or web search song in the player as a sound of its own: its
        audio written to the library, in its site's folder (Myinstants/…). None: its
        audio is gone (it was stopped meanwhile)."""
        mw = self.mw
        data = mw.audio.get(LINK_ID)
        if data is None:
            mw.toast(_("Play a sound first, then save it with your changes"), "warn")
            return None
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        url = mw.searchctl._link_url
        new, _audio = library.save_clip(
            data, name, library.PAD_COLORS[len(mw.cfg.sounds) % len(library.PAD_COLORS)],
            folder=library.site_folder(url) if url else library.MY_SOUNDS)
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
        mw.soundctl.add_to_board(new, after=m)
        self._rerender(new, m.fx, mw.audio.get(m.id))

    def _rerender(self, m: SoundMeta, old_fx: dict | None = None, old_data=None,
                  keep: bool = False):
        """Load a sound again after its effects changed. They're rendered in the
        background (a slow one in its own process: renderworker); the pad shows how far
        it is until it's ready. old_fx: the effects before, which Stop goes back to (with
        old_data, their audio; the pad's own audio when not given). keep: it plays on
        meanwhile, and the new audio takes over where it is (Save in Edit sound)."""
        mw = self.mw
        prev = self._renders.get(m.id)
        if old_data is None and old_fx is not None:
            old_data = mw.audio.get(m.id)
        keep = keep and mw.engine.state(m.id) is not None
        if not keep:
            mw.engine.stop(m.id)
        mw.audio.pop(m.id, None)
        mw.engine.forget(m.id)
        gen = self._render_gen[m.id] = self._render_gen.get(m.id, 0) + 1
        if prev is not None:   # edited again while rendering: Stop still goes back to
            old_fx, old_data = prev.old_fx, prev.old_data   # how it was before both
        self._renders[m.id] = Render(gen, old_fx, old_data, keep=keep)
        p = mw.pads.get(m.id)
        if p:
            p.state = "rendering"
            p.render_frac, p.can_stop = 0.0, old_fx is not None
            p.update()
        self._show_render(m.id)
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
                data = render_fx(m, cancel, progress)
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

    # ------------------------------------------------- the playing sound follows the draft
    def _fx_edited(self, d: EditDialog):
        """An effect changed in an Edit sound window: a playing sound has it at once
        when it can run live (speed, pitch, Live controls' knobs, boost); what has to be
        baked in is made again once the changes stop for a moment (_live_apply)."""
        sid = d.meta.id
        if self._editors.get(sid) is not d:
            return
        if self._live_apply(sid, render=False):
            self._live_due.add(sid)
            self._live_timer.start()
        if self._preview_playing(sid) is not None:   # the preview follows them too
            self._preview_due.add(sid)
            self._live_timer.start()

    def _vol_edited(self, d: EditDialog):
        """Its volume slider: a playing sound is that loud at once (Cancel puts it back)."""
        mw = self.mw
        m = mw.meta(d.meta.id)
        if self._editors.get(d.meta.id) is d and m is not None:
            mw.engine.set_gain(m.id, mw.gain_for(m, volume=d.vol.value() / 100))

    def _live_now(self):
        due, self._live_due = self._live_due, set()
        for sid in due:
            self._live_apply(sid)
        due, self._preview_due = self._preview_due, set()
        for sid in due:
            self._preview_follow(sid)

    def _preview_playing(self, sid: str) -> tuple[str, float, tuple] | None:
        """(its preview voice, how far through the whole sound it is, what it plays:
        playctl.preview_of) while the sound's preview plays, else None."""
        mw = self.mw
        of = mw.playctl.preview_of.get(sid)
        for psid in (f"{sid}~fx:preview", f"{sid}:preview"):
            st = mw.engine.state(psid)
            if st is not None and of is not None:
                return psid, of[1] + st[0] * of[2], of
        return None

    def _preview_follow(self, sid: str):
        """The window's effects changed while its preview played: it plays them from the
        same spot in the file (the start of what's kept, when that's been cut)."""
        d = self._editors.get(sid)
        now = self._preview_playing(sid)
        if d is None or not qt_valid(d) or now is None:
            return
        _psid, frac, (old_fx, _at, _span) = now
        fx = d.effects.fx()
        if soundfx.key(fx) == soundfx.key(old_fx):
            return
        at = soundfx.moved_frac(old_fx, fx, d.effects.trim.length, frac)
        self.mw.playctl.preview(sid, d.vol.value() / 100, fx, d.fades(), at=at, quiet=True)

    def _seek(self, d: EditDialog, t: float, done: bool):
        """Its waveform's ruler or playhead was dragged to `t` seconds into the file: the
        playing pad or preview goes on from there (or the start of the next part that
        plays). A long sound's preview, which holds only a part, is made again from
        there once the drag lets go."""
        mw = self.mw
        sid = d.meta.id
        m = mw.meta(sid)
        if self._editors.get(sid) is not d or m is None:
            return
        trim = d.effects.trim
        if mw.engine.state(sid) is not None:
            live = self._live.get(sid)
            mw.engine.seek(sid, trim.frac_of(t, live.fx if live is not None else m.fx))
            return
        now = self._preview_playing(sid)
        if now is None:
            return
        psid, _frac, (fx, _at, span) = now
        frac = trim.frac_of(t, fx)
        if span >= 1.0:
            mw.engine.seek(psid, frac)
        elif done:
            mw.playctl.preview(sid, d.vol.value() / 100, fx, d.fades(), at=frac, quiet=True)

    def _moved(self, sid: str, old_fx: dict, new_fx: dict):
        """For Engine.swap: where audio with `new_fx` goes on from, for how far through
        the one with `old_fx` is, when the trim or splices changed; None when they didn't."""
        d = self._editors.get(sid)
        length = d.effects.trim.length if d is not None and qt_valid(d) else 0.0
        same = (soundfx.kept_parts(old_fx, length) == soundfx.kept_parts(new_fx, length)
                and soundfx.clean(old_fx)["reverse"] == soundfx.clean(new_fx)["reverse"])
        if length <= 0 or same:
            return None
        return lambda frac: soundfx.moved_frac(old_fx, new_fx, length, frac)

    def _live_apply(self, sid: str, render: bool = True) -> bool:
        """The sound plays with its Edit sound window's effects. What can run live is
        put on the playing sound at once (Engine.set_sound_live); the rest is baked into
        a new copy in the background (it plays on as it was meanwhile), then swapped in
        at the same spot. Only while it plays, or once it did with the window open.
        render=False: no render is started, True back when one is needed."""
        mw = self.mw
        self._live_due.discard(sid)
        d = self._editors.get(sid)
        m = mw.meta(sid)
        if d is None or not qt_valid(d) or m is None or self.rendering(sid) is not None:
            return False
        fx = d.effects.fx()
        key = soundfx.key(fx)
        live = self._live.get(sid)
        if live is None:
            saved = mw.audio.get(sid)
            if saved is None or mw.engine.state(sid) is None or key == soundfx.key(m.fx):
                return False   # not playing: Save applies them, as it always did
            k = soundfx.key(m.fx)
            live = self._live[sid] = Live(saved, k, k, base=k,
                                          clean=soundfx.live_split(m.fx)[1] is None,
                                          fx=m.fx)
        if key == live.key:
            if live.want is not None:   # changed back while a render was on its way
                live.gen += 1
                live.want = None
            self._live_told(sid, live)
            return False
        if key == live.saved_key:   # back to the saved effects: their audio is here
            self._live_put(sid, live, live.saved, key)
            return False
        base_fx, stage = soundfx.live_split(fx)
        bkey = soundfx.key(base_fx)
        if bkey == live.base and live.clean:   # it all runs live: at once
            self._live_stage(sid, live, stage, key)
            return False
        # the saved one sped up, shifted or louder (plain is made: Reset means plain)
        delta = soundfx.live_delta(m.fx, fx) if key else None
        if delta is not None:
            self._live_put(sid, live, live.saved, key, delta)
            return False
        if live.clean:   # the live part is heard now, the rest once it's made
            self._live_stage(sid, live, stage, live.key)
        if bkey == live.want:
            return False   # being made already
        if not render:
            return True
        self._live_render(sid, live, replace(m, fx=base_fx), bkey)
        return False

    def _live_render(self, sid: str, live: Live, draft: SoundMeta, bkey: str):
        """`draft` (the window's effects less what runs live) made in the background;
        _live_ready puts it on with the live part."""
        live.gen += 1   # a render still going for an older change gives up
        gen = live.gen
        live.want = bkey
        d = self._editors.get(sid)
        if d is not None and qt_valid(d):
            d.show_live(0.0)
        told = [0.0]

        def cancel():
            return self._live.get(sid) is not live or live.gen != gen

        def progress(frac: float):   # (the rendering thread)
            now = time.monotonic()
            if now - told[0] >= PROGRESS_MS / 1000 or frac >= 1.0:
                told[0] = now
                self.live_progress.emit(sid, gen, float(frac))

        def run():
            try:
                data = render_fx(draft, cancel, progress)
            except library.Cancelled:
                return worker.SKIP
            if cancel():
                return worker.SKIP
            self.mw.engine.prepare(sid, data)
            return sid, gen, data

        def failed(e):
            log.warning("can't apply effects to the playing %s: %s", sid, e)
            return sid, gen, None
        worker.run(run, self.live_ready, "fx-live", error=failed, owner=self)

    def _live_progress(self, sid: str, gen: int, frac: float):
        live, d = self._live.get(sid), self._editors.get(sid)
        if (live is not None and live.gen == gen and live.want is not None
                and d is not None and qt_valid(d)):
            d.show_live(frac)

    def _live_ready(self, sid: str, gen: int, data):
        live = self._live.get(sid)
        if live is None or live.gen != gen or live.want is None:
            return   # saved, cancelled or changed again meanwhile
        bkey, live.want = live.want, None
        d = self._editors.get(sid)
        if data is None:
            if d is not None and qt_valid(d):
                d.show_live(None, _("Couldn't apply the effects to the playing sound"))
            return
        fx = d.effects.fx() if d is not None and qt_valid(d) else {}
        base_fx, stage = soundfx.live_split(fx)
        self._live_put(sid, live, data, soundfx.key(fx), stage, base=bkey, clean=True)

    def _live_stage(self, sid: str, live: Live, stage: tuple | None, key: str):
        """What plays gets this live stage on the audio it has: heard at once."""
        live.key, live.stage = key, stage
        self.mw.engine.set_sound_live(sid, stage)
        self._live_told(sid, live)

    def _live_put(self, sid: str, live: Live, data, key: str, stage: tuple | None = None,
                  base: str | None = None, clean: bool = False):
        """What plays (and plays next) becomes `data` with `stage` live on top, the
        sound with effects `key`. `data` has effects `base` baked in (`clean`: none of
        the live kind); when not given, it's the saved audio."""
        mw = self.mw
        if base is None:
            m = mw.meta(sid)
            base = live.saved_key
            clean = soundfx.live_split(m.fx if m is not None else {})[1] is None
        live.key, live.stage = key, stage
        if live.want is not None:   # a render on its way for an older change gives up
            live.gen += 1
            live.want = None
        if data is not mw.audio.get(sid) or base != live.base:
            live.base, live.clean = base, clean
            mw.audio[sid] = data
            mw.engine.set_sound_live(sid, stage, now=False)   # the old copy keeps its own
            m = mw.meta(sid)
            d = self._editors.get(sid)
            new_fx = (m.fx if m is not None else {}) if data is live.saved else (
                d.effects.fx() if d is not None and qt_valid(d) else live.fx)
            mw.engine.swap(sid, data, self._moved(sid, live.fx, new_fx))
            live.fx = new_fx
        else:
            mw.engine.set_sound_live(sid, stage)
        self._live_told(sid, live)

    def _live_told(self, sid: str, live: Live):
        """Its window says the playing sound has the changes (or nothing, at the
        saved ones), unless a render is still on its way."""
        d = self._editors.get(sid)
        if d is not None and qt_valid(d) and live.want is None:
            d.show_live(None, _("✓ The playing sound has your changes. Cancel puts it back.")
                        if live.key != live.saved_key else "")

    def _live_back(self, sid: str):
        """The window closed without saving: the sound goes back to its saved audio."""
        live = self._live.pop(sid, None)
        if live is None:
            return
        live.gen += 1
        mw = self.mw
        if mw.audio.get(sid) is not live.saved:
            mw.audio[sid] = live.saved
            mw.engine.set_sound_live(sid, None, now=False)
            m = mw.meta(sid)
            mw.engine.swap(sid, live.saved,
                           self._moved(sid, live.fx, m.fx) if m is not None else None)
        elif live.stage is not None:
            mw.engine.set_sound_live(sid, None)   # its live stage fades out

    def _show_playing(self):
        """Each open window's trim shows where its sound is playing: the pad (with the
        draft's effects once they're swapped in, else the saved ones) or its preview."""
        mw = self.mw
        for sid, d in list(self._editors.items()):
            if not qt_valid(d):
                continue
            m = mw.meta(sid)
            st = mw.engine.state(sid)
            live = self._live.get(sid)
            if st is not None:   # the pad: what plays follows the draft once it's put on
                frac, fx = st[0], live.fx if live is not None else (m.fx if m else {})
            else:   # its preview, to headphones (a long sound's: a part of it)
                now = self._preview_playing(sid)
                frac, fx = (None, {}) if now is None else (now[1], now[2][0])
            d.effects.trim.show_playing(frac, fx)
            d.bun.set_playing(frac is not None)   # Bun mixes along while it plays

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
        if r.keep and data is not None:
            mw.engine.swap(sid, data)   # it played on meanwhile: the new one takes over
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
