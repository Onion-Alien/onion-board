"""Which language you speak to the live voice (speech recognition), from the app's own.

Speech recognition (Whisper, in the live-voice add-on) hears the languages in
`WHISPER`. The translation add-ons go from English to another language, so a line
said in any other language is first turned into English by Whisper itself (its
"translate" task), then into the language picked.
"""
from __future__ import annotations

import re

from soundboard import i18n

# the languages Whisper's multilingual models hear (its own codes)
WHISPER = frozenset(
    "af am ar as az ba be bg bn bo br bs ca cs cy da de el en es et eu fa fi fo fr gl gu "
    "ha haw he hi hr ht hu hy id is it ja jw ka kk km kn ko la lb ln lo lt lv mg mi mk ml "
    "mn mr ms mt my ne nl nn no oc pa pl ps pt ro ru sa sd si sk sl sn so sq sr su sv sw "
    "ta te tg th tk tl tr tt uk ur uz vi yi yo yue zh".split())

# an app (or add-on) language code whose Whisper code isn't its first part
_ALIASES = {"fil": "tl", "nb": "no", "iw": "he", "in": "id"}

# the English-only recognition models, and the one that hears every language instead.
# The default (base.en) becomes small: base turns other languages into English much
# worse ("the station" for "the bomb site"), small takes ~1.3 s a line on a CPU
# instead of ~0.4 s. Fastest stays fast.
MULTILINGUAL = {"tiny.en": "base", "base.en": "small", "small.en": "small"}


def whisper_code(code: str | None) -> str | None:
    """`code` ("pt-BR", "zh-TW", "fil", "es-419"…) as Whisper's, or None when
    Whisper doesn't hear that language."""
    base = re.split(r"[-_]", str(code or "").strip().lower(), maxsplit=1)[0]
    base = _ALIASES.get(base, base)
    return base if base in WHISPER else None


def app_language() -> str | None:
    """The language the app is shown in, as Whisper's code (None: it doesn't hear it)."""
    return whisper_code(i18n.current() or "en")


def heard() -> bool:
    """Whether speech recognition hears the app's language (the Languages tab needs it)."""
    return app_language() is not None


def typed(settings: dict) -> str:
    """What's typed in as the language you speak: "spoken" in the speech settings, a
    code or "auto"; empty for the app's language. Before it, "language" held it with
    "en" as the default, so an old "en" follows the app's language too."""
    if "spoken" in settings:
        return str(settings["spoken"] or "").strip().lower()
    s = str(settings.get("language") or "").strip().lower()
    return "" if s == "en" else s


def spoken(settings: dict) -> str:
    """The language to listen for (Whisper's code, or "auto"), from the speech settings."""
    s = typed(settings)
    if s == "auto":
        return s
    return (whisper_code(s) if s else None) or app_language() or "en"


def model_for(model: str, language: str) -> str:
    """The recognition model to load: an English-only one can't hear anything else."""
    return model if language == "en" else MULTILINGUAL.get(model, model)


def same(target: str | None, language: str) -> bool:
    """Whether a translation add-on's language (`target`) is the one you speak."""
    return whisper_code(target) == language
