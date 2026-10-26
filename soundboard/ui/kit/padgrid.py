"""The board: the grid that lays out the pads, and dropped files."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QEvent, QPoint, QPointF, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import (QGridLayout, QLabel, QMainWindow, QScrollArea, QVBoxLayout, QWidget)

from soundboard.sounds import thumbs
from soundboard.ui.kit import theme
from soundboard.sounds.library import AUDIO_EXTS
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.kit.layouts import (take_out, widget_at)
from soundboard.ui.kit.pad import (LIST_ROW_H, LIST_ROW_W, MINI_PAD_MIN_W, PAD_MIME, PAD_RADIUS,
                                   PAD_SHRINK, Pad, SLIM_PAD_H, pad_height)


class PadGrid(QWidget):
    reorder = Signal(str, int)   # sound id, new index
    files_dropped = Signal(list)
    image_dropped = Signal(str, str)   # sound id, picture file dropped on its pad
    laid_out = Signal()   # after each relayout: slack() may have changed
    HOW_TO = DROP_HINT = _("Drop sound files here")
    NO_MATCH = _("No sounds match the search\nor this category")
    DROP_HINT_HEIGHT = 110

    def __init__(self):
        super().__init__()
        self.pads: list[Pad] = []
        self.background_image = ""
        self.background_opacity = 0
        self.background_pad_height = 0
        self.pad_w = 150         # the size picked (Pad size); narrower only when it won't fit
        self.two_up = False      # the mini player: two smaller pads a row rather than one
        self.slim = False        # a tiny mini player: one-line rows instead of cards
        self.listed = False      # the list view (Sounds tab): one-line rows in columns
        self.row_size = "medium"   # ...and how big those rows are (LIST_ROW_H)
        self.grid = QGridLayout(self)
        self.grid.setSpacing(10)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)   # see event()
        # no sounds yet: Bun waits (sadly) above the how-to, and cheers up when
        # files are dragged over
        self.empty = QWidget()
        self.empty.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 24, 0, 4)
        ev.setSpacing(12)
        self.bun = BunnyWidget(
            height=130, pad=16, sad=0.9,
            lines=(_("add a sound?"), _("pleeease?"), _("it's so quiet…"),
                   _("drop one on me!"), _("just one sound?"), _("I'm bored…")),
            hope_lines=(_("yes! drop it!"), _("ooh, for me?!")),
            joy_lines=(_("yay!!"), _("↑ Add sounds!"), _("hehe!")), pong=True, naps=True,
            dances=True)
        ev.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_text = QLabel(self.HOW_TO)
        # short lines: fits the mini player
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text.setWordWrap(True)   # and wraps rather than losing both ends
        self.empty_text.setObjectName("empty")
        self.empty_text.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.empty_text.setStyleSheet("padding:8px 12px; background:transparent;")
        self.empty_text.setFixedHeight(self.DROP_HINT_HEIGHT)
        ev.addWidget(self.empty_text)
        self._cols = 0
        self._n_shown = 0        # pads in the grid now (drop_area)
        self._shape = None       # (columns, pad width) last laid out
        self._slack = 0          # pixels right of a full row (slack())
        self._placed = None      # (columns, the pads shown) in the grid now
        self._slots: dict[Pad, tuple[int, int]] = {}   # the pads in the grid: row, column
        self.tab_after: QWidget | None = None   # the control Tab goes to the pads from

    def set_background(self, image: str, opacity: int):
        opacity = min(100, max(0, opacity))
        if (image, opacity) != (self.background_image, self.background_opacity):
            self.background_image, self.background_opacity = image, opacity
            self.update()

    def background_rect(self, size: QSize) -> QRectF:
        view = self.parentWidget()
        area = QRectF(0, -self.y(), self.width(),
                      view.height() if view else self.height())
        if size.isEmpty() or area.width() <= 0 or area.height() <= 0:
            return QRectF()
        return area

    def minimumSizeHint(self):
        # never wider than the scroll area around it: the pads fit themselves to its
        # width (relayout), so a narrower window can't leave them stuck wider than it
        # is, with a sideways scroll bar and the rest out of sight
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(0, super().sizeHint().height())

    def set_pads(self, pads, layout: bool = True):
        """The pads, in order. `layout`: lay them out now (False: the caller filters
        them next, and that lays them out)."""
        keep = set(pads)   # (one gone from the list is taken out of the grid by _place)
        self._slots = {p: at for p, at in self._slots.items() if p in keep}
        self.pads = pads
        self._shape = self._placed = None
        if layout:
            self.relayout(force=True)

    def set_pad_width(self, w: int):
        self.pad_w = w
        self.relayout(force=True)

    def set_two_up(self, on: bool):
        if on != self.two_up:
            self.two_up = on
            self.relayout(force=True)

    def set_slim(self, on: bool):
        if on != self.slim:
            self.slim = on
            self._spacing()
            self.relayout(force=True)

    def set_listed(self, on: bool):
        if on != self.listed:
            self.listed = on
            self._spacing()
            self.relayout(force=True)

    def set_row_size(self, size: str):
        if size in LIST_ROW_H and size != self.row_size:
            self.row_size = size
            if self.listed:
                self.relayout(force=True)

    def _spacing(self):
        self.grid.setSpacing(4 if self.slim else 6 if self.listed else 10)

    def rows(self) -> bool:
        """Pads drawn as one-line rows: the list view, or a tiny mini player."""
        return self.slim or self.listed

    def pad_h(self, w: int) -> int:
        return self.background_pad_height or self.natural_pad_h(w)

    def natural_pad_h(self, w: int) -> int:
        # as tall as the picked size while a row only stretches or squeezes them (the
        # height followed the width: each row losing a pad as the window narrowed
        # jolted every row below); only pads squeezed past that (a narrow window, the
        # mini player) get shorter
        if self.slim:
            return SLIM_PAD_H
        if self.listed:
            return LIST_ROW_H[self.row_size]
        return pad_height(min(self.pad_w, round(w / PAD_SHRINK)))

    def fit_width(self, room: int, slim: bool | None = None) -> tuple[int, int]:
        """(columns, pad width) for `room` pixels: the picked size, but never wider than
        the room, and two a row in the mini player while they'd still be a usable size.
        Slim rows take the whole width, one a row."""
        if self.slim if slim is None else slim:
            return 1, max(1, room)
        if self.listed and slim is None:   # the mini player's rows take the whole width
            if self.two_up:
                return 1, max(1, room)
            sp = 6
            cols = max(1, (room + sp) // (LIST_ROW_W[self.row_size] + sp))
            return cols, max(1, (room - sp * (cols - 1)) // cols)
        sp = 10
        w = max(1, min(self.pad_w, room))
        if self.two_up and (room + sp) // (w + sp) < 2 and room - sp >= 2 * MINI_PAD_MIN_W:
            w = (room - sp) // 2
        # the picked size is roughly what they get: the pads stretch so the row ends at
        # the edge (a fixed size left a strip as wide as most of a pad on the right),
        # or take one more a row when that shrinks them by a fifth at most
        cols = max(1, (room + sp) // (w + sp))
        if (room - sp * cols) // (cols + 1) >= w * PAD_SHRINK:
            cols += 1
        return cols, max(1, (room - sp * (cols - 1)) // cols)

    def slack(self) -> int:
        """Pixels left over right of a full row (the width rarely splits evenly)."""
        return self._slack if self.pads else 0

    def row_height(self) -> int:
        """One row of pads as they're laid out now, margins included (0 with none)."""
        m = self.grid.contentsMargins()
        if not self.pads or self._shape is None:
            return 0
        return self.pad_h(self._shape[1]) + m.top() + m.bottom()

    def relayout(self, force=False):
        m = self.grid.contentsMargins()
        room = self.width() - m.left() - m.right()
        cols, w = self.fit_width(room)
        self._slack = max(0, room - cols * w - self.grid.horizontalSpacing() * (cols - 1))
        self.laid_out.emit()
        if (cols, w) == self._shape and not force:
            return
        self._shape = (cols, w)
        self._cols = cols
        # the grid switched off while the pads move: each show() / addWidget() into a
        # live layout laid the whole grid out again (85-145 ms clearing a search with
        # 600 pads); once at the end instead
        self.grid.setEnabled(False)
        try:
            self._place(cols, w)
        finally:
            self.grid.setEnabled(True)
            self.grid.activate()
            # Moving children only repaints the strips they expose. The drop hint
            # also moves (or disappears), including background below every pad:
            # repaint it with the completed layout so its old border/text is erased.
            self.update()

    def _place(self, cols: int, w: int):
        h = self.pad_h(w)
        for p in self.pads:
            if p.width() != w or p.height() != h:
                p.setFixedSize(w, h)
        shown = [p for p in self.pads if not p.property("filtered")]
        self._n_shown = len(shown)
        placed = (cols, tuple(map(id, shown)))
        if shown and placed == self._placed:
            return   # the same pads in the same columns: only their size changed
        self._placed = placed if shown else None
        want = {p: (i // cols, i % cols) for i, p in enumerate(shown)}
        # only the pads that move are taken out and put back, and only the ones whose
        # filter changed are shown or hidden: a category click redid all of them, even
        # the hundreds out of sight
        slots, grid = self._slots, self.grid
        for i in reversed(range(grid.count())):   # from the end: each take is cheap
            it = widget_at(grid, i)
            pad = it if isinstance(it, Pad) else None
            # (Bun's never wanted)
            if pad is None or pad not in want or slots.get(pad) != want[pad]:
                take_out(grid, i)
                if pad is not None:
                    slots.pop(pad, None)
        if not shown:
            # every pad filtered out showed nothing at all: Bun says why instead
            for p in self.pads:
                p.hide()
            self.empty_text.setText(self.NO_MATCH if self.pads else self.HOW_TO)
            # across the whole width, however wide that is now (a fixed width here kept
            # the grid as wide as the window once was: a shrunk window showed nothing),
            # halfway down the page rather than stuck to its top
            grid.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(self.empty, 0, 0)
            self.empty.show()
            return
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty.hide()
        self.empty_text.setText(self.HOW_TO)
        for p, at in want.items():
            if p not in slots:
                # into the grid first: a new pad has no parent yet, and showing it then
                # flashed it up on the desktop as a little window of its own
                grid.addWidget(p, *at)
                slots[p] = at
        for p in self.pads:
            if p in want:
                if p.isHidden():
                    p.show()
            elif not p.isHidden():
                p.hide()
        # Tab order: the pads right after `tab_after`, in the order they're shown. A pad
        # put in the grid goes to the end of the window's focus chain, past the player bar
        prev: QWidget = self.tab_after or self
        for p in shown:
            QWidget.setTabOrder(prev, p)
            prev = p

    def tab_out(self, forward: bool) -> bool:
        """Tab (Shift+Tab) on a pad: focus the first control after (before) the pads."""
        tab = Qt.FocusPolicy.TabFocus.value
        w = self.window().focusWidget() or self
        for _i in range(5000):   # (the chain is a ring: never round it twice)
            w = w.nextInFocusChain() if forward else w.previousInFocusChain()
            if w is None:
                return False
            if (w is not self and not self.isAncestorOf(w) and w.focusProxy() is None
                    and w.focusPolicy().value & tab == tab and w.isVisible() and w.isEnabled()):
                w.setFocus(Qt.FocusReason.TabFocusReason if forward
                           else Qt.FocusReason.BacktabFocusReason)
                return True
        return False

    def event(self, e):
        done = super().event(e)
        if e.type() in (QEvent.Type.Polish, QEvent.Type.StyleChange, QEvent.Type.ParentChange):
            # opaque: it paints the page colour behind itself (paintEvent), so a scroll
            # copies what's on screen and only the strip that came into view is drawn.
            # See-through, every pad in view was painted again on each wheel step. Qt
            # clears the flag when the scroll area adopts it and on each restyle (a
            # theme change), so it's set again after those
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        return done

    def paintEvent(self, e):
        # the same colour the page behind it shows; read on each paint, so a theme
        # change (theme.apply repaints every widget) follows
        p = QPainter(self)
        # no snap_to_pixels until the background is down: it's opaque (nothing is
        # cleared first), and the half-pixel nudge left a one-pixel strip of the old
        # picture at the edge of each repaint, lines behind the cards at 125 %
        # the window's faint glow, fixed to the pads (so a scroll can still copy
        # what's on screen): it lines up with the window at the top of the board
        win, view = self.window(), self.parentWidget()
        root = win.centralWidget() if isinstance(win, QMainWindow) else None
        if root is not None and view is not None:
            at = view.mapTo(root, QPoint(0, 0))
            theme.paint_window_bg(p, e.rect(), QPointF(-at.x(), -at.y()),
                                  root.width(), root.height())
        else:
            p.fillRect(e.rect(), QColor(theme.T["bg"]))
        if self.background_image and self.background_opacity:
            pm = thumbs.pixmap(self.background_image, waiter=self)
            if pm is not None and not pm.isNull():
                # Stretch the whole thumbnail across the visible board, with breathing
                # room beside the scrollbar. Keep it fixed while the cards scroll.
                target = self.background_rect(pm.size())
                clip = QPainterPath()
                clip.addRoundedRect(target, PAD_RADIUS, PAD_RADIUS)
                p.save()
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setClipPath(clip)
                p.setOpacity(self.background_opacity / 100)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.drawPixmap(target, pm, QRectF(pm.rect()))
                p.restore()
        snap_to_pixels(p)
        drop = self.drop_area()
        if drop is not None and drop.intersects(QRectF(e.rect())):
            # the empty room under the pads says what it's for, faintly
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(theme.T["border"]), 1.4)
            p.setPen(pen)
            p.drawRoundedRect(drop, PAD_RADIUS, PAD_RADIUS)
            if self._n_shown:
                p.setPen(QColor(theme.T["faint"]))
                p.drawText(drop, Qt.AlignmentFlag.AlignCenter, self.DROP_HINT)

    def drop_area(self) -> QRectF | None:
        """The same drop box below Bun on an empty board or below the last card row."""
        if not self.pads and not self.empty.isHidden():
            m = self.grid.contentsMargins()
            top = self.empty.y() + self.empty_text.y()
            return QRectF(m.left() + 2, top, self.width() - m.left() - m.right() - 4,
                          self.DROP_HINT_HEIGHT)
        if not self._n_shown or self._shape is None or self.rows():
            return None
        cols, w = self._shape
        m, sp = self.grid.contentsMargins(), self.grid.spacing()
        rows = -(-self._n_shown // cols)
        top = m.top() + rows * (self.pad_h(w) + sp) + 2
        room = self.height() - top - m.bottom() - 4
        if room < 90:
            return None
        # the full width, whatever the pad size: as wide as the pads' columns, it
        # jumped about as Pad size moved
        return QRectF(m.left() + 2, top, self.width() - m.left() - m.right() - 4,
                      min(room, self.DROP_HINT_HEIGHT))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def pad_at(self, pos) -> Pad | None:
        return next((p for p in self.pads if p.isVisible() and p.geometry().contains(pos)),
                    None)

    def focus_step(self, pad: Pad, dx: int, dy: int):
        """Arrow keys on a pad: move the keyboard focus through the grid."""
        shown = [p for p in self.pads if not p.property("filtered")]
        if pad not in shown:
            return
        i = shown.index(pad) + dx + dy * max(1, self._cols)
        if 0 <= i < len(shown):
            shown[i].setFocus(Qt.FocusReason.TabFocusReason)

    def reveal(self, pad: Pad):
        """Scroll the pad with the keyboard focus into view."""
        view = self.parentWidget()
        area = view.parentWidget() if view is not None else None
        if isinstance(area, QScrollArea):
            area.ensureWidgetVisible(pad)

    def _drop_target(self, pos) -> int:
        """Where a dragged pad dropped at ``pos`` goes: the pad under it, else (a gap
        between pads, the margin) the nearest one; below the last row, the end."""
        shown = [(i, p.geometry()) for i, p in enumerate(self.pads) if p.isVisible()]
        if not shown or pos.y() > max(r.bottom() for _i, r in shown):
            return len(self.pads) - 1

        def dist(r) -> int:
            dx = max(r.left() - pos.x(), 0, pos.x() - r.right())
            dy = max(r.top() - pos.y(), 0, pos.y() - r.bottom())
            return dx * dx + dy * dy
        return min(shown, key=lambda ir: dist(ir[1]))[0]

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(PAD_MIME) or md.hasUrls():
            e.acceptProposedAction()
            if md.hasUrls() and not self.pads:
                self.bun.hope(True)

    def dragMoveEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(PAD_MIME) or md.hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.bun.hope(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self.bun.hope(False)
        md = e.mimeData()
        if md.hasFormat(PAD_MIME):
            sid = bytes(md.data(PAD_MIME)).decode()
            pos = e.position().toPoint()
            over = self.pad_at(pos)
            if over is None or over.meta.id != sid:   # back on itself: nothing moved
                self.reorder.emit(sid, self._drop_target(pos))
            e.acceptProposedAction()
        elif md.hasUrls():
            files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            pad = self.pad_at(e.position().toPoint())
            if pad is not None and len(files) == 1 and thumbs.is_image(files[0]):
                self.image_dropped.emit(pad.meta.id, files[0])
                e.acceptProposedAction()
                return
            self.files_dropped.emit(expand_dropped(files))
            e.acceptProposedAction()


def expand_dropped(files: list[str]) -> list[str]:
    """Files dropped from Explorer, with folders opened up into the sound files (and zips)
    in them. An unzipped backup / sound pack folder is kept whole (see backup.py)."""
    expanded = []
    for f in files:
        pth = Path(f)
        if pth.is_dir() and any((pth / n).is_file() for n in ("onionboard.json", "sound.json")):
            expanded.append(f)
        elif pth.is_dir():
            expanded += [str(x) for x in sorted(pth.rglob("*"))
                         if x.is_file() and x.suffix.lower() in AUDIO_EXTS | {".zip"}]
        else:
            expanded.append(f)
    return expanded
