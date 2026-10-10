# Rules from past regressions (for AI agents and anyone else)

About 300 of the first 700 commits were fixes, and most of them were the same few
mistakes made again. Each rule below is one of those mistakes, with commits that
fixed it (`git show <hash>` to see the fix). Check your change against the rules for the area
you touched before committing. When you fix a new kind of regression, add a line here.

## Before the first edit: latest main, open PRs

Every task, before changing anything (details in `CLAUDE.md`):

1. `git fetch origin` and work on a new branch (or worktree) off `origin/main`.
   Never edit someone else's dirty checkout.
2. Confirm it: `git status -sb` doesn't say `behind`; your `HEAD` is `origin/main`'s.
3. `gh pr list --state open`: if a PR already does this or touches the same code,
   stop and tell the user. No duplicate work.

## What to read for a task (don't read the rest)

| Task | Read | Skip |
|---|---|---|
| Small fix in one module | this file, the module, its test (`scripts/pick_tests.py --local`) | DESIGN, FEATURES, CHANGELOG |
| Any UI change | this file, [DESIGN.md](DESIGN.md) | FEATURES, CHANGELOG |
| Audio path, mic effect, engine | this file, [CODE.md](CODE.md) *Audio notes* and *Sending sounds* | DESIGN |
| New module or file | [CODE.md](CODE.md) *Code layout* (add it there) | |
| Text a user sees | `CLAUDE.md` *Text the app shows*, [TRANSLATING.md](TRANSLATING.md) | |
| Build, installer, release | [DEVELOPING.md](DEVELOPING.md) sections 4 to 7 | DESIGN |

- **`CHANGELOG.md` is append-only for agents:** never read it whole (1700+ lines). Add
  your line under `## Unreleased` (read its first ~30 lines for the style).
- The big files (`ui/mainwindow.py`, `ui/voicepanel.py`, `engine.py`, `ui/setupwizard.py`,
  `tests/test_mainwindow.py`): grep for the name you need, then read only that range.
- `git log --oneline -S <name>` finds when and why something changed faster than reading.

## The rules

### UI thread (about 80 fixes: the biggest group)
- Disk, network, device, process and capture calls never run on the Qt UI thread.
  Run them on a worker, and the UI thread only applies the result.
  `9fa49b9` `154b0f5` `307ff86`
- Work that grows with the data (drawing a map, listing a folder, filling a big list)
  goes in slices or tiles, never all at once. `307ff86`
- A timer that repaints slows down while the app is in the background
  (`ui/appstate.py`: `slow_in_background`, `pause_in_background`).

### Async results (about 26)
- A worker's result or a delayed callback checks that its owner (tab, dialog, engine
  voice) still exists and is still on before touching it. Tabs get switched off and
  dialogs get closed while work is in flight. `a885d6e` `42b9526`
- Qt objects are created and freed on the UI thread only.

### Audio path (about 50)
- Audio callbacks and the mic effect never block, take the engine lock, allocate,
  touch Qt or do file I/O ([CODE.md](CODE.md) *Audio notes*). `4b4f9a7` `e5cc373`
- Anything the native mic effect reads (the ring file) is fuzzed:
  `scripts/fuzz_directmic.py`, and `scripts/build_directmic.py --testhost` before the
  `test_directmic.py` tests, which CI skips.

### Tests (about 24)
- Garbage collection runs only on the UI thread (`soundboard/uigc.py`). Python's GC on an
  audio or worker thread frees Qt objects there and crashes natively. `15d7fb5`
- A test needing a port that refuses uses `closed_port()` / `ipv4_only()` from
  `tests/conftest.py`, never a hard-coded port.
- A timing test takes the best of several tries and skips on CI. A busy runner
  makes single measurements flaky. `63fe4e5`
- Tests never touch the real `%APPDATA%\OnionBoard`, real devices or real hotkeys;
  `conftest.py` fakes them. Keep it that way in new fixtures.

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

### Releases (about 45 hand-made commits)
- Bump with `scripts/release.py X.Y.Z`, never by hand. It dates the changelog, sets
  `__version__` and refreshes the release line. `tests/test_release.py` fails when
  `__init__.py` and the changelog disagree.

## Before every commit

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\precommit.ps1        # what you changed
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\precommit.ps1 -All   # once before a PR
```

It runs ruff, the sensitive-data scan and the translation check, then pytest on just
the test files your committed and uncommitted changes need.
