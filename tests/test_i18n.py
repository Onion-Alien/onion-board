"""Translations: lookup with English fallback, placeholders, plural forms, picking the
language, the pseudo-language and the extract script."""
import json

import pytest

from soundboard import i18n
from soundboard.i18n import _, ngettext


@pytest.fixture
def langs(tmp_path, monkeypatch):
    d = tmp_path / "lang"
    d.mkdir()
    (d / "de.json").write_text(json.dumps({
        "_meta": {"name": "Deutsch"},
        "Add sounds": "Sounds hinzufügen",
        "Added “{name}”": "„{name}“ hinzugefügt",
        "{n} sound": ["{n} Sound", "{n} Sounds"],
        "Untranslated": "",
    }, ensure_ascii=False), encoding="utf-8")
    (d / "ru.json").write_text(json.dumps({
        "_meta": {"name": "Русский"},
        "{n} sound": ["{n} звук", "{n} звука", "{n} звуков"],
    }, ensure_ascii=False), encoding="utf-8")
    (d / "pt-BR.json").write_text(json.dumps({"_meta": {"name": "Português (Brasil)"}}),
                                  encoding="utf-8")
    monkeypatch.setattr(i18n, "LANG_DIR", d)
    yield d
    i18n.set_language(i18n.ENGLISH)


def test_english_is_the_text_as_written():
    assert i18n.current() == "en"
    assert _("Add sounds") == "Add sounds"
    assert _("Added “{name}”", name="Boom") == "Added “Boom”"
    assert ngettext("{n} sound", "{n} sounds", 1) == "1 sound"
    assert ngettext("{n} sound", "{n} sounds", 3) == "3 sounds"


def test_a_catalog_translates_and_falls_back_to_english(langs):
    assert i18n.set_language("de") == "de"
    assert _("Add sounds") == "Sounds hinzufügen"
    assert _("Added “{name}”", name="Boom") == "„Boom“ hinzugefügt"
    assert _("Untranslated") == "Untranslated"       # empty: English
    assert _("Never seen") == "Never seen"
    assert ngettext("{n} sound", "{n} sounds", 1) == "1 Sound"
    assert ngettext("{n} sound", "{n} sounds", 5) == "5 Sounds"


def test_russian_plural_forms(langs):
    i18n.set_language("ru")
    got = {n: ngettext("{n} sound", "{n} sounds", n) for n in (1, 2, 5, 11, 21, 22, 112)}
    assert got == {1: "1 звук", 2: "2 звука", 5: "5 звуков", 11: "11 звуков",
                   21: "21 звук", 22: "22 звука", 112: "112 звуков"}


def test_a_broken_placeholder_in_a_translation_shows_it_unfilled(langs):
    (langs / "de.json").write_text(json.dumps({"Hi {name}": "Hallo {nme}"}), encoding="utf-8")
    i18n.set_language("de")
    assert _("Hi {name}", name="x") == "Hallo {nme}"


def test_unknown_or_unreadable_language_is_english(langs):
    (langs / "fr.json").write_text("{not json", encoding="utf-8")
    assert i18n.set_language("fr") == "en"
    assert i18n.set_language("zz") == "en"
    assert _("Add sounds") == "Add sounds"


def test_available_lists_each_catalog_by_its_own_name(langs):
    (langs / "xx.json").write_text("{}", encoding="utf-8")   # never offered
    assert i18n.available() == [("en", "English"), ("de", "Deutsch"),
                                ("pt-BR", "Português (Brasil)"), ("ru", "Русский")]


def test_resolve_follows_windows_and_matches_regions(langs, monkeypatch):
    monkeypatch.setattr(i18n, "windows_language", lambda: "de-AT")
    assert i18n.resolve(i18n.WINDOWS) == "de"
    monkeypatch.setattr(i18n, "windows_language", lambda: "pt-PT")
    assert i18n.resolve("") == "pt-BR"
    monkeypatch.setattr(i18n, "windows_language", lambda: "ja-JP")
    assert i18n.resolve("") == "en"
    assert i18n.resolve("ru") == "ru" and i18n.resolve("en") == "en"
    assert i18n.resolve("xx") == "xx"


def test_pseudo_language_marks_and_lengthens_but_keeps_placeholders():
    i18n.set_language(i18n.PSEUDO)
    try:
        t = _("Settings")
        assert t.startswith("[") and t.endswith("~]") and len(t) >= len("Settings") * 1.3
        assert "Šéttîñĝš" in t and i18n.is_pseudo(t)
        t = _("Added “{name}” to <b>{cat}</b>", name="Boom", cat="Memes")
        assert "Boom" in t and "<b>Memes</b>" in t and i18n.is_pseudo(t)
        assert i18n.is_pseudo(ngettext("{n} sound", "{n} sounds", 2)) \
            and "2" in ngettext("{n} sound", "{n} sounds", 2)
        assert not i18n.is_pseudo("Settings")
    finally:
        i18n.set_language(i18n.ENGLISH)


def test_unwrapped_texts_finds_text_that_skipped_the_translator(qapp):
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
    i18n.set_language(i18n.PSEUDO)
    try:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(_("Wrapped")))
        lay.addWidget(QPushButton("Not wrapped"))
        lay.addWidget(QLabel("42 %"))   # no words: fine
        b = QPushButton(_("Ok"))
        b.setToolTip("Raw tip")
        lay.addWidget(b)
        found = i18n.unwrapped_texts(w)
        assert ("QPushButton", "Not wrapped") in found and ("QPushButton", "Raw tip") in found
        assert len(found) == 2
        w.deleteLater()
    finally:
        i18n.set_language(i18n.ENGLISH)


def test_extract_finds_texts_plurals_and_a_shadowed_translator(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "i18n_extract", Path(__file__).resolve().parent.parent / "scripts" / "i18n_extract.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "a.py").write_text(
        "from soundboard.i18n import _, ngettext\n"
        "def f(n):\n"
        "    return _('Hello'), ngettext('{n} sound', '{n} sounds', n)\n"
        "def g():\n"
        "    path, _ = 1, 2\n"
        "    return _('Oops')\n"
        "def h(x):\n"
        "    return _(x)\n", encoding="utf-8")
    texts, plural, problems = ex.scan(src)
    assert set(texts) == {"Hello", "{n} sound", "Oops"} and plural["{n} sound"]
    assert any("g() assigns `_`" in p for p in problems)
    assert any("plain string" in p for p in problems)
    missing, unused = ex.compare(texts, {"_meta": {}, "Hello": "Hallo", "Gone": "Weg"})
    assert missing == ["Oops", "{n} sound"] and unused == ["Gone"]


def test_the_app_source_has_no_shadowed_translator():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "i18n_extract", Path(__file__).resolve().parent.parent / "scripts" / "i18n_extract.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    _texts, _plural, problems = ex.scan()
    assert problems == []


def test_startup_reads_the_setting_or_the_env(langs, tmp_path, monkeypatch):
    monkeypatch.delenv("ONIONBOARD_LANG", raising=False)
    monkeypatch.setattr(i18n, "windows_language", lambda: "en-NZ")
    assert i18n.startup(tmp_path) == "en"                       # no settings yet
    (tmp_path / "config.json").write_text(json.dumps({"language": "de"}), encoding="utf-8")
    assert i18n.startup(tmp_path) == "de" and _("Add sounds") == "Sounds hinzufügen"
    (tmp_path / "config.json").write_text(json.dumps({"language": 5}), encoding="utf-8")
    assert i18n.startup(tmp_path) == "en"
    monkeypatch.setenv("ONIONBOARD_LANG", "xx")
    assert i18n.startup(tmp_path) == "xx"


def test_any_placeholder_name_works():
    assert _("{text} and {singular}", text="a", singular="b") == "a and b"
    assert ngettext("{n} {text}", "{n} {text}s", 2, text="cat", plural="x") == "2 cats"


def _import_time_translations(path) -> list[int]:
    """Lines of `path` where _() / ngettext() runs when the module is imported: calls
    outside any function or lambda body (module level, class bodies, default argument
    values and decorators all run at import)."""
    import ast
    found: list[int] = []

    def visit(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("_", "ngettext"):
            found.append(node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in node.decorator_list + node.args.defaults + node.args.kw_defaults:
                if n is not None:
                    visit(n)
            return   # the body runs later
        if isinstance(node, ast.Lambda):
            for n in node.args.defaults + node.args.kw_defaults:
                if n is not None:
                    visit(n)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(ast.parse(path.read_text(encoding="utf-8")))
    return found


def test_modules_imported_before_the_language_is_picked_translate_on_use():
    """app.main imports some modules before i18n.startup(): text they translate at
    import time would stay English for good. Finds them (app.py's own imports and
    main's above the startup call, then everything those pull in) and checks none
    calls _() / ngettext() at import time."""
    import ast
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "soundboard" / "app.py").read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    startup = next(n.lineno for n in ast.walk(main) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == "startup")
    early = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    early += [n for n in ast.walk(main) if isinstance(n, (ast.Import, ast.ImportFrom))
              and n.lineno < startup]
    wanted = {"soundboard.app"}
    for n in early:
        if isinstance(n, ast.Import):
            wanted.update(a.name for a in n.names)
        elif n.module and n.module.split(".")[0] == "soundboard":
            wanted.add(n.module)
            wanted.update(f"{n.module}.{a.name}" for a in n.names)   # maybe submodules
    code = ("import importlib, sys\n"
            f"for m in {sorted(wanted)!r}:\n"
            "    try:\n"
            "        importlib.import_module(m)\n"
            "    except ImportError:\n"
            "        pass   # a name imported from a module, not a submodule\n"
            "print(' '.join(sorted(n for n, m in sys.modules.items()\n"
            "    if n.split('.')[0] == 'soundboard' and getattr(m, '__file__', None))))\n")
    env = dict(os.environ, PYTHONPATH=str(root), QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=root, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    mods = out.stdout.split()
    assert "soundboard.library" in mods and "soundboard.errors" in mods   # it found them
    bad = {}
    for name in mods:
        path = root / Path(*name.split("."))
        path = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
        if path.is_file() and (lines := _import_time_translations(path)):
            bad[name] = lines
    assert not bad, f"_() / ngettext() at import time, before i18n.startup(): {bad}"


def test_import_time_finder_sees_module_level_class_and_default_calls(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("from soundboard.i18n import _\n"
                 "A = _('a')\n"
                 "class C:\n"
                 "    b = _('b')\n"
                 "    def m(self, x=_('c')):\n"
                 "        return _('fine')\n"
                 "def f():\n"
                 "    return _('fine')\n"
                 "g = lambda: _('fine')\n", encoding="utf-8")
    assert _import_time_translations(f) == [2, 4, 5]
