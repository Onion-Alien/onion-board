"""Part of the download card (ui/window/downloadbar.py `DownloadBar`): where it sits and how it
folds: the banner or the corner card over the page (above the player bar and anything low on
the page), folding to its pill and gliding between the two."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRect, QVariantAnimation
from PySide6.QtWidgets import QFrame, QWidget

from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.window import responsive
from soundboard.ui.window.downloadbits import CARD_GAP, CARD_MARGIN, CARD_W, PILL_BAR_W

if TYPE_CHECKING:
    from typing import Any

    _Base = QFrame
else:
    _Base = object


class DownloadPlace(_Base):
    if TYPE_CHECKING:   # what DownloadBar has that these use
        _area: Any
        _collapsed: Any
        _corner: Any
        _fit_tight: Any
        _glide: Any
        _glide_from: Any
        _glide_to: Any
        _host: Any
        _mini: Any
        _outer: Any
        _place_due: Any
        _room: Any
        _sync_head: Any
        _tall: Any
        _tight: Any
        _under: Any
        btn_min: Any
        contentsMargins: Any
        geometry: Any
        hasHeightForWidth: Any
        heightForWidth: Any
        hide: Any
        isRightToLeft: Any
        isVisible: Any
        isVisibleTo: Any
        panel: Any
        placed: Any
        property: Any
        raise_: Any
        room_changed: Any
        rows: Any
        s_bar: Any
        scroll_area: Any
        setGeometry: Any
        setParent: Any
        setProperty: Any
        sizeHint: Any
        style: Any
        summary: Any

    def set_collapsed(self, on: bool):
        """Minimised: just the summary line (and a thin bar), in the corner a pill, so the
        page under it shows again; its chevron, or a click anywhere on it, opens it
        again."""
        on = on and not self._mini
        glide = self._corner and self.isVisible() and on != self._collapsed
        start = self.geometry()
        self._collapsed = on
        self._apply_fold()
        if glide:
            self.place(start)   # at once: no frame of the new view in the old size
        self.room_changed.emit()

    def _folded(self) -> bool:
        """Only the summary line shows: minimised, or the window has no room for more."""
        return self._collapsed or self._room == "line"

    def _apply_fold(self):
        folded = self._folded() if self._tall is None else not self._tall
        pill = self._corner and folded
        if bool(self.property("pill")) != pill:
            self.setProperty("pill", pill)
            self.style().unpolish(self)
            self.style().polish(self)
            self.s_bar.setMaximumWidth(PILL_BAR_W if pill else 160)
        self.panel.setVisible(not folded)
        self.scroll_area.setVisible(self.rows.count() > 1 and self._room == "open")
        self._outer.setContentsMargins(8, 6 if folded else 8, 8, 6 if folded else 8)
        self._fold_icon()
        self._sync_head()
        # the window's fitter measures again straight away: without this the box around
        # the bar kept the open list's height, nothing seemed to fit, and a failed link
        # sent a roomy window into the mini player (where the bar never re-measures)
        responsive.touch(self.panel)

    def _set_room(self, room: str):
        if room != self._room:
            self._room = room
            self._apply_fold()

    def _fold_icon(self):
        self.btn_min.setAccessibleName(_("Show more") if self._folded() else _("Hide"))
        # the corner card folds down into its pill and opens upwards; the mini
        # player's bar the other way round
        opens, folds = ("fold_up", "fold_open") if self._corner else ("fold_open", "fold_up")
        icons.set_icon(self.btn_min, opens if self._folded() else folds, "muted")

    def float_in(self, host: QWidget, area: QWidget, under: tuple[QWidget, ...] = ()):
        """A card over the bottom-right corner of `area` (the page; bottom-left right to
        left), above it rather than in its layout, so nothing under it moves when it
        comes and goes. A child of `host`, which holds the page and what's under it:
        it's hidden with it (the mini player). It stands on the highest of `under` that
        shows and has something under it (the Now playing row's chips, the player bar),
        else on the host's bottom; its top never goes past the page's."""
        self._corner = True
        self._host = host
        self._area = area
        self._under = under
        self.setParent(host)
        for w in (host, area, *under):
            w.installEventFilter(self)
        self.room_changed.connect(self._place_soon)
        self._tight = True   # makes _fit_tight apply the card's own rule
        self._fit_tight()
        self._fold_icon()
        self.hide()

    # (LayoutRequest: chips came or went on the Now playing row)
    _MOVES = (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide,
              QEvent.Type.LayoutRequest)

    def eventFilter(self, obj, ev):
        if (ev.type() in self._MOVES and self._host is not None
                and (obj is self._host or obj is self._area or obj in self._under)
                and self.isVisibleTo(self._host)):
            self._place_soon()
        return False

    def _in_host(self, w: QWidget) -> QRect:
        """`w`'s rectangle in the host's coordinates."""
        host = self._host
        assert host is not None
        win = host.window()
        return QRect(w.mapTo(win, QPoint(0, 0)) - host.mapTo(win, QPoint(0, 0)), w.size())

    def _floor(self, left: int, right: int) -> int:
        """The host y the card stands on, given its host x span: above the highest of
        `under` that shows and has something under it. The Now playing row's chips sit
        on the left: past them the card goes down onto the player."""
        host = self._host
        if host is None:
            return 0
        floor = host.height()
        for w in self._under:
            if not w.isVisibleTo(host) or w.height() <= 0:
                continue
            r = self._in_host(w)
            used = w.childrenRect()   # what's drawn on it (a row's chips), else all of it
            if not used.isEmpty():
                x0, x1 = r.x() + used.left(), r.x() + used.right()
                if x1 < left - CARD_GAP or x0 > right + CARD_GAP:
                    continue   # nothing under the card
            floor = min(floor, r.y())
        return floor

    def _place_soon(self):
        if self._corner:
            self._place_due.start(0)

    def card_width(self) -> int:
        area = self._area
        return max(200, min(CARD_W, area.width() - 2 * CARD_MARGIN)) if area else CARD_W

    def _card_x(self, w: int) -> int:
        page = self._in_host(self._area) if self._area is not None else QRect()
        return (page.left() + CARD_MARGIN if self.isRightToLeft()
                else page.right() + 1 - w - CARD_MARGIN)

    def place(self, glide_from: QRect | None = None):
        """Its size and spot in the corner: the whole list if the page has the height,
        else the running row, else the summary line; minimised, a pill as wide as the
        summary line needs. `glide_from`: it slides there from that rectangle."""
        host, area = self._host, self._area
        if host is None or area is None or not self._corner:
            return
        if self._tall is not None:   # measured as it'll end up
            self._tall = None
            self._outer.setEnabled(True)
            self._apply_fold()
        w = self.card_width()
        x = self._card_x(w)
        floor = self._floor(x, x + w)
        room_h = floor - self._in_host(area).top() - 2 * CARD_GAP
        lay = self._outer
        h = 0
        for room in ("open", "row", "line"):
            self._set_room(room)
            lay.activate()
            h = self.heightForWidth(w) if self.hasHeightForWidth() else self.sizeHint().height()
            if h <= room_h:
                break
        if self._collapsed:   # the pill: as wide as its line, never wider than the card
            w = min(w, self.summary.sizeHint().width() + 20)
        h = max(0, min(h, room_h))
        x = self._card_x(w)
        to = QRect(x, floor - h - CARD_GAP, w, h)
        glide = self._glide
        if glide_from is not None and glide_from.isValid() and glide_from != to:
            glide.stop()
            self._glide_from, self._glide_to = QRect(glide_from), to
            # the pictures as for the wider end: they don't drop out as it slides
            self._fit_tight(max(glide_from.width(), to.width()))
            glide.start()
            self._glide_step(0.0)
            return
        if glide.state() == QVariantAnimation.State.Running:
            self._glide_to = to   # the window moved under it: it goes to the new spot
            self._glide_step(glide.currentValue())
            return
        self.setGeometry(to)
        self.raise_()
        self.placed.emit()

    def _glide_step(self, k: float):
        a, b = self._glide_from, self._glide_to
        shrinks = b.height() < a.height()
        ease = QEasingCurve(QEasingCurve.Type.InOutCubic)
        first = ease.valueForProgress(min(1.0, k * 2))
        second = ease.valueForProgress(max(0.0, k * 2 - 1))
        kh, kw = (first, second) if shrinks else (second, first)

        def mix(x0: int, x1: int, t: float) -> int:
            return round(x0 + (x1 - x0) * t)

        r = QRect(QPoint(mix(a.left(), b.left(), kw), mix(a.top(), b.top(), kh)),
                  QPoint(mix(a.right(), b.right(), kw), mix(a.bottom(), b.bottom(), kh)))
        if a.height() == b.height():
            tall = not self._folded()
        else:
            tall = k < 0.5 if shrinks else k >= 0.5
        if tall != self._tall:
            self._tall = tall
            self._outer.setEnabled(True)
            self._apply_fold()
            if tall:
                # the list laid out at its full size, then held there: the card's edge
                # cuts it off instead of the rows squashing together
                full = QRect(0, 0, max(a.width(), b.width()), max(a.height(), b.height()))
                self._outer.setGeometry(full.marginsRemoved(self.contentsMargins()))
                self._outer.setEnabled(False)
        self.setGeometry(r)
        self.raise_()
        self.placed.emit()   # the toasts standing on it go with it

    def _end_glide(self):
        self._glide.stop()
        if self._tall is not None:
            self._tall = None
            self._outer.setEnabled(True)
            self._apply_fold()

    def _glide_done(self):
        self._end_glide()
        self._fit_tight()
        self.place()
