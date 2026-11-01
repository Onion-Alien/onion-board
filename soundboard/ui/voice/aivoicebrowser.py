"""The AI voices card's Hear it samples and its "Make your own voice" editor.

Hear it plays a short sample in your headphones (soundboard.speech.aipreview). Your
own voices (soundboard.speech.aivoicelist.Store) are blends of the others; the card
(ui/voice/aivoicepanel.py) lists them with the rest, to change, delete or make another.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget)

from soundboard.core import errors
from soundboard.i18n import _
from soundboard.sounds import thumbs
from soundboard.speech import aipreview
from soundboard.speech import aivoicelist as avl
from soundboard.ui.kit import busy, fit, icons, toast
from soundboard.ui.kit.panel import hint_label
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.voice import art

log = logging.getLogger(__name__)

HEAR, MAKING = _("Hear it"), _("Making a sample…")
PIC = 56              # the editor's picture
PIC_SAVED = 256       # the picture as kept (a square PNG; cards show it at most 128 px)
DEFAULT_ART = "voice-custom"   # your voices' picture until you pick one (My own mix's)


def default_pixmap(size: int) -> QPixmap:
    return art.pixmap(DEFAULT_ART, size) or QPixmap()


def mine_icon(voice: dict) -> QIcon | None:
    """One of your voices' card picture: the one you picked, else My own mix's."""
    return art.file_icon(avl.picture_path(str(voice.get("id", "")))) or art.icon(DEFAULT_ART)


def mine_pixmap(voice: dict, size: int) -> QPixmap:
    return art.file_pixmap(avl.picture_path(str(voice.get("id", ""))), size) or \
        default_pixmap(size)


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
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work
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
        self.emoji = str((voice or {}).get("emoji", "") or "")   # older voices' (kept)
        pic = avl.picture_path(self.vid)
        self.picture: QImage | None = QImage(str(pic)) if voice and pic.is_file() else None
        if self.picture is not None and self.picture.isNull():
            self.picture = None
        self._picture_changed = False
        self.setMaximumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)
        title = QLabel(self.windowTitle())
        title.setObjectName("helptitle")   # the dialog Title role (DESIGN.md)
        lay.addWidget(title)
        lay.addWidget(hint_label(_("Start from a voice, mix a bit of another one in, then "
                                   "set how deep and how high it is. Press Hear it to try "
                                   "it.")))
        lay.addSpacing(4)
        # one grid: names on the left, the controls in one column, the sliders' values
        # in a column of their own so every slider ends at the same place
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(12)
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        r = 0
        g.addWidget(QLabel(_("Name")), r, 0)
        self.ed_name = QLineEdit((voice or {}).get("name", ""))
        self.ed_name.setMaxLength(avl.MAX_NAME)
        self.ed_name.setPlaceholderText(_("My voice"))
        g.addWidget(self.ed_name, r, 1, 1, 2)
        r += 1
        g.addWidget(QLabel(_("About it")), r, 0)
        self.ed_about = QLineEdit((voice or {}).get("about", ""))
        self.ed_about.setMaxLength(avl.MAX_TEXT)
        self.ed_about.setPlaceholderText(_("What it sounds like, for the list (optional)"))
        g.addWidget(self.ed_about, r, 1, 1, 2)
        r += 1
        g.addWidget(QLabel(_("Picture")), r, 0)
        pic_row = QHBoxLayout()
        pic_row.setSpacing(8)
        self.pic_view = QLabel()
        self.pic_view.setFixedSize(PIC, PIC)
        pic_row.addWidget(self.pic_view)
        pic_row.addSpacing(4)
        self.b_pic = QPushButton(_("Pick a picture"))
        icons.set_icon(self.b_pic, "image")
        self.b_pic.clicked.connect(self._pick_picture)
        pic_row.addWidget(self.b_pic)
        self.b_pic_clear = QPushButton(_("Remove"))
        self.b_pic_clear.setProperty("quiet", True)
        self.b_pic_clear.clicked.connect(lambda: self._set_picture(None))
        pic_row.addWidget(self.b_pic_clear)
        pic_row.addStretch(1)
        g.addLayout(pic_row, r, 1, 1, 2)
        r += 1
        g.setRowMinimumHeight(r, 4)                 # a little gap before the sound
        r += 1
        g.addWidget(QLabel(_("Start from")), r, 0)
        self.cb_base = QComboBox()
        for v in built_in:
            self.cb_base.addItem(f"{v.get('emoji', '')} {v['name']}".strip(), v["id"])
        self.cb_base.setCurrentIndex(max(0, self.cb_base.findData(recipe.get("base", ""))))
        g.addWidget(self.cb_base, r, 1, 1, 2, left)
        r += 1
        g.addWidget(QLabel(_("Mix in")), r, 0)
        mrow = QHBoxLayout()
        mrow.setSpacing(12)
        self.cb_other = QComboBox()
        self.cb_other.addItem(_("Nothing"), "")
        for v in built_in:
            self.cb_other.addItem(f"{v.get('emoji', '')} {v['name']}".strip(), v["id"])
        self.cb_other.setCurrentIndex(max(0, self.cb_other.findData(recipe.get("other", ""))))
        mrow.addWidget(self.cb_other)
        self.sl_amount = QSlider(Qt.Orientation.Horizontal)
        self.sl_amount.setRange(0, 50)
        self.sl_amount.setValue(int(round(float(recipe.get("amount", 0.3)) * 100)))
        self.sl_amount.setToolTip(_("How much of it: up to half"))
        mrow.addWidget(self.sl_amount, 1)
        mrow.addStretch(0)
        g.addLayout(mrow, r, 1)
        # both lists of voices the same width, one above the other
        w = max(self.cb_base.sizeHint().width(), self.cb_other.sizeHint().width())
        self.cb_base.setFixedWidth(min(w, 360))
        self.cb_other.setFixedWidth(min(w, 360))
        self.lbl_amount = QLabel("")
        g.addWidget(self.lbl_amount, r, 2)
        r += 1
        g.addWidget(QLabel(_("Deeper / brighter")), r, 0)
        self.sl_formant = QSlider(Qt.Orientation.Horizontal)
        self.sl_formant.setRange(-4, 4)            # half semitones
        self.sl_formant.setToolTip(_("Left: a bigger, deeper-sounding person. Right: a "
                                     "smaller, brighter one. Doesn't change how high."))
        g.addWidget(self.sl_formant, r, 1)
        self.lbl_formant = QLabel("")
        g.addWidget(self.lbl_formant, r, 2)
        r += 1
        g.addWidget(QLabel(_("How high")), r, 0)
        self.sl_pitch = QSlider(Qt.Orientation.Horizontal)
        self.sl_pitch.setRange(avl.PITCH_HZ[0], avl.PITCH_HZ[1])
        self.sl_pitch.setToolTip(_("Where your voice is moved to while Match the voice is on"))
        g.addWidget(self.sl_pitch, r, 1)
        self.lbl_pitch = QLabel("")
        g.addWidget(self.lbl_pitch, r, 2)
        g.setColumnStretch(1, 1)
        # the values' column as wide as its longest word: nothing moves as they change
        fm = self.lbl_pitch.fontMetrics()
        words = [_("{percent}%", percent=50), _("as it is"),
                 _("deeper {amount}", amount="1.5"), _("brighter {amount}", amount="1.5")]
        words += [avl.pitch_word(top - 1) for top, _w in avl.PITCH_WORDS[:-1]]
        words.append(avl.pitch_word(avl.PITCH_HZ[1]))
        g.setColumnMinimumWidth(2, max(fm.horizontalAdvance(w) for w in words) + 4)
        lay.addLayout(g)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        self.status.hide()
        lay.addWidget(self.status)
        lay.addSpacing(4)
        # the footer: Hear it on the left (it tries what's above), then Save and Cancel
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.b_hear = hear_button()
        self.b_hear.setVisible(previewer.available())
        self.b_hear.clicked.connect(lambda: self.previewer.hear(
            self.b_hear, self.result_voice(), self._sampled, self._say))
        foot.addWidget(self.b_hear)
        foot.addStretch(1)
        self.b_save = QPushButton(_("Save"))
        self.b_save.setObjectName("primary")
        self.b_save.setDefault(True)
        self.b_save.clicked.connect(self.accept)
        foot.addWidget(self.b_save)
        b_cancel = QPushButton(_("Cancel"))
        b_cancel.clicked.connect(self.reject)
        foot.addWidget(b_cancel)
        lay.addLayout(foot)
        self._show_picture()
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
        self.resize(540, self.sizeHint().height())

    def _say(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    # ------------------------------------------------------------------ picture
    def _show_picture(self):
        """The card picture as it will be after Save; Remove only with one of yours."""
        pm = art.rounded(self.picture, PIC) if self.picture is not None else \
            default_pixmap(PIC)
        self.pic_view.setPixmap(pm)
        self.b_pic_clear.setVisible(self.picture is not None)

    def _set_picture(self, img: QImage | None):
        self.picture = img
        self._picture_changed = True
        self._show_picture()

    def _pick_picture(self):
        f, __ = QFileDialog.getOpenFileName(
            self, _("Pick a picture"), str(Path.home()),
            _("Pictures ({patterns})",
              patterns=" ".join(f"*{x}" for x in sorted(thumbs.IMAGE_EXTS))))
        if not f:
            return
        img = QImage(f)
        if img.isNull():
            busy.toast(self, toast.titled(_("Couldn't use that picture"), _(
                "{name} isn't a picture this app can read.", name=Path(f).name)), "warn")
            return
        self._set_picture(img)

    def save_picture(self):
        """Write (or remove) the picture: Save calls it, never Cancel."""
        if not self._picture_changed:
            return
        path = avl.picture_path(self.vid)
        try:
            if self.picture is None:
                path.unlink(missing_ok=True)
                return
            img = self.picture
            side = min(img.width(), img.height())
            sq = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
            sq = sq.scaled(PIC_SAVED, PIC_SAVED, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not sq.save(str(path)):           # a PNG: from the name
                raise OSError(f"couldn't write {path}")
        except OSError:
            log.warning("couldn't save the voice's picture", exc_info=True)

    def accept(self):
        self.save_picture()
        super().accept()

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
        self.sl_amount.setVisible(other)      # mixing in nothing: no how-much slider
        self.lbl_amount.setText(_("{percent}%", percent=self.sl_amount.value()) if other
                                else "")
        f = self.sl_formant.value() / 2
        self.lbl_formant.setText(_("as it is") if f == 0 else
                                 _("deeper {amount}", amount=f"{abs(f):g}") if f < 0 else
                                 _("brighter {amount}", amount=f"{abs(f):g}"))
        self.lbl_pitch.setText(avl.pitch_word(self.sl_pitch.value()))
        self._say("")

    def showEvent(self, ev):
        super().showEvent(ev)
        self.ed_name.setFocus()

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
                "emoji": self.emoji,
                "description": about or made, "about": about, "tags": tags,
                "mix": avl.blend(base, other, amount), "formant": self.sl_formant.value() / 2,
                "pitch_hz": self.sl_pitch.value(),
                "recipe": {"base": base.get("id", ""), "other": (other or {}).get("id", ""),
                           "amount": amount}}
