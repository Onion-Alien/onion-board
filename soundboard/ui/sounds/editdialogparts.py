"""Part of the sound's edit dialog (ui/sounds/dialogs.py `EditDialog`): its Source line, the
fade cells, the render and live-preview progress, the status note, the picture (from a file or
a link), the pad colour, the name check and the hotkey."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from soundboard.audio import soundfx
from soundboard.core import errors, usage
from soundboard.i18n import _
from soundboard.online import net
from soundboard.sounds import sourceinfo, thumbs
from soundboard.sounds.library import MAX_FADE_S, PAD_COLORS
from soundboard.ui.kit import busy, icons, theme, toast
from soundboard.ui.kit.hotkeypick import HotkeyDialog, pretty_key
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.ui.kit.panel import steady_number
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.sounds import sourcedialog


PIC_W, PIC_H = 64, 36   # the Picture row's 16:9 preview


log = logging.getLogger("soundboard.ui.sounds.dialogs")

if TYPE_CHECKING:
    from typing import Any

    _Base = QDialog
else:
    _Base = object


class EditDialogParts(_Base):
    if TYPE_CHECKING:   # what EditDialog has that these use
        _bb: Any
        _look: Any
        _reset_glow: Any
        _source_at: Any
        adv: Any
        btn_pic_clear: Any
        btn_preview: Any
        btn_reset: Any
        custom_swatch: Any
        effects: Any
        fx_note: Any
        hk_btn: Any
        advanced: Any
        hotkeys: Any
        hotkeys_changed: Any
        live_bar: Any
        meta: Any
        name: Any
        name_hint: Any
        others: Any
        pic_note: Any
        pic_view: Any
        picture_fetched: Any
        render_bar: Any
        render_box: Any
        render_close: Any
        render_stop: Any
        render_words: Any
        source_forgotten: Any
        swatches: Any
        simple: Any

    def _fill_source(self):
        """The "From YouTube: channel  [Details]" row, for the sound shown (none: no row)."""
        if self.source_row is not None:
            self._look.removeWidget(self.source_row)
            self.source_row.hide()
            self.source_row.deleteLater()
        self.btn_source = self.source_row = None
        if not (src := sourceinfo.shown(self.meta)):
            return
        srow = QHBoxLayout()
        srow.setSpacing(8)
        ic = QLabel()
        icons.set_label_icon(ic, sourceinfo.icon(src), size=16)
        srow.addWidget(ic)
        site, who = sourceinfo.site_name(src), src.get("channel")
        from_lbl = QLabel(_("From {site}: {channel}", site=site, channel=who) if who
                          else _("From {site}", site=site))
        from_lbl.setObjectName("muted")
        from_lbl.setTextFormat(Qt.TextFormat.PlainText)   # a web channel name (plaintext.py)
        srow.addWidget(from_lbl)
        self.btn_source = QPushButton(_("Details"))
        self.btn_source.setProperty("quiet", True)
        self.btn_source.setToolTip(plain_tip(src["link"]))
        srow.addWidget(self.btn_source)
        srow.addStretch(1)
        row = self.source_row = QWidget()
        row.setLayout(srow)
        srow.setContentsMargins(0, 0, 0, 0)
        self._look.addWidget(row, self._source_at, 0, 1, 2)

        def details():
            d = sourcedialog.SourceDialog(self.meta, self)
            d.forgotten.connect(row.hide)
            d.forgotten.connect(self.source_forgotten)   # the owner saves it
            d.show()
        self.btn_source.clicked.connect(details)

    @staticmethod
    def _fade_cell(grid: QGridLayout, r: int, col: int, label: str, value: float, tip: str,
                   top: float = MAX_FADE_S) -> QSlider:
        """A 0..top slider in tenths of a second, its name and value above it."""
        v = QVBoxLayout()
        v.setSpacing(4)
        head = QHBoxLayout()
        name = QLabel(label)
        name.setToolTip(tip)
        lbl = QLabel()
        lbl.setObjectName("muted")
        steady_number(lbl, _("{s} s", s=f"{top:.1f}"))
        head.addWidget(name)
        head.addStretch(1)
        head.addWidget(lbl)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(0, int(top * 10))
        sl.setValue(int(round(min(max(value, 0.0), top) * 10)))
        sl.setToolTip(tip)
        sl.setAccessibleName(label)
        no_wheel(sl)

        def show(v):
            lbl.setText(_("{s} s", s=f"{v / 10:.1f}") if v else _("off"))
            sl.setAccessibleDescription(lbl.text())
        sl.valueChanged.connect(show)
        show(sl.value())
        v.addLayout(head)
        v.addWidget(sl)
        grid.addLayout(v, r, col)
        return sl

    def render_shown(self) -> bool:
        return not self.render_box.isHidden()

    def show_render(self, frac: float | None, words: str = "", can_stop: bool = False):
        """Its sound's effects render: how far (`frac`, 0..1, and `words`), or None when
        there's none (then `words`, if any, says why it ended: shown where the effects
        summary goes)."""
        on = frac is not None
        was = self.render_shown()
        if on:
            self.render_bar.setValue(int(round(frac * 1000)))
            self.render_words.setText(_("Applying the effects: {how}", how=words))
            self.render_bar.setAccessibleDescription(words)
            self.render_stop.setVisible(can_stop)
        if on == was:
            return
        # the bar's box is taller than the buttons it stands in for: the window grows
        # by the difference (on its screen) rather than squeezing the waveform, whose
        # bottom edge went under the Start / End row; and gives it back after
        extra = self.render_box.sizeHint().height() - self._bb.sizeHint().height()
        self._bb.setVisible(not on)
        self.btn_preview.setVisible(not on)
        self._reset_glow.setVisible(not on)
        self.simple.setEnabled(not on)   # the draft is saved: it waits while it renders
        if getattr(self, "adv", None) is not None:
            self.adv.setEnabled(not on)
        self.render_box.setVisible(on)
        self._grow_for_render(extra if on else -getattr(self, "_render_grew", 0))
        if on:
            self.render_close.setDefault(True)
            self.render_close.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            save = self._bb.button(QDialogButtonBox.StandardButton.Save)
            save.setFocus(Qt.FocusReason.OtherFocusReason)
            if words:
                self._say(words, 6000)

    def _grow_for_render(self, by: int):
        """Taller by `by` px (less, to give it back), as far as the screen has room."""
        if not by or self.isMaximized() or not self.isVisible():
            self._render_grew = 0
            return
        h = self.height() + by
        if by > 0 and (screen := self.screen()) is not None:
            room = screen.availableGeometry()
            h = min(h, room.bottom() - self.geometry().top() + 1)
        grew = max(0, h - self.height())
        self._render_grew = grew if by > 0 else 0
        if h != self.height():
            self.resize(self.width(), max(h, self.minimumHeight()))

    def _light_reset(self):
        """Reset effects stands out (the accent border and glow) while any effect is
        on, so it's easy to find; the trim alone doesn't count (Reset keeps it)."""
        f = self.effects.fx()
        on = bool(f) and not soundfx.is_neutral({**f, "start": 0.0, "end": 0.0})
        self._reset_glow.set_on(on)
        if bool(self.btn_reset.property("nudge")) != on:
            self.btn_reset.setProperty("nudge", on)
            self.btn_reset.style().unpolish(self.btn_reset)
            self.btn_reset.style().polish(self.btn_reset)

    def show_live(self, frac: float | None, words: str = ""):
        """The playing sound being made again with these effects: how far (`frac`,
        0..1), or None when it's done or dropped (then `words`, if any, say how it
        went, where the effects summary goes)."""
        if frac is not None:
            pct = int(frac * 100)
            self.live_bar.setValue(int(round(frac * 1000)))
            self.live_bar.show()
            self._say(_("Applying to the playing sound: {pct}%. It plays on as it was "
                        "until then.", pct=pct), 0)
            return
        self.live_bar.hide()
        if words:
            self._say(words, 6000)
        elif getattr(self, "_saying", False):
            self._said = getattr(self, "_said", 0) + 1
            self._saying = False
            self._fx_note()

    def _fx_note(self):
        if getattr(self, "_saying", False):
            return   # a preview message is up: it puts the summary back when it's done
        # (Simple has its summary's chips at the top instead)
        s = soundfx.summary(self.effects.fx()) if self.advanced() else ""
        self.fx_note.setText(_("Effects: {s}", s=s) if s else "")
        self.fx_note.setVisible(bool(s))

    def _say(self, text: str, ms: int):
        """A preview message where the effects summary goes; back to the summary after
        ``ms`` (0: stays until the next message)."""
        self._saying = True
        self.fx_note.setText(text)
        self.fx_note.show()
        self._said = getattr(self, "_said", 0) + 1
        if ms:
            n = self._said

            def back():
                if n == self._said:
                    self._saying = False
                    self._fx_note()
            QTimer.singleShot(ms, self, back)

    # ------------------------------------------------------------------ picture
    def _show_picture(self):
        """The picture as it will be after Save, and only the buttons that apply."""
        if isinstance(self.picture, QImage):
            pm = QPixmap.fromImage(self.picture)
        elif self.picture is None and self.meta.image:
            pm = QPixmap(self.meta.image)
        else:
            pm = QPixmap()
        if not pm.isNull():
            self.pic_view.setPixmap(pm.scaled(PIC_W, PIC_H, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        self.pic_view.setVisible(not pm.isNull())   # no picture: just the buttons
        self.btn_pic_clear.setVisible(not pm.isNull())

    def _set_picture(self, pic):
        self._pic_gen += 1   # a link still loading no longer counts
        self.pic_note.setText("")
        self.picture = pic
        self._show_picture()

    def _picture_from_file(self):
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

    def _picture_from_link(self):
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
        self.pic_note.setText(_("Getting the picture…"))

        def work():   # the network, off the UI thread
            try:
                img, err = thumbs.fetch(url), ""
            except (thumbs.LinkError, net.FeatureOff) as e:
                img, err = None, str(e)
            except Exception as e:  # noqa: BLE001 - never leave it saying "Getting…"
                log.exception("picture from a link")
                img, err = None, errors.plain(e)
            busy.emit(self.picture_fetched, gen, img, err)
        threading.Thread(target=work, daemon=True, name="edit-picture-link").start()

    def _on_picture_fetched(self, gen: int, img, err: str):
        if gen != self._pic_gen:   # another picture was picked meanwhile
            return
        if img is None or img.isNull():
            self.pic_note.setText("")
            busy.toast(self, toast.titled(_("Couldn't use that picture"),
                                          err or _("There's no picture at that link.")), "warn")
            return
        self._set_picture(img)

    def _pick_custom(self):
        c = QColorDialog.getColor(QColor(self.color or PAD_COLORS[0]), self,
                                  _("Pick a colour"))
        if c.isValid():
            usage.used("custom-colour")
        self._set_color(c.name() if c.isValid() else self.color)

    def _set_color(self, c):
        self.color = c
        t = theme.T
        custom = bool(c) and c.lower() not in {col.lower() for col in PAD_COLORS}
        b = self.custom_swatch
        b.setChecked(custom)
        ink = (("#000000" if QColor(c).lightnessF() > 0.6 else "#ffffff") if custom
               else "muted")
        icons.set_icon(b, "palette", ink, ink, size=12)
        bg = c if custom else t["inset"]
        b.setStyleSheet(
            f"QPushButton {{ background:{bg}; border:1px solid {t['border']};"
            f" border-radius:11px; }}"
            f"QPushButton:checked {{ border:3px solid {t['text']}; }}"
            f"QPushButton:focus {{ border:2px solid {t['accent']}; }}"
            f"QPushButton:checked:focus {{ border:3px solid {t['accent']}; }}")
        for b, col in self.swatches:
            b.setChecked(col == c)
            # its own sheet outranks the theme's :focus rule, so focus is drawn here:
            # an accent ring, thick when it's also the chosen colour
            b.setStyleSheet(
                f"QPushButton {{ background:{col}; border:1px solid {t['border']};"
                f" border-radius:11px; }}"
                f"QPushButton:checked {{ border:3px solid {t['text']}; }}"
                f"QPushButton:focus {{ border:2px solid {t['accent']}; }}"
                f"QPushButton:checked:focus {{ border:3px solid {t['accent']}; }}")

    def _check_name(self, *_a):
        """The warning under Name: another sound already goes by it (any case)."""
        name = self.name.text().strip().casefold()
        taken = bool(name) and self.others is not None and any(
            m.id != self.meta.id and m.name.strip().casefold() == name for m in self.others())
        self.name_hint.setVisible(taken)

    def _set_hk(self, combo):
        self.hotkey = combo
        self.hk_btn.setText(pretty_key(combo) or _("Click to set"))
        if getattr(self, "adv", None) is not None:
            self.adv.hk.setText(self.hk_btn.text())

    def _capture(self):
        d = HotkeyDialog(self.hotkeys, self)
        if d.exec() and d.result_combo:
            self._set_hk(d.result_combo)
        self.hotkeys_changed.emit()   # the capture paused them; the owner re-registers
