# AGENTS.md

For AI coding agents that read `AGENTS.md` (Codex and others). The guidance is
[CLAUDE.md](CLAUDE.md): read it first, it applies to every agent, not only Claude. Then
[docs/AGENT-RULES.md](docs/AGENT-RULES.md) for which other docs your task needs.

The ones agents break most, each kept in one place:

- Start from the latest `origin/main`, check open PRs: [CLAUDE.md *Before you change anything*](CLAUDE.md#before-you-change-anything-sync-first-check-open-prs).
- Merge only with `sh scripts/merge_pr.sh N`, never on GitHub; commits in UTC: [CLAUDE.md *Commit times and merging*](CLAUDE.md#commit-times-and-merging).
- Public repo, no personal data: [CLAUDE.md *This repo is public*](CLAUDE.md#this-repo-is-public).
- Text in every language: [CLAUDE.md *Text the app shows*](CLAUDE.md#text-the-app-shows-every-language-in-the-same-change).
- UI: [docs/DESIGN.md](docs/DESIGN.md); the only UI to-do list is [docs/UI-AUDIT.md](docs/UI-AUDIT.md).
- Changelog: [changelog.d/README.md](changelog.d/README.md), never `CHANGELOG.md`.
- Before committing: [AGENT-RULES *Before every commit*](docs/AGENT-RULES.md#before-every-commit).
