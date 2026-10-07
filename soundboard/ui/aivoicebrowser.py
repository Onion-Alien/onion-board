"""The AI voices card's "All voices" window and the "Make your own voice" editor.

Every voice as a card: who it sounds like, how high it sits, a few lines about it,
Hear it (a short sample in your headphones, soundboard.speech.aipreview) and Use.
Your own voices (soundboard.speech.aivoicelist.Store) are blends of the others:
edit, delete (Undo, then Recently deleted), or make another.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSlider, QVBoxLayout, QWidget)

from soundboard import errors
from soundboard.speech import aipreview
from soundboard.speech import aivoicelist as avl
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import UndoBar, hint_label
from soundboard.wheelguard import no_wheel

HEAR, MAKING = "Hear it", "Making a sample…"


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
        if data is not None:
            self.play(data)
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
        if data is not None:
            self.play(data)
        elif err:
            on_error(f"⚠ Couldn't play a sample: {err}")


def _hear_button() -> QPushButton:
    b = QPushButton(HEAR)
    icons.set_icon(b, "headphones")
    b.setToolTip("A short sample in this voice, in your headphones only (nobody else "
                 "hears it). The first one takes a few seconds.")
    return b


class VoiceCard(QFrame):
    def __init__(self, voice: dict, current: bool, can_hear: bool):
        super().__init__()
        self.voice = voice
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        emoji = QLabel(voice.get("emoji") or "🎙️")
        emoji.setStyleSheet("font-size: 22pt; background: transparent;")
        top.addWidget(emoji, 0, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name = QLabel(voice["name"])
        self.name.setTextFormat(Qt.PlainText)
        self.name.setStyleSheet("font-weight: 600; font-size: 11pt; background: transparent;")
        names.addWidget(self.name)
        self.tags = QLabel(avl.tag_line(voice))
        self.tags.setObjectName("muted")
        self.tags.setTextFormat(Qt.PlainText)
        names.addWidget(self.tags)
        top.addLayout(names, 1)
        v.addLayout(top)
        self.about = hint_label(voice.get("about") or voice.get("description") or "")
        self.about.setTextFormat(Qt.PlainText)
        v.addWidget(self.about, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.b_use = QPushButton("In use" if current else "Use this voice")
        self.b_use.setEnabled(not current)
        if not current:
            self.b_use.setObjectName("primary")
        row.addWidget(self.b_use)
        self.b_hear = _hear_button()
        self.b_hear.setVisible(can_hear)
        row.addWidget(self.b_hear)
        row.addStretch(1)
        self.b_edit = self.b_delete = None
        if avl.is_mine(voice):
            self.b_edit = QPushButton()
            icons.set_icon(self.b_edit, "edit")
            self.b_edit.setToolTip("Change this voice")
            row.addWidget(self.b_edit)
            self.b_delete = QPushButton()
            icons.set_icon(self.b_delete, "trash", "danger_text")
            self.b_delete.setToolTip("Delete this voice (you can bring it back)")
            row.addWidget(self.b_delete)
        v.addLayout(row)


class AiVoiceBrowser(QDialog):
    """`voices`: what the add-on has now (built-in and yours). Emits `picked(id)` for
    Use, `edited()` when your own voices changed (the card re-syncs the add-on)."""
    picked = Signal(str)
    edited = Signal()
    _sampled = Signal(object, object, str)

    def __init__(self, voices: list[dict], current: str, store: avl.Store,
                 previewer: Previewer, can_make: bool, parent=None,
                 refresh: Callable[[], list[dict]] | None = None):
        super().__init__(parent)
        fit.watch(self)
        self.setWindowTitle("AI voices")
        self.voices, self.current, self.store = voices, current, store
        self.previewer, self.can_make = previewer, can_make
        self.refresh_voices = refresh
        self._sampled.connect(lambda b, d, e: self.previewer.done(b, d, e, self._say))
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(hint_label(
            "Every voice, who it sounds like and how high it sits. Hear it plays a short "
            "sample in your headphones only. Make your own by blending them."))
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.status.hide()
        lay.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setMinimumSize(680, 420)
        lay.addWidget(self.scroll, 1)
        self.undo_bar = UndoBar("Bring the voice back")
        lay.addWidget(self.undo_bar)
        row = QHBoxLayout()
        self.b_make = QPushButton("Make your own voice")
        icons.set_icon(self.b_make, "plus")
        self.b_make.setEnabled(can_make)
        self.b_make.setToolTip(
            "Blend two voices and set how deep and how high it is" if can_make else
            "Only for AI voices installed with the Get AI voices button")
        self.b_make.clicked.connect(lambda: self.edit(None))
        row.addWidget(self.b_make)
        self.b_bin = QPushButton("")
        self.b_bin.setObjectName("fold")
        icons.set_icon(self.b_bin, "trash", "muted", "text", size=12)
        self.b_bin.clicked.connect(self.show_deleted)
        row.addWidget(self.b_bin)
        row.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        row.addWidget(box)
        lay.addLayout(row)
        self.fill()

    def _say(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def fill(self):
        self.cards: list[VoiceCard] = []
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setSpacing(10)
        can_hear = self.previewer.available()
        for i, vo in enumerate(self.voices):
            c = VoiceCard(vo, vo["id"] == self.current, can_hear)
            c.b_use.clicked.connect(lambda _=False, vid=vo["id"]: self.use(vid))
            c.b_hear.clicked.connect(lambda _=False, c=c: self.previewer.hear(
                c.b_hear, c.voice, self._sampled, self._say))
            if c.b_edit is not None:
                c.b_edit.clicked.connect(lambda _=False, vid=vo["id"]: self.edit(vid))
                c.b_delete.clicked.connect(lambda _=False, vid=vo["id"]: self.delete(vid))
            grid.addWidget(c, i // 2, i % 2)
            self.cards.append(c)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(self.voices) // 2 + 1, 1)
        self.scroll.setWidget(body)
        n = len(self.store.deleted)
        self.b_bin.setText(f"Recently deleted ({n})")
        self.b_bin.setVisible(n > 0)

    def card(self, vid: str) -> VoiceCard | None:
        return next((c for c in self.cards if c.voice["id"] == vid), None)

    def use(self, vid: str):
        self.current = vid
        self.picked.emit(vid)
        for c in self.cards:
            on = c.voice["id"] == vid
            c.b_use.setText("In use" if on else "Use this voice")
            c.b_use.setEnabled(not on)

    def _changed(self):
        self.edited.emit()
        if self.refresh_voices is not None:
            self.voices = self.refresh_voices()
        self.fill()

    # ------------------------------------------------------------ your own voices
    def edit(self, vid: str | None):
        if vid is None and self.store.full():
            self._say(f"⚠ You have {avl.MAX_VOICES} voices of your own already: "
                      "delete one to make another.")
            return
        built = [v for v in self.voices if not avl.is_mine(v)]
        d = AiVoiceEditor(built, self.store.get(vid) if vid else None, self.previewer, self)
        if d.exec() == QDialog.Accepted and self.store.put(d.result_voice()) is not None:
            self._changed()
            if vid is None:
                self.use(d.result_voice()["id"])

    def delete(self, vid: str):
        item = self.store.remove(vid)
        if item is None:
            return
        self._changed()
        self.undo_bar.show_for(f"Deleted “{item.name}”", lambda: self._undo(item.id))

    def _undo(self, item_id: str):
        it = self.store.take(item_id)
        if it is not None and self.store.restore(it) is not None:
            self._changed()

    def show_deleted(self):
        from soundboard.ui.deleted import DeletedDialog
        self.undo_bar.finish()

        def back(item) -> bool:
            return self.store.restore(item) is not None
        DeletedDialog(avl.KIND, "voices", back, self, source=self.store).exec()
        self._changed()


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
        self.setWindowTitle("Change your voice" if voice else "Make your own voice")
        self._sampled.connect(lambda b, d, e: self.previewer.done(b, d, e, self._say))
        recipe = (voice or {}).get("recipe") or {}
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(hint_label("Start from a voice, mix a bit of another one in, then set "
                                 "how deep and how high it is. Press Hear it to try it."))
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        r = 0
        g.addWidget(QLabel("Name"), r, 0)
        nrow = QHBoxLayout()
        self.ed_emoji = QLineEdit((voice or {}).get("emoji", "") or "🎙️")
        self.ed_emoji.setMaxLength(4)
        self.ed_emoji.setFixedWidth(52)
        self.ed_emoji.setToolTip("An emoji for it (Windows key + . opens the emoji list)")
        nrow.addWidget(self.ed_emoji)
        self.ed_name = QLineEdit((voice or {}).get("name", ""))
        self.ed_name.setMaxLength(avl.MAX_NAME)
        self.ed_name.setPlaceholderText("My voice")
        nrow.addWidget(self.ed_name, 1)
        g.addLayout(nrow, r, 1)
        r += 1
        g.addWidget(QLabel("About it"), r, 0)
        self.ed_about = QLineEdit((voice or {}).get("about", ""))
        self.ed_about.setMaxLength(avl.MAX_TEXT)
        self.ed_about.setPlaceholderText("What it sounds like, for the list (optional)")
        g.addWidget(self.ed_about, r, 1)
        r += 1
        g.addWidget(QLabel("Start from"), r, 0)
        self.cb_base = QComboBox()
        for v in built_in:
            self.cb_base.addItem(f"{v.get('emoji', '')} {v['name']}".strip(), v["id"])
        self.cb_base.setCurrentIndex(max(0, self.cb_base.findData(recipe.get("base", ""))))
        g.addWidget(self.cb_base, r, 1)
        r += 1
        g.addWidget(QLabel("Mix in"), r, 0)
        mrow = QHBoxLayout()
        mrow.setSpacing(12)
        self.cb_other = QComboBox()
        self.cb_other.addItem("Nothing", "")
        for v in built_in:
            self.cb_other.addItem(f"{v.get('emoji', '')} {v['name']}".strip(), v["id"])
        self.cb_other.setCurrentIndex(max(0, self.cb_other.findData(recipe.get("other", ""))))
        mrow.addWidget(self.cb_other, 1)
        self.sl_amount = QSlider(Qt.Horizontal)
        self.sl_amount.setRange(0, 50)
        self.sl_amount.setValue(int(round(float(recipe.get("amount", 0.3)) * 100)))
        self.sl_amount.setToolTip("How much of it: up to half")
        mrow.addWidget(self.sl_amount, 1)
        self.lbl_amount = QLabel("")
        self.lbl_amount.setMinimumWidth(40)
        mrow.addWidget(self.lbl_amount)
        g.addLayout(mrow, r, 1)
        r += 1
        g.addWidget(QLabel("Deeper / brighter"), r, 0)
        frow = QHBoxLayout()
        frow.setSpacing(12)
        self.sl_formant = QSlider(Qt.Horizontal)
        self.sl_formant.setRange(-4, 4)            # half semitones
        self.sl_formant.setToolTip("Left: a bigger, deeper-sounding person. Right: a "
                                   "smaller, brighter one. Doesn't change how high.")
        frow.addWidget(self.sl_formant, 1)
        self.lbl_formant = QLabel("")
        self.lbl_formant.setMinimumWidth(100)
        frow.addWidget(self.lbl_formant)
        g.addLayout(frow, r, 1)
        r += 1
        g.addWidget(QLabel("How high"), r, 0)
        prow = QHBoxLayout()
        prow.setSpacing(12)
        self.sl_pitch = QSlider(Qt.Horizontal)
        self.sl_pitch.setRange(avl.PITCH_HZ[0], avl.PITCH_HZ[1])
        self.sl_pitch.setToolTip("Where your voice is moved to while Match the voice is on")
        prow.addWidget(self.sl_pitch, 1)
        self.lbl_pitch = QLabel("")
        self.lbl_pitch.setMinimumWidth(100)
        prow.addWidget(self.lbl_pitch)
        g.addLayout(prow, r, 1)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        hrow = QHBoxLayout()
        self.b_hear = _hear_button()
        self.b_hear.setVisible(previewer.available())
        self.b_hear.clicked.connect(lambda: self.previewer.hear(
            self.b_hear, self.result_voice(), self._sampled, self._say))
        hrow.addWidget(self.b_hear)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        hrow.addWidget(self.status, 1)
        lay.addLayout(hrow)
        self.box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
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

    def _show(self, *_):
        other = self._other() is not None
        self.sl_amount.setEnabled(other)
        self.lbl_amount.setText(f"{self.sl_amount.value()} %" if other else "")
        f = self.sl_formant.value() / 2
        self.lbl_formant.setText("as it is" if f == 0 else
                                 f"{'deeper' if f < 0 else 'brighter'} {abs(f):g}")
        self.lbl_pitch.setText(avl.pitch_word(self.sl_pitch.value()))
        self.status.setText("")

    def result_voice(self) -> dict:
        base, other = self._base(), self._other()
        amount = self.sl_amount.value() / 100 if other else 0.0
        tags = [t for t in base.get("tags", []) if not other or t in other.get("tags", [])]
        about = " ".join(self.ed_about.text().split())
        made = f"{base['name']}" + (f" with {int(amount * 100)} % {other['name']}"
                                     if other and amount else "")
        return {"id": self.vid, "name": avl.clean_name(self.ed_name.text()) or "My voice",
                "emoji": self.ed_emoji.text().strip()[:4],
                "description": about or f"Made from {made}.", "about": about, "tags": tags,
                "mix": avl.blend(base, other, amount), "formant": self.sl_formant.value() / 2,
                "pitch_hz": self.sl_pitch.value(),
                "recipe": {"base": base.get("id", ""), "other": (other or {}).get("id", ""),
                           "amount": amount}}
