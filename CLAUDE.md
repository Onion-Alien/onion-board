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
  radio web cache, decoded-audio cache).
- **Never put Claude session links** (`claude.ai/code/session_…`) or
  `Claude-Session:` trailers in commits, PRs or comments. Strip any your tooling
  adds; `Co-Authored-By` is fine.
- **Never add audio files, binaries, or third-party assets.** Tests synthesize audio
  with numpy; icons are drawn in code. The one exception is artwork made for this
  project (e.g. generated pictures) in `assets/art/` — see its README.
- New network access must be added to the table in `SECURITY.md`. No telemetry beyond the opt-out anonymous usage count (`soundboard/usage.py`).
- Loopback sockets bind `127.0.0.1` and verify a secret with `secrets.compare_digest`
  (a per-launch one; the opt-in remote control API checks the key shown in Settings);
  never log the secret. The opt-in server for remote add-ons (Onion Pocket) is the one
  exception: local-network addresses only, its own key.

Run `python scripts/check_sensitive.py` before proposing a commit and fix anything it
reports. Don't add `# sensitive-scan: allow` to silence it without telling the user why.

## Text the app shows: every language, in the same change

Onion Board ships in every language in `assets/lang/` (the same set as Onion Watch). So any change
that adds or edits text a user can see (labels, buttons, tooltips, dialogs, toasts,
errors) does all of this **before committing**, not "later":

1. Wrap it: `_("…")` / `ngettext("…", "…", n)` from `soundboard.i18n`. Whole sentences with
   `{placeholders}`: never an f-string, `+`, or an English word passed into a
   placeholder ("{what}" = "sounds" can't be translated).
2. `python scripts/i18n_extract.py --update`: adds the new texts (empty) to every
   catalog and drops the unused ones.
3. Translate every text you added or changed into **every** catalog: plain, short,
   friendly words for gamers, the same words the catalog already uses (and Onion Watch
   uses, for shared things), every `{placeholder}`, `<b>…</b>`, `&amp;` and line break
   kept, and the language's number of plural forms (`i18n.FORMS`). Lots of text: one
   subagent per language.
4. `ruff`, the i18n tests, and check that `i18n_extract.py` lists none of your texts as
   missing.

Never wrap log messages, settings keys, file names, the control API's JSON or the changelog. A new language goes into
both apps at once. Details: [docs/TRANSLATING.md](docs/TRANSLATING.md).

## Any UI work: read docs/DESIGN.md first

**[docs/DESIGN.md](docs/DESIGN.md) is the design system**: tokens, layout, buttons,
colour, text, behaviour, a "never" list and a checklist. Build every new screen, card,
dialog and button from it. The rules people trip over most:

- **Narrow by default**: controls as wide as their words, then `addStretch(1)`;
  dialogs ≤ ~620 px; tiles in fixed-size grids that scroll down.
- **Buttons on the left, the main one first** (`[Send] [Cancel]`), one filled
  `#primary` button per card or dialog at most.
- **Icons and pop-ups over long buttons**: a button is one to three words; anything
  a picture says is an icon with a tooltip; how-to text goes behind an ⓘ pop-up.
- **Cards look designed, not like a form**: heading icon, status pill, choice tiles,
  pictures, an inner area; never a heading over stacked plain rows.
- Theme tokens only, never a hex colour; ticks and on-states stay the accent colour.
- Sentence case, no long dashes, `23%`, every string through `_()`.
- Before sending pictures of a change, look at every state yourself for empty space,
  cut-off words and invisible controls.

## Working in the code

**[docs/DEVELOPING.md](docs/DEVELOPING.md) is the full loop**: setup → change →
headless checks → `build.ps1` → silent reinstall → commit. Read it before building
or installing anything. The short version:

- Checks: `.venv\Scripts\ruff check .` and `.venv\Scripts\python -m pytest`
  (tests use Qt's offscreen platform — no windows, devices or hotkeys).
- Build: `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\OnionBoard\`
  and `dist\OnionBoardSetup.exe` (needs MinGW-w64's g++ for the mic effect in
  `native\directmic\`). Rebuild after changing anything the app ships.
- Reinstall headless: `dist\OnionBoardSetup.exe /VERYSILENT /SUPPRESSMSGBOXES
  /NORESTART /CLOSEAPPLICATIONS` (a UAC prompt appears only if VB-Cable is missing
  and its box is ticked).
- *Straight into my mic*'s set-up, `OnionBoard.exe --direct-mic …` and uninstalling
  (when the mic effect is on a mic) ask for admin, change the mic's Windows audio settings and restart Windows' audio:
  never run them without asking.
- A `.venv` breaks if moved; recreate it instead.
- Don't launch the GUI or anything that opens windows / grabs global hotkeys without
  asking first; the author may be mid-game.
- Edit files with UTF-8-safe tools. Windows PowerShell 5.1 `Get-Content`/`Set-Content`
  mangles UTF-8 (this codebase uses symbols like ⚙ ⏺ 🐰 in strings).
- Audio callbacks never block or take the engine lock ([docs/CODE.md](docs/CODE.md) → *Audio notes*).
- Code layout is the table in [docs/CODE.md](docs/CODE.md); keep it current when adding modules.
- **Commit times: UTC only.** Every commit's author and committer time must be
  `+0000`: a local time zone in a public repo says where the author lives. The
  enforcement:
  - `git config core.hooksPath .githooks` (required) turns on the hooks:
    `post-commit` and `post-merge` re-stamp new commits in UTC, and `pre-push` refuses
    anything that isn't.
  - CI's *Commit times in UTC* step fails a PR (and main) that has any.
  - **Never merge a PR with `gh pr merge`, GitHub's Merge button or GitHub's
    *Update branch*.** GitHub writes those commits in your local time zone, and no
    hook can touch them. Merge with `sh scripts/merge_pr.sh N [--delete-branch]`: it
    checks CI is green, makes the merge commit here in UTC and pushes it to main.
  - Bring main into a branch with a local `git merge origin/main` (the hook stamps
    it).
  - A branch whose commits aren't UTC: `sh scripts/utc_fix.sh`, then
    `git push --force-with-lease`.
  - The same goes for anything else that records where you are: never write your time
    zone, locale, city or machine names into commits, PR text or files.
- Never rewrite history already pushed to `main` (no filter-repo, rebase or force-push):
  commits get new IDs, so every fork or branch that merges `main` sees them all as new
  and conflicts. To clean up old commits, add a new commit instead.
