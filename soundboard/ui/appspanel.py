"""The Apps tab: send one running program's sound (a music player, a browser, a
game, a call in another app) out to others (the cable, another device or the
stream output, like your sounds), without touching what any other program plays.
Each program is a card: its level, a **Send** switch, its own volume and *Hear it
myself*, and **Record**, which waits for the program to make a sound, records it
until you click again and adds it to your Sounds as a pad. Folded away at the
bottom of each card is its *Clip editor* (soundboard.ui.clipeditor): opened, it
keeps the program's last minute as a live waveform to cut bits out of; closed,
nothing of it runs. Its Save puts the bit in *Saved clips* under the cards
(soundboard.ui.clipshelf), and its Big view button gives one card the whole tab.

The capture is Windows' per-process loopback (soundboard.appaudio), a *copy* of
the program's audio: the program keeps playing on your speakers. Programs you
switch on are remembered by their .exe and folder (path_key), and picked up again
next time they run.
"""
from __future__ import annotations

import dataclasses
import logging
import math
import os
import re
import threading
import time
import zlib

from PySide6.QtCore import QFileInfo, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileIconProvider, QFrame, QHBoxLayout, QLabel,
                               QLayout, QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

from soundboard import appaudio, errors, library, theme, trash
from soundboard.clipedit import LiveBuffer
from soundboard.engine import SR
from soundboard.library import MAX_SECONDS, trim_silence
from soundboard.recorder import ArmedRecorder
from soundboard.ui import appstate, icons
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.clipeditor import WAVE_H, ClipEditor
from soundboard.ui.clipshelf import ClipShelf
from soundboard.ui.panel import CardGrid, HoverCard, UndoBar, VolumeControl, hint_label
from soundboard.ui.responsive import FitWidth
from soundboard.wheelguard import no_wheel

log = logging.getLogger(__name__)

REFRESH_MS = 1500       # how often the list of programs is re-read while the tab is shown
REFRESH_HIDDEN_MS = 5000   # ...and while it isn't (a remembered program still gets picked up)
METER_MS = 60
MAX_REMEMBERED = 30
CARD_MIN_W = 300        # programs are cards, as many across as fit at this width
CARD_MAX_W = 900        # the Card size slider's widest: one big card across most windows
MAX_VOL = 10.0          # 1000 %, the most the volume box takes
CONNECTING = "Connecting…"   # a card's status while its capture is starting
# where a sent program goes (cfg.apps[exe]["to"], cfg.apps_paths[path]["to"]): the
# choice shows once a stream output is set (Settings → Audio), or while it's set to
# anything but both
TO = (("both", "Call + stream", "Others in the call and your stream output both get it"),
      ("call", "Call only", "Only others in the call get it, not your stream output"),
      ("stream", "Stream only", "Only your stream output gets it (music for your viewers), "
                                "not the call"))
TO_KEYS = tuple(k for k, *_ in TO)


# a version folder in a program's path (Discord's app-1.0.9156, 24.1.3): it changes on
# every update, so it doesn't count when telling two programs of the same name apart
_VERSION_DIR = re.compile(r"(app-)?v?\d+(\.\d+)+([-_+][\w.]*)?", re.I)


def path_key(path: str) -> str:
    """How a program's .exe path is remembered: lower case, version folders as *."""
    parts = re.split(r"[\\/]+", path.lower())
    return "\\".join("*" if _VERSION_DIR.fullmatch(p) else p for p in parts)


def is_path_key(key: str) -> bool:
    """A row / remembered key that is a path (cfg.apps_paths), not an .exe name."""
    return "\\" in key


def saved_volume(v) -> float:
    """A remembered program's volume from the config, whatever was written there."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return min(max(v, 0.0), MAX_VOL) if math.isfinite(v) else 1.0


class _Lister(QObject):
    """Reads the audio sessions off the UI thread (COM, ~50 ms) and hands the result
    to it: `peaks`' next rescan makes the list while that watcher runs (it was finding
    the same sessions on its own), else a worker thread of its own does."""
    ready = Signal(object)

    def __init__(self, parent=None, peaks: appaudio.PeakWatcher | None = None):
        super().__init__(parent)
        self.peaks = peaks
        self._busy = False
        self._stopped = False

    def refresh(self):
        if self._busy or self._stopped:
            return
        self._busy = True
        if self.peaks is not None and self.peaks.list_for(self._listed):
            return
        threading.Thread(target=self._work, name="applist", daemon=True).start()

    def _work(self):
        alive: dict[int, str] = {}   # every process, from the listing's own process list
        apps = None
        try:
            apps = appaudio.list_apps(strict=True, alive=alive)
        except appaudio.ComError:
            log.debug("listing programs failed", exc_info=True)
        except Exception:  # noqa: BLE001
            log.exception("listing programs failed")
        self._listed(apps, alive)

    def _listed(self, apps: list | None, alive: dict[int, str] | None):
        """On the worker's or the level watcher's thread. apps None: the listing failed,
        and this round is skipped (an empty list would stop every capture and drop
        the rows)."""
        self._busy = False
        if apps is not None and not self._stopped:
            self.ready.emit((apps, alive))

    def stop(self):
        self._stopped = True


class ElidedLabel(QLabel):
    """A one-line label that ends in "…" when it doesn't fit (the full text in its
    tooltip), instead of being cut off mid-word. With `hide_overflow` it shows nothing
    instead: for interface text half a phrase only looks broken."""

    def __init__(self, text: str = "", hide_overflow: bool = False):
        super().__init__(text)
        self.hide_overflow = hide_overflow

    def paintEvent(self, e):
        text = self.text()
        r = self.contentsRect()
        shown = self.fontMetrics().elidedText(text, Qt.ElideRight, r.width())
        if shown != text and self.hide_overflow:
            shown = ""
        tip = text if shown != text else ""
        if tip != self.toolTip():   # every paint (meters, hover): only when it changes
            self.setToolTip(tip)
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(r, int(self.alignment() | Qt.AlignVCenter), shown)


def _route(src, to: str):
    """Point a sent program (engine.AuxSource) at the call, the stream or both."""
    src.live = to in ("both", "call")
    src.stream = to in ("both", "stream")


class AppRow(HoverCard):
    """One program, as a card: icon and name, its level, Send and Record, volume and
    Hear it myself."""
    send_toggled = Signal(object, bool)     # row, on
    rec_toggled = Signal(object, bool)
    vol_changed = Signal(object, float)
    hear_toggled = Signal(object, bool)
    to_changed = Signal(object, str)        # row, one of TO_KEYS
    clip_toggled = Signal(object, bool)     # row, the clip editor opened / closed
    forget = Signal(object)

    def __init__(self, exe: str, meter_cls, vol: float = 1.0, hear: bool = False,
                 to: str = "both", key: str = "", path: str = ""):
        super().__init__()
        self.exe = exe
        self.key = key or exe.lower()   # AppsTab.rows' key: the .exe, or a path_key
        self.path = path                # path_key of the program it is ("" not known yet)
        self.folder = ""                # shown after the name: two programs share it
        self.app: appaudio.App | None = None
        self.capture: appaudio.AppCapture | None = None
        self.remember_pending = False   # Send clicked: remembered once the capture is up
        self.src = None                 # engine.AuxSource while sending
        self.rec: ArmedRecorder | None = None   # while Record is on
        self.listen: LiveBuffer | None = None   # while the clip editor is open
        self.editor: ClipEditor | None = None   # made the first time it's opened
        self.status_text = ""
        self.status_error = False
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(28, 28)
        self.icon.setAlignment(Qt.AlignCenter)
        top.addWidget(self.icon)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.name = ElidedLabel(exe)
        bold = self.name.font()   # not a style sheet: each one re-styles the widget
        bold.setWeight(QFont.DemiBold)
        self.name.setFont(bold)
        self.sub = ElidedLabel()
        self.sub.setObjectName("hint")
        for lbl in (self.name, self.sub):   # long titles give way instead of widening the card
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lbl.setTextFormat(Qt.PlainText)   # window titles are set by web pages
        names.addWidget(self.name)
        names.addWidget(self.sub)
        top.addLayout(names, 1)
        self.btn_forget = QPushButton("✕")
        self.btn_forget.setObjectName("small")
        self.btn_forget.setToolTip("Take this program off the list")
        self.btn_forget.setFixedWidth(26)
        self.btn_forget.clicked.connect(lambda: self.forget.emit(self))
        top.addWidget(self.btn_forget, 0, Qt.AlignTop)
        v.addLayout(top)
        self.meter = meter_cls()
        self.meter.setMinimumWidth(60)
        self.meter.setToolTip("What the program is playing")
        v.addWidget(self.meter)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.btn_send = QPushButton()
        self.btn_send.setObjectName("live")
        self.btn_send.setCheckable(True)
        self.btn_send.setToolTip("Send this program's sound out to others, the way your "
                                 "sounds go (Setup tab)")
        icons.set_icon(self.btn_send, "live", checked_color="#ffffff")
        self.btn_send.toggled.connect(lambda on: self.send_toggled.emit(self, on))
        self.btn_rec = QPushButton("Record")
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip("Record this program: it waits for the program to make a "
                                "sound, then records until you click again, and the clip is "
                                "added to your Sounds. Nobody hears it unless Send is on.")
        icons.set_icon(self.btn_rec, "record", "#ff4d4f", "#ffffff", size=14)
        self.btn_rec.toggled.connect(lambda on: self.rec_toggled.emit(self, on))
        for b in (self.btn_send, self.btn_rec):
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            buttons.addWidget(b)
        self.cb_to = QComboBox(self)   # hidden/shown before its row is laid out: no flash
        for i, (key, label, tip) in enumerate(TO):
            self.cb_to.addItem(label, key)
            self.cb_to.setItemData(i, tip, Qt.ToolTipRole)
        self.cb_to.setToolTip("Where this program's sound goes when Send is on")
        self.cb_to.setCurrentIndex(TO_KEYS.index(to) if to in TO_KEYS else 0)
        self.cb_to.currentIndexChanged.connect(lambda _i: self.to_changed.emit(self, self.to))
        no_wheel(self.cb_to)
        self.cb_to.setVisible(self.to != "both")
        buttons.addWidget(self.cb_to)
        v.addLayout(buttons)
        mix = QHBoxLayout()
        mix.setSpacing(8)
        self.vol = VolumeControl(vol, tip="This program's volume in the mix")
        self.vol.slider.setMaximumWidth(16777215)   # the card's width, not a row's sliver
        self.vol.changed.connect(lambda v: self.vol_changed.emit(self, v))
        mix.addWidget(self.vol, 1)
        self.chk_hear = QCheckBox("Hear it myself")
        self.chk_hear.setToolTip("Also play it into your headphones (off: the program already "
                                 "plays there on its own)")
        self.chk_hear.setChecked(hear)
        self.chk_hear.toggled.connect(lambda on: self.hear_toggled.emit(self, on))
        mix.addWidget(self.chk_hear)
        v.addLayout(mix)
        self.btn_clip = QPushButton("Clip editor")
        self.btn_clip.setObjectName("fold")
        self.btn_clip.setCheckable(True)
        self.btn_clip.setToolTip("Keep this program's last minute as a waveform you can cut "
                                 "bits out of, play, save as sounds or send straight back. "
                                 "It only listens while it's open.")
        icons.set_icon(self.btn_clip, "fold", "muted", "text", size=12)
        self.btn_clip.toggled.connect(lambda on: self.clip_toggled.emit(self, on))
        v.addWidget(self.btn_clip, 0, Qt.AlignLeft)
        self._tight = 0   # how many of _TIGHTEN are applied (a narrow window)
        self._label_send()
        self.set_app(None)

    NAME_ROOM = 0    # the name has its own line in the card: nothing to keep room for
    # narrow card, in this order: the typed volume goes, the buttons keep only their
    # icons (their tooltips say what they are), "Hear it myself" becomes "Hear"
    _TIGHTEN = ("spin", "send", "rec", "hear")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # only a new width: tightening changes the card's height (the typed volume is
        # taller than the slider), and refitting on that made the cards flip between
        # tight and full forever, jumping up and down
        if e.size().width() != e.oldSize().width():
            self._fit_width(self.width())

    def _needs(self) -> int:
        """The card's narrowest width as it is now, measured fresh: the rows cache
        their sizes, and a stale one picked a different tightness on each pass."""
        for lay in self.findChildren(QLayout):
            lay.invalidate()
        return self.minimumSizeHint().width() + self.NAME_ROOM

    def _fit_width(self, width: int):
        want = 0
        while want < len(self._TIGHTEN):
            self._set_tight(want)
            if self._needs() <= width:
                break
            want += 1
        self._set_tight(want)

    def _set_tight(self, n: int):
        if n == self._tight:
            return
        self._tight = n
        on = set(self._TIGHTEN[:n])
        self.vol.spin.setVisible("spin" not in on)
        self.chk_hear.setText("Hear" if "hear" in on else "Hear it myself")
        self._label_send()
        if not self.btn_rec.isChecked():   # while recording it shows how long it's been
            self.btn_rec.setText("" if "rec" in on else "Record")
        self.layout().activate()

    @property
    def sending(self) -> bool:
        return self.btn_send.isChecked()

    @property
    def to(self) -> str:
        """Where it goes when sent: one of TO_KEYS."""
        return self.cb_to.currentData() or "both"

    def show_to(self, stream_output: bool):
        """The call / stream choice: only worth showing with a stream output set
        (or when it's already set to something else)."""
        self.cb_to.setVisible(stream_output or self.to != "both")

    def _label_send(self):
        self.btn_send.setText("" if "send" in self._TIGHTEN[:self._tight]
                              else "Sending" if self.sending else "Send")

    def set_app(self, app: appaudio.App | None):
        """The program is running (app) or not (None)."""
        self.app = app
        running = app is not None
        if running:
            self.name.setText(app.name + self.folder)
            self._set_icon(app.path)
            where = ", ".join(app.devices[:2])
            sub = app.title or app.exe
            if where:
                sub += f"  ·  playing on {where}"
            if not self.status_text:   # an error stays up until the next attempt
                self.sub.setText(sub)
        else:
            self.name.setText((self.exe.rsplit(".", 1)[0].capitalize() if self.exe else "?")
                              + self.folder)
            self.set_status("")
            self.sub.setText("Not running — it'll be picked up when it starts")
        self.btn_send.setEnabled(running)
        self.btn_rec.setEnabled(running)
        self.btn_clip.setEnabled(running or self.btn_clip.isChecked())
        self.btn_forget.setVisible((not running or not self.sending) and self.listen is None)
        self.setEnabled(True)
        self.name.setEnabled(running)
        name = self.name.text()   # a screen reader hears whose card each button is on
        self.btn_send.setAccessibleName(f"Send {name}")
        self.btn_rec.setAccessibleName(f"Record {name}")
        self.btn_forget.setAccessibleName(f"Forget {name}")
        self.btn_clip.setAccessibleName(f"Clip editor for {name}")

    def set_status(self, text: str, error: bool = False):
        self.status_text = text
        self.status_error = error
        if text:
            self.sub.setText(text)
            theme.set_tone(self.sub, "error" if error else "")
        else:
            theme.set_tone(self.sub, "")   # an error line was red: back to normal
            if self.app is not None:
                self.set_app(self.app)   # back to the program's own line

    def set_sending(self, on: bool):
        self.btn_send.blockSignals(True)
        self.btn_send.setChecked(on)
        self.btn_send.blockSignals(False)
        self._label_send()
        self.btn_forget.setVisible((not on or self.app is None) and self.listen is None)

    def set_clip_open(self, on: bool):
        self.btn_clip.blockSignals(True)
        self.btn_clip.setChecked(on)
        self.btn_clip.blockSignals(False)
        icons.set_icon(self.btn_clip, "fold_open" if on else "fold", "muted", "text", size=12)
        self.btn_forget.setVisible((not self.sending or self.app is None) and not on)

    def set_recording(self, on: bool):
        self.btn_rec.blockSignals(True)
        self.btn_rec.setChecked(on)
        self.btn_rec.blockSignals(False)
        if not on:
            self.btn_rec.setText("" if "rec" in self._TIGHTEN[:self._tight] else "Record")

    _icons = QFileIconProvider()

    def _set_icon(self, path: str, force: bool = False):
        # set_app runs on every refresh (each 1.5 s, 5 s while hidden): the shell's
        # icon lookup is only worth doing when the program changed
        if not force and path == getattr(self, "_icon_path", None):
            return
        self._icon_path = path
        pm = None
        if path:
            try:
                pm = self._icons.icon(QFileInfo(path)).pixmap(QSize(24, 24))
            except Exception:  # noqa: BLE001
                pm = None
        if pm is None or pm.isNull():
            pm = icons.icon("apps", "muted").pixmap(QSize(22, 22))
        self.icon.setPixmap(pm)


class AppsTab(QWidget):
    """Lists the programs that have sound and captures the ones you switch on."""
    clip_ready = Signal(object, str)   # audio, suggested name (like RadioTab's)
    clip_error = ""                    # set by whoever saves the clip, when it can't
    active_changed = Signal(bool)      # some program is / no program is sent (the tab's live dot)

    def __init__(self, engine, cfg, save_cb, meter_cls):
        super().__init__()
        self.engine, self.cfg, self._save, self._meter_cls = engine, cfg, save_cb, meter_cls
        if not isinstance(cfg.apps, dict):
            cfg.apps = {}
        if not isinstance(cfg.apps_paths, dict):
            cfg.apps_paths = {}
        self.rows: dict[str, AppRow] = {}     # exe (lower) or path_key -> row
        self._stopping: list[appaudio.AppCapture] = []   # stopped, maybe not ended yet
        self._sending: tuple[str, ...] = ()   # the programs being sent, as last reported
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        # the explanation is behind the ⓘ at the end of the tab bar (MainWindow)
        self.info = ("Send a program's sound",
                     "Pick a program that's playing — a music player, a browser, a game, "
                        "even a call in another app — and it goes out to whoever's listening, "
                        "on its own volume, the same way your sounds do (your mic, the "
                        "cable or the device you picked on the Setup tab, and the stream "
                        "output). Sending to Nowhere: only the stream output gets it. Only "
                        "that program: nothing else you play is "
                        "touched, and it keeps playing on your speakers as before. Programs "
                        "you switch on are remembered and picked up again next time they run.")
        self.warn = hint_label("")
        theme.set_tone(self.warn, "warn")
        self.warn.setVisible(False)
        v.addWidget(self.warn)
        self.btn_bin = QPushButton("Forgotten programs…")
        self.btn_bin.setToolTip("Bring back a program you forgot, with its volume and "
                                "“Hear it myself”")
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.show_forgotten)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.btn_bin)
        toolbar.addStretch(1)
        size_label = QLabel("Card size")
        size_label.setObjectName("muted")
        toolbar.addWidget(size_label)
        self.card_size = QSlider(Qt.Horizontal)
        self.card_size.setRange(240, CARD_MAX_W)
        self.card_size.setValue(cfg.app_card_width)
        self.card_size.setFixedWidth(100)
        self.card_size.setAccessibleName("App card size")
        self.card_size.setToolTip("App card size: smaller fits more programs across")
        no_wheel(self.card_size)
        toolbar.addWidget(self.card_size)
        v.addLayout(toolbar)
        self.undo_bar = UndoBar("Remember the program again, as it was")
        v.addWidget(self.undo_bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = FitWidth()   # the cards re-flow to the width they get (AppRow._fit_width)
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(6)
        self.grid = CardGrid(min_w=self.card_size.value(), gap=10, even=False)
        self.card_size.valueChanged.connect(self._set_card_size)
        # nothing playing: Bun waits, a bit glum, above the how-to
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 12, 0, 0)
        ev.setSpacing(4)
        self.bun = BunnyWidget(height=72, pad=18, sad=0.6,
                               lines=("play something?", "so quiet…", "music, please?"),
                               joy_lines=("hehe!", "yay!"))
        ev.addWidget(self.bun, 0, Qt.AlignHCenter)
        self.empty_text = hint_label("Nothing is playing sound right now. Start some music, "
                                     "a video or a call and it'll show up here.")
        self.empty_text.setAlignment(Qt.AlignCenter)
        ev.addWidget(self.empty_text)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addLayout(self.grid)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list)
        v.addWidget(self.scroll, 1)
        self.big: AppRow | None = None   # the card in the big view (the rest are hidden)
        # what the clip editors' Save keeps, under the cards
        self.shelf = ClipShelf(engine, cfg, self)
        self.shelf.add_to_sounds.connect(self._shelf_to_sounds)
        v.addWidget(self.shelf)

        ok, why = appaudio.supported()
        if not ok:
            self.warn.setText(why)
            self.warn.setVisible(True)

        for exe, spec in list(cfg.apps.items())[:MAX_REMEMBERED]:   # remembered programs
            if isinstance(spec, dict):
                self._row(exe, saved_volume(spec.get("vol", 1.0)), bool(spec.get("monitor")),
                          str(spec.get("to", "both")), path=str(spec.get("path") or ""))
        for key, spec in list(cfg.apps_paths.items())[:MAX_REMEMBERED]:
            if isinstance(spec, dict) and is_path_key(key):
                self._row(str(spec.get("exe") or key.rsplit("\\", 1)[-1]),
                          saved_volume(spec.get("vol", 1.0)), bool(spec.get("monitor")),
                          str(spec.get("to", "both")), key=key, path=key)
        self._label_folders()

        self.peaks = appaudio.PeakWatcher()   # live levels; the list is only re-read every 1.5 s
        self.lister = _Lister(self, self.peaks)
        self.lister.ready.connect(lambda listed: self._on_apps(*listed))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.lister.refresh)
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._meters)
        appstate.slow_in_background(self, self.meter_timer, METER_MS)   # behind a game
        # behind a game nobody watches the levels: the meters fall back to the list's
        appstate.pause_in_background(self, self.peaks.start, self.peaks.stop)
        self._started = False
        self._label_bin()
        if self.rows:   # remembered programs are picked up even if this tab is never opened
            QTimer.singleShot(1500, self.start)

    def _set_card_size(self, width: int):
        self.cfg.app_card_width = width
        self.grid.min_w = width
        self.grid.invalidate()
        self.list.updateGeometry()
        self.list_layout.activate()
        self._save()

    # ------------------------------------------------------------------ lifecycle
    def showEvent(self, ev):
        super().showEvent(ev)
        self.start()
        self._pace_list()
        self.meter_timer.start(appstate.interval(METER_MS))
        if appstate.active():
            self.peaks.start()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.peaks.stop()
        self._pace_list()

    def start(self):
        """Begin watching for programs (also called before the tab is first shown,
        so remembered programs are picked up right after launch)."""
        if self._started:
            return
        self._started = True
        # the meters run while shown / recording; the list is re-read slowly until then
        self._pace_list()
        self.lister.refresh()

    def _watching(self) -> bool:
        """Something to keep an eye on while the tab is hidden: a remembered program
        (picked up when it starts) or a captured one (let go when it closes)."""
        return any(row.capture is not None or self._spec(key) is not None
                   for key, row in self.rows.items())

    def _pace_list(self):
        """Re-read the list every 1.5 s while shown, every 5 s while hidden, and not
        at all while hidden with nothing remembered or captured."""
        if not self._started:
            return
        ms = (REFRESH_MS if self.isVisible() else
              REFRESH_HIDDEN_MS if self._watching() else 0)
        if not ms:
            self.timer.stop()
        elif not self.timer.isActive() or self.timer.interval() != ms:
            self.timer.start(ms)

    def shutdown(self):
        self.timer.stop()
        self.meter_timer.stop()
        self.peaks.stop()
        self.lister.stop()
        self.shelf.shutdown()
        for row in list(self.rows.values()):
            self._stop_capture(row, save=False)
            if row.editor is not None:
                row.editor.shutdown()
        end = time.monotonic() + 3.0   # all of them together, not 3 s each
        for cap in self._stopping:
            cap.join(max(0.0, end - time.monotonic()))
        self._stopping = []

    def stop_all(self):
        """Stop all: switch every program off (they stay remembered). A recording
        keeps going: nobody hears it."""
        for row in self.rows.values():
            if row.sending:
                row.set_sending(False)
                self._stop_send(row)
        self._report_active()

    def on_air(self) -> bool:
        return self.engine.aux_on_air()

    def is_active(self) -> bool:
        """Some program's sound is being sent."""
        return any(row.sending for row in self.rows.values())

    def live_tip(self) -> str:
        """The "● ON" line for the Apps tab's tooltip while a program is sent."""
        names = [row.name.text() for row in self.rows.values() if row.sending]
        return "● ON: sending " + (", ".join(names) if names else "a program's sound")

    def _report_active(self):
        """Tell the tab's live dot when the set of programs being sent changes
        (on / off, and which: its tip names them)."""
        now = tuple(sorted(key for key, row in self.rows.items() if row.sending))
        if now != self._sending:
            self._sending = now
            self.active_changed.emit(bool(now))

    # ------------------------------------------------------------------ rows
    def _row(self, exe: str, vol: float = 1.0, hear: bool = False, to: str = "both",
             key: str = "", path: str = "") -> AppRow:
        key = key or exe.lower()
        row = self.rows.get(key)
        if row is None:
            row = self.rows[key] = AppRow(exe, self._meter_cls, vol, hear, to, key, path)
            row.show_to(self._stream_output())
            row.send_toggled.connect(self._on_send)
            row.rec_toggled.connect(self._on_rec)
            row.vol_changed.connect(self._on_vol)
            row.hear_toggled.connect(self._on_hear)
            row.to_changed.connect(self._on_to)
            row.clip_toggled.connect(self._on_clip)
            row.forget.connect(self._on_forget)
            self.grid.addWidget(row)
            if self.big is not None:
                row.hide()   # another card has the big view
            self.empty.setVisible(False)
        return row

    def _drop_row(self, row: AppRow):
        self._stop_capture(row)
        self._close_clip(row)
        if self.big is row:
            self._set_big(row, False)
        if row.editor is not None:
            row.editor.shutdown()
        self.rows.pop(row.key, None)
        self.grid.removeWidget(row)
        row.deleteLater()
        self.empty.setVisible(not self.rows)
        self._report_active()

    def _hidden(self) -> set[str]:
        return {str(e).lower() for e in self.cfg.apps_hidden}

    # ------------------------------------------------------------------ keys
    # A program is remembered by its .exe name (cfg.apps, all an older version reads)
    # and the folder it runs from (spec["path"]). Another program with the same name
    # from another folder gets a row of its own, keyed and remembered by its path
    # (cfg.apps_paths), so the two never share a volume, a Send or an auto-send.
    def _spec(self, key: str) -> dict | None:
        """What's remembered about the row `key`, None if nothing."""
        spec = (self.cfg.apps_paths if is_path_key(key) else self.cfg.apps).get(key)
        return spec if isinstance(spec, dict) else None

    def _keys_for(self, apps: list) -> list[str]:
        """The row key for each listed program: its .exe for the one program of that
        name that "owns" it (the remembered folder; else the one already on the row;
        else the first listed), its path_key for any other one."""
        paths: dict[str, list[str]] = {}
        for app in apps:
            paths.setdefault(app.exe.lower(), []).append(path_key(app.path) if app.path else "")
        owner: dict[str, str] = {}
        for exe, found in paths.items():
            spec = self._spec(exe)
            home = str(spec.get("path") or "") if spec is not None else ""
            row = self.rows.get(exe)
            if home:
                owner[exe] = home
            elif row is not None and row.path and row.path in found:
                owner[exe] = row.path
            else:
                owner[exe] = next((p for p in found if p not in self.cfg.apps_paths), found[0])
        keys = []
        for app in apps:
            exe, p = app.exe.lower(), path_key(app.path) if app.path else ""
            if p and p in self.cfg.apps_paths:
                keys.append(p)
            elif not p or p == owner[exe]:
                keys.append(exe)
            else:
                keys.append(p)
        return keys

    def _label_folders(self):
        """Two rows of the same .exe name: each shows the folder it runs from."""
        count: dict[str, int] = {}
        for row in self.rows.values():
            count[row.exe.lower()] = count.get(row.exe.lower(), 0) + 1
        for row in self.rows.values():
            folder = ""
            if count[row.exe.lower()] > 1 and row.path:
                parts = [p for p in row.path.split("\\")[:-1] if p and p != "*"]
                stem = os.path.splitext(row.exe.lower())[0]
                while len(parts) > 1 and parts[-1] in (stem, "bin", "app", "application"):
                    parts.pop()   # ...\spotify\spotify.exe: "spotify" tells nothing
                folder = f" ({parts[-1]})" if parts else ""
            if folder != row.folder:
                row.folder = folder
                row.name.setToolTip(row.app.path if row.app is not None else row.path)
                row.set_app(row.app)

    def _on_apps(self, apps: list, alive: dict[int, str] | None = None):
        """`apps` the programs with an audio session; `alive` every running process
        (pid -> exe), when known. Browsers and chat apps close their session when they
        go quiet: while the process still runs, its card stays (and keeps sending)."""
        stream = self._stream_output()   # set or cleared in Settings meanwhile
        for row in self.rows.values():
            row.show_to(stream)
        by_key: dict[str, appaudio.App] = {}
        hidden = self._hidden()
        for app, key in zip(apps, self._keys_for(apps)):
            if key in hidden and key not in self.rows:
                continue                          # taken off the list with ✕
            cur = self.rows.get(key)
            if cur is not None and cur.capture is not None and cur.capture.pid == app.pid:
                by_key[key] = app   # two copies running: stay on the one being captured
            else:
                by_key.setdefault(key, app)
            self._row(app.exe, key=key)
        for key, row in list(self.rows.items()):
            app = by_key.get(key)
            if (app is None and alive is not None and row.app is not None
                    and alive.get(row.app.pid) == row.app.exe.lower()):
                # quiet, not closed: no level, no "playing on"
                app = dataclasses.replace(row.app, active=False, peak=0.0, devices=[])
            if app is not None and app.path:
                row.path = path_key(app.path)
                spec = self._spec(key)
                if spec is not None and not is_path_key(key) and not spec.get("path"):
                    spec["path"] = row.path   # remembered by an older version: by name only
                    self._save()
            remembered = self._spec(key) is not None
            if app is None:                       # not running
                self._stop_capture(row)
                row.set_sending(False)
                if not remembered and row.listen is None and not self._has_take(row):
                    self._drop_row(row)
                    continue
                row.set_app(None)
                continue
            appeared = row.app is None
            row.set_app(app)
            if self._poll_capture(row):           # the capture died: said so, no blind retry
                continue
            cap = row.capture
            if cap is not None and (cap.ended or cap.pid != app.pid):
                rec, row.rec = row.rec, None      # a recording carries on across the restart
                self._stop_capture(row)           # it closed / restarted / the device changed
                if rec is not None:
                    row.rec = rec
                    if not row.sending and not self._open_capture(row):
                        self._finish_rec(row)
            if row.capture is None:
                if remembered and appeared:
                    row.set_sending(True)         # a remembered program just started
                if row.sending:
                    self._start_capture(row)
                if row.capture is None and row.rec is not None:
                    self._finish_rec(row)         # reopening failed: nothing feeds the clip
                if row.capture is None and row.listen is not None:
                    self._open_capture(row)       # the clip editor keeps listening
            elif row.status_text and row.status_error:
                row.set_status("")
        self._label_folders()
        self.empty.setVisible(not self.rows)
        self._report_active()
        if not self.isVisible():
            self._pace_list()   # the last captured program closed: stop re-reading

    def _poll_capture(self, row: AppRow) -> bool:
        """A capture started without waiting (start(wait=False)): clears *Connecting…*
        once it's up, or stops it and says why. True if it failed."""
        cap = row.capture
        if cap is None:
            return False
        if cap.error:
            row.remember_pending = False
            self._stop_capture(row)
            row.set_sending(False)
            row.set_status(cap.error, error=True)
            log.warning("capturing %s stopped: %s", row.exe, cap.error)
            self._report_active()
            return True
        if cap.ready:
            if row.status_text == CONNECTING:
                row.set_status("")
            if row.remember_pending:
                row.remember_pending = False
                self._remember(row)
        return False

    def _meters(self):
        for row in list(self.rows.values()):
            if row.capture is not None and (row.remember_pending or row.status_text == CONNECTING
                                            or row.capture.error):
                self._poll_capture(row)
        if not self.isVisible() and not any(r.rec for r in self.rows.values()):
            self.meter_timer.stop()   # hidden, nothing to cap: showEvent restarts it
            return
        for row in list(self.rows.values()):
            rec = row.rec
            if rec is not None:
                secs = rec.seconds
                if secs >= MAX_SECONDS:
                    self._finish_rec(row)
                elif rec.triggered:
                    row.btn_rec.setText(f"Stop  {int(secs // 60)}:{int(secs % 60):02d}")
                else:
                    row.btn_rec.setText("Waiting for sound…")
            if row.src is not None:
                row.meter.set_level(row.src.level)
                row.src.level *= 0.8
            elif row.app is None:
                row.meter.set_level(0.0)
            else:
                live = self.peaks.peak(row.app.pid)
                row.meter.set_level(row.app.peak if live is None else live)

    # ------------------------------------------------------------------ capture
    # One capture per program, open while it's being sent, recorded, or both.
    def _sink(self, row: AppRow, x):
        """A chunk of the program's audio (on the capture thread)."""
        src = row.src
        if src is not None:
            self.engine.feed_aux(src, x)
        rec = row.rec
        if rec is not None:
            rec.push(x)
        listen = row.listen
        if listen is not None:
            listen.push(x)

    def _open_capture(self, row: AppRow) -> bool:
        if row.capture is not None:
            return True
        if row.app is None:
            return False
        cap = appaudio.AppCapture(row.app.pid, lambda x, r=row: self._sink(r, x),
                                  name=row.app.name)
        if not cap.start(wait=False):   # opening it can take seconds: see _poll_capture
            row.set_status(cap.error or "Couldn't capture it.", error=True)
            log.warning("capturing %s failed: %s", row.exe, cap.error)
            return False
        row.capture = cap
        log.info("capturing %s (pid %d)", row.exe, row.app.pid)
        return True

    def _close_capture(self, row: AppRow):
        cap, row.capture = row.capture, None
        if cap is not None:
            # without waiting: a capture Windows is still opening takes up to 5 s to
            # notice (that froze the window); shutdown() waits for the stragglers
            cap.stop(wait=False)
            self._stopping = [c for c in self._stopping if c.running] + [cap]
        row.meter.set_level(0.0)

    def _start_capture(self, row: AppRow):
        """Send on: the program's audio goes into the mix."""
        if row.app is None or row.src is not None:
            return
        row.set_status(CONNECTING)   # opening its audio can take a moment (_poll_capture)
        key = ("app", row.key)
        src = self.engine.add_aux(key)
        src.vol = row.vol.value()
        src.monitor = row.chk_hear.isChecked()
        _route(src, row.to)
        row.src = src
        if not self._open_capture(row):
            row.src = None
            self.engine.remove_aux(key)
            row.set_sending(False)
            return
        row.set_sending(True)
        self._poll_capture(row)

    def _stop_send(self, row: AppRow):
        """Send off; the capture stays open while Record is on."""
        src, row.src = row.src, None
        if src is not None:
            self.engine.remove_aux(src.key)
        if row.rec is None and row.listen is None:
            self._close_capture(row)

    def _stop_capture(self, row: AppRow, save: bool = True):
        """Stop everything on this row: sending, and recording (kept if `save`)."""
        self._finish_rec(row, save)
        src, row.src = row.src, None
        if src is not None:
            self.engine.remove_aux(src.key)
        self._close_capture(row)

    # ------------------------------------------------------------------ record
    def _spool_path(self, row: AppRow):
        name = re.sub(r'[^A-Za-z0-9._-]', '_', row.exe)
        if is_path_key(row.key):   # another program of the same name: its own file
            name += f"-{zlib.crc32(row.key.encode()):08x}"
        return library.APP_DIR / f"app-recording-{name}.tmp.wav"

    def _on_rec(self, row: AppRow, on: bool):
        if not on:
            self._finish_rec(row)
            return
        if row.app is None or row.rec is not None:
            row.set_recording(row.rec is not None)
            return
        row.rec = ArmedRecorder(self._spool_path(row))
        if not self._open_capture(row):
            row.rec = None
            row.set_recording(False)
            return
        row.btn_rec.setText("Waiting for sound…")
        # also enforces the length cap while hidden
        self.meter_timer.start(appstate.interval(METER_MS))

    def _finish_rec(self, row: AppRow, save: bool = True):
        rec, row.rec = row.rec, None
        if rec is None:
            return
        row.set_recording(False)
        if save:
            row.set_status("Saving the clip…")
            row.sub.repaint()
        heard = rec.triggered
        data = rec.stop()
        if row.src is None and row.listen is None:
            self._close_capture(row)
        if not save:
            return
        data = trim_silence(data)
        if len(data) < int(0.2 * SR):
            self._flash(row, "Too short to keep." if heard
                        else "Nothing was recorded: it didn't make a sound.")
            return
        error = self._add_clip(row, data)
        if error:   # the window couldn't save it
            row.set_status(f"Couldn't save the clip: {error}", error=True)
            return
        self._flash(row, f"✓ Saved a {len(data) / SR:.1f}s clip to your Sounds.")

    def _add_clip(self, row: AppRow, data) -> str:
        """Hand a clip to the window to become a sound; why it couldn't, or ""."""
        name = (row.app.name if row.app else row.name.text())[:30] or "App"
        self.clip_error = ""
        self.clip_ready.emit(data, f"{name} {time.strftime('%H.%M.%S')}")
        return self.clip_error

    # ------------------------------------------------------------------ clip editor
    # Opt-in per card: nothing is built, kept or drawn until its Clip editor is
    # opened, and closing it stops listening (an edited take stays for next time).
    def _has_take(self, row: AppRow) -> bool:
        return row.editor is not None and row.editor.take is not None

    def _on_clip(self, row: AppRow, on: bool):
        if not on:
            self._close_clip(row)
            return
        if row.listen is not None:
            return
        if row.app is None and not self._has_take(row):
            row.set_clip_open(False)
            return
        if row.editor is None:
            row.editor = ClipEditor(self.engine, self.cfg, row)
            row.editor.save_clip.connect(lambda data, whole, r=row: self._save_edit(r, data, whole))
            row.editor.big_toggled.connect(lambda on, r=row: self._set_big(r, on))
            row.layout().addWidget(row.editor)
        row.set_clip_open(True)
        row.editor.show()
        if row.app is not None:
            row.listen = LiveBuffer()
            if not self._open_capture(row):
                row.listen = None
        row.editor.set_buffer(row.listen)
        row.btn_forget.setVisible(False)
        self._poll_capture(row)

    def _close_clip(self, row: AppRow):
        if self.big is row:
            self._set_big(row, False)
        row.set_clip_open(False)
        listen, row.listen = row.listen, None
        if row.editor is not None:
            row.editor.set_buffer(None)   # stops playing; an unedited take is let go
            row.editor.hide()
        if listen is not None and row.src is None and row.rec is None:
            self._close_capture(row)
        row.set_sending(row.sending)      # the ✕ comes back

    def _save_edit(self, row: AppRow, data, whole: bool):
        if whole:   # nothing picked out: the dead air at its ends goes
            data = trim_silence(data)
        if len(data) < int(0.05 * SR):
            row.editor.flash("Nothing but silence there.")
            return
        src = (row.app.name if row.app else row.name.text())[:30] or "App"
        try:
            self.shelf.add(data, f"{src} {time.strftime('%H.%M.%S')}", src)
        except Exception as e:  # noqa: BLE001 - the disk is full, the folder is locked
            log.exception("can't keep the clip")
            row.editor.flash(f"Couldn't save it: {errors.plain(e)}", error=True)
            return
        row.editor.flash(f"✓ Kept {len(data) / SR:.2f}s in Saved clips below: double-click "
                         "plays it, right-click adds it to your Sounds.")

    def _shelf_to_sounds(self, data, name: str):
        self.clip_error = ""
        self.clip_ready.emit(data, name)
        self.shelf.error = self.clip_error

    # ------------------------------------------------------------------ big view
    # One card's clip editor gets the whole tab: the other cards hide, the card is as
    # wide as the tab and the waveform as tall as the room left.
    def _set_big(self, row: AppRow, on: bool):
        if on and row.editor is None:
            return
        self.big = row if on else None
        for r in self.rows.values():
            r.setVisible(on is False or r is row)
        if row.editor is not None:
            row.editor.set_big(on)
        self.grid.max_cols = 1 if on else 0   # the one card shown, the tab's width
        self.card_size.setEnabled(not on)
        self.grid.invalidate()
        self._fit_big()
        if not on:
            self.scroll.ensureWidgetVisible(row)

    def _fit_big(self):
        row = self.big
        if row is None or row.editor is None:
            return
        wave = row.editor.wave
        rest = row.sizeHint().height() - max(wave.minimumHeight(), wave.sizeHint().height())
        room = self.scroll.viewport().height() - rest - 12
        wave.setMinimumHeight(max(WAVE_H, room))
        self.list_layout.activate()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.big is not None:
            QTimer.singleShot(0, self._fit_big)

    def _flash(self, row: AppRow, text: str):
        row.set_status(text)

        def clear():
            if row.status_text == text and not row.status_error:
                row.set_status("")
        QTimer.singleShot(5000, row, clear)

    # ------------------------------------------------------------------ controls
    def _remember(self, row: AppRow):
        spec = {"vol": row.vol.value(), "monitor": row.chk_hear.isChecked()}
        if row.to != "both":
            spec["to"] = row.to
        if is_path_key(row.key):
            spec["exe"] = row.exe.lower()
            store = self.cfg.apps_paths
        else:
            if row.path:
                spec["path"] = row.path
            store = self.cfg.apps
        store[row.key] = spec
        while len(store) > MAX_REMEMBERED:
            store.pop(next(iter(store)))
        self._save()

    def _unremember(self, key: str) -> dict | None:
        spec = (self.cfg.apps_paths if is_path_key(key) else self.cfg.apps).pop(key, None)
        return spec if isinstance(spec, dict) else None

    def _on_send(self, row: AppRow, on: bool):
        row._label_send()
        if on:
            self._start_capture(row)
            if row.capture is not None:
                row.remember_pending = True
                self._poll_capture(row)
        else:
            row.remember_pending = False
            self._stop_send(row)
            self._unremember(row.key)
            self._save()
            row.btn_forget.setVisible(True)
            if row.app is None:
                self._drop_row(row)
        self._report_active()

    def _on_vol(self, row: AppRow, v: float):
        if row.src is not None:
            row.src.vol = v
        if self._spec(row.key) is not None:
            self._remember(row)

    def _on_to(self, row: AppRow, to: str):
        if row.src is not None:
            _route(row.src, to)
        if self._spec(row.key) is not None:
            self._remember(row)
        self._report_active()

    def _stream_output(self) -> bool:
        """A stream output is set (Settings → Audio → Stream output)."""
        return bool(self.engine.names.get("obs"))

    def _on_hear(self, row: AppRow, on: bool):
        if row.src is not None:
            row.src.monitor = on
        if self._spec(row.key) is not None:
            self._remember(row)

    def _on_forget(self, row: AppRow):
        """✕: forget what's remembered about the program and take it off the list. A
        running one stays off (cfg.apps_hidden) until it's brought back from the
        Undo bar or *Forgotten programs…*."""
        key = row.key
        spec = self._unremember(key) or {}
        running = row.app is not None
        if running and key not in self._hidden():
            self.cfg.apps_hidden.append(key)
        self._save()
        if spec or running:          # something to bring back: keep it in the bin
            name = row.name.text() or row.exe
            item = trash.put_app(row.exe.lower(), spec, name, hidden=running,
                                 path=key if is_path_key(key) else "")
            self._label_bin()
            self.undo_bar.show_for(f"Removed “{name}”",
                                   lambda: self._undo_forget(item.id))
        self._stop_send(row)
        self._drop_row(row)
        self._report_active()

    def _undo_forget(self, item_id: str):
        it = trash.take(item_id)
        if it is not None:
            self._unforget(it)

    def show_forgotten(self):
        from soundboard.ui.deleted import DeletedDialog
        self.undo_bar.finish()
        DeletedDialog(trash.APP, "programs", self._unforget, self).exec()
        self._label_bin()

    def _label_bin(self):
        self.btn_bin.setVisible(bool(trash.items(trash.APP)))

    def _unforget(self, item: trash.Item) -> bool:
        """A forgotten program taken out of the bin: remember it again."""
        exe, spec = str(item.data.get("exe", "")).lower(), item.data.get("spec")
        if not exe or not isinstance(spec, dict):
            return False
        key = str(item.data.get("path") or "").lower()
        key = key if is_path_key(key) else exe
        self.cfg.apps_hidden = [e for e in self.cfg.apps_hidden if str(e).lower() != key]
        if not spec:                 # only taken off the list: back on the next listing
            self._save()
            self._label_bin()
            if self._started:
                self.lister.refresh()
            return True
        store = self.cfg.apps_paths if is_path_key(key) else self.cfg.apps
        store[key] = dict(spec)
        while len(store) > MAX_REMEMBERED:
            store.pop(next(iter(store)))
        self._save()
        old = self.rows.get(key)
        app = old.app if old is not None else None
        if old is not None and not old.sending:
            self._drop_row(old)   # built again with the remembered volume
        row = self._row(exe, saved_volume(spec.get("vol", 1.0)), bool(spec.get("monitor")),
                        str(spec.get("to", "both")), key=key,
                        path=key if is_path_key(key) else str(spec.get("path") or ""))
        row.set_app(app)
        self._label_folders()
        self._label_bin()
        if not self._started:
            self.start()
        self._pace_list()
        return True

    def retheme(self):
        for row in self.rows.values():   # a program that isn't running: the placeholder
            row._set_icon(row.app.path if row.app is not None else "", force=True)
