"""The main window: pads, transport, browser tab, the audio panel, auto push-to-talk."""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSlider,
                               QTabWidget, QVBoxLayout, QWidget)

from soundboard import engine as eng
from soundboard import theme, winkeys
from soundboard.browser import BrowserTab
from soundboard.engine import SR, Engine
from soundboard.engine import is_virtual as is_virtual_cable
from soundboard.library import (AUDIO_EXTS, PAD_COLORS, RESOURCE_DIR, Config, SoundMeta,
                                delete_file, fingerprint, import_file, load_sound, prune_cache,
                                save_clip)
from soundboard.settings import HOTKEY_ACTIONS, HotkeyDialog, SettingsDialog, pretty_key
from soundboard.testcheck import analyze as analyze_output
from soundboard.testcheck import summary_html
from soundboard.ui.dialogs import EditDialog
from soundboard.ui import icons
from soundboard.ui.panel import (EqPanel, VolumeControl, bar, card, hint_label, icon_label,
                                 vsep)
from soundboard.ui.overlay import Overlay
from soundboard.ui.voicepanel import VoicePanel
from soundboard.ui.widgets import Meter, Pad, PadGrid, SeekSlider, fmt_pos
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys

log = logging.getLogger(__name__)


class Bridge(QObject):
    loaded = Signal(str, object, str)          # id, data|None, error
    imported = Signal(object, object, str)     # meta|None, data|None, error/filename


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soundboard")
        self.setWindowIcon(theme.app_icon())
        self.cfg = Config.load()
        app = QApplication.instance()
        if app is not None:   # before the UI is built, so everything polishes in-theme
            self.cfg.theme = theme.apply(app, self.cfg.theme)
        self.engine = Engine()
        self.audio: dict[str, np.ndarray] = {}
        self.pads: dict[str, Pad] = {}
        self._meta: dict[str, SoundMeta] = {}   # id -> meta, rebuilt when the list changes
        self._index()
        self.hotkeys = Hotkeys()
        self.hotkeys.fired.connect(self.on_hotkey)
        self.hotkeys.failed_changed.connect(self.on_hotkeys_failed)
        self.overlay = Overlay(self, self.cfg.overlay)
        self._save_failed_shown = False
        self.bridge = Bridge()
        self.bridge.loaded.connect(self.on_loaded)
        self.bridge.imported.connect(self.on_imported)
        self._ptt_held: str | None = None   # PTT key we're currently holding
        self._pending_imports = 0
        self._import_errors: list[str] = []
        self._rec_playing = False
        self.current: str | None = None   # sound shown in the transport bar
        self.start_frac = 0.0             # where ▶ starts if it isn't playing
        self._seeking = False
        self._tick_n = 0                  # ticks since start (the watchdog runs every 30th)
        self._xruns_shown = 0             # drop-out count last written to the status line
        self._talk_until = 0.0            # "hearing you" indicator holds until this time
        self._talk_shown: bool | None = None
        self.virtual_mic: str | None = None
        self._cap: list[np.ndarray] = []  # Record-6s test: capture of the cable's far end
        self._cap_stream = None
        self._cap_rate: int | None = None
        self._cap_name: str | None = None
        self._rec_started = 0.0
        self._load_thread: threading.Thread | None = None
        self.engine.latency = self.cfg.latency if self.cfg.latency in ("low", "high") else "low"
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_now)

        self.setup_state = ""
        self._build_ui()
        self._init_devices()
        if self.setup_state != "ok":
            self.tabs.blockSignals(True)
            self.tabs.setCurrentWidget(self.setup_page)
            self.tabs.blockSignals(False)
        self._rebuild_pads()
        self._load_all()
        self.register_hotkeys()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.resize(1180, 720)
        if self.cfg.always_on_top:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

    # ------------------------------------------------------------------ UI build
    # Layout: header (setup pill, Stop all, Settings) / tabs / mixer strip / status.
    # Every tab is built the same way: a toolbar row on top, its content, and a
    # bottom bar ending in "Volume [slider %] | Hear it myself" for that source.
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        rv = QVBoxLayout(root)
        rv.setContentsMargins(14, 10, 14, 10)
        rv.setSpacing(8)

        # ---- header: logo + name, then setup status, Stop all, Settings
        head = QHBoxLayout()
        head.setSpacing(10)
        self.logo = QLabel()
        self.logo.setFixedSize(34, 34)
        head.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        wm = QLabel("SOUNDBOARD")
        wm.setObjectName("wordmark")
        tag = QLabel("sounds + browser + voice, straight into your mic")
        tag.setObjectName("tagline")
        names.addWidget(wm)
        names.addWidget(tag)
        head.addLayout(names)
        head.addStretch(1)
        self.pill = QPushButton()
        self.pill.setObjectName("pill")
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setToolTip("Where your sounds go — click for setup and testing")
        self.pill.clicked.connect(lambda: self.tabs.setCurrentWidget(self.setup_page))
        head.addWidget(self.pill)
        self.stop_btn = QPushButton("Stop all")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setToolTip("Stops every sound and pauses the browser")
        self.stop_btn.clicked.connect(self.stop_all)
        icons.set_icon(self.stop_btn, "stop", "danger_text", size=14)
        head.addWidget(self.stop_btn)
        gear = QPushButton("Settings")
        gear.setObjectName("settings")
        gear.setToolTip("Themes, hotkeys and more")
        gear.clicked.connect(lambda: self.open_settings())
        icons.set_icon(gear, "settings")
        head.addWidget(gear)
        rv.addLayout(head)
        self._paint_logo()

        self.mic_banner = QPushButton("YOU'RE HEARING YOUR MIC OUTPUT  —  mic + sounds, "
                                      "exactly what others hear   ·   click to turn off")
        self.mic_banner.setObjectName("micbanner")
        self.mic_banner.setCursor(Qt.PointingHandCursor)
        self.mic_banner.clicked.connect(lambda: self.btn_check.setChecked(False))
        self.mic_banner.hide()
        icons.set_icon(self.mic_banner, "ear", "#ffffff", size=20)
        # pulse: an opacity animation, not a stylesheet rewrite 30x a second (each
        # setStyleSheet re-parses and re-polishes the widget)
        self._banner_fx = QGraphicsOpacityEffect(self.mic_banner)
        self.mic_banner.setGraphicsEffect(self._banner_fx)
        self._pulse = QPropertyAnimation(self._banner_fx, b"opacity", self)
        self._pulse.setDuration(1200)
        self._pulse.setStartValue(1.0)
        self._pulse.setKeyValueAt(0.5, 0.55)
        self._pulse.setEndValue(1.0)
        self._pulse.setLoopCount(-1)
        rv.addWidget(self.mic_banner)

        # ---- tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(18, 18))
        rv.addWidget(self.tabs, 1)
        self.sounds_page = self._build_sounds_page()
        self.tabs.addTab(self.sounds_page, "Sounds")
        browser_page = QWidget()
        bl = QVBoxLayout(browser_page)
        bl.setContentsMargins(0, 8, 0, 0)
        self.browser = BrowserTab(self.engine, self.cfg, self._save_later, Meter)
        self.browser.clip_ready.connect(self.on_clip)
        bl.addWidget(self.browser)
        self.tabs.addTab(browser_page, "Browser")
        self.voice = VoicePanel(self.engine, self.cfg.voice_fx, self.cfg.speech)
        self.voice.fx_changed.connect(lambda spec: self.set_option("voice_fx", spec))
        self.voice.speech_changed.connect(lambda s: self.set_option("speech", s))
        self.tabs.addTab(self.voice, "Voice")
        self.setup_page = self._build_setup_page()
        self.tabs.addTab(self.setup_page, "Setup")
        for i, name in enumerate(("sounds", "browser", "voice", "setup")):
            icons.set_tab_icon(self.tabs, i, name)
        self.tabs.setCurrentIndex(self.cfg.tab if 0 <= self.cfg.tab < self.tabs.count() else 0)
        self.tabs.currentChanged.connect(lambda i: self.set_option("tab", i))
        self.tabs.currentChanged.connect(lambda _i: self._update_status())

        # ---- mixer strip: the things that apply whatever tab you're on
        rv.addWidget(self._build_mixer())

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        rv.addWidget(self.status)

    def _build_mixer(self) -> QFrame:
        c = self.cfg
        f, h = bar()
        h.addWidget(icon_label("mic"))
        self.mic_lbl = QLabel("My mic")
        self.mic_lbl.setStyleSheet("font-weight:600;")
        h.addWidget(self.mic_lbl)
        self.chk_mic = QCheckBox("on")
        self.chk_mic.setToolTip("Mix your real mic in, so they still hear you talk")
        self.chk_mic.setChecked(c.mic_enabled)
        self.chk_mic.toggled.connect(self.on_mic_toggle)
        h.addWidget(self.chk_mic)
        self.mic_meter = Meter()
        self.mic_meter.setFixedWidth(70)
        self.mic_meter.setToolTip("Your mic level")
        h.addWidget(self.mic_meter)
        self.vol_mic = VolumeControl(c.mic_vol, tip="How loud your voice is for them")
        h.addWidget(self.vol_mic)
        h.addWidget(vsep())

        h.addWidget(icon_label("headphones"))
        hp = QLabel("My headphones")
        hp.setStyleSheet("font-weight:600;")
        hp.setToolTip("Only what YOU hear. Doesn't change anything for them.")
        h.addWidget(hp)
        self.vol_mon = VolumeControl(c.mon_vol, tip="Only what YOU hear — doesn't change "
                                                    "anything for them")
        h.addWidget(self.vol_mon)
        h.addWidget(vsep())

        h.addWidget(icon_label("live", "What Discord / the game receives"))
        h.addWidget(QLabel("Sending"))
        self.out_meter = Meter()
        self.out_meter.setMinimumWidth(60)
        self.out_meter.setToolTip("Level of what Discord / the game receives")
        h.addWidget(self.out_meter, 1)
        self.btn_check = QPushButton("Hear what they hear")
        self.btn_check.setObjectName("miccheck")
        self.btn_check.setCheckable(True)
        self.btn_check.setToolTip("Plays your mic into your headphones on top of the sounds — "
                                  "exactly what others hear. A red banner shows while it's on.")
        self.btn_check.toggled.connect(self.on_mic_check)
        icons.set_icon(self.btn_check, "ear", checked_color="#ffffff")
        h.addWidget(self.btn_check)

        for box, key in ((self.vol_mic, "mic_vol"), (self.vol_mon, "mon_vol")):
            box.changed.connect(lambda v, key=key: self.set_option(key, v))
        return f

    def _build_sounds_page(self) -> QWidget:
        c = self.cfg
        page = QWidget()
        left = QVBoxLayout(page)
        left.setContentsMargins(0, 8, 0, 0)
        left.setSpacing(8)
        tb = QHBoxLayout()
        tb.setSpacing(8)
        add = QPushButton("Add sounds")
        add.setObjectName("primary")
        add.clicked.connect(self.add_dialog)
        icons.set_icon(add, "plus", "on_accent")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sounds…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        tb.addWidget(add)
        tb.addWidget(self.search, 1)
        size = QSlider(Qt.Horizontal)
        size.setRange(110, 240)
        size.setValue(c.pad_width)
        size.setFixedWidth(90)
        size.setToolTip("Pad size")
        size.valueChanged.connect(self.set_pad_width)
        no_wheel(size)
        size_lbl = QLabel("Pad size")
        size_lbl.setObjectName("muted")
        tb.addWidget(size_lbl)
        tb.addWidget(size)
        left.addLayout(tb)

        self.grid = PadGrid()
        self.grid.reorder.connect(self.on_reorder)
        self.grid.files_dropped.connect(self.import_files)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        scroll.setFrameShape(QFrame.NoFrame)
        left.addWidget(scroll, 1)

        # ---- "now playing" chips: shown while 2+ sounds overlap, so every one of
        # them can be stopped (■) or taken into the player (name) without clicking
        # its pad, which would restart it
        self.playing_row = QWidget()
        self._chips_hl = QHBoxLayout(self.playing_row)
        self._chips_hl.setContentsMargins(0, 0, 0, 0)
        self._chips_hl.setSpacing(6)
        self._chips: dict[str, QWidget] = {}
        self._chip_ids: tuple = ()
        self.playing_row.hide()
        left.addWidget(self.playing_row)

        f, th = bar()
        self.btn_pp = QPushButton()
        self.btn_pp.setObjectName("round")
        self.btn_pp.setToolTip("Play / pause")
        self.btn_pp.clicked.connect(self.toggle_play_pause)
        self._pp_icon = None
        self.btn_st = QPushButton()
        self.btn_st.setObjectName("round")
        self.btn_st.setToolTip("Stop")
        self.btn_st.clicked.connect(self.stop_current)
        icons.set_icon(self.btn_st, "stop", size=16)
        for b in (self.btn_pp, self.btn_st):
            b.setFixedSize(38, 34)
        self.np_name = QLabel("Click a sound to control it here")
        self.np_name.setFixedWidth(190)
        self.np_name.setStyleSheet("font-weight:600;")
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setObjectName("seek")
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self.do_seek)
        self.seek.valueChanged.connect(self._seek_preview)
        no_wheel(self.seek)
        self.np_time = QLabel("0:00 / 0:00")
        self.np_time.setFixedWidth(84)
        self.np_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.np_time.setObjectName("muted")
        th.addWidget(self.btn_pp)
        th.addWidget(self.btn_st)
        th.addWidget(self.np_name)
        th.addWidget(self.seek, 1)
        th.addWidget(self.np_time)
        th.addWidget(vsep())
        th.addWidget(icon_label("volume", "Volume of all your sounds"))
        self.vol_sound = VolumeControl(c.sound_vol, tip="How loud your sounds are — type up "
                                                        "to 1000% in the box")
        self.vol_sound.changed.connect(lambda v: self.set_option("sound_vol", v))
        th.addWidget(self.vol_sound)
        self.chk_monitor = QCheckBox("Hear it myself")
        self.chk_monitor.setToolTip("Also play your sounds into your headphones")
        self.chk_monitor.setChecked(c.monitor_sounds)
        self.chk_monitor.toggled.connect(lambda b: self.set_option("monitor_sounds", b))
        th.addWidget(self.chk_monitor)
        left.addWidget(f)
        self._set_pp_icon("play")
        return page

    def _update_chips(self, playing):
        ids = tuple(s for s in self.pads if s in playing)
        if ids != self._chip_ids:
            self._chip_ids = ids
            while self._chips_hl.count():
                w = self._chips_hl.takeAt(0).widget()
                if w:
                    w.deleteLater()
            self._chips = {}
            if len(ids) >= 2:
                lbl = QLabel("Now playing")
                lbl.setObjectName("muted")
                self._chips_hl.addWidget(lbl)
                for sid in ids:
                    m = self.meta(sid)
                    chip = QFrame()
                    chip.setObjectName("chip")
                    ch = QHBoxLayout(chip)
                    ch.setContentsMargins(4, 2, 2, 2)
                    ch.setSpacing(2)
                    name = QPushButton(chip.fontMetrics().elidedText(
                        m.name if m else sid, Qt.ElideRight, 150))
                    name.setObjectName("chipname")
                    name.setToolTip("Show this sound in the player (keeps playing)")
                    name.clicked.connect(lambda _=False, s=sid: self.select(s))
                    stop = QPushButton()
                    stop.setObjectName("chipstop")
                    stop.setToolTip("Stop this sound")
                    stop.setIcon(icons.icon("stop", "danger_text"))
                    stop.setIconSize(QSize(12, 12))
                    stop.setFixedSize(24, 24)
                    stop.clicked.connect(lambda _=False, s=sid: self.engine.stop(s))
                    ch.addWidget(name)
                    ch.addWidget(stop)
                    self._chips_hl.addWidget(chip)
                    self._chips[sid] = chip
                self._chips_hl.addStretch(1)
            self.playing_row.setVisible(len(ids) >= 2)
        for sid, chip in self._chips.items():
            sel = "true" if sid == self.current else "false"
            if chip.property("sel") != sel:
                chip.setProperty("sel", sel)
                chip.style().unpolish(chip)
                chip.style().polish(chip)

    def _set_pp_icon(self, name: str):
        if name != self._pp_icon:
            self._pp_icon = name
            self.btn_pp.setIcon(icons.icon(name))
            self.btn_pp.setIconSize(QSize(16, 16))

    def _build_setup_page(self) -> QWidget:
        """One-time setup and the rarely-touched stuff: where the audio goes,
        devices, the recorded test, EQ, levelling."""
        c = self.cfg
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.NoFrame)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        cols = QHBoxLayout(inner)
        cols.setContentsMargins(0, 10, 4, 10)
        cols.setSpacing(12)
        lcol, rcol = QVBoxLayout(), QVBoxLayout()
        for col in (lcol, rcol):
            col.setSpacing(12)
            cols.addLayout(col, 1)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        howcard, cv = card("YOUR VIRTUAL MIC")
        self.flow_mic = QLabel()
        self.flow_snd = QLabel("Your sounds, browser and voice effects")
        arrow = QLabel("↓   the app mixes them together")
        arrow.setObjectName("muted")
        self.flow_out = QLabel()
        for ic, w in (("mic", self.flow_mic), ("volume", self.flow_snd), ("", arrow),
                      ("cable", self.flow_out)):
            w.setTextFormat(Qt.RichText)
            w.setWordWrap(True)
            row = QHBoxLayout()
            row.setSpacing(8)
            if ic:
                row.addWidget(icon_label(ic))
            else:
                row.addSpacing(26)
            row.addWidget(w, 1)
            cv.addLayout(row)
        self.step_lbl = QLabel()
        self.step_lbl.setWordWrap(True)
        self.step_lbl.setTextFormat(Qt.RichText)
        self.step_lbl.setObjectName("stepbox")
        cv.addWidget(self.step_lbl)
        self.btn_install = QPushButton("Install the free virtual cable")
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(self.install_cable)
        icons.set_icon(self.btn_install, "cable", "on_accent")
        cv.addWidget(self.btn_install)
        self.btn_rescan = QPushButton("I've installed it — check again")
        self.btn_rescan.clicked.connect(self.refresh_devices)
        icons.set_icon(self.btn_rescan, "reload")
        cv.addWidget(self.btn_rescan)
        self.btn_nomic = QPushButton("Game has no microphone setting?")
        self.btn_nomic.clicked.connect(self.open_windows_mic)
        cv.addWidget(self.btn_nomic)
        guide = QPushButton("Step-by-step guide")
        guide.setToolTip("Walks you through mic, headphones, the cable and Discord")
        icons.set_icon(guide, "check")
        guide.clicked.connect(self.run_setup)
        cv.addWidget(guide)
        lcol.addWidget(howcard)

        # ---- devices
        devcard, av = card("DEVICES", "Already set up for you — only change these if "
                                      "something's wrong.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.cb_main, self.cb_mon, self.cb_mic = QComboBox(), QComboBox(), QComboBox()
        for r, (ic, text, cb) in enumerate((
                ("cable", "Send into (the cable)", self.cb_main),
                ("headphones", "My headphones", self.cb_mon),
                ("mic", "My real mic", self.cb_mic))):
            grid.addWidget(icon_label(ic), r, 0)
            grid.addWidget(QLabel(text), r, 1)
            grid.addWidget(cb, r, 2)
            cb.setMinimumWidth(120)
        grid.setColumnStretch(2, 1)
        av.addLayout(grid)
        self.setup_hint = hint_label("")
        self.setup_hint.setTextFormat(Qt.RichText)
        av.addWidget(self.setup_hint)
        no_wheel(self.cb_main, self.cb_mon, self.cb_mic)
        for cb, attr in ((self.cb_main, "main_device"), (self.cb_mon, "mon_device"),
                         (self.cb_mic, "mic_device")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: self.on_device(cb, attr))
        ref = QPushButton("Re-scan devices")
        icons.set_icon(ref, "reload")
        ref.clicked.connect(self.refresh_devices)
        av.addWidget(ref, 0, Qt.AlignLeft)
        lcol.addWidget(devcard)
        lcol.addStretch(1)

        # ---- test
        testcard, tv = card("TEST IT", "Talk while a sound plays. Records what Discord / the "
                                       "game actually receives, plays it back, and tells you "
                                       "if your voice + sounds are in it.")
        self.btn_rec = QPushButton("Record 6s → play back")
        self.btn_rec.setObjectName("primary")
        icons.set_icon(self.btn_rec, "record", "on_accent")
        self.btn_rec.clicked.connect(self.start_test)
        tv.addWidget(self.btn_rec)
        tv.addWidget(hint_label("For a live check, use “Hear what they hear” at the bottom: "
                                "it plays your output into your headphones."))
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        self.test_result.setTextFormat(Qt.RichText)
        self.test_result.setObjectName("resultbox")
        self.test_result.hide()
        tv.addWidget(self.test_result)
        rcol.addWidget(testcard)

        # ---- sound shaping
        eqcard, ev = card()
        self.eq = EqPanel(c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains)
        self.eq.changed.connect(self.on_eq)
        ev.addWidget(self.eq)
        self.chk_level = QCheckBox("Level volumes (all sounds equally loud)")
        self.chk_level.setChecked(c.level_volumes)
        self.chk_level.toggled.connect(self.on_level_toggle)
        ev.addWidget(self.chk_level)
        hk = QPushButton("Hotkeys & auto push-to-talk…")
        hk.setToolTip("Opens Settings → Hotkeys")
        hk.clicked.connect(lambda: self.open_settings("hotkeys"))
        ev.addWidget(hk, 0, Qt.AlignLeft)
        rcol.addWidget(eqcard)
        rcol.addStretch(1)
        self.on_eq(*self.eq.state())   # push the saved EQ into the engine
        return page

    def on_eq(self, gains, enabled, target, preset):
        c = self.cfg
        c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains = enabled, target, preset, list(gains)
        self.engine.eq_target = target
        self.engine.eq_gains = list(gains) if enabled else None
        self._save_later()

    # ------------------------------------------------------------------ devices
    def refresh_devices(self):
        e = self.engine
        e.shutdown()
        if not eng.rescan():
            self.status.setText("<span style='color:#ffb020'>Couldn't re-scan devices — "
                                "restart the app to pick up new ones.</span>")
        self._init_devices()
        self._prepare_all()

    def set_latency(self, mode: str):
        """'low' (default) or 'high' (bigger buffers: more delay, fewer drop-outs)."""
        if mode not in ("low", "high") or mode == self.cfg.latency:
            return
        self.cfg.latency = mode
        self.engine.latency = mode
        self.engine.reopen_all()
        self.cfg.save()
        self._update_status()

    def _init_devices(self):
        outs = [d["name"] for d in eng.list_devices("output")]
        # a virtual cable as the *mic* would record our own output and feed it back
        # into itself (a loud feedback screech), so cables never appear here
        ins = [d["name"] for d in eng.list_devices("input") if not is_virtual_cable(d["name"])]
        c = self.cfg
        if c.mic_device and is_virtual_cable(c.mic_device):
            c.mic_device = None   # was set to the cable: fall back to the real mic
        if not c.main_device or eng.find_device("output", c.main_device) is None:
            c.main_device = next(iter(eng.virtual_outputs()), None) or c.main_device
        if not c.mon_device:
            dflt = eng.default_device_name("output")
            c.mon_device = dflt if dflt and not is_virtual_cable(dflt) else \
                next((n for n in outs if not is_virtual_cable(n)), None)
        if not c.mic_device:
            dflt = eng.default_device_name("input")
            c.mic_device = dflt if dflt and not is_virtual_cable(dflt) else \
                next(iter(ins), None)
        self._fill_combo(self.cb_main, outs, c.main_device)
        self._fill_combo(self.cb_mon, outs, c.mon_device)
        self._fill_combo(self.cb_mic, ins, c.mic_device)

        e = self.engine
        e.sound_vol, e.mic_vol, e.mon_vol = c.sound_vol, c.mic_vol, c.mon_vol
        e.mic_enabled, e.monitor_sounds = c.mic_enabled, c.monitor_sounds
        e.set_mic_device(c.mic_device if c.mic_enabled else None)
        e.set_main_device(c.main_device)
        e.set_mon_device(c.mon_device)
        self._update_status()

    def _fill_combo(self, cb, names, current):
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("— none —", None)
        for n in names:
            cb.addItem(n, n)
        i = cb.findData(current) if current else 0
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.blockSignals(False)

    def on_device(self, cb, attr):
        name = cb.currentData()
        setattr(self.cfg, attr, name)
        if attr == "main_device":
            self.engine.set_main_device(name)
        elif attr == "mon_device":
            self.engine.set_mon_device(name)
        else:
            self.engine.set_mic_device(name if self.cfg.mic_enabled else None)
        self.cfg.save()
        self._update_status()
        self._prepare_all()

    def _prepare_all(self):
        items = list(self.audio.items())
        threading.Thread(target=lambda: [self.engine.prepare(s, d) for s, d in items],
                         daemon=True, name="prepare").start()

    def on_mic_toggle(self, b):
        self.set_option("mic_enabled", b)
        self.engine.set_mic_device(self.cfg.mic_device if b else None)
        self._update_status()

    def _update_status(self):
        e = self.engine
        main = self.cfg.main_device or ""
        self.virtual_mic = eng.virtual_mic_for(main)
        if self.virtual_mic:
            self.setup_hint.setText(f"A virtual cable is a pipe: audio goes in at <b>{main}</b> "
                                    f"and comes out at <b>{self.virtual_mic}</b>, which Discord "
                                    "/ the game uses as your mic.")
        elif main:
            self.setup_hint.setText("<span style='color:#ffb020'>That's a normal speaker/headphone "
                                    "device, so only you will hear the sounds. Pick a virtual "
                                    "cable here.</span>")
        else:
            self.setup_hint.setText("<span style='color:#ffb020'>Nothing picked — only you "
                                    "will hear sounds.</span>")
        self._update_flow()
        errs = [f"{k}: {v}" for k, v in e.errors.items()]
        if errs:
            self.status.setText("<span style='color:#ff6b6b'>Audio device problem — "
                                + " · ".join(errs) + "</span>")
            return
        n = len(self.cfg.sounds)
        text = ""
        if self.tabs.currentWidget() is self.sounds_page:
            text = (f"{n} sound{'s' if n != 1 else ''} · click to play · right-click to "
                    "edit / set hotkey · drag to reorder · drop files to add")
        xr = sum(e.xruns.values())
        self._xruns_shown = xr
        if xr:
            tip = ("" if self.cfg.latency == "high" else
                   " — try Settings → General → Audio buffering: Safer")
            text += (f"{'<br>' if text else ''}<span style='color:#ffb020'>{xr} audio drop-out"
                     f"{'s' if xr != 1 else ''} since start{tip}</span>")
        self.status.setText(text)

    def _update_flow(self, talking=False):
        e = self.engine
        ok, bad = "#13ce66", "#ff4d4f"
        if e.mic_stream is None or not self.cfg.mic_enabled:
            mic = f"Your mic  <b style='color:{bad}'>✗ off</b>"
        elif talking:
            mic = f"Your mic  <b style='color:{ok}'>✓ hearing you</b>"
        else:
            mic = f"Your mic  <b style='color:{ok}'>✓</b>"
        vm = self.virtual_mic
        any_cable = bool(eng.virtual_outputs())
        if not any_cable:
            state = "missing"
            out = f"Virtual mic  <b style='color:{bad}'>✗ not installed yet</b>"
            step = ("<b style='color:#ffb020'>One-time setup:</b> install the free virtual "
                    "cable. It's what lets Discord and games hear your sounds — without it, "
                    "only you can hear them.")
        elif vm and e.main_stream is not None:
            state = "ok"
            out = (f"<b style='color:{ok}'>{vm}</b> — your new mic "
                   f"<b style='color:{ok}'>✓ working</b>")
            step = (f"<b>The only thing you set:</b> in Discord or your game, pick "
                    f"<b style='color:{ok}'>{vm}</b> as your <b>microphone</b>.")
        else:
            state = "unrouted"
            out = f"Virtual mic  <b style='color:{bad}'>✗ not connected</b>"
            step = ("<b style='color:#ffb020'>Almost:</b> under <b>Devices</b>, set "
                    "“Send into (the cable)” to your virtual cable.")
        self.flow_mic.setText(mic)
        self.flow_out.setText(out)
        self.step_lbl.setText(step)
        self.btn_install.setVisible(state == "missing")
        self.btn_rescan.setVisible(state == "missing")
        self.btn_nomic.setVisible(state == "ok")
        self.setup_state = state
        if state == "ok":
            pill = f"Your mic in Discord / games:  {vm}"
        elif state == "missing":
            pill = "One-time setup needed — others can't hear you yet"
        else:
            pill = "Not connected to the virtual cable — click to fix"
        if self.pill.text() != pill:
            self.pill.setText(pill)
            self.pill.setIcon(icons.icon("check", "#13ce66") if state == "ok" else
                              icons.icon("warn", "warn_text"))
            self.pill.setProperty("state", "ok" if state == "ok" else "warn")
            self.pill.style().unpolish(self.pill)
            self.pill.style().polish(self.pill)

    def install_cable(self):
        script = RESOURCE_DIR / "install-vbcable.ps1"
        if not script.exists():
            QMessageBox.warning(self, "Installer missing", f"Can't find {script.name}.")
            return
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-File", str(script)],
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
        QMessageBox.information(
            self, "Installing the virtual cable",
            "A window opened that downloads VB-Cable (free) from the official VB-Audio site.\n\n"
            "Windows will ask for permission — click Yes, then click “Install Driver”.\n\n"
            "When it's done, click “I've installed it — check again”. If it doesn't show up, "
            "restart your PC.")

    def run_setup(self):
        """The quick-setup guide (first launch, or the Setup tab's Step-by-step guide)."""
        from soundboard.ui.setupwizard import SetupWizard
        SetupWizard(self).exec()
        self._prepare_all()

    def open_windows_mic(self):
        vm = self.virtual_mic or "your virtual cable"
        subprocess.Popen(["control", "mmsys.cpl,,1"], creationflags=0x08000000)
        QMessageBox.information(
            self, "Game with no mic setting",
            "Some games just use Windows' main mic. A sound window just opened:\n\n"
            f"1.  Right-click  {vm}  →  Set as Default Device\n"
            "2.  Restart the game.\n\n"
            "Heads-up: voice typing will then also hear your sounds.\n"
            "To undo, do the same on your normal mic.")

    # ------------------------------------------------------------------ settings
    def set_option(self, attr: str, v):
        """Change one config value (mirrored onto the engine when it has the same
        attribute) and save shortly after. The small public surface the Settings
        window and dialogs use."""
        setattr(self.cfg, attr, v)
        if hasattr(self.engine, attr):
            setattr(self.engine, attr, v)
        self._save_later()

    def _save_later(self):
        self._save_timer.start(400)

    def _save_now(self):
        """The debounced save. A failure (disk full, antivirus lock) is logged by
        Config.save; here it's shown once so the user knows settings aren't sticking."""
        if self.cfg.save():
            self._save_failed_shown = False
        elif not self._save_failed_shown:
            self._save_failed_shown = True
            self.status.setText("<span style='color:#ff6b6b'>Couldn't save your settings — "
                                r"see the log in %APPDATA%\Soundboard.</span>")

    def on_level_toggle(self, b):
        self.set_option("level_volumes", b)
        for m in self.cfg.sounds:
            self.engine.set_gain(m.id, self.gain_for(m))

    def on_top_toggle(self, b):
        self.set_option("always_on_top", b)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, b)
        self.show()

    def set_pad_width(self, w):
        self.cfg.pad_width = w
        for p in self.pads.values():
            p.setFixedSize(w, int(w * 0.62))
        self.grid.relayout(force=True)
        self._save_later()

    # ------------------------------------------------------------------ hotkeys
    def register_hotkeys(self):
        mapping = {}
        for attr, action, _label, _desc in HOTKEY_ACTIONS:
            combo = getattr(self.cfg, attr)
            if combo:
                mapping.setdefault(combo, action)
        for m in self.cfg.sounds:
            if m.hotkey:
                mapping.setdefault(m.hotkey, m.id)
        mapping.update(self.overlay.layer())   # its keys, only while it's open
        self.hotkeys.register(mapping)

    def on_hotkeys_failed(self, failed: list[str]):
        if failed:
            log.warning("hotkeys another program already owns: %s", failed)
            self.status.setText("<span style='color:#ffb020'>Another program is already using "
                                + ", ".join(pretty_key(c) for c in failed)
                                + " — pick a different hotkey.</span>")

    def set_global_hotkey(self, attr: str, combo: str):
        """Set one of the app-wide hotkeys (or ptt_key). A combo can only do one thing,
        so it's taken off any other action or sound that had it."""
        if combo:
            if attr != "ptt_key":
                for other, *_ in HOTKEY_ACTIONS:
                    if other != attr and getattr(self.cfg, other) == combo:
                        setattr(self.cfg, other, "")
                for m in self.cfg.sounds:
                    if m.hotkey == combo:
                        m.hotkey = ""
                        if m.id in self.pads:
                            self.pads[m.id].update()
        setattr(self.cfg, attr, combo)
        self.cfg.save()
        self.register_hotkeys()

    def open_settings(self, page: str = "appearance"):
        SettingsDialog(self, page).exec()
        self.register_hotkeys()   # in case a capture was cancelled

    def apply_theme(self, name: str):
        self.cfg.theme = theme.apply(QApplication.instance(), name)
        icons.retheme()
        self.pill.setText("")   # forces _update_flow to repaint its icon
        self._update_flow()
        self._paint_logo()
        self._save_later()

    def _paint_logo(self):
        dpr = self.devicePixelRatioF() or 1.0
        pm = theme.logo_pixmap(int(34 * dpr), theme.T["accent"], theme.T["accent2"])
        pm.setDevicePixelRatio(dpr)
        self.logo.setPixmap(pm)

    def on_hotkey(self, action):
        b = self.browser
        if self.overlay.handle(action):
            return
        if action == "__stop__":
            self.stop_all()
        elif action == "__pause__":
            self.engine.pause_all()
        elif action == "__rec__":
            b.btn_rec.toggle()
            self.cue("start" if b.recorder.recording else "stop")
        elif action == "__clip__":
            self.cue("saved" if b.clip_last() else "fail")
        elif action == "__bplay__":
            b.toggle_play()
        elif action == "__live__":
            b.btn_live.toggle()
            self.cue("start" if self.cfg.browser_live else "stop")
        else:
            self.play(action)

    CUES = {"start": (660, 990), "stop": (990, 660), "saved": (880, 880, 1320), "fail": (330, 247)}

    def cue(self, kind: str | tuple):
        """A short beep in the headphones only (others never hear it), so a hotkey pressed
        in-game is confirmed without looking at the app. `kind` is a CUES name or the
        notes themselves (Hz; 0 = a gap)."""
        if not self.cfg.cue_sounds or self.engine.mon_stream is None:
            return
        notes, n = self.CUES[kind] if isinstance(kind, str) else kind, int(0.075 * SR)
        t = np.arange(n) / SR
        env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.008)   # 8 ms fade in/out
        tone = np.concatenate([np.sin(2 * np.pi * f * t) * env for f in notes]) * 0.18
        self.engine.play("__cue__", np.stack([tone, tone], 1).astype(np.float32), 1.0,
                         mode="restart", preview=True)

    def stop_all(self):
        self.engine.stop_all()
        self.browser.pause_media()

    # ------------------------------------------------------------------ sounds
    def _index(self):
        """Rebuild the id -> meta lookup (call after any change to cfg.sounds)."""
        self._meta = {m.id: m for m in self.cfg.sounds}

    def meta(self, sid) -> SoundMeta | None:
        return self._meta.get(sid)

    def gain_for(self, m: SoundMeta, volume=None) -> float:
        v = m.volume if volume is None else volume
        return v * (m.level_gain if self.cfg.level_volumes else 1.0)

    def play(self, sid):
        m = self.meta(sid)
        data = self.audio.get(sid)
        if m is None or data is None:
            return
        self.select(sid)
        v = self.engine.play(sid, data, self.gain_for(m), loop=m.loop, mode=m.mode)
        if v is None and not self.engine.active_outputs():
            self.status.setText("<span style='color:#ffb020'>No audio device is open — pick one "
                                "in Setup.</span>")

    def select(self, sid):
        if self.current != sid:
            if self.current in self.pads:
                self.pads[self.current].selected = False
                self.pads[self.current].update()
            self.current = sid
            self.start_frac = 0.0
            if sid in self.pads:
                self.pads[sid].selected = True
                self.pads[sid].update()
            m = self.meta(sid)
            name = m.name if m else ""
            self.np_name.setText(self.np_name.fontMetrics().elidedText(name, Qt.ElideRight, 186))

    def toggle_play_pause(self):
        sid = self.current
        if not sid:
            return
        st = self.engine.state(sid)
        if st:
            self.engine.set_paused(sid, not st[1])
            return
        m, data = self.meta(sid), self.audio.get(sid)
        if m and data is not None:
            frac = 0.0 if self.start_frac >= 0.995 else self.start_frac
            self.engine.play(sid, data, self.gain_for(m), loop=m.loop, mode="restart", start=frac)

    def stop_current(self):
        if self.current:
            self.engine.stop(self.current)
        self.start_frac = 0.0

    def _seek_preview(self, v):
        if self._seeking:
            m = self.meta(self.current) if self.current else None
            if m:
                self.np_time.setText(fmt_pos(v / 1000 * m.duration, m.duration))

    def do_seek(self):
        self._seeking = False
        if not self.current:
            return
        frac = self.seek.value() / 1000
        if not self.engine.seek(self.current, frac):
            self.start_frac = frac   # not playing: ▶ will start from here

    def preview(self, sid, volume=None):
        m = self.meta(sid)
        data = self.audio.get(sid)
        if m and data is not None:
            self.engine.play(sid + ":preview", data, self.gain_for(m, volume), mode="restart",
                             preview=True)

    def _rebuild_pads(self):
        """Sync the pad widgets with cfg.sounds: keep the ones that still exist, create
        the new ones, drop the removed ones."""
        self._index()
        keep = {m.id for m in self.cfg.sounds}
        for sid in [s for s in self.pads if s not in keep]:
            p = self.pads.pop(sid)
            p.setParent(None)
            p.deleteLater()
        ordered = []
        for m in self.cfg.sounds:
            p = self.pads.get(m.id)
            if p is None:
                p = Pad(m, self.cfg.pad_width)
                p.clicked.connect(self.play)
                p.menu.connect(self.pad_menu)
                self.pads[m.id] = p
            p.state = "ready" if m.id in self.audio else p.state
            p.selected = m.id == self.current
            ordered.append(p)
        self.grid.set_pads(ordered)
        self.apply_filter(self.search.text())
        self._update_status()

    def apply_filter(self, text):
        t = text.strip().lower()
        for m in self.cfg.sounds:
            p = self.pads.get(m.id)
            if p:
                p.setProperty("filtered", bool(t) and t not in m.name.lower())
        self.grid.relayout(force=True)

    def _load_all(self):
        todo = [m for m in self.cfg.sounds if m.id not in self.audio]
        keep = {m.id for m in self.cfg.sounds}

        def run():
            t0 = time.monotonic()
            for m in todo:
                try:
                    data = load_sound(m)   # from the cache after the first run
                    self.engine.prepare(m.id, data)
                    self.bridge.loaded.emit(m.id, data, "")
                except Exception as e:  # noqa: BLE001
                    log.warning("can't load %s: %s", m.file, e)
                    self.bridge.loaded.emit(m.id, None, str(e))
            prune_cache(keep)
            log.info("loaded %d sounds in %.1fs", len(todo), time.monotonic() - t0)
        self._load_thread = threading.Thread(target=run, daemon=True, name="load")
        self._load_thread.start()

    def on_loaded(self, sid, data, err):
        p = self.pads.get(sid)
        if data is not None:
            self.audio[sid] = data
            m = self.meta(sid)
            if m and not m.duration:
                m.duration = len(data) / SR
            if m and not m.fingerprint:   # sounds imported before fingerprints existed
                m.fingerprint = fingerprint(m.file)
                self._save_later()
        if p:
            p.state = "ready" if data is not None else "error"
            p.error = err
            p.update()

    def add_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Add sounds", str(Path.home()),
                                                f"Audio ({exts});;All files (*)")
        if files:
            self.import_files(files)

    def import_files(self, files):
        files = [f for f in files if f]
        if not files:
            return
        self._pending_imports += len(files)
        start = len(self.cfg.sounds)
        known = {m.fingerprint: m.name for m in self.cfg.sounds if m.fingerprint}

        def run():
            for i, f in enumerate(files):
                try:
                    fp = fingerprint(f)
                    if fp and fp in known:
                        raise RuntimeError(f"already in your library as “{known[fp]}”")
                    meta, data = import_file(f, PAD_COLORS[(start + i) % len(PAD_COLORS)])
                    if fp:
                        known[fp] = meta.name   # the same file twice in one drop
                    self.engine.prepare(meta.id, data)
                    self.bridge.imported.emit(meta, data, "")
                except Exception as e:  # noqa: BLE001
                    log.warning("can't import %s: %s", f, e)
                    self.bridge.imported.emit(None, None, f"{Path(f).name}: {e}")
        threading.Thread(target=run, daemon=True, name="import").start()
        self.status.setText(f"Importing {len(files)} file(s)…")

    def on_imported(self, meta, data, err):
        self._pending_imports -= 1
        if meta is not None:
            self.cfg.sounds.append(meta)
            self._index()
            self.audio[meta.id] = data
        else:
            self._import_errors.append(err)
        if self._pending_imports <= 0:
            self._pending_imports = 0
            self.cfg.save()
            self._rebuild_pads()
            if self._import_errors:
                QMessageBox.warning(self, "Some files weren't added",
                                    "\n".join(self._import_errors[:15]))
                self._import_errors = []

    def on_clip(self, data, name):
        """A clip recorded in the browser tab becomes a normal sound pad."""
        try:
            meta, data = save_clip(data, name, PAD_COLORS[len(self.cfg.sounds) % len(PAD_COLORS)])
        except Exception as e:  # noqa: BLE001
            log.exception("can't save clip")
            QMessageBox.warning(self, "Couldn't save clip", str(e))
            return
        self.cfg.sounds.append(meta)
        self._index()
        self.audio[meta.id] = data
        threading.Thread(target=self.engine.prepare, args=(meta.id, data), daemon=True).start()
        self.cfg.save()
        self._rebuild_pads()
        self.status.setText(f"Added “{meta.name}” ({meta.duration:.1f}s) to Sounds — "
                            "right-click it there to rename or set a hotkey.")

    def on_reorder(self, sid, target):
        m = self.meta(sid)
        if not m:
            return
        self.cfg.sounds.remove(m)
        self.cfg.sounds.insert(min(target, len(self.cfg.sounds)), m)
        self.cfg.save()
        self._rebuild_pads()

    def pad_menu(self, sid, pos):
        m = self.meta(sid)
        if not m:
            return
        menu = QMenu(self)
        a_stop = (menu.addAction(icons.icon("stop"), "Stop") if self.engine.state(sid)
                  else None)
        a_prev = menu.addAction(icons.icon("headphones"), "Preview (only me)")
        a_edit = menu.addAction(icons.icon("edit"), "Edit… (name, volume, hotkey, loop)")
        a_hk = menu.addAction(icons.icon("keyboard"), "Set hotkey…")
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash", "danger_text"), "Remove")
        act = menu.exec(pos)
        if act is not None and act == a_stop:
            self.engine.stop(sid)
        elif act == a_prev:
            self.preview(sid)
        elif act == a_edit:
            self.edit(sid)
        elif act == a_hk:
            d = HotkeyDialog(self.hotkeys, self)
            if d.exec() and d.result_combo:
                m.hotkey = d.result_combo
                self._clear_dupe_hotkey(m)
                self.cfg.save()
                self.pads[sid].update()
            self.register_hotkeys()
        elif act == a_del:
            if QMessageBox.question(self, "Remove sound", f"Remove “{m.name}”?") == QMessageBox.Yes:
                self.remove_sound(sid)

    def remove_sound(self, sid: str):
        m = self.meta(sid)
        if not m:
            return
        self.engine.stop(sid)
        self.cfg.sounds.remove(m)
        self.audio.pop(sid, None)
        self.engine.forget(sid)
        delete_file(m)
        if self.current == sid:
            self.current = None
            self.np_name.setText("Click a sound to control it here")
        self.cfg.save()
        self._rebuild_pads()
        self.register_hotkeys()

    def _clear_dupe_hotkey(self, m):
        for o in self.cfg.sounds:
            if o is not m and o.hotkey and o.hotkey == m.hotkey:
                o.hotkey = ""
                if o.id in self.pads:
                    self.pads[o.id].update()
        for attr, *_ in HOTKEY_ACTIONS:
            if m.hotkey and m.hotkey == getattr(self.cfg, attr):
                setattr(self.cfg, attr, "")

    def edit(self, sid):
        m = self.meta(sid)
        d = EditDialog(m, self.hotkeys, self.preview, self)
        d.hotkeys_changed.connect(self.register_hotkeys)
        if d.exec():
            d.apply()
            self._clear_dupe_hotkey(m)
            self.engine.set_gain(sid, self.gain_for(m))
            self.cfg.save()
            self.pads[sid].update()
            self.apply_filter(self.search.text())
        self.register_hotkeys()

    # ------------------------------------------------------------------ test mode
    def on_mic_check(self, on):
        self.engine.ring_mon.clear()
        self.engine.mic_check = on
        self.btn_check.setText("Stop hearing it" if on else "Hear what they hear")
        self.mic_banner.setVisible(on)
        if on:
            self._pulse.start()   # impossible to miss, and cheap
        else:
            self._pulse.stop()
            self._banner_fx.setOpacity(1.0)
        self.setWindowTitle("● MIC LIVE IN HEADPHONES — Soundboard" if on else "Soundboard")
        self.mic_lbl.setStyleSheet("color:#ff4d4f; font-weight:700;" if on else
                                   "font-weight:600;")
        self.mic_meter.hot = on
        if on and not self.cfg.mic_enabled:
            self.status.setText("<span style='color:#ffb020'>“My mic” is off — "
                                "nobody (including you) will hear your mic.</span>")

    def start_test(self):
        if self.engine.main_stream is None:
            QMessageBox.information(self, "Test",
                                    "Set up the virtual cable first (see How it works).")
            return
        # Capture the far end of the virtual cable too, so the test hears exactly
        # what Discord / the game hears (not just our internal mix).
        self._stop_capture()
        self._cap, self._cap_rate = [], None
        vm = eng.virtual_mic_for(self.cfg.main_device)
        self._cap_name = vm
        if vm:
            idx = eng.find_device("input", vm)
            if idx is not None:
                try:
                    self._cap_rate = int(sd.query_devices(idx)["default_samplerate"])
                    self._cap_stream = sd.InputStream(
                        device=idx, samplerate=self._cap_rate, channels=2, dtype="float32",
                        callback=lambda i, f, t, s: self._cap.append(i.copy()))
                    self._cap_stream.start()
                except Exception:  # noqa: BLE001 - fall back to the internal mix
                    log.warning("can't capture %s for the test; using the internal mix",
                                vm, exc_info=True)
                    self._cap_stream = None
        self.engine.start_test_record(6.0)
        self.btn_rec.setEnabled(False)
        self.test_result.hide()
        self._rec_started = time.monotonic()

    def _stop_capture(self) -> bool:
        """Close the test's cable-capture stream if one is open. True if there was one."""
        s, self._cap_stream = self._cap_stream, None
        if s is None:
            return False
        try:
            s.stop()
            s.close()
        except Exception:  # noqa: BLE001
            log.debug("closing the test capture stream raised", exc_info=True)
        return True

    def _finish_test(self, internal, rate):
        e = self.engine
        cable = False
        data = internal
        if self._stop_capture() and self._cap:
            data, rate, cable = np.concatenate(self._cap), self._cap_rate, True
        mic = e.take_mic_recording()
        try:
            r = analyze_output(data, rate, mic[0] if mic else None, mic[1] if mic else SR,
                               self.cfg.sound_vol)
            self.test_result.setText(summary_html(r, self._cap_name if cable else None))
        except Exception as ex:  # noqa: BLE001
            log.exception("test analysis failed")
            self.test_result.setText(
                f"<span style='color:#ff4d4f'>Test analysis failed: {ex}</span>")
        self.test_result.show()
        return data, rate

    # ------------------------------------------------------------------ tick
    def tick(self):
        e = self.engine
        self._tick_n += 1
        if self._tick_n % 30 == 0:   # about once a second
            if e.check_streams() or sum(e.xruns.values()) != self._xruns_shown:
                self._update_status()
            self.voice.poll()
        playing = e.playing()
        for sid, p in self.pads.items():
            prog, paused = playing.get(sid, (None, False))
            if prog != p.progress or paused != p.paused:
                p.progress, p.paused = prog, paused
                p.update()
        self._update_transport(playing)
        self._update_chips(playing)
        self.overlay.tick(playing)
        self.out_meter.set_level(e.level_main)
        self.mic_meter.set_level(e.level_mic if e.mic_stream else 0.0)
        talking = e.mic_stream is not None and e.level_mic > 0.05
        if talking:
            self._talk_until = time.monotonic() + 0.8
        talking = time.monotonic() < self._talk_until
        if talking != self._talk_shown:
            self._talk_shown = talking
            self._update_flow(talking)
        e.level_main *= 0.9
        e.level_mic *= 0.9

        # test recording
        if e.recording:
            left = 6.0 - (time.monotonic() - self._rec_started)
            self.btn_rec.setText(f"Recording… talk / play sounds  ({max(left, 0):.0f}s)")
        elif e.rec_done is not None:
            data, rate = e.rec_done
            e.rec_done = None
            data, rate = self._finish_test(data, rate)
            e.play("__test__", data, 1.0, preview=True, src_rate=rate)
            self._rec_playing = True
            self.btn_rec.setText("Playing back what they heard…")
        elif self._rec_playing and "__test__" not in playing:
            self._rec_playing = False
            self.btn_rec.setEnabled(True)
            self.btn_rec.setText("Record 6s → play back")

        # auto push-to-talk: hold the game's PTT key only while a sound (or the live
        # browser) goes out. _ptt_held remembers exactly which key we pressed, so it's
        # always released even if the setting changes mid-sound.
        on_air = e.any_playing() or e.browser_on_air()
        want = self.cfg.ptt_key if (self.cfg.ptt_key and on_air) else None
        if want != self._ptt_held:
            self._release_ptt()
            if want and winkeys.press(want):
                self._ptt_held = want

    def _update_transport(self, playing):
        sid = self.current
        m = self.meta(sid) if sid else None
        enabled = m is not None
        for w in (self.btn_pp, self.btn_st, self.seek):
            w.setEnabled(enabled)
        if not m:
            return
        prog, paused = playing.get(sid, (None, False))
        live = prog is not None
        self._set_pp_icon("pause" if live and not paused else "play")
        if not self._seeking:
            frac = prog if live else self.start_frac
            self.seek.blockSignals(True)
            self.seek.setValue(int(frac * 1000))
            self.seek.blockSignals(False)
            self.np_time.setText(fmt_pos(frac * m.duration, m.duration))

    def _release_ptt(self):
        if self._ptt_held:
            winkeys.release(self._ptt_held)
            self._ptt_held = None

    def closeEvent(self, ev):
        self.timer.stop()
        self._release_ptt()
        self._stop_capture()
        self.cfg.save()
        self.overlay.shutdown()
        self.hotkeys.stop()
        self.browser.shutdown()
        self.voice.shutdown()
        self.engine.shutdown()
        log.info("closed cleanly (drop-outs %s, callback errors %s, stalls %d)",
                 self.engine.xruns, self.engine.cb_errors, self.engine.stalls)
        super().closeEvent(ev)
