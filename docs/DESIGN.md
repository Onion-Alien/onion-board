---
# Onion Board design system: the machine-readable part.
# Colour values live in soundboard/theme.py (THEMES): 30+ themes share these token
# NAMES, so code always uses a token, never a hex value. The prose below says how.
name: Onion Board
version: 1
platform: PySide6 (Qt Widgets), styled by one app style sheet (theme.stylesheet)
font:
  family: "Segoe UI (a theme may swap it with its `font` token)"
  base: 10pt          # everything, unless a role below says otherwise
  hint: 8.5pt         # QLabel#hint: explanations under a heading
  small: 8pt          # QPushButton#small, badges
  section: 10pt bold  # QLabel#section: card and group headings
  title: 1.3x base, bold   # a dialog's one big question ("What would you improve?")
  wordmark: 13pt bold
  digits: same-width (tabular); live numbers via panel.steady_number()
colour_roles:          # token names in theme.THEMES; values change per theme
  background: bg
  surface: panel        # cards (QFrame#card, #setcard), bars
  surface_raised: card_hi   # hover, selected, a box inside a card
  button: btn / btn_hover / btn_press
  text: text, text_hi (titles), muted (secondary), faint (disabled-looking)
  heading: section
  accent: accent / accent_hi / on_accent   # main action, on-state, Live, playing
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
size:
  dialog_max_width: 620px
  dropdown_max_width: 360px
  icon_button: 28-32px square
  focus_ring: always visible on keyboard focus
---

# Onion Board design system

How every screen, card, dialog and button in Onion Board should look and behave.
Read this before building or changing any UI. It is written for people and for AI
coding agents alike: the rules are meant to be followed literally. When a rule here
and an older screen disagree, this file wins for new work; don't restyle old screens
in passing unless the task is about them.

The style is **quiet and compact**: flat surfaces in the theme's colours, no resting
outlines, controls only as big as their words, one accent-coloured thing that says
"do this" or "this is on". The app should look designed, not generated.

## 1. The best screens to copy

These are the current reference points. Copy their structure before inventing a new one.

| Screen | What it gets right |
| --- | --- |
| Sounds tab board (`ui/mainwindow.py`, pads) | Fixed-size tiles in a grid that scrolls down; picture, name, hotkey badge, length; one filled main button (*Add sounds*), the rest quiet. |
| Setup guide (`ui/setupwizard.py`) | One question per step in a big title, a short plain explanation, choices as large icon rows, the mascot for warmth, one main button. |
| Setup tab cards | `setcard`: heading, one-line hint, controls, buttons at their own width in a wrapping row. |
| Left tab rail (`ui/sidebar.py`) | Icons only when closed, names when open, the selected tab a soft accent fill, settings at the foot. |
| Send feedback box (`ui/feedbackdialog.py`) | The small-dialog pattern: title question, hint, tick boxes, buttons on the left with the main one first, a second page instead of a second dialog. |
| Bottom strip / player bar | One slim bar: icon, slider, steady number. No boxes around each part. |

## 2. Layout

- **Narrow by default.** Every control is as wide as its content: buttons as wide as
  their words, dropdowns as wide as their longest choice (capped at 360 px), then
  `addStretch(1)`. Only a control that holds long free text (search, a path, a slider,
  a text line) may stretch.
- **Dialogs**: capped at about 620 px wide, as tall as their content. Use
  `fit.watch(self)` so they grow to fit translated text. A multi-step dialog changes
  pages in a `QStackedWidget` and shrinks to the current page (see feedbackdialog).
- **Grids** use few columns of fixed-size tiles and scroll down; never spread tiles
  out to fill the width.
- **Cards** (`QFrame#card` / `#setcard`) group related things: heading (`QLabel#section`),
  an optional one-line `QLabel#hint`, then the controls. One idea per card. If two cards
  could be one, make one: fewer sections beats more. Cards must look designed, not
  like a form: see *Cards that look designed* below.
- Long text wraps (`setWordWrap(True)`); it never widens the layout.
- No huge empty gaps and no sideways scroll bars, at 900x700, 720x500 and the
  smallest window size.
- Right-to-left languages mirror automatically; don't hard-code left/right positions
  in painting code without checking `layoutDirection()`.

## 3. Buttons

- **Button rows sit on the left, the main button first**:
  `[Send] [Cancel]`, `[Open the feedback form] [Done]`, then a stretch. Never
  right-aligned with the main button last.
- **At most one filled button** (`setObjectName("primary")`) per card or dialog: the
  thing most people should press. Everything else is a plain button or a quiet one
  (`setProperty("quiet", True)`: no background until hover).
- Destructive actions use `#danger`, and anything that removes something a person
  made goes through Undo or the Recently deleted bin (`trash.py`, `ui/deleted.py`,
  `panel.UndoBar`), not a one-click loss. Keep "are you sure?" for deleting for good.
- **Icon-only buttons** wherever the picture says it (section 4). The words become
  the tooltip *and* the accessible name (`setToolTip`, `setAccessibleName`). Icons
  come from the app's own painted set (`ui/icons.py`, `icons.set_icon`); add new ones
  there in the same style, never an image file.
- **Keep words** on the main action of a card and on anything a new user must
  understand to get started.
- A button that starts slow work doesn't disable itself (focus would jump to the next
  control). Use `busy.set_busy` / `busy.run_busy` / `busy.hold`.
- Links open with `busy.open_url(...)` so a failure shows a toast with the address.
- Add / + buttons go right after the last item (like a browser's new-tab button),
  never before the first.

## 4. Icons and pop-ups instead of long buttons

The screen shows **what you can do**; the explaining happens on demand. Wherever it
works, a short control plus a pop-up beats a long button or a paragraph on the page.

- **A button is one to three words.** If it needs more ("I've installed it, check
  again", "Make it sound clean in Discord"), it becomes an icon or a short word and the
  rest moves to its tooltip, or the button opens a small pop-up that explains and asks.
- **Icon first.** Any action a picture says (folder, refresh, clear, stop, play, copy,
  show/hide, record, effects, sort, add, settings, info, more) is an icon-only button,
  quiet, 28-32 px square (never smaller than 24 px, WCAG 2.2 *Target size*). Its words
  are the tooltip and the accessible name, so every language keeps working.
- **Explanations behind an ⓘ.** More than one line of "how this works" text on a card
  goes into a pop-up opened from an ⓘ icon beside the heading (or the card's hint, cut
  to one line). Warnings, the consequence of a delete and what a new user must do next
  stay visible: never hide those.
- **Rare options in a menu or pop-up.** Settings someone changes once go behind a
  ⋯ / ⚙ icon on the card (a `QMenu` or a small dialog), not as a row of controls
  everyone has to read past.
- **Multi-step or "are you sure" flows are a dialog**, not extra buttons that appear
  in the card. One question per dialog page (see the Send feedback box).
- **Pop-ups**: non-modal unless the app truly can't go on without an answer; close with
  Esc and a clear Done/Cancel; as narrow as their content; open next to what opened
  them. Tooltips are short (one line), never the only way to do something, and never
  hold buttons.

## 5. Cards that look designed

A card is not a heading followed by a stack of plain rows. Every card uses at least
three of these, and none of them is plain grey boxes of text:

- **Depth from the theme**: `QFrame#card` / `#setcard` already paint a soft gradient, a
  light top edge and a darker bottom edge (`POLISH_STYLE`). Don't override their
  background or add borders; nest an inner area in `card_hi` or `inset` (12 px corners
  outside, 8 px inside: inner corners are smaller than outer ones).
- **A heading with an icon**: a painted icon (`ui/icons.py`) in front of the
  `QLabel#section` heading, optional ⓘ or ⋯ icon at the end of the same line.
- **Status as a pill**, not a sentence: a small rounded label in the tone colour
  ("On", "Ready", "Not set up") beside the heading, via `theme.set_tone`.
- **Choices as tiles**, not radio lists: icon + name (+ one muted line) in a rounded
  tile, the picked one filled with the accent tint. Copy `#voicetile`, `#themecard`, the
  setup guide's device rows and More tabs' `#tabcard` (picture, bold title, one-line
  blurb).
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

- Only theme tokens (`theme.T["accent"]`, `$accent` in the style sheet). Never a hex
  value in widget code: it breaks 30+ themes, High Contrast and light themes.
- **Accent means "do this" or "this is on"**: the main button, ticked boxes, toggles,
  the picked option, Live, the playing tile, the selected tab. Ticks and switches stay
  the accent colour when on, never grey.
- Hover and selection highlights in menus and lists stay neutral (`card_hi`,
  `btn_hover`), not accent.
- Status text uses `theme.set_tone(label, "ok" | "warn" | "error")`, not a colour.
- Check contrast in Dark, Light, High Contrast and Retro 98 at least: 4.5:1 for text,
  3:1 for a control's edge.

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
- Pop-ups that aren't urgent are not modal (`dlg.show()`), so sounds keep playing and
  hotkeys keep working.
- Every control works from the keyboard and shows a focus ring.
- Mouse wheel never changes a dropdown or flips a tab unless it has focus
  (`wheelguard.py` does this app-wide; don't undo it).
- Settings changes apply at once; there is no Apply button.

## 9. Never

- A hex colour, a pixel font size or an outline (`border:` at rest) in widget code.
- A control stretched to fill a row, or a dialog as wide as its parent.
- A right-aligned button row, or more than one filled button in one place.
- ALL CAPS headings, Title Case Buttons, long dashes.
- A new bitmap icon, a new font, or a third-party widget library (Fluent, Material,
  qt-material...). The app's look comes from `theme.py` and `ui/icons.py` only.
- A feature that hides or shows on a rule a user couldn't guess.
- A button with more than three words, or a paragraph of how-to text on a card
  (icon + tooltip, or an ⓘ pop-up).
- A plain card: heading + stacked rows of text and buttons with no icon, tile,
  pill or inner area.
- Disabling the button that was just clicked.
- A one-click delete of something a person made.

## 10. Checklist for every UI change

1. Built from the pieces above (cards, hint, primary, quiet, icon buttons, tokens)?
2. As narrow as its content; no stretched control; dialog ≤ 620 px?
3. Buttons on the left, main one first, one filled button at most? Every button
   three words or fewer, icons wherever a picture says it, long text in a pop-up?
4. Cards: at least three of section 5's pieces, nothing that looks like a plain form?
5. Text: sentence case, no long dashes, `_()`, `23%`, short plain words?
6. Pictures of **every** state, rendered offscreen (`window` test fixture,
   `widget.grab().save(...)`, `QT_QPA_FONTDIR=C:/Windows/Fonts`), in at least Dark and
   one light theme, and one long-word language (German) if text changed. Look at
   them before anyone else does: empty space, cut-off words, things the same colour
   as what's behind them.
7. Tests: the new widget's flow, and that tooltips/accessible names exist on icon
   buttons.

## 11. Modern standards this follows (2025-2026)

The rules above are Onion Board's take on what the big design systems agree on now:

- **Layers, not lines** (Windows 11 Fluent, Apple's Liquid Glass): the page is the
  base, cards float on it, pop-ups and menus float above cards. Show the layer with
  surface colour and depth, not outlines. Controls float, content leads.
- **Nested rounding** (Fluent geometry): rounder outside, tighter inside; every
  surface of the same kind has the same radius.
- **4 px spacing grid** (Fluent 2, Material 3): every gap and padding is a multiple of 4.
- **Shape and size show importance** (Material 3 Expressive): the one main action is
  bigger, filled and rounder; secondary actions are quiet icons.
- **Progressive disclosure**: the common path is on screen, the rare one is a click
  away in a menu, ⓘ pop-up or dialog. Never hide warnings or what's needed to finish.
- **Accessibility as a floor** (WCAG 2.2 AA): text 4.5:1, control edges 3:1, click
  targets at least 24 px, every action works from the keyboard with a visible focus
  ring that nothing covers, tooltips show on keyboard focus too and close with Esc,
  nothing relies on colour alone (a tick, an icon or a word goes with it).
- **Calm motion**: short and purposeful; respect Windows' "Animation effects" off
  setting by skipping animations when it's off.

## 12. Where things live

| Piece | Code |
| --- | --- |
| Colour tokens, themes, the app style sheet, object names (`#card`, `#primary`, `#hint`, `#section`, `#danger`, `#chip`, `#pill`, `[quiet]`, `[busy]`, `[tone]`) | `soundboard/theme.py` |
| Painted icons | `soundboard/ui/icons.py` |
| Busy states, opening links, toasts | `soundboard/ui/busy.py` |
| Dialogs that grow to fit their text | `soundboard/ui/fit.py` |
| Wrapping button rows (`Flow`), undo bar, steady numbers | `soundboard/ui/panel.py`, `settings._button_row` |
| Settings cards | `settings.SettingsDialog._card` |
| Left tab rail | `soundboard/ui/sidebar.py` |
| Wheel guard, dropdown widths | `soundboard/wheelguard.py` |

## 13. Known gaps (old screens that break these rules)

Fix these when a task touches them; don't sweep them all in one go.

- Settings' *Done* and the setup guide's *Next* sit bottom-right.
- Some Setup texts still have long dashes (open work: text style pass).
- Voice tab cards stretch across the full width with empty space below.
- Many word buttons that should be icons, and long ones ("Make it sound clean in
  Discord", "Record 6s, play back") that should be shorter (open work: the compact pass).
- Plain cards: Setup's *Your mic* (paragraphs of how-to text that belong behind an ⓘ),
  *Connect your chat* (a grid of long word buttons that could be app tiles), Settings
  pages (rows of text and buttons with no icons or pills).

## Where this comes from

The format follows Google Labs' [DESIGN.md](https://github.com/google-labs-code/design.md)
idea: tokens on top for tools, rules in prose for people and agents. The 4 px spacing
ramp and type sizes follow Microsoft's [Fluent 2](https://fluent2.microsoft.design/layout),
which matches Windows, where most people run the app. Section 11 draws on Fluent's
[geometry](https://learn.microsoft.com/windows/apps/design/signature-experiences/geometry)
and layering guidance, Apple's [Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/liquid-glass)
hierarchy principle, [Material 3 Expressive](https://developer.android.com/design/ui/wear/guides/get-started/design-language)
and [WCAG 2.2](https://www.w3.org/TR/WCAG22/).
