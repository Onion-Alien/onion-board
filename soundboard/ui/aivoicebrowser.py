"""The AI voices card's Hear it samples and its "Make your own voice" editor.

Hear it plays a short sample in your headphones (soundboard.speech.aipreview). Your
own voices (soundboard.speech.aivoicelist.Store) are blends of the others; the card
(ui/aivoicepanel.py) lists them with the rest, to change, delete or make another.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget)

from soundboard import errors
from soundboard.i18n import _
from soundboard.speech import aipreview
from soundboard.speech import aivoicelist as avl
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import hint_label, steady_number
from soundboard.wheelguard import no_wheel

HEAR, MAKING = _("Hear it"), _("Making a sample…")


class Previewer:
    """Hear it buttons: one sample at a time, made off the UI thread, then played.
    `module()` gives the add-on (None: no samples), `play(data)` plays a sample."""

    def __init__(self, owner: QWidget, module: Callable, play: Callable | None):
        self.owner, self.module, self.play = owner, module, play
        self.busy = False

    def available(self) -> bool:
        return self.play is not None and self.module() is not None

    def hear(self, btn: QPushButton, voice: dict, done_sig, on_error: Callable[[str], None]):
        if self.busy or not self.available():
            return
        data = aipreview.cached(voice)
        play = self.play
        assert play is not None   # available() checked
        if data is not None:
            play(data)
            return
        self.busy = True
        btn.setText(MAKING)
        module = self.module()

        def work():
            try:
                busy.emit(done_sig, btn, aipreview.make(module, voice), "")
            except aipreview.PreviewError as e:
                busy.emit(done_sig, btn, None, str(e))
            except Exception as e:  # noqa: BLE001 - the button must come back
                busy.emit(done_sig, btn, None, errors.plain(e))
        threading.Thread(target=work, name="ai-voice-sample", daemon=True).start()

    def done(self, btn: QPushButton, data, err: str, on_error: Callable[[str], None]):
        self.busy = False
        try:
            btn.setText(HEAR)
        except RuntimeError:          # its card was rebuilt meanwhile
            pass
        if data is not None and self.play is not None:   # (hear() checked it)
            self.play(data)
        elif err:
            on_error(_("⚠ Couldn't play a sample: {error}", error=err))


def hear_button() -> QPushButton:
    b = QPushButton(HEAR)
    icons.set_icon(b, "headphones")
    b.setToolTip(_("A short sample in this voice, in your headphones only (nobody else "
                   "hears it). The first one takes a few seconds."))
    return b


class AiVoiceEditor(QDialog):
    """Make or change one of your own voices: start from a voice, mix in another,
    deeper or brighter, how high. `voice`: the one to change (None: a new one)."""
    _sampled = Signal(object, object, str)

    def __init__(self, built_in: list[dict], voice: dict | None, previewer: Previewer,
                 parent=None):
        super().__init__(parent)
        fit.watch(self)
        self.built = built_in
        self.previewer = previewer
        self.vid = voice["id"] if voice else avl.new_id()
        self.setWindowTitle(_("Change your voice") if voice else _("Make your own voice"))
        self._sampled.connect(lambda b, d, e: self.previewer.done(b, d, e, self._say))
        recipe = (voice or {}).get("recipe") or {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)
        title = QLabel(self.windowTitle())
        title.setObjectName("helptitle")   # the dialog Title role (DESIGN.md)
        lay.addWidget(title)
        lay.addWidget(hint_label(_("Start from a voice, mix a bit of another one in, then "
                                   "set how deep and how high it is. Press Hear it to try "
                                   "it.")))
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        r = 0
        g.addWidget(QLabel(_("Name")), r, 0)
        nrow = QHBoxLayout()
        self.ed_emoji = QLineEdit((voice or {}).get("emoji", "") or "🎙️")
        self.ed_emoji.setMaxLength(4)
        self.ed_emoji.setFixedWidth(52)
        self.ed_emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        big = self.ed_emoji.font()
        big.setPointSizeF(big.pointSizeF() * 1.3)
        self.ed_emoji.setFont(big)
        self.ed_emoji.setToolTip(_("An emoji for it (Windows key + . opens the emoji list)"))
        nrow.addWidget(self.ed_emoji)
        self.ed_name = QLineEdit((voice or {}).get("name", ""))
        self.ed_name.setMaxLength(avl.MAX_NAME)
        self.ed_name.setPlaceholderText(_("My voice"))
        nrow.addWidget(self.ed_name, 1)
        g.addLayout(nrow, r, 1)
        r += 1
        g.addWidget(QLabel(_("About it")), r, 0)
        self.ed_about = QLineEdit((voice or {}).get("about", ""))
        self.ed_about.setMaxLength(avl.MAX_TEXT)
        self.ed_about.setPlaceholderText(_("What it sounds like, for the list (optional)"))
        g.addWidget(self.ed_about, r, 1)
        r += 1
        g.addWidget(QLabel(_("Start from")), r, 0)
        self.cb_base = QComboBox()
        for v in built_in:
            self.cb_base.addItem(f"{v.get('emoji', '')} {v['name']}".strip(), v["id"])
        self.cb_base.setCurrentIndex(max(0, self.cb_base.findData(recipe.get("base", ""))))
        g.addWidget(self.cb_base, r, 1)
        r += 1
        g.addWidget(QLabel(_("Mix in")), r, 0)
        mrow = QHBoxLayout()
        mrow.setSpacing(12)
        self.cb_other = QComboBox()
        self.cb_other.addItem(_("Nothing"), "")
        for v in built_in:
            self.cb_other.addItem(f"{v.get('emoji', '')} {v['name']}".strip(), v["id"])
        self.cb_other.setCurrentIndex(max(0, self.cb_other.findData(recipe.get("other", ""))))
        mrow.addWidget(self.cb_other, 1)
        self.sl_amount = QSlider(Qt.Orientation.Horizontal)
        self.sl_amount.setRange(0, 50)
        self.sl_amount.setValue(int(round(float(recipe.get("amount", 0.3)) * 100)))
        self.sl_amount.setToolTip(_("How much of it: up to half"))
        mrow.addWidget(self.sl_amount, 1)
        self.lbl_amount = steady_number(QLabel(""), "100%")
        mrow.addWidget(self.lbl_amount)
        g.addLayout(mrow, r, 1)
        r += 1
        g.addWidget(QLabel(_("Deeper / brighter")), r, 0)
        frow = QHBoxLayout()
        frow.setSpacing(12)
        self.sl_formant = QSlider(Qt.Orientation.Horizontal)
        self.sl_formant.setRange(-4, 4)            # half semitones
        self.sl_formant.setToolTip(_("Left: a bigger, deeper-sounding person. Right: a "
                                     "smaller, brighter one. Doesn't change how high."))
        frow.addWidget(self.sl_formant, 1)
        self.lbl_formant = QLabel("")
        self.lbl_formant.setMinimumWidth(100)
        frow.addWidget(self.lbl_formant)
        g.addLayout(frow, r, 1)
        r += 1
        g.addWidget(QLabel(_("How high")), r, 0)
        prow = QHBoxLayout()
        prow.setSpacing(12)
        self.sl_pitch = QSlider(Qt.Orientation.Horizontal)
        self.sl_pitch.setRange(avl.PITCH_HZ[0], avl.PITCH_HZ[1])
        self.sl_pitch.setToolTip(_("Where your voice is moved to while Match the voice is on"))
        prow.addWidget(self.sl_pitch, 1)
        self.lbl_pitch = QLabel("")
        self.lbl_pitch.setMinimumWidth(100)
        prow.addWidget(self.lbl_pitch)
        g.addLayout(prow, r, 1)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        hrow = QHBoxLayout()
        self.b_hear = hear_button()
        self.b_hear.setVisible(previewer.available())
        self.b_hear.clicked.connect(lambda: self.previewer.hear(
            self.b_hear, self.result_voice(), self._sampled, self._say))
        hrow.addWidget(self.b_hear)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        hrow.addWidget(self.status, 1)
        lay.addLayout(hrow)
        self.box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                    | QDialogButtonBox.StandardButton.Cancel)
        self.box.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        lay.addWidget(self.box)
        no_wheel(self.cb_base, self.cb_other, self.sl_amount, self.sl_formant, self.sl_pitch)
        base = self._base()
        self.sl_formant.setValue(int(round(float((voice or base).get("formant", 0)) * 2)))
        self.sl_pitch.setValue(int((voice or base).get("pitch_hz", 150)))
        self.cb_base.currentIndexChanged.connect(self._base_picked)
        self.cb_other.currentIndexChanged.connect(self._show)
        self.sl_amount.valueChanged.connect(self._show)
        self.sl_formant.valueChanged.connect(self._show)
        self.sl_pitch.valueChanged.connect(self._show)
        self._show()
        self.resize(520, self.sizeHint().height())

    def _say(self, text: str):
        self.status.setText(text)

    def _base(self) -> dict:
        vid = self.cb_base.currentData()
        return next((v for v in self.built if v["id"] == vid), self.built[0] if self.built
                    else {"mix": [], "formant": 0, "pitch_hz": 150})

    def _other(self) -> dict | None:
        vid = self.cb_other.currentData()
        return next((v for v in self.built if v["id"] == vid), None)

    def _base_picked(self, *_):
        b = self._base()            # its depth and height, as a starting point
        self.sl_formant.setValue(int(round(float(b.get("formant", 0)) * 2)))
        self.sl_pitch.setValue(int(b.get("pitch_hz", 150)))

    def _show(self, *__):
        other = self._other() is not None
        self.sl_amount.setEnabled(other)
        self.lbl_amount.setText(_("{percent}%", percent=self.sl_amount.value()) if other
                                else "")
        f = self.sl_formant.value() / 2
        self.lbl_formant.setText(_("as it is") if f == 0 else
                                 _("deeper {amount}", amount=f"{abs(f):g}") if f < 0 else
                                 _("brighter {amount}", amount=f"{abs(f):g}"))
        self.lbl_pitch.setText(avl.pitch_word(self.sl_pitch.value()))
        self.status.setText("")

    def showEvent(self, ev):
        super().showEvent(ev)
        self.ed_name.setFocus()   # the name first, not the small emoji box before it

    def result_voice(self) -> dict:
        base, other = self._base(), self._other()
        amount = self.sl_amount.value() / 100 if other else 0.0
        tags = [t for t in base.get("tags", []) if not other or t in other.get("tags", [])]
        about = " ".join(self.ed_about.text().split())
        # (the name and description are yours: written in the app's language)
        made = (_("Made from {voice} with {percent}% {other}.", voice=base["name"],
                  percent=int(amount * 100), other=other["name"]) if other and amount
                else _("Made from {voice}.", voice=base["name"]))
        return {"id": self.vid, "name": avl.clean_name(self.ed_name.text()) or _("My voice"),
                "emoji": self.ed_emoji.text().strip()[:4],
                "description": about or made, "about": about, "tags": tags,
                "mix": avl.blend(base, other, amount), "formant": self.sl_formant.value() / 2,
                "pitch_hz": self.sl_pitch.value(),
                "recipe": {"base": base.get("id", ""), "other": (other or {}).get("id", ""),
                           "amount": amount}}
