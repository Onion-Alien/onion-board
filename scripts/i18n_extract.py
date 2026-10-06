"""Find every text wrapped for translation (`_("…")`, `ngettext("…", "…", n)`) in
soundboard/ and compare it with the language catalogs in assets/lang/.

    python scripts/i18n_extract.py            report, per language: missing / unused
    python scripts/i18n_extract.py --update   add missing texts to every catalog (empty,
                                              so English shows until translated) and
                                              drop unused ones
    python scripts/i18n_extract.py --check    exit 1 if anything is missing, unused,
                                              or `_` is shadowed (for CI)

It also reports functions that both call `_()` and assign `_` (`path, _ = …`): there
`_` is the local variable, not the translator, and the call fails. Use `__` or a name
for the throwaway instead.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "soundboard"
LANG = ROOT / "assets" / "lang"
SKIP = {"en", "xx"}   # English is the source; xx is generated


def _str(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) \
        else None


def scan(src: Path = SRC) -> tuple[dict[str, set[str]], dict[str, bool], list[str]]:
    """({text: {where…}}, {text: is it plural}, [shadowing problems])."""
    texts: dict[str, set[str]] = {}
    plural: dict[str, bool] = {}
    problems: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src.parent).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), rel)
        except SyntaxError as e:
            problems.append(f"{rel}: can't parse ({e})")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
                if name == "_" and node.args:
                    s = _str(node.args[0])
                    if s is not None:
                        texts.setdefault(s, set()).add(f"{rel}:{node.lineno}")
                        plural.setdefault(s, False)
                    else:
                        problems.append(f"{rel}:{node.lineno}: _() needs a plain string, "
                                        "not an expression (use {placeholders})")
                elif name == "ngettext" and len(node.args) >= 2:
                    s = _str(node.args[0])
                    if s is not None and _str(node.args[1]) is not None:
                        texts.setdefault(s, set()).add(f"{rel}:{node.lineno}")
                        plural[s] = True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                problems += _shadowing(node, rel)
    return texts, plural, problems


def _shadowing(fn, rel: str) -> list[str]:
    calls = assigns = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "_":
            calls = True
        elif isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, ast.Store):
            assigns = True
        elif isinstance(node, ast.arg) and node.arg == "_":
            assigns = True
    if calls and assigns:
        name = getattr(fn, "name", "<lambda>")
        return [f"{rel}:{fn.lineno}: {name}() assigns `_` and also calls _(): rename the "
                "throwaway"]
    return []


def catalogs(lang: Path = LANG) -> dict[str, tuple[Path, dict]]:
    out = {}
    for f in sorted(lang.glob("*.json")):
        if f.stem in SKIP:
            continue
        out[f.stem] = (f, json.loads(f.read_text(encoding="utf-8")))
    return out


def compare(texts: dict, cat: dict) -> tuple[list[str], list[str]]:
    keys = {k for k in cat if not k.startswith("_")}
    missing = sorted(t for t in texts if not cat.get(t))
    unused = sorted(keys - set(texts))
    return missing, unused


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    texts, plural, problems = scan()
    print(f"{len(texts)} texts wrapped ({sum(plural.values())} with plural forms)")
    for p in problems:
        print("problem:", p)
    bad = bool(problems)
    for code, (path, cat) in catalogs().items():
        missing, unused = compare(texts, cat)
        print(f"{code}: {len(texts) - len(missing)}/{len(texts)} translated, "
              f"{len(missing)} missing, {len(unused)} unused")
        for t in unused:
            print(f"  unused: {t!r}")
        if a.update:
            for t in missing:
                if t not in cat:
                    cat[t] = ["", ""] if plural.get(t) else ""
            for t in unused:
                del cat[t]
            path.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        elif missing or unused:
            bad = True
    return 1 if a.check and bad else 0


if __name__ == "__main__":
    sys.exit(main())
