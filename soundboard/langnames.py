"""Language names in the app's language ("Japanisch" in German), for the "Speak in"
list. The names come from Unicode CLDR via scripts/make_langnames.py, so adding a
language never needs a translator: add its translate-xx add-on and rerun the script."""
from __future__ import annotations

import unicodedata

from soundboard import i18n
from soundboard.langnames_data import NAMES


def name(code: str, fallback: str = "") -> str:
    """`code`'s name ("ja", "pt-BR"…) in the current app language; `fallback` (the
    add-on's own English name) when the table doesn't have it yet."""
    lang = i18n.current()
    english = NAMES["en"].get(code) or fallback or code
    if lang == i18n.PSEUDO:
        return i18n.pseudo(english)
    return NAMES.get(lang, {}).get(code) or english


def of(m) -> str:
    """A translation add-on's language name."""
    return name(m.language, m.language_name)


def sort_key(m) -> str:
    """A to Z the way people read it: "Dänisch" before "Deutsch"."""
    return "".join(c for c in unicodedata.normalize("NFKD", of(m).casefold())
                   if not unicodedata.combining(c))
