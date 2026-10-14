"""What the app using the style kit plugs in: the current theme and translation.

The app's theme module calls connect() once, at import. Until then (a script or test
that only imports the kit) the kit draws in Dark and in English.
"""
from __future__ import annotations

from collections.abc import Callable


def _palette() -> dict[str, str]:
    from .palettes import DEFAULT, THEMES
    return THEMES[DEFAULT]


def _theme_name() -> str:
    from .palettes import DEFAULT
    return DEFAULT


def _tr(text: str, /, **kw) -> str:
    return text.format(**kw) if kw else text


palette: Callable[[], dict[str, str]] = _palette   # the current theme's colours (`T`)
theme_name: Callable[[], str] = _theme_name        # its name (picks Bun's outfit)
tr: Callable[..., str] = _tr                       # the app's translation, as i18n._


def connect(*, palette=None, theme_name=None, tr=None) -> None:
    """Plug in the app's own: `palette()` -> the current theme's colours, `theme_name()`
    -> its name, `tr(text, **kw)` -> `text` in the user's language."""
    g = globals()
    for key, fn in (("palette", palette), ("theme_name", theme_name), ("tr", tr)):
        if fn is not None:
            g[key] = fn


def _(text: str, /, **kw) -> str:
    """Translate through the app (the kit's modules import this as `_`)."""
    return tr(text, **kw)
