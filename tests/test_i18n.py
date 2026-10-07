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


def test_plural_rules_pick_the_right_form():
    pl, ar, ja = i18n.PLURALS["pl"], i18n.PLURALS["ar"], i18n.PLURALS["ja"]
    assert [pl(n) for n in (1, 2, 5, 12, 22, 25)] == [0, 1, 2, 2, 1, 2]
    assert [ar(n) for n in (0, 1, 2, 3, 11, 100)] == [0, 1, 2, 3, 4, 5]
    assert {ja(n) for n in (0, 1, 2, 5, 100)} == {0}
    # every rule stays inside its language's number of forms
    assert set(i18n.FORMS) <= set(i18n.PLURALS)
    for code, rule in i18n.PLURALS.items():
        assert {rule(n) for n in range(250)} == set(range(i18n.forms(code))), code


def test_chinese_follows_the_region_not_just_the_language(langs, monkeypatch):
    for code in ("zh-CN", "zh-TW"):
        (langs / f"{code}.json").write_text(json.dumps({"_meta": {"name": code}}),
                                            encoding="utf-8")
    for name in ("zh-TW", "zh-HK", "zh-MO", "zh-Hant", "zh-Hant-HK", "zh-Hant-TW"):
        assert i18n.resolve(name) == "zh-TW", name
    for name in ("zh-CN", "zh-SG", "zh", "zh-Hans", "zh-Hans-SG"):
        assert i18n.resolve(name) == "zh-CN", name
    monkeypatch.setattr(i18n, "windows_language", lambda: "zh-HK")
    assert i18n.resolve(i18n.WINDOWS) == "zh-TW"
    (langs / "zh-TW.json").unlink()      # no Traditional catalog: English, not Simplified
    assert i18n.resolve("zh-HK") == "en"
    assert i18n.resolve("de-AT") == "de"


def test_arabic_is_right_to_left(langs):
    assert i18n.is_rtl("ar") and not i18n.is_rtl("de") and not i18n.is_rtl()
    (langs / "ar.json").write_text(json.dumps({"_meta": {"name": "العربية"}},
                                              ensure_ascii=False), encoding="utf-8")
    i18n.set_language("ar")
    assert i18n.is_rtl()


def extract_script():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "i18n_extract", Path(__file__).resolve().parent.parent / "scripts" / "i18n_extract.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    return ex


def test_every_shipped_catalog_keeps_the_placeholders():
    """Each language in assets/lang: every translation it has keeps the English's
    {placeholders} and markup and has the right number of plural forms. A text not
    translated yet (newly wrapped: `i18n_extract.py --update` adds it empty) shows the
    English, so wrapping more text never waits on 19 translations. The same languages
    as Onion Watch, so the Triggers tab reads like the rest of the board."""
    import re
    ex = extract_script()
    texts, plural, _problems = ex.scan()
    cats = ex.catalogs()
    assert set(cats) == {"de", "es", "fr", "pt-BR", "ru", "zh-CN", "zh-TW", "ja", "ko",
                         "hi", "id", "vi", "th", "tr", "it", "pl", "uk", "nl", "ar"}
    ph = re.compile(r"\{[^{}]*\}|<[^<>]*>|&[a-z]+;")
    for code, (_path, cat) in cats.items():
        assert isinstance(cat["_meta"].get("name"), str), code
        for key, value in cat.items():
            if key.startswith("_") or key not in texts or not value:
                continue
            assert isinstance(value, list) == plural[key], (code, key)
            for v in value if isinstance(value, list) else [value]:
                if v:
                    assert set(ph.findall(v)) == set(ph.findall(key)), (code, key, v)
            if plural[key] and all(value):
                assert len(value) == i18n.forms(code), (code, key)


def test_qt_standard_buttons_follow_the_language(qapp, langs):
    from PySide6.QtWidgets import QDialogButtonBox
    i18n.set_language(i18n.PSEUDO)
    try:
        assert i18n.translate_qt_buttons(qapp)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        assert all(i18n.is_pseudo(b.text()) for b in box.buttons())
        i18n.set_language(i18n.ENGLISH)          # back in English: Qt's own words again
        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        assert box.buttons()[0].text() == "Cancel"
    finally:
        i18n.set_language(i18n.ENGLISH)
