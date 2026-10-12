# Rules from past regressions (for AI agents and anyone else)

About 300 of the first 700 commits were fixes, and most of them were the same few
mistakes made again. Each rule below is one of those mistakes, with commits that
fixed it (`git show <hash>` to see the fix). Check your change against the rules for the area
you touched before committing. When you fix a new kind of regression, add a line here.

Before the first edit, every task: latest `origin/main` and the open PRs
([CLAUDE.md *Before you change anything*](../CLAUDE.md#before-you-change-anything-sync-first-check-open-prs)).

## What to read for a task (don't read the rest)

| Task | Read | Skip |
|---|---|---|
| Small fix in one module | this file, the module, its test (`scripts/pick_tests.py --local`) | DESIGN, FEATURES, CHANGELOG |
| Any UI change | this file, [DESIGN.md](DESIGN.md), relevant [UI-AUDIT.md](UI-AUDIT.md) items | FEATURES, CHANGELOG |
| Audio path, mic effect, engine | this file, [CODE.md](CODE.md) *Audio notes* and *Sending sounds* | DESIGN |
| New module or file | [CODE.md](CODE.md) *Code layout* (add it there) | |
| Text a user sees | `CLAUDE.md` *Text the app shows*, [TRANSLATING.md](TRANSLATING.md) | |
| Bun the mascot: drawing, outfits, animations | [MASCOT.md](MASCOT.md) | |
| Build, installer, release | [DEVELOPING.md](DEVELOPING.md) sections 4 to 7 | DESIGN |

- Never read `CHANGELOG.md` whole (2000+ lines), and never edit it for a change:
  [changelog.d/README.md](../changelog.d/README.md).
- The big files (`ui/mainwindow.py`, `ui/voicepanel.py`, `engine.py`, `ui/setupwizard.py`,
  `tests/test_mainwindow.py`): grep for the name you need, then read only that range.
- `git log --oneline -S <name>` finds when and why something changed faster than reading.

## Where each rule lives (one home each; elsewhere only a link)

| Rule | Home |
|---|---|
| Sync to `origin/main`, check open PRs, worktree for a dirty checkout | [CLAUDE.md](../CLAUDE.md) *Before you change anything* |
| Commit times in UTC, merging only with `scripts/merge_pr.sh`, no history rewrites | [CLAUDE.md](../CLAUDE.md) *Commit times and merging* |
| Public repo: secrets, personal data, assets, network table, loopback | [CONTRIBUTING.md](../CONTRIBUTING.md) *Rules that aren't negotiable* (agent extras: CLAUDE.md) |
| Text in every language | [CLAUDE.md](../CLAUDE.md) *Text the app shows*; details [TRANSLATING.md](TRANSLATING.md) |
| UI look, sizes, text style, dialog actions, UI workflow | [DESIGN.md](DESIGN.md) |
| UI to-do list | [UI-AUDIT.md](UI-AUDIT.md) |
| Changelog entries | [changelog.d/README.md](../changelog.d/README.md) |
| Ask before launching the app or the mic effect's admin steps | [CLAUDE.md](../CLAUDE.md) *Working in the code* |
| Regression rules (UI thread, async, audio path, tests, frozen build) | this file, *The rules* |
| The quick check before a commit, and what's left to CI | this file, *Before every commit* |
| Setup, test, build, install and release commands; what needs a rebuild | [DEVELOPING.md](DEVELOPING.md) |
| Code layout, audio internals | [CODE.md](CODE.md) |

## The rules

### Every fix has a test
- A bug fix comes with a test that fails without the fix and passes with it, so the
  same mistake can't come back unseen. The PR's `Regression test:` line names it, or
  says `none: <why>` (e.g. only a real device or the frozen build shows it).
  `precommit.ps1` warns when a `fix/*` branch or a "fix" commit changes `soundboard/`
  but nothing in `tests/`.

### UI thread (about 80 fixes: the biggest group)
#### Layout acceptance
- Review the complete final screen, using the final branch with current main included,
  before presenting a UI change or merging it. Check Dark and Light, empty and populated
  boards, 800x600, 1180x720, and the mini/full transition. A change to colours, icons
  or the style sheet: check **all 31 themes** in `theme.THEMES`, not just Dark and Light
  (fresh launch and a live switch from Dark; `tests/test_every_theme.py`). Half the
  themes once looked unfinished because only two were ever looked at. Inspect controls together,
  including their spacing and unused areas, rather than approving individual widgets.
- Keep the large drop target across the board's full width. Keep the audio footer compact
  and its controls using the available width. A hidden playback label must leave no
  reserved gap before the seek slider. Sidebar buttons need at least 34 px height and
  4 px spacing at normal window sizes. Preserve normal navigation at 800x600.
- Sidebar edge drag has three states, no steps between: shut below halfway (one icon
  column, centred), mid from halfway (names; what doesn't fit is hidden or kept
  small), full once everything fits (`_full_fit`). Attention dots sit on their icon.
- Card headings come from `card()` / `heading_row()` only, every part centred on the
  title's cap height from the font, never `AlignVCenter` or a margin found by eye
  (DESIGN section 4, *Card headings*). `tests/test_card_headings.py` measures the ink.
- Add regression checks for a reported layout defect, and run them before committing.
  Do not treat a partial spacing adjustment as completion of the screen's review.
- Moving a widget between layouts (re-stacking columns, reflowing a grid): take it out
  with `widgets.take_out()`, never a bare `takeAt()`. An item that's taken but never freed
  keeps the widget's size changes, so the re-added card keeps a stale height and gets
  squeezed until the width changes.

- Disk, network, device, process and capture calls never run on the Qt UI thread.
  Run them on a worker, and the UI thread only applies the result.
  `9fa49b9` `154b0f5` `307ff86`
- `MainWindow.__init__` pumps events (the splash) part-way through, so timers and
  worker answers can reach any slot before `__init__` ends. Set every attribute a
  slot reads before the first `splash.pump()`; `test_triggers_timer_during_start_up`
  sends them in at each pump. `9636b3f4`
- Work that grows with the data (drawing a map, listing a folder, filling a big list)
  goes in slices or tiles, never all at once. `307ff86`
- A timer that repaints slows down while the app is in the background
  (`ui/appstate.py`: `slow_in_background`, `pause_in_background`).

### Async results (about 26)
- Background cache writers use unique temporary files and coordinate replacement
  with readers across owner instances; Windows refuses replacement of open files.
- A worker's result or a delayed callback checks that its owner (tab, dialog, engine
  voice) still exists and is still on before touching it. Tabs get switched off and
  dialogs get closed while work is in flight. `a885d6e` `42b9526`
- Qt objects are created and freed on the UI thread only.
- Never walk layouts with `layout.itemAt(i).layout()`: it gives every item a PySide
  wrapper, and when a `QStackedWidget` page goes (a tab switched off) Qt frees the item
  but the dead wrapper stays registered at its address; the next object Qt makes there
  crashes natively on its first event. Use `layout.findChildren(QLayout)`. (#389, issue #339)

### Audio path (about 50)
- Audio callbacks and the mic effect never block, take the engine lock, allocate,
  touch Qt or do file I/O ([CODE.md](CODE.md) *Audio notes*). `4b4f9a7` `e5cc373`
- Anything the native mic effect reads (the ring file) is fuzzed:
  `scripts/fuzz_directmic.py`, and `scripts/build_directmic.py --testhost` before the
  `test_directmic.py` tests. CI's `mic-effect` job does all of it on a PR that touches
  the effect, plus `scripts/check_directmic.py` (warnings as errors, GCC's analyzer,
  cppcheck): run that one locally before pushing C++ changes.
- The mic effect's admin install / uninstall (`soundboard/directmic.py`: copying the DLL,
  registering it, putting it on a mic, taking it off) is fuzzed at every registry write:
  **run `python scripts/sim_directmic.py` after changing it, or the ring layout**, before
  opening the PR. It drives the real code against the fake registry and checks a mic
  always ends up exactly as it started, even when the step is cut off half-way (a crash,
  a reboot). CI runs the normal-path tests; this reaches the interrupted paths by hand.

### Tests (about 24)
- Garbage collection runs only on the UI thread (`soundboard/uigc.py`). Python's GC on an
  audio or worker thread frees Qt objects there and crashes natively. `15d7fb5`
- So is what a finished thread held (its target, args, closures): `uigc` hands it to
  the UI thread, or a tab switched off mid-job was freed on the worker. A test that
  checks something a thread held is freed calls `uigc.let_go()` first.
- A test needing a port that refuses uses `closed_port()` / `ipv4_only()` from
  `tests/conftest.py`, never a hard-coded port.
- A timing test takes the best of several tries and skips on CI. A busy runner
  makes single measurements flaky. `63fe4e5`
- CI gives a failed or crashed test two more tries (`--reruns 2`), so a flake doesn't
  block a merge. A test that needed one is listed on the run's summary page as a
  warning: it's still a bug to fix, not a pass to lean on.
- Tests never touch the real `%APPDATA%\OnionBoard`, real devices or real hotkeys;
  `conftest.py` fakes them. Keep it that way in new fixtures.
- Offscreen traps that look like app bugs but aren't: an offscreen window is never
  active, so window shortcuts (Ctrl+1..9, Ctrl+Tab) don't fire; `QTest.keyClicks` with a
  zero-width joiner (family emoji) kills even a bare `QLineEdit` (set the text instead);
  Qt stores a label's `&` as `&&`.
- `QMenu.exec` can't be monkeypatched on the C++ class: swap a Python subclass into the
  module (`mod.QMenu = Shown`), as `tests/test_padbatch.py::menu_shows` does.

### Hotkeys and devices (about 10)
- Global hotkeys use `RegisterHotKey`, never a low-level keyboard hook. Hooks left
  keys stuck. `b2659e5`
- A device Windows lists may still refuse to open: catch it and re-scan, don't crash.

### Outside services
- Websites (search sources, radio, Discord) change without notice. Keep their parsing
  in one place with a test on saved-shape data, and fail with a message, not a crash.
  `05de134`

### Frozen build
- Changes to `build.ps1`, `scripts/prune_build.py`, PyInstaller hooks or bundled data
  only show in the built app: build with `-NoInstaller` and start it once. `8f6f343`
- **"DLL load failed while importing QtWidgets: The specified procedure could not be
  found"** means a foreign DLL got into `_internal\`: another program's ICU
  (`icuuc.dll`, `icudt78.dll`) or an older `msvcp140.dll`, picked up from a folder on
  the build PC's PATH (AI tool runtimes carry their own). `build.ps1` runs PyInstaller
  with only Windows' folders on PATH, and `scripts/vc_runtime.py` deletes bundled ICU
  and evens out the C++ runtime. Don't hand-delete files from `dist\` or `App\`: fix
  it in those two, then `build.ps1 -Clean` (the cached analysis keeps old paths). Find
  where a DLL came from in `build\OnionBoard\Analysis-00.toc`. On an installed copy
  it can also be an old installer run over a new install: reinstall with the current
  `OnionBoardSetup.exe` (it clears `_internal` first), never an older setup file.

### Releases (about 45 hand-made commits)
- Bump with `scripts/release.py X.Y.Z`, never by hand (the steps:
  [DEVELOPING.md](DEVELOPING.md) section 7). `tests/test_release.py` fails when
  `__init__.py` and the changelog disagree.

## Before every commit

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\precommit.ps1          # quick checks
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\precommit.ps1 -Tests   # + the picked tests
```

It runs ruff, the sensitive-data scan, the translation check and CODE.md's module list
(about 14 s), plus pyright on the Python files you changed: only type errors that
aren't in `scripts/pyright_baseline.json` fail (`scripts/check_types.py`). Fixed an old
one? `python scripts/check_types.py --update` shrinks the baseline. CI checks the whole
repo the same way (the `types` job; `test` fails with it). Pyright wrong? Add
`# pyright: ignore[rule]` with a reason. The tests are left to CI: push, open the PR and keep working while it runs
the test files your changes need, on 4 jobs side by side. `-Tests` runs those files here
(a change to `theme.py`, `mainwindow.py` or `library.py` picks most of the suite: about
4 minutes); use it only when you need a result before pushing. **Don't run `-All`
locally**: CI runs the whole suite on main after every merge (and on a branch when the
workflow is run by hand).
