"""The Add-ons tab's voice servers: a row for each TTS server in the voices folder,
saying whether it answers (checked off the UI thread once when the voices load, and
again only from the Add-ons tab's Refresh: nothing asks them over and over), with an on
/ off switch (on: it's the computer voice, so it
speaks your typed lines) and its settings in a fold under it."""
from __future__ import annotations

import logging
import threading
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

from soundboard.core import errors
from soundboard.i18n import _
from soundboard.online import net
from soundboard.sounds import thumbs
from soundboard.speech import customvoices
from soundboard.speech.customvoices import CustomVoice
from soundboard.ui.kit import busy, fit, icons, theme, toast
from soundboard.ui.kit.panel import fold_button, hint_label, section_label
from soundboard.ui.kit.panellayouts import Flow
from soundboard.ui.kit.restyled import on_restyle
from soundboard.ui.voice import art
from soundboard.ui.voice.fxcontrols import Switch
from soundboard.ui.voice.voicetiles import LIST_ART, TILE_ART

log = logging.getLogger(__name__)

FORM_W = 640        # the settings fold's widest
PIC_SAVED = 256     # a picture from a link, as kept beside the server's .json
PILL_H = 22         # the Online / Offline pill
NOT_OFFERED = {"onion-watch", "voice-random"}   # not a voice's face


def app_pictures() -> list[str]:
    """The app's own voice pictures a server can wear, by key."""
    return sorted(p.stem for p in art.ART_DIR.glob("*.png") if p.stem not in NOT_OFFERED)


def picture_pixmap(cv: CustomVoice, size: int) -> QPixmap | None:
    """A server's picture as a rounded square, or None when it has none."""
    f = customvoices.picture_file(cv)
    if f is not None:
        return art.file_pixmap(f, size)
    return art.pixmap(cv.picture, size) if cv.picture else None


class PicturePicker(QDialog):
    """The app's voice pictures in a grid: a click picks one."""

    def __init__(self, parent: QWidget | None, current: str = ""):
        super().__init__(parent)
        fit.watch(self)
        self.setWindowTitle(_("Pick a picture"))
        self.picked = ""
        v = QVBoxLayout(self)
        grid = QWidget()
        flow = Flow(grid, gap=8)
        for key in app_pictures():
            b = QToolButton()
            b.setObjectName("iconbutton")
            b.setProperty("quiet", True)
            b.setCheckable(True)
            b.setChecked(key == current)
            b.setIcon(art.icon(key) or QIcon())
            b.setIconSize(QSize(TILE_ART, TILE_ART))
            b.setFixedSize(TILE_ART + 12, TILE_ART + 12)
            name = key.removeprefix("ai-").removeprefix("voice-").replace("-", " ").capitalize()
            b.setToolTip(name)
            b.setAccessibleName(name)
            b.clicked.connect(lambda _on=False, k=key: self._pick(k))
            flow.addWidget(b)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(grid)
        side, cols = TILE_ART + 12, 8      # 8 across exactly: no empty strip on the right
        scroll.setMinimumSize(cols * side + (cols - 1) * 8
                              + scroll.verticalScrollBar().sizeHint().width() + 4,
                              5 * (side + 8))
        v.addWidget(scroll, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _pick(self, key: str):
        self.picked = key
        self.accept()


def address(url: str) -> str:
    """A server's host and port, the part that tells two servers apart."""
    return urllib.parse.urlsplit(url).netloc or url


class ServerRow(QFrame):
    """One server: a badge and words for whether it answers, its switch, and Settings."""
    switched = Signal(str, bool)      # its voice id, on
    saved = Signal()
    remove_asked = Signal(object)     # the CustomVoice
    picture_changed = Signal()
    _link_fetched = Signal(int, str, str)   # round, file name, error

    def __init__(self, cv: CustomVoice):
        super().__init__()
        self.cv = cv
        self.online: bool | None = None   # None: not asked yet
        self._pic_gen = 0
        self._link_fetched.connect(self._on_link_fetched)
        self.setObjectName("voicebox")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.pic = QLabel()
        self.pic.setFixedSize(LIST_ART, LIST_ART)
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.pic)
        # the name and its pill on one line, what that means on a line under them (a
        # narrow window wraps it there, not into a column beside the name)
        words = QVBoxLayout()
        words.setSpacing(2)
        line = QHBoxLayout()
        line.setSpacing(8)
        name = section_label(cv.name)
        name.setProperty("head", True)   # no top padding: it shares a line with the pill
        line.addWidget(name)
        self.pill = QLabel()          # Online / Offline / Checking…
        self.pill.setObjectName("pill")
        # tall enough for its 10 px corners (Qt squares off a radius over half the
        # height, and its text alone makes it ~18 px)
        self.pill.setFixedHeight(PILL_H)
        line.addWidget(self.pill)
        line.addStretch(1)
        words.addLayout(line)
        self.state = hint_label("")
        words.addWidget(self.state)
        top.addLayout(words, 1)
        body = QWidget()
        self.fold = fold_button(_("Settings"), body)
        top.addWidget(self.fold)
        self.switch = Switch(_("Use {name} for typed lines", name=cv.name))
        self.switch.toggled.connect(lambda on: (self._show_state(),
                                                self.switched.emit(cv.id, on)))
        top.addWidget(self.switch)
        v.addLayout(top)

        body.setMaximumWidth(FORM_W)   # an address needs room; a whole card row is too much
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        self.ed_url = QLineEdit(cv.url)
        self.ed_url.setPlaceholderText("http://127.0.0.1:8880/v1/audio/speech")
        self.ed_voice = QLineEdit(cv.voice)
        self.ed_voice.setPlaceholderText(_("the server's voice name, e.g. af_bella (optional)"))
        self.ed_model = QLineEdit(cv.model)
        self.ed_model.setPlaceholderText(_("optional"))
        self.ed_key = QLineEdit(cv.api_key)
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_key.setPlaceholderText(_("only if the server asks for one"))
        for lbl, w in ((_("Address"), self.ed_url), (_("Voice"), self.ed_voice),
                       (_("Model"), self.ed_model), (_("API key"), self.ed_key)):
            form.addRow(lbl, w)
        # its picture: one of the app's, or one from a link; it's kept at once (no Save)
        prow = QHBoxLayout()
        prow.setSpacing(8)
        b = self.b_pic_ours = QPushButton(_("Pick one of ours"))
        icons.set_icon(b, "image")
        b.clicked.connect(self._pick_ours)
        prow.addWidget(b)
        b = self.b_pic_link = QPushButton(_("From a link…"))
        b.clicked.connect(self._pick_link)
        prow.addWidget(b)
        b = self.b_pic_clear = QPushButton(_("Remove picture"))
        b.setProperty("quiet", True)
        b.clicked.connect(lambda: self._set_picture(""))
        prow.addWidget(b)
        prow.addStretch(1)
        form.addRow(_("Picture"), prow)
        self.err = hint_label("")
        theme.set_tone(self.err, "error")
        self.err.hide()
        self.ed_url.textEdited.connect(lambda _t: self.err.hide())
        form.addRow(self.err)
        brow = QHBoxLayout()
        brow.setSpacing(8)
        brow.addStretch(1)
        b_save = self.b_save = QPushButton(_("Save"))
        b_save.setObjectName("primary")
        b_save.clicked.connect(self._save)
        b_remove = self.b_remove = QPushButton(_("Remove server"))
        b_remove.setObjectName("danger")
        b_remove.setProperty("quiet", True)
        b_remove.clicked.connect(lambda: self.remove_asked.emit(self.cv))
        brow.addWidget(b_save)
        brow.addWidget(b_remove)
        form.addRow(brow)
        v.addWidget(body)
        self._show_state()
        self._show_picture()
        on_restyle(self.pic, self._show_picture)   # the line icon's colour, per theme

    def _show_picture(self):
        pm = picture_pixmap(self.cv, LIST_ART)
        if pm is None:   # no picture yet: the computer voice's own line icon
            pm = icons.pixmap("speech", 18, theme.T["muted"])
        self.pic.setPixmap(pm)
        self.b_pic_clear.setVisible(bool(self.cv.picture))

    def _set_picture(self, picture: str) -> bool:
        path = self.cv.file or customvoices.server_path(self.cv.name)
        try:
            customvoices.set_picture(Path(path), picture)
        except (OSError, ValueError) as e:
            self.err.setText(_("Couldn't save it in the voices folder: {error}",
                               error=errors.plain(e)))
            self.err.show()
            return False
        self.cv.picture = picture
        self._show_picture()
        self.picture_changed.emit()
        return True

    def _pick_ours(self):
        dlg = PicturePicker(self, self.cv.picture)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.picked:
            self._set_picture(dlg.picked)

    def _pick_link(self):
        copied = QApplication.clipboard().text().strip()
        copied = copied if "://" in copied and len(copied) < 2000 and \
            not any(c.isspace() for c in copied) else ""
        url, ok = QInputDialog.getText(
            self, _("Picture from a link"),
            _("The picture's address (right-click it → Copy image address),\nor a link "
              "to a YouTube video or a web page:"), text=copied)
        url = url.strip()
        if not ok or not url:
            return
        self._pic_gen += 1
        gen = self._pic_gen
        busy.set_busy(self.b_pic_link, True)
        json_path = Path(self.cv.file or customvoices.server_path(self.cv.name))
        name = json_path.stem + ".png"

        def work():   # the network and the file, off the UI thread
            err = ""
            try:
                img = thumbs.fetch(url)
                if img.isNull():
                    raise thumbs.LinkError(_("There's no picture at that link."))
                side = min(img.width(), img.height())
                sq = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
                sq = sq.scaled(PIC_SAVED, PIC_SAVED, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                if not sq.save(str(json_path.parent / name)):
                    raise OSError(f"couldn't write {name}")
            except (thumbs.LinkError, net.FeatureOff) as e:
                err = str(e)
            except Exception as e:  # noqa: BLE001 - never leave the button busy
                log.exception("voice server picture from a link")
                err = errors.plain(e)
            busy.emit(self._link_fetched, gen, name, err)
        threading.Thread(target=work, daemon=True, name="server-picture-link").start()

    def _on_link_fetched(self, gen: int, name: str, err: str):
        if gen != self._pic_gen:
            return
        busy.set_busy(self.b_pic_link, False)
        if err:
            busy.toast(self, toast.titled(_("Couldn't use that picture"), err), "warn")
            return
        self._set_picture(name)

    def set_on(self, on: bool):
        if self.switch.isChecked() != on:
            self.switch.blockSignals(True)
            self.switch.setChecked(on)
            self.switch.blockSignals(False)
            self._show_state()

    def set_online(self, online: bool):
        self.online = online
        self._show_state()

    def _show_state(self):
        on = self.switch.isChecked()
        if self.online is None:
            pill, tone, words = _("Checking…"), "muted", ""
        elif not self.online:
            pill, tone = _("Offline"), "error"
            words = _("Nothing answers at {address}", address=address(self.cv.url))
        else:
            pill, tone = _("Online"), "ok"
            words = _("Speaks your typed lines") if on else ""
        self.pill.setText(pill)
        theme.set_tone(self.pill, tone)
        self.state.setText(words)
        self.state.setVisible(bool(words))   # nothing to add: one line, beside the picture

    def _save(self):
        url = self.ed_url.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            self.err.setText(_("The address starts with http:// or https://"))
            self.err.show()
            return
        path = self.cv.file or customvoices.server_path(self.cv.name)
        try:
            customvoices.update_server(Path(path), url, self.ed_voice.text().strip(),
                                       self.ed_model.text().strip(), self.ed_key.text().strip())
        except (OSError, ValueError) as e:
            self.err.setText(_("Couldn't save it in the voices folder: {error}",
                               error=errors.plain(e)))
            self.err.show()
            return
        self.err.hide()
        busy.flash(self.b_save, _("✓ Saved"), 1400)
        self.saved.emit()


class ServerList(QWidget):
    """The rows, in the voices folder's order; hidden while there are none."""
    switched = Signal(str, bool)
    saved = Signal()
    remove_asked = Signal(object)
    picture_changed = Signal()
    _answered = Signal(int, str, bool)   # check round, voice id, online

    def __init__(self):
        super().__init__()
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(8)
        self.rows: dict[str, ServerRow] = {}
        self._round = 0
        self._answered.connect(self._got_answer)
        self.hide()

    def set_servers(self, servers: list[CustomVoice], current: str):
        """Rebuild the rows (after the voices were loaded), `current` switched on."""
        known = {k: r.online for k, r in self.rows.items()}
        for r in self.rows.values():
            self.v.removeWidget(r)
            r.hide()
            r.deleteLater()
        self.rows = {}
        for cv in servers:
            r = ServerRow(cv)
            r.online = known.get(cv.id)   # no "Checking…" flash for one already known
            r.set_on(cv.id == current)
            r._show_state()
            r.switched.connect(self.switched)
            r.saved.connect(self.saved)
            r.remove_asked.connect(self.remove_asked)
            r.picture_changed.connect(self.picture_changed)
            self.v.addWidget(r)
            self.rows[cv.id] = r
        self.setVisible(bool(servers))
        self.check()

    def sync(self, current: str):
        """The computer voice changed somewhere else (the Voice list, a chip)."""
        for k, r in self.rows.items():
            r.set_on(k == current)

    def online(self, voice: str) -> bool | None:
        r = self.rows.get(voice)
        return r.online if r is not None else None

    def check(self):
        """Ask every server whether it answers, off the UI thread."""
        if not self.rows:
            return
        self._round += 1
        n = self._round
        targets = [(k, r.cv.url) for k, r in self.rows.items()]

        def work():
            for k, url in targets:
                busy.emit(self._answered, n, k, customvoices.answers(url), owner=self)
        threading.Thread(target=work, name="voice-server-check", daemon=True).start()

    def _got_answer(self, n: int, key: str, online: bool):
        r = self.rows.get(key)
        if r is not None and n == self._round:
            r.set_online(online)
