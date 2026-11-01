# CLAUDE.md

Guidance for AI coding agents (Claude Code, Codex, Copilot, etc.) working in this repo.
Humans: [CONTRIBUTING.md](CONTRIBUTING.md).

## This repo is public

Everything written here (code, comments, docs, tests, commit messages, PR text) is
published. The rules for everyone (no secrets, no personal data, no app-data files, no
unlicensed audio or binaries, new network calls in `SECURITY.md`, loopback locked) are
[CONTRIBUTING.md *Rules that aren't negotiable*](CONTRIBUTING.md#rules-that-arent-negotiable).
On top of those, for agents:

- **The maintainer's working notes stay out of the repo.** Plans, roadmaps, to-do
  lists, audits, checklists, handoffs, test reports and agent rulebooks are kept
  locally, outside git. Never add one to the repo (not in `docs/`, not anywhere), and
  never link to one or cite its item numbers ("U12", "see the audit") in code,
  comments, tests, commits or PRs. What's committed is what a user or an outside
  contributor needs: the README, the website, CONTRIBUTING, SECURITY, the changelog
  and the reference docs in `docs/` (DEVELOPING, CODE, DESIGN, FEATURES, ...).
  `.gitignore` blocks the usual names; a new kind of note goes there too.
- **Never copy content from outside the repo** (the author's other projects,
  parent-folder docs, memory files, shell history) into files here, and never name the
  author's machines, other projects, Tailscale or LAN details.
- **Never put Claude session links** (`claude.ai/code/session_…`) or
  `Claude-Session:` trailers in commits, PRs or comments. Strip any your tooling
  adds; `Co-Authored-By` is fine.
- Run `python scripts/check_sensitive.py` (part of `scripts\precommit.ps1`) and fix what
  it reports. Don't add `# sensitive-scan: allow` to silence it without telling the user why.

## Working in a fork or clone

A copy of this repo still sends its usage counts to Onion Board's GoatCounter, reads Onion
Board's sound store, takes Onion Board's updates and carries its name and logo. If the
user's repo isn't `Onion-Alien/onion-board`, go through
[docs/FORKING.md](docs/FORKING.md) before building or releasing anything, and tell the
user which of those still point here.

## Text the app shows: every language, in the same change

Onion Board ships in every language in `assets/lang/`. Any change that adds or edits text
a user can see (labels, buttons, tooltips, dialogs, toasts, errors) does all of this
**before committing**, not "later":

1. Wrap it: `_("…")` / `ngettext("…", "…", n)` from `soundboard.i18n`. Whole sentences with
   `{placeholders}`: never an f-string, `+`, or an English word passed into a
   placeholder ("{what}" = "sounds" can't be translated).
2. `python scripts/checks/i18n_extract.py --update`: adds the new texts (empty) to every
   catalog and drops the unused ones.
3. Translate every text you added or changed into **every** catalog: plain, short,
   friendly words for gamers, the same words the catalog already uses (and Onion Watch
   uses, for shared things), every `{placeholder}`, `<b>…</b>`, `&amp;` and line break
   kept, and the language's number of plural forms (`i18n.FORMS`). Lots of text: one
   subagent per language.
4. `scripts\precommit.ps1` checks that no text is missing.

What not to wrap, plurals and per-language notes: [docs/TRANSLATING.md](docs/TRANSLATING.md).

## Any UI work

[docs/DESIGN.md](docs/DESIGN.md) is the design system: start with its *Standard kit*
(the only text sizes, button kinds and pop-ups), follow section 0 for controls and
section 13 (*UI workflow*) for the workflow, and go through its checklist (section 10)
before showing pictures.
**The app has 33 themes** (`theme.THEMES`), not two or three: any colour, icon or style
sheet change has to work and be checked in all of them (DESIGN.md section 6), with Dark
and Light as the reference look.

## Working in the code

- Setup, tests, build, install and release commands: [docs/DEVELOPING.md](docs/DEVELOPING.md).
  You don't need a build to try a change; build only for what section 4 says needs one.
- **Ask first** before launching the GUI or anything that opens windows / grabs global
  hotkeys (the author may be mid-game), and before *Straight into my mic*'s set-up,
  `OnionBoard.exe --direct-mic …` or uninstalling with the mic effect on: those ask for
  admin, change the mic's Windows audio settings and restart Windows' audio.
- Edit files with UTF-8-safe tools. Windows PowerShell 5.1 `Get-Content`/`Set-Content`
  mangles UTF-8 (this codebase uses symbols like ⚙ ⏺ 🐰 in strings).
- Code layout is the table in [docs/CODE.md](docs/CODE.md); keep it current when adding modules.
- A change's changelog lines go in a new `changelog.d/<branch-name>.md`, never in
  `CHANGELOG.md` ([changelog.d/README.md](changelog.d/README.md)).

## Commit times and merging

Every commit's author and committer time must be `+0000`: a local time zone in a public
repo says where the author lives. The enforcement:

- `git config core.hooksPath .githooks` (required) turns on the hooks: `post-commit` and
  `post-merge` re-stamp new commits in UTC, and `pre-push` refuses anything that isn't.
- CI's *Commit times in UTC* step fails a PR (and main) that has any.
- **Merge only with `sh scripts/merge_pr.sh N [--delete-branch]`**: it checks CI is
  green, makes the merge commit here in UTC and pushes it to main. Never GitHub's merge
  (the `gh` merge command, the API's merge call, the Merge button) or *Update branch*:
  GitHub writes those commits in your local time zone, and no hook can touch them.
- Bring main into a branch with a local `git merge origin/main` (the hook stamps it).
- A branch whose commits aren't UTC: `sh scripts/checks/utc_fix.sh`, then
  `git push --force-with-lease`.
- The same goes for anything else that records where you are: never write your time
  zone, locale, city or machine names into commits, PR text or files.
- Never rewrite history already pushed to `main` (no filter-repo, rebase or force-push):
  commits get new IDs, so every fork or branch that merges `main` sees them all as new
  and conflicts. To clean up old commits, add a new commit instead.
