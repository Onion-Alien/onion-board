"""Settings → Privacy and Data: what goes online, Offline mode, what's kept."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.ui import busy, icons
from soundboard.ui.settingspages import Page, _button_row
from soundboard.wheelguard import no_wheel

log = logging.getLogger(__name__)

# jsengine's names for the engines, as people know them
ENGINE_NAMES = {"deno": "Deno", "node": "Node", "bun": "Bun", "quickjs": "QuickJS"}


class _Found(QObject):
    """Carries what a worker found out about the helper programs to the UI thread."""
    found = Signal(object)


class PrivacyPage(Page):
    """Settings → Privacy and Data: what goes online, Offline mode, what's kept."""

    # ------------------------------------------------------------------ privacy & security
    def _privacy(self):
        w, v = self._page()
        self._switches_card(v)
        v.addWidget(self._online_card())
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ data & quality
    def _data(self):
        """Settings > Data & quality (soundboard.quality): download size, keeping the
        video, radio bitrate and patience, search extras. Each applies at once."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QFileDialog, QSizePolicy

        from soundboard import library, quality
        from soundboard.ui.panel import icon_button
        q = quality.current
        w, v = self._page()
        self.dlg._data_widgets = {}

        card, cv = self._card(_("Local sounds"), icon="folder")
        self.dlg.copy_local_sounds = self._option(
            cv, _("Copy into library"),
            _("Off: link to the original file. Turn on to keep sounds if the original is "
              "moved, deleted or on a disconnected drive. Uses extra disk space. "
              "Applies to new local imports only."),
            self.mw.cfg.copy_local_sounds,
            lambda b: self.mw.set_option("copy_local_sounds", b))
        v.addWidget(card)

        card, cv = self._card(_("Low data mode"),
                              _("For a phone hotspot, capped plan or slow internet: smaller "
                                "downloads, lower-bitrate radio, more patience with stations "
                                "that cut out, and no pictures in web search results. Or pick "
                                "each one below."), icon="leaf")
        self.dlg.data_low = QCheckBox(_("Use less data"))
        self.dlg.data_low.toggled.connect(
            lambda b: self._data_set(**(quality.LOW if b else quality.NORMAL)))
        cv.addWidget(self.dlg.data_low)
        v.addWidget(card)

        card, cv = self._card(_("Downloads"),
                              _("Sounds added from YouTube, SoundCloud and other links. Smaller "
                                "files are about a third of the size (around 0.5 MB a minute "
                                "instead of 1.5 MB) and still sound fine on a pad."),
                              icon="download")
        save_hint = _("Downloads and recordings are saved as this in your Sounds folder. "
                      "MP3 opens anywhere; FLAC is about 7 times bigger and loses nothing. "
                      "Files you add from your PC stay as they are.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel(_("Quality")), 0, 0)
        dl = QComboBox()
        for key, (label, _fmt) in quality.DOWNLOADS.items():
            dl.addItem(label, key)
        dl.currentIndexChanged.connect(lambda _i: self._data_set(download=dl.currentData()))
        dl.setMinimumWidth(dl.sizeHint().width())
        grid.addWidget(dl, 0, 1)
        no_wheel(dl)
        grid.addWidget(QLabel(_("Save sounds as")), 1, 0)
        fmt = QComboBox()
        for key, label in quality.SAVE_FORMATS.items():
            fmt.addItem(label, key)
        fmt.setToolTip(save_hint)
        fmt.currentIndexChanged.connect(lambda _i: self._data_set(save_format=fmt.currentData()))
        fmt.setMinimumWidth(fmt.sizeHint().width())
        grid.addWidget(fmt, 1, 1)
        no_wheel(fmt)
        grid.setColumnStretch(2, 1)
        cv.addLayout(grid)
        hint = QLabel(save_hint)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        cv.addWidget(hint)
        self.dlg._data_widgets["download"] = dl
        self.dlg._data_widgets["save_format"] = fmt
        has_ff = library._ffmpeg() is not None
        self.dlg._data_widgets["save_video"] = self._option(
            cv, _("Also save the video"),
            _("Add as sound keeps a copy of the video too (the pad is still just its sound). "
              "Videos use a lot more data: about 5 to 25 MB a minute.") if has_ff else
            _("Add as sound keeps a copy of the video too (the pad is still just its sound). "
              "Videos use a lot more data: about 5 to 25 MB a minute. Without ffmpeg "
              "installed only lower-quality videos can be saved (usually 360p)."),
            q.save_video, lambda b: self._data_set(save_video=b))
        from soundboard.ui.widgets import widget_at   # (it imports this module)
        hint_lbl = widget_at(cv, cv.count() - 1)   # _option's hint: its words follow FFmpeg
        assert isinstance(hint_lbl, QLabel)
        self.dlg._save_video_hint = hint_lbl
        self.dlg._has_ff = has_ff
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setContentsMargins(26, 0, 0, 0)
        grid.addWidget(QLabel(_("Video quality")), 0, 0)
        vh = QComboBox()
        for h in quality.VIDEO_HEIGHTS:
            vh.addItem(_("Up to {height}p", height=h), h)
        vh.currentIndexChanged.connect(lambda _i: self._data_set(video_height=vh.currentData()))
        vh.setMinimumWidth(vh.sizeHint().width())
        grid.addWidget(vh, 0, 1)
        no_wheel(vh)
        self.dlg._data_widgets["video_height"] = vh
        grid.addWidget(QLabel(_("Save videos in")), 1, 0)
        self.dlg.data_folder = QLabel()
        self.dlg.data_folder.setObjectName("hint")
        self.dlg.data_folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # a path has no spaces to wrap at: it gets cut short instead of widening the page
        self.dlg.data_folder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        grid.addWidget(self.dlg.data_folder, 1, 1, 1, 2)
        row = _button_row()
        change = QPushButton(_("Change"))

        def pick():
            folder = QFileDialog.getExistingDirectory(self.dlg, _("Save videos in"),
                                                      str(quality.current.videos()))
            if folder:
                self._data_set(video_dir=folder)
        change.clicked.connect(pick)
        row.addWidget(change)
        show = icon_button("folder", _("Open folder"), hover=False)

        def open_folder():
            folder = quality.current.videos()
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        show.clicked.connect(open_folder)
        row.addWidget(show)
        grid.addLayout(row, 2, 1, 1, 2)
        grid.setColumnStretch(2, 1)
        cv.addLayout(grid)
        self.dlg._data_video_rows = (vh, change, show, self.dlg.data_folder)
        self.dlg._data_widgets["keep_source"] = self._option(
            cv, _("Remember where it came from"),
            _("Keeps each download's link, channel, upload date, length and views (from the "
              "download itself, nothing extra is fetched), in a text file next to the sound "
              "too. Right-click the sound to open or copy the link. Off: new downloads keep "
              "none of it and the menu hides it; what's already saved stays."),
            q.keep_source, lambda b: self._data_set(keep_source=b))

        v.addWidget(card)

        card, cv = self._card(_("Radio"),
                              _("Lower bitrates use less data: 128 kbps is about 58 MB an hour, "
                                "64 kbps about 29 MB and 32 kbps about 14 MB. With a limit, the "
                                "map and search only show stations at or under it (and ones that "
                                "don't say)."), icon="radio")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel(_("Stations")), 0, 0)
        kb = QComboBox()
        for kbps, label in quality.RADIO_KBPS.items():
            kb.addItem(label, kbps)
        kb.currentIndexChanged.connect(lambda _i: self._data_radio(kb.currentData()))
        kb.setMinimumWidth(kb.sizeHint().width())
        grid.addWidget(kb, 0, 1)
        no_wheel(kb)
        grid.setColumnStretch(2, 1)
        cv.addLayout(grid)
        self.dlg._data_widgets["radio_kbps"] = kb
        self.dlg._data_widgets["patient"] = self._option(
            cv, _("Slow or patchy connection"),
            _("Gives a station longer to start and to come back after it cuts out (on mobile "
              "data or weak Wi-Fi) before the Radio tab gives up on it."),
            q.patient, lambda b: self._data_set(patient=b))
        v.addWidget(card)

        card, cv = self._card(_("Sounds from the web"), icon="search")
        self.dlg._data_widgets["web_extras"] = self._option(
            cv, _("Show pictures"),
            _("Search results load each video's thumbnail. Off: just the titles, a lot less data "
              "per search."),
            q.web_extras, lambda b: self._data_set(web_extras=b))
        v.addWidget(card)
        v.addStretch(1)
        self._data_sync()
        return w

    def _data_set(self, **kw):
        from soundboard import quality
        if self.dlg._data_syncing:
            return
        self.mw.set_option("data", quality.change(**kw))
        self._data_sync()

    def _data_radio(self, kbps):
        """A new bitrate cap: the map's list follows (a lower cap trims the saved list,
        a higher one fetches it again)."""
        from soundboard import quality
        if self.dlg._data_syncing:
            return
        old = quality.current.radio_kbps
        self._data_set(radio_kbps=kbps)
        tab = getattr(self.mw, "radio", None)
        directory = getattr(tab, "dir", None)
        if directory is not None and getattr(tab, "_started", False) and kbps != old:
            directory.load_globe(force=not kbps or bool(old and kbps > old))

    def _data_sync(self):
        """Every control on the page shows quality.current."""
        from soundboard import quality
        q = quality.current
        self.dlg._data_syncing = True
        try:
            self.dlg.data_low.setChecked(q.low_data)
            for key, wdg in self.dlg._data_widgets.items():
                val = getattr(q, key)
                if isinstance(wdg, QComboBox):
                    wdg.setCurrentIndex(max(0, wdg.findData(val)))
                else:
                    wdg.setChecked(val)
            for wdg in self.dlg._data_video_rows:
                wdg.setEnabled(q.save_video)
            self.dlg.data_folder.setText(str(q.videos()))
            self.dlg.data_folder.setToolTip(str(q.videos()))
            self._ffmpeg_sync()
        finally:
            self.dlg._data_syncing = False

    # ------------------------------------------------------------------ helper programs
    def _tools_card(self):
        """Settings > Updates: the programs the app downloads and plays sounds with
        (FFmpeg, yt-dlp, the JavaScript engine, Tor), each with how it is, how it
        updates and its button."""
        from soundboard.ui.panel import heading_row
        card, cv = self._card(_("Helper programs"),
                              _("The programs the app uses to download and play sounds. "
                                "They update with the app, to the exact versions it was "
                                "tested with. Only yt-dlp can update sooner, if you let it."),
                              icon="download")
        # FFmpeg: M4A, AAC and video files need it. The installer offers it once; someone
        # who skipped it had no way to add it later, so the app can get it itself now.
        # Always shown: whether it works (MainWindow.check_ffmpeg), and a way to fix it.
        ff_box = QWidget()
        ff_col = QVBoxLayout(ff_box)
        ff_col.setContentsMargins(0, 0, 0, 0)
        ff_col.setSpacing(6)
        self.dlg.ff_state = QLabel()
        self.dlg.ff_state.setObjectName("pill")       # works / missing / won't start
        self.dlg.ff_state.setProperty("keepline", True)
        # "FFmpeg": a name, the same in every language; the pill right after it
        head, _name, _marks = heading_row("FFmpeg", "video", beside=(self.dlg.ff_state,))
        ff_col.addLayout(head)
        self.dlg.ff_note = QLabel()
        self.dlg.ff_note.setObjectName("hint")
        self.dlg.ff_note.setWordWrap(True)
        ff_col.addWidget(self.dlg.ff_note)
        self.dlg.btn_ffmpeg = QPushButton(_("Get FFmpeg"))
        icons.set_icon(self.dlg.btn_ffmpeg, "download")
        self.dlg.ff_box = ff_box
        ff_col.addWidget(self.dlg.btn_ffmpeg, 0, Qt.AlignmentFlag.AlignLeft)   # buttons sit left
        cv.addWidget(ff_box)
        self.dlg.btn_ffmpeg.clicked.connect(self._get_ffmpeg)
        self._ffmpeg_sync()   # filled now: Updates can open before Data & quality is built
        self._helper_rows(cv)
        return card

    def _ffmpeg_sync(self):
        """The FFmpeg row: whether it works, how far its download is, and Reinstall /
        Get FFmpeg / Fix it. It shows the main window's state (FfmpegControl.news
        calls this), so it and the bar always agree."""
        from soundboard import ffmpegget
        self._video_hint_sync()
        button = getattr(self.dlg, "btn_ffmpeg", None)
        if button is None or not qt_valid(button):
            return
        mw = self.mw
        ff = getattr(mw, "ffctl", None)   # ui/ffmpegcontrol.py
        h = ffmpegget.last()
        working = h is not None and h.state == ffmpegget.OK
        getting = getattr(ff, "getting", False)
        if h is None:
            mw.check_ffmpeg()   # its answer comes back through FfmpegControl.news
            state, tone, label = _("Checking…"), "", _("Get FFmpeg")
            note = _("M4A, AAC and video files need FFmpeg. It's a free download of "
                     "about 100 MB.")
        elif working:
            state = (_("Working: version {version}", version=h.version) if h.version
                     else _("Working"))
            tone, label = "on", _("Reinstall")
            note = _("M4A, AAC and video files play, and videos can be saved. If "
                     "they stop working, reinstall it.")
            if not ffmpegget.is_own(h.path):
                note = " ".join((note, _("It came from winget or another program: that "
                                         "updates it, not the app.")))
            else:
                note = " ".join((note, _("It updates with the app.")))
        elif h.state == ffmpegget.MISSING:
            state, tone, label = _("Missing"), "slow", _("Get FFmpeg")
            note = _("M4A, AAC and video files need FFmpeg. It's a free download of "
                     "about 100 MB.")
        else:
            state, tone, label = _("Won't start"), "slow", _("Fix it")
            note = _("It's installed but won't start ({error}), so M4A, AAC and "
                     "video files won't play. Fix it installs it again.",
                     error=h.why or _("no reason given"))
        pct = getattr(ff, "percent", -1)
        if getting:
            note = (_("Getting FFmpeg… {percent}%", percent=pct) if pct >= 0
                    else _("Getting FFmpeg…"))
        elif ff is not None and ff.error:
            note = ff.error
        elif getattr(ff, "done", False) and working:
            note = _("FFmpeg is ready: M4A, AAC and video files play now.")
        elif not working and ffmpegget.why_not():
            note = "\n".join((note, ffmpegget.why_not()))
        self._pill(self.dlg.ff_state, state, tone)
        self.dlg.ff_note.setText(note)
        if not busy.is_busy(button):
            button.setText(_("Getting FFmpeg…") if getting else label)
            button.setToolTip(_("Download FFmpeg (about 110 MB) so M4A, AAC and video "
                                "files play and videos can be saved"))

    def _video_hint_sync(self):
        """Data & quality's "Also save the video" hint says what FFmpeg changes."""
        from soundboard import ffmpegget
        hint = getattr(self.dlg, "_save_video_hint", None)
        h = ffmpegget.last()
        if hint is None or not qt_valid(hint) or h is None:
            return
        working = h.state == ffmpegget.OK
        if working != self.dlg._has_ff:
            self.dlg._has_ff = working
            hint.setText(
                _("Add as sound keeps a copy of the video too (the pad is still just its "
                  "sound). Videos use a lot more data: about 5 to 25 MB a minute.") if working
                else _("Add as sound keeps a copy of the video too (the pad is still just its "
                       "sound). Videos use a lot more data: about 5 to 25 MB a minute. "
                       "Without ffmpeg installed only lower-quality videos can be saved "
                       "(usually 360p)."))

    @staticmethod
    def _pill(pill: QLabel, text: str, tone: str = ""):
        """A status pill's words and colours: on = works, slow = a problem."""
        pill.setText(text)
        for prop in ("on", "slow"):
            pill.setProperty(prop, "true" if tone == prop else "false")
        pill.style().unpolish(pill)
        pill.style().polish(pill)

    # ---- the other helper programs, under FFmpeg and built like it
    def _helper_row(self, cv, name: str, icon: str):
        """A helper program's row: its icon, name and a status pill, one hint line, then
        (added by the caller) a button on the left. Returns (row, its column, pill, hint)."""
        from soundboard.ui.panel import heading_row
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        pill = QLabel(_("Checking…"))
        pill.setObjectName("pill")
        pill.setProperty("keepline", True)   # one line, whatever its words turn out to be
        head, _name, _marks = heading_row(name, icon, beside=(pill,))
        col.addLayout(head)
        note = QLabel()
        note.setObjectName("hint")
        note.setWordWrap(True)
        col.addWidget(note)
        cv.addWidget(box)
        return box, col, pill, note

    def _helper_rows(self, cv):
        """yt-dlp, the JavaScript engine and Tor (only once it's here). Their versions
        are looked up on workers (_helpers_refresh); the buttons run the Connection
        page's jobs (ConnectionPage._ytdlp_run, _tor_get)."""
        from soundboard import torget, ytdl
        d = self.dlg
        d._ytdlp_msg = d._tor_msg = ""
        left = Qt.AlignmentFlag.AlignLeft   # buttons sit left
        # "yt-dlp" and "Tor": names, the same in every language
        __, col, d.ytdlp_state, d.ytdlp_note = self._helper_row(cv, "yt-dlp", "link")
        auto = self._option(col, _("Update automatically"),
                            _("Once a day and after a failed download, gets a newer "
                              "yt-dlp from PyPI, but only a version the app's makers "
                              "approved that has been out for at least 3 days. Off by "
                              "default."),
                            self.mw.cfg.ytdlp_auto_optin,
                            lambda b: self.mw.set_option("ytdlp_auto_optin", b))
        d.ytdlp_auto_box = auto
        row = _button_row()
        d.ytdlp_btns = []
        # (label, its icon, the English one for the network log, ytdl's job, tooltip)
        for text, icon, logged, job, tip in (
                (_("Update now"), "reload", "Update now", "update",
                 _("Check for a newer yt-dlp and install it")),
                (_("Reinstall"), "download", "Reinstall", "reset",
                 _("Delete the downloaded yt-dlp and its cache, then install a fresh copy"))):
            b = QPushButton(text)
            icons.set_icon(b, icon)
            b.setProperty("tip", tip)
            b.clicked.connect(lambda __=False, j=job, t=logged:
                              d.connection._ytdlp_run(getattr(ytdl, j), t))
            row.addWidget(b)
            d.ytdlp_btns.append(b)
        # for when downloads broke and nothing approved fixes them yet: PyPI's newest
        force = QPushButton(_("Force update"))
        icons.set_icon(force, "alert")
        force.setProperty("quiet", True)
        force.setProperty("tip", _("Install the newest yt-dlp now, even one the app's makers "
                                   "haven't approved yet"))
        force.clicked.connect(self._ytdlp_force_ask)
        row.addWidget(force)
        d.ytdlp_btns.append(force)
        d.ytdlp_force_btn = force
        col.addLayout(row)
        d._ytdlp_row_say = self._ytdlp_row_say

        __, __, d.js_state, d.js_note = self._helper_row(cv, _("JavaScript engine"), "puzzle")

        d.tor_row, col, d.tor_state, d.tor_note = self._helper_row(cv, "Tor", "tor")
        d.tor_row.hide()   # until Tor turns out to be here
        d.tor_row_btn = QPushButton(_("Update Tor"))
        icons.set_icon(d.tor_row_btn, "download")
        d.tor_row_btn.setProperty("tip", _("Download Tor {version} from the Tor Project "
                                           "(dist.torproject.org), the way the Connection "
                                           "setting says", version=torget.VERSION))
        d.tor_row_btn.clicked.connect(self._tor_update)
        col.addWidget(d.tor_row_btn, 0, left)
        d._helpers_refresh = self._helpers_refresh
        self._helpers_offline()
        d.connection._net_sync()   # a download that's switched off: greyed, with why
        self._helpers_refresh()

    def _ytdlp_force_ask(self):
        """Force update's warning: the newest yt-dlp isn't approved yet. Install anyway
        runs ytdl.force_newest like Update now runs ytdl.update."""
        from soundboard import ytdl
        from soundboard.ui import fit
        d = self.dlg
        if any(busy.is_busy(b) for b in d.connection._ytdlp_buttons()):
            return
        box = QDialog(d)
        box.setWindowTitle(_("Install an unapproved yt-dlp?"))
        box.setMaximumWidth(620)
        v = QVBoxLayout(box)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        title = QLabel(_("Install an unapproved yt-dlp?"))
        title.setObjectName("helptitle")
        v.addWidget(title)
        for text, name in (
                (_("Warning: this gets the newest yt-dlp from PyPI right away. Onion Board "
                   "hasn't approved it yet, so nobody has checked it's safe. It may fix "
                   "downloads that stopped working."), ""),
                (_("Use it only when YouTube or another site stopped working and Update now "
                   "doesn't fix it. Reinstall goes back to an approved version."), "hint")):
            label = QLabel(text)
            label.setWordWrap(True)
            if name:
                label.setObjectName(name)
            v.addWidget(label)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        go = QPushButton(_("Install anyway"))
        go.setObjectName("danger")
        go.setDefault(True)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(box.reject)

        def install():
            box.accept()
            if qt_valid(d):
                d.connection._ytdlp_run(ytdl.force_newest, "Force update")
        go.clicked.connect(install)
        row.addWidget(go)
        row.addWidget(cancel)
        v.addLayout(row)
        fit.watch(box)
        box.finished.connect(box.deleteLater)
        d.ytdlp_force_box = box
        box.open()

    def _helpers_refresh(self):
        """Look up what's in use on workers (reading files, starting each engine with
        --version); _helpers_show puts the answers on the rows."""
        self._off_ui(self._files_now, "helpers-files")
        self._off_ui(self._engine_now, "helpers-js")   # slower the first time: on its own

    def _off_ui(self, job, name: str):
        relay = _Found(self.mw)   # outlives this window if it's closed meanwhile

        def got(found):
            relay.deleteLater()
            self._helpers_show(found)
        relay.found.connect(got)
        signal = relay.found   # (taken here: the worker can't touch a deleted relay)

        def run():
            try:
                found = job()
            except Exception:  # noqa: BLE001 - the row says Checking…, never a crash
                log.exception("couldn't look up a helper program")
                found = {}
            busy.emit(signal, found, owner=relay)   # not if the window went meanwhile
        threading.Thread(target=run, daemon=True, name=name).start()

    @staticmethod
    def _files_now() -> dict:
        """yt-dlp's version, and Tor's: (version, a newer one is ready), None if it isn't
        here. Worker thread."""
        from soundboard import tor, torget, ytdl
        found: dict = {"ytdlp": ytdl.active_version(), "tor": None}
        if tor.available():
            where = tor.bundle_dir()
            try:
                version = (where / torget.STAMP).read_text("ascii").split()[0]
            except (OSError, IndexError):
                version = ""   # (from source: scripts/fetch_tor.py's copy may not say)
            found["tor"] = (version, where == torget.bin_dir() and not torget.installed())
        return found

    @staticmethod
    def _engine_now() -> dict:
        """The JavaScript engine yt-dlp gets, or None. Worker thread."""
        from soundboard import jsengine
        engines = jsengine.picked()
        return {"js": engines[0] if engines else None}

    def _helpers_show(self, found: dict):
        from soundboard import jsengine, net, torget
        d = self.dlg
        state = getattr(d, "ytdlp_state", None)
        if state is None or not qt_valid(state):
            return   # Settings was closed meanwhile, or the rows aren't built
        if "ytdlp" in found:
            version, __ = found["ytdlp"]
            if version:
                self._pill(d.ytdlp_state, _("Working: version {version}", version=version), "on")
            else:
                self._pill(d.ytdlp_state, _("Missing"), "slow")
            if not any(busy.is_busy(b) for b in d.ytdlp_btns):
                d.ytdlp_note.setText(d._ytdlp_msg or _(
                    "Gets the sounds from YouTube, SoundCloud and other links. Sites change "
                    "often, so it needs updating now and then."))
        if "js" in found:
            engine = found["js"]
            if engine is None:
                self._pill(d.js_state, _("Not found"), "slow")
                d.js_note.setText(_("YouTube downloads still work, but with fewer formats."))
            elif engine.name == jsengine.QUICKJS:
                self._pill(d.js_state, _("Working: {engine}", engine="QuickJS"), "on")
                d.js_note.setText(_("Lets YouTube downloads get every format. It comes with "
                                    "the app, updates with it and only runs on this PC."))
            else:
                name = ENGINE_NAMES.get(engine.name, engine.name)
                self._pill(d.js_state, _("Working: {engine} {version} (faster)", engine=name,
                                         version=".".join(map(str, engine.version[:2]))), "on")
                d.js_note.setText(_("Lets YouTube downloads get every format. {engine} is on "
                                    "this PC and faster than the app's own, so it's used "
                                    "first. You update {engine} yourself; the app leaves it "
                                    "alone.", engine=name))
        if "tor" in found:
            got = found["tor"]
            d.tor_row.setVisible(got is not None)
            if got is not None:
                version, outdated = got
                self._pill(d.tor_state,
                           _("Installed: version {version}", version=version) if version
                           else _("Installed"), "slow" if outdated else "on")
                if not busy.is_busy(d.tor_row_btn):
                    d.tor_row_btn.setText(_("Update Tor") if outdated else _("Reinstall"))
                    d.tor_note.setText(d._tor_msg or (
                        (_("A newer Tor ({version}) came with this app update. Tor is in "
                           "use (Connection is set to Tor), so press Update Tor when it "
                           "suits you.",
                           version=torget.VERSION) if net.mode() == net.TOR else
                         _("A newer Tor ({version}) came with this app update. The app "
                           "gets it by itself next start, or press Update Tor.",
                           version=torget.VERSION)) if outdated else
                        _("Used when Connection is set to Tor. It's up to date, and updates with "
                          "the app.")))

    def _helpers_offline(self):
        """Offline mode: the buttons that would go online are hidden."""
        from soundboard import net
        tor = getattr(self.dlg, "tor_row_btn", None)
        for b in (*getattr(self.dlg, "ytdlp_btns", ()), tor):
            if b is not None and qt_valid(b):
                b.setVisible(not net.offline())

    def _ytdlp_row_say(self, msg: str, done: bool = False):
        """How Update now is going, on this row too; when it's done, the new version."""
        if not qt_valid(self.dlg.ytdlp_note):
            return
        self.dlg.ytdlp_note.setText(msg)
        if done:
            self.dlg._ytdlp_msg = msg
            self._helpers_refresh()

    def _tor_update(self):
        """Update Tor / Reinstall: the Connection page's Get Tor does it (_tor_get)."""
        d = self.dlg
        d._tor_msg = ""

        def progress(text):
            if qt_valid(d.tor_note):
                d.tor_note.setText(text)

        def done(err):
            d._tor_msg = err   # (it worked: _tor_get has already looked again)
            if err and qt_valid(d.tor_note):
                d.tor_note.setText(err)
        d.connection._tor_get(d.tor_row_btn, progress, done, "Settings > Data & quality")

    def _get_ffmpeg(self):
        """Get FFmpeg, fix it or reinstall it (MainWindow.fix_ffmpeg_clicked: on a worker,
        winget then the app's own download)."""
        from soundboard import ffmpegget
        h = ffmpegget.last()
        self.mw.fix_ffmpeg_clicked(self.dlg.btn_ffmpeg,
                                   force=h is not None and h.state == ffmpegget.OK)

    def _count_eye(self) -> QPushButton:
        """Count me in's eye: opens the table of what it sends (ui/countdialog.py)."""
        eye = QPushButton()
        eye.setObjectName("iconbutton")
        eye.setProperty("quiet", True)
        icons.set_icon(eye, "eye")
        eye.setToolTip(_("See what's sent"))
        eye.setAccessibleName(_("See what's sent"))

        def show():
            from soundboard.ui import countdialog
            self.dlg.count_dialog = countdialog.show(self.dlg)
        eye.clicked.connect(show)
        self.dlg.count_eye = eye
        self.dlg.count_dialog = None   # the dialog show() opens
        return eye

    def _switches_card(self, v=None):
        """Every feature that goes online, each with its own switch (soundboard.net
        enforces them: off means no connection at all, in any Connection mode), and
        Offline mode over all of them."""
        from soundboard import net
        cfg = self.mw.cfg
        card, cv = self._card(
            _("What goes online"),
            _("Onion Board has no account or ads. The only thing it sends us is the anonymous "
              "usage count below, if it's on. These are the only things that go online. Switch "
              "off what you don't want: off means it makes no connection at all, whatever the "
              "Connection setting."), icon="offline")
        self.dlg.offline_box = self._option(
            cv, _("Offline mode"),
            _("Nothing goes online at all, and everything that needs the internet is hidden "
              "(the Radio tab, web search, downloads, updates…). Untick it to pick what may go "
              "online."),
            cfg.net_offline, self._set_offline)
        note = QLabel(_("Not covered by these: links you open in your own browser (Support, "
                        "Report a problem, release pages) and the installer's own downloads."))
        note.setObjectName("hint")
        note.setWordWrap(True)
        cv.addWidget(note)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)
        self.dlg._net_body = body
        self.dlg.net_boxes = {}
        self.dlg._net_subs = {}
        groups = (
            (_("Sounds and radio"), "music", ("sounds_web", "sound_packs", "sound_store", "radio")),
            (_("Voices"), "voice", ("voices", "voice_servers")),
            (_("Updates and add-ons"), "reload", ("app_update", "ytdlp_update", "addons")),
            (_("Setup downloads"), "download",
             ("setup_downloads", "tor_download", "ffmpeg_download")),
            (_("Usage count"), "eye", ("usage_stats",)),
        )
        labels = {"sounds_web": _("Online sounds"), "sound_packs": _("Free sound packs"),
                  "app_update": _("App updates"),
                  "ytdlp_update": _("Downloader updates"), "addons": _("Add-on downloads"),
                  "voices": _("Voice and model downloads"),
                  "voice_servers": _("Online voice servers"),
                  "setup_downloads": _("Virtual cable download"),
                  "tor_download": _("Tor download"),
                  "ffmpeg_download": _("FFmpeg download"),
                  "usage_stats": _("Count me in")}
        for title, icon, keys in groups:
            section, sv = self._card(title, icon=icon)
            for key in keys:
                self.dlg.net_boxes[key] = self._option(
                    sv, labels.get(key) or net.feature_name(key), self.dlg.NET_HINTS[key],
                    key not in cfg.net_off, lambda on, k=key: self._set_feature(k, on),
                    extra=self._count_eye() if key == "usage_stats" else None)
                sub = QWidget()
                sl = QVBoxLayout(sub)
                sl.setContentsMargins(26, 0, 0, 0)
                sl.setSpacing(6)
                self._net_sub_options(key, sl)
                if sl.count():
                    sv.addWidget(sub)
                    self.dlg._net_subs[key] = sub
            bl.addWidget(section)
        if v is not None:
            v.addWidget(card)
            v.addWidget(body)
        else:
            cv.addWidget(body)
        self.dlg.connection._net_sync()
        return card

    def _net_sub_options(self, key: str, sl):
        """The options that belong to one switch, indented under it."""
        from soundboard import net
        cfg = self.mw.cfg
        if key == "sounds_web":
            row = QGridLayout()
            row.setHorizontalSpacing(14)
            for i, (site, name) in enumerate(net.SITES.items()):
                k = f"sounds_web.{site}"
                b = QCheckBox(_("Other links") if site == "other" else name)
                b.setChecked(k not in cfg.net_off)
                b.toggled.connect(lambda on, k=k: self._set_feature(k, on))
                self.dlg.net_boxes[k] = b
                row.addWidget(b, i // 2, i % 2)
            sl.addLayout(row)
            h = QLabel(_("YouTube also covers YouTube Music and the TikTok search button "
                         "(TikTok's own search needs an account, so it finds TikTok sounds on "
                         "YouTube). Other: any other site's link, including pasted TikTok links, "
                         "which still download from TikTok."))
            h.setObjectName("hint")
            h.setWordWrap(True)
            sl.addWidget(h)
        elif key == "radio":
            def count_plays(on: bool):
                cfg.radio["count_plays"] = on
                self.mw.set_option("radio", cfg.radio)   # saves
            self.dlg.plays_box = self._option(
                sl, _("Share play counts"),
                _("Radio Browser ranks stations by how often they're played. Off: starting a "
                  "station only contacts the station itself."),
                bool(cfg.radio.get("count_plays", False)), count_plays)
        elif key in ("app_update", "ytdlp_update"):
            go = QPushButton(_("Update settings"))
            go.clicked.connect(
                lambda: self.dlg.tabs.setCurrentIndex(self.dlg._page_keys.index("updates")))
            sl.addWidget(go, 0, Qt.AlignmentFlag.AlignLeft)

    def _set_feature(self, key: str, on: bool):
        from soundboard import net, usage
        cfg = self.mw.cfg
        was_on = key not in cfg.net_off
        off = [k for k in cfg.net_off if k != key] + ([] if on else [key])
        self.mw.set_option("net_off", off)   # saves
        if key == usage.FEATURE and was_on and not on and net.allowed(key):
            # Count me in switched off: one anonymous "opt-out/settings" goes first
            # (usage.opt_out), and the switch takes hold the moment it's done
            t = threading.Thread(target=usage.opt_out, args=("settings",), daemon=True,
                                 name="usage-opt-out")
            t.start()
            self._opt_out_wait(t, cfg, self.dlg)
            return
        net.configure_features(cfg.net_off, cfg.net_offline)   # applies at once
        self.dlg.connection._net_sync()

    def _opt_out_wait(self, t, cfg, dlg):
        """The switch takes hold even when Settings closed meanwhile; only the page
        that's still open shows it."""
        from soundboard import net
        if t.is_alive():
            QTimer.singleShot(100, lambda: self._opt_out_wait(t, cfg, dlg))
            return
        net.configure_features(cfg.net_off, cfg.net_offline)
        if qt_valid(dlg):
            dlg.connection._net_sync()

    def _set_offline(self, on: bool):
        from soundboard import net
        cfg = self.mw.cfg
        self.mw.set_option("net_offline", on)
        net.configure_features(cfg.net_off, cfg.net_offline)
        self.dlg.connection._net_sync()

    def _online_card(self):
        """What goes online only when you do something, and the app's local doors."""
        card, cv = self._card(
            _("Network information"),
            _("Everything else goes online only when you do it: a search or a pasted link goes "
              "to that site (YouTube, SoundCloud, TikTok, Myinstants), a radio station plays "
              "straight from that station, and a download you press fetches that one file. Those "
              "sites see your IP address like they would in a browser, unless you use a proxy or "
              "Tor (Connection page). The radio maps ship with the app: opening them contacts "
              "nobody."), icon="info")
        remote = QLabel()
        remote.setWordWrap(True)
        on = self.mw.cfg.api_enabled
        remote.setText(_("Remote control is <b>on</b>: scripts and a Stream Deck on this PC can "
                         "play sounds with its key.") if on else
                        _("Remote control is <b>off</b>: nothing else on this PC can control the "
                          "app."))
        go = QPushButton(_("Remote settings"))
        go.clicked.connect(
            lambda: self.dlg.tabs.setCurrentIndex(self.dlg._page_keys.index("remote")))
        cv.addWidget(remote)
        full = QPushButton(_("Network details"))
        full.setToolTip(_("Opens the full list (SECURITY.md) on GitHub, in your browser"))
        from soundboard.updates import REPO
        full.clicked.connect(lambda: busy.open_url(
            f"https://github.com/{REPO}/blob/main/SECURITY.md#what-the-app-does-on-the-network",
            full, self.dlg))
        row = _button_row()   # both under the text, on the left
        row.addWidget(go)
        row.addWidget(full)
        cv.addLayout(row)
        return card

    def _offline_card(self, card: QFrame, online_only=None) -> QFrame:
        """Hide `card` in Offline mode (and show it again after), or, with
        `online_only()`, only while that says it's no use offline."""
        if not hasattr(self.dlg, "_offline_cards"):
            self.dlg._offline_cards = {}
        cards = self.dlg._offline_cards
        cards[card] = online_only or (lambda: True)
        self._offline_hide(card, self._offline_says(cards[card]))
        return card

    @staticmethod
    def _offline_says(online_only) -> bool:
        from soundboard import net
        return net.offline() and online_only()

    @staticmethod
    def _offline_hide(card: QFrame, hide: bool):
        """A card hidden for Offline mode: the search leaves it be (_apply_search)."""
        if bool(card.property("offline_hid")) == hide:
            return
        card.setProperty("offline_hid", hide)
        card.setProperty("search_hid", False)
        card.setVisible(not hide)

    def _offline_sync(self):
        """Offline mode on or off: its pages, cards and tab boxes follow."""
        from soundboard import net
        offline = net.offline()
        self._helpers_offline()
        for card, online_only in list(getattr(self.dlg, "_offline_cards", {}).items()):
            if qt_valid(card):
                self._offline_hide(card, self._offline_says(online_only))
        needs = getattr(getattr(self.mw, "tabctl", None), "needs_online", None)
        for key, box in getattr(self.dlg, "tab_boxes", {}).items():
            if qt_valid(box) and needs is not None:
                box.setEnabled(not needs(key))
                box.setToolTip(_("Needs the internet: Offline mode is on (Privacy & security)")
                               if needs(key) else "")
        note = getattr(self.dlg, "tabs_offline_note", None)
        if note is not None and qt_valid(note):
            note.setVisible(needs is not None and any(needs(k) for k in getattr(
                self.dlg, "tab_boxes", {})))
        for refresh in ("_watch_refresh", "_pocket_refresh"):
            if hasattr(self.dlg, refresh):
                getattr(self.dlg, refresh)()
        keys = getattr(self.dlg, "_page_keys", None)   # None while the dialog is being made
        cats = getattr(self.dlg, "categories", None)
        if keys is None or cats is None or not qt_valid(cats):
            return
        for i, key in enumerate(keys):
            cats.item(i).setHidden(offline and key in self.dlg.OFFLINE_PAGES)
        self.dlg._fold()   # (the advanced rows stay folded away)
        if cats.item(self.dlg.tabs.currentIndex()).isHidden():
            self.dlg.tabs.setCurrentIndex(keys.index("privacy"))
        search = getattr(self.dlg, "search_box", None)
        if (search is not None and search.text().strip()   # it hides what doesn't match
                and not getattr(self.dlg, "_searching", False)):   # (a page built by it)
            self.dlg._apply_search(search.text())
