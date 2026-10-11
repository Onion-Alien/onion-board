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
