"""Add a voice server: pick the server (Kokoro, AllTalk, openedai-speech or another),
check its address, then Find voices lists what it has (customvoices.list_voices, or
the fixed names AllTalk and openedai-speech take) as ticks. Each ticked voice is saved
as a server voice of its own (one .json each, the same address), so each is a card on
AI voices. A server with no list (Other): its voice's name is typed instead."""
from __future__ import annotations

import threading
import urllib.parse

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from soundboard.core import errors, usage
from soundboard.i18n import _
from soundboard.speech import customvoices
from soundboard.ui.kit import busy, fit, modals, theme
from soundboard.ui.kit.modalframe import ModalFrame
from soundboard.ui.kit.panel import fold_button, hint_label
from soundboard.ui.voice.voiceservers import address

LIST_H = 220   # the ticks' list at its tallest (Kokoro has dozens): it scrolls past that
TICK_COLS = 3  # ticks a row (voice names are short: "af_bella")


class AddServerDialog(QDialog):
    """`saved`: the names of the server voices it wrote, once Add is pressed."""
    _found = Signal(int, object, str)   # find round, voice names (None: no list), error

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        fit.watch(modals.keep_open(self))   # a form: a click outside keeps it
        self.setWindowTitle(_("Add a voice server"))
        self.saved: list[str] = []
        self._round = 0
        self._found.connect(self._on_found)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = ModalFrame(_("Add a voice server"),
                                _("Pick your server, check its address, then find its "
                                  "voices."), close=False)   # (the window's own ✕)
        outer.addWidget(self.frame)
        v = self.frame.body
        v.setSpacing(12)
        # which server: its usual address and model filled in
        row = QHBoxLayout()
        row.setSpacing(8)
        self.kinds = QButtonGroup(self)
        self.kinds.setExclusive(True)
        self._kind: dict[QAbstractButton, tuple] = {}
        for preset in customvoices.PRESETS:
            b = QPushButton(preset[1] or _("Other"))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.kinds.addButton(b)
            self._kind[b] = preset
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        form = QFormLayout()
        form.setSpacing(10)
        arow = QHBoxLayout()
        arow.setSpacing(8)
        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("http://127.0.0.1:8880")
        arow.addWidget(self.ed_url, 1)
        self.b_find = QPushButton(_("Find voices"))
        self.b_find.clicked.connect(self._find)
        arow.addWidget(self.b_find)
        form.addRow(_("Address"), arow)
        v.addLayout(form)
        self.lbl = hint_label("")
        self.lbl.hide()
        v.addWidget(self.lbl)
        # what it found: a tick each (none ticked: you pick), in columns, scrolling
        self.voices = QScrollArea()
        self.voices.setWidgetResizable(True)
        self.voices.setFrameShape(QFrame.Shape.NoFrame)
        self.voices.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._ticks: list[QCheckBox] = []
        self.voices.hide()
        v.addWidget(self.voices)
        # no list there: the voice's name, typed
        self.ed_voice = QLineEdit()
        self.ed_voice.setPlaceholderText(_("the server's voice name, e.g. af_bella (optional)"))
        self.ed_voice.textChanged.connect(lambda _t: self._count())
        self.voice_row = QWidget()
        vf = QFormLayout(self.voice_row)
        vf.setContentsMargins(0, 0, 0, 0)
        vf.addRow(_("Voice"), self.ed_voice)
        self.voice_row.hide()
        v.addWidget(self.voice_row)
        # rarely needed: the model it's asked for, a key
        self.btn_opts = fold_button(_("More options"))
        v.addWidget(self.btn_opts, 0, Qt.AlignmentFlag.AlignLeft)
        self.opts = QWidget()
        of = QFormLayout(self.opts)
        of.setContentsMargins(0, 0, 0, 0)
        of.setSpacing(10)
        self.ed_model = QLineEdit()
        self.ed_model.setPlaceholderText(_("optional"))
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_key.setPlaceholderText(_("only if the server asks for one"))
        of.addRow(_("Model"), self.ed_model)
        of.addRow(_("API key"), self.ed_key)
        self.opts.hide()
        self.btn_opts.toggled.connect(self.opts.setVisible)
        v.addWidget(self.opts)
        self.err = hint_label("")
        theme.set_tone(self.err, "error")
        self.err.hide()
        v.addWidget(self.err)
        self.b_add = self.frame.add_button("", primary=True)
        self.b_add.setDefault(False)   # Enter in the address is Find voices, not Add
        self.b_add.clicked.connect(self._add)
        self.frame.add_button(_("Cancel")).clicked.connect(self.reject)
        self.kinds.buttonClicked.connect(self._pick_kind)
        self.ed_url.returnPressed.connect(self._find)
        self.setFixedWidth(560)
        first = self.kinds.buttons()[0]
        first.setChecked(True)
        self._pick_kind(first)

    # ------------------------------------------------------------ the server
    def preset(self) -> tuple:
        b = self.kinds.checkedButton()
        return self._kind[b] if b is not None else customvoices.PRESETS[-1]

    def _pick_kind(self, b: QAbstractButton):
        _key, _name, url, model, _voices = self._kind[b]
        self.ed_url.setText(url)
        self.ed_model.setText(model)
        self._round += 1        # an answer for the old server is dropped
        self.b_find.setText(_("Find voices"))
        self.b_find.setEnabled(True)
        self._show_found(None, "", asked=False)
        self.ed_url.setFocus()

    def _find(self):
        """Ask the server what it has (AllTalk / openedai-speech: their fixed names,
        once it answers), off the UI thread."""
        url = self.ed_url.text().strip()
        parts = urllib.parse.urlsplit(customvoices.base_url(url))
        if parts.scheme not in ("http", "https") or not parts.netloc or " " in parts.netloc:
            self._error(_("The address starts with http:// or https://"))
            return
        self._round += 1
        n, fixed = self._round, self.preset()[4]
        self.b_find.setText(_("Finding voices…"))
        self.b_find.setEnabled(False)
        self.err.hide()

        def work():
            names, err = None, ""
            try:
                if fixed != "list":
                    if not customvoices.answers(customvoices.speech_url(url)):
                        raise OSError("no answer")
                    names = list(fixed)
                else:
                    try:
                        names = customvoices.list_voices(url)
                    except (OSError, ValueError):
                        if not customvoices.answers(customvoices.speech_url(url)):
                            raise
            except (OSError, ValueError):
                err = _("Nothing answers at {address}",
                        address=address(customvoices.speech_url(url)))
            busy.emit(self._found, n, names, err, owner=self)
        threading.Thread(target=work, name="voice-server-find", daemon=True).start()

    def _on_found(self, n: int, names, err: str):
        if n != self._round:
            return
        self.b_find.setText(_("Find voices"))
        self.b_find.setEnabled(True)
        self._show_found(names, err)

    def _show_found(self, names: list[str] | None, err: str, asked: bool = True):
        """`names`: the ticks to offer; None with no `err`: it answers but has no list
        (type the voice); `err`: nothing answered. Not `asked`: nothing found yet."""
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self._ticks = []
        for i, name in enumerate(names or []):
            c = QCheckBox(name)
            c.toggled.connect(lambda _on: self._count())
            grid.addWidget(c, i // TICK_COLS, i % TICK_COLS)
            self._ticks.append(c)
        grid.setColumnStretch(TICK_COLS - 1, 1)
        self.voices.setWidget(box)
        box.adjustSize()
        self.voices.setFixedHeight(min(LIST_H, box.sizeHint().height()))
        self.voices.setVisible(bool(names))
        typed = asked and names is None and not err
        self.voice_row.setVisible(typed)
        if err:
            self.lbl.setText(err)
            theme.set_tone(self.lbl, "error")
        elif names:
            self.lbl.setText(_("Tick the voices you want: each one becomes a card."))
            theme.set_tone(self.lbl, "")
        elif typed:
            self.lbl.setText(_("No voice list at this address: type the voice's name."))
            theme.set_tone(self.lbl, "")
        self.lbl.setVisible(asked)
        self.b_add.setVisible(bool(names) or typed)   # nothing to add until it's found
        self._count()
        QTimer.singleShot(0, self, self._refit)

    def _refit(self):
        """As tall as what's in it now: a list that went (nothing answered this time)
        left its height behind as a gap (fit only ever grows a dialog)."""
        if self.isVisible():
            fit.shrink(self, fit.needed_height(self, self.width()))

    def picked(self) -> list[str]:
        if not self.voice_row.isHidden():
            return [self.ed_voice.text().strip()]
        return [c.text() for c in self._ticks if c.isChecked()]

    def _count(self):
        n = len([p for p in self.picked() if p or not self.voice_row.isHidden()])
        self.b_add.setText(_("Add voices ({n})", n=n))
        self.b_add.setEnabled(n > 0)

    # ------------------------------------------------------------ saving
    def _error(self, text: str):
        self.err.setText(text)
        self.err.show()

    def _add(self):
        names = self.picked()
        if not names:
            self._error(_("Tick at least one voice."))
            return
        url = self.ed_url.text().strip()
        speech = customvoices.speech_url(url)
        label = self.preset()[1] or address(speech)
        taken = {cv.name: cv for cv in customvoices.load()[0] if cv.url}
        saved = []
        try:
            for voice in names:
                name = voice or label
                old = taken.get(name)
                if old is not None and (old.url, old.voice) == (speech, voice):
                    continue   # this very voice is in already
                if old is not None or customvoices.server_path(name).exists():
                    name = f"{name} ({label})"
                customvoices.save_server(name, speech, voice, self.ed_model.text().strip(),
                                         self.ed_key.text().strip())
                saved.append(name)
        except OSError as e:
            self._error(_("Couldn't save it in the voices folder: {error}",
                          error=errors.plain(e)))
            return
        self.saved = saved
        if saved:   # which kind only, never its address or voices
            usage.used(f"voice-server-added-{self.preset()[0]}")
        self.accept()
