"""The app's icon set: simple line icons painted on a 24-unit grid.

Painted (not image files) so they're crisp at any DPI and take the current theme's
colours. `set_icon(widget, name)` applies an icon and remembers it, so `retheme()`
can repaint every icon after a theme switch. A checkable button gets a second,
on-accent colour for its checked state.
"""
from __future__ import annotations

import math
import weakref

import shiboken6

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontInfo, QFontMetricsF, QIcon, QIconEngine, QImage,
                           QPainter, QPainterPath, QPen, QPixmap, QTextDocument)

from soundboard.ui.kit import theme
from soundboard.ui.kit.iconshapes import SHAPES

SIZES = (16, 20, 24, 32, 48)


# --------------------------------------------------------------------------- painting

def pixmap(name: str, size: int, color: str, dy: float = 0.0) -> QPixmap:
    """`dy`: drawn that fraction of a pixel lower, in a picture a pixel taller (to put
    a picture's middle on a line between two screen pixels: SettingsDialog's heading)."""
    pm = QPixmap(size, size + (1 if dy else 0))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(0, dy)
    p.scale(size / 24, size / 24)
    col = QColor(color)
    pen = QPen(col, 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def fill(path: QPainterPath, build=None):
        if build is not None:
            build(path)
        p.fillPath(path, col)

    SHAPES[name](p, fill)
    p.end()
    return pm


class SharpEngine(QIconEngine):
    """Draws the picture at exactly the size and screen scale it's shown at.

    Pixmaps made ahead of time at a few sizes (16, 20, 24...) get shrunk to the
    18 / 14 / 12 px the app asks for, and to 22 / 18 / 15 px on a 125 % screen,
    which blurs thin lines. This draws each size the first time it's needed, once.
    `draw(px, mode, state)` returns a `px`-pixel square QPixmap. `pad`: empty pixels
    after it, so a button's words sit TEXT_GAP from its icon (Qt's own gap is 4 px)."""

    def __init__(self, draw, pad: int = 0):
        super().__init__()
        self._draw = draw
        self._pad = pad
        self._made: dict[tuple, QPixmap] = {}

    def _get(self, px: int, mode, state) -> QPixmap:
        key = (px, mode, state)
        pm = self._made.get(key)
        if pm is None:
            pm = self._made[key] = self._draw(px, mode, state)
        return pm

    def scaledPixmap(self, size, mode, state, scale):
        side = max(1, min(size.width() - self._pad, size.height()))
        pm = QPixmap(self._get(max(1, round(side * scale)), mode, state))
        if self._pad:
            wide = QPixmap(round((side + self._pad) * scale), pm.height())
            wide.fill(Qt.GlobalColor.transparent)
            p = QPainter(wide)
            p.drawPixmap(0, 0, pm)
            p.end()
            pm = wide
        pm.setDevicePixelRatio(scale)
        return pm

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1.0)

    def paint(self, painter, rect, mode, state):
        scale = painter.device().devicePixelRatioF() if painter.device() else 1.0
        painter.drawPixmap(rect, self.scaledPixmap(rect.size(), mode, state, scale))

    def actualSize(self, size, mode, state):
        side = min(size.width() - self._pad, size.height())
        return QSize(side + self._pad, side)

    def availableSizes(self, mode=QIcon.Mode.Normal, state=QIcon.State.Off):
        return [QSize(s, s) for s in SIZES]

    def clone(self):
        # a copy (QIcon detaching, e.g. on addPixmap, which this engine ignores): Qt
        # deletes it, but PySide drops the Python side as soon as this returns, so
        # keep it here (rare: the app never adds pixmaps to these icons)
        c = SharpEngine(self._draw, self._pad)
        _clones.append(c)
        return c

    def key(self):
        return "onionboard-sharp"


_clones: list[SharpEngine] = []


def sharp_icon(draw) -> QIcon:
    """A QIcon drawn by `draw(px, mode, state) -> QPixmap` at the exact size shown."""
    return QIcon(SharpEngine(draw))   # the QIcon owns the engine


_cache: dict[tuple, QIcon] = {}


def resolve(c: str) -> str:
    """A theme token's colour (a literal colour as it is)."""
    # an icon is drawn on the window or a card, never on an accent fill (that's
    # on_accent): the accent's readable shade there (Flashbang's yellow on white)
    return theme.T.get("accent_text" if c == "accent" else c, c)


def icon(name: str, color: str | None = None, checked_color: str | None = None,
         selected: str = "accent", pad: int = 0) -> QIcon:
    """`color`/`checked_color` are theme token names (e.g. "text", "on_accent") or
    literal colours ("#ff4d4f"). `selected` colours the current tab / a highlighted
    list item (accent, not Qt's washed-out tint)."""
    normal = resolve(color or "text")
    on = resolve(checked_color or "on_accent")
    sel = resolve(selected)
    muted = resolve("muted")
    key = (name, normal, on, sel, pad)
    if key not in _cache:
        def draw(px, mode, state):
            if mode == QIcon.Mode.Disabled:
                col = muted
            elif state == QIcon.State.On:
                col = on
            elif mode == QIcon.Mode.Selected:
                col = sel
            else:
                col = normal
            return pixmap(name, px, col)
        _cache[key] = QIcon(SharpEngine(draw, pad))
    return _cache[key]


# --------------------------------------------------------------------------- live retheme

def _gone(ref: weakref.ref) -> bool:
    """The widget an entry below is for was deleted (its Python side may still be
    around, pointing at nothing)."""
    w = ref()
    return w is None or not shiboken6.isValid(w)


# the widgets given a live icon, one entry each, gone with the widget's Python side:
# looked up by widget, since a list scanned on every call (and every retheme step)
# froze a big board (thousands of buttons) for seconds
_applied: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()   # -> (name, color, checked, pad)

# icon to words on a button, the same everywhere (DESIGN.md: 6-8 px); Qt puts 4 px
TEXT_GAP = 8
_tabs: list[tuple[weakref.ref, int, str, str | None, bool]] = []


def set_icon(widget, name: str, color: str | None = None, checked_color: str | None = None,
             size: int = 18, gap: bool = True):
    """Give a button or menu action (anything with setIcon) an icon that follows theme
    changes. A button with words gets TEXT_GAP between the icon and them; `gap=False`
    for one lined up on its own icon column (the sidebar's)."""
    if not gap:
        widget.setProperty("noTextGap", True)
    has_text = (hasattr(widget, "setIconSize") and not widget.property("noTextGap")
                and bool(getattr(widget, "text", str)()))
    pad = TEXT_GAP - 4 if has_text else 0
    widget.setIcon(icon(name, color, checked_color, pad=pad))
    if hasattr(widget, "setIconSize"):   # a QAction takes its menu's size
        widget.setIconSize(QSize(size + pad, size))
    _applied[widget] = (name, color, checked_color, pad)


def close_button(btn, side: int, color: str = "muted"):
    """Make `btn` a square ✕ button drawn with the painted "close" icon, never the "✕"
    character: a font's glyph got clipped by small buttons' padding, and a layout could
    squeeze it (a style sheet's min-width:0). Its tooltip names it (a11y.label_tree)."""
    from PySide6.QtWidgets import QSizePolicy
    btn.setText("")
    set_icon(btn, "close", color, size=16 if side >= 22 else 14)
    btn.setFixedSize(side, side)
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)


def clear_button(edit, color: str = "muted"):
    """Turn on a line edit's clear button, drawn with the painted "close" icon: Qt's
    own grey disc only comes at 16/32 px, so at 125 % scaling it was squashed to 20 and
    sat off-centre (blurred, half a pixel low)."""
    from PySide6.QtGui import QAction
    edit.setClearButtonEnabled(True)
    act = edit.findChild(QAction, "_q_qlineeditclearaction")
    if act is not None:
        set_icon(act, "close", color)


def text_gap(button):
    """Re-fit the icon's gap after a button's words were dropped or put back (a
    narrow window's icon-only step): no words, no empty space after the icon."""
    if (e := _applied.get(button)) is not None:
        name, color, checked, __ = e
        set_icon(button, name, color, checked, button.iconSize().height())


def recolor(button, color: str | None):
    """The same icon in another colour: a button that turned into the filled main one
    (on_accent) or back (None: the text colour). Its old colour would sit on the new fill."""
    if (e := _applied.get(button)) is not None and e[1] != color:
        set_icon(button, e[0], color, e[2], button.iconSize().height())


_labels: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()   # -> (name, color, size)


_inline: dict[tuple, str] = {}


def _mark(name: str, px: int, color: str) -> QPixmap:
    """A status tick or cross in a circle, drawn on the pixel grid at `px` pixels.
    The 24-unit icons scaled to 16 px get 1.3 px lines that fall between pixels and
    come out thin and fuzzy; this one's lines are a whole number of pixels wide and
    its circle's edges sit on pixel boundaries, so it's solid and smooth."""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w = max(1, round(px / 8))   # 2 px at 16 px, like bold text
    pen = QPen(QColor(color), w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    c = px / 2
    r = c - w / 2 - 0.5
    # the stroke's edges (r +- w/2 from the centre) on whole pixels
    r = math.floor(c + r + w / 2) - w / 2 - c
    p.drawEllipse(QPointF(c, c), r, r)
    k = px / 24
    if name == "check":
        p.drawPolyline([QPointF(c - 4 * k, c + 0.5 * k), QPointF(c - 1 * k, c + 3.5 * k),
                        QPointF(c + 4.5 * k, c - 3 * k)])
    else:
        d = r * 0.42
        p.drawLine(QPointF(c - d, c - d), QPointF(c + d, c + d))
        p.drawLine(QPointF(c + d, c - d), QPointF(c - d, c + d))
    p.end()
    return pm


_INLINE_GAP = 3   # clear space either side of an inline mark, so it isn't on the words
_lift: dict[tuple, int] = {}


def _inked_rows(img: QImage, x0: int, x1: int) -> list[int]:
    """The rows of `img` with something drawn between columns x0 and x1."""
    return [y for y in range(img.height())
            if any(img.pixelColor(x, y).alpha() > 128 for x in range(x0, x1))]


def _mark_lift(font: QFont, size: int) -> int:
    """How many pixels of empty space under a `size` px inline mark put its middle level
    with the middle of `font`'s capitals. Rich text's "vertical-align: middle" centres
    an image on the font's own box, which sits lower in some fonts than others
    (Bahnschrift, the default, dropped the tick 4 px under its words), so it's measured:
    "H" and the mark laid out together, once per font. The key holds the font Qt
    really draws with and its measures, not only the name asked for: a name can stand
    for another font later (one added or removed while the app runs, a fallback)."""
    fm = QFontMetricsF(font)
    key = (font.key(), QFontInfo(font).family(), fm.ascent(), fm.descent(), size)
    if key in _lift:
        return _lift[key]
    cap = fm.horizontalAdvance("H")
    best, best_off = 0, None
    for pad in range(size):
        pm = QPixmap(size, size + pad)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.fillRect(0, 0, size, size, QColor("black"))
        p.end()
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setDocumentMargin(0)
        doc.addResource(QTextDocument.ResourceType.ImageResource, "mark:", pm)
        doc.setHtml(f"H&nbsp;<img src='mark:' width='{size}' height='{size + pad}' "
                    "style='vertical-align: middle'>")
        img = QImage(doc.size().toSize(), QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        doc.drawContents(p)
        p.end()
        split = math.ceil(cap)
        h, m = _inked_rows(img, 0, split), _inked_rows(img, split + 1, img.width())
        if not h or not m:
            break
        off = abs((m[0] + m[-1]) - (h[0] + h[-1]))
        if best_off is None or off < best_off:
            best, best_off = pad, off
        elif off > best_off:   # past the best: it only gets worse from here
            break
    _lift[key] = best
    return best


def inline(name: str, color: str, size: int = 16, dpr: float = 1.0,
           font: QFont | None = None) -> str:
    """A status mark ("check" or "cross") inside rich text, as an <img>.
    Drawn at exactly the screen pixels it fills (`size` x the label's
    devicePixelRatioF): rich text scales an image without smoothing, so one drawn
    bigger and shrunk came out jagged. `color` is a real colour (theme.status(...)),
    so a redraw after a theme change picks up the new one. `font`: the label's, so
    the mark sits level with its words (see _mark_lift) with a little space each side."""
    lift = _mark_lift(font, size) if font is not None else 0
    gap = _INLINE_GAP if font is not None else 0
    px = max(1, round(size * dpr))
    key = (name, color, px, lift, gap)
    if key not in _inline:
        w, h = size + 2 * gap, size + lift
        pm = QPixmap(round(w * dpr), round(h * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.drawPixmap(round(gap * dpr), 0, _mark(name, px, color))
        p.end()
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        pm.save(buf, "PNG")
        src = bytes(data.toBase64().data()).decode()
        _inline[key] = (f"<img src='data:image/png;base64,{src}' width='{w:g}' "
                        f"height='{h:g}' style='vertical-align: middle'>")
    return _inline[key]


def set_label_icon(label, name: str, color: str = "muted", size: int = 18):
    """Show an icon in a QLabel (as its pixmap) that follows theme changes."""
    dpr = label.devicePixelRatioF() or 1.0
    pm = icon(name, color).pixmap(QSize(size, size), dpr)
    label.setPixmap(pm)
    # one entry per label, and none for deleted ones: a dialog's labels went on the
    # list each time it was opened
    _labels[label] = (name, color, size)


_items: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()   # combo -> names


def set_item_icons(combo, names: list[str]):
    """Icons for a combo box's items, in order, that follow theme changes ("" for a
    divider: no icon)."""
    for i, name in enumerate(names):
        if name:
            combo.setItemIcon(i, icon(name))
    _items[combo] = names


_tab_cache: dict[tuple, QIcon] = {}


def _tab_icon(name: str, tint: str | None, badge: bool = False) -> QIcon:
    """A tab's icon, kept: the live tabs are re-iconed on every sound start and stop,
    and a badged one paints 40 pictures."""
    key = (name, theme.T.get(tint, tint) if tint else None, badge, theme.T["live_text"],
           theme.T["muted"], theme.T["accent"])
    if key not in _tab_cache:
        _tab_cache[key] = _make_tab_icon(name, tint, badge)
    return _tab_cache[key]


def _make_tab_icon(name: str, tint: str | None, badge: bool = False) -> QIcon:
    if name.startswith("art:"):   # a picture (ui/voice/art.py): its own colours, whatever the tint
        from soundboard.ui.voice import art
        ic = art.icon(name[4:]) or QIcon()
    elif tint is None:
        ic = icon(name, "muted", "accent")
    else:
        col = theme.T.get(tint, tint)   # one colour whatever the tab's state (e.g. live)
        ic = sharp_icon(lambda px, _mode, _state: pixmap(name, px, col))
    return _with_badge(ic) if badge and not ic.isNull() else ic


def _with_badge(ic: QIcon) -> QIcon:
    """`ic` with a small "live" dot on its top-right corner, cut out of the picture by
    a thin gap so it reads on any background. Drawn into the icon itself, so the
    tab it's on keeps its size."""
    color = QColor(theme.T["live_text"])

    def draw(s, mode, state):
        r = s * 0.2
        gap = max(1.0, s / 12)
        c = QPointF(s - r, r)
        # Paint both the glyph and badge at the requested physical pixel size.
        pm = QPixmap(ic.pixmap(QSize(s, s), 1.0, mode, state))
        pm.setDevicePixelRatio(1.0)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.setBrush(Qt.GlobalColor.black)
        p.drawEllipse(c, r + gap, r + gap)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setBrush(color)
        p.drawEllipse(c, r, r)
        p.end()
        return pm

    return sharp_icon(draw)


def set_tab_icon(tabs, index: int, name: str, tint: str | None = None, badge: bool = False):
    """`tint` colours the icon in every state; None is the usual muted / accent.
    "art:<key>" shows that picture from ui/voice/art.py instead of a painted icon. `badge`
    adds the small "live" dot."""
    # on the bar itself: QTabWidget.setTabIcon also lays the whole widget out again and
    # repaints every page under it (the live badge did that to the whole board each
    # time a sound started or stopped); the bar asks for a layout only if it changed
    # size, and widgets.SteadyTabs lets that through
    tabs.tabBar().setTabIcon(index, _tab_icon(name, tint, badge))
    # ...and none for deleted tab widgets: Settings' tabs added 12 each time it opened
    _tabs[:] = [e for e in _tabs if not _gone(e[0]) and not (e[0]() is tabs and e[1] == index)]
    _tabs.append((weakref.ref(tabs), index, name, tint, badge))
    changed = getattr(tabs, "changed", None)   # a tab widget shown elsewhere (ui/window/sidebar.py)
    if changed is not None:
        changed.emit()


def tab_icon_name(tabs, index: int) -> str | None:
    """The icon name a tab was last given with set_tab_icon, or None."""
    for ref, i, name, _tint, _badge in _tabs:
        if ref() is tabs and i == index:
            return name
    return None


LIVE_TOKENS = {"live_text", "on_live", "live"}   # the tokens a live-colour change moves


def retheme_live():
    """Re-draw only the icons in the live colour (a live tab's, the mic pill's) or on it
    (a switched-on button's, in on_live) after the user picks a new one: retheme()
    re-draws every icon in the app."""
    for w, (name, color, checked, pad) in list(_applied.items()):
        if {color, checked} & LIVE_TOKENS:
            try:
                w.setIcon(icon(name, color, checked, pad=pad))
            except RuntimeError:   # the C++ widget is gone
                pass
    for ref, index, name, tint, badge in _tabs:
        t = ref()
        if t is not None and (tint == "live_text" or badge):
            try:
                t.setTabIcon(index, _tab_icon(name, tint, badge))
            except RuntimeError:
                pass


def retheme():
    _cache.clear()
    _tab_cache.clear()
    for w, (name, color, checked, pad) in list(_applied.items()):
        try:
            w.setIcon(icon(name, color, checked, pad=pad))
        except RuntimeError:   # the C++ widget is gone
            _applied.pop(w, None)
    for combo, names in list(_items.items()):
        try:
            set_item_icons(combo, names)
        except RuntimeError:   # the C++ widget is gone
            _items.pop(combo, None)
    for lbl, (name, color, size) in list(_labels.items()):
        try:
            set_label_icon(lbl, name, color, size)
        except RuntimeError:
            _labels.pop(lbl, None)
    for ref, index, name, tint, badge in _tabs:
        t = ref()
        if t is not None:
            try:
                t.setTabIcon(index, _tab_icon(name, tint, badge))
            except RuntimeError:
                pass
