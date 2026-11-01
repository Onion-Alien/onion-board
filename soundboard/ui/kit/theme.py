"""Colour themes: the current theme's colours, the app style sheet built from them, and
how a theme switch restyles the open windows (the sheet's text is in themesheet.py, the
pictures it draws controls with in indicators.py, the logo in logo.py).

A theme is a set of named colour tokens. The Qt stylesheet is built from them, and
the hand-painted widgets (pads, meters, EQ curve, logo) read the same tokens through
`T` when they paint, so switching theme recolours everything live.
"""
from __future__ import annotations

import datetime
import re
import time
from contextlib import contextmanager

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import (QColor, QPainter)

from soundboard.i18n import _
from soundboard.style import hooks, palettes, textures
from soundboard.ui.settings import lite
# the colours and textures are in the style kit, shared with Onion Watch
from soundboard.style.palettes import (DEFAULT, FONT, GROUPS, LIMITED, LIVE_NAMES,  # noqa: F401
                                       LIVE_STYLE, TEXT_ON, THEMES, _add_live_tokens, _contrast,
                                       _mix, font_families, is_light_colour, mix, valid_colour)
from soundboard.style.textures import (AURORA, TEXTURE_TILE, TEXTURES, texture_image)  # noqa: F401
from soundboard.ui.kit.themesheet import (OUTLINE_STYLE, POLISH_STYLE, STYLE)  # noqa: F401
from soundboard.ui.kit.indicators import _check_url, _chevron_url, _radio_url
from soundboard.ui.kit.logo import (BRAND, ICON_INSET, app_icon, logo_image,  # noqa: F401
                                    logo_pixmap, paint_logo)


def group_name(group: str) -> str:
    """A GROUPS key as Settings shows it, in the language picked (the keys stay
    English; a function: this module can be imported before the language is)."""
    return {"Classic": _("Classic"), "Colourful": _("Colourful"), "Wild": _("Wild"),
            "Meme": _("Meme")}.get(group, group)


kept: set[str] = set()   # limited-edition themes this user picked in time (Config.kept_themes)


def _today() -> datetime.date:
    return datetime.date.today()   # (the tests pin it inside every offer)


def on_offer(name: str, today: datetime.date | None = None) -> bool:
    """Whether limited-edition theme `name` can still be picked by anyone (False for an
    everyday theme: it has no offer to end)."""
    return name in LIMITED and (today or _today()) <= LIMITED[name]


def offered(name: str, today: datetime.date | None = None) -> bool:
    """Whether theme `name` is in this user's list: every everyday theme, and a limited
    one while it's on offer or once they've kept it."""
    return name in THEMES and (name not in LIMITED or name in kept or on_offer(name, today))


def keep(name: str, today: datetime.date | None = None) -> bool:
    """Theme `name` was used: a limited one still on offer is the user's for good.
    True when that's new (the caller saves `kept`)."""
    if name in kept or not on_offer(name, today):
        return False
    kept.add(name)
    return True


def groups(today: datetime.date | None = None) -> list[tuple[str, list[str]]]:
    """GROUPS as this user's Settings shows them: limited themes gone once missed."""
    return [(g, [n for n in names if offered(n, today)]) for g, names in GROUPS]


T: dict[str, str] = dict(THEMES[DEFAULT])   # current theme (read at paint time)
current_name = DEFAULT
live_override = ""   # the user's own highlight colour ("" = each theme's own)
textures_on = True  # Settings > Appearance: Textured (each theme's pattern, the default) or Plain
# what the style kit (Bun's outfit, Hoot, the textures) paints in; Hoot holds still in
# lite mode
hooks.connect(palette=lambda: T, theme_name=lambda: current_name, tr=_, still=lite.on)


def tokens(name: str | None = None) -> dict[str, str]:
    """Theme `name`'s colours (default: the current one), with the user's own highlight
    colour if they picked one."""
    t = dict(THEMES.get(name or current_name, THEMES[DEFAULT]))
    if live_override:
        _add_live_tokens(t, live_override)
    return t


def set_live(colour: str) -> str:
    """Use `colour` for the live highlight in every theme ("" = back to each theme's
    own). Takes effect on the next apply(). Returns what was kept."""
    global live_override
    live_override = valid_colour(colour)
    return live_override


def status(kind: str) -> str:
    """The current theme's colour for an inline "ok", "warn" or "error" message. The
    bright green / amber / red of the dark themes can't be read on the light ones."""
    return T[f"{kind}_text"]


def set_tone(label, kind: str = "") -> None:
    """Colour a label as an "ok", "warn" or "error" message ("" = normal) in a way that
    follows theme changes (the stylesheet's [tone] rules)."""
    if label.property("tone") != kind:
        label.setProperty("tone", kind)
        label.style().unpolish(label)
        label.style().polish(label)


def set_current(name: str) -> str:
    global current_name
    name = name if offered(name) else DEFAULT
    current_name = name
    T.clear()
    T.update(tokens(name))
    return name


@contextmanager
def previewing(name: str):
    """Theme `name` in `T` for the block, then the current one back: paints something
    (Bun on the theme-change cover) in a theme before apply() has switched to it."""
    global current_name
    was, colours = current_name, dict(T)
    set_current(name)
    try:
        yield
    finally:
        current_name = was
        T.clear()
        T.update(colours)


def live_sheet() -> str:
    """The live rules in the current colours, as a widget's own stylesheet (the style
    kit's palettes.live_sheet)."""
    return palettes.live_sheet(T)


def _rgba(colour: str, alpha: float) -> str:
    c = QColor(colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {round(alpha * 255)})"


def polish_tokens(tk: dict[str, str], light: bool) -> dict[str, str]:
    """The extra shades POLISH_STYLE paints with, from theme tokens `tk`."""
    panel = tk["panel"]
    return dict(
        tk,
        surface_border=_mix(panel, tk["border"], 0.55),
        edge=_mix(panel, tk["border"], 0.55),
        glass=_rgba(panel, 0.86),
        **_accent_shades(tk),
    )


def _accent_shades(tk: dict[str, str]) -> dict[str, str]:
    """A filled accent button's gradient: lit top-left corner, the accent, then a blend
    into the theme's second colour (accent2) at the bottom-right, with a light rim on
    top. Every shade keeps the button's text as readable as on the plain accent (4.5:1,
    or the accent's own ratio when that's lower): the lit corner lightens less, and the
    blend's end is deepened (away from the text colour) until the text reads."""
    on = tk["on_accent"]
    white, black = "#ffffff", "#000000"
    away = black if _contrast(on, black) > _contrast(on, white) else white

    def lit(base: str) -> str:
        need = min(4.5, _contrast(on, base))
        return next((c for c in (_mix(base, white, 0.2 * (10 - i) / 10) for i in range(11))
                     if _contrast(on, c) >= need), base)

    def blend(base: str) -> str:
        need = min(4.5, _contrast(on, base))
        mixed = _mix(base, tk["accent2"], 0.35)
        return next((c for c in (_mix(mixed, away, i / 20) for i in range(15))
                     if _contrast(on, c) >= need), _mix(mixed, away, 0.7))

    return dict(
        accent_top=lit(tk["accent"]),
        accent_top_hi=lit(tk["accent_hover"]),
        accent_end=blend(tk["accent"]),
        accent_end_hi=blend(tk["accent_hover"]),
        accent_press=_mix(tk["accent"], black, 0.15),
        accent_rim=_rgba(white, 0.30),
        accent_rim_side=_rgba(_mix(tk["accent"], black, 0.25), 0.55),
    )


def accent_fill(hover: bool = False) -> str:
    """A filled accent button's background as a stylesheet value, for widgets that style
    themselves: the same gradient as `#primary`, or the flat accent in outlined themes."""
    if not polished():
        return T["accent_hover" if hover else "accent"]
    s = _accent_shades(T)
    top, mid, end = ((s["accent_top_hi"], T["accent_hover"], s["accent_end_hi"]) if hover
                     else (s["accent_top"], T["accent"], s["accent_end"]))
    return (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {top}, stop:0.3 {mid}, "
            f"stop:1 {end})")


def accent_edge() -> str:
    """The border that goes with accent_fill(): a light rim on top (stylesheet text)."""
    if not polished():
        return f"border:1px solid {T['accent']};"
    s = _accent_shades(T)
    return f"border:1px solid {s['accent_rim_side']}; border-top-color:{s['accent_rim']};"


def polished(name: str | None = None) -> bool:
    """Whether theme `name` (default: the current one) gets POLISH_STYLE's depth."""
    return (name or current_name) not in OUTLINED


def paint_window_bg(p: QPainter, rect, origin: QPointF, width: float, height: float,
                    tk: dict[str, str] | None = None, textured: bool | None = None) -> None:
    """Paint the window background, aligned to its origin, without disk access: the flat
    page colour, or with Textured on, the theme's soft accent glow over it (the style
    kit's textures.paint_glow). `tk`: a theme other than the current one (a preview).
    Opaque widgets use this same background so scrolling leaves no seams."""
    tk = T if tk is None else tk
    textured = textures_on if textured is None else textured
    p.fillRect(rect, QColor(tk["bg"]))
    if not textured or (tk is T and not polished()):
        return
    textures.paint_glow(p, rect, origin, width, height, tk)


_shift_turn = 0


def vary_texture(card) -> None:
    """Start `card`'s texture somewhere else than the card made before it
    (textures.SHIFTS), so cards next to each other don't show it lined up."""
    global _shift_turn
    _shift_turn = (_shift_turn + 1) % len(textures.SHIFTS)
    card.setProperty("texshift", _shift_turn)


def texture_style(selector: str, tk: dict[str, str] | None = None) -> str:
    """Apply the active tiling texture to a surface, including locally styled panels
    ("" with Textured off)."""
    return textures.texture_style(selector, T if tk is None else tk) if textures_on else ""


# Themes whose controls and cards keep an outline at rest: the others draw buttons,
# boxes and cards as flat fills, which in High Contrast (black on black) vanish.
OUTLINED = {"High Contrast"}


def is_light(name: str | None = None) -> bool:
    """Whether theme `name` (default: the current one) has a light background."""
    c = QColor(THEMES.get(name or current_name, THEMES[DEFAULT])["bg"])
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 140


def stand_out(base: str, towards: tuple[str, ...], need: float,
              tk: dict[str, str]) -> str:
    """`base` moved towards the first of `towards` that gets there until it stands out
    from `base` by `need`:1 while text_hi still reads on it (4.5:1)."""
    return next((c for c in (_mix(base, to, i / 50) for to in towards for i in range(2, 30))
                 if _contrast(c, base) >= need and _contrast(c, tk["text_hi"]) >= 4.5),
                _mix(base, tk["text"], 0.25))


def rail_bg(tk: dict[str, str], outlined: bool) -> str:
    """The side rail's colour: the window's with a little of the panel's in it."""
    return tk["panel"] if outlined else _mix(tk["bg"], tk["panel"], 0.18)


def rail_tint() -> tuple[str, float]:
    """The rail's current tab's fill: the accent at a soft 16% where that shows, more
    where it would vanish, and the darker accent_text where even that can't (Flashbang's
    yellow on white was 1.07:1). (colour, alpha)"""
    base = rail_bg(T, current_name in OUTLINED)
    for key in ("accent", "accent_text"):
        for a in range(16, 52, 2):
            if _contrast(_mix(base, T[key], a / 100), base) >= 1.3:
                return T[key], a / 100
    return T["accent_text"], 0.5


def stylesheet(name: str | None = None) -> str:
    tk = tokens(name)
    tk.setdefault("font", FONT)
    outlined = (name or current_name) in OUTLINED
    # Navigation belongs to the window background, with a quiet inner edge.
    # Outlined themes keep their deliberate surface and strong divider.
    tk["rail_bg"] = rail_bg(tk, outlined)
    tk["rail_border"] = tk["border"] if outlined else _mix(tk["bg"], tk["border"], 0.35)
    # card titles in the text colour; High Contrast keeps its yellow to scan by
    tk["heading"] = tk["section"] if outlined else tk["text_hi"]
    # a nudged button (DESIGN *Buttons*): a soft wash of the accent behind its edge
    # the Settings list's page you're on, on the window: card_hi was 1.03:1 there in
    # the light themes (Paper, Light: no visible mark). A theme whose own colour stood
    # out more already keeps it (Swamp, Deep Fried, Retro 98). 1.6 on the token, as the
    # window's finish shades both a little: 1.5 measured 1.42:1 as drawn in Paper.
    tk["nav_sel"] = max((stand_out(tk["bg"], (tk["accent"], tk["text"]), 1.6, tk),
                         tk["card_hi"]), key=lambda c: _contrast(c, tk["bg"]))
    tk["box_hover"] = _rgba(tk["text_hi"], 0.07)   # a hovered box in a card
    tk["accent_tint"] = _rgba(tk["accent"], 0.30)
    tk["accent_tint_hi"] = _rgba(tk["accent"], 0.42)
    tk["check"] = _check_url(tk["on_accent"])
    tk["check_off"] = _check_url(tk["muted"])   # ticked but greyed out: on $inset
    tk["radio"] = _radio_url(tk["off"], tk["card"])
    tk["radio_hover"] = _radio_url(tk["border_hi"], tk["card"])
    tk["radio_on"] = _radio_url(tk["accent"], tk["accent"], tk["on_accent"])
    tk["radio_on_hover"] = _radio_url(tk["accent_hi"], tk["accent_hi"], tk["on_accent"])
    tk["radio_off"] = _radio_url(tk["border"], tk["inset"])
    tk["radio_on_off"] = _radio_url(tk["border"], tk["inset"], tk["muted"])
    for key, colour in (("", tk["muted"]), ("_off", tk["off"])):
        tk["down" + key] = _chevron_url(colour, 10, up=False)
        tk["up" + key] = _chevron_url(colour, 10, up=True)
        tk["down_small" + key] = _chevron_url(colour, 8, up=False)
        tk["up_small" + key] = _chevron_url(colour, 8, up=True)
        tk["left" + key] = _chevron_url(colour, 10, False, side="left")
        tk["right" + key] = _chevron_url(colour, 10, False, side="right")
    css = STYLE.substitute(tk)
    if outlined:
        css += OUTLINE_STYLE.substitute(tk)
    else:
        css += POLISH_STYLE.substitute(polish_tokens(tk, is_light(name)))
    css += texture_style("QFrame#card, QFrame#setcard, QFrame#fxcard, QFrame#transport, "
                         "QDialog#transport, QFrame#deck", tk)
    return css + held_rings(css)


_FOCUS_RULE = re.compile(r"([^{}]*:focus[^{}]*)\{([^{}]*)\}")
_HELD = (("QPushButton", ":pressed"), ("QToolButton", ":pressed"), ("QComboBox", ":on"),
         ("QSlider", ":pressed"), ("QCheckBox", ":pressed"), ("QRadioButton", ":pressed"))


def held_rings(css: str) -> str:
    """Click controls take the focus from the Tab key only (widgets.click_focus),
    so their :focus ring is the keyboard's. A mouse gets the same ring while it holds
    the control down (a drop-down or a button's menu: while it's open), gone as it
    lets go: every :focus rule again as :pressed (:on for a drop-down)."""
    out = []
    for m in _FOCUS_RULE.finditer(css):
        sels = []
        for sel in m.group(1).split(","):
            sel = sel.strip()
            kind = next((h for k, h in _HELD if k in sel), None)
            if kind and ":focus" in sel:
                sels.append(sel.replace(":focus", kind))
        if sels:
            out.append(", ".join(sels) + " {" + m.group(2) + "}")
    return "\n" + "\n".join(out) + "\n" if out else ""


# Text colours code writes straight into a label's rich text or a widget's own stylesheet
# (status(), T["faint"]...): a live theme switch swaps the old theme's for the new one's.
_INLINE_KEYS = ("ok_text", "warn_text", "error_text", "danger_text", "text", "text_hi",
                "muted", "faint", "section", "accent", "accent_hi", "live_text", "accent_text",
                "accent_link")
_TEXT_COLOUR = re.compile(r"(?<![-\w])(color:\s*)(#[0-9a-fA-F]{6})(?![0-9a-fA-F])")


def _recolour_inline(widgets, old: dict[str, str]) -> None:
    """Only `color:` (text), never backgrounds or borders: those can be a sound's own
    colour that merely matches a token.

    Two tokens can share a hex in the old theme and part in the new one; the text
    doesn't say which token wrote it, so that hex goes to the new colour most of those
    tokens agree on, a tie to the one listed first in _INLINE_KEYS (the same result
    every time, whatever order the themes list their tokens in)."""
    votes: dict[str, dict[str, int]] = {}
    for k in _INLINE_KEYS:
        if k in old and k in T:
            new = votes.setdefault(old[k].lower(), {})
            new[T[k]] = new.get(T[k], 0) + 1
    # max() keeps the first of equal counts, and dicts keep _INLINE_KEYS order
    swap = {a: max(c, key=lambda k, c=c: c[k]) for a, c in votes.items()}
    swap = {a: b for a, b in swap.items() if a != b.lower()}
    if not swap:
        return

    def sub(text: str) -> str:
        return _TEXT_COLOUR.sub(lambda m: m[1] + swap.get(m[2].lower(), m[2]), text)
    for w in widgets:
        try:
            css = w.styleSheet()
            if "color" in css and (new := sub(css)) != css:
                w.setStyleSheet(new)
            if not hasattr(w, "textFormat"):   # QLabel: its rich text
                continue
            text = w.text()
            if "color" in text and (new := sub(text)) != text:
                w.setText(new)
        except RuntimeError:   # being deleted
            pass


def _style_when_shown(app, closed: list | None = None) -> list:
    """Leave the app's closed windows (Edit voice, Live controls, a menu: a few hundred
    widgets never shown yet) out of the next restyle: Qt restyles only the widgets it
    has polished, and a widget not polished is polished in the sheet of the day when
    it's shown. A third of a theme switch, which froze the app on slower PCs. Only
    windows with an owner: the main window hidden in the tray restyles as before.
    Returns the widgets in them with a sheet of their own (_own_sheets_again);
    `closed` gets the windows."""
    from PySide6.QtWidgets import QWidget
    polished = Qt.WidgetAttribute.WA_WState_Polished
    own = []
    for top in app.topLevelWidgets():
        if top.isVisible() or top.parentWidget() is None:
            continue
        if closed is not None:
            closed.append(top)
        # one under an owner with its own sheet (Live controls' button, lit) takes
        # its style from there, so it counts as having one
        inherits = any(p.styleSheet() for p in _owners(top))
        for w in (top, *top.findChildren(QWidget)):
            w.setAttribute(polished, False)
            if w.styleSheet() or (inherits and w is top):
                own.append(w)
    return own


def _owners(w):
    p = w.parentWidget()
    while p is not None:
        yield p
        p = p.parentWidget()


def _own_sheets_again(own: list) -> None:
    """A widget with its own sheet (and all under it) keeps a style of its own, made
    from the app sheet of the day it was set: skipped by the restyle, it stayed on the
    plain one the restyle clears to first, so a closed Live controls opened with bare
    Windows sliders and boxes until a change re-set its button's sheet. Setting each
    sheet again makes those styles anew from the new app sheet (cheap while they're
    not polished: nothing is polished until it's shown)."""
    for w in own:
        try:
            sheet = w.styleSheet()
            w.setStyleSheet("" if sheet else " ")
            w.setStyleSheet(sheet)
        except RuntimeError:   # being deleted
            pass


def _hidden_parts(app) -> list:
    """The hidden parts of the open windows (the other tabs, Settings' other pages, a
    closed panel): each the topmost hidden widget under a widget on screen. Most of a
    window is in them (~1400 of ~1500 styled widgets on a full board)."""
    from PySide6.QtWidgets import QWidget
    direct = Qt.FindChildOption.FindDirectChildrenOnly
    parts, on = [], [w for w in app.topLevelWidgets() if w.isVisible()]
    while on:
        for c in on.pop().findChildren(QWidget, options=direct):
            if not c.isWindow():   # (a window of its own: closed, or on screen)
                (on if c.isVisible() else parts).append(c)
    return parts


_HELD_BACK = (QEvent.Type.StyleChange, QEvent.Type.FontChange, QEvent.Type.PaletteChange)


class _Later(QObject):
    """What a theme switch leaves for after it, done a few widgets at a time between
    the event loop's other work. Qt tells every widget in the app the style changed
    (a StyleChange each), and each works its look out again from the sheet's ~530
    rules: most of a switch's freeze (~0.5 s on a full board, 1-1.7 s on a busy PC),
    for the ~2000 widgets nobody can see. Those hear of it afterwards: the hidden
    parts of the open windows (styled in the new sheet then, as Qt's restyle would
    have) and the closed windows (styled when shown, as before). One shown before its
    turn has its share done as it shows, before it paints."""

    SLICE_S = 0.008   # the most each turn takes before the event loop is back

    def __init__(self):
        super().__init__()
        self.todo: list = []    # (widget, style it, set its sheet again), parents first
        self.hold: set = set()  # the widgets in todo: no StyleChange while restyling
        self.tops: list = []    # the tops of what's in todo, watched for a show
        self.holding = False
        self.timer = QTimer(self)
        self.timer.setInterval(0)
        self.timer.timeout.connect(self._step)

    def queue(self, parts: list, closed: list, own: list) -> None:
        """The hidden `parts` of the open windows and the `closed` windows, left for
        later; `own`: the widgets in those with a sheet of their own (_own_sheets_again).
        Their old sheet stays on them until then (undone with the new style's
        unpolish: _keep_sheet_caches)."""
        from PySide6.QtWidgets import QWidget
        polished = Qt.WidgetAttribute.WA_WState_Polished
        own_set = set(own)
        _keep_sheet_caches()
        for tops, styled in ((parts, True), (closed, False)):
            for top in tops:
                for w in (top, *top.findChildren(QWidget)):   # (each after its parent)
                    if w in self.hold:
                        continue   # (left from a switch just before: still to do)
                    style = styled and w.testAttribute(polished)
                    self.hold.add(w)
                    # (Qt's restyle sets a styled widget's own sheet again: so does this)
                    self.todo.append((w, style, w in own_set or (style and bool(w.styleSheet()))))
                    if style:
                        w.setAttribute(polished, False)   # left out of Qt's restyle
                top.installEventFilter(self)
                self.tops.append(top)
        if self.todo:
            self.timer.start()

    @contextmanager
    def holding_back(self, app):
        """While the app restyles: no StyleChange to the widgets left for later."""
        self.holding = True
        app.installEventFilter(self)
        try:
            yield
        finally:
            app.removeEventFilter(self)
            self.holding = False

    def eventFilter(self, obj, ev):  # noqa: N802 - Qt API
        try:
            t = ev.type()
            if t in _HELD_BACK:
                return self.holding and obj in self.hold
            if t == QEvent.Type.Show and obj in self.tops:
                self._do_now(obj)
        except RuntimeError:   # (being deleted: nothing to style)
            pass
        return False

    def _do_now(self, top) -> None:
        """`top` is showing: its share done now, before it paints."""
        rest = []
        for item in self.todo:
            w = item[0]
            if not shiboken6.isValid(w):
                self.hold.discard(w)
            elif w is top or top.isAncestorOf(w):
                self.hold.discard(w)
                _style_one(*item)
            else:
                rest.append(item)
        self.todo = rest

    def _step(self) -> None:
        end = time.perf_counter() + self.SLICE_S
        todo = self.todo
        i = 0
        while i < len(todo) and time.perf_counter() < end:
            item = todo[i]
            i += 1
            self.hold.discard(item[0])
            if shiboken6.isValid(item[0]):
                _style_one(*item)
        del todo[:i]
        if not todo:
            self.timer.stop()
            self.hold.clear()
            for top in self.tops:
                if shiboken6.isValid(top):
                    top.removeEventFilter(self)
            self.tops = []


def _style_one(w, style: bool, sheet_again: bool) -> None:
    """One widget left out of the restyle: told the style changed, its own sheet made
    anew over the new app sheet (`sheet_again`: _own_sheets_again), and (`style`) given
    the app's sheet, as Qt's restyle would have."""
    polished = Qt.WidgetAttribute.WA_WState_Polished
    try:
        if sheet_again:
            _own_sheets_again([w])
        if style and not w.testAttribute(polished):
            st = w.style()
            st.unpolish(w)   # the old sheet undone (its palette and font back)
            st.polish(w)
            w.setAttribute(polished, True)
        QCoreApplication.sendEvent(w, QEvent(QEvent.Type.StyleChange))
    except RuntimeError:   # being deleted
        pass


_later: _Later | None = None
_keeper = None


def _keep_sheet_caches() -> None:
    """Qt keeps what a sheet changed on each widget (its palette and font before) only
    while some sheet style exists, and clearing the app's sheet can end the last one:
    a widget left out of the restyle kept the old theme's colours for good where the
    new sheet had no rule (the old one's undone only by Qt's clear, ~0.1 s). A widget
    never shown with a sheet of its own keeps one alive, so _style_one's unpolish
    can undo it later."""
    global _keeper
    if _keeper is None or not shiboken6.isValid(_keeper):
        from PySide6.QtWidgets import QWidget
        _keeper = QWidget()
        _keeper.setObjectName("sheetkeeper")
        _keeper.setStyleSheet("QWidget#sheetkeeper { }")


def _restyle(app, css: str, later: _Later | None = None) -> None:
    """The app's sheet to `css`, every widget restyled. `later` (holding back): the
    widgets not on screen are left to it, done a few at a time after this."""
    closed: list = []
    own = _style_when_shown(app, closed)
    if later is None or not css:
        # cleared first: Qt swapping one app-wide sheet straight for another re-styles
        # every widget the slow way (3 s against 0.6 s with ~2000 widgets); empty and
        # then the new sheet gives the same look. No paint happens in between.
        app.setStyleSheet("")
        app.setStyleSheet(css)
        if css:
            _own_sheets_again(own)
        return
    later.queue(_hidden_parts(app), closed, own)
    app.setStyleSheet("")   # (as above: cleared first)
    app.setStyleSheet(css)


@contextmanager
def styled_after(app):
    """Build a lot of widgets with the app sheet off, then style them all at once: Qt
    re-applies an app-wide sheet to every widget added to a layout or tab, about half
    of a window's build. Widgets that measure text re-measure on StyleChange
    (ui/kit/restyled.py)."""
    css = app.styleSheet() if app is not None else ""
    if app is None or not css:
        yield
        return
    _restyle(app, "")
    try:
        yield
    finally:
        if not app.styleSheet():   # (apply() inside put a sheet up itself)
            _restyle(app, css)
            # a layout keeps the spacing it worked out in the plain style until told
            for w in app.allWidgets():
                if (lay := w.layout()) is not None:
                    lay.invalidate()


def apply(app, name: str, live: str | None = None) -> str:
    """Switch the whole app to theme `name` (live). `live`: the user's own highlight
    colour ("" = the theme's), None = keep the one set already."""
    old = dict(T)
    if live is not None:
        set_live(live)
    name = set_current(name)
    css = stylesheet(name)
    global _later
    if _later is None:
        _later = _Later()
    with _later.holding_back(app):
        if app.styleSheet() != css:   # the same sheet again (a new window): no change
            _restyle(app, css, _later)
        widgets = app.allWidgets()
        _recolour_inline(widgets, old)
        sheet = live_sheet()
        for w in widgets:   # restyled by apply_live: in step with the new theme
            if w.objectName() in LIVE_NAMES and w.styleSheet():
                w.setStyleSheet(sheet)
    for w in widgets:   # hand-painted widgets read T in paintEvent
        w.update()
    return name


def apply_live(app, colour: str) -> str:
    """Switch only the live highlight to `colour` ("" = the theme's): restyles the
    LIVE_NAMES widgets and repaints, a fraction of a second where apply() takes
    seconds. Returns the colour kept ("" for the theme's, or for a bad one)."""
    old = dict(T)
    set_live(colour)
    T.clear()
    T.update(tokens())
    sheet = live_sheet()
    widgets = app.allWidgets()
    for w in widgets:
        if w.objectName() in LIVE_NAMES:
            w.setStyleSheet(sheet)
    _recolour_inline(widgets, old)
    for w in widgets:   # hand-painted widgets (a live tab's wash) read T in paintEvent
        w.update()
    return live_override
