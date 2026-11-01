---
# Onion Board design system: the machine-readable part.
# Colour values live in soundboard/style/palettes.py (theme.THEMES): 33 themes (not 2 or 3: every
# one is shipped and picked by real people) share these token NAMES, so code always
# uses a token, never a hex value. The prose below says how; section 6 says how to check.
name: Onion Board
version: 3
platform: PySide6 (Qt Widgets), styled by one app style sheet (theme.stylesheet)
font:                 # THE type scale: these 7 sizes only (see "Standard kit")
  family: "Segoe UI (a theme may swap it with its `font` token)"
  caption: 8pt          # QPushButton#small, badges, counts on chips
  hint: 8.5pt           # QLabel#hint: explanations, secondary lines
  body: 10pt            # everything, unless a role here says otherwise
  section: 10pt 600     # QLabel#section: card and group headings
  large: 11pt 600-700   # tile / pack / tab-card names; body text of full-page guides
  title: 13pt 700       # a dialog's one question, #helptitle, the wordmark
  display: 17pt 800     # a full-page guide's step title (wizardkit TITLE_CSS)
  number: 28pt 600      # one big live number (the recording timer)
  digits: same-width (tabular); live numbers via panel.steady_number()
button:               # THE button kinds and sizes (see "Standard kit")
  kinds: default, primary, quiet, danger, danger+quiet, small, iconbutton
  text_button: padding 7px 12px, 10pt, about 32px tall, as wide as its words
  small_button: "#small: padding 2px 8px, 8pt, about 22px tall; dense rows only"
  icon_button: 28px square, 18px glyph (24px + 16px glyph in dense rows, 36px in bars)
colour_roles:          # token names in theme.THEMES; values change per theme
  background: bg
  surface: panel        # cards (QFrame#card, #setcard), bars
  surface_raised: card_hi   # hover, selected, a box inside a card
  button: btn / btn_hover / btn_press
  item_hover: item_hover # a hovered menu / dropdown row (worked out per theme: always shows)
  text: text, text_hi (titles), muted (secondary), faint (disabled-looking)
  heading: section
  accent: accent / accent_hi / on_accent / accent_text   # main action, on-state, Live, playing; accent_text: as text or an icon on a surface
  accent2: accent2      # the logo's second colour, gradients only
  status: ok_text, warn_text / warn_bg, error_text, danger_* (destructive buttons)
radius:
  control: 8px          # buttons, boxes
  small: 6px            # spin boxes, list items, menu items
  card: 12px            # cards, bars, tiles, dialogs' inner boxes
  pill: 15px            # Live, pills, chips (fully round ends)
spacing:               # multiples of 4 (Fluent's 4px ramp)
  unit: 4px
  in_row: 8px           # between buttons in a row (settings._button_row: Flow(gap=8))
  in_card: 8px          # between rows inside a card
  card_padding: 14px sides, 12px top, 14px bottom   # settings._card
  dialog_padding: 16-18px
  between_cards: 12-16px
  dropdown_gap: 8px     # a dropdown's list / a button's menu and its button (wheelguard.DROP_GAP)
size:
  dialog_max_width: 620px
  dropdown_max_width: 360px
  icon_button: 28px square (24 dense rows, 36 = CONTROL_H in bars); nothing else
  control_height: 36px  # panel.CONTROL_H: toolbar buttons, search box, play/stop
  bar_height: 48px      # panel.BAR_H: the Sounds toolbar and every bottom bar
  interface_size: 80-150%  # Settings > Appearance; Qt scales it all, so sizes stay in px
  focus_ring: always visible on keyboard focus
---

# Onion Board design system

How every screen, card, dialog and button in Onion Board should look and behave.
Read this before building or changing any UI. It is written for people and for AI
coding agents alike: the rules are meant to be followed literally. When a rule here
and an older screen disagree, this file wins for new work; don't restyle old screens
in passing unless the task is about them.

The style is **quiet and compact**: surfaces in the theme's colours (with the theme's own
faint texture unless the user picks Plain), no resting
outlines, controls only as big as their words, one accent-coloured thing that says
"do this" or "this is on". The app should look designed, not generated.

## Standard kit: text sizes, buttons, pop-ups (read this first)

These are the only sizes and parts new UI may use. Pick from these lists; never
invent an in-between size ("10.5pt looks nicer here") or a one-off look for one
screen. If something truly can't be built from the kit, add the new part to
`theme.py` **and to this section** in the same PR, so the next screen reuses it.

Older code still has off-scale sizes (7pt, 9pt, 9.5pt, 10.5pt, 12pt, 15pt, 19pt and
22-36 px icon buttons in between). They are debt: never copy a size from old code, copy it from here.

### Text sizes

| Role | Size | How to get it | Use for |
| --- | --- | --- | --- |
| Caption | 8pt | `QPushButton#small`, a badge | small buttons, counts, badges |
| Hint | 8.5pt, `muted` | `panel.hint_label(text)` (`QLabel#hint`) | the line under a heading, secondary lines, empty-state help |
| Body | 10pt | nothing: the default | everything else |
| Section | 10pt, weight 600 | `panel.section_label(text)` (`QLabel#section`) | card and group headings |
| Large | 11pt, weight 600-700 | the tile's object name (`#tabcardtitle`) | a tile's or pack's name; body text of a full-page guide |
| Title | 13pt, weight 700 | `QLabel#helptitle` | a dialog's one question; at most one per dialog page |
| Display | 17pt, weight 800 | `setupwizard.TITLE_CSS` | the step title of a full-page guide (setup, reset, chat guide) only |
| Number | 28pt, weight 600 | the recording timer's style | one big live number per screen, with `steady_number()` |

- Hierarchy comes from **weight and colour first, size second**: a heading is body
  size in weight 600, a secondary line is `muted`. Most screens need only hint, body
  and section.
- Set sizes in the app style sheet (`themesheet.py`) by object name. **No `font-size` in widget
  code** and no `setPointSizeF(…)` with a literal. If a role has no generic object
  name yet, add one to the style sheet (e.g. `QLabel#title`) and use it.
- Sizes are in pt so the *Interface size* setting (80-150%) and Windows scaling
  stretch everything evenly. Never px for text.
- Emoji used as pictures are pictures, not text: size them like icons.

### Buttons

Every button is one of these kinds. Don't add a new `QPushButton#name` to change a
button's look; an object name on a button is for finding it in tests and for the
kinds below.

| Kind | Code | When |
| --- | --- | --- |
| Primary | `b.setObjectName("primary")` | the one thing most people should press: **at most one per card, dialog page or bar** |
| Default | plain `QPushButton(_("…"))` | other actions with words |
| Quiet | `b.setProperty("quiet", True)` | secondary actions that shouldn't draw the eye; no fill until hover |
| Danger | `b.setObjectName("danger")` | removes or resets something; add `quiet` when it sits in a list row |
| Small | `b.setObjectName("small")` | an action inside a dense row (a list item, a chip); never a card's main action |
| Icon | `b.setObjectName("iconbutton")`, `quiet`, `icons.set_icon(b, "name")`, `setToolTip` + `setAccessibleName` | any action a picture says (section 4) |
| Toggle | `b.setCheckable(True)` (fills with the accent when on) | a feature's on/off (`#power`); a mode in an exclusive `QButtonGroup` |
| Nudge | `b.setProperty("nudge", True)` + repolish, icon in `"accent"` (accent edge, wash and words) | an off switch people miss while what it controls is running (the radio's *Send to others* while a station plays to only you); drop it the moment it's on or nothing runs |
| Page tab | `#voicetab`: checkable, icon + name, in a `Flow`, an exclusive `QButtonGroup` (semi-bold always, so picking one never changes its width; `live` property: that page is on) | a tab's own pages, one card shown at a time (the Voice tab) |

Sizes (the theme gives them; don't override):

| Button | Size | Notes |
| --- | --- | --- |
| Text button (primary, default, danger) | about 32 px tall (padding 7/12 px), as wide as its words | never `setFixedWidth` / `setMinimumWidth` on a text button: German is 30% longer |
| Small | about 22 px tall (padding 2/8 px, 8pt) | |
| Guide button | about 38 px tall (padding 9/20 px, 11pt, 10 px corners): `b.setProperty("guide", True)` | a full-page guide's Back / Next only (setup, reset); the Large text role matches the guide's body |
| Icon button, normal | `setFixedSize(28, 28)`, 18 px glyph (`set_icon`'s default) | cards, dialogs, menus' anchors |
| Icon button, dense | `setFixedSize(24, 24)`, `set_icon(b, name, size=16)` | list rows, chips; 24 px is the WCAG minimum, never smaller |
| Bar control | height `panel.CONTROL_H` (36) inside a `panel.BAR_H` (48) bar | the Sounds toolbar, player and bottom bars only |

Labels: one to three words, sentence case, a verb for actions ("Save", "Add sounds",
"Delete"), never "OK" or "Yes"/"No".

Rows of buttons: `Flow(gap=8)` (`settings._button_row()`) or an `QHBoxLayout` with
spacing 8, buttons at their own width, then `addStretch(1)`.

### Choice tiles, fold pills, status cards

| Part | Code | When |
| --- | --- | --- |
| Choice tile | `choicetile.ChoiceTile(name, icon, w, h)` in a `QGridLayout` (spacing 12) | picking one of a few things that have a picture (devices, what the app is for): fixed-width tiles as tall as the longest name needs (`setupwizard.tile_h`: no empty band round a short name), the picked one tinted, ringed and ticked (same name weight: picking never rewraps it); never full-width radio rows |
| Fold pill | `choicetile.FoldPill(words, icon)` + a `QFrame#card` under it, shown when checked | a tip most people don't need: as wide as its words, chevron right after them |
| Status card | `setupwizard.StatusCard`: badge, bold line, words, pill | "is it working?" in a guide: tinted ok / warn / busy, never a coloured word at the start of a sentence |
| Filter chip | `QPushButton#filterchip`, checkable, in a `Flow(gap=8)` and an exclusive `QButtonGroup` | narrowing a grid by kind (Free packs): round pill, the picked one in the accent; "All" first |
| Emoji tile | `QLabel#packart` with `packsdialog.emoji_art()` | an emoji standing for a thing (a pack): drawn as a picture on a soft accent square, 44 px on a card |

Keep a page's cards and tiles on the dialog's own edges (no extra page inset): their
left edge is the button row's left, their right edge its right. A card in a page's column
(a test sound, a status) spans it, never stops at its words' width. A guide's header (title,
words, Bun) ends where its words do: Bun top-aligned and no taller than them, then one
fixed gap (`HEADER_GAP`) to what's below; the parts under it share one gap
(`SECTION_GAP`). Side-by-side tiles share their row: one left alone fills it.

### Pop-ups, messages and modals: one way for each job

| Job | Use | Never |
| --- | --- | --- |
| Tell the user something worked or failed | `busy.toast(window, _("…"), "ok" / "warn" / "error")` | `QMessageBox.information` / `.warning` for news |
| An error the user fixes right there | a `QLabel#hint` under the control with `theme.set_tone(lbl, "error")` | a pop-up that hides the control |
| Removing something a person made | do it at once, then offer **Undo** (`panel.UndoBar` or `toast(..., action=(_("Undo"), fn))`), into Recently deleted | "Are you sure?" for something that can be undone |
| Something that can't be undone (delete for good, reset everything) | a small modal dialog: the consequence in words, `[Delete for good] [Cancel]`, the verb on a `#danger` button | `QMessageBox.question` with Yes/No |
| Explain how something works | an ⓘ icon button opening an anchored help pop-up; Esc / click outside closes | a paragraph on the card, a modal |
| Walk a new user through a tab once (do the thing) | `coach.Tour` with `coach.Step`s (`ui/setup/coach.py`): the window dims, what to use sits in the yellow ring, one card (Bun, step dots, title, one line, its button) points at it; `Not now` only on the action step | two bubbles or panels at once, a tour that any click dismisses |
| A card's few extra actions | quiet buttons in the card's own button row | a ⋯ menu that hides two or three options |
| Many actions on an item in a list | right-click `QMenu`, plus a ⋯ icon button (`widgets.DropdownMenu`) with the same actions | actions only on right-click |
| Ask a short question or a choice | a small `QDialog` (the dialog recipe below) | a chain of message boxes |
| Something about the whole app that needs a click (an urgent fix, "Set up for it?", a missing helper, the language offer, the survey) | a **top bar**: `TopBar` (`ui/kit/topbar.py`), see *Top bars* below | a hand-built `QFrame` bar, a banner without ✕, two bars at once |
| A long editor or tuning panel | a retained **modeless** `QDialog`: create once, `show()` + `raise_()`, changes apply live, `[Done]` closes | a modal that blocks sounds and hotkeys |

### Top bars

Every bar across the top of the window is a `TopBar`, so they all look the same:

- The panel's surface, 8 px corners, a 4 px stripe on the left in the bar's **tone**:
  `info` (the accent), `warn` (amber: something stops sounds working), `ok` (green: done).
  The icon on the left is drawn in the same colour.
- The words: `set_message(text)` makes the first sentence a **bold heading** and the rest
  quieter text after a gap, wrapping onto more lines when the window is narrow. However
  many lines, the icon, the buttons and the ✕ stay centred on the bar. Put anything else
  (a progress bar, a text box) under the words with `add_row`.
- Buttons from `add_button`, all 28 px tall: at most one primary, last before the ✕.
  Every bar has a ✕ (`bar.close_btn`); it hides the bar.
- One bar at a time (`MainWindow.TOP_BARS`), and none while a game is in front.

**Modal or not:** modeless (`show()`) is the default, so sounds keep playing and
hotkeys keep working. Modal (`open()` + the `finished` signal) only when the app can't
go on without the answer. Keep a reference to the dialog and check its owner still
exists in callbacks after it closes. A modeless window never steals focus back while
the user works elsewhere. New code doesn't use `exec()` (it runs a nested event loop:
callbacks fire after the dialog's owner is gone); old `exec()` calls stay until someone
reviews their lifecycle.

### Dialog anatomy (every dialog looks like this)

```
┌───────────────────────────────── ≤ 620 px ─┐
│  Title: the one question (13pt, bold)       │  18 px margins all round
│  Hint: one or two plain lines (8.5pt, muted)│  12 px between blocks
│                                             │
│  [content: choices, fields, a list]         │
│                                             │
│                       [Main action] [Cancel]│  stretch, then main first
└─────────────────────────────────────────────┘
```

- Window title = the same words as the title, sentence case.
- Width: as narrow as its content, `setMaximumWidth(620)`; height fits the content
  (`fit.watch(self)` grows it for long translations). Never as wide as the main window.
- Footer: `addStretch(1)`, then the main action (`#primary`, `setDefault(True)`), then
  Cancel / Done / Close. Mirrors itself in right-to-left languages. Don't use
  `QDialogButtonBox` in new code: it reorders buttons per platform.
- Esc = Cancel (or Done for live settings). Closing returns focus to whatever opened it.
- Two steps = two pages in one `QStackedWidget`, not a second dialog (feedbackdialog).

```python
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from soundboard.i18n import _
from soundboard.ui.kit import fit, panel


class RenameDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Rename the sound"))
        self.setMaximumWidth(620)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        title = QLabel(_("Rename the sound"))
        title.setObjectName("helptitle")            # the Title role
        v.addWidget(title)
        v.addWidget(panel.hint_label(_("This is the name on its tile.")))
        # ... content ...
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        save = QPushButton(_("Save"))
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(save)
        row.addWidget(cancel)
        v.addLayout(row)
        fit.watch(self)

# modal only if the app needs the answer; otherwise dlg.show()
dlg = RenameDialog(window)
dlg.finished.connect(lambda code: ...)   # check the owner still exists first
dlg.open()
```

### Card recipe

```python
card, v = SettingsDialog._card(_("Recording"), _("What the Record button captures."))
# = QFrame#setcard, margins 14/12/14/14, spacing 8, QLabel#section + QLabel#hint
# then: an icon before the heading, a status pill, tiles or a meter (section 5),
# controls at their own width, a Flow(gap=8) row of buttons, addStretch(1).
```

Outside Settings, copy the same numbers onto a `QFrame#card`. Cards never set their
own background, border or font sizes: the theme paints them.

### Spacing, corners, colours

Spacing comes from this list only: 4, 8 (in rows and cards), 12 (between blocks),
14 (card padding), 16, 18 (dialog margins), 24. Corners: 8 px buttons and boxes, 6 px small items, 12 px cards, 15 px pills.
Colours: only theme tokens (section 6). All of these are in the token block at the
top of this file.

## 0. Foundation and decisions before drawing

Use **Microsoft Fluent 2 interaction guidance, implemented with our existing
PySide6 widgets**. `theme.py`, painted icons and shared UI helpers are the component
implementation. This file is the app's single design contract. The web examples
linked below explain behaviour; they are not dependencies to embed. Our compact
geometry, themes, bottom-right dialog actions and existing wording take precedence where
Fluent examples differ. New UI must follow these decisions; older UI is migrated
in small changes.

### Choose the control by the user's task

| Task | Default control and rule |
| --- | --- |
| Turn one setting on/off | Labelled `QCheckBox`. Reuse an existing `#power` checkable button for a feature's main on/off action. Do not introduce a third switch style. |
| Pick one of 2-5 choices that need comparison | A labelled exclusive group. Use radio tiles for choices with icons or explanations; compact `QRadioButton`s suit short technical options. |
| Pick a frequent short mode in a toolbar | Exclusive checkable buttons in `QButtonGroup`; match the existing mode controls. Give the group a label and keyboard selection. |
| Pick from a long or changing list | `QComboBox`, with a persistent label, meaningful selected value and width cap. Devices, languages and voices belong here. Use a dropdown for a small group only when space demands it. |
| Pick several independent options | Labelled checkboxes. Never radio buttons or an exclusive button group. |
| Execute an action | `QPushButton`; one primary action, secondary actions quiet. A dropdown changes a value; a menu offers actions. |
| Set a bounded number | Slider with a steady visible value; use a spin box where precise entry matters. |

Different controls are intentional only when their tasks differ. Keep comparable
choices in the same feature family consistent. An exclusive group must stay
exclusive when restyled; verify arrows, Tab, Space and visible selected state.
Custom button tiles need the keyboard behaviour of the radio choice they replace.

### Choose the surface and save behaviour

| Task | Default surface and contract |
| --- | --- |
| A few extra settings for the current card | A labelled inline disclosure, immediately after that card's main controls. Keep its common controls visible. |
| A long editor or tuning while using the app | A retained modeless `QDialog`: reuse/raise it, apply live settings immediately, close without undoing them. |
| Short secondary actions | Quiet buttons in the card's own row. A list item with many actions: a right-click `QMenu` and a ⋯ `DropdownMenu` offering the same ones. |
| Brief explanation | Anchored help popup; Escape/outside click closes it and focus returns to its opener. |
| Edit an item as a transaction | Draft changes with `[Save] [Cancel]`; Cancel/Escape discards the draft. Preview must not persist edits. Modeless is preferred if the owning item can safely remain editable. |
| A required decision or irreversible operation | A modal dialog with a specific action and Cancel. Explain the consequence; prefer Undo/recently deleted for reversible removal. |
| General app preferences | Modeless settings, applied immediately, `[Done]` to close. No Save, Apply or Cancel implying rollback. |

Modal or modeless: the *Modal or not* rule in the kit above. Escape follows the same
contract as Cancel/Done, and closing a popup restores focus to its opener.

### Action rows and labels

Place dialog actions at the **bottom-right**, with stretch before the action group.
The main action is first within that group, then alternatives and Cancel/Done/Close:
`stretch [Save] [Cancel]`, `stretch [Send] [Cancel]`, or `stretch [Done]`.
The group mirrors to bottom-left in right-to-left languages. Preview/reset tools
stay beside what they affect. This rule applies to dialog footer actions, not to
ordinary fields, card controls or toolbar actions. Do not let
`QDialogButtonBox`'s platform ordering silently override this app's action order.
Use Save for a draft commit, Cancel for discarding a draft, Done for closing live
settings and Close for information. A destructive action uses its verb and `#danger`.
Menus use short verbs, separators between groups and checkmarks for current values.
Do not hide an action solely behind right-click; provide a keyboard or visible entry.

Primary references: Fluent 2 [radio groups](https://fluent2.microsoft.design/components/web/react/core/radiogroup/usage/),
[dropdowns](https://fluent2.microsoft.design/components/web/react/core/dropdown/usage),
[buttons](https://fluent2.microsoft.design/components/web/react/core/button/usage/),
[dialogs](https://fluent2.microsoft.design/components/web/react/core/dialog/usage),
and Qt's [QDialog lifecycle](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QDialog.html).

## 1. The best screens to copy

These are the current reference points. Copy their structure before inventing a new one.

| Screen | What it gets right |
| --- | --- |
| Sounds tab board (`ui/window/mainwindow.py`, pads) | Fixed-size tiles in a grid that scrolls down; picture, name, hotkey badge, length; one accent main button (*Add*, a menu of every way in), the rest quiet. |
| Setup guide (`ui/setup/setupwizard.py`) | One question per step in a big title, a short plain explanation, choices as large icon rows, the mascot for warmth, one main button. |
| Setup tab cards | A grid: your mic and Who's listening side by side in one row (always the same height, titles on one line), Devices and Connect your chat under your mic, Equalizer and volume under Who's listening. Every card open, built with `card()` (heading from `heading_row()`): they fit the screen, so nothing folds away. |
| Left tab rail (`ui/window/sidebar.py`) | Icons only when closed, names when open, the selected tab a soft accent fill, settings at the foot. |
| Send feedback box (`ui/kit/feedbackdialog.py`) | The small-dialog pattern: title question, hint, tick boxes, buttons bottom-right with the main one first, a second page instead of a second dialog. |
| Bottom strip / player bar | One slim bar: icon, slider, steady number. No boxes around each part. |

## 2. Layout

- **Narrow by default.** Every control is as wide as its content: buttons as wide as
  their words, dropdowns as wide as their longest choice (capped at 360 px), then
  `addStretch(1)`. Only a control that holds long free text (search, a path, a slider,
  a text line) may stretch. On a full-screen window only the search box is capped
  (`SEARCH_MAX_W`, 480 px); the seek bar, the meter and the drop box keep following the
  window on purpose (a longer seek bar seeks finer). Don't cap them.
- **Dialogs**: see *Dialog anatomy* above. A multi-step dialog shrinks to the
  current page (see feedbackdialog).
- **Grids** use few columns of fixed-size tiles and scroll down; never spread tiles
  out to fill the width.
- **Cards** (`QFrame#card` / `#setcard`) group related things: heading (`QLabel#section`),
  an optional one-line `QLabel#hint`, then the controls. One idea per card. If two cards
  could be one, make one: fewer sections beats more. Cards must look designed, not
  like a form: see *Cards that look designed* below.
- **Breathing room: nothing touches an edge.** A card's pieces sit at least its
  padding (14 px, `card()`) inside its edge; a scrolling list's items end 8 px before
  its scroll bar (a right margin of 8 on the list's layout), and the scroll bar sits
  inside the card's padding, never on its border. Rows in a list have 4 px between
  them. This keeps coming back in pop-ups and lists built by hand, so it's tested:
  any test that builds a card or a scrolling list calls
  `uicheck.assert_breathing_room(widget)` (`tests/uicheck.py`), filled with enough
  items to scroll, and the pictures are checked zoomed in at the right edge.
- Long text wraps (`setWordWrap(True)`); it never widens the layout.
- No huge empty gaps and no sideways scroll bars at any size in section 6's *Window*
  row.
- Right-to-left languages mirror automatically; don't hard-code left/right positions
  in painting code without checking `layoutDirection()`.
- The sidebar's inner edge drags between three states, with nothing in between:
  shut below halfway (one centred icon column), mid from halfway (names; what doesn't
  fit is hidden or kept small) and full once everything fits (`sidebar._full_fit`). It
  never grows wider than the full rail. Keep the named expand/collapse button as the
  keyboard alternative.

## 3. Buttons

- Dialog action rows: section 0, *Action rows and labels*.
- **At most one filled button** (`setObjectName("primary")`) per card or dialog: the
  thing most people should press. Everything else is a plain button or a quiet one
  (`setProperty("quiet", True)`: no background until hover). The filled button is the
  one surface that isn't flat: the theme paints it a gradient from `accent` into
  `accent2` with a light top rim (`POLISH_STYLE`, `_accent_shades`), so don't give it
  its own `background`.
- Destructive actions use `#danger`, and anything that removes something a person
  made goes through Undo or the Recently deleted bin (`trash.py`, `ui/sounds/deleted.py`,
  `panel.UndoBar`), not a one-click loss. Keep "are you sure?" for deleting for good.
- **Icon-only buttons** wherever the picture says it (section 4). The words become
  the accessible name (`setAccessibleName`), and the tooltip only when the picture
  needs them. **No tooltip that repeats what's on screen**: not on ▶ ■ ⏭ ✕ ← 📁 copy
  or a star, not on a button or switch beside words that already say it ("Chipmunk"
  → "Sound like: Chipmunk"), not on a label that shows its whole text. A tooltip
  says something new (a size, what's kept, a shortcut) or isn't there
  (`icon_button(..., hover=False)`, `Switch(..., hover=False)`). Icons
  come from the app's own painted set (`ui/kit/icons.py`, `icons.set_icon`); add new ones
  there in the same style, never an image file.
- **Keep words** on the main action of a card and on anything a new user must
  understand to get started.
- A button that starts slow work doesn't disable itself (focus would jump to the next
  control). Use `busy.set_busy` / `busy.run_busy` / `busy.hold`.
- Links open with `busy.open_url(...)` so a failure shows a toast with the address.
- Add / + buttons go right after the last item (like a browser's new-tab button),
  never before the first.

## 4. Icons and pop-ups instead of long buttons

- **Icon and text alignment** (Fluent 2, Material 3 and Apple's lists agree on this).
  Model: the sidebar's Sound output card (`OutputBlock` in `ui/window/onaircard.py`).
  - **One icon column.** Icons in a stack of rows share one fixed-width column (16 px
    in cards, the tab icon size on the rail), centred on one line. A card inside a
    column of nav items puts its icons on the nav icons' centre line.
  - **One text keyline.** Every line of words in the group starts at the same x: the
    icon column plus one gap (6-8 px, the same gap on every row). A line with no icon
    of its own (a "Set up" action, a hint, a second line) starts on the keyline too,
    never under the icons.
  - **Centre the icon on the cap height of the first line**, not on the label's box.
    A box centre drifts with line height, descenders and wrapping; the cap height is
    what the eye reads. Wrapped text keeps the icon (and a trailing chevron) on its
    first line, so top-align the row and offset the icon from the font metrics
    (`OutputBlock._pin`: `ascent - capHeight / 2`), never a hand-tuned margin.
  - **Trailing controls** (a switch) centre on the title's first line; the title is
    pushed down so the two share a centre.
  - **Card headings: build them with `card()` / `heading_row()`** (`ui/kit/panel.py`),
    never a hand-made `QHBoxLayout`. This is the rule that broke most often: the ⓘ
    sat 1.5 px low and "Your mic" sat 6 px below "Who's listening" beside it,
    because each card built its own heading row (one centred its parts on the row's
    box with `AlignVCenter`, another on a padded title), and every fix moved one
    card by hand. How the good ones do it (the sidebar's Sound output card,
    `OutputBlock._pin`, and the headings since `heading_row()`):
    1. **One centre line from the font**: the title's cap-height middle row,
       `ascent - (capHeight + 1) / 2`. Not the label's box, not `AlignVCenter`, not
       a margin found by eye.
    2. **Every part on it**: the heading icon, the ⓘ right after the title, the status
       pill at the end: each one's top is `centre - (height - 1) / 2`, set as a top
       margin in its own top-aligned box.
    3. **Taller parts push the title down**, never stick up out of the row.
    4. **Every titled card starts its title at the same height** (the card's top
       margin is the same for all; `card()` sets it), so two cards side by side have
       their titles on one line without anyone lining them up.
    5. **Measured on the ink, by a test**: `tests/test_card_headings.py` grabs each
       Setup card and checks every part's ink centre is within 1 px of the title's
       first capital, and that side-by-side titles share a line. A new card heading
       gets added to it (or to a test like it); a heading made any other way fails
       review.
  - **A chevron sits right after its words** (one small gap), never at the row's far
    edge; a link-style action's hover fill reaches 8 px past its words on each side.
  - **Wrapping grows, never clips.** A button holding a wrapped label gets a
    `Minimum` vertical size policy, so long translations push the card taller.
  - **Measure the ink.** Widget bounds lie (glyphs have side bearings and empty
    space in their box). Check a rendered grab, zoomed with guide lines, and keep a
    test that measures the ink (`tests/test_output_rail.py::_assert_keylines`).
    Within a pixel is aligned; 2+ px is a visible defect.

The screen shows **what you can do**; the explaining happens on demand. Wherever it
works, a short control plus a pop-up beats a long button or a paragraph on the page.

- **A button is one to three words.** If it needs more ("I've installed it, check
  again", "Make it sound clean in Discord"), it becomes an icon or a short word and the
  rest moves to its tooltip, or the button opens a small pop-up that explains and asks.
- **Icon first.** Any action a picture says (folder, refresh, clear, stop, play, copy,
  show/hide, record, effects, sort, add, settings, info, more) is an icon-only button,
  quiet, 28 px square (24 px in dense rows, never smaller: WCAG 2.2 *Target size*). Its words
  are the tooltip and the accessible name, so every language keeps working.
- **Explanations behind an ⓘ.** More than one line of "how this works" text on a card
  goes into a pop-up opened from an ⓘ icon beside the heading (or the card's hint, cut
  to one line). Warnings, the consequence of a delete and what a new user must do next
  stay visible: never hide those.
- **Rare settings in a pop-up.** A group of settings someone changes once goes behind
  a ⚙ icon on the card (a small dialog), not as rows everyone has to read past. A card's
  few extra *actions* stay as quiet buttons on it: never a ⋯ menu that hides two or
  three options.
- **Multi-step or "are you sure" flows are a dialog**, not extra buttons that appear
  in the card. One question per dialog page (see the Send feedback box).
- **Pop-ups**: close with Esc and a clear Done/Cancel; a left click anywhere else in
  the app closes a modal one too, as Cancel (`ui/kit/modals.py`, app-wide). A dialog
  that holds work a click would throw away (an editor, a form, a recording, the setup
  guide) sets `KEEP_OPEN = True` (or `modals.keep_open(dlg)`); as narrow as their content;
  open next to what opened them (modal or not: the kit). Tooltips are short (one line), never the only way to do something, and never
  hold buttons.

## 5. Cards that look designed

A card is not a heading followed by a stack of plain rows. Every card uses at least
three of these, and none of them is plain grey boxes of text:

- **Depth from the theme**: `QFrame#card` / `#setcard` already paint a soft gradient, a
  light top edge and a darker bottom edge (`POLISH_STYLE`). Don't override their
  background or add borders; nest an inner area in `card_hi` or `inset` (12 px corners
  outside, 8 px inside: inner corners are smaller than outer ones).
- **A heading with an icon**: a painted icon (`ui/kit/icons.py`) in front of the
  `QLabel#section` heading, an optional ⓘ at the end of the same line.
- **Status as a pill**, not a sentence: a small rounded label in the tone colour
  ("On", "Ready", "Not set up") beside the heading, via `theme.set_tone`.
- **Choices as tiles** when they need comparison or explanation: icon + name (+ one muted line) in a rounded
  tile, the picked one filled with the accent tint. Copy `#voicetile`, `#themecard`, the
  setup guide's device rows and More tabs' `#tabcard` (picture, bold title, one-line
  blurb). Compact technical choices follow section 0; do not turn every field into a tile.
- **Pictures**: a card about a thing shows it (an app icon, a device icon, the mascot,
  art from `assets/art/`), at a fixed size on the left.
- **Rhythm**: 14 px padding, 8 px between rows, 12-16 px between groups; one idea per
  group; a group's label is muted text, not a second heading.
- **Numbers that matter look like numbers**: a level meter, a slider with a steady
  number, a big value with a small label, not "Volume: 70%" in body text.
- **Motion where it explains**: a short (120-200 ms) ease when a card folds, a tile
  is hovered or a value changes; nothing that loops or moves on its own while idle.

Before sending pictures of a card, ask: would this look at home in a modern Windows 11
or macOS app? If it looks like a settings form from 2005, it isn't done.

## 6. Colour

- **There are 33 themes, not three.** Every colour you add has to work in all of
  `theme.THEMES` (dark, light, true black, High Contrast's outlines, pale accents like
  Flashbang's yellow, loud ones like Deep Fried, other fonts like Retro 98 and Comic
  Sans). Dark and Light are the reference look; the others must look as finished.
- Only theme tokens (`theme.T["accent"]`, `$accent` in the style sheet). Never a hex
  value in widget code: it breaks the other 29 themes, High Contrast and light themes.
  A new token is derived for every theme in `theme.py` (like `live_text`,
  `accent_text`, `item_hover`), never filled in by hand for two of them.
- The accent drawn **as text or an icon** straight on the window or a card uses
  `accent_text` (`$accent_text`; `icons.icon(..., "accent")` does it for you): the plain
  accent is for fills, and some themes' accent can't be read on their own background
  (Flashbang's yellow on white was 1.4:1). Text on an accent fill is `on_accent`.
- A rule for a widget that sits inside a card must be as specific as the card's generic
  rules (`QFrame#setcard QPushButton:checked` filled the picked theme card with the
  accent): give it a `QFrame#setcard ...` / `QFrame#card ...` twin.
- **Accent means "do this" or "this is on"**: the main button, ticked boxes, toggles,
  the picked option, Live, the playing tile, the selected tab. Ticks and switches stay
  the accent colour when on, never grey.
- Hover and selection highlights in menus and lists stay neutral (`card_hi`,
  `btn_hover`), not accent.
- A menu's picked item (the search site, the sort order) shows in the accent colour,
  its text and icon (`checked_color="accent"`).
- **A dropdown never touches its button.** Every dropdown's list (`QComboBox`) and every
  button's menu opens 8 px below its button, or 8 px above when it opens upwards. The app
  style does it for all of them (`wheelguard.drop_gap`): don't place a menu with a gap
  of your own on top. Right-click menus open where the mouse is.
- Controls above and below a card grid start where the cards' panels do (the search
  results' Back and Show more).
- Status text uses `theme.set_tone(label, "ok" | "warn" | "error")`, not a colour.
- Contrast in **every** theme: 4.5:1 for text, 3:1 for icons, bold labels and a
  control's edge. `tests/test_every_theme.py` and `tests/test_ui_audit.py` check the
  tokens in all 31; add a case there for a new colour role.
- A live theme switch must leave nothing in the old theme's colours: anything that
  bakes a colour in (an icon, a pixmap, a widget's own style sheet) is redrawn by
  `icons.retheme()` / `MainWindow._apply_theme` or reads `theme.T` when it paints.

### The states a feature is built for

Not "dark, light, maybe hover". Every new screen, card or control is built and checked
for all of these at once:

| Axis | States |
| --- | --- |
| Theme | all 31 in `theme.THEMES`, picked at launch **and** switched to live from another theme |
| Control | rest, hover, pressed, keyboard focus, checked / picked, disabled, busy |
| Content | empty, one item, full (scrolling), long translated words (German) |
| Window | 1180x720, 800x600, the mini player, right-to-left |
| Route | the On Air card connected and not (*Setup needed*), with a toast up |

The theme traits that broke things before (pick one theme of each kind when checking by eye;
the tests check the tokens in all 31):

| Trait | Themes | What breaks |
| --- | --- | --- |
| Pale accent on a light background | Flashbang, Barbie | the accent as text or an icon can't be read: use `accent_text` |
| Accent close to grey or to the text colour | Carbon, Arctic, Hacker, Amber Terminal | anything filled with the accent under `text`-coloured words (grey on grey) |
| Light backgrounds | Light, Paper, Mint, Cherry Blossom, Vaporwave, Flashbang, Barbie, Comic Sans, Retro 98 | bright dark-theme status colours, white text, shadows that assume dark |
| Outlined, black on black | High Contrast | flat fills vanish: it keeps borders at rest (`OUTLINED`) |
| Textures | every theme but Midnight, High Contrast, Flashbang (`theme.TEXTURES`; Plain turns them off) | flat colours painted over panels show as patches |
| Other fonts | Amber Terminal, Hacker (Consolas), Retro 98 (Tahoma), Comic Sans | wider words: fixed widths cut text off |
| Loud colours | Deep Fried, Brainrot, Synthwave | `text` is yellow / lime, so a hard-coded white or grey stands out |

Never draw a fixed colour except a sound's own colour, the user's own highlight colour
(`live_override`) and the status colours: those three stay as they are in every theme.

## 7. Text

- Plain, short, friendly words a non-technical gamer understands. Say what happens
  ("Your sounds go into your mic"), not how ("route via the APO endpoint").
- **Sentence case** for every heading, button and tab ("Send feedback", not
  "Send Feedback" or "SEND FEEDBACK"), and no letter spacing.
- **No long dashes** (— or a spaced –) in anything shown: use a colon, comma, full stop
  or brackets.
- Percentages as `23%`. Live numbers hold still: `panel.steady_number()` (same-width
  digits, room for the widest value).
- Every shown string goes through `_()` (`soundboard/i18n.py`) with `{placeholders}`,
  never string concatenation, so all 32 languages can translate it. Reuse an existing
  string when one says the same thing.
- Explanations go in a hint under the heading or in a tooltip, not in the button.
- No jargon for routes and devices: pick devices by their name ("My mic", "My
  headphones"), never "virtual cable (Discord, games)" style labels.

## 8. Behaviour

- **One simple rule for when something shows.** If a row shows while sounds play, it
  shows for one sound too. Rules like "only for 2+" or "stays once shown" confuse people.
- New features go into an existing place (a menu, a card, Settings) before they get a
  new toolbar button. The Sounds tab is the home screen: keep its toolbar as it is
  unless the task is about it.
- Every control works from the keyboard and shows a focus ring.
- Mouse wheel never changes a dropdown or flips a tab unless it has focus
  (`wheelguard.py` does this app-wide; don't undo it).
- Settings changes apply at once; there is no Apply button.

## 9. Never

- A hex colour, a `font-size` / `setPointSizeF(<number>)` or an outline (`border:` at
  rest) in widget code. A text size or button size that isn't in the *Standard kit*.
- A new `QPushButton#name` look for one screen, a fixed width on a text button, or an
  icon button that isn't 24, 28 or 36 px.
- `QMessageBox.information` / `.warning` for news (toast it), Yes/No buttons, or
  `exec()` / `QDialogButtonBox` in new dialogs.
- A control stretched to fill a row, or a dialog as wide as its parent.
- A left-aligned dialog footer, or more than one filled button in one place.
- ALL CAPS headings, Title Case Buttons, long dashes.
- A new bitmap icon, a new font, or a third-party widget library (Fluent, Material,
  qt-material...). The app's look comes from `theme.py` and `ui/kit/icons.py` only.
- A feature that hides or shows on a rule a user couldn't guess.
- A button with more than three words, or a paragraph of how-to text on a card
  (icon + tooltip, or an ⓘ pop-up).
- A plain card: heading + stacked rows of text and buttons with no icon, tile,
  pill or inner area.
- Disabling the button that was just clicked.
- A card heading built by hand (its own `QHBoxLayout` of icon + `QLabel#section` +
  ⓘ), or any part of it placed with `AlignVCenter` or a hand-tuned margin: use
  `card(title, icon=..., beside=..., end=...)` (section 4, *Card headings*).
- A card that folds shut when the page fits the screen open. Folding is for a page
  that really doesn't fit, never a way to tidy up.
- A one-click delete of something a person made.
- Anything touching an edge: a row against its scroll bar, a scroll bar on a card's
  border, a button on the card's edge (section 2, *Breathing room*). A pop-up card is
  built with `card()`, not a bare `QFrame` with hand-set margins.

## 10. Checklist for every UI change

1. Built only from the *Standard kit*: text sizes from its table (no inline
   `font-size`), button kinds and sizes from its tables, the right pop-up for the job,
   dialogs in its anatomy? Pieces above (cards, hint, primary, quiet, icon buttons, tokens)?
2. As narrow as its content; no stretched control; dialog ≤ 620 px?
3. Dialog actions bottom-right, main first within the group, one filled button at most? Every button
   three words or fewer, icons wherever a picture says it, long text in a pop-up?
4. Cards: at least three of section 5's pieces, nothing that looks like a plain form?
5. Text: sentence case, no long dashes, `_()`, `23%`, short plain words?
6. Pictures of **every** state, rendered offscreen (`window` test fixture,
   `widget.grab().save(...)`, `QT_QPA_FONTDIR=C:/Windows/Fonts`), in Dark and Light
   and, for any colour change, **every theme in `theme.THEMES` (31)**: a fresh launch
   in each and a live switch from Dark, plus one long-word language (German) if text
   changed. Look at them before anyone else does: empty space, cut-off words, things
   the same colour as what's behind them, the old theme's colours left after a switch.
7. Icons and words aligned (section 4, *Icon and text alignment*): one icon column,
   one text keyline for every line, icons on the first line's cap height? Card
   headings from `card()` only, covered by `tests/test_card_headings.py`. Check a
   zoomed grab with guide lines.
8. Tests: the new widget's flow, and that tooltips/accessible names exist on icon
   buttons.
9. Breathing room (section 2): the test calls `uicheck.assert_breathing_room` on
   every new card, pop-up and scrolling list, filled until it scrolls; in the pictures,
   zoom on its right edge and bottom: nothing touches the scroll bar or the border.

## 11. Modern standards this follows (2025-2026)

The rules above are Onion Board's take on what the big design systems agree on now:

- **Layers, not lines** (Windows 11 Fluent, Apple's Liquid Glass): the page is the
  base, cards float on it, pop-ups and menus float above cards. Show the layer with
  surface colour and depth, not outlines. Controls float, content leads.
- **Nested rounding** (Fluent geometry): rounder outside, tighter inside; every
  surface of the same kind has the same radius.
- **4 px spacing grid** (Fluent 2, Material 3): every gap and padding is a multiple of 4.
  One exception: lining up with an existing keyline (the rail's icon column) beats
  the grid, so an inset can be 11 px when that is what puts icons on one line.
- **Shape and size show importance** (Material 3 Expressive): the one main action is
  bigger, filled and rounder; secondary actions are quiet icons.
- **Progressive disclosure**: the common path is on screen, the rare one is a click
  away in a menu, ⓘ pop-up or dialog. Never hide warnings or what's needed to finish.
- **Accessibility as a floor** (WCAG 2.2 AA): text 4.5:1, control edges 3:1, click
  targets at least 24 px, every action works from the keyboard with a visible focus
  ring that nothing covers, tooltips show on keyboard focus too and close with Esc,
  nothing relies on colour alone (a tick, an icon or a word goes with it).
- **Calm motion**: short and purposeful; respect Windows' "Animation effects" off
  setting by skipping animations when it's off. A loading indicator keeps a quiet
  colour change (no movement) so a busy app never looks frozen.

## 12. Where things live

| Piece | Code |
| --- | --- |
| Colour tokens, themes, the app style sheet, object names (`#card`, `#primary`, `#hint`, `#section`, `#danger`, `#chip`, `#pill`, `[quiet]`, `[busy]`, `[tone]`) | `soundboard/ui/kit/theme.py`, its sheet's text in `themesheet.py` |
| Painted icons | `soundboard/ui/kit/icons.py`, their drawings in `iconshapes.py` |
| Busy states, opening links, toasts | `soundboard/ui/kit/busy.py` |
| Dialogs that grow to fit their text | `soundboard/ui/kit/fit.py` |
| The bars across the top of the window (`TopBar`) | `soundboard/ui/kit/topbar.py` |
| Wrapping button rows (`Flow`), undo bar, steady numbers | `soundboard/ui/kit/panel.py`, `settings._button_row` |
| Settings cards | `settings.SettingsDialog._card` |
| Left tab rail | `soundboard/ui/window/sidebar.py` |
| Wheel guard, dropdown widths, the gap under a dropdown | `soundboard/ui/kit/wheelguard.py` |

## 13. UI workflow for agents and reviewers

1. **Read and inspect.** Start from the latest main in a clean checkout. Read this
   file. Inspect the
   existing widget and reuse its helpers before inventing another pattern.
2. **State the contract.** In the task notes or PR, write: user task; control chosen
   from section 0; inline/menu/popup/dialog; live or draft changes; action order;
   close/Escape behaviour. Explain any exception briefly. This needs no extra
   user approval for ordinary implementation choices.
3. **Build with existing pieces.** Use `theme.py`, `icons`, `Flow`, `fit`, `busy`,
   wheelguard and established card/choice widgets. If two screens need the same
   behaviour, extract a small shared helper instead of pasting another layout.
4. **Review every affected state.** Render offscreen with the test fixtures and
   `QT_QPA_FONTDIR` set to the system fonts. For MainWindow screenshots, switch
   themes with `window.apply_theme(name)`: it refreshes registered icons as well
   as the stylesheet; calling `theme.apply()` alone leaves stale icon colours.
   Inspect the complete page and each
   menu, expanded card and dialog affected, including empty/populated and disabled/
   busy states where relevant. Use Dark/Light, narrow/normal sizes, and German when
   labels change. Check focus,
   keyboard choice, Escape, save/cancel semantics and long labels. Inspect High
   Contrast/Retro 98 when colours or custom painting change.
5. **Validate and deliver.** Translate user-visible changes in every catalog, run
   `scripts\precommit.ps1` on the changed scope, and show the reviewed pictures.
   Add behavioural regression checks for reported defects, not tests that merely
   repeat styling code. Follow the normal PR/CI/local UTC merge loop.
6. **Keep the contract current.** Update this file when adding an approved reusable pattern;
   do not leave contradictory instructions in another document.

PR evidence can be one short paragraph: `Control/surface: ...; changes: live/draft;
actions: ...; close: ...; verified states: ...`. Documentation-only changes do not
need new UI screenshots or runtime tests. This workflow is a review requirement;
existing CI checks do not automatically judge visual or interaction consistency.

## Where this comes from

The format follows Google Labs' [DESIGN.md](https://github.com/google-labs-code/design.md)
idea: tokens on top for tools, rules in prose for people and agents. The 4 px spacing
ramp and type sizes follow Microsoft's [Fluent 2](https://fluent2.microsoft.design/layout),
which matches Windows, where most people run the app. Section 11 draws on Fluent's
[geometry](https://learn.microsoft.com/windows/apps/design/signature-experiences/geometry)
and layering guidance, Apple's [Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/liquid-glass)
hierarchy principle, [Material 3 Expressive](https://developer.android.com/design/ui/wear/guides/get-started/design-language)
and [WCAG 2.2](https://www.w3.org/TR/WCAG22/).
