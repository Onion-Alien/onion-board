# UI audit: the one UI to-do list

**This is the only UI to-do list.** "The UI audit doc" or "the UI doc" means this file.
Don't start new audit files: add findings here as new U-items. Rules live in
[DESIGN.md](DESIGN.md) (section 0 for controls and surfaces, section 14 for the
workflow); this file only tracks work.

Before suggesting or starting an item, check it against latest `origin/main` (git log + an
offscreen render) and the open PRs: many sessions fix UI in parallel and an item can be done
within hours. Each item is scoped work, not permission to restyle the app. Tick it with its
PR and what was checked (themes, sizes, test file) only after reviewing the affected states.

## Open

- [ ] **U16: Move old screens onto the standard sizes.** DESIGN.md's *Standard kit*
  fixes 7 text sizes, 3 icon-button sizes and one pop-up per job. Old code (11 October,
  `origin/main` `67ea807`) still has: inline `font-size` / `setPointSizeF` in about 60
  places, with off-scale 7, 7.5, 9, 9.5, 10.5, 12, 14, 15 and 19pt (`theme.py` `#fxend`,
  `#recordtitle`, `#round`; `ui/speedpitch.py`, `ui/chatguide.py`, `ui/resetguide.py`,
  `ui/whatsnew.py`, `ui/setupwizard.py`, `ui/overlay.py`); icon buttons at 22, 30, 32
  and 36 px outside bars; about 28 `QMessageBox.information` / `.warning` calls that
  should be toasts or inline tone labels, Yes/No `QMessageBox.question`s, 30
  `QDialogButtonBox` footers and 35 `exec()` calls. Do it one screen per PR (pictures
  before and after), moving inline sizes into `theme.py` object names. Don't sweep
  everything in one go; `exec()` changes need a lifecycle check each.

Ideas from test runs on 11 October, not yet verified on main. Check each first; some may
be the owner's call rather than a fix.

- [ ] **U17: A link lookup looks like a hang.** Paste a link in the Sounds search and press
  Enter: the card says "Looking up <host>…" with no progress and no Cancel. Idea: a small
  spinner or "still looking…" after about 3 s, and Cancel on the card.
  Target: `ui/ytsearch.py` (`show_link`).
- [ ] **U19: Two mic-mute switches on Setup.** *Send my mic to others* and *Mute mic during
  sounds* both gate the mic, worded differently. Check what each does: if different, the
  words must say so; if the same, merge them. Also: Audio buffering's two choices only show
  which is active in the combo text (low priority). Target: `settings.py` ~1272/1286.
- [ ] **U20: A program that went quiet looks the same as one playing.** Apps tab: a captured
  program at volume 0 keeps "playing" and Send on; only the meter drops. Idea: a "silent"
  hint after a few seconds without sound. Target: `ui/appspanel.py`.
- [ ] **U21: Turning Send off forgets the program's volume.** By design today
  (`test_appspanel`: "stopped and forgotten"). Could remember the volume without
  auto-sending. Ask the owner before changing it.
- [ ] **U22: Long word buttons and plain cards** (carried from DESIGN's old known-gaps list,
  recheck first): buttons like "Make it sound clean in Discord" / "Record 6s, play back"
  that should be shorter or icons; Setup's *Your mic* (how-to paragraphs that belong
  behind an ⓘ) and *Connect your chat* (a grid of long word buttons that could be tiles).

**Owner's call, not bugs** (raised in testing, listed so nobody re-finds them): pad
duration and bottom-bar text small; Setup step 2 shows raw device names and "CABLE Input /
mono" with no plain explanation; *Live* turns into *Muted* with no hint; Settings > Hotkeys
doesn't list pad hotkeys or a Mute row; the Triggers toolbar is icon-only while its empty
text names "Cut picture..."; the Radio bar drops star/volume/Record at 1100x750; "Add a
device" adds a same-as-call copy, not the stream output; a scroll area and the tab bar are
nameless focus stops for screen readers. Skip: a voice-gated push-to-talk (calls and games
do that; the board's Auto push-to-talk is the right feature).

## Done

Decisions in the right-hand column are standing: don't undo them without the owner.

| Item | PR | What it settled |
|---|---|---|
| U1 dialog actions | #398 | Bottom-right, main first, one filled button (DESIGN §1). Recently deleted's list actions and the guides' Back/Next stay where they are. |
| U2 choice controls | #420 | Each control already matched section 0: radio tiles (Recording source), plain radios (Live tabs, Connection, Network activity), exclusive buttons (Who's listening), dropdown (Edit sound's *On press*). |
| U3 config entry points | #419 | *Make it yours* = the one retained modeless editor; small option sets fold out inline (`panel.fold_button`). |
| U4 live vs draft | #413 | Settings is a page in the window (live, no Save). Edit sound is modeless, one per sound, Save/Cancel. Yes/no questions, hotkey capture and the setup guide stay modal. |
| U5 button families | #400, #415 | Folder = quiet icon button (`panel.icon_button`); Reset = `panel.reset_button`; help = ⓘ beside the heading (`panel.info_button`). |
| U6 Settings cards | #423 | Kept as forms; a `keepline` property stops a short field label wrapping. |
| U7 help popup | #416 | `#helpcard` / `#helptitle` / `#helpbody` roles, painted close icon, focus returns to the opener. |
| U8 Apps + Triggers | #422 | Triggers without the add-on is Onion Watch's card on the tab, no pop-up. Apps cards open their menu with the Menu key / Shift+F10. |
| U9 menus | #399, #414 | One colour list (`padbatch.fill_colour_menu`), ticks on the current value, short red Remove/Delete. |
| U10 secondary text | #409 | `theme.SECONDARY_ON` lifts muted/faint to 4.5:1 on every surface; placeholders use `$muted`. |
| U11 full-screen width | #411 | Only the search box is capped (`SEARCH_MAX_W` 480). Seek bar, meter and drop box follow the window on purpose (#410, capping all four, was closed). Don't re-cap them. |
| U12 sizes | #412 | `panel.CONTROL_H` 36, `panel.BAR_H` 48, *Interface size* setting (80-150 %, restart). Don't change heights elsewhere. |
| U13 program names | #424 | Apps cards use the .exe's FileDescription (*VLC media player*), stem as fallback. |
| U14 category names | #425 | Built-in Apps categories translated for display; config keeps the English key. |
| U15 heading keyboard | #426 | Apps category headings take focus; Menu key / Shift+F10 opens their menu. |
| U18 long import | #484 | The import's busy card stays up until the import is done (`ms=0`), for one file too, not 4 s. Checked on main with a 1-hour MP3, offscreen: "Adding 1 sound…" the whole 9.4 s (before: gone at 4 s), then "Added 1 sound". Test: `test_one_slow_file_keeps_its_busy_card_until_its_in`. |

## Features for later (not UI fixes; after 2.0)

- Lower other programs (Spotify, the game) while a sound plays; `appaudio` already lists
  the sessions.
- Timed sounds: play X every N minutes or at a set time.
- Twitch / YouTube chat and channel-point triggers built in.
- A native Stream Deck plugin.
- Multiple boards / profiles with one switch (low priority).

## Prompt for a UI session

```text
Work on Onion Board's UI backlog. Read AGENTS.md, CLAUDE.md, docs/AGENT-RULES.md and
docs/DESIGN.md first. Start from latest origin/main in a worktree and check open PRs for
overlap. Take the open items in docs/UI-AUDIT.md one PR each; check each against main
first. Follow DESIGN section 0 for the control and section 14 for the workflow; report
intentional differences instead of forcing one widget type. Translate changed text in
every language, render the affected states offscreen and show the pictures, run
scripts\precommit.ps1. Don't merge a UI PR before the owner OKs its pictures; merge with
scripts/merge_pr.sh. Tick the item here with its PR and what was checked.
```

## Button and icon alignment pass (12 October 2026)

Audit only; no UI changes. Checked main `2bff2b22` with offscreen renders in
Light and Dark at 1400x900 and 800x600, plus expanded Setup and Voice subpages
at 1180x720. Six main tabs, populated Sounds/Apps, Triggers install card and
Settings > Appearance. Measurements are logical Qt pixels at the default interface
size. Private captures stay outside the repository. No open PRs were returned at
inspection. Existing U16 and U22 cover some of the same debt; these entries scope
individual alignment passes rather than authorize an app-wide restyle.

**Labels:** defect = visible or measured problem; polish = proposed consistency
improvement, not broken behavior; verify = coverage still needed before a fix.

### Setup: start here

- [ ] **U23 (defect): Virtual mic action heights differ.** The direct-mic primary is
  40 px high; cable install, guide and rescan are 38 px. Side-by-side controls have
  different top/bottom edges. Normalize the action row using the standard control
  family. Target: `ui/mainwindow.py`, `_build_setup_page` and `_update_status`.
- [ ] **U24 (defect): Cable-install icon disappears in Light.** The secondary cable
  button keeps an `on_accent` icon when it loses primary styling. White icon on the
  white card leaves a conspicuous blank slot before the text. Confirmed visually
  and by the `look` / `_set_primary` sequence. Choose the icon role from the final
  button state. Target: `ui/mainwindow.py`, `_update_status`.
- [ ] **U25 (polish): Virtual mic actions wrap into a ragged staircase.** At 1400 the
  direct-mic and cable buttons share row one, the guide occupies row two, and rescan
  row three. At 1180 the primary occupies row one, cable + guide row two, and rescan
  row three. Define a deliberate primary row and compact secondary row, preserving
  sensible wrapping. Target: `_ways`, `mic_ways`, `Flow`.
- [ ] **U26 (polish): Rescan has a separate spacing rhythm.** There is a larger gap
  before rescan than between the other action rows. Bring its row into the same
  action-group rhythm. Target: `_build_setup_page`, `btn_rescan`.
- [ ] **U27 (polish, overlaps U22): Long primary label dominates the card.**
  "Straight into my mic instead (no cable)" is 295 px wide, forcing the other
  actions to wrap early. Shorten the visible action and retain the explanation
  nearby or in help, with translations checked. Target: `btn_attach`.
- [ ] **U28 (polish): Who's listening uses another control height.** Mode buttons
  are 38 px versus the standard 36 px. Review them alongside the mic action group
  so the two Setup cards share a control scale. Target: `ui/destpanel.py`.
- [ ] **U29 (polish): Setup heading indents differ.** Your virtual mic has a leading
  icon and indented title; Who's listening starts directly with text; fold headers
  use a third icon/title treatment. Normalize heading icon slots and title offsets
  without changing what the cards contain. Target: Setup card headings / FoldCard.

### Shared rail and bottom controls

- [ ] **U30 (polish): Bottom icon actions are rectangular.** At compact width, mic
  and headphones actions are 44x34 and listen-back is 48x34. Compare against the
  documented 36 px bar icon-button family; standardize hitboxes and centering while
  retaining the footer's intended compact layout. Target: main-window audio strip.
- [ ] **U31 (polish): Listen-back has a different icon scale.** Its wide-state icon
  is 22 px; the compact state uses 18 px. Review the switch with the neighboring
  mic, broadcast and headphone glyphs, avoiding an unexplained size jump.
- [ ] **U32 (polish): Footer labels use several different icon/text gaps.** My mic,
  What others hear and My headphones combine labels, meters/sliders and actions
  differently. Establish consistent icon slots and text gaps within each group;
  do not force the groups to equal widths or re-cap the meter (U11 decision).
- [ ] **U33 (verify): Light theme refresh leaves some icons nearly invisible.**
  After changing the already-built window to Light, help, guide, gear and several
  toolbar icons retain very pale colors. Dark renders restore many of them. Verify
  cold-start Light separately from live theme changes before calling each one a
  bug; U24 is independently supported by the button's icon-role code.

### Sounds

- [ ] **U34 (polish): Play and Stop have different silhouettes.** The player puts a
  circular 36 px Play next to a rounded-square 36 px Stop. Centers align, but the
  pair has unequal visual weight. Decide whether transport actions should share
  a silhouette before changing either. Target: Sounds player bar.
- [ ] **U35 (polish): Compact toolbar has unequal icon/menu group widths.** Add,
  source and sort each pair a glyph with a chevron, but the search-source group
  reads as a wide loose pair. Review group padding and glyph/chevron gaps together
  at 800 px. Target: Sounds toolbar.
- [ ] **U36 (polish): Category add affordance is very faint in Light.** The small
  control after All is difficult to distinguish from the background in the rendered
  idle state. Verify its icon role and hover/focus appearance before adjustment.
- [ ] **U37 (verify): Pad hover actions need a separate alignment pass.** Idle pads
  keep name/duration aligned; hover edit/play/menu controls were not exercised in
  this quick pass. Check short/long names and pictures before declaring pads clear.

### Radio

- [ ] **U38 (defect/debt, overlaps U16): Radio bar mixes 34, 33 and 21 px buttons.**
  Play/Send/Last 15s are 34 px; Record is 33 px; Effects is 21 px. Vertical centers
  are close, but edges and hit areas differ visibly. Normalize the intended bar
  families together. Target: `ui/radiopanel.py` control bar.
- [ ] **U39 (polish): Radio icon buttons are 44x34.** Shuffle/Favorite have wider
  rectangular hitboxes than neighboring transport icons. Review standard square
  bar controls and consistent icon centering. Target: radio control bar.
- [ ] **U40 (polish): Compact Radio stretches icon actions very wide.** At 800 px,
  Play, Shuffle and Send become roughly 176 px wide, while the shared footer below
  has compact icon actions. Consider compact transport groups plus flexible
  remaining space; preserve access to the controls intentionally hidden at narrow
  sizes rather than treating that existing decision as a newly found bug.
- [ ] **U41 (polish): Radio selector star uses a larger icon than its peers.**
  Favorites has a 22 px icon at wide width; Popular/Recent are text, with a 28 px
  selector height. Review optical centering and the icon-only compact Favorites
  state. Target: radio selector row.
- [ ] **U42 (verify): Loaded station-row action alignment remains unchecked.** The
  offscreen map does not render and this pass did not wait for network station data.
  Audit play/favorite/overflow buttons on loaded and selected station rows later.

### Apps

- [ ] **U43 (defect/debt): Send and Record heights differ on every app card.** Send
  measures 34 px and Record 33 px in the same row. Fix at the shared control level,
  coordinating with U38, rather than padding individual cards.
- [ ] **U44 (polish): App toolbar is smaller than other page toolbars.** Effects and
  Category are 21 px high; app-card actions are 33/34 px. Review whether this page
  intentionally needs dense controls; otherwise use the standard toolbar family.
- [ ] **U45 (polish): App close action uses a 26 px square.** The top-right close
  button is between the documented 24 and 28 px dense/normal families. Use one of
  those families and check its center against the app heading. Existing app rows
  otherwise align consistently between the two populated cards.
- [ ] **U46 (verify): Expanded Clip editor needs its own pass.** Idle fold toggles
  line up; editor transport/trim/save actions were not opened in this pass.

### Voice

- [ ] **U47 (defect/debt): Voice navigation and speech actions are 33 px high.**
  Compare with the 36 px standard toolbar family and 34 px Make it yours action.
  Align the page's control families together. Preset artwork tiles are a separate
  family and should retain their existing consistent grid.
- [ ] **U48 (polish): Voice subtab row leaves a lone Add-ons button at 800 px.** Four
  tabs occupy row one, Add-ons occupies row two. It is functional, but review a
  deliberate wrapping or navigation treatment instead of an orphaned final tab.
- [ ] **U49 (polish): My own mix heading icon is visually oversized.** The sliders
  glyph is much larger than the mic/ear glyphs in the adjoining bars. Normalize
  optical weight while retaining the heading hierarchy. Target: Voice mix bar.
- [ ] **U50 (polish): Voice Add-ons mixes a word Refresh button and bare folder
  action.** Both are centered, but their silhouettes and visible action widths
  differ. Review using the established refresh/folder icon family with shared
  hitboxes. Target: Voice Add-ons card.
- [ ] **U51 (verify): Languages, selected-preset controls and installed AI states.**
  AI install, Custom and Add-ons were inspected; Languages was not captured by this
  pass, and installed/live AI controls were not enabled. Audit those rows before
  claiming complete Voice-state coverage.

### Triggers and Settings

- [ ] **U52 (polish): Triggers install CTA icon/text gap is tight.** The eye glyph
  sits close to "Get Onion Watch" compared with Setup actions. Standardize the
  action's icon slot/gap. The install-card bullet icons otherwise align consistently.
- [ ] **U53 (verify): Installed Onion Watch toolbar and trigger cards.** Only the
  not-installed card was checked. The separately shipped add-on needs a matching
  pass on cut/capture/add/record/delete controls; do not infer its layout from the
  host's install card.
- [ ] **U54 (polish): Settings has a larger navigation icon scale than the main rail.**
  Appearance's settings category glyphs are visually larger and heavier than the
  outer rail. Review whether that hierarchy is intentional; align icon slots and
  optical centers rather than flattening all glyphs to one size.
- [ ] **U55 (verify): Remaining Settings categories and interface scaling.** This
  pass covered Appearance at default scaling only. Check other categories, 80/150%
  interface sizes and Windows DPI scaling before applying global sizing changes.

Suggested fix order: U24 (missing cable icon), U23/U25/U26 (virtual mic action
layout), shared Send/Record and toolbar sizes (U38/U43/U47), then page-specific
polish. Verify items remain coverage gaps, not confirmed defects. No runtime code,
real audio/device settings or installed application changed during this audit.