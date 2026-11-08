"""Pick a picture for one of your voices (a saved voice changer voice or your own AI
voice): one of the app's voice pictures (ui/voice/art.py), a picture file, or a
picture pasted from the clipboard. `ask` shows the window; `write` keeps the pick as a
square PNG."""
from __future__ import annotations

import html
import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QLabel,
                               QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget)

from soundboard import voicefx
from soundboard.i18n import _
from soundboard.sounds import thumbs
from soundboard.speech import aivoicelist as avl
from soundboard.ui.kit.modalframe import ModalFrame
from soundboard.ui.kit import busy, fit, icons, toast
from soundboard.ui.voice import art

log = logging.getLogger(__name__)

DEFAULT = "voice-custom"   # your voices' picture until you pick one (My own mix's)
SAVED = 256                # the picture as kept (cards show it at most 128 px)
TILE = 44
COLS = 9


def _names() -> dict[str, str]:
    """Each picture's tooltip: the voice it's drawn for."""
    out = {art.voice_key(p): voicefx.shown(p) for p in voicefx.PRESETS}
    out.update({"ai-voice-" + art.slug(v["id"]): v["name"] for v in avl.BUILT_IN})
    out[DEFAULT] = _("My own mix")
    return out


def keys() -> list[str]:
    """The app's voice pictures: My own mix's first, the voice changer's, the AI voices'."""
    have = {p.stem for p in art.ART_DIR.glob("*.png")}
    rest = sorted(k for k in have if k.startswith("voice-") and k != DEFAULT)
    return ([DEFAULT] if DEFAULT in have else []) + rest + \
        sorted(k for k in have if k.startswith("ai-voice-"))


def write(img: QImage | None, path: Path) -> bool:
    """Keep `img` at `path` as a square PNG (centre-cropped), or remove it (None)."""
    try:
        if img is None:
            path.unlink(missing_ok=True)
            return True
        side = min(img.width(), img.height())
        sq = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
        sq = sq.scaled(SAVED, SAVED, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not sq.save(str(path)):           # a PNG: from the name
            raise OSError(f"couldn't write {path}")
        return True
    except OSError:
        log.warning("couldn't save the voice's picture", exc_info=True)
        return False


def art_image(key: str) -> QImage | None:
    img = QImage(str(art.ART_DIR / f"{key}.png"))
    return None if img.isNull() else img


class PicLabel(QLabel):
    """A voice's picture that, while it's one of yours (`set_editable`), opens Pick a
    picture on a click (`clicked`)."""
    clicked = Signal()

    def set_editable(self, on: bool):
        self.setProperty("editable", on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor)
        self.setToolTip(_("Change the picture") if on else "")

    def mousePressEvent(self, e):
        if self.property("editable") and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            return
        super().mousePressEvent(e)


class PicturePicker(QDialog):
    """The app's voice pictures to click, or From a file / Paste. After exec():
    `image` is the pick (None: back to the usual picture)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        fit.watch(self)
        self.image: QImage | None = None
        self.setWindowTitle(_("Pick a picture"))
        self.setMaximumWidth(620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = ModalFrame(self.windowTitle(),
                           _("Click one of the app's pictures, or use your own: a "
                             "picture file, or one you copied (Ctrl+V)."),
                           close=False)   # (the window's own ✕)
        outer.addWidget(frame)
        lay = frame.body
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        names = _names()
        for i, key in enumerate(keys()):
            b = QToolButton()
            b.setIcon(art.icon(key) or QIcon())
            b.setIconSize(QSize(TILE, TILE))
            b.setAutoRaise(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            tip = names.get(key) or key.removeprefix("ai-voice-").removeprefix("voice-") \
                .replace("-", " ").capitalize()
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.clicked.connect(lambda __=False, k=key: self._pick_art(k))
            grid.addWidget(b, i // COLS, i % COLS)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(grid_box)
        scroll.setMinimumWidth(grid_box.sizeHint().width()
                               + scroll.verticalScrollBar().sizeHint().width())
        scroll.setMinimumHeight(min(grid_box.sizeHint().height(), 4 * (TILE + 14)))
        lay.addWidget(scroll, 1)
        # your own picture on the left, Cancel on the right
        b_file = QPushButton(_("From a file…"))
        icons.set_icon(b_file, "image")
        b_file.clicked.connect(self._pick_file)
        frame.footer.insertWidget(0, b_file)
        b_paste = QPushButton(_("Paste"))
        icons.set_icon(b_paste, "copy")
        b_paste.setToolTip(_("Use a picture you copied (Ctrl+V)"))
        b_paste.clicked.connect(self._paste)
        frame.footer.insertWidget(1, b_paste)
        frame.add_button(_("Cancel")).clicked.connect(self.reject)
        QShortcut(QKeySequence.StandardKey.Paste, self, self._paste)

    def _done(self, img: QImage | None):
        self.image = img
        self.accept()

    def _pick_art(self, key: str):
        self._done(None if key == DEFAULT else art_image(key))

    def _pick_file(self):
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
        self._done(img)

    def _paste(self):
        """A copied picture, or a copied picture file."""
        data = QGuiApplication.clipboard().mimeData()
        img = QImage()
        if data is not None and data.hasImage():
            img = QImage(data.imageData())
        elif data is not None and data.hasUrls():
            local = next((u.toLocalFile() for u in data.urls() if u.isLocalFile()), "")
            img = QImage(local) if local else QImage()
        if img.isNull():
            busy.toast(self, html.escape(_("There's no picture to paste. Copy one first.")),
                       "warn")
            return
        self._done(img)


def ask(parent: QWidget) -> tuple[bool, QImage | None]:
    """(picked?, the picture: None for the usual one)."""
    d = PicturePicker(parent)
    ok = d.exec() == QDialog.DialogCode.Accepted
    return ok, d.image
