"""The app in other languages: `_("English text")` gives the text in the language
picked (Settings → Appearance → Language), or the English as written when there's
no translation for it.

Catalogs are JSON files, one per language, in `assets/lang/<code>.json` (shipped as
`lang/` beside the app): English text → translation. A text with a number in it
(`ngettext`) maps to a list of forms, in the order the language's plural rule
(PLURALS) numbers them. `_meta` holds the language's own name. See
docs/TRANSLATING.md; `scripts/i18n_extract.py` lists what's missing or unused.

`{name}` placeholders are filled from keyword arguments after the lookup, so a
translation can move them around: `_("Added “{name}”", name=m.name)`.

The pseudo-language `xx` turns every wrapped text into `[Šéttîñĝš~~~]`: about 40 %
longer (German and Russian run long) with accents, so text that isn't wrapped yet
stands out in a screenshot and labels too narrow for a translation get cut off
visibly. Tests and the screenshot sweeps use it; it isn't offered in the app.

Never wrap: log messages, settings keys, the control API's JSON, file names.
"""
from __future__ import annotations

import json
import locale
import logging
import re
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LANG_DIR = (Path(sys._MEIPASS) / "lang" if hasattr(sys, "_MEIPASS")
            else Path(__file__).resolve().parent.parent / "assets" / "lang")
ENGLISH = "en"
PSEUDO = "xx"
WINDOWS = ""     # Config.language: follow Windows' display language

# plural rules: n -> index into a catalog entry's list of forms (FORMS: how many)
def _one_other(n):
    return 0 if n == 1 else 1


def _slavic(n):            # ru, uk: one (1, 21, 31…), few (2-4, 22-24…), many (the rest)
    return 0 if n % 10 == 1 and n % 100 != 11 \
        else 1 if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 2


PLURALS = {
    "en": _one_other, "de": _one_other, "es": _one_other, "it": _one_other,
    "nl": _one_other, "tr": _one_other,
    "pt-BR": lambda n: 0 if n in (0, 1) else 1,
    "fr": lambda n: 0 if n in (0, 1) else 1,
    "hi": lambda n: 0 if n in (0, 1) else 1,
    "ru": _slavic, "uk": _slavic,
    # one (1), few (2-4, 22-24…, not 12-14), many (the rest)
    "pl": lambda n: 0 if n == 1
    else 1 if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 2,
    # one form for every number
    "zh-CN": lambda n: 0, "zh-TW": lambda n: 0, "ja": lambda n: 0, "ko": lambda n: 0,
    "id": lambda n: 0, "vi": lambda n: 0, "th": lambda n: 0,
    # zero, one, two, few (3-10, 103-110…), many (11-99, 111-199…), other
    "ar": lambda n: 0 if n == 0 else 1 if n == 1 else 2 if n == 2
    else 3 if 3 <= n % 100 <= 10 else 4 if 11 <= n % 100 <= 99 else 5,
}
FORMS = {"ru": 3, "uk": 3, "pl": 3, "ar": 6,
         **dict.fromkeys(("zh-CN", "zh-TW", "ja", "ko", "id", "vi", "th"), 1)}


def forms(code: str) -> int:
    """How many plural forms a catalog entry has in language `code`."""
    return FORMS.get(code, 2)


RTL = {"ar"}               # written right to left: the layout is mirrored
# the font for each script, by language: Windows finds one by itself, but on a Japanese
# PC it would draw Chinese with Japanese shapes (and the other way round)
FONTS = {"zh-CN": "Microsoft YaHei UI", "zh-TW": "Microsoft JhengHei UI",
         "ja": "Yu Gothic UI", "ko": "Malgun Gothic", "th": "Leelawadee UI",
         "hi": "Nirmala UI"}

_lang = ENGLISH
_catalog: dict[str, str | list[str]] = {}


# ------------------------------------------------------------------ looking up
def _(text: str, /, **kw) -> str:
    """`text` in the current language, its `{placeholders}` filled from `kw`."""
    if _lang == PSEUDO:
        out = pseudo(text)
    else:
        t = _catalog.get(text)
        out = t if isinstance(t, str) and t else text
    return _fill(out, kw) if kw else out


def ngettext(singular: str, plural: str, n: int, /, **kw) -> str:
    """The form for `n` ("1 sound" / "{n} sounds"); `{n}` is filled in too."""
    kw.setdefault("n", n)
    if _lang == PSEUDO:
        return _fill(pseudo(singular if n == 1 else plural), kw)
    forms = _catalog.get(singular)
    if isinstance(forms, list) and forms and all(isinstance(f, str) and f for f in forms):
        rule = PLURALS.get(_lang, PLURALS[ENGLISH])
        out = forms[min(rule(n), len(forms) - 1)]
    else:
        out = singular if n == 1 else plural
    return _fill(out, kw)


def _fill(text: str, kw: dict) -> str:
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):   # a translation with a broken placeholder
        log.warning("bad placeholder in translation %r", text)
        return text


# ------------------------------------------------------------------ languages
def current() -> str:
    return _lang


def available() -> list[tuple[str, str]]:
    """(code, the language's own name) for every catalog shipped, English first."""
    out = [(ENGLISH, "English")]
    try:
        files = sorted(LANG_DIR.glob("*.json"))
    except OSError:
        files = []
    for f in files:
        code = f.stem
        if code in (ENGLISH, PSEUDO):
            continue
        meta = _read(f).get("_meta", {})
        out.append((code, meta.get("name", code) if isinstance(meta, dict) else code))
    return out


def windows_language() -> str:
    """Windows' display language as a catalog code ("de", "pt-BR"), best effort."""
    name = ""
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                name = buf.value
        except Exception:  # noqa: BLE001
            name = ""
    if not name:
        name = (locale.getlocale()[0] or "")
    return name.replace("_", "-")


def resolve(setting: str) -> str:
    """The catalog to use for Config.language (`WINDOWS`: Windows' own, if shipped)."""
    codes = [c for c, _n in available()]
    want = setting if setting and setting != WINDOWS else windows_language()
    if want == PSEUDO:
        return PSEUDO
    if want in codes:
        return want
    chinese = _chinese(want)
    if chinese:
        return chinese if chinese in codes else ENGLISH
    base = want.split("-")[0].lower()
    for c in codes:                       # "de-AT" -> "de", "pt-PT" -> "pt-BR"
        if c.split("-")[0].lower() == base:
            return c
    return ENGLISH


def _chinese(name: str) -> str | None:
    """Windows names Chinese by region or script: Hong Kong, Macau and Traditional
    script read zh-TW, the rest zh-CN (a plain "zh" match would send Hong Kong to
    Simplified). None for other languages."""
    parts = [p.lower() for p in name.split("-")]
    if parts[0] != "zh":
        return None
    if "hant" in parts or {"hk", "mo", "tw"} & set(parts[1:]):
        return "zh-TW"
    return "zh-CN"


def is_rtl(code: str | None = None) -> bool:
    """Language `code` (default: the current one) is written right to left."""
    return (_lang if code is None else code) in RTL


def use_fonts(families) -> None:
    """After the QApplication is made: the theme fonts `families` (Segoe UI, Consolas…)
    fall back to the current language's own font for letters they haven't got."""
    own = FONTS.get(_lang)
    if not own:
        return
    from PySide6.QtGui import QFont
    for fam in families:
        if fam and own not in QFont.substitutes(fam):
            QFont.insertSubstitution(fam, own)


def set_language(code: str) -> str:
    """Switch to catalog `code` (unknown or unreadable: English). Returns the code used.
    Text already on screen stays as it was: the app asks for a restart."""
    global _lang, _catalog
    if code in (ENGLISH, PSEUDO, "", None):
        _lang, _catalog = code or ENGLISH, {}
        return _lang
    data = _read(LANG_DIR / f"{code}.json")
    if not data:
        _lang, _catalog = ENGLISH, {}
        return ENGLISH
    _lang = code
    _catalog = {k: v for k, v in data.items() if not k.startswith("_")}
    return code


def startup(app_dir: Path) -> str:
    """The language for this run, from config.json's `language` (read here, before the
    rest of the settings, so module-level text is made in it), or ONIONBOARD_LANG (for
    checking a translation or the pseudo-language `xx` from source)."""
    import os
    want = os.environ.get("ONIONBOARD_LANG")
    if want is None:
        raw = _read(app_dir / "config.json") if (app_dir / "config.json").is_file() else {}
        want = raw.get("language", WINDOWS)
        want = want if isinstance(want, str) else WINDOWS
    code = set_language(resolve(want))
    log.info("language: %s (setting %r)", code, want)
    return code


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        log.warning("can't read language file %s", path, exc_info=True)
        return {}


# ------------------------------------------------------------------ the pseudo-language
_ACCENTS = str.maketrans("aceginorsuyACEGINORSUY", "áçéĝîñöŕšûýÁÇÉĜÎÑÖŔŠÛÝ")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}|<[^<>]*>|&[a-z]+;")   # {name}, <b>, &amp;
OPEN, CLOSE = "[", "]"


def pseudo(text: str) -> str:
    """`[Šéttîñĝš~~~]`: accents on the letters (not on placeholders or markup), padded
    to about 140 % of the length, in brackets so a cut-off end shows."""
    if not text:
        return text
    parts, last = [], 0
    for m in _PLACEHOLDER.finditer(text):
        parts.append(text[last:m.start()].translate(_ACCENTS))
        parts.append(m.group(0))
        last = m.end()
    parts.append(text[last:].translate(_ACCENTS))
    pad = "~" * max(1, round(len(text) * 0.4))
    return f"{OPEN}{''.join(parts)}{pad}{CLOSE}"


def is_pseudo(text: str) -> bool:
    """`text` came through _() while the pseudo-language was on (or holds such text)."""
    return OPEN in text and "~" + CLOSE in text


def unwrapped_texts(root) -> list[tuple[str, str]]:
    """(widget class, text) of every visible label, button, box, tab and tooltip under
    the Qt widget `root` whose text didn't come through _(): with the pseudo-language
    on, that's the text still to wrap. Texts with no letters (numbers, symbols) don't
    count."""
    from PySide6.QtWidgets import (QAbstractButton, QGroupBox, QLabel, QLineEdit,
                                   QTabBar, QWidget)
    found = []

    def check(w, text):
        if text and re.search(r"[A-Za-z]{2}", text) and not is_pseudo(text):
            found.append((type(w).__name__, text))

    for w in [root, *root.findChildren(QWidget)]:
        if not w.isVisibleTo(root) and w is not root:
            continue
        if isinstance(w, (QLabel, QAbstractButton)):
            check(w, w.text())
        elif isinstance(w, QGroupBox):
            check(w, w.title())
        elif isinstance(w, QLineEdit):
            check(w, w.placeholderText())
        elif isinstance(w, QTabBar):
            for i in range(w.count()):
                check(w, w.tabText(i))
        check(w, w.toolTip())
    return found
