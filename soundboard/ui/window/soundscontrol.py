"""The board's sounds coming in, in the main window: loading them all (decoded on a worker,
the cache kept), each one's audio arriving, a clip or a recording made into a sound, one
downloaded from a link, moving a pad to another place, and renaming one.

MainWindow makes one ``SoundsControl`` (``MainWindow.soundctl``); everything here runs on
the UI thread except the decoding it hands to a worker."""
from __future__ import annotations

import html
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog

from soundboard.core import errors, trash, usage
from soundboard.sounds import library, thumbs
from soundboard.audio.engine import SR
from soundboard.i18n import _
from soundboard.sounds.library import (
    PAD_COLORS,
    SoundMeta,
    cache_keep,
    fingerprint,
    load_sound,
    prune_cache,
    save_clip,
)
from soundboard.ui.kit import worker
from soundboard.ui.window.controller import Controller
from soundboard.ui.kit.crashdialog import free_dialog
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)


class SoundsControl(Controller):
    """Loading and adding the sounds of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._load_thread: threading.Thread | None = None
        self._loading: set[str] = set()   # sids a load thread is decoding right now
        self._tidied = False   # the first load took out unfinished adds' files

    def _load_all(self):
        # one still being loaded by an earlier call (a pack import or Undo during a slow
        # first load) isn't decoded again: two writers of one cache file garble it
        mw = self.mw
        todo = [m for m in mw.cfg.sounds if m.id not in mw.audio and m.id not in self._loading]
        self._loading.update(m.id for m in todo)
        # once, and only with the settings as they were saved: a backup may not know the
        # newest sounds (their files aren't leftovers)
        tidy_adds = not (self._tidied or mw.cfg.read_only or mw.cfg.load_note)
        self._tidied = True
        prev = self._load_thread

        def run():
            t0 = time.monotonic()
            for m in todo:
                try:
                    data = load_sound(m)   # from the cache after the first run
                    mw.engine.prepare(m.id, data)
                    mw.bridge.loaded.emit(m.id, data, "")
                except Exception as e:  # noqa: BLE001
                    log.warning("can't load %s: %s", m.file, e)
                    mw.bridge.loaded.emit(m.id, None, errors.plain(e))
                finally:
                    self._loading.discard(m.id)
            if prev is not None:   # done only once the sounds it skipped are, too
                prev.join()
            live = self._live_metas()   # as of now, not of the start
            prune_cache(cache_keep(live))
            if tidy_adds:   # files of adds an earlier run didn't finish (it was closed)
                library.drop_unfinished([m.file for m in live])
            thumbs.prune({m.image for m in live if m.image})
            trash.prune()   # what's been in Recently deleted for too long
            log.info("loaded %d sounds in %.1fs", len(todo), time.monotonic() - t0)
        self._load_thread = worker.run(run, name="load")

    def on_loaded(self, sid, data, err):
        # removed while it was loading (the index can lag behind cfg.sounds: check both)
        mw = self.mw
        if (sid != LINK_ID and sid not in mw._meta
                and all(m.id != sid for m in mw.cfg.sounds)):
            for i, (m, index, _d) in enumerate(mw.rmctl._removed):
                if m.id == sid:   # still undo-able: keep the audio with it
                    mw.rmctl._removed[i] = (m, index, data)
                    return
            mw.engine.forget(sid)   # gone for good: don't keep its audio around
            return
        p = mw.pads.get(sid)
        if data is not None:
            mw.audio[sid] = data
            m = mw.meta(sid)
            if m and abs(m.duration - len(data) / SR) > 0.005:   # effects change the length
                m.duration = len(data) / SR
                mw._save_later()
            if m and not m.fingerprint:   # sounds imported before fingerprints existed
                m.fingerprint = fingerprint(m.file)
                mw._save_later()
        if p:
            p.state = "ready" if data is not None else "error"
            p.error = err
            p.update()
        if data is not None:
            mw.playctl.loaded(sid)   # pressed while it loaded: it plays now

    def _live_metas(self) -> list[SoundMeta]:
        """Every sound whose files must be kept: the library, and removed ones that
        can still be undone."""
        mw = self.mw
        return list(mw.cfg.sounds) + [m for m, _i, _d in list(mw.rmctl._removed)]

    def add_to_board(self, meta: SoundMeta, after: SoundMeta | None = None):
        """A new sound on the board, in the category showing (_tag_new), right after
        `after` or at the end: saved, and its pad made."""
        mw = self.mw
        mw.catctl._tag_new(meta)
        if after is None:
            mw.cfg.sounds.append(meta)
        else:
            mw.cfg.sounds.insert(mw.cfg.sounds.index(after) + 1, meta)
        mw._save_now()
        mw._rebuild_pads()

    def on_clip(self, data, name) -> SoundMeta | None:
        """A clip recorded in the Radio or Apps tab (or with the mic) becomes a normal
        sound pad."""
        mw = self.mw
        try:
            meta, data = save_clip(data, name, PAD_COLORS[len(mw.cfg.sounds) % len(PAD_COLORS)])
        except Exception as e:  # noqa: BLE001
            log.exception("can't save clip")
            src = self.sender()
            if src is not None and hasattr(src, "clip_error"):
                src.clip_error = errors.plain(e)   # pyright: ignore[reportAttributeAccessIssue]  # the tab says so on its row (hasattr)
            else:
                errors.warn(mw, _("Couldn't save clip"), e)
            return None
        mw.audio[meta.id] = data
        usage.used("clip")
        usage.step(mw.cfg, "added-sound")
        worker.run(lambda: mw.engine.prepare(meta.id, data), name="prepare")
        self.add_to_board(meta)
        mw.toast(_("Added “{name}” ({duration:.1f}s) to Sounds: right-click it there "
                     "to rename or set a hotkey.",
                     name=html.escape(meta.name), duration=meta.duration), "ok")
        return meta

    def record_dialog(self, quick: bool = False):
        """Sounds tab → Record: record a sound with the mic, or a bit of what's playing.
        The window doesn't block the board: pads, web results, the radio and Space
        still work while it's open (to play what's being recorded). `quick` (the Voice
        tab's Record): it starts recording your voice straight away."""
        mw = self.mw
        from soundboard.ui.sounds.recordmic import RecordDialog
        d = getattr(self, "_record_dlg", None)
        if d is not None:   # already open: bring it forward
            d.raise_()
            d.activateWindow()
            return
        voice = getattr(mw, "voice", None)

        def voice_on() -> bool:
            on = getattr(voice, "is_active", None)
            return bool(on()) if on is not None else False

        def open_devices():
            mw.tabs.setCurrentWidget(mw.setup_page)

        recs = getattr(voice, "recordings", None) if quick else None
        if recs is not None:
            names = lambda: [c.name for c in recs.shelf.snapshot()]  # noqa: E731

            def save(data, name, picture: str = "") -> bool:
                """The Voice tab's Record keeps it in the tab's Recordings."""
                try:
                    recs.add(data, name, _("My changed voice")
                             if RecordDialog.last_source == "fx" else _("My voice"))
                except OSError as e:
                    errors.warn(mw, _("Couldn't save clip"), e)
                    return False
                recs.title.setChecked(True)
                recs.list.setFocus()
                return True
        else:
            names, save = (lambda: [m.name for m in mw.cfg.sounds]), self.add_recording
        d = RecordDialog(mw.engine, voice_on, names, save, open_devices, mw,
                         playing_name=self._playing_name,
                         playing_picture=self._playing_picture)
        self._record_dlg = d

        def closed(_r):
            self._record_dlg = None
            # after its own signal returns; tied to `d`, so nothing runs if the window
            # (and the dialog with it) is gone first
            QTimer.singleShot(0, d, lambda: free_dialog(d))
        d.finished.connect(closed)
        d.setModal(False)
        d.show()
        if quick:
            d.quick_start()

    def _playing_name(self) -> str:
        """What's playing now, for naming a recording of it: the player's sound (a pad
        or a web result) or the radio station; "" for nothing."""
        mw = self.mw
        sid = mw.current
        st = mw.engine.state(sid) if sid else None
        if st is not None and not st[1]:
            m = mw.meta(sid)
            if m is not None:
                return m.name
        station = getattr(getattr(mw.radio, "player", None), "station", None)
        return station.name if station is not None else ""

    def _playing_picture(self) -> str:
        """The picture of the pad playing now ("" for none, or not a pad), for a
        recording of it."""
        mw = self.mw
        sid = mw.current
        st = mw.engine.state(sid) if sid else None
        m = mw.meta(sid) if st is not None and not st[1] else None
        return m.image if m is not None and m.image and Path(m.image).is_file() else ""

    def add_recording(self, data, name, picture: str = "") -> bool:
        """A mic recording becomes a pad: selected, scrolled to, and a toast says so.
        `picture`: the picture of the pad it was recorded from (copied onto it)."""
        mw = self.mw
        meta = self.on_clip(data, name)
        if meta is None:
            return False
        if picture and thumbs.set_image(meta, picture):
            mw._save_now()
            if meta.id in mw.pads:
                mw.pads[meta.id].update()
        usage.used("record")
        mw.playctl.select(meta.id)

        def reveal():   # once the grid has laid the new pad out
            pad = mw.pads.get(meta.id)
            if pad is not None:
                mw._pads_scroll.ensureWidgetVisible(pad)
        QTimer.singleShot(0, mw._pads_scroll, reveal)   # not after the window's gone
        mw.toast(_("✓ Added “{name}”", name=html.escape(meta.name)), "ok")
        return True

    def on_downloaded(self, meta, data):
        """"Add as sound" (link bar / web search) finished: already decoded, stored and
        prepared."""
        mw = self.mw
        mw.audio[meta.id] = data
        usage.used("youtube")
        usage.step(mw.cfg, "added-sound")
        self.add_to_board(meta)
        mw.toast(_("Added “{name}” ({duration:.1f}s) to Sounds: right-click it there "
                     "to rename or set a hotkey.",
                     name=html.escape(meta.name), duration=meta.duration), "ok")

    def on_reorder(self, sid, target):
        mw = self.mw
        m = mw.meta(sid)
        if not m:
            return
        if mw.cfg.pad_sort != "custom":   # the drop index is into the sorted pads
            mw.toast(_("The pads are sorted {how}: pick “My order” (the ⇣ button by the "
                         "search box) to drag them into place.",
                         how=mw.padctl._sort_names()[mw.cfg.pad_sort]))
            return
        mw.cfg.sounds.remove(m)
        mw.cfg.sounds.insert(min(target, len(mw.cfg.sounds)), m)
        mw._save_now()
        mw._rebuild_pads()

    def rename_sound(self, sid: str, new: str | None = None):
        """F2 on a pad (and the pad menu's Rename): just the name, without the Edit
        window."""
        mw = self.mw
        m = mw.meta(sid)
        if m is None:
            return
        if new is None:
            new, ok = QInputDialog.getText(mw, _("Rename sound"), _("New name:"), text=m.name)
            if not ok:
                return
        typed = library.one_line(new)
        new = typed[:library.SOUND_NAME_MAX].strip()
        if not new:   # an empty box (or only spaces) did nothing and said nothing
            mw.toast(_("Type a name first."), "warn")
            return
        if new == m.name:
            return
        m.name = new
        if sid in mw.pads:
            mw.pads[sid].update()
        if mw.current == sid:
            mw._set_np_name(new)
        mw._save_now()
        if len(typed) > len(new):
            mw.toast(_("Names can be up to {n} characters, so it's “{name}”.",
                       n=library.SOUND_NAME_MAX, name=html.escape(new)), "warn")
        elif any(o is not m and o.name.lower() == new.lower() for o in mw.cfg.sounds):
            # allowed (two takes of one clip), but two pads called the same are easy to mix up
            mw.toast(_("✓ Renamed to “{new}”. Another sound has that name too.",
                       new=html.escape(new)), "ok")
        else:
            mw.toast(_("✓ Renamed to “{new}”", new=html.escape(new)), "ok")
