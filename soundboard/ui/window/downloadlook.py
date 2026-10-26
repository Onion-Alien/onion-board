"""Part of the download card (ui/window/downloadbar.py `DownloadBar`): its look in the theme: the
style sheet, the card's and rows' gradients, and lining up its two lines of text."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QFrame, QSizePolicy

from soundboard.ui.kit import theme
from soundboard.ui.window.downloadbits import PILL_R
from soundboard.ui.window.downloadparts import SOFT, glow

if TYPE_CHECKING:
    from typing import Any

    _Base = QFrame
else:
    _Base = object


class DownloadLook(_Base):
    if TYPE_CHECKING:   # what DownloadBar has that these use
        _drops: Any
        _fill_rows: Any
        _fold_icon: Any
        _icon: Any
        _row1: Any
        _source: Any
        _sync_head: Any
        _update_thumb: Any
        bar: Any
        lbl_meta: Any
        lbl_title: Any
        pill: Any
        property: Any
        setProperty: Any
        setStyleSheet: Any
        src_icon: Any
        style: Any
        url: Any

    def retheme(self):
        T = theme.T
        k = glow()
        card_bg = theme.mix(T["card"], T["accent"], 0.12 * k)
        border = theme.mix(T["card"], T["accent"], 0.38 * k)
        row_bg = theme.mix(card_bg, T["text"], 0.05)
        bad = theme.status("error")

        self.setStyleSheet(
            f"QFrame#downloadbar {{ background:{card_bg}; border:1px solid {border}; "
            f"border-radius:12px; }}"
            + self._gradient_css(row_bg) +
            f"QWidget#downloadhead, QWidget#queuepanel, QWidget#queueholder, "
            f"QScrollArea#queuescroll {{ background:transparent; border:none; }}"
            # words sit on the banner (the flat themes give every widget a background)
            f"QFrame#downloadbar QLabel {{ background:transparent; }}"
            f"QLabel#downloadhead {{ color:{T['text_hi']}; font-weight:600; }}"
            f"QLabel#kindtag {{ color:{T['live_text']}; font-size:8.5pt; font-weight:600; }}"
            f"QLabel#downloadtitle {{ color:{T['text_hi']}; font-weight:600; }}"
            f"QLabel#queuetitle {{ color:{T['text']}; }}"
            f"QLabel#queuetitle[waiting=\"true\"] {{ color:{T['muted']}; }}"
            f"QLabel#downloadmeta {{ color:{T['muted']}; font-size:8.5pt; }}"
            f"QLabel#downloadstatus {{ color:{T['text']}; font-size:8.5pt; font-weight:600; }}"
            f"QLabel#downloadstatus[tone=\"ok\"] {{ color:{theme.status('ok')}; }}"
            f"QLabel#downloadstatus[tone=\"error\"] {{ color:{bad}; }}"
            f"QPushButton#dlicon {{ background:transparent; border:none; border-radius:8px; "
            f"padding:0px; }}"
            f"QPushButton#dlicon:hover {{ background:{T['btn_hover']}; }}"
            f"QPushButton#dlicon:pressed {{ background:{T['btn_press']}; }}"
            f"QPushButton#retrybutton {{ background:{T['btn']}; border:none; border-radius:8px; "
            f"padding:2px 10px; color:{T['text']}; font-size:8pt; font-weight:600; }}"
            f"QPushButton#retrybutton:hover {{ background:{T['btn_hover']}; }}"
            f"QPushButton#retrybutton[main=\"true\"] {{ background:{theme.accent_fill()}; "
            f"{theme.accent_edge()} color:{T['on_accent']}; }}"
            f"QPushButton#retrybutton[main=\"true\"]:hover "
            f"{{ background:{theme.accent_fill(hover=True)}; }}"
            f"QFrame#queuerow {{ background:transparent; border:1px solid transparent; "
            f"border-radius:8px; }}"
            f"QFrame#queuerow[running=\"true\"] {{ background:{row_bg}; }}"
            # lights up under the mouse like the app's other cards (More tabs)
            f"QFrame#queuerow:hover {{ background:{theme.mix(row_bg, T['text'], 0.06)}; "
            f"border-color:{T['border_hi']}; }}"
            + self._row_gradient_css(row_bg)
            # minimised in the corner: a pill (its height is the summary line's, 40)
            + f"QFrame#downloadbar[pill=\"true\"] {{ border-radius:{PILL_R}px; }}"
        )
        self.bar.update()
        self._fold_icon()
        self.pill.retheme()
        self._line_up()
        self._sync_head()
        if self.url:
            self._update_thumb()   # the plain icon is drawn in the theme's colour
            self.src_icon.setPixmap(self._icon(self._source[0]))
        self._fill_rows()

    def _gradient_css(self, row_bg: str) -> str:
        """The banner as one of the theme's designed surfaces: the accent lit at the top
        left fading into the theme's second colour, a light rim on top. How it ended
        tints the lit corner: green when added, red when it failed (state below). The
        outlined theme (High Contrast) stays flat."""
        if not theme.polished():
            return ""
        T, mix = theme.T, theme.mix
        base = T["card"]
        a, a2 = T["accent"], T.get("accent2") or T["accent"]
        ok, bad = theme.status("ok"), theme.status("error")
        k = glow()   # soft unless the theme's cards share the accent's colour
        mid = mix(base, a, 0.12 * k)
        end = mix(base, a2, 0.14 * k)
        rim = mix(mix(base, a, 0.45 * k), "#ffffff", 0.18 * k)

        def grad(top, middle, last):
            return (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {top}, "
                    f"stop:0.45 {middle}, stop:1 {last})")
        # added / failed: a light green / red at half on every theme (they're never the
        # theme's colours); failed is red the whole way across, so it still reads as red
        # in red themes (Blood Moon), and the red words, pill and Retry say the rest
        return (f"QFrame#downloadbar {{ background:{grad(mix(base, a, 0.26 * k), mid, end)}; "
                f"border-color:{mix(base, a, 0.38 * k)}; border-top-color:{rim}; }}"
                f"QFrame#downloadbar[ended=\"ok\"] {{ "
                f"background:{grad(mix(base, ok, 0.22 * SOFT), mid, end)}; "
                f"border-color:{mix(base, ok, 0.45 * SOFT)}; }}"
                f"QFrame#downloadbar[ended=\"failed\"] {{ background:"
                f"{grad(mix(base, bad, 0.26 * SOFT), mix(base, bad, 0.14 * SOFT),
                        mix(base, bad, 0.08 * SOFT))}; "
                f"border-color:{mix(base, bad, 0.65 * SOFT)}; }}")

    def _row_gradient_css(self, row_bg: str) -> str:
        """The running row lit from the left in the accent; the others plain until the
        mouse is on them."""
        if not theme.polished():
            return ""
        T, mix = theme.T, theme.mix
        k = glow()
        hover = mix(row_bg, T["text"], 0.06)

        def lit(left, rest):
            return (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {left}, "
                    f"stop:0.5 {rest}, stop:1 {rest})")
        return (f"QFrame#queuerow[running=\"true\"] {{ "
                f"background:{lit(mix(row_bg, T['accent'], 0.16 * k), row_bg)}; "
                f"border-color:{mix(row_bg, T['text'], 0.07)}; }}"
                f"QFrame#queuerow:hover {{ background:"
                f"{lit(mix(hover, T['accent'], 0.24 * k), hover)}; "
                f"border-color:{T['border_hi']}; }}")

    def _set_ended(self, how: str):
        """"ok", "failed" or "" (running): the banner's gradient follows it."""
        if self.property("ended") == how:
            return
        self.setProperty("ended", how)
        self.style().unpolish(self)
        self.style().polish(self)

    def _line_up(self):
        """Line 1 on one line: the title and the uploader on the same baseline, the
        site's logo centred on the middle of the title's capitals. Worked out from the
        fonts the style sheet gave."""
        texts = (self.lbl_title, self.lbl_meta)
        for w in texts:
            w.ensurePolished()
        cap_mid = QFontMetricsF(self.lbl_title.font()).capHeight() / 2
        line_at = {}
        for w in texts:
            fm = QFontMetricsF(w.font())
            w.setFixedHeight(math.ceil(fm.height()))
            line_at[w] = (w.height() - fm.height()) / 2 + fm.ascent()
        line_at[self.src_icon] = self.src_icon.height() / 2 + cap_mid
        base = max(line_at.values())
        for w, drop in self._drops.items():
            drop.changeSize(0, round(base - line_at[w]), QSizePolicy.Policy.Minimum,
                            QSizePolicy.Policy.Fixed)
        self._row1.invalidate()
