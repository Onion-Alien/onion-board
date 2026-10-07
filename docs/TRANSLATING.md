# Translating Onion Board

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
- Plural entries are a list of forms in the order of the language's rule
  (`soundboard/i18n.py` → `PLURALS`): English, German, Spanish: one, other; French and
  Portuguese (Brazil): 0–1, other; Russian: one, few, many.
- Keep the app's tone: short, plain, friendly words. Keep `{placeholders}`, `<b>…</b>`
  and `&amp;` as they are.

`python scripts/i18n_extract.py` lists, per language, what's missing and what's no
longer used; `--update` adds the missing texts (empty) to every catalog and drops the
unused ones; `--check` exits 1 if anything is off.

## Checking the layout

The pseudo-language `xx` (`i18n.set_language("xx")`) shows every wrapped text as
`[Šéttîñĝš~~~]`: about 40 % longer, like German or Russian. In a screenshot, text
without brackets isn't wrapped yet and a missing `]` means the label cuts it off.
`i18n.unwrapped_texts(widget)` lists the unwrapped ones for a test.
