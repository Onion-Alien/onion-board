# Developing, building and reinstalling

The loop for changing Soundboard, from edit to a reinstalled app. Written so an
AI agent can follow it headless; humans can too. Commands are run from the repo
root in PowerShell unless noted.

## 1. One-time setup

```powershell
py -3.13 -m venv .venv                 # Python 3.11+ works
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
git config core.hooksPath .githooks    # secrets check on every commit
```

Build tools, only needed for step 4:

```powershell
winget install JRSoftware.InnoSetup    # for SoundboardSetup.exe
```

A `.venv` can't be moved or copied to another folder (its launchers hard-code the
path). If the repo moves, delete `.venv` and recreate it. The same goes for a
module's own `.venv` (e.g. `modules\live-voice\.venv`: recreate it with that
module's `install.bat` or `pip install -r requirements.txt`).

## 2. Change the code

- Layout: README → *Code layout*. Rules: [CONTRIBUTING.md](../CONTRIBUTING.md).
- Real-time audio callbacks never block and never take the engine lock.
- Anything user-visible goes in `CHANGELOG.md` under *Unreleased*.

## 3. Check it (headless)

```powershell
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest -q
.venv\Scripts\python scripts\check_sensitive.py
```

The tests are fully headless: `tests/conftest.py` forces Qt's `offscreen`
platform and a separate single-instance name, and never touches the real
`%APPDATA%\Soundboard`. No window appears, no audio device opens and no global
hotkey is registered. They're safe to run while someone is using the PC.

**Launching the real app is not headless.** It opens a window, grabs global
hotkeys and opens audio devices. Agents: ask the user before running
`run.bat`, `python -m soundboard`, `Soundboard.exe` or the installer.

## 4. Build the app and the installer

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

This produces:

| output | what |
|---|---|
| `dist\Soundboard\Soundboard.exe` | the one-folder app (PyInstaller), with `LICENSE.txt` and `THIRD-PARTY-NOTICES.txt` beside it |
| `dist\SoundboardSetup.exe` | the installer (Inno Setup). Skipped with a warning if Inno Setup isn't installed |

`-AppDir <dir>` and `-InstallerDir <dir>` also copy those results elsewhere,
e.g. `build.ps1 -AppDir ..\App -InstallerDir ..\Installer`.

Build steps, in order: PyInstaller (bundles `install-vbcable.ps1` and the icon
as data), licence files, `make_bunny.py` (renders the installer artwork
`installer\wizard*.bmp`, gitignored), then `ISCC` with `/DAppVersion` taken from
`soundboard/__init__.py`. Bump `__version__` there for a release.

Rebuild after changing anything under `soundboard\`, `main.py`,
`install-vbcable.ps1`, `soundboard.ico`, `installer\` or `modules\` (the installer
copies the add-ons from there when their boxes are ticked). Changes to docs, tests
or `scripts\` don't need a rebuild.

## 5. Install / reinstall / uninstall

The installer is per-user (no admin for the app itself) and installs to
`%LOCALAPPDATA%\Programs\Soundboard`. Settings and sounds live in
`%APPDATA%\Soundboard` and survive reinstalls and uninstalls.

Headless reinstall over an existing install:

```powershell
dist\SoundboardSetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS
```

- `/CLOSEAPPLICATIONS` closes a running Soundboard first (it's also the
  installer's default).
- Silent installs don't launch the app afterwards (`skipifsilent`).
- The installer runs `install-vbcable.ps1 -Silent`. It exits straight away if a
  virtual cable is already present. If none is, VB-Cable is downloaded and
  Windows shows a **UAC prompt** — that part can't be headless, so tell the user
  to expect it.
- Restart handling: after setup the script waits for the CABLE devices. If Windows
  reports they need a restart it exits **3010** and writes
  `%APPDATA%\Soundboard\cable-restart-pending`; the installer then offers
  "Restart now / later" (suppressed by `/NORESTART`), and the setup guide shows a
  Restart button instead of reinstalling until the PC has restarted. Check the
  state without installing: `powershell -File install-vbcable.ps1 -Check`
  (0 working, 3010 restart needed, 2 not installed).

Headless uninstall:

```powershell
& "$env:LOCALAPPDATA\Programs\Soundboard\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Check what's installed without launching anything:

```powershell
Get-Item "$env:LOCALAPPDATA\Programs\Soundboard\Soundboard.exe" | Select-Object LastWriteTime, Length
Get-Process Soundboard -ErrorAction SilentlyContinue      # is it running?
```

## 6. Debugging a user's problem

- Log: `%APPDATA%\Soundboard\soundboard.log` (rotating, 3 × 1 MB). Set
  `SOUNDBOARD_DEBUG=1` for more detail. Module logs: `module-<id>.log` beside it.
- Config: `%APPDATA%\Soundboard\config.json`, with backups `config.json.1`–`.3`.
- Decoded-audio cache: `%APPDATA%\Soundboard\cache\` (safe to delete).
- Never copy any of these into the repo. The log contains the user's paths, and
  `browser\` holds their logins.

## 7. Commit and release

1. Section 3 passes. The pre-commit hook re-runs the secrets scan.
2. Commit, then push. CI (`.github/workflows/checks.yml`) runs the secrets scan
   over the full history, gitleaks, ruff and pytest.
3. For a release: bump `__version__`, move *Unreleased* in the CHANGELOG under
   the version, build, then upload `dist\SoundboardSetup.exe` to a GitHub Release
   with its SHA-256 (`certutil -hashfile dist\SoundboardSetup.exe SHA256`).
   Keep the asset named exactly `SoundboardSetup.exe` and don't mark the release
   as a pre-release: the README's download button links to
   `releases/latest/download/SoundboardSetup.exe`.
   Never commit build output. Walk through
   [PUBLIC-RELEASE-CHECKLIST.md](PUBLIC-RELEASE-CHECKLIST.md) once more.
