# UI audit: the one UI to-do list

**This is the only UI to-do list.** "The UI audit doc" or "the UI doc" means this file.
Older audit notes (8 and 11 October) were merged in here and retired; don't start new
audit files: add findings here as new U-items. Before suggesting or starting an item,
check it against latest `origin/main` (git log + an offscreen render): many sessions
fix UI in parallel and an item can be done within hours. Tick it with its PR when done.


Spot audit of `origin/main` at `44a35c6`. Evidence: Dark offscreen previews of all
six main tabs, General/Appearance/Audio/Connection settings, Edit sound and the
initial Recording state, plus targeted source inspection of secondary surfaces.
This was not a full interaction, accessibility or responsive audit. Apps was empty
and the Watch add-on was not loaded; their populated interiors remain unverified.

Use [DESIGN.md](DESIGN.md) section 0 for decisions and section 14 for the workflow.
Recheck latest main and open PRs before implementing an item. Each item is scoped
work, not permission to restyle the whole app. Mark it complete only after reviewing
the affected states; include its PR and validation evidence here.

## Fix first

- [x] **U1: Consistent bottom-right dialog actions.** The original audit treated
  right-aligned actions as a defect under the old design rule. That finding is
  superseded: bottom-right is the intended pattern, and Settings, Edit sound,
  Recording and the Program picker already followed it (PR #396, which moved them
  left, was closed unmerged). Acceptance: stretch before the bottom-right action
  group, main action first within the group, then alternatives/Cancel/Done, one
  filled action; preview/reset stays with its content.

  Done (PR #398): the remaining left-aligned footers moved bottom-right: Send
  feedback (both pages), Count me in (Done) and the sound source box (Open, Copy
  link, Close; its Delete info bin stays on the left beside the details and stays
  last in focus order). Order, defaults, Escape and focus unchanged; checked
  offscreen in Dark and Light, English and German (`tests/test_dialog_actions.py`).
  Left as is on purpose: Recently deleted's Bring back / Delete for good act on the
  list above them (its Close is already bottom-right); setup and reset guides keep
  Back on the left and Next/Go on the right.

- [x] **U2: A clear rule for choice controls.** Recording source uses radio tiles;
  Appearance's live indicator and Connection use plain radios; output modes use
  exclusive buttons; Edit playback uses a combo. These are not all defects: compare
  task and available space against DESIGN section 0 before changing them.
  Targets: `ui/recordmic.py`, `settings.py`, `ui/destpanel.py`, `ui/dialogs.py`.
  Acceptance: comparable choices use the same pattern; labels, exclusivity,
  keyboard selection and saved values work; dynamic device lists remain dropdowns.

  Done (PR #420): each one checked against section 0's table; they follow it, so they
  stay. Recording source (two choices with icons) = radio tiles; Live tabs, Connection
  and Network activity (short technical options) = plain radios; Who's listening (a
  frequent mode) = exclusive buttons, and arrows move the pick and apply it like radio
  buttons (new test). Fixed: Live tabs' two radios were stacked while Connection's and
  Network activity's sit in a row: now one wrapping row too. Left on purpose: Edit
  sound's *On press* stays a dropdown (five choices with long labels;
  as radios they'd add four rows to a tall window, and it's set once per sound).
  Checked offscreen in Dark and Light at 800x600 and 1180x720 (`tests/test_settings.py`,
  `tests/test_destpanel.py`).

- [x] **U3: Predictable configuration entry points.** Voice's Make it yours opens a
  retained modeless editor, AI voice More options expands inline, and mode options
  also appear in menus. Decide by complexity using section 0; retain intentional
  differences. Targets: `ui/voicepanel.py`, `ui/aivoicepanel.py`, `ui/destpanel.py`.
  Acceptance: a few fields expand inline; large/live tuning gets one retained editor;
  entry labels explain the task, reopening raises the existing editor, and collapsed
  cards keep the common controls visible.

  Done (PR #419): checked each entry against section 0; the two kinds are right for
  their size and stay. *Make it yours* (pitch, every effect, saved voices) is the one
  retained modeless editor: a second click raises it, closing keeps what you set.
  *More options* (two to four fields) expands in place on AI voices, Speak another
  language and, as *Clip editor*, an Apps card; all three now come from one helper
  (`panel.fold_button`). Fixed: *Make it yours* was under all 24 voice tiles (off the
  bottom at 1180x720); it now sits beside the on/off switch and wraps under it when
  narrow. Speak another language's *More options* was below the *What the voice said*
  box; it now follows the voice and speed. The Say bar lost its own volume (the owner's
  call): a typed line plays like a sound, so the bottom bar's volumes set it. Left on
  purpose: Who's listening is both a rail menu (a quick switch) and Settings > Audio's card (the full choice);
  *What do these do?* there and the AI voice browser still open modal (help and a
  pick-a-voice list; converting them needs the lifecycle review U4 did). Checked
  offscreen in Dark and Light at 440, 800x600 and 1180x720 (`tests/test_voicepanel.py`).

- [x] **U4: Consistent live/draft and modal contracts.** MainWindow opens Settings
  and Edit sound with `exec()`; Voice tuning explicitly stays modeless. Settings
  apply immediately; Edit commits on Save. Targets: `ui/mainwindow.py`,
  `settings.py`, `ui/dialogs.py`, `ui/voicepanel.py`. Acceptance: preferences/live
  tuning permit continued app use; transactional Save/Cancel remains intact; modal
  tasks have an explicit reason. Before converting, check lifetime, repeated opening,
  deletion of the edited item, async results, preview rollback and shortcut behaviour.

  Done (PR #413): Settings is a page in the main window, not a window: it takes the
  place of the tabs and the bars over them (`_content`, a stack), while the tab rail
  and the player + mixer strip stay, so sounds can still be played and stopped. The
  rail's cog (icon only, a square) shows selected while it's up; a back arrow over the
  categories (no `[Done]` row), Escape or any rail tab (also Ctrl+1...) goes back to
  the tab you were on. It keeps its own category list and
  search, applies live (no Save/Cancel), and every `open_settings("page")` link lands
  on that page (`SettingsDialog.show_page`, clearing a search first). Under 640 px the
  categories become an icon column (names as tips) and the search box goes over the
  page, so it fits 440 to 1920 wide. Made too small for it, Settings closes and the
  mini player shows; asked for from the mini player, the window grows to fit it
  (`SETTINGS_ROOM`). Edit sound opens with `show()` beside the board: a draft with
  `[Save] [Cancel]`, one window per sound (editing it again raises it); Save applies
  to the sound as it is in the list then, and removing the sound closes its window
  unsaved (Undo brings it back as it was). Previews stop on close either way. Checked
  offscreen in Dark and Light at 440 to 1920 wide, with GIFs
  (`tests/test_shell_dialogs.py`, `test_audit_main.py`). Kept modal on purpose: the
  yes/no questions, catching a hotkey and the setup guide (each needs an answer
  before the app can go on).

## Polish next

- [x] **U5: Button/icon/label consistency.** Reset, help, folder and configuration
  actions mix text, icon-with-text and icon-only treatments. Examples include What
  do these do?, Save as new sound and Browse for a program. Targets: `ui/destpanel.py`,
  `ui/dialogs.py`, `ui/programpick.py`, `settings.py`. Acceptance: short labels, a
  consistent treatment for each action family, main actions still understandable,
  tooltips/accessibility names on icons and no smaller click targets.

  Folder family done (PR #400): `panel.icon_button` (tooltip and accessible name
  from one string) and every plain "open this folder" action is now a quiet
  icon-only folder button: Settings > Data & quality (videos), the Voice tab's
  speech and add-ons folders, and the crash report. The crash report's button is
  named "Open folder"; its tooltip adds what the folder holds. Kept labelled on
  purpose: *Sounds folder* in the toolbar and *Browse for a program*, where a new
  person needs the words. Checked offscreen in Dark (`tests/test_icon_actions.py`).

  Rest done (PR #415): **reset family** (`panel.reset_button`): one slim muted
  *Reset* link with the reset arrow beside an effect, the live controls (was *Reset
  all*, a filled button) and a sound's effects (was a small button); the tooltip says
  what goes back, heading rows keep their height. **Help**: the sound modes' *What do
  these do?* (a four-word button on its own row) is an ⓘ beside the *Who's listening*
  heading (`panel.info_button`, `card(beside=...)`, centred on the heading's cap
  height). The mode buttons got the sidebar mode button's pictures. *Save as new
  sound* is *Save a copy* (three words at most). **Configuration**: the two *More
  options* disclosures already share one look (`#fold`); *Make it yours* vs inline
  options is U3. Checked offscreen in Dark and Light at 800x600 and 1180x720
  (`tests/test_icon_actions.py`).

- [x] **U6: Settings card hierarchy.** Sampled General/Audio/Connection cards are
  predominantly stacked forms; Appearance and Recording have stronger grouping
  and choice hierarchy. Target: `settings.py`. Acceptance: clear headings, compact
  labelled fields, hints/help on demand, status when meaningful and consistent
  spacing. Keep technical settings as readable forms where appropriate; do not add
  decorative tiles or redundant pills merely to satisfy a visual quota.

  Done (PR #423): rendered all 13 pages (Settings is a page in the window since U4).
  The cards already have a heading, a hint and compact labelled rows; kept as forms.
  Fixed where one card broke the pattern: General's *Play pads with one click* had its
  explanation at the card's edge (now `_option`, under the box's text like the rest);
  Overlay's *Open overlay* ran to the card's edge and *Auto-hide after*'s choice sat at
  the far right (both now as wide as their words, right after what they belong to);
  Audio's *While I talk, lower my sounds:* wrapped onto two lines with room to spare
  (Settings wraps every label; a `keepline` property opts a short field label out).
  Checked offscreen in Dark and Light at 1180x720 (`tests/test_settings.py`).

- [x] **U7: Shared help-popup treatment.** `TabHelpPopup` in `ui/dialogs.py` defines
  local pixel typography, padding, border and close styling. Acceptance: reuse shared
  typography/surface/action roles; coherent help placement, Escape/outside dismissal,
  focus return and accessible close action. Verify Dark, Light and High Contrast.

  Done (PR #416): `TabHelpPopup` sets no style of its own: `#helpcard` (panel
  surface, an edge because it floats over the board, 16 px corners), `#helptitle` (the
  title role, 13pt bold `text_hi`) and `#helpbody`, all in
  `theme.py`, so it follows every theme. Close is the painted `close` icon
  (`icons.py`) as a quiet `icon_button` named *Close* (it was a typed ×). Escape, the
  close button or a click outside close it (the "Click outside to close" line
  went: people do it anyway), and the focus goes back to its opener.
  Checked offscreen in Dark, Light and High Contrast (`tests/test_card_ui_fixes.py`).

## Coverage still needed

- [x] **U8: Populated Apps and installed Triggers.** Check their item menus,
  submenus, configuration and confirmation states with safe test fixtures; the
  initial spot audit did not cover them. Treat new observations as findings only
  after inspection. Triggers' add-on UI is maintained separately.

  Done (PR #422): rendered Apps with six programs in three categories (cards, the
  card menu and its Categories submenu, a category heading's menu) and the Triggers
  tab without the add-on, Dark and Light at 800x600 and 1180x720. Fine as they are:
  the card menu (Categories ticked, red Remove), the heading menu. Fixed: **Triggers
  without the add-on** was a window popping up on entering the tab and, once closed,
  an empty page with one button. Now the tab itself is Onion Watch's card, short like an
  ad (the owner's call): its logo (`assets/art/onion-watch.png`, from the add-on's own
  painted logo) and name, one line, four points with painted icons, *Get Onion Watch*
  as the one filled button, Hoot beside them, one line of fine print (the full privacy
  words are its tooltip); centred on the tab, a `HoverCard`. No window. **Apps cards** open their
  menu with the Menu key or Shift+F10 from anything in the card (it was right-click
  only). New findings: U13, U14, U15 below (`tests/test_triggerstab.py`,
  `tests/test_appspanel.py`).
- [x] **U9: Menu interaction and accessibility pass.** Check Sounds/Apps/Radio/Voice
  menus for action grouping, current-value checkmarks, destructive treatment,
  visible alternatives to right-click, keyboard navigation, focus return and screen
  edges. Existing `DropdownMenu` and `QMenu` usage is a starting point, not evidence
  that these behaviours fail. Include light theme and small windows.

  Started (PR #399): the Sounds bulk Colour menu checks the shared colour (none
  for a mixed selection) and the empty and filled boards share one "Drop sound
  files here" hint. Checked offscreen in Dark, Light, High Contrast and Retro 98 at
  narrow and normal sizes.

  Done (PR #414): one colour list for both Sounds Colour menus
  (`padbatch.fill_colour_menu`): named colours (the bulk one showed `#1fb6ff`), the
  current one ticked on its own dot (the category one had a typed "✓" and bold). The
  Apps card's Categories tick the program's category (it was greyed out) and keep
  "Music & media"'s "&" (it read "Music _media"); the Apps card and category heading
  menus got icons, a short red Remove / Delete category (the long words are the
  tooltip). The picked-pads menu lost its empty first row (a section title our menu
  style doesn't draw). Shuffled play got the shuffle icon. Checked offscreen in Dark
  and Light (`tests/test_padbatch.py`, `test_appspanel.py`). Checked and fine as they
  are: the pad menu (Menu key / Shift+F10 open it), Voice's saved-voice menu (red
  Delete; Menu key on the focused tile), Radio's country dropdown. Left for later:
  Apps cards and headings have no keyboard way to their menu (the card's ✕ and drag
  cover remove and move), and Apps category names aren't translated.

## Merged in from the earlier audits

Rechecked against `origin/main` 09b72491 (1.9.28) on 11 October with offscreen renders
at 360×320 to 1920×1080. Everything else from those audits is already on main: mini
mode only at very small sizes (360×320 yes, 440×380 no) with status + mic in it, Setup devices first, labelled sidebar
and audio footer, grouped Sounds toolbar, Voice changer open by default, pad sorting
with play counts, Ctrl+wheel pad volume, Save as sound, list view, category colours.

- [x] **U10: Dim secondary text.** Hints, pad durations, "Drop sound files here",
  "Pad size" and empty-state lines are still faint on the dark background. Measure
  contrast (aim for WCAG AA, 4.5:1) in Dark, Light and the other themes, then raise
  the secondary text colour token rather than patching single labels.

  Done (PR #409): measured every theme. `muted`/`faint` already cleared 4.5:1 on
  bg, panel, card, card_hi and btn, but not on `btn_hover` (quiet buttons and rail
  tabs under the mouse) or `inset`: 3.6-4.5:1 in 30 of 31 themes (Deep Fried 3.6,
  Barbie 3.95, Dark 4.06). `theme.SECONDARY_ON` now lists those surfaces too, so the
  tokens lift until they pass; nothing got dimmer. Placeholder text ("Search sounds
  or paste a link") was Qt's half-see-through text colour (Light 3.2:1, Retro 98
  4.0, Dark 4.2): the style sheet now gives it `$muted` (5.9, 11.4, 5.9). Checked
  offscreen in Dark, Light and High Contrast at 440, 800x600, 1180x720 and 1920x1080
  (`tests/test_ui_audit.py`).
- [x] **U11: Full-screen stretching.** At 1920×1080 the seek bar, the *What others
  hear* meter, the search box and the drop box run the whole width. Cap utility widths
  (DESIGN: narrow by default) and recheck with a populated board.
- [x] **U12: One control height, one bar height, an interface size.** The Sounds
  toolbar (52 px, 40 px controls), player bar (51) and mic bar (47) were all
  different, so the header looked heavy beside the tab rail. Now `panel.CONTROL_H`
  (36) for the toolbar's buttons, the search box and play/stop, and `panel.BAR_H` (48)
  for every bar (`panel.bar()` and the mixer strip). New *Interface size* card in
  Settings > Appearance (80-150 %, `Config.ui_scale`): `app.ui_scale_startup` sets
  `QT_SCALE_FACTOR` before the QApplication, so a change offers *Restart now*.
  No Ctrl +/- keys: each press would restart the app. Search width is U11's.
  Checked offscreen at 800x600, 1280x760 and 1920x1080, and at 125 %
  (`tests/test_ui_size.py`).

  Decided with the owner (11 October): **only the search box is capped**
  (`SEARCH_MAX_W` 480, PR #411; 456 px at 1180x720, so normal windows are unchanged).
  A few words go in it, so past that it was only a longer empty bar. The seek bar,
  the meter and the drop box **keep following the window on purpose**: a longer seek
  bar seeks finer, and capping them only traded a long control for an empty gap
  (PR #410, capping all four, was closed for that). Don't re-cap them.

- [x] **U13: Program names from the file name.** Apps cards title a program from
  its .exe: *Vlc*, *Obs64* (the window says VLC and OBS). Use the program's own
  name (its file description, as Windows' volume mixer does) and keep the .exe
  stem only as a fallback. Target: `appaudio.App.name`, `ui/appspanel.py`.

  Done (PR #424): `appaudio.file_description` reads the .exe's FileDescription on
  the lister's worker, cached per path; `App.name` uses it (*VLC media player*,
  *OBS Studio*), and a card keeps it once the program closes.
- [ ] **U14: Apps category names aren't translated.** The built-in categories
  (Browsers, Music & media, Calls & chat, Games, Other) show in English in every
  language; translate the shown name, keep the saved key. Target: `ui/appspanel.py`.
- [ ] **U15: Apps category headings have no keyboard way to their menu** (Rename,
  Delete). They take no focus; give them one with a visible focus ring, or put the
  menu on a small button beside the heading. Target: `ui/appspanel.py`.

### Features for later (not UI fixes; after 2.0)

- Lower other programs (Spotify, the game) while a sound plays; `appaudio` already
  lists the sessions.
- Timed sounds: play X every N minutes or at a set time.
- Twitch / YouTube chat and channel-point triggers built in.
- A native Stream Deck plugin.
- Multiple boards / profiles with one switch (low priority).

## Ready-to-paste LLM handoff

```text
Improve Onion Board UI consistency using the existing PySide6 widgets and theme
system. Read AGENTS.md, CLAUDE.md and docs/AGENT-RULES.md first. Start from latest
origin/main in an isolated branch/worktree; check open PRs for overlapping work.
Read docs/DESIGN.md: Fluent 2 supplies interaction guidance; our Qt components,
themes and local action-order rules supply the implementation. Follow section 0
for controls/surfaces and section 14 for the UI workflow.
Use docs/UI-AUDIT.md as the backlog (the only UI to-do list). U1 requires bottom-right dialog actions:
stretch before the action group, main action first within that group, then
alternatives/Cancel/Done. Ordinary fields and card/toolbar actions stay beside
their content. U1 is done (PR #398); U5's folder family (PR #400) and part of
U9 (PR #399) are done. Work through the open U-items in separate changes. Report intentional
differences instead of forcing every choice into one widget type. Preserve live
settings versus draft Save/Cancel, preview, keyboard access and window lifetimes.
Reuse small shared helpers, translate changed UI text in every language, inspect
offscreen screenshots of the full affected page and secondary states, run scoped
precommit checks, and show the pictures. Never launch the live app without asking.
Leave PRs open for review; do not merge unless explicitly asked. Any authorized
merge must follow the repository's local UTC merge rules. Update the backlog with each
completed PR and validation; leave unverified items open. This document records
existing observations; no UI fixes have been implemented by the documentation PR.
```
