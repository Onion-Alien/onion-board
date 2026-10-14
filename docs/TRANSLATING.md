# Translating Onion Board

People pick the language in **Settings → Appearance → Language**: a drop-down
(`ui/langpick.py`) with each language in its own name and a search on top; the card's
title is in Windows' language too. It's saved as config.json's
`language` and takes effect after a restart. The board doesn't follow Windows by itself
yet (`i18n.FOLLOW_WINDOWS`, for 2.0): until a language is picked, a bar in Windows'
language offers to switch, once, if a catalog for it is shipped.

The app's text is English in the code, wrapped for translation:

```python
from soundboard.i18n import _, ngettext

QPushButton(_("Add sounds"))
self.toast(_("Added “{name}”", name=meta.name))
ngettext("{n} sound", "{n} sounds", n)
```

- `_()` takes a plain string (never an f-string or `+`): put the changing parts in
  `{placeholders}` and pass them as keyword arguments, so a translation can move them.
- `ngettext(singular, plural, n)` for text with a number in it; `{n}` is filled in.
- Don't wrap log messages, settings keys, the control API's JSON or file names. The
  changelog stays in English, and so do the older What's new notes
  (`ui/whatsnew.py`); notes for 2.0 and later are wrapped.
- Menus, pop-ups and text set later (status lines, toasts) don't show up in a
  screenshot sweep: check them in the code too.
- Don't use `_` as a throwaway name (`path, _ = …`) in a function that calls `_()`:
  write `path, __ = …`. `scripts/i18n_extract.py` and the tests catch it.

## The catalogs

`assets/lang/<code>.json`, shipped beside the app as `lang\`:

```json
{
  "_meta": {"name": "Deutsch"},
  "Add sounds": "Sounds hinzufügen",
  "Added “{name}”": "„{name}“ hinzugefügt",
  "{n} sound": ["{n} Sound", "{n} Sounds"]
}
```

- The key is the English exactly as in the code. An empty or missing translation shows
  the English.
- Plural entries are a list of forms in the order of the language's rule:
  `soundboard/i18n.py`'s `PLURALS` (each rule with a comment saying which numbers take
  which form) and `FORMS` (how many forms). Most languages have two (one, other);
  Russian, Ukrainian, Polish, Czech and Romanian three, Arabic six, and Chinese,
  Japanese, Korean, Indonesian, Malay, Vietnamese and Thai one for every number.
- Keep the app's tone: short, plain, friendly words. Keep `{placeholders}`, `<b>…</b>`
  and `&amp;` as they are.

`python scripts/i18n_extract.py` lists, per language, what's missing and what's no
longer used; `--update` adds the missing texts (empty) to every catalog and drops the
unused ones; `--check` exits 1 if anything is off. The tests check that every
translation keeps the placeholders and has the right plural forms. CI's pick job runs
`--check` too, so a change that adds or edits text translates it into every catalog
in the same change (`--update`, then fill in the new texts).

A new language: copy a catalog to `<code>.json` (a Windows language code), set
`_meta.name` to the language's own name, translate, and add its plural rule to
`PLURALS` (and its number of forms to `FORMS`) if it isn't one / other. Add it to
Onion Watch too, so the two keep the same languages.

## The languages and what's special about them

English (the code itself) and 32 translations, one catalog each in `assets/lang/`. Onion
Watch (the Triggers tab) has the same ones, with the same words for shared things.

- **Chinese** goes by region: Windows' `zh-HK`, `zh-MO`, `zh-TW` and `zh-Hant…` get
  Traditional (`zh-TW`), the rest (`zh-CN`, `zh-SG`, `zh-Hans…`) Simplified (`zh-CN`).
  A plain base-language match would send Hong Kong to Simplified (`i18n._chinese`).
- **Arabic** is written right to left (`i18n.RTL`, `i18n.is_rtl()`): the app calls
  `setLayoutDirection(Qt.RightToLeft)` at start-up, so layouts, menus and text flip.
  Add-on tabs follow the app's direction.
  Check painted widgets (bars, meters, icons) in Arabic: they don't flip by themselves.
- **Fonts**: the themes name one font (Segoe UI, Consolas, Tahoma, Comic Sans MS);
  Windows falls back for letters it hasn't got. `i18n.use_fonts()` points that
  fallback at the language's own font (`i18n.FONTS`: Microsoft YaHei UI / JhengHei UI,
  Yu Gothic UI, Malgun Gothic, Leelawadee UI, Nirmala UI), so Chinese isn't drawn with
  Japanese shapes on a Japanese PC. Offscreen screenshots need `QT_QPA_FONTDIR=C:/Windows/Fonts`
  and the `.ttc` fonts added with `QFontDatabase.addApplicationFont` (the offscreen
  font list skips them), or CJK and Hindi show as boxes.

## Checking the layout

The pseudo-language `xx` (`i18n.set_language("xx")`) shows every wrapped text as
`[Šéttîñĝš~~~]`: about 40 % longer, like German or Russian. In a screenshot, text
without brackets isn't wrapped yet and a missing `]` means the label cuts it off.
`i18n.unwrapped_texts(widget)` lists the unwrapped ones for a test.
