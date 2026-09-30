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

Build tools, only needed for step 4:

```powershell
winget install JRSoftware.InnoSetup    # for OnionBoardSetup.exe
```

A `.venv` can't be moved or copied to another folder (its launchers hard-code the
path). If the repo moves, delete `.venv` and recreate it. The same goes for a
module's own `.venv` (e.g. `modules\live-voice\.venv`: recreate it with that
module's `install.bat` or `pip install -r requirements.txt`).

## 2. Change the code

- Layout: README → *Code layout*. Rules: [CONTRIBUTING.md](../CONTRIBUTING.md).
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
  app ships (it has no pip): the standard library, numpy, scipy and PySide6's
  QtCore / QtGui / QtWidgets. Removing one of those from the build breaks it.

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
the speakers or headphones, and the web engine (the Radio tab's globe) runs with
`--mute-audio` (set `ONIONBOARD_TEST_REAL_AUDIO=1` to
opt out of both).
They're safe to run while someone is using the PC.

To iterate faster, run just the file you touched, e.g.
`.venv\Scripts\python -m pytest -q tests\test_engine.py`, and the full suite
before committing. You don't need to rebuild to see a change: `scripts\run.bat` runs
from source.

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

The real-world checks play test signals into the virtual cable, so they aren't
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

Build steps, in order: PyInstaller (bundles `installer\install-vbcable.ps1` and
`assets\onionboard.ico` as data, both at the root of `_internal\`),
`scripts\prune_build.py` (removes the parts of Qt the app never loads — QML, 3D,
charts, Chromium's dev tools, translations — by walking the DLL import tables; the
build fails if a kept file would lose an import), `OnionBoard.exe --selftest` (the
trimmed app loads Qt, WebEngine, Multimedia and the audio stack headless, no window
or device), licence files,
`scripts\make_bunny.py` (renders the installer artwork
`installer\wizard*.bmp`, gitignored), then `ISCC` with `/DAppVersion` taken from
`soundboard/__init__.py`. Bump `__version__` there for a release.

Rebuild after changing anything under `soundboard\`, `main.py`,
`assets\`, `installer\` (including `install-vbcable.ps1`) or `modules\` (the installer
copies the add-ons from there when their boxes are ticked). Changes to docs, tests
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
- The installer runs `install-vbcable.ps1 -Silent` (bundled as
  `_internal\install-vbcable.ps1`). It exits straight away if a virtual cable is
  already present. If none is, VB-Cable is downloaded and Windows shows a **UAC prompt** — that part can't be headless, so tell the user
  to expect it.
- Restart handling: after setup the script waits for the CABLE devices. If Windows
  reports they need a restart it exits **3010** and writes
  `%APPDATA%\OnionBoard\cable-restart-pending`; the installer then offers
  "Restart now / later" (suppressed by `/NORESTART`), and the setup guide shows a
  Restart button instead of reinstalling until the PC has restarted. Check the
  state without installing: `powershell -File installer\install-vbcable.ps1 -Check`
  (0 working, 3010 restart needed, 2 not installed).

Headless uninstall (a silent uninstall never removes the cable; an interactive one
asks, defaulting to Yes only if this installer put the cable there):

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
- Never copy any of these into the repo. The log contains the user's paths, and
  `browser\` holds their logins.

## 7. Commit and release

1. Section 3 passes. The pre-commit hook re-runs the secrets scan.
2. Commit, then push. CI (`.github/workflows/checks.yml`) runs the secrets scan
   over the full history, gitleaks, ruff and pytest.
3. For a release: bump `__version__`, move *Unreleased* in the CHANGELOG under
   the version, build, then upload `dist\OnionBoardSetup.exe` to a GitHub Release
   with its SHA-256 (`certutil -hashfile dist\OnionBoardSetup.exe SHA256`).
   Keep the asset named exactly `OnionBoardSetup.exe` and don't mark the release
   as a pre-release: the README's download button links to
   `releases/latest/download/OnionBoardSetup.exe`, and installed copies update
   themselves from the latest release's `OnionBoardSetup.exe` (`soundboard/updates.py`
   only installs it when GitHub lists its SHA-256, and runs it with `/RELAUNCH=1`,
   see `installer/OnionBoard.iss`). A release with a broken installer reaches
   everyone who clicks *Update now*: install the built one over your own copy
   before publishing.
   Never commit build output. Run `python scripts/check_sensitive.py --history`
   once more before pushing the release.
