"""The pad menu's *Details* for a sound downloaded from YouTube, YouTube Music, TikTok
or SoundCloud: its picture, title and channel, when it was uploaded and added, its
length and views, and Open on YouTube / Copy link (soundboard.sourceinfo)."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout)

from soundboard import sourceinfo, theme
from soundboard.i18n import _
from soundboard.ui import busy, fit, icons

PIC_W, PIC_H = 160, 90   # a video's 16:9 thumbnail


def open_link(src: dict, window=None) -> bool:
    """Open the video in the browser."""
    return busy.open_url(src.get("link", ""), window=window)


def copy_link(src: dict, window=None) -> None:
    QApplication.clipboard().setText(src.get("link", ""))
    busy.toast(window, _("✓ Link copied"), "ok")


class SourceDialog(QDialog):
    forgotten = Signal()   # Delete info: the owner saves the settings

    def __init__(self, meta, parent=None):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.meta = meta
        self.src = sourceinfo.clean(meta.source)
        site = sourceinfo.site_name(self.src)
        self.setWindowTitle(site)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(12)

        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 14, 14, 14)
        cv.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)
        pic = QLabel()
        pic.setFixedSize(PIC_W, PIC_H)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = QPixmap(meta.image) if meta.image else QPixmap()
        if not pm.isNull():
            pic.setPixmap(pm.scaled(PIC_W, PIC_H, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
        else:   # no thumbnail: the site's icon on an inner area
            pic.setStyleSheet(f"background: {theme.T['inset']}; border-radius: 8px;")
            pic.setPixmap(icons.pixmap(sourceinfo.icon(self.src), 40,
                                       theme.T["muted"]))
        top.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        title = QLabel(self.src.get("title") or meta.name)
        f = title.font()
        f.setPointSizeF(f.pointSizeF() * 1.15)
        f.setBold(True)
        title.setFont(f)
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        names.addWidget(title)
        if ch := self.src.get("channel"):
            chl = QLabel()
            chl.setObjectName("hint")
            if link := self.src.get("channel_link"):
                chl.setText(f'<a href="{html.escape(link)}" style="color: {theme.T["accent"]};'
                            f' text-decoration: none;">{html.escape(ch)}</a>')
                chl.setOpenExternalLinks(True)
                chl.setToolTip(link)
            else:
                chl.setText(html.escape(ch))
            names.addWidget(chl)
        names.addStretch(1)
        top.addLayout(names, 1)
        cv.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        shown = {_("Uploaded"), _("Length"), _("Views"), _("Added")}
        for r, (k, val) in enumerate((k, x) for k, x in sourceinfo.rows(self.src)
                                     if k in shown):
            lab = QLabel(k)
            lab.setObjectName("hint")
            grid.addWidget(lab, r, 0)
            vl = QLabel(val)
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(vl, r, 1)
        grid.setColumnStretch(2, 1)
        cv.addLayout(grid)
        v.addWidget(card)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_open = QPushButton(icons.icon(sourceinfo.icon(self.src)),
                                    _("Open on {site}", site=site))
        self.btn_open.setObjectName("primary")
        self.btn_open.setToolTip(self.src.get("link", ""))
        self.btn_open.clicked.connect(lambda: open_link(self.src, self))
        self.btn_copy = QPushButton(icons.icon("copy"), _("Copy link"))
        self.btn_copy.clicked.connect(self._copy)
        close = QPushButton(_("Close"))
        close.clicked.connect(self.accept)
        for b in (self.btn_open, self.btn_copy, close):
            row.addWidget(b)
        self.btn_forget = QPushButton()
        self.btn_forget.setObjectName("iconbutton")
        icons.set_icon(self.btn_forget, "trash", "danger_text")
        self.btn_forget.setToolTip(_("Delete info"))
        self.btn_forget.setAccessibleName(_("Delete info"))
        self.btn_forget.clicked.connect(self._forget)
        row.addWidget(self.btn_forget)
        row.addStretch(1)
        v.addLayout(row)
        self.setMaximumWidth(620)

    def _forget(self):
        """Ask, then drop the link and details and the text file (the sound stays)."""
        box = QMessageBox(QMessageBox.Question, _("Delete info"),
                          _("Delete where “{name}” came from?\n\nIts link, channel and other "
                            "details and their text file are deleted. The sound stays.",
                            name=self.meta.name),
                          QMessageBox.Yes | QMessageBox.Cancel, self)
        box.button(QMessageBox.Yes).setText(_("Delete"))
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return
        sourceinfo.forget(self.meta)
        self.forgotten.emit()
        self.accept()

    def _copy(self):
        QApplication.clipboard().setText(self.src.get("link", ""))
        busy.flash(self.btn_copy, _("✓ Copied"))
