"""A widget with no parent that's shown is, for that moment, a window of its own:
Windows makes it (a little box flashing up on screen: start-up's "small windows") and
takes it down again once a layout adopts it, two native calls of ~15 ms each that the
audio threads wait out. Make it with its parent, or put it in a layout that's already
on a widget before showing it. (A layout made bare, QHBoxLayout(), adopts nothing
till it's added to one that is.)"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "soundboard"
ADOPT = {"addWidget", "insertWidget", "setWidget", "addTab", "insertTab", "addRow",
         "setCentralWidget", "setCornerWidget", "setCellWidget", "addPermanentWidget"}
NEST = {"addLayout", "insertLayout"}
SHOW = {"setVisible", "show", "setHidden"}
NEVER = float("inf")


def _src(node) -> str:
    return ast.unparse(node) if node is not None else ""


def _made(call: ast.Call) -> str:
    return _src(call.func).split(".")[-1]


def _parentless(call: ast.Call) -> bool:
    """A widget made with no parent: Q…(…) or hint_label(…), with no parent= and no
    last argument that looks like one (self, parent, self.x)."""
    name = _made(call)
    if not (name[:1] == "Q" or name == "hint_label") or "Layout" in name:
        return False
    if any(k.arg == "parent" for k in call.keywords):
        return False
    last = _src(call.args[-1]) if call.args else ""
    return not (last in ("self", "parent") or last.startswith(("self.", "parent")))


def _shows(call: ast.Call) -> bool:
    arg = _src(call.args[0]) if call.args else ""
    if call.func.attr == "setVisible":
        return arg != "False"
    if call.func.attr == "setHidden":
        return arg != "True"
    return True


def _check(fn) -> list[tuple[int, str]]:
    nodes = sorted((n for n in ast.walk(fn) if hasattr(n, "lineno")),
                   key=lambda n: (n.lineno, n.col_offset))
    layouts: dict[str, list] = {}      # name -> [(made at, on a widget from)]
    widgets: dict[str, int] = {}       # parentless widget -> made at
    shows, adds, nests = [], [], []
    for n in nodes:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            for t in map(_src, n.targets):
                if "Layout" in _made(n.value) or _made(n.value) == "Flow":
                    layouts.setdefault(t, []).append([n.lineno, n.lineno if n.value.args
                                                      else NEVER])
                elif _parentless(n.value):
                    widgets[t] = n.lineno
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            obj, meth = _src(n.func.value), n.func.attr
            if meth in SHOW and _shows(n):
                shows.append((n.lineno, obj))
            elif meth in ADOPT and n.args:
                adds.append((n.lineno, obj, _src(n.args[0])))
            elif meth in NEST and n.args:
                nests.append((n.lineno, obj, _src(n.args[-1])))
            elif meth in ("setLayout", "setParent"):
                adds.append((n.lineno, None, obj if meth == "setParent" else _src(n.args[0])))

    def made_as(name, line):
        """The layout `name` meant at `line`: the latest one made by then."""
        got = [lay for lay in layouts.get(name, []) if lay[0] <= line]
        return got[-1] if got else None

    for _ in range(4):   # a layout is on a widget once it's in one that is
        for line, outer, inner in nests:
            o, i = made_as(outer, line), made_as(inner, line)
            if i is not None:
                on = max(line, o[1]) if o is not None else line   # unknown outer: trust it
                i[1] = min(i[1], on)

    def adopted(widget, since):
        times = []
        for line, lay, w in adds:
            if w != widget or line < since:
                continue
            got = made_as(lay, line) if lay else None
            times.append(max(line, got[1]) if got is not None else line)
        return min(times, default=NEVER)

    found = []
    for w, made in widgets.items():
        first = min((line for line, obj in shows if obj == w and line >= made), default=None)
        if first is not None and first < adopted(w, made):
            found.append((first, w))
    return found


def shown_before_adopted(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [f"{path.relative_to(ROOT)}:{line} {w}"
            for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            for line, w in _check(fn)]


def test_no_widget_is_shown_before_it_has_a_parent():
    found = [hit for p in sorted(ROOT.rglob("*.py")) for hit in shown_before_adopted(p)]
    assert found == []


def test_the_check_finds_the_mistake(tmp_path, monkeypatch):
    bad = tmp_path / "bad.py"
    bad.write_text("def build(self):\n"
                   "    v = QVBoxLayout(self)\n"
                   "    self.hint = QLabel('x')\n"            # shown, then adopted
                   "    self.hint.setVisible(True)\n"
                   "    v.addWidget(self.hint)\n"
                   "    row = QHBoxLayout()\n"
                   "    late = QPushButton('y')\n"            # in a bare row: no parent yet
                   "    row.addWidget(late)\n"
                   "    late.setVisible(True)\n"
                   "    v.addLayout(row)\n"
                   "    ok = QLabel('z')\n"                   # adopted, then shown: fine
                   "    v.addWidget(ok)\n"
                   "    ok.setVisible(True)\n"
                   "    kid = QLabel('k', self)\n"            # made with its parent: fine
                   "    kid.show()\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    assert shown_before_adopted(bad) == ["bad.py:4 self.hint", "bad.py:9 late"]
