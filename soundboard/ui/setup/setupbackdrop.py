"""The first launch's plain backdrop: while the quick-setup guide is up, the window
behind it shows just the theme's background, not a board that isn't set up yet. When
the guide closes (finished or not) it fades away and the app shows.

It's up before the window first shows, the logo big in the middle where the loading
screen was, so the loading screen hands over to it without the app flashing up first.
As the guide comes in, the logo and name fade out: the title bar already says them.

A child of the window, over everything in it: no window of its own appears.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, QVariantAnimation, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from soundboard.ui.kit import theme
from soundboard.ui.bun import splash
from soundboard.ui.kit.toast import animations_on

REVEAL_MS = 320   # the fade to the app once the guide is gone
SETTLE_MS = 520   # the logo and name fading out as the guide comes in
NAME = "Onion Board"
# In the middle the logo stands where Bun stood on the loading screen and the name where
# its name was (splash.py: the card's centred on the screen, as the window is), so as the
# loading screen fades the name stays put and Bun gives way to the logo.
BIG, BIG_DY = 80, 78 - splash.CARD_H / 2      # the logo: Bun's size and centre (_bun_rect)
BIG_PX, NAME_DY = 18, 155 - splash.CARD_H / 2  # the name: its pixel size and centre


class Backdrop(QWidget):
    def __init__(self, window: QWidget, logo: bool = True):
        """`logo`: start with the logo and name (the first launch, after the loading
        screen); without, just the background (the guide opened again)."""
        super().__init__(window)
        self.setObjectName("setupbackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._k = 0.0 if logo else 1.0   # 0: the logo and name in the middle, 1: gone
        self._settle: QVariantAnimation | None = None
        self._fade: QVariantAnimation | None = None
        window.installEventFilter(self)
        self.setGeometry(window.rect())
        self.raise_()
        self.show()

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, ev):
        p = QPainter(self)
        r = QRectF(self.rect())
        theme.paint_window_bg(p, r, QPointF(0, 0), r.width(), r.height())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        # the logo and name stay where the loading screen had them and fade out as the
        # guide comes in. They used to glide to the top corner, right under the title
        # bar's own logo and name: the same thing twice
        alpha = 1.0 - self._k
        if alpha <= 0:
            return
        cx, cy = r.width() / 2, r.height() / 2
        p.setOpacity(alpha)
        theme.paint_logo(p, QRectF(cx - BIG / 2, cy + BIG_DY - BIG / 2, BIG, BIG),
                         theme.T["accent"], theme.T["accent2"])
        p.setOpacity(1.0)
        p.setPen(QColor(theme.T["text_hi"]))
        self._name(p, BIG_PX, cx, cy + NAME_DY, alpha, centred=True)

    @staticmethod
    def _font(px: int) -> QFont:
        f = QFont(theme.T.get("font", theme.FONT))   # (the loading screen's)
        f.setPixelSize(px)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def _name(self, p: QPainter, f: QFont | int, x: float, y: float, alpha: float,
              centred: bool = False):
        """The name in font `f` (or the loading screen's, `f` pixels high), its middle
        at height `y`: centred on `x`, or starting there."""
        if alpha <= 0:
            return
        if isinstance(f, int):
            f = self._font(f)
        p.setFont(f)
        fm = QFontMetricsF(f)
        tw, th = fm.horizontalAdvance(NAME), fm.height()
        left = x - tw / 2 if centred else x
        p.setOpacity(min(1.0, alpha))
        p.drawText(QRectF(left, y - th / 2, tw + 4, th),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, NAME)
        p.setOpacity(1.0)

    def _set_k(self, k):
        self._k = float(k)
        self.update()

    def settle(self):
        """The guide is coming in: the logo and name fade out."""
        if self._settle is not None or self._k >= 1:
            return
        if not animations_on():
            self._set_k(1.0)
            return
        self._settle = QVariantAnimation(self)
        self._settle.setDuration(SETTLE_MS)
        self._settle.setStartValue(self._k)
        self._settle.setEndValue(1.0)
        self._settle.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._settle.valueChanged.connect(self._set_k)
        self._settle.start()

    def reveal(self):
        """Fade out, then go: the app underneath is what's left."""
        if self._fade is not None:
            return
        if not animations_on():
            self.deleteLater()
            return
        fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(fx)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(REVEAL_MS)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(fx.setOpacity)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()
