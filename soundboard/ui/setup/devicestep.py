"""The setup guide's first step: the speakers and mic, as tiles, with a live level
and a test sound. Mixed into SetupWizard."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from soundboard.audio import engine as eng
from soundboard.core import feedback
from soundboard.ui.kit import icons
from soundboard.ui.kit.failreport import FailReport, mode_of
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.kit.choicetile import ChoiceTile
from soundboard.i18n import _
from soundboard.ui.setup.wizardkit import (BUN_H, BUN_PAD, HEADER_GAP, NOWHERE,
                                           SECTION_GAP, TILE_COLS, TILE_GAP, TILE_MIN_H,
                                           TILE_W, _bad, _choice_icon, _header, _label,
                                           _section, _split_name, _test_title, tile_h,
                                           WizardStep)
from soundboard.ui.setup.testtune import test_tune


MIC_SILENT_S = 10   # the mic open, nothing heard this long: the test failed


class DeviceStep(WizardStep):
    """SetupWizard's speakers and mic step."""

    def _choice_list(self, names: list[str], current: str | None,
                     on_pick, kind: str = "output",
                     beside: QWidget | None = None) -> tuple[QWidget, QButtonGroup]:
        """The devices as tiles in a grid (TILE_COLS across), each with its picture;
        the picked one is filled, ringed and ticked. Every tile is as tall as the
        longest name needs (tile_h), so short names don't float in a tall tile. More
        than two rows scroll. `beside`: the list's own control (the test sound, Send my
        voice too), after the tiles in their row when one row leaves it the room; its
        parent is then set (else the caller puts it under the list)."""
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(TILE_GAP)
        group = QButtonGroup(box)
        tiles = []
        for i, n in enumerate(names):
            title, sub = _split_name(n)
            tile = ChoiceTile(n, "stop" if n == NOWHERE else _choice_icon(n, kind),
                              TILE_W, TILE_MIN_H, title=title, sub=sub)
            tile.meter = kind == "input"   # the picked mic shows your voice's level
            tiles.append(tile)
            tile.setToolTip(n)
            tile.setProperty("device", n)
            group.addButton(tile)
            grid.addWidget(tile, i // TILE_COLS, i % TILE_COLS)
            if n == current:
                tile.setChecked(True)
        if not names:   # the line on its own, as tall as its words: in the tiles' grid it
            # wrapped into a narrow strip (the spare width all went to the room column),
            # in a box a tile tall
            none = _label(_("<span style='color:{colour}'>None found. Plug it in, close this, "
                            "then press <b>Step-by-step guide</b> on the Setup tab.</span>",
                            colour=_bad()))
            group.setParent(none)   # (the empty grid goes: the group stays, with no tiles)
            return none, group
        h = tile_h(tiles)
        grid.setColumnStretch(TILE_COLS, 1)   # tiles keep their size; room goes to the end
        if beside is not None and 0 < len(names) <= TILE_COLS - 2:
            # in the tiles' row, not on a line of its own under them: at 150 % on a
            # 1080p screen the step was taller than the window and scrolled, its last
            # lines cut off at the bottom. Two free tiles' room at least: in one it sat
            # squeezed against the edge (more devices: the step scrolls, as it did)
            span = TILE_COLS - len(names)
            if beside.sizeHint().width() <= span * TILE_W + (span - 1) * TILE_GAP:
                grid.addWidget(beside, 0, len(names), 1, span + 1,   # (+ the room column)
                               Qt.AlignmentFlag.AlignVCenter)
        group.buttonClicked.connect(lambda b: on_pick(b.property("device")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(box)
        rows = min(2, max(1, -(-len(names) // TILE_COLS)))
        scroll.setFixedHeight(rows * h + (rows - 1) * TILE_GAP)
        return scroll, group

    def _page_devices(self) -> QWidget:
        """Step 1: the headphones or speakers (with a test sound) and, under them, the
        mic (its tile shows your voice's level), on one page."""
        p = QWidget()
        v = QVBoxLayout(p)
        self.bun_mic = BunnyWidget("headphones", height=BUN_H, pad=BUN_PAD)
        self.bun_phones = self.bun_mic   # (one Bun: talks along, and bursts on the test)
        v.addLayout(_header(_("Your speakers and mic"),
                            _label(_("Pick the ones you use for gaming. <b>Say something</b>: "
                                     "the bar on your mic should move.")),
                            self.bun_mic))
        v.addSpacing(HEADER_GAP)
        # the headphones, then the test sound's button under them (beside their title,
        # a long title or button in some languages made the step wider than the tiles)
        v.addWidget(_section(_("Headphones or speakers")))
        v.addSpacing(6)
        outs = [d["name"] for d in eng.list_devices("output") if not eng.is_virtual(d["name"])]
        cur = self.win.cfg.mon_device if self.win.cfg.mon_device in outs else \
            (outs[0] if outs else None)
        if cur and cur != self.win.cfg.mon_device:   # the saved one is missing
            self._pick_headphones(cur)
        test = QWidget()
        row = QHBoxLayout(test)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        play = self.btn_test = QPushButton(_test_title())
        icons.set_icon(play, "volume")
        play.setToolTip(_("Only you hear it. Didn't hear it? Pick another one and try again."))
        play.setAccessibleName(_test_title())
        play.setAutoDefault(False)   # (Enter is Next's)
        play.clicked.connect(self.test_sound)
        row.addWidget(play)
        self.test_hint = _label("", "font-size:10pt;")
        self.test_hint.setObjectName("muted")
        row.addWidget(self.test_hint, 1)
        lst, __ = self._choice_list(outs, cur,
                                   lambda n: self._pick_headphones(n, by_user=True),
                                   beside=test)
        v.addWidget(lst)
        if test.parentWidget() is None:   # (no room beside the tiles: under them)
            v.addSpacing(8)
            v.addWidget(test)
        v.addSpacing(SECTION_GAP + 4)
        # the mic
        v.addWidget(_section(_("Microphone")))
        v.addSpacing(6)
        mics = [d["name"] for d in eng.list_devices("input") if not eng.is_virtual(d["name"])]
        self._no_mics = not mics
        cur = self.win.cfg.mic_device if self.win.cfg.mic_device in mics else \
            (mics[0] if mics else None)
        if cur and cur != self.win.cfg.mic_device:   # the saved one is missing
            self._pick_mic(cur)
        # the mic's one option: beside its tiles when there's room, else under what the
        # mic hears (on the far right of the page it sat apart from the mic it's about)
        self.chk_send = QCheckBox(_("Send my voice too"))
        self.chk_send.setToolTip(_("Send my voice too (untick if you only want your sounds to "
                                   "go out, not your mic)"))
        self.chk_send.setChecked(self.win.cfg.mic_enabled)
        lst, self.mic_group = self._choice_list(
            mics, cur, lambda n: self._pick_mic(n, by_user=True), "input",
            beside=self.chk_send)
        v.addWidget(lst)   # the picked mic's tile shows your voice's level along its foot
        # under the tiles, on their left edge: what the mic hears
        v.addSpacing(8)
        self.mic_heard = _label("", "font-size:10pt;")
        v.addWidget(self.mic_heard)
        # the mic test failed (won't open, or silent): tell us, before giving up
        self.mic_report = FailReport(self._mic_fail_details)
        v.addWidget(self.mic_report)
        if self.chk_send.parentWidget() is None:
            v.addSpacing(4)
            v.addWidget(self.chk_send, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)
        self._mic_peak_seen = False
        self._mic_wait_since = time.monotonic()
        return p

    def _mic_fail(self) -> str:
        """Why the mic test failed, as the report's short code ("" = it hasn't): no
        mic, the mic won't open, or open but nothing heard for MIC_SILENT_S."""
        e = self.win.engine
        if e.mic_stream is None and self._no_mics:
            return "no-mic"
        if e.mic_stream is None:
            err = e.errors_snapshot().get("mic")
            return feedback.mic_error("mic-open", err) if err else ""   # ("" = opening)
        if (not self._mic_peak_seen
                and time.monotonic() - self._mic_wait_since > MIC_SILENT_S):
            return "mic-silent"
        return ""

    def _mic_fail_details(self) -> dict:
        return {"mic": self.win.cfg.mic_device or "", "mode": mode_of(self.win.cfg.route),
                "err": self._mic_fail() or "mic-test"}

    def _pick_mic(self, name: str, by_user: bool = False):
        if by_user:
            self._user_picked.add("mic_device")
        self.win.cfg.mic_device = name
        self._mic_peak_seen = False
        self._mic_wait_since = time.monotonic()
        self._reopen("mic_device", self.win.engine.set_mic_device)

    def _pick_headphones(self, name: str, by_user: bool = False):
        if by_user:
            self._user_picked.add("mon_device")
        self.win.cfg.mon_device = name
        self._reopen("mon_device", self.win.engine.set_mon_device)

    def _reopen(self, attr: str, open_it):
        """The picked device is opened on the device thread (the window never waits on
        a slow driver), with the one in the config when its turn comes: quick clicks
        through the list open only where they ended up."""
        cfg = self.win.cfg
        self.win.devctl._device_job(lambda: (lambda n=getattr(cfg, attr): open_it(n)))

    def _flash_hint(self, text: str, ms: int):
        self.test_hint.setText(text)
        self._hint_serial = getattr(self, "_hint_serial", 0) + 1
        serial = self._hint_serial
        # self as the receiver: the guide may be closed before it fires
        QTimer.singleShot(ms, self, lambda: serial == self._hint_serial
                          and self.test_hint.setText(""))

    def test_sound(self):
        if self.win.engine.mon_stream is None:
            self._flash_hint(_("<b>No headphones open</b>, pick another above."), 3500)
            return
        self.win.engine.play("__setup__", test_tune(), 1.0, preview=True)
        self.bun_phones.burst()
        self._flash_hint(_("<b>Playing… hear it?</b>"), 1500)
