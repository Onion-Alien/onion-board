# Unreleased changes

One file per change, so pull requests never edit the same lines and conflict.

- Name it after your branch: `changelog.d/<branch-name>.md` (letters, digits, `-`, `_`, `.`).
- Inside: one or more bullet lines in the CHANGELOG's style (`- The thing now does…`),
  plain words for users. Wrap long lines at about 90 characters with two-space indents.
- Never edit `CHANGELOG.md` for a change: `scripts/release.py X.Y.Z` moves every file
  here into it under the new version (newest first) and deletes them.
