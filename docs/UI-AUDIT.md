# UI consistency backlog

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

- [ ] **U2: A clear rule for choice controls.** Recording source uses radio tiles;
  Appearance's live indicator and Connection use plain radios; output modes use
  exclusive buttons; Edit playback uses a combo. These are not all defects: compare
  task and available space against DESIGN section 0 before changing them.
  Targets: `ui/recordmic.py`, `settings.py`, `ui/destpanel.py`, `ui/dialogs.py`.
  Acceptance: comparable choices use the same pattern; labels, exclusivity,
  keyboard selection and saved values work; dynamic device lists remain dropdowns.

- [ ] **U3: Predictable configuration entry points.** Voice's Make it yours opens a
  retained modeless editor, AI voice More options expands inline, and mode options
  also appear in menus. Decide by complexity using section 0; retain intentional
  differences. Targets: `ui/voicepanel.py`, `ui/aivoicepanel.py`, `ui/destpanel.py`.
  Acceptance: a few fields expand inline; large/live tuning gets one retained editor;
  entry labels explain the task, reopening raises the existing editor, and collapsed
  cards keep the common controls visible.

- [ ] **U4: Consistent live/draft and modal contracts.** MainWindow opens Settings
  and Edit sound with `exec()`; Voice tuning explicitly stays modeless. Settings
  apply immediately; Edit commits on Save. Targets: `ui/mainwindow.py`,
  `settings.py`, `ui/dialogs.py`, `ui/voicepanel.py`. Acceptance: preferences/live
  tuning permit continued app use; transactional Save/Cancel remains intact; modal
  tasks have an explicit reason. Before converting, check lifetime, repeated opening,
  deletion of the edited item, async results, preview rollback and shortcut behaviour.

## Polish next

- [ ] **U5: Button/icon/label consistency.** Reset, help, folder and configuration
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
  Still open: the reset, help (*What do these do?*) and configuration families,
  and *Save as new sound*.

- [ ] **U6: Settings card hierarchy.** Sampled General/Audio/Connection cards are
  predominantly stacked forms; Appearance and Recording have stronger grouping
  and choice hierarchy. Target: `settings.py`. Acceptance: clear headings, compact
  labelled fields, hints/help on demand, status when meaningful and consistent
  spacing. Keep technical settings as readable forms where appropriate; do not add
  decorative tiles or redundant pills merely to satisfy a visual quota.

- [ ] **U7: Shared help-popup treatment.** `TabHelpPopup` in `ui/dialogs.py` defines
  local pixel typography, padding, border and close styling. Acceptance: reuse shared
  typography/surface/action roles; coherent help placement, Escape/outside dismissal,
  focus return and accessible close action. Verify Dark, Light and High Contrast.

## Coverage still needed

- [ ] **U8: Populated Apps and installed Triggers.** Check their item menus,
  submenus, configuration and confirmation states with safe test fixtures; the
  initial spot audit did not cover them. Treat new observations as findings only
  after inspection. Triggers' add-on UI is maintained separately.
- [ ] **U9: Menu interaction and accessibility pass.** Check Sounds/Apps/Radio/Voice
  menus for action grouping, current-value checkmarks, destructive treatment,
  visible alternatives to right-click, keyboard navigation, focus return and screen
  edges. Existing `DropdownMenu` and `QMenu` usage is a starting point, not evidence
  that these behaviours fail. Include light theme and small windows.

  Started (PR #399): the Sounds bulk Colour menu checks the shared colour (none
  for a mixed selection) and the empty and filled boards share one "Drop sound
  files here" hint. Checked offscreen in Dark, Light, High Contrast and Retro 98 at
  narrow and normal sizes. Still open: the rest of the Sounds menus, and the Apps,
  Radio and Voice menus.

## Ready-to-paste LLM handoff

```text
Improve Onion Board UI consistency using the existing PySide6 widgets and theme
system. Read AGENTS.md, CLAUDE.md and docs/AGENT-RULES.md first. Start from latest
origin/main in an isolated branch/worktree; check open PRs for overlapping work.
Read docs/DESIGN.md: Fluent 2 supplies interaction guidance; our Qt components,
themes and local action-order rules supply the implementation. Follow section 0
for controls/surfaces and section 14 for the UI workflow.
Use docs/UI-AUDIT.md as the backlog. U1 requires bottom-right dialog actions:
stretch before the action group, main action first within that group, then
alternatives/Cancel/Done. Ordinary fields and card/toolbar actions stay beside
their content. U1 is done (PR #398); U5's folder family (PR #400) and part of
U9 (PR #399) are done. Work through U2-U4 in separate changes. Report intentional
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
