# CLAUDE.md

Guidance for AI coding agents (Claude Code, Codex, Copilot, etc.) working in this repo.
Humans: [CONTRIBUTING.md](CONTRIBUTING.md) has the same rules.

## This repo is public

Everything written here — code, comments, docs, tests, commit messages — is
published. Before writing or committing anything:

- **Never write personal or machine-specific data** into the repo: user names,
  real names, e-mails, `C:\Users\<name>\…` paths, host names, IPs (other than
  `127.0.0.1`), Tailscale or LAN details, names of the author's other projects or
  machines. Use `%APPDATA%`, `Path.home()`, `example.com`, placeholders.
- **Never copy content from outside the repo** (the author's other projects,
  parent-folder docs, memory files, shell history) into files here.
- **Never commit secrets** or anything from `%APPDATA%\OnionBoard\` (config, logs,
  browser profile, cache).
- **Never add audio files, binaries, or third-party assets.** Tests synthesize audio
  with numpy; icons/artwork are drawn in code.
- New network access must be added to the table in `SECURITY.md`. No telemetry.
- Loopback sockets bind `127.0.0.1` and verify a per-launch secret with
  `secrets.compare_digest`; never log the secret.

Run `python scripts/check_sensitive.py` before proposing a commit and fix anything it
reports. Don't add `# sensitive-scan: allow` to silence it without telling the user why.

## Working in the code

**[docs/DEVELOPING.md](docs/DEVELOPING.md) is the full loop**: setup → change →
headless checks → `build.ps1` → silent reinstall → commit. Read it before building
or installing anything. The short version:

- Checks: `.venv\Scripts\ruff check .` and `.venv\Scripts\python -m pytest`
  (tests use Qt's offscreen platform — no windows, devices or hotkeys).
- Build: `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\OnionBoard\`
  and `dist\OnionBoardSetup.exe`. Rebuild after changing anything the app ships.
- Reinstall headless: `dist\OnionBoardSetup.exe /VERYSILENT /SUPPRESSMSGBOXES
  /NORESTART /CLOSEAPPLICATIONS` (a UAC prompt appears only if VB-Cable is missing).
- A `.venv` breaks if moved; recreate it instead.
- Don't launch the GUI or anything that opens windows / grabs global hotkeys without
  asking first; the author may be mid-game.
- Edit files with UTF-8-safe tools. Windows PowerShell 5.1 `Get-Content`/`Set-Content`
  mangles UTF-8 (this codebase uses symbols like ⚙ ⏺ 🐰 in strings).
- Audio callbacks never block or take the engine lock (README → *Audio notes*).
- Code layout is in the README table; keep it current when adding modules.
