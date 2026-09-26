"""The main window: pads, transport, browser tab, the audio panel, auto push-to-talk."""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit,
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
from soundboard.ui.panel import EqPanel, VolumeBox, hint_label, section_label
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
        self._save_timer.timeout.connect(self.cfg.save)

        self._build_ui()
        self._init_devices()
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
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        rv = QVBoxLayout(root)
        rv.setContentsMargins(14, 10, 14, 10)
        rv.setSpacing(8)

        # ---- header: logo + name, settings on the right
        head = QHBoxLayout()
        head.setSpacing(10)
        self.logo = QLabel()
        self.logo.setFixedSize(34, 34)
        head.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        wm = QLabel("SOUNDBOARD")
        wm.setObjectName("wordmark")
        tag = QLabel("sounds + browser, straight into your mic")
        tag.setObjectName("tagline")
        names.addWidget(wm)
        names.addWidget(tag)
        head.addLayout(names)
        head.addStretch(1)
        gear = QPushButton("⚙  Settings")
        gear.setObjectName("settings")
        gear.setToolTip("Themes, hotkeys and more")
        gear.clicked.connect(lambda: self.open_settings())
        head.addWidget(gear)
        rv.addLayout(head)
        self._paint_logo()

        h = QHBoxLayout()
        h.setSpacing(14)
        rv.addLayout(h, 1)

        # ---- left: tabs (sounds / browser), with the mic banner + status around them
        outer = QVBoxLayout()
        self.mic_banner = QPushButton("🎤  YOU'RE HEARING YOUR MIC OUTPUT  —  mic + sounds, "
                                      "exactly what others hear   ·   click to turn off")
        self.mic_banner.setObjectName("micbanner")
        self.mic_banner.setCursor(Qt.PointingHandCursor)
        self.mic_banner.clicked.connect(lambda: self.btn_check.setChecked(False))
        self.mic_banner.hide()
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
        outer.addWidget(self.mic_banner)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        outer.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_sounds_page(), "🎛  Sounds")
        browser_page = QWidget()
        bl = QVBoxLayout(browser_page)
        bl.setContentsMargins(0, 8, 0, 0)
        self.browser = BrowserTab(self.engine, self.cfg, self._save_later, Meter)
        self.browser.clip_ready.connect(self.on_clip)
        bl.addWidget(self.browser)
        self.tabs.addTab(browser_page, "🌐  Browser → mic")
        self.tabs.setCurrentIndex(self.cfg.tab if 0 <= self.cfg.tab < self.tabs.count() else 0)
        self.tabs.currentChanged.connect(lambda i: self.set_option("tab", i))

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        outer.addWidget(self.status)
        h.addLayout(outer, 1)

        # ---- right: audio panel
        pscroll = QScrollArea()
        pscroll.setWidget(self._build_panel())
        pscroll.setWidgetResizable(True)
        pscroll.setFrameShape(QFrame.NoFrame)
        pscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pscroll.setFixedWidth(344)
        h.addWidget(pscroll)

    def _build_sounds_page(self) -> QWidget:
        page = QWidget()
        left = QVBoxLayout(page)
        left.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        add = QPushButton("＋  Add sounds")
        add.setObjectName("primary")
        add.clicked.connect(self.add_dialog)
        self.stop_btn = QPushButton("■  Stop all")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setToolTip("Stops every sound and pauses the browser")
        self.stop_btn.clicked.connect(self.stop_all)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sounds…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        bar.addWidget(add)
        bar.addWidget(self.stop_btn)
        bar.addWidget(self.search, 1)
        size = QSlider(Qt.Horizontal)
        size.setRange(110, 240)
        size.setValue(self.cfg.pad_width)
        size.setFixedWidth(90)
        size.setToolTip("Pad size")
        size.valueChanged.connect(self.set_pad_width)
        no_wheel(size)
        bar.addWidget(QLabel("Size"))
        bar.addWidget(size)
        left.addLayout(bar)

        self.grid = PadGrid()
        self.grid.reorder.connect(self.on_reorder)
        self.grid.files_dropped.connect(self.import_files)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        scroll.setFrameShape(QFrame.NoFrame)
        left.addWidget(scroll, 1)

        tb = QFrame()
        tb.setObjectName("transport")
        th = QHBoxLayout(tb)
        th.setContentsMargins(10, 8, 14, 8)
        th.setSpacing(10)
        self.btn_pp = QPushButton("▶")
        self.btn_pp.setObjectName("round")
        self.btn_pp.setToolTip("Play / pause")
        self.btn_pp.clicked.connect(self.toggle_play_pause)
        self.btn_st = QPushButton("■")
        self.btn_st.setObjectName("round")
        self.btn_st.setToolTip("Stop")
        self.btn_st.clicked.connect(self.stop_current)
        for b in (self.btn_pp, self.btn_st):
            b.setFixedSize(40, 36)
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
        left.addWidget(tb)
        return page

    def _build_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(330)
        panel.setMinimumHeight(0)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(16, 16, 16, 16)
        pv.setSpacing(8)
        c = self.cfg

        # ---- plain-English picture of where the audio goes
        card = QFrame()
        card.setObjectName("howcard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 12)
        cv.setSpacing(3)
        cv.addWidget(section_label("HOW IT WORKS"))
        self.flow_mic = QLabel()
        self.flow_snd = QLabel("🔊  Your soundboard sounds")
        arrow = QLabel("⬇   the app mixes them together   ⬇")
        arrow.setObjectName("muted")
        self.flow_out = QLabel()
        for w in (self.flow_mic, self.flow_snd, arrow, self.flow_out):
            w.setTextFormat(Qt.RichText)
            w.setWordWrap(True)
            cv.addWidget(w)
        self.step_lbl = QLabel()
        self.step_lbl.setWordWrap(True)
        self.step_lbl.setTextFormat(Qt.RichText)
        self.step_lbl.setObjectName("stepbox")
        cv.addWidget(self.step_lbl)
        self.btn_install = QPushButton("⬇  Install the free virtual cable")
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(self.install_cable)
        cv.addWidget(self.btn_install)
        self.btn_rescan = QPushButton("⟳  I've installed it — check again")
        self.btn_rescan.setObjectName("small")
        self.btn_rescan.clicked.connect(self.refresh_devices)
        cv.addWidget(self.btn_rescan)
        self.btn_nomic = QPushButton("Game has no microphone setting? Click here")
        self.btn_nomic.setObjectName("small")
        self.btn_nomic.clicked.connect(self.open_windows_mic)
        cv.addWidget(self.btn_nomic)
        pv.addWidget(card)

        pv.addWidget(section_label("YOUR MIC"))
        self.chk_mic = QCheckBox("Mix my mic in (so they still hear me)")
        self.chk_mic.setChecked(c.mic_enabled)
        self.chk_mic.toggled.connect(self.on_mic_toggle)
        pv.addWidget(self.chk_mic)
        mic_row = QHBoxLayout()
        self.mic_lbl = QLabel("Mic")
        mic_row.addWidget(self.mic_lbl)
        self.mic_meter = Meter()
        mic_row.addWidget(self.mic_meter, 1)
        pv.addLayout(mic_row)

        pv.addWidget(section_label("VOLUME"))
        self.vol_sound = VolumeBox(
            "🔊  Soundboard → them",
            "How loud your sounds are for Discord / the game. Type up to 1000% in the box.",
            c.sound_vol)
        self.vol_mic = VolumeBox("🎤  Your voice → them",
                                 "How loud your mic is for Discord / the game.", c.mic_vol)
        self.vol_mon = VolumeBox("🎧  Your headphones",
                                 "Only what YOU hear. Doesn't change anything for them.",
                                 c.mon_vol)
        for box, key in ((self.vol_sound, "sound_vol"), (self.vol_mic, "mic_vol"),
                         (self.vol_mon, "mon_vol")):
            box.changed.connect(lambda v, key=key: self.set_option(key, v))
            pv.addWidget(box)
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Going out"))
        self.out_meter = Meter()
        self.out_meter.setToolTip("Level of what Discord / the game receives")
        out_row.addWidget(self.out_meter, 1)
        pv.addLayout(out_row)

        pv.addWidget(section_label("TEST MODE"))
        self.btn_check = QPushButton("🎤  Listen to my mic output")
        self.btn_check.setObjectName("miccheck")
        self.btn_check.setCheckable(True)
        self.btn_check.toggled.connect(self.on_mic_check)
        pv.addWidget(self.btn_check)
        pv.addWidget(hint_label("Plays your mic into your headphones on top of the sounds — "
                                "exactly what others hear. A red banner shows while it's on."))
        self.btn_rec = QPushButton("⏺  Record 6s → play back")
        self.btn_rec.clicked.connect(self.start_test)
        pv.addWidget(self.btn_rec)
        pv.addWidget(hint_label("Talk while a sound plays. Records what Discord / the game "
                                "actually receives, plays it back, and tells you if your voice "
                                "+ sounds are in it."))
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        self.test_result.setTextFormat(Qt.RichText)
        self.test_result.setObjectName("resultbox")
        self.test_result.hide()
        pv.addWidget(self.test_result)

        # ---- everything below is advanced, hidden until you open it
        self.btn_adv = QPushButton()
        self.btn_adv.setObjectName("advtoggle")
        self.btn_adv.setCheckable(True)
        pv.addWidget(self.btn_adv)
        adv = QWidget()
        av = QVBoxLayout(adv)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(8)
        pv.addWidget(adv)

        av.addWidget(section_label("DEVICES"))
        av.addWidget(hint_label("Already set up for you — only change these if something's "
                                "wrong."))
        av.addWidget(hint_label("Sounds + my voice get sent into (the cable):"))
        self.cb_main = QComboBox()
        av.addWidget(self.cb_main)
        self.setup_hint = hint_label("")
        av.addWidget(self.setup_hint)
        av.addWidget(hint_label("I listen on (my headphones):"))
        self.cb_mon = QComboBox()
        av.addWidget(self.cb_mon)
        av.addWidget(hint_label("My real microphone:"))
        self.cb_mic = QComboBox()
        av.addWidget(self.cb_mic)
        no_wheel(self.cb_main, self.cb_mon, self.cb_mic)
        for cb, attr in ((self.cb_main, "main_device"), (self.cb_mon, "mon_device"),
                         (self.cb_mic, "mic_device")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: self.on_device(cb, attr))
        ref = QPushButton("⟳ Re-scan devices")
        ref.setObjectName("small")
        ref.clicked.connect(self.refresh_devices)
        av.addWidget(ref)

        av.addWidget(section_label("SOUND OPTIONS"))
        self.chk_monitor = QCheckBox("Hear sounds myself")
        self.chk_monitor.setChecked(c.monitor_sounds)
        self.chk_monitor.toggled.connect(lambda b: self.set_option("monitor_sounds", b))
        av.addWidget(self.chk_monitor)
        self.chk_level = QCheckBox("Level volumes (all sounds equally loud)")
        self.chk_level.setChecked(c.level_volumes)
        self.chk_level.toggled.connect(self.on_level_toggle)
        av.addWidget(self.chk_level)

        self.eq = EqPanel(c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains)
        self.eq.changed.connect(self.on_eq)
        av.addWidget(self.eq)
        self.on_eq(*self.eq.state())   # push the saved EQ into the engine

        av.addWidget(section_label("HOTKEYS"))
        hk = QPushButton("⌨  Hotkeys, push-to-talk & more…")
        hk.setToolTip("Opens Settings → Hotkeys")
        hk.clicked.connect(lambda: self.open_settings("hotkeys"))
        av.addWidget(hk)

        def set_adv(on):
            adv.setVisible(on)
            self.btn_adv.setText("⚙  Advanced  ▾   (hide)" if on else
                                 "⚙  Advanced  ▸   devices, EQ…")
            self.cfg.show_advanced = on
            self._save_later()
        self.btn_adv.toggled.connect(set_adv)
        self.btn_adv.setChecked(c.show_advanced)
        set_adv(c.show_advanced)
        pv.addStretch()
        return panel

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
        text = (f"{n} sound{'s' if n != 1 else ''} · click to play · right-click to "
                "edit / set hotkey · drag to reorder · drop files to add")
        xr = sum(e.xruns.values())
        self._xruns_shown = xr
        if xr:
            tip = ("" if self.cfg.latency == "high" else
                   " — try ⚙ Settings → General → Audio buffering: Safer")
            text += (f"<br><span style='color:#ffb020'>{xr} audio drop-out"
                     f"{'s' if xr != 1 else ''} since start{tip}</span>")
        self.status.setText(text)

    def _update_flow(self, talking=False):
        e = self.engine
        ok, bad = "#13ce66", "#ff4d4f"
        if e.mic_stream is None or not self.cfg.mic_enabled:
            mic = f"🎤  Your mic  <b style='color:{bad}'>✗ off</b>"
        elif talking:
            mic = f"🎤  Your mic  <b style='color:{ok}'>✓ hearing you</b>"
        else:
            mic = f"🎤  Your mic  <b style='color:{ok}'>✓</b>"
        vm = self.virtual_mic
        any_cable = bool(eng.virtual_outputs())
        if not any_cable:
            state = "missing"
            out = f"🎙  Virtual mic  <b style='color:{bad}'>✗ not installed yet</b>"
            step = ("<b style='color:#ffb020'>One-time setup:</b> install the free virtual "
                    "cable. It's what lets Discord and games hear your sounds — without it, "
                    "only you can hear them.")
        elif vm and e.main_stream is not None:
            state = "ok"
            out = (f"🎙  <b style='color:{ok}'>{vm}</b> — your new mic "
                   f"<b style='color:{ok}'>✓ working</b>")
            step = (f"<b>The only thing you set:</b> in Discord or your game, pick "
                    f"<b style='color:{ok}'>{vm}</b> as your <b>microphone</b>.")
        else:
            state = "unrouted"
            out = f"🎙  Virtual mic  <b style='color:{bad}'>✗ not connected</b>"
            step = ("<b style='color:#ffb020'>Almost:</b> open <b>⚙ Advanced → Devices</b> and "
                    "set “Sounds + my voice get sent into” to your virtual cable.")
        self.flow_mic.setText(mic)
        self.flow_out.setText(out)
        self.step_lbl.setText(step)
        self.btn_install.setVisible(state == "missing")
        self.btn_rescan.setVisible(state == "missing")
        self.btn_nomic.setVisible(state == "ok")

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
        self.hotkeys.register(mapping)

    def on_hotkeys_failed(self, failed: list[str]):
        if failed:
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
        self._paint_logo()
        self._save_later()

    def _paint_logo(self):
        dpr = self.devicePixelRatioF() or 1.0
        pm = theme.logo_pixmap(int(34 * dpr), theme.T["accent"], theme.T["accent2"])
        pm.setDevicePixelRatio(dpr)
        self.logo.setPixmap(pm)

    def on_hotkey(self, action):
        b = self.browser
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

    def cue(self, kind: str):
        """A short beep in the headphones only (others never hear it), so a hotkey pressed
        in-game is confirmed without looking at the app."""
        if not self.cfg.cue_sounds or self.engine.mon_stream is None:
            return
        notes, n = self.CUES[kind], int(0.075 * SR)
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
                                "on the right.</span>")

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
        a_prev = menu.addAction("▶  Preview (only me)")
        a_edit = menu.addAction("✎  Edit… (name, volume, hotkey, loop)")
        a_hk = menu.addAction("⌨  Set hotkey…")
        menu.addSeparator()
        a_del = menu.addAction("🗑  Remove")
        act = menu.exec(pos)
        if act == a_prev:
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
        self.btn_check.setText("🔴  LISTENING TO MY MIC — click to stop" if on
                               else "🎤  Listen to my mic output")
        self.mic_banner.setVisible(on)
        if on:
            self._pulse.start()   # impossible to miss, and cheap
        else:
            self._pulse.stop()
            self._banner_fx.setOpacity(1.0)
        self.setWindowTitle("🔴 MIC LIVE IN HEADPHONES — Soundboard" if on else "Soundboard")
        self.mic_lbl.setStyleSheet("color:#ff4d4f; font-weight:700;" if on else "")
        self.mic_meter.hot = on
        if on and not self.cfg.mic_enabled:
            self.status.setText("<span style='color:#ffb020'>“Mix my mic in” is off — "
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
        playing = e.playing()
        for sid, p in self.pads.items():
            prog, paused = playing.get(sid, (None, False))
            if prog != p.progress or paused != p.paused:
                p.progress, p.paused = prog, paused
                p.update()
        self._update_transport(playing)
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
            self.btn_rec.setText(f"⏺  Recording… talk / play sounds  ({max(left, 0):.0f}s)")
        elif e.rec_done is not None:
            data, rate = e.rec_done
            e.rec_done = None
            data, rate = self._finish_test(data, rate)
            e.play("__test__", data, 1.0, preview=True, src_rate=rate)
            self._rec_playing = True
            self.btn_rec.setText("🔊  Playing back what they heard…")
        elif self._rec_playing and "__test__" not in playing:
            self._rec_playing = False
            self.btn_rec.setEnabled(True)
            self.btn_rec.setText("⏺  Record 6s → play back")

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
        self.btn_pp.setText("⏸" if live and not paused else "▶")
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
        self.hotkeys.stop()
        self.browser.shutdown()
        self.engine.shutdown()
        log.info("closed cleanly (drop-outs %s, callback errors %s, stalls %d)",
                 self.engine.xruns, self.engine.cb_errors, self.engine.stalls)
        super().closeEvent(ev)
