"""The pad menu's *Details* for a sound downloaded from YouTube, YouTube Music, TikTok
or SoundCloud: its picture, title and channel, when it was uploaded and added, its
length and views, and Open on YouTube / Copy link (soundboard.sounds.sourceinfo)."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QLabel, QMessageBox,
                               QVBoxLayout, QWidget)

from soundboard.sounds import sourceinfo
from soundboard.ui.kit import theme
from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.kit.modalframe import WIDTH, InfoCard
from soundboard.ui.kit.panel import icon_button
from soundboard.ui.kit.plaintext import plain_tip

PIC_W, PIC_H = 160, 90   # a video's 16:9 thumbnail


def open_link(src: dict, window=None) -> bool:
    """Open the video in the browser."""
    usage.used("source-open")
    return busy.open_url(src.get("link", ""), window=window)


def copy_link(src: dict, window=None) -> None:
    usage.used("source-copy-link")
    QApplication.clipboard().setText(src.get("link", ""))
    busy.toast(window, _("✓ Link copied"), "ok")


class SourceDialog(InfoCard):
    """Where a sound came from, on the shared card frame: the video's picture in the
    header with its title and channel, the dates under them, Open / Copy link bottom
    right and the bin on the left. A click outside, Esc or the ✕ shuts it."""
    forgotten = Signal()   # Delete info: the owner saves the settings

    def __init__(self, meta, parent=None):
        usage.used("source-details")
        self.meta = meta
        self.src = sourceinfo.clean(meta.source)
        site = sourceinfo.site_name(self.src)
        super().__init__(self.src.get("title") or meta.name, self.src.get("channel", ""),
                         button="", width=WIDTH, parent=parent)
        self.setWindowTitle(site)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        fit.watch(self)   # grows to fit its text (ui/kit/fit.py)
        self.heading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # the video's picture where the mascot would be (its inner-area look: theme.py)
        pic = QLabel()
        pic.setFixedSize(PIC_W, PIC_H)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = QPixmap(meta.image) if meta.image else QPixmap()
        if not pm.isNull():
            pic.setPixmap(pm.scaled(PIC_W, PIC_H, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
        else:   # no thumbnail: the site's icon on an inner area
            pic.setObjectName("sourcepic")
            icons.set_label_icon(pic, sourceinfo.icon(self.src), size=40)
        tile = QFrame()
        tile.setObjectName("card")   # (the inner area's style lives under a card)
        tl = QVBoxLayout(tile)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(pic)
        head, old = self.frame.layout(), self.mascot
        assert head is not None and old is not None
        head.replaceWidget(old, tile)
        old.hide()
        old.deleteLater()
        self.mascot = self.frame.mascot = None
        if (ch := self.src.get("channel")) and (link := self.src.get("channel_link")):
            self.subtitle.setTextFormat(Qt.TextFormat.RichText)
            self.subtitle.setText(f'<a href="{html.escape(link)}" style="color: '
                                  f'{theme.T["accent_link"]}; text-decoration: none;">'
                                  f'{html.escape(ch)}</a>')
            self.subtitle.setOpenExternalLinks(True)
            self.subtitle.setToolTip(plain_tip(link))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        shown = {_("Uploaded"), _("Length"), _("Views"), _("Added")}
        for r, (k, val) in enumerate((k, x) for k, x in sourceinfo.rows(self.src)
                                     if k in shown):
            lab = QLabel(k)
            lab.setObjectName("muted")
            grid.addWidget(lab, r, 0)
            vl = QLabel(val)
            vl.setTextFormat(Qt.TextFormat.PlainText)
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(vl, r, 1)
        grid.setColumnStretch(2, 1)
        if grid.count():
            self.frame.body.addLayout(grid)

        # icons that follow a theme switch while it's open (set_icon), on the filled
        # Open button in its words' colour; the main one first, bottom right
        self.btn_open = self.frame.add_button(_("Open on {site}", site=site), primary=True)
        icons.set_icon(self.btn_open, sourceinfo.icon(self.src), "on_accent")
        self.btn_open.setToolTip(plain_tip(self.src.get("link", "")))
        self.btn_open.clicked.connect(lambda: open_link(self.src, self))
        self.btn_copy = self.frame.add_button(_("Copy link"))
        icons.set_icon(self.btn_copy, "copy")
        self.btn_copy.clicked.connect(self._copy)
        # the bin acts on the details above: on the left, last in Tab order; focus
        # starts on Open, never on deleting
        self.btn_forget = icon_button("trash", _("Delete info"))
        icons.set_icon(self.btn_forget, "trash", "danger_text")
        self.btn_forget.clicked.connect(self._forget)
        self.frame.footer.insertWidget(0, self.btn_forget)
        QWidget.setTabOrder(self.btn_open, self.btn_copy)
        QWidget.setTabOrder(self.btn_copy, self.btn_forget)
        QWidget.setTabOrder(self.btn_forget, self.close_btn)
        self.btn_open.setFocus()

    def showEvent(self, ev):   # noqa: N802 - Qt API
        super().showEvent(ev)
        QTimer.singleShot(0, self, self.btn_open.setFocus)   # (after Qt's own popup focus)

    def _forget(self):
        """Ask, then drop the link and details and the text file (the sound stays)."""
        box = QMessageBox(QMessageBox.Icon.Question, _("Delete info"),
                          _("Delete where “{name}” came from?\n\nIts link, channel and other "
                            "details and their text file are deleted. The sound stays.",
                            name=self.meta.name),
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                          self.parentWidget() or self)   # (asking closes this pop-up)
        box.setTextFormat(Qt.TextFormat.PlainText)   # the name is a web title
        box.button(QMessageBox.StandardButton.Yes).setText(_("Delete"))
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        sourceinfo.forget(self.meta)
        usage.used("source-deleted")
        self.forgotten.emit()
        self.accept()

    def _copy(self):
        usage.used("source-copy-link")
        QApplication.clipboard().setText(self.src.get("link", ""))
        busy.flash(self.btn_copy, _("✓ Copied"))
