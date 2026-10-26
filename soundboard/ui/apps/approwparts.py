"""Part of an Apps tab card (ui/apps/approw.py `AppRow`): fitting it to its width (the one-line
list view, dropping words then the typed volume), where it sends, and showing the program's
state: running or not, its window and devices, the status line, sending, recording, the clip
editor and its icon."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLayout, QSizePolicy

from soundboard.audio import appaudio
from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.panel import HoverCard
from soundboard.ui.window.responsive import settled
from soundboard.win import exeicon

if TYPE_CHECKING:
    from typing import Any

    _Base = HoverCard
else:
    _Base = object


class AppRowParts(_Base):
    if TYPE_CHECKING:   # what AppRow has that these use
        _line: Any
        _line_lay: Any
        _top: Any
        _v: Any
        btn_clip: Any
        btn_forget: Any
        btn_rec: Any
        btn_send: Any
        btn_view: Any
        buttons_w: Any
        cb_to: Any
        exe: Any
        findChildren: Any
        folder: Any
        header: Any
        icon: Any
        layout: Any
        listen: Any
        meter: Any
        minimumSizeHint: Any
        mix_w: Any
        name: Any
        setEnabled: Any
        sub: Any
        view: Any
        vol: Any
        width: Any
        window: Any

    def set_listed(self, on: bool):
        """The list view: everything on one line (name, level, buttons, volume, ✕),
        the window picture still folding out below. A row narrower than LINE_MIN_W
        stacks as the card does, still one a line: squeezed onto one line, the
        buttons were crushed to slivers."""
        if on == self.listed:
            return
        self.listed = on
        self._tight = -1
        self._fit_width(self.width())

    def _arrange(self, as_line: bool):
        self._as_line = as_line
        v, line = self._v, self._line_lay
        if as_line:
            line.addWidget(self.header, 3)
            line.addWidget(self.meter, 1)
            line.addWidget(self.buttons_w)
            line.addWidget(self.mix_w, 1)
            self.header.setMinimumWidth(150)   # the name never squeezed away
            self.meter.setMinimumWidth(50)
            self.meter.setMaximumWidth(120)
            self.buttons_w.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.mix_w.setMinimumWidth(110)
            self.mix_w.setMaximumWidth(190)
            self._top.removeWidget(self.btn_forget)
            line.addWidget(self.btn_forget)
            v.insertWidget(0, self._line)
            self._line.show()
            v.setContentsMargins(12, 6, 8, 6)
        else:
            self._top.addWidget(self.btn_forget, 0, Qt.AlignmentFlag.AlignTop)
            for i, w in enumerate((self.header, self.meter, self.buttons_w, self.mix_w)):
                v.insertWidget(i, w)
            self.meter.setMinimumWidth(60)
            self.meter.setMaximumWidth(16777215)
            self.header.setMinimumWidth(0)
            self.buttons_w.setSizePolicy(QSizePolicy.Policy.Preferred,
                                         QSizePolicy.Policy.Preferred)
            self.mix_w.setMinimumWidth(0)
            self.mix_w.setMaximumWidth(16777215)
            self._line.hide()
            v.setContentsMargins(12, 10, 12, 10)

    NAME_ROOM = 0    # the name has its own line in the card: nothing to keep room for
    # narrow card, in this order: the typed volume goes, the buttons keep only their
    # icons (their tooltips say what they are)
    _TIGHTEN = ("spin", "send", "rec")
    LINE_MIN_W = 720   # px: the list view's one line with its words dropped, and room

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
        as_line = self.listed and width >= self.LINE_MIN_W
        if as_line != self._as_line:
            self._arrange(as_line)
            self._tight = -1
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
        self._label_send()
        if not self.btn_rec.isChecked():   # while recording it shows how long it's been
            self.btn_rec.setText("" if "rec" in on else _("Record"))
        lay = self.layout()
        assert lay is not None   # made in __init__
        lay.activate()

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
                              else _("Sending") if self.sending else _("Send"))
        icons.text_gap(self.btn_send)   # (its icon was set before it had words)

    def _on_view(self, on: bool):
        if on:
            usage.used("apps-window-view")
        self.btn_view.setToolTip(_("Hide this program's window") if on
                                 else _("Show this program's window"))
        # the card grows or shrinks in one paint: closing, it kept its old height a
        # frame with everything moved, then closed up
        with settled(self.window()):
            self.view.set_open(on)

    def close_view(self):
        if self.btn_view.isChecked():
            self.btn_view.setChecked(False)
        self.view.set_open(False)

    def set_app(self, app: appaudio.App | None):
        """The program is running (app) or not (None)."""
        self.app = app
        running = app is not None
        has_window = app is not None and bool(app.title)
        if app is not None and has_window:
            self.view.set_pids((app.pid, *sorted(app.session_pids)))
        else:
            self.close_view()
        self.btn_view.setVisible(has_window)
        if running:
            self.known_name = app.name   # kept for when it closes
            self.name.setText(app.name + self.folder)
            self._set_icon(app.path)
            where = ", ".join(app.devices[:2])
            sub = app.title or app.exe
            # a quiet program keeps its audio session (and its devices): it says so
            if where and app.active:
                sub = _("{title}  ·  playing on {devices}", title=sub, devices=where)
            elif where:
                sub = _("{title}  ·  quiet on {devices}", title=sub, devices=where)
            if not self.status_text:   # an error stays up until the next attempt
                self.sub.setText(sub)
        else:
            self.name.setText((self.known_name
                               or (self.exe.rsplit(".", 1)[0].capitalize() if self.exe else "?"))
                              + self.folder)
            self.set_status("")
            self.sub.setText(_("Not running: it'll be picked up when it starts"))
        # not running: its icon faded, so a remembered card doesn't pass for a live one
        if running != (self.icon.graphicsEffect() is None):
            if running:
                self.icon.setGraphicsEffect(None)  # pyright: ignore[reportArgumentType] - None takes it off (Qt allows it)
            else:
                fade = QGraphicsOpacityEffect(self.icon)
                fade.setOpacity(0.4)
                self.icon.setGraphicsEffect(fade)
        self.btn_send.setEnabled(running)
        self.btn_rec.setEnabled(running)
        self.btn_clip.setEnabled(running or self.btn_clip.isChecked())
        self.btn_forget.setVisible((not running or not self.sending) and self.listen is None)
        self.setEnabled(True)
        self.name.setEnabled(running)
        name = self.name.text()   # a screen reader hears whose card each button is on
        self.btn_send.setAccessibleName(_("Send {name}", name=name))
        self.btn_rec.setAccessibleName(_("Record {name}", name=name))
        self.btn_forget.setAccessibleName(_("Forget {name}", name=name))
        self.btn_clip.setAccessibleName(_("Clip editor for {name}", name=name))
        self.btn_view.setAccessibleName(_("Window of {name}", name=name))
        self.vol.slider.setAccessibleName(_("Volume of {name}", name=name))
        self.vol.spin.setAccessibleName(_("Exact volume of {name}", name=name))

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
        self.btn_forget.setVisible((not self.sending or self.app is None) and not on)

    def set_recording(self, on: bool):
        self.btn_rec.blockSignals(True)
        self.btn_rec.setChecked(on)
        self.btn_rec.blockSignals(False)
        if not on:
            self.btn_rec.setText("" if "rec" in self._TIGHTEN[:self._tight] else _("Record"))

    def _set_icon(self, path: str, force: bool = False):
        # set_app runs on every refresh (each 1.5 s, 5 s while hidden): only when the
        # program changed. The icon itself was read by the listing's thread (exeicon):
        # asking the shell here held up the audio
        if not force and path == getattr(self, "_icon_path", None):
            return
        self._icon_path = path
        img = exeicon.get(path) if path else None
        if img is None:
            pm = icons.icon("apps", "accent").pixmap(QSize(22, 22))
        else:
            dpr = self.icon.devicePixelRatioF()
            side = round(24 * dpr)
            pm = QPixmap.fromImage(img.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
            pm.setDevicePixelRatio(dpr)
        self.icon.setPixmap(pm)
