# AGENTS.md

For AI coding agents that read `AGENTS.md` (Codex and others). The full guidance is
[CLAUDE.md](CLAUDE.md): read it first, it applies to every agent, not only Claude.
Then [docs/AGENT-RULES.md](docs/AGENT-RULES.md) for which other docs your task needs.

The rules agents break most, in short:

- **Merge locally, never on GitHub.** Merge a green PR with
  `sh scripts/merge_pr.sh N --delete-branch`. Never `gh pr merge`, the API's merge
  call, GitHub's Merge button or *Update branch*: GitHub writes those commits in the
  local time zone, and every commit here must be in UTC (`+0000`). Bring `main` into a
  branch with a local `git merge origin/main`.
- `git config core.hooksPath .githooks` in every new checkout or worktree (the UTC hooks).
- Start from the latest `origin/main` on a new branch or worktree; never edit someone
  else's dirty checkout. Check `gh pr list --state open` for the same work first.
- No personal or machine data, secrets or session links in files, commits or PR text:
  this repo is public.
- Never edit `CHANGELOG.md` for a change: add `changelog.d/<branch-name>.md`.
- Text the app shows goes through `_()` and into every language in `assets/lang/`.
- Check with `scripts\precommit.ps1` before committing.
