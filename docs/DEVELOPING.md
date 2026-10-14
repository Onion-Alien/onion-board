# Developing, building and reinstalling

The loop for changing Onion Board, from edit to a reinstalled app. Written so an
AI agent can follow it headless; humans can too. Commands are run from the repo
root in PowerShell unless noted.

## 1. One-time setup

```powershell
py -3.13 -m venv .venv                 # Python 3.12+ works
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
git config core.hooksPath .githooks    # secrets check, commit times in UTC (required)
```

Build tools, only needed for step 4 (and for the mic effect's own tests):

```powershell
winget install BrechtSanders.WinLibs.POSIX.UCRT   # MinGW-w64 g++, for the mic effect (obmic.dll)
winget install JRSoftware.InnoSetup    # for OnionBoardSetup.exe
```

*Straight into my mic* runs from source too once the effect is built:
`.venv\Scripts\python scripts\build_directmic.py` writes `build\directmic\obmic.dll`
(g++ on `PATH`, winget's WinLibs folder, or `MINGW_GXX`); `--testhost` also builds
`testhost.exe` for the tests.

A `.venv` can't be moved or copied to another folder (its launchers hard-code the
path). If the repo moves, delete `.venv` and recreate it. The same goes for a
module's own `.venv` (e.g. `modules\live-voice\.venv`: recreate it with that
module's `install.bat` or `pip install -r requirements.txt`).

## 2. Change the code

- Layout: [CODE.md](CODE.md) → *Code layout*. Rules: [CONTRIBUTING.md](../CONTRIBUTING.md)
  and, for agents, [AGENT-RULES.md](AGENT-RULES.md) (audio callbacks, UI thread, tests).
- Anything user-visible gets a changelog line: [changelog.d/README.md](../changelog.d/README.md).
- The Triggers tab is the [Onion Watch](https://github.com/Onion-Alien/onion-watch)
  add-on, a separate project. Onion Board's side is `ui/triggerstab.py` (the tab,
  Hoot and the download), `ui/triggershost.py` (the host interface the add-on
  talks to; `modules.TRIGGERS_API` is the version of it this app can host) and
  `watchaddon.py` (its releases). To try an Onion Watch build before it's
  released, or while its repo isn't reachable, build its zip
  (`scripts\build_module.py` there) and start Onion Board with
  `ONIONBOARD_ONION_WATCH_ZIP` set to it: *Get Onion Watch* and the update check
  then use that file instead of GitHub. The add-on may only import what the built
  app ships (it has no pip): the standard library, numpy, soxr, scipy.fft and
  PySide6's QtCore / QtGui / QtWidgets. The app's own code doesn't import scipy (its
  filters are `soundboard/dsp.py`); `build.ps1` bundles only scipy.fft, with
  `--hidden-import`, for Onion Watch's matcher (which falls back to numpy's slower FFTs
  without it), and scipy.ndimage, which released Onion Watch 0.5.6 imports (its
  module.json lists it, so without it the Triggers tab refuses to load for everyone
  still on 0.5.6). The rest of scipy (signal, stats…) isn't shipped. **Never drop a
  part a released Onion Watch lists in its `imports`:** `RELEASED_WATCH_IMPORTS` in
  `tests/test_triggers_module.py` fails the tests if `build.ps1` stops shipping one;
  add each new release's list there. Removing scipy.fft from the build makes the
  Triggers tab slower; check it still runs: `OnionBoard.exe --selftest-addon <zip>`
  proves a build can run it (build.ps1 does that when `ONIONBOARD_ONION_WATCH_ZIP` is
  set). Before a release, run it on the newest *released* Onion Watch zip from
  GitHub too, not only one built from its main.

## 3. Check it (headless)

```powershell
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest -q
.venv\Scripts\python scripts\check_sensitive.py
```

Or the quick checks (ruff, the sensitive scan, translations, CODE.md) in one go,
`scripts\precommit.ps1`: how and when to use it, and what's left to CI, is
[AGENT-RULES.md *Before every commit*](AGENT-RULES.md#before-every-commit).

The tests are fully headless: `tests/conftest.py` forces Qt's `offscreen`
platform and a separate single-instance name, and never touches the real
`%APPDATA%\OnionBoard`. No window appears and no global hotkey is registered.
`sounddevice.OutputStream` is swapped for a silent stand-in that runs the
callback at the device's pace but plays nothing, so no test is ever heard on
the speakers or headphones (set `ONIONBOARD_TEST_REAL_AUDIO=1` to
opt out).
They're safe to run while someone is using the PC. The mic effect's tests
(`tests\test_directmic.py`) run the real DLL in `testhost.exe`, never on a real mic or
the registry; the ones that need the DLL are skipped until
`scripts\build_directmic.py --testhost` has built it. CI's `mic-effect` job builds it
and runs them (with a minute of fuzzing) on a PR that touches the effect.
`scripts\check_directmic.py` checks the C++ without running it: g++ with extra
warnings as errors, GCC's static analyzer and cppcheck (WinLibs ships it beside g++).
`scripts\build_directmic.py --fuzz` also builds `fuzzhost.exe`, which throws hostile and
half-written ring files at the effect (built with sanitizer traps);
`scripts\fuzz_directmic.py [seconds] [workers]` runs it for longer than the tests do.
`fuzzhost --lead` replays a late board block by block (no timing luck) and checks the
effect's lead grows just enough and comes back; the real-time tests can't pin that down.
`scripts\sim_directmic.py` drives the mic effect's admin install / uninstall against a
fake registry, killing it at every write (when to run it: AGENT-RULES *Audio path*).

**Not on Windows?** The suite also runs on Linux and macOS: `tests/offwindows.py`
stands in for Windows' registry (every key missing) and DLLs (every call fails), so the
app imports, and tests marked `@pytest.mark.windows` (or a file's `pytestmark`) are
skipped. Everything else (mixing, effects, config, the windows on Qt's offscreen
platform) runs as on Windows. CI runs the Linux tests only when asked:
`gh workflow run checks.yml -f linux=true`. On Debian / Ubuntu:

```sh
sudo apt-get install libportaudio2 libsndfile1 libegl1 libxkbcommon0 libgl1 libfontconfig1 libdbus-1-3 \
  libpulse0 libx11-xcb1 libxrandr2
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest==9.1.1 pytest-xdist==3.8.0 pytest-rerunfailures==16.7 ruff==0.16.10
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

`-m windows` or `-m "not windows"` picks either set on any system. Mark a test
`windows` only when it fails off Windows because of Windows itself (its registry, a
DLL, a Windows-only process or file), never to hide a real failure; anything that
changes Windows (the mic effect, the registry) is still checked only on Windows.

To iterate faster, run just the file you touched, e.g.
`.venv\Scripts\python -m pytest -q tests\test_engine.py`; CI runs the rest.
`python scripts\pick_tests.py` lists the test files your branch's
changes need (what a PR runs on CI). The full suite runs on 4 workers (pytest-xdist,
about 4 minutes); one or two files run in a single process. `-n 2` caps the workers (say, while a
game is running) and `-n 0` turns them off. You don't need to rebuild to see a change: `scripts\run.bat` runs
from source.

Keeping it fast: Windows takes ~2 s to refuse a connection to a closed port, even
on 127.0.0.1, and `localhost` tries `::1` first (hence AGENT-RULES' `closed_port()` /
`ipv4_only()` rule). `--durations=20` shows what's slow (CI lists them on every run).

Hangs and flakes: a test still running after 2 minutes is hung; every thread's stack
is printed and its worker stopped (`faulthandler_timeout` in `pyproject.toml`), and
the run goes on. Wall-clock audio timing tests carry `conftest.real_pc_timing`: CI's
shared runners stall a thread as long as the hitch they measure, so they run on a
real PC only. Something a test makes that a thread of its own (or Qt's) calls back
into is stopped after the test (`_STOP_AFTER_TEST` in `conftest.py`), as the app
stops it when its tab goes. A test that needs `time.sleep`, `threading.Thread` and
the like faked gives only the module under test a fake one (`conftest.own_module`,
`own_time`): patched on the real module, every leftover thread in the worker spins
or never starts. A wait on another thread polls until done (with a generous limit)
instead of sleeping a fixed time. `PYTEST_XDIST_AUTO_NUM_WORKERS=N` sets the workers
for the whole suite (8 on CI's 4 cores measured no faster than 4: runners differ by
up to 2x from run to run, so compare runs started at the same time).

### How heavy is it (the performance suite)

`.venv\Scripts\python -m perf --tier quick` (~1.5 min) runs the real app in a child
process on a throwaway profile, offscreen with fake audio devices, steps it through
idle, tray, imports, plays, previews, tabs, dialogs, the voice changer and a leak
loop, and writes `report.md`: CPU, RAM, threads, handles, disk writes and audio
callback lateness per step. `--tier full` is longer, `--watch-src <onion-watch
checkout>` adds the Triggers add-on and standalone Onion Watch, `--compare
old\report.json` shows before → after, and over `perf\budgets.json` it exits 1. It
isn't part of pytest. Tiers, scenarios and how to read it:
[perf/README.md](../perf/README.md).

### What voice chat does to the sounds (the bench)

`scripts\codec_bench.py` runs sounds through each voice chat's codec, and with
`--defaults` through its own mic cleanup and voice gate as the game ships it
(`--list` shows every profile: the games it covers, its settings and whether
they're measured, sourced or estimated). `scripts\dest_fit.py` ranks the
*Who's listening* modes for each game. The cleanup is the real WebRTC / RNNoise
code, which lives in a separate environment so the app's stays lean:

```powershell
py -3.13 -m venv .venv-bench
.venv-bench\Scripts\pip install -r requirements-bench.txt
.venv-bench\Scripts\python scripts\codec_bench.py --library --defaults
```

The real-world checks play test signals into the virtual cable (they need it
installed, even if you normally send your sounds elsewhere), so they aren't
headless: mute your mic in the app and stay out of calls that use the cable.
`game_capture.py` (which device Windows gives a game, its resampling, ducking;
with no flags it only reports), `steam_voice_roundtrip.py` (Steam's own voice
codec, one PC, one account), `discord_roundtrip.py` and `game_roundtrip.py` (a
friend records the game on their end). The stacks, their sources and what the
bench found: [GAME-VOICE.md](GAME-VOICE.md).

**After any change to the sending path** (the mic effect, `directmic.py`, routes, send volume or the *Who's listening* modes), run the maintainer's silent voice check (`voicecheck.py`, kept outside the repo because it needs Vivox and Epic developer keys; ~3 min) and paste its table into the PR: it shows what Discord, Vivox and Epic voice do to 3 songs, and whether apps opening the mic each way still get our sounds.

**Launching the real app is not headless.** It opens a window, grabs global
hotkeys and opens audio devices: `scripts\run.bat`, `python -m soundboard`,
`OnionBoard.exe` and the installer all do (agents: ask first, CLAUDE.md).

## 4. Build the app and the installer

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

This produces:

| output | what |
|---|---|
| `dist\OnionBoard\OnionBoard.exe` | the one-folder app (PyInstaller), with `LICENSE.txt` and `THIRD-PARTY-NOTICES.txt` beside it |
| `dist\OnionBoardSetup.exe` | the installer (Inno Setup). Skipped with a warning if Inno Setup isn't installed |

`-AppDir <dir>` and `-InstallerDir <dir>` also copy those results elsewhere,
e.g. `build.ps1 -AppDir ..\App -InstallerDir ..\Installer`.

Rebuilds are incremental: PyInstaller reuses its analysis cache in `build\`.
`-Clean` starts from scratch (do this for a release, or if a build misbehaves).
`-NoInstaller` stops after the app folder and skips the Inno Setup compression.

Tor isn't part of the build: the app downloads it when asked (`soundboard\torget.py`,
which pins the version and SHA-256 and says how to move to a newer Tor; the
installer's *Private connection (Tor)* box runs `OnionBoard.exe --get-tor`). To try
Tor mode from source without pressing *Get Tor*, `scripts\fetch_tor.py` unpacks the
same files into the gitignored `vendor\tor`.

Build steps, in order: `scripts\build_bootloader.ps1` (only when `.venv` has
PyInstaller's stock bootloader: rebuilds PyInstaller with one compiled here by
MinGW-w64's gcc, as virus scanners flag the stock one, which is in thousands of
programs, some of them malware; that build is then `-Clean`. Without gcc this step
warns and the build falls back to the stock bootloader, so a dev build still works —
install gcc for a clean release build),
`scripts\version_info.py` (the .exe's version resource),
`scripts\build_directmic.py` (the mic effect; the build stops
if g++ is missing), `scripts\build_michelper.py` (the mic helper `obmichelper.exe`,
a `--console` build whose Python archive sits beside the .exe rather than appended to
it — both to avoid antivirus false positives; it warns, but still builds, on the stock
bootloader), PyInstaller (bundles `installer\install-vbcable.ps1` and
`assets\onionboard.ico` as data, both at the root of `_internal\`, and `obmic.dll` in
`_internal\directmic\`),
`scripts\vc_runtime.py` (overwrites any older copy of the C++ runtime, `msvcp140.dll`
and the rest, with the newest, PySide6's own: an older one from the build PC stops the
app at start with "The specified procedure could not be found"; it also deletes any
ICU DLL another program on PATH slipped in, as Qt uses Windows' own; PyInstaller
itself runs with only Windows' folders on PATH),
`scripts\prune_build.py` (removes the parts of Qt the app never loads — QML, 3D,
charts, the web engine, unused image formats, translations — by walking the DLL import tables; the
build fails if a kept file would lose an import), `OnionBoard.exe --selftest` (the
trimmed app loads Qt, Multimedia and the audio stack headless, no window
or device), licence files,
the add-ons in `modules\` copied into `dist\OnionBoard\modules\` (all but
`ai-voices`, which has its own release), `scripts\make_bunny.py` (renders the installer artwork
`installer\wizard*.bmp`, gitignored), then `ISCC` with `/DAppVersion` taken from
`soundboard/__init__.py`. Bump `__version__` there for a release.

**When to build.** Not to try a change: `scripts\run.bat` runs from source. Build for a
release, or to check something only the built app shows: `build.ps1`, `installer\`
(including `install-vbcable.ps1`), PyInstaller hooks, `scripts\prune_build.py`,
`scripts\vc_runtime.py`, `scripts\make_bunny.py` or bundled data (then
`build.ps1 -NoInstaller` and start it once). An existing `dist\` or install is out of
date after any change under `soundboard\`, `main.py`, `native\`, `assets\`,
`installer\` or `modules\` (the build copies the add-ons from there); docs, tests and
other `scripts\` never need one.

## 5. Install / reinstall / uninstall

The installer is per-user (no admin for the app itself) and installs to
`%LOCALAPPDATA%\Programs\OnionBoard`. Settings and sounds live in
`%APPDATA%\OnionBoard` and survive reinstalls and uninstalls.

Headless reinstall over an existing install:

```powershell
dist\OnionBoardSetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS
```

- `/CLOSEAPPLICATIONS` closes a running Onion Board first (it's also the
  installer's default).
- Silent installs don't launch the app afterwards (`skipifsilent`).
- `/OFFLINE=1` ticks the privacy page's *Offline mode* box: the installer runs
  `OnionBoard.exe --set-offline` first (`net_offline: true` in
  `%APPDATA%\OnionBoard\config.json`, other settings kept) and skips VB-Cable,
  FFmpeg, live voice and Tor unless `/TASKS=` or `/MERGETASKS=` names them (Tor
  never: the app doesn't start it while offline). It never switches Offline mode off.
- Sounds go straight into the mic by default, so the installer's cable box is
  unticked (a silent install keeps what the last install chose). Only when it's
  ticked (`/MERGETASKS=vbcable`) does the installer run `install-vbcable.ps1 -Silent`
  (bundled as `_internal\install-vbcable.ps1`). It exits straight away if a virtual cable is
  already present. If none is, VB-Cable is downloaded and Windows shows a **UAC prompt** — that part can't be headless, so tell the user
  to expect it.
- Restart handling: after setup the script waits for the CABLE devices. If Windows
  reports they need a restart it exits **3010** and writes
  `%APPDATA%\OnionBoard\cable-restart-pending`; the installer then offers
  "Restart now / later" (suppressed by `/NORESTART`), and the setup guide shows a
  Restart button instead of reinstalling until the PC has restarted. Check the
  state without installing: `powershell -File installer\install-vbcable.ps1 -Check`
  (0 working, 3010 restart needed, 2 not installed).

Headless uninstall. It first runs `OnionBoard.exe --direct-mic remove`, which puts
every mic back as it was; if the mic effect is on a mic, Windows shows a **UAC
prompt** even for a silent uninstall (none otherwise). A silent uninstall never
removes the cable; an interactive one asks, defaulting to Yes only if this installer
put the cable there:

```powershell
& "$env:LOCALAPPDATA\Programs\OnionBoard\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Check what's installed without launching anything:

```powershell
Get-Item "$env:LOCALAPPDATA\Programs\OnionBoard\OnionBoard.exe" | Select-Object LastWriteTime, Length
Get-Process OnionBoard -ErrorAction SilentlyContinue      # is it running?
```

## 6. Debugging a user's problem

- Log: `%APPDATA%\OnionBoard\onionboard.log` (rotating, 3 × 1 MB). Set
  `ONIONBOARD_DEBUG=1` for more detail. Module logs: `module-<id>.log` beside it.
- Config: `%APPDATA%\OnionBoard\config.json`, with backups `config.json.1`–`.3`.
- Decoded-audio cache: `%APPDATA%\OnionBoard\cache\` (safe to delete).
- Themed app icons: `%APPDATA%\OnionBoard\icons\` (the shortcuts point at one;
  deleting it leaves them blank until the next start writes it again).
- Straight into my mic: the admin step logs to
  `%ProgramData%\OnionBoard\directmic-admin.log` when Windows' prompt (or the
  uninstaller, or a `--direct-mic` command by hand) ran it, setting up the helper
  included; to `michelper.log` beside it when the mic helper ran it (a fix by itself, a
  click with no prompt), so that file only appears once the helper has done something
  (helper: `%ProgramFiles%\Onion Board Mic Helper\`, task `\Onion Board\Mic helper`,
  `schtasks /query /tn "\Onion Board\Mic helper"`; from source it's built by
  `scripts\build_michelper.py` after `build_directmic.py`); the ring shared with the effect is
  `%ProgramData%\OnionBoard\MicPlugin\ring2.bin`, and what the set-up changed is noted
  under `HKLM\SOFTWARE\OnionBoard\MicPlugin`. `directmic.status()` says where it
  stands on a mic (missing / other / wiped / outdated / ready).
- Never copy any of these into the repo. The log contains the user's paths, and
  `config.json` can hold a proxy password and the remote control key.

## 7. Commit and release

1. Section 3 passes. The pre-commit hook re-runs the secrets scan.
2. Commit, push, and open a pull request (main takes changes by PR only). Merge it
   with `sh scripts/merge_pr.sh N` (why: CLAUDE.md, *Commit times and merging*). CI
   (`.github/workflows/checks.yml`) runs on the PR and on main after a merge: the
   secrets scan over the full history, gitleaks, ruff and pytest. On a PR, pytest
   runs only the test files the change needs (`scripts/pick_tests.py`: the tests
   that import a changed module or name a changed file; all of them when
   `conftest.py`, `pyproject.toml`, the requirements, the workflow or a hub
   (`ui/mainwindow.py`, `engine.py`, `library.py`, `settings.py`) change; none for
   a change no test is about, like the changelog). main, after the merge, runs the
   whole suite, and so does running the workflow by hand on a branch. A newer push to
   the PR cancels its unfinished run. Every night the whole suite runs on main too,
   and its `flaky-trend` job fails when a test needed a rerun that didn't the night
   before (the run's summary lists the new ones and the ones no longer flaky).
3. `release.py` (next step) refuses to start unless the checkout is exactly
   `origin/main` (it fetches first) and main's full `checks` run passed on that
   commit (`gh run list --workflow checks.yml --branch main --commit <sha>`): a PR
   only runs the tests its change imports, so main's after-merge run is the first
   time the whole suite sees the change. Still going: wait. Failed or cancelled: fix
   main, or rerun it (`gh run rerun <id>`). `--skip-ci-check` releases anyway with a
   loud warning: only for an urgent fix when CI itself is broken.
   For a release: `.venv\Scripts\python scripts\release.py X.Y.Z` (bumps
   `__version__`, moves the `changelog.d/` entries into the CHANGELOG under the version, checks the
   translations, refreshes the README's release line; `--dry-run` checks only),
   build, then upload `dist\OnionBoardSetup.exe` to a GitHub Release
   with its SHA-256 (`certutil -hashfile dist\OnionBoardSetup.exe SHA256`).
   Keep the asset named exactly `OnionBoardSetup.exe` and don't mark the release
   as a pre-release: the README's download button links to
   `releases/latest/download/OnionBoardSetup.exe`, and installed copies update
   themselves from the latest release's `OnionBoardSetup.exe` (`soundboard/updates.py`
   only installs it when GitHub lists its SHA-256, and runs it with `/RELAUNCH=1`,
   see `installer/OnionBoard.iss`). Upload the same file a second time as
   `OnionBoardSetup-update.exe` (`gh release upload vX.Y.Z
   "dist\OnionBoardSetup.exe#OnionBoardSetup-update.exe"` doesn't rename it: copy it
   to that name first): *Update now* fetches that one when a release has it, so
   GitHub's download counts tell updates apart from new downloads. A release with a broken installer reaches
   everyone who clicks *Update now*: install the built one over your own copy
   before publishing.
   **An urgent fix** (a crash, sounds cutting out, a security problem): add a line
   `Urgent: <what it fixes, in a few plain words>` to the notes. Copies that check
   (every 6 hours) then show a banner across the window with that reason and
   *Update now*, and *Skip this version* isn't offered. The same line works in Onion
   Watch's release notes. Only the newest release is read, so if a normal release
   follows soon after, keep the line there too while the fix still matters.
   The notes start with a one-line headline, then a download line, because GitHub
   adds two *Source code* files that people mistake for the app:
   `**[⬇ Download OnionBoardSetup.exe](https://github.com/Onion-Alien/onion-board/releases/download/vX.Y.Z/OnionBoardSetup.exe)**: the one file you need (Windows 10 / 11). Already have Onion Board? The *Update* button at the top of the app offers this version. (The *Source code* files are for developers.)`
   Keep it second, not first: the app's *Update* dialog shows the start of the notes
   (`updates.summary` skips the ⬇ line, but 1.6.4 and older don't). Those show
   whole paragraphs up to 420 characters, so make the headline paragraph at least
   ~220 characters: then their dialog stops before the ⬇ line instead of telling
   someone who's already updating to go and download the file.
   Never commit build output. Run `python scripts/check_sensitive.py --history`
   once more before pushing the release.
