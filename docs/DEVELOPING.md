# Developing, building and reinstalling

The loop for changing Onion Board, from edit to a reinstalled app. Written so an
AI agent can follow it headless; humans can too. Commands are run from the repo
root in PowerShell unless noted.

## 1. One-time setup

```powershell
py -3.13 -m venv .venv                 # Python 3.12+ works
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
git config core.hooksPath .githooks    # secrets check on every commit
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

- Layout: [CODE.md](CODE.md) → *Code layout*. Rules: [CONTRIBUTING.md](../CONTRIBUTING.md).
- Real-time audio callbacks never block and never take the engine lock.
- Anything user-visible goes in `CHANGELOG.md` under *Unreleased*.
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
`scripts\build_directmic.py --testhost` has built it (CI doesn't build it, so run them
locally after touching `native\directmic\` or the ring in `directmic.py`).
`scripts\build_directmic.py --fuzz` also builds `fuzzhost.exe`, which throws hostile and
half-written ring files at the effect (built with sanitizer traps);
`scripts\fuzz_directmic.py [seconds] [workers]` runs it for longer than the tests do.

To iterate faster, run just the file you touched, e.g.
`.venv\Scripts\python -m pytest -q tests\test_engine.py`, and the full suite
before committing. The full suite runs on 4 workers (pytest-xdist, about a minute);
one or two files run in a single process. `-n 2` caps the workers (say, while a
game is running) and `-n 0` turns them off. You don't need to rebuild to see a change: `scripts\run.bat` runs
from source.

Keeping it fast: Windows takes ~2 s to refuse a connection to a closed port, even
on 127.0.0.1, and `localhost` tries `::1` first. A test that needs "nothing is
listening" takes its port from `conftest.closed_port()` (refused at once), and a
test server on 127.0.0.1 only marks its port with `conftest.ipv4_only()`.
`--durations=20` shows what's slow.

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

**Launching the real app is not headless.** It opens a window, grabs global
hotkeys and opens audio devices. Agents: ask the user before running
`scripts\run.bat`, `python -m soundboard`, `OnionBoard.exe` or the installer.

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

Build steps, in order: `scripts\version_info.py` (the .exe's version resource),
`scripts\build_directmic.py` (the mic effect; the build stops
if g++ is missing), PyInstaller (bundles `installer\install-vbcable.ps1` and
`assets\onionboard.ico` as data, both at the root of `_internal\`, and `obmic.dll` in
`_internal\directmic\`),
`scripts\prune_build.py` (removes the parts of Qt the app never loads — QML, 3D,
charts, the web engine, unused image formats, translations — by walking the DLL import tables; the
build fails if a kept file would lose an import), `OnionBoard.exe --selftest` (the
trimmed app loads Qt, Multimedia and the audio stack headless, no window
or device), licence files,
the add-ons in `modules\` copied into `dist\OnionBoard\modules\` (all but
`ai-voices`, which has its own release), `scripts\make_bunny.py` (renders the installer artwork
`installer\wizard*.bmp`, gitignored), then `ISCC` with `/DAppVersion` taken from
`soundboard/__init__.py`. Bump `__version__` there for a release.

Rebuild after changing anything under `soundboard\`, `main.py`, `native\`,
`assets\`, `installer\` (including `install-vbcable.ps1`) or `modules\` (the build
copies the add-ons from there). Changes to docs, tests
or `scripts\` don't need a rebuild, except `scripts\make_bunny.py` (the installer art).

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
  `%ProgramData%\OnionBoard\directmic-admin.log`; the ring shared with the effect is
  `%ProgramData%\OnionBoard\MicPlugin\ring2.bin`, and what the set-up changed is noted
  under `HKLM\SOFTWARE\OnionBoard\MicPlugin`. `directmic.status()` says where it
  stands on a mic (missing / other / wiped / outdated / ready).
- Never copy any of these into the repo. The log contains the user's paths, and
  `config.json` can hold a proxy password and the remote control key.

## 7. Commit and release

1. Section 3 passes. The pre-commit hook re-runs the secrets scan.
2. Commit, push, and open a pull request (main takes changes by PR only). CI
   (`.github/workflows/checks.yml`) runs on the PR and on main after a merge: the
   secrets scan over the full history, gitleaks, ruff and pytest. A newer push to
   the PR cancels its unfinished run.
3. For a release: bump `__version__`, move *Unreleased* in the CHANGELOG under
   the version, build, then upload `dist\OnionBoardSetup.exe` to a GitHub Release
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
