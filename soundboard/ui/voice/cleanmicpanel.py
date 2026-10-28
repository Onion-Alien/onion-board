"""The Voice tab's Clean mic card: background noise out of your mic (voicefx.cleanmic).

On or off, Light, Normal or Strong (DeepFilterNet, downloaded the first time it's
picked: voicefx.deepfilter), a live look at your mic and the cleaned mic, and Hear the
difference: 5 seconds of your mic recorded, then played as it was and cleaned, in your
headphones only. The chain does the cleaning (VoiceChain.set_clean); this card only
says what's wanted and shows how it's doing.
"""
from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.core import errors, usage
from soundboard.i18n import _
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.meters import Meter
from soundboard.ui.kit.panel import Flow, hint_label, section_label
from soundboard.ui.voice.voicetiles import BigSwitch
from soundboard.ui.voice.livevoice import download_bar
from soundboard.voicefx import cleanmic, deepfilter

TEST_S = 5            # Hear the difference: seconds recorded
METER_MS = 40         # the two meters' refresh while the card shows
METER_W = 420         # px: a meter's widest (stretched across a wide window it said nothing more)
LABEL_W = 130         # px: the meters' names, one column
PLAY_ID = "__clean_mic_test"
MB = round(deepfilter.SIZE / 1e6)


def strength_words(key: str) -> str:
    if key == "light":
        return _("Light: noise is turned well down, and your voice stays most natural.")
    if key == "strong":
        return _("Strong: nearly everything but your voice goes, even loud noise. Uses "
                 "about twice Normal's CPU.")
    return _("Normal: fans, keyboards and a TV go. Uses about 5% of one CPU core.")


class CleanMicPanel(QWidget):
    """`changed(settings)`: {"on", "strength"} to keep with the speech settings.
    `chain`: the Voice tab's VoiceChain; `engine`: for the mic's level, the test
    recording and playing it in your headphones."""
    changed = Signal(dict)
    live_changed = Signal(bool)
    _cleaned = Signal(object, object)   # the test's (raw, cleaned), from its worker
    _got = Signal(int, int)             # Strong's download: bytes so far, of
    _got_done = Signal(str)             # ...and how it ended ("" done, "-" cancelled)

    def __init__(self, chain, engine, saved=None):
        super().__init__()
        self.chain, self.engine = chain, engine
        self.s = cleanmic.clean_settings(saved)
        self.ok = cleanmic.available()
        if not self.ok:
            self.s["on"] = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.title = section_label(_("Clean mic"))
        v.addWidget(self.title)
        # the big ON/OFF, as the other cards': the Voice tab puts `head` after the name
        self.b_on = BigSwitch(_("Clean mic"))
        self.head = QWidget()
        hh = QHBoxLayout(self.head)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(self.b_on)
        self.intro = hint_label(_(
            "Takes fans, keyboards and other background noise out of your mic while you "
            "talk. It runs on this PC and works with every app and every voice."))
        v.addWidget(self.intro)
        self.lbl_missing = hint_label(_("Clean mic isn't in this copy of Onion Board."))
        theme.set_tone(self.lbl_missing, "warn")
        v.addWidget(self.lbl_missing)   # in the layout first: shown bare it's a window
        self.lbl_missing.setVisible(not self.ok)
        self.lbl_error = hint_label("")
        theme.set_tone(self.lbl_error, "error")
        self.lbl_error.hide()
        v.addWidget(self.lbl_error)

        # the rest only where RNNoise is here (greyed out it said nothing, and the
        # picked strength's words were hard to read on its disabled fill)
        self.body = QWidget()
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(12)
        v.addWidget(self.body)
        self.body.setVisible(self.ok)

        # ---- how strong: Light or Normal
        bv.addWidget(section_label(_("How strong")))
        row = Flow(gap=4)
        self.strength = QButtonGroup(self)
        self.strength.setExclusive(True)
        self.b_strength: dict[str, QPushButton] = {}
        for key, name in (("light", _("Light")), ("normal", _("Normal")),
                          ("strong", _("Strong"))):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(strength_words(key))
            b.setAccessibleName(_("{label} cleaning", label=name))
            b.clicked.connect(lambda _c=False, k=key: self._pick(k))
            self.strength.addButton(b)
            self.b_strength[key] = b
            row.addWidget(b)
        bv.addLayout(row)
        self.lbl_strength = hint_label("")
        bv.addWidget(self.lbl_strength)
        self.lbl_fallback = hint_label("")   # Strong stopped: Normal cleans instead
        theme.set_tone(self.lbl_fallback, "warn")
        self.lbl_fallback.hide()
        bv.addWidget(self.lbl_fallback)

        # ---- Strong's download: offered when Strong is picked and isn't here yet
        self.get_box = QWidget()
        gv = QVBoxLayout(self.get_box)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(6)
        self.lbl_get = hint_label("")
        gv.addWidget(self.lbl_get)
        self.get_bar = download_bar()
        self.get_bar.setAccessibleName(_("Strong download"))
        gv.addWidget(self.get_bar)
        gr = QHBoxLayout()
        gr.setSpacing(8)
        self.b_get = QPushButton(_("Download ({size} MB)", size=MB))
        icons.set_icon(self.b_get, "download", size=16)
        self.b_get.clicked.connect(self._download)
        self.b_cancel = QPushButton(_("Cancel"))
        self.b_cancel.clicked.connect(self._cancel_download)
        self.b_cancel.hide()
        gr.addWidget(self.b_get)
        gr.addWidget(self.b_cancel)
        gr.addStretch(1)
        gv.addLayout(gr)
        self.get_box.hide()
        bv.addWidget(self.get_box)
        # ...and taken off this PC again, while it's the one picked
        self.b_drop = QPushButton(_("Remove Strong's download"))
        self.b_drop.setToolTip(_("Frees {size} MB. Normal cleans instead.", size=MB))
        icons.set_icon(self.b_drop, "trash", size=16)
        self.b_drop.clicked.connect(self._remove_download)
        dr = QHBoxLayout()
        dr.addWidget(self.b_drop)
        dr.addStretch(1)
        bv.addLayout(dr)
        self._getting = False
        self._stop_get = False
        self._got.connect(self._on_got)
        self._got_done.connect(self._on_got_done)

        # ---- right now: your mic, and what's left of it once it's cleaned
        bv.addWidget(section_label(_("Right now")))
        self.m_mic, self.m_clean = Meter(), Meter()
        for name, m in ((_("Your mic"), self.m_mic), (_("Cleaned"), self.m_clean)):
            r = QHBoxLayout()
            r.setSpacing(12)
            lbl = QLabel(name)
            lbl.setMinimumWidth(LABEL_W)
            r.addWidget(lbl)
            m.setMaximumWidth(METER_W)
            m.setAccessibleName(name)
            r.addWidget(m, 1)
            r.addStretch(0)
            bv.addLayout(r)
        self.lbl_now = hint_label("")
        bv.addWidget(self.lbl_now)
        self._meters = QTimer(self)
        self._meters.setInterval(METER_MS)
        self._meters.timeout.connect(self._tick)

        # ---- hear the difference
        bv.addWidget(section_label(_("Hear the difference")))
        tr = QHBoxLayout()
        tr.setSpacing(8)
        self.b_rec = QPushButton(_("Record 5 seconds"))
        icons.set_icon(self.b_rec, "mic", size=16)
        self.b_rec.setToolTip(_("Talk with your usual noise around, then hear it as it was "
                                "and cleaned."))
        self.b_rec.clicked.connect(self._record)
        tr.addWidget(self.b_rec)
        self.b_before = QPushButton(_("Before"))
        self.b_after = QPushButton(_("After"))
        for b, tip in ((self.b_before, _("Your mic as it was")),
                       (self.b_after, _("Your mic cleaned"))):
            icons.set_icon(b, "play", size=16)
            b.setToolTip(tip)
            b.setEnabled(False)
            tr.addWidget(b)
        self.b_before.clicked.connect(lambda: self._play(False))
        self.b_after.clicked.connect(lambda: self._play(True))
        tr.addStretch(1)
        bv.addLayout(tr)
        self.lbl_test = hint_label(_("Talk with your usual noise around, then play both."))
        bv.addWidget(self.lbl_test)
        v.addStretch(1)

        self._take = None           # the test's blocks while it records
        self._rec_timer = QTimer(self)
        self._rec_timer.setSingleShot(True)
        self._rec_timer.timeout.connect(self._stop_record)
        self._count = QTimer(self)
        self._count.setInterval(1000)
        self._count.timeout.connect(self._count_down)
        self._left = 0
        self._test: tuple[np.ndarray, np.ndarray, int] | None = None   # raw, cleaned, rate
        self._cleaned.connect(self._test_ready)

        self.b_on.toggled.connect(self._toggle)
        self.b_on.setEnabled(self.ok)
        self.b_on.blockSignals(True)
        self.b_on.setChecked(self.s["on"])
        self.b_on.blockSignals(False)
        self._show()
        if self.s["on"]:
            self.chain.set_clean(True, self.s["strength"])

    # ------------------------------------------------------------ on / off, strength
    def is_on(self) -> bool:
        return self.b_on.isChecked()

    def set_on(self, on: bool):
        """Switched from elsewhere (the status bar's chip): as if the switch was flipped."""
        if self.ok and on != self.is_on():
            self.b_on.setChecked(on)

    def _toggle(self, on: bool):
        self.s["on"] = on
        self.chain.set_clean(on, self.s["strength"])
        if on:
            usage.used("clean-mic")   # switched on (never how strong)
        self._show()
        self.changed.emit(dict(self.s))
        self.live_changed.emit(on)

    def _pick(self, key: str):
        if key == "strong" and not deepfilter.downloaded():
            self._offer()   # it stays as it was until the download is here
            return
        self.get_box.setVisible(self._getting)
        if key == self.s["strength"]:
            self._show()
            return
        self.lbl_fallback.hide()
        self.s["strength"] = key
        if self.is_on():
            self.chain.set_clean(True, key)
        self._show()
        self.changed.emit(dict(self.s))
        if self._test is not None:   # the After of the test, at the new strength
            self._clean_test(self._test[0], self._test[2])

    def _show(self):
        on = self.is_on()
        self.b_on.setText(_("On") if on else _("Off"))
        self.b_strength[self.s["strength"]].setChecked(True)
        self.lbl_strength.setText(strength_words(self.s["strength"]))
        self.b_drop.setVisible(self.s["strength"] == "strong")
        self._show_error()

    # ------------------------------------------------------------ Strong's download
    def _offer(self, error: str = ""):
        """Strong picked, not downloaded: what it needs, and a Download button."""
        self.b_strength[self.s["strength"]].setChecked(True)
        self.get_box.show()
        if self._getting:
            return
        if error:
            self.lbl_get.setText(_("Couldn't download Strong: {error}", error=error))
        else:
            self.lbl_get.setText(_("Strong needs a one-time download of {size} MB "
                                   "(DeepFilterNet).", size=MB))
        theme.set_tone(self.lbl_get, "error" if error else "")
        self.b_get.setText(_("Try again") if error else _("Download ({size} MB)", size=MB))

    def _download(self):
        if self._getting:
            return
        self._getting, self._stop_get = True, False
        self.b_get.hide()
        self.b_cancel.setEnabled(True)
        self.b_cancel.show()
        self.get_bar.setValue(0)
        self.get_bar.show()
        theme.set_tone(self.lbl_get, "")
        self.lbl_get.setText(_("Downloading Strong…"))

        def work():
            try:
                deepfilter.download(lambda done, total: self._got.emit(done, total),
                                    lambda: self._stop_get)
                why = ""
            except Exception as ex:  # noqa: BLE001 - said on the card
                why = "-" if self._stop_get else deepfilter.friendly(ex)
            self._got_done.emit(why)
        threading.Thread(target=work, daemon=True, name="clean-mic-strong-get").start()

    def _cancel_download(self):
        self._stop_get = True
        self.b_cancel.setEnabled(False)

    def _on_got(self, done: int, total: int):
        if not self._getting:
            return
        total = total or deepfilter.SIZE
        self.get_bar.setValue(min(1000, done * 1000 // max(1, total)))
        self.lbl_get.setText(_("Downloading Strong: {percent}% of {size} MB",
                               percent=min(100, done * 100 // max(1, total)), size=MB))

    def _on_got_done(self, why: str):
        self._getting = False
        self.get_bar.hide()
        self.b_cancel.hide()
        self.b_get.show()
        if not why:
            self.get_box.hide()
            self._pick("strong")
        else:
            self._offer("" if why == "-" else why)

    def _remove_download(self):
        if self.s["strength"] == "strong":
            self._pick("normal")
        try:
            deepfilter.remove()
        except OSError as ex:
            self._fallback(_("Couldn't remove Strong's download: {error}",
                             error=errors.plain(ex)))
        self._show()

    def _fallback(self, text: str):
        self.lbl_fallback.setText(text)
        self.lbl_fallback.show()

    def _cleaning(self) -> bool:
        """On and working: what others hear is the cleaned mic (after an error it's the
        mic as it is, until it's switched again)."""
        return self.is_on() and not self.chain.clean_error

    def _show_error(self):
        why = self.chain.clean_error if self.is_on() else ""
        text = _("Clean mic stopped after an error: {error}", error=why) if why else ""
        if text != self.lbl_error.text():
            self.lbl_error.setText(text)
        self.lbl_error.setVisible(bool(text))
        now = (_("On: what others hear from your mic is the cleaned one.") if self._cleaning()
               else _("Off: others hear your mic as it is, noise and all."))
        if now != self.lbl_now.text():
            self.lbl_now.setText(now)

    # ------------------------------------------------------------ meters
    def showEvent(self, e):
        super().showEvent(e)
        self._meters.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._meters.stop()

    def _tick(self):
        note = getattr(self.chain.cleaner, "note", "")
        if note and self.s["strength"] == "strong" and self.is_on():
            self._pick("normal")   # it has stopped: say so, and show what's cleaning
            self._fallback(_("Strong couldn't run ({error}), so Normal is cleaning "
                             "instead.", error=note))
        mic = float(getattr(self.engine, "level_mic", 0.0) or 0.0)
        self.m_mic.set_level(mic)
        self.m_clean.set_level(self.chain.clean_level() if self._cleaning() else mic)
        self._show_error()

    # ------------------------------------------------------------ hear the difference
    def _record(self):
        if self._take is not None:   # Stop, early
            self._stop_record()
            return
        eng = self.engine
        if getattr(eng, "mic_stream", None) is None:
            self._say(_("No mic is open. Pick one in Settings → Audio."), "error")
            return
        if getattr(eng, "taking", False):
            self._say(_("A recording is already running: finish it first."), "error")
            return
        self._take = eng.start_mic_take(processed=False)
        self._left = TEST_S
        self.b_rec.setText(_("Stop ({seconds})", seconds=self._left))
        icons.set_icon(self.b_rec, "live_off", size=16)
        self._say(_("Recording: talk as you usually do."))
        self._rec_timer.start(TEST_S * 1000)
        self._count.start()

    def _count_down(self):
        self._left = max(0, self._left - 1)
        if self._take is not None:
            self.b_rec.setText(_("Stop ({seconds})", seconds=self._left))

    def _stop_record(self):
        self._rec_timer.stop()
        self._count.stop()
        if self._take is None:
            return
        self._take = None
        blocks = self.engine.stop_mic_take()
        self.b_rec.setText(_("Record again"))
        icons.set_icon(self.b_rec, "mic", size=16)
        rate = int(self.engine.rates.get("mic") or 48000)
        raw = (np.concatenate([b[:, 0] for b in blocks]).astype(np.float32)
               if blocks else np.zeros(0, np.float32))
        if len(raw) < rate // 2:
            self._say(_("Nothing came from your mic. Is it muted?"), "error")
            return
        self._say(_("Cleaning it…"))
        self._clean_test(raw, rate)

    def _clean_test(self, raw: np.ndarray, rate: int):
        strength = self.s["strength"]

        def work():
            try:
                out = cleanmic.clean_clip(raw, rate, strength)
            except Exception:  # noqa: BLE001 - said in the card
                out = None
            self._cleaned.emit((raw, rate), out)
        threading.Thread(target=work, daemon=True, name="clean-mic-test").start()

    def _test_ready(self, rec, out):
        raw, rate = rec
        if out is None:
            self._say(_("Your recording couldn't be cleaned."), "error")
            return
        self._test = (raw, out, rate)
        self.b_before.setEnabled(True)
        self.b_after.setEnabled(True)
        self._say(_("Only you hear these, in your headphones."))

    def _play(self, cleaned: bool):
        if self._test is None:
            return
        raw, out, rate = self._test
        usage.used("clean-mic-test")
        clip = out if cleaned else raw
        if self.engine.play(PLAY_ID, clip, 1.0, preview=True, src_rate=rate) is None:
            self._say(_("Pick your headphones in Settings → Audio to hear it."), "error")

    def _say(self, text: str, tone: str = ""):
        self.lbl_test.setText(text)
        theme.set_tone(self.lbl_test, tone)

    def shutdown(self):
        self._stop_get = True
        self._meters.stop()
        if self._take is not None:
            self._take = None
            self.engine.stop_mic_take()
