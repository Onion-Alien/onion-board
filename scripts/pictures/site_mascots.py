"""Draw Bun and Hoot for the website from the apps' own drawing code.

    .venv\\Scripts\\python scripts/pictures/site_mascots.py

Runs bunny.draw_bunny and owl.draw_owl, dressed in each theme the site's look switcher
offers (site_themes.py), through a stand-in painter that writes SVG instead of pixels.
It rewrites the art between the <!-- bun: ... --> / <!-- hoot: ... --> markers in
site/index.html and each look's colours and parts between the /* looks */ markers in
site/home.css. Rerun it after changing either drawing.

Each part the page moves (ears, eyes, brows, mouth, wings...) is its own group, named
by where draw_bunny / draw_owl paints it. A part that differs between looks (his
markings, a floppy ear, an outfit) gets one copy per difference, and the look's CSS
variables pick the copy; colours that change with the look are variables too.
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QGradient, QLinearGradient, QPainterPath,  # noqa: E402
                           QPainterPathStroker, QPen, QRadialGradient, QTransform)

from site_themes import DEFAULT, SITE_THEMES, slug  # noqa: E402
from soundboard.ui.bun import bunny  # noqa: E402
from soundboard.ui.kit import theme  # noqa: E402
from soundboard.style import bunnyfit, owl  # noqa: E402

PAGE = ROOT / "site" / "index.html"
CSS = ROOT / "site" / "home.css"
LOOKS = [DEFAULT] + SITE_THEMES
INK = "#2b2340"


def num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def path_d(path: QPainterPath) -> str:
    """A QPainterPath as SVG path data (closing each shape that ends where it began)."""
    out, start, last, i, n = [], None, None, 0, path.elementCount()
    while i < n:
        e = path.elementAt(i)
        if e.type == QPainterPath.ElementType.MoveToElement:
            if start is not None and last == start:
                out.append("Z")
            start = last = (num(e.x), num(e.y))
            out.append(f"M{start[0]} {start[1]}")
            i += 1
        elif e.type == QPainterPath.ElementType.LineToElement:
            last = (num(e.x), num(e.y))
            out.append(f"L{last[0]} {last[1]}")
            i += 1
        else:   # a curve: this element and the next two
            c1, c2 = e, path.elementAt(i + 1)
            end = path.elementAt(i + 2)
            last = (num(end.x), num(end.y))
            out.append(f"C{num(c1.x)} {num(c1.y)} {num(c2.x)} {num(c2.y)} {last[0]} {last[1]}")
            i += 3
    if start is not None and last == start:
        out.append("Z")
    d = "".join(out)
    return re.sub(r" -", "-", d)


def matrix(t: QTransform) -> str:
    if t.isIdentity():
        return ""
    if t.type() == QTransform.TransformationType.TxTranslate:
        return f' transform="translate({num(t.dx())} {num(t.dy())})"'
    return (f' transform="matrix({num4(t.m11())} {num4(t.m12())} {num4(t.m21())} '
            f'{num4(t.m22())} {num(t.dx())} {num(t.dy())})"')


def num4(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class Defs:
    """The gradients the drawings use, shared by every look and copy (same gradient,
    one id)."""

    def __init__(self):
        self.items: dict[str, str] = {}

    def add(self, body: str, tag: str) -> str:
        key = "g" + hashlib.sha1(body.encode()).hexdigest()[:7]
        self.items.setdefault(key, f'<{tag} id="{key}" {body}</{tag}>')
        return key


class SvgPainter:
    """Enough of QPainter for the mascots' drawing code, writing SVG elements. Each
    element is tagged with what's drawing it (tagger) so the parts can be sorted out."""

    def __init__(self, colours: dict[str, str], defs: Defs, tagger):
        self.colours = colours   # hex -> CSS variable, for the look's own colours
        self.defs = defs
        self.tagger = tagger
        self.t = QTransform()
        self.pen_ = None
        self.brush_ = None
        self.op = 1.0
        self.clip = None   # in canvas coordinates
        self.stack = []
        self.out: list[tuple[dict, str]] = []

    # ---- state
    def save(self):
        self.stack.append((QTransform(self.t), self.pen_, self.brush_, self.op, self.clip))

    def restore(self):
        self.t, self.pen_, self.brush_, self.op, self.clip = self.stack.pop()

    def setRenderHint(self, *a):
        pass

    def translate(self, x, y=None):
        if isinstance(x, QPointF):
            x, y = x.x(), x.y()
        self.t = QTransform().translate(x, y) * self.t

    def rotate(self, a):
        self.t = QTransform().rotate(a) * self.t

    def scale(self, sx, sy):
        self.t = QTransform().scale(sx, sy) * self.t

    def setPen(self, pen):
        if isinstance(pen, Qt.PenStyle):
            self.pen_ = None if pen == Qt.PenStyle.NoPen else QPen(pen)
        elif isinstance(pen, QColor):
            self.pen_ = QPen(pen)
        else:
            self.pen_ = QPen(pen)

    def setBrush(self, brush):
        if isinstance(brush, Qt.BrushStyle):
            self.brush_ = None
        elif isinstance(brush, Qt.GlobalColor):
            self.brush_ = QColor(brush)
        else:
            self.brush_ = brush

    def setOpacity(self, o):
        self.op = o

    def opacity(self):
        return self.op

    def setClipPath(self, path):
        clip = self.t.map(path)
        self.clip = clip if self.clip is None else self.clip.intersected(clip)

    # ---- drawing
    def drawPath(self, path):
        self._emit(path, self.brush_, self.pen_)

    def fillPath(self, path, brush):
        self._emit(path, brush, None)

    def fillRect(self, rect, brush):
        path = QPainterPath()
        path.addRect(rect)
        self._emit(path, brush, None, ("rect", rect))

    def drawEllipse(self, a, rx=None, ry=None):
        rect = QRectF(a.x() - rx, a.y() - ry, 2 * rx, 2 * ry) if rx is not None else QRectF(a)
        path = QPainterPath()
        path.addEllipse(rect)
        self._emit(path, self.brush_, self.pen_, ("ellipse", rect))

    def drawRect(self, rect):
        path = QPainterPath()
        path.addRect(rect)
        self._emit(path, self.brush_, self.pen_, ("rect", rect))

    def drawRoundedRect(self, rect, rx, ry):
        path = QPainterPath()
        path.addRoundedRect(rect, rx, ry)
        self._emit(path, self.brush_, self.pen_, ("rrect", rect, rx, ry))

    def drawLine(self, a, b):
        path = QPainterPath(a)
        path.lineTo(b)
        self._emit(path, None, self.pen_)

    # ---- output
    def _paint(self, what, attr: str) -> str:
        """`attr` ("fill" / "stroke") set to a colour or gradient, as SVG attributes."""
        if isinstance(what, QPen):
            what = what.color()
        if isinstance(what, QGradient):
            return f' {attr}="url(#{self._gradient(what)})"'
        c = QColor(what)
        hexc = c.name()
        var = self.colours.get(hexc)
        s = f' style="{attr}:var({var})"' if var else f' {attr}="{hexc}"'
        if c.alpha() < 255:
            s += f' {attr}-opacity="{num(c.alphaF())}"'
        return s

    def _gradient(self, g: QGradient) -> str:
        stops = ""
        for pos, c in g.stops():
            var = self.colours.get(c.name())
            col = f'style="stop-color:var({var})"' if var else f'stop-color="{c.name()}"'
            op = f' stop-opacity="{num(c.alphaF())}"' if c.alpha() < 255 else ""
            stops += f'<stop offset="{num(pos)}" {col}{op}/>'
        if isinstance(g, QRadialGradient):
            c, f = g.center(), g.focalPoint()
            focal = "" if f == c else f' fx="{num(f.x())}" fy="{num(f.y())}"'
            body = (f'gradientUnits="userSpaceOnUse" cx="{num(c.x())}" cy="{num(c.y())}" '
                    f'r="{num(g.radius())}"{focal}>{stops}')
            return self.defs.add(body, "radialGradient")
        assert isinstance(g, QLinearGradient)
        a, b = g.start(), g.finalStop()
        body = (f'gradientUnits="userSpaceOnUse" x1="{num(a.x())}" y1="{num(a.y())}" '
                f'x2="{num(b.x())}" y2="{num(b.y())}">{stops}')
        return self.defs.add(body, "linearGradient")

    @staticmethod
    def _rule(path: QPainterPath) -> str:
        return (' fill-rule="evenodd"' if path.fillRule() == Qt.FillRule.OddEvenFill
                and path.elementCount() > 0 and _subpaths(path) > 1 else "")

    def _stroke_attrs(self, pen: QPen) -> str:
        if (pen.color().name() == INK and pen.color().alpha() == 255 and pen.widthF() == 2.4
                and pen.capStyle() == Qt.PenCapStyle.RoundCap
                and pen.joinStyle() == Qt.PenJoinStyle.RoundJoin):
            return ' class="k"'   # their ink outline (home.css)
        cap = {Qt.PenCapStyle.RoundCap: "round", Qt.PenCapStyle.FlatCap: "butt"}.get(
            pen.capStyle(), "square")
        join = {Qt.PenJoinStyle.RoundJoin: "round", Qt.PenJoinStyle.MiterJoin: "miter"}.get(
            pen.joinStyle(), "bevel")
        return (self._paint(pen, "stroke") + f' stroke-width="{num(pen.widthF())}"'
                + f' stroke-linecap="{cap}" stroke-linejoin="{join}"')

    def _emit(self, path: QPainterPath, brush, pen: QPen | None, shape=None):
        tr = matrix(self.t)
        op = f' opacity="{num(self.op)}"' if self.op < 0.999 else ""
        if self.clip is not None:   # cut to the clip, in this element's own frame
            inv, ok = self.t.inverted()
            clip = inv.map(self.clip)
            if brush is not None:
                part = path.intersected(clip)
                if not part.isEmpty():
                    self._add(f'<path d="{path_d(part)}"{self._rule(part)}'
                              f'{self._paint(brush, "fill")}{tr}{op}/>')
            if pen is not None:
                st = QPainterPathStroker(pen)
                part = st.createStroke(path).intersected(clip)
                if not part.isEmpty():
                    self._add(f'<path d="{path_d(part)}"{self._paint(pen, "fill")}{tr}{op}/>')
            return
        fill = self._paint(brush, "fill") if brush is not None else ' fill="none"'
        stroke = self._stroke_attrs(pen) if pen is not None else ""
        if brush is None and pen is None:
            return
        if shape and shape[0] == "ellipse":
            r = shape[1]
            el = (f'<ellipse cx="{num(r.center().x())}" cy="{num(r.center().y())}" '
                  f'rx="{num(r.width() / 2)}" ry="{num(r.height() / 2)}"')
        elif shape and shape[0] in ("rect", "rrect"):
            r = shape[1]
            el = (f'<rect x="{num(r.x())}" y="{num(r.y())}" width="{num(r.width())}" '
                  f'height="{num(r.height())}"')
            if shape[0] == "rrect":
                el += f' rx="{num(shape[2])}" ry="{num(shape[3])}"'
        else:
            el = f'<path d="{path_d(path)}"{self._rule(path) if brush is not None else ""}'
        self._add(el + fill + stroke + tr + op + "/>")

    def _add(self, markup: str):
        self.out.append((self.tagger(), markup))


def _subpaths(path: QPainterPath) -> int:
    return sum(1 for i in range(path.elementCount())
               if path.elementAt(i).type == QPainterPath.ElementType.MoveToElement)


# ------------------------------------------------------------------------- tagging
class Tagger:
    """What's being drawn right now: the line of draw_bunny / draw_owl that's running,
    a few of its loop variables (which ear, which eye) and the outfit piece."""

    def __init__(self, fn_name: str, parts: list[tuple[int, str]]):
        self.fn = fn_name
        self.parts = parts   # (first line, part), in order
        self.piece = None

    def __call__(self) -> dict:
        f = sys._getframe(2)
        while f is not None and f.f_code.co_name != self.fn:
            f = f.f_back
        assert f is not None, "drawn from outside " + self.fn
        part = None
        for line, name in self.parts:
            if f.f_lineno >= line:
                part = name
        loc = f.f_locals
        return {"part": part, "piece": self.piece,
                "side": loc.get("side") if part == "ears" else
                loc.get("sx") if part in ("tufts", "wings") else
                loc.get("i") if part in ("eyes", "brows") else
                (EYE_INDEX.get(loc.get("x"))) if part == "owl-eyes" else None}


EYE_INDEX = {owl.EYES[0]: 0, owl.EYES[1]: 1}


def anchors(fn, marks: list[tuple[str, str]]) -> list[tuple[int, str]]:
    """The first line of each part of drawing function `fn`, found by a bit of its code
    (so the parts stay right when lines move)."""
    import inspect
    lines, first = inspect.getsourcelines(fn)
    out, at = [], 0
    for snippet, name in marks:
        for k in range(at, len(lines)):
            if snippet in lines[k]:
                out.append((first + k, name))
                at = k + 1
                break
        else:
            raise SystemExit(f"{fn.__name__} has no line with {snippet!r} any more: "
                             "update site_mascots.py's parts")
    return out


BUN_PARTS = [
    ('bunnyfit.draw(p, fit, "behind"', "fit-behind"),
    ("fold = 115", "ears"),
    ("# tail (peeking out", "tail"),
    ("head_xf = QTransform()", "reach"),
    ("p.drawPath(body_shape)", "body"),
    ("belly = (QColor(kit", "belly"),
    ("pads = QColor(kit", "feet"),
    ("body = tuple(n for n in fit", "fit-body"),
    ("_paws(p, prop", "arms"),
    ('bunnyfit.draw(p, fit_head, "back"', "fit-head"),
    ("p.drawPath(head_shape)", "head"),
    ('bunnyfit.draw(p, fit_head, "under"', "fit-under"),
    ("# headphones:", "phones"),
    ("if nightcap:", "cap"),
    ('bunnyfit.draw(p, fit_head, "over"', "fit-over"),
    ('if "shiner" in extras', "shiner"),
    ("shut = blink > 0.6", "eyes"),
    ("up = 3.5 if hidden", "brows"),
    ("blush = QColor(CHEEK)", "cheeks"),
    ('if "freckles" in extras', "freckles"),
    ("nose = QPainterPath(", "nose"),
    ("line = ROBOT_CYAN if robot", "mouth"),
    ("if not robot:   # the little line", "noseline"),
    ('bunnyfit.draw(p, fit_head, "face"', "fit-face"),
    ("if angry > 0.5:", "vein"),
    ("p.restore()   # (the head's frame)", "wave"),
    ("bunnyfit.draw(p, tuple(n for n in body", "fit-neck"),
    ('if prop != "headphones":', "mic"),
]

OWL_PARTS = [
    ('_fit(p, fit, "behind"', "fit-back"),
    ("# ear tufts", "tufts"),
    ("# body: feathers", "body"),
    ("# belly, with rows", "belly"),
    ("# feet: three", "feet"),
    ("# the face: a cream mask", "mask"),
    ("# wings:", "wings"),
    ('_fit(p, fit, "under"', "fit-under"),
    ("# the big eyes", "owl-eyes"),
    ("# brows:", "brows"),
    ("# beak:", "beak"),
    ("# a tear rolling", "tear"),
    ('_fit(p, fit, "over"', "fit-over"),
]


# ------------------------------------------------------------------------- colours
def _hex(c) -> str:
    return QColor(c).name()


def bun_colours(name: str) -> dict[str, str]:
    """Bun's colours in theme `name`, as draw_bunny works them out: CSS variable ->
    colour."""
    kit = {**bunnyfit.VANILLA, **bunnyfit.LOOKS.get(name, {})}
    fur = QColor(kit["fur"])
    shade = bunny.FUR_SHADE if fur == bunny.FUR else fur.darker(107)
    dark = fur.lightnessF() < 0.45
    nose = QColor(kit["nose"])
    phones = QColor(theme.THEMES[name]["accent"])
    out = {"--bun-fur": fur, "--bun-shade": shade, "--bun-inner": kit["inner"],
           "--bun-iris": kit["iris"], "--bun-nose": nose,
           "--bun-nose-edge": bunny.NOSE_EDGE if nose == bunny.NOSE else nose.darker(125),
           "--bun-marks": kit["marks"],
           "--bun-belly": kit["belly"] or (fur.lighter(125) if dark else shade),
           "--bun-pads": kit["pads"] or kit["inner"],
           "--bun-face": bunny.FACE_LIGHT if dark else bunny.INK,
           "--bun-phones": phones, "--bun-phones-hi": phones.lighter(145),
           "--bun-phones-lo": phones.darker(128), "--bun-cap-star": phones.lighter(160),
           "--bun-cap-fold": phones.darker(125)}
    return {k: _hex(v) for k, v in out.items()}


def owl_colours(name: str) -> dict[str, str]:
    kit = owl.look(name)
    feather, belly = QColor(kit["feather"]), QColor(kit["belly"])
    beak = QColor(kit["beak"])
    out = {"--hoot-feather": feather, "--hoot-wing": kit["wing"] or feather.darker(135),
           "--hoot-light": feather.lighter(125), "--hoot-face": kit["face"],
           "--hoot-belly": belly,
           "--hoot-shade": owl.BELLY_MARK if kit["belly"] == owl.VANILLA["belly"]
           else belly.darker(118),
           "--hoot-iris": kit["iris"], "--hoot-mark": kit["mark"], "--hoot-beak": beak,
           "--hoot-beak-dark": owl.BEAK_DARK if kit["beak"] == owl.VANILLA["beak"]
           else beak.darker(122),
           "--hoot-toes": kit["feet"] or kit["beak"]}
    return {k: _hex(v) for k, v in out.items()}


def var_map(colours: dict[str, str]) -> dict[str, str]:
    """colour -> the first variable that holds it (never the ink: the outlines stay
    literal, so they read the same in every look)."""
    out = {}
    for var, c in colours.items():
        if c != INK:
            out.setdefault(c, var)
    return out


# ------------------------------------------------------------------------- drawing
def record(name: str, fn, parts, colours, defs, **pose):
    """The elements drawing function `fn` paints for theme `name` in `pose`."""
    tagger = Tagger(fn.__name__, anchors(fn, parts))
    p = SvgPainter(var_map(colours), defs, tagger)
    real = bunnyfit.draw

    def draw(pp, pieces, layer, ink, hats=True, shut=False):
        for piece in pieces:
            tagger.piece = piece
            real(pp, (piece,), layer, ink, hats=hats, shut=shut)
        tagger.piece = None

    bunnyfit.draw = draw
    try:
        with theme.previewing(name):
            fn(p, QRectF(0, 0, 100, 120), **pose)
    finally:
        bunnyfit.draw = real
    return p.out


def pick(elements, part, side=None) -> list:
    """The elements of `part` (and `side`, if given), each outfit piece in its own group
    (hats and glasses get a class: they come off for his nap)."""
    out, piece = [], None
    for tag, markup in elements:
        if tag["part"] != part or (side is not None and tag["side"] != side):
            continue
        if tag["piece"] != piece:
            if piece is not None:
                out.append("</g>")
            piece = tag["piece"]
            if piece is not None:
                kind = (" hat" if piece in bunnyfit.HATS else
                        " eyewear" if piece in bunnyfit.EYEWEAR else "")
                out.append(f'<g class="fit{kind}">')
        out.append(markup)
    if piece is not None:
        out.append("</g>")
    return out


SIDES = {"ears", "tufts", "wings"}   # parts drawn once a side: -1 the viewer's left,
                                     # 1 the right (eyes are 0 and 1)


class Parts:
    """The parts of one mascot, each drawn once (in <defs>, `prefix`-name) and used by
    both the big picture and the small copies. A part that differs between looks has
    one copy per difference inside it, each shown by its own CSS variable (set per look
    in home.css)."""

    def __init__(self, prefix: str, rec: dict):
        self.prefix = prefix
        self.rec = rec
        self.defs: dict[str, str] = {}     # id -> markup
        self.ids: dict[str, str] = {}      # a look's copy -> its class
        self.looks: dict[str, set] = {}    # class -> the looks showing it

    def __call__(self, name: str, pose: str = "rest", side=None, cls: str = "") -> str:
        """A <use> of part `name` in `pose` (`side`: one ear, eye...), in a group of class
        `cls` if given; "" if no look draws it."""
        kinds: dict[str, list[str]] = {}
        for look in LOOKS:
            kinds.setdefault("".join(pick(self.rec[look][pose], name, side)), []).append(look)
        if len(kinds) == 1:
            body = next(iter(kinds))
        else:
            body = ""
            for copy, looks in kinds.items():
                if copy:
                    vid = self.ids.setdefault(copy, f"{self.prefix}{len(self.ids) + 1}")
                    self.looks.setdefault(vid, set()).update(looks)
                    body += f'<g class="{vid}">{copy}</g>'
        if not body:
            return ""
        where = {-1: "l", 1: "r"}.get(side) if name in SIDES else side
        key = "-".join(str(k) for k in (self.prefix, name, pose, where)
                       if k not in (None, "rest"))
        self.defs[key] = f'<g id="{key}">{body}</g>'
        use = f'<use href="#{key}"/>'
        return f'<g class="{cls}">{use}</g>' if cls else use


# the talking mouth: draw_bunny's open mouth, reshaped by home.js as the sound gets
# louder (its mouthD is this same shape)
def mouth_d(m: float) -> str:
    oh, hw = 2.5 + 6.5 * min(1.0, m), 4.2 + 1.3 * m
    b = 75.5 + oh * 1.25
    return (f"M{num(50 - hw)} 75.2Q{num(50 - hw / 2)} 77 50 75.4Q{num(50 + hw / 2)} 77 "
            f"{num(50 + hw)} 75.2C{num(50 + hw)} {num(b)} {num(50 - hw)} {num(b)} "
            f"{num(50 - hw)} 75.2Z")


def talk() -> str:
    m = 0.3
    oh, hw = 2.5 + 6.5 * m, 4.2 + 1.3 * m
    return (f'<g class="talk"><path class="mo" d="{mouth_d(m)}" fill="{bunny.MOUTH.name()}"/>'
            f'<ellipse class="tongue" cx="50" cy="{num(75.5 + oh * 0.95)}" rx="{num(hw * 0.65)}" '
            f'ry="{num(oh * 0.3)}" fill="{bunny.NOSE.name()}" clip-path="url(#mouth-clip)"/>'
            f'<path class="mo" d="{mouth_d(m)}" fill="none" style="stroke:var(--bun-face)" '
            f'stroke-width="1.7" stroke-linejoin="round"/></g>')


def bun_tree(part: Parts, live: bool) -> str:
    """Bun's parts in draw_bunny's order (`live`: the big one, who talks)."""
    eyes = "".join(
        f'<g class="eye"><g class="open">{part("eyes", side=i)}</g>'
        f'<g class="shut">{part("eyes", "asleep", i)}</g></g>' for i in (0, 1))
    return "".join([
        part("fit-behind"),
        part("ears", side=-1, cls="ear l"), part("ears", side=1, cls="ear r"),
        part("tail"), part("reach"), part("body"), part("belly"), part("feet"),
        part("fit-body"), part("arms"), part("fit-head"), part("head"), part("fit-under"),
        part("phones"), part("cap", "asleep", cls="cap"), part("fit-over"), part("shiner"),
        f'<g class="eyes">{eyes}</g>',
        part("brows", cls="rest-brows"), part("brows", "angry", cls="brows"),
        part("cheeks", cls="cheeks"), part("cheeks", "angry", cls="cheeks-angry"),
        part("freckles"), part("nose"),
        part("mouth", cls="smile"), part("mouth", "angry", cls="frown"),
        talk() if live else "",
        part("noseline"), part("fit-face"), part("vein", "angry", cls="vein"),
        part("fit-neck"), part("mic", cls="mic"),
    ])


# Hoot's alert glow behind his eyes (the page's own: he lights up when something shows up)
GLOW = ('<g class="glow" fill="#ffc53d" filter="url(#soft)">'
        + "".join(f'<circle cx="{x}" cy="{num(owl.EYE_Y)}" r="15"/>' for x in owl.EYES)
        + "</g>")


def owl_tree(part: Parts) -> str:
    eyes = "".join(
        f'<g class="eye"><g class="pupils">{part("owl-eyes", side=i)}</g>'
        f'<g class="shut">{part("owl-eyes", "blink", i)}</g></g>' for i in (0, 1))
    return "".join([
        part("fit-back"),
        part("tufts", side=-1, cls="tuft l"), part("tufts", side=1, cls="tuft r"),
        part("body"), part("belly"), part("feet"), part("mask"),
        part("wings", side=-1, cls="wing l"), part("wings", side=1, cls="wing r"),
        part("fit-under"), GLOW, eyes,
        part("beak", cls="beak"), part("beak", "cheer", cls="beak-open"),
        part("fit-over"),
    ])


def looks_css(*parts: Parts) -> str:
    lines = ["/* looks: written by scripts/pictures/site_mascots.py from the apps' bunny.py and",
             "   owl.py. Each look's colours, and which copy of a part it shows (a floppy ear,",
             "   markings, an outfit). Variables, so the small copies (<use>) follow too. */"]
    variants = {v: on for p in parts for v, on in p.looks.items()}
    lines.append(" ".join(f".{v} {{ display: var(--{v}, none); }}" for v in variants))
    for look in LOOKS:
        sel = (':root, html[data-look="dark"]' if look == DEFAULT
               else f'html[data-look="{slug(look)}"]')
        decl = {**bun_colours(look), **owl_colours(look)}
        decl.update({f"--{v}": "inline" if look in on else "none" for v, on in variants.items()})
        body = "; ".join(f"{k}: {v}" for k, v in decl.items())
        lines.append(f"{sel} {{ {body}; }}")
    lines.append("/* /looks */")
    return "\n".join(lines)


def replace(text: str, start: str, end: str, new: str, path: Path) -> str:
    a, b = text.find(start), text.find(end)
    if a < 0 or b < a:
        raise SystemExit(f"{path.name} has no {start} ... {end} markers")
    return text[:a + len(start)] + new + text[b:]


BUN_POSES = {"rest": {"prop": "mic"}, "angry": {"prop": "mic", "angry": 1.0},
             "asleep": {"prop": "mic", "nightcap": True, "blink": 1.0}}
OWL_POSES = {"rest": {}, "blink": {"blink": 1.0}, "cheer": {"beak": 1.0}}


def recordings(defs: Defs):
    bun = {look: {k: record(look, bunny.draw_bunny, BUN_PARTS, bun_colours(look), defs, **pose)
                  for k, pose in BUN_POSES.items()} for look in LOOKS}
    hoot = {look: {k: record(look, owl.draw_owl, OWL_PARTS, owl_colours(look), defs, **pose)
                   for k, pose in OWL_POSES.items()} for look in LOOKS}
    return bun, hoot


MARK = "written by scripts/pictures/site_mascots.py"


def build() -> tuple[str, str, str, str]:
    """(the shared <defs> and small copies, big Bun, big Hoot, home.css's looks)."""
    defs = Defs()
    bun_rec, owl_rec = recordings(defs)
    bun, hoot = Parts("bun", bun_rec), Parts("hoot", owl_rec)
    bun_live, bun_icon, owl_art = bun_tree(bun, True), bun_tree(bun, False), owl_tree(hoot)
    shared = "\n".join([
        "".join(defs.items[k] for k in sorted(defs.items)),
        f'<clipPath id="mouth-clip"><path class="mo" d="{mouth_d(0.3)}"/></clipPath>'
        '<filter id="soft" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="3"/></filter>',
        *bun.defs.values(), *hoot.defs.values(),
        f'<symbol id="bun-icon" overflow="visible"><g class="bun-g">{bun_icon}</g></symbol>',
        f'<symbol id="hoot-icon" overflow="visible"><g class="hoot-g"><g class="body-turn">'
        f'{owl_art}</g></g></symbol>'])
    return shared, bun_live, owl_art, looks_css(bun, hoot)


def main():
    shared, bun_live, owl_art, css_looks = build()
    page = PAGE.read_text(encoding="utf-8")
    page = replace(page, f"<!-- mascots: {MARK} -->", "<!-- /mascots -->",
                   "\n" + shared + "\n", PAGE)
    page = replace(page, f"<!-- bun: {MARK} -->", "<!-- /bun -->", bun_live, PAGE)
    page = replace(page, f"<!-- hoot: {MARK} -->", "<!-- /hoot -->", owl_art, PAGE)
    PAGE.write_text(page, encoding="utf-8", newline="\n")
    css = CSS.read_text(encoding="utf-8")
    a, b = css.find("/* looks:"), css.find("/* /looks */")
    if a < 0 or b < a:
        raise SystemExit("home.css has no /* looks: ... /* /looks */ markers")
    css = css[:a] + css_looks + css[b + len("/* /looks */"):]
    CSS.write_text(css, encoding="utf-8", newline="\n")
    print(f"site/index.html: {len(shared) // 1024} KB of shared art, Bun {len(bun_live)} B, "
          f"Hoot {len(owl_art)} B; site/home.css: {len(css_looks) // 1024} KB of looks")


if __name__ == "__main__":
    main()
