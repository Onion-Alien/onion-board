# Contributing

Thanks for helping. Setup is in [docs/DEVELOPING.md](docs/DEVELOPING.md) and code layout in [docs/CODE.md](docs/CODE.md);
this file is the rules.

## Before you open a PR

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest
python scripts\check_sensitive.py
```

All four must pass. CI runs the same checks.

Turn on the hooks once per clone: the secrets check runs before every commit, and
commit times are recorded in UTC:

```
git config core.hooksPath .githooks
```

## Rules that aren't negotiable

This is a public repo. Everything you commit — including in history, commit
messages, and your git author e-mail — is public forever, even if you delete it
in a later commit.

1. **No secrets.** No API keys, tokens, passwords, cookies, signing
   certificates, `.env` files. The app doesn't need any; if a feature seems to,
   open an issue first.
2. **No personal data.** No real names, e-mails, user-profile paths
   (`C:\Users\<you>\…`), host names, IPs, Discord IDs, or screenshots showing any of
   those. In code, docs and tests use `%APPDATA%`, `Path.home()`, `example.com`,
   and made-up names.
3. **No files from your own app data.** Don't commit `config.json`, `onionboard.log`,
   anything from `%APPDATA%\OnionBoard\` (`config.json` can hold a proxy password and the remote control key; the log holds your paths).
4. **No audio you don't have the rights to.** Tests generate their audio in code
   (`numpy`); keep it that way. No copyrighted sound effects, music or clips.
5. **No bundled third-party binaries.** Dependencies come from PyPI via
   `requirements.txt`; VB-Cable is downloaded when someone chooses to install it because its licence
   forbids redistribution. Don't add `.exe`, `.dll` or driver files.
6. **Assets must be ours.** Icons and artwork are drawn in code (`theme.py`,
   `icons.py`, `bunny.py`), except pictures made for this project in `assets/art/`
   (see its README); the app works without them. Other images, fonts or sounds need
   a licence that allows redistribution, noted in the PR.
7. **No new network calls without saying so.** Anything that talks to the
   internet goes in the table in [SECURITY.md](SECURITY.md#what-the-app-does-on-the-network)
   in the same PR. No telemetry beyond the opt-out anonymous usage count (`soundboard/usage.py`).
8. **Loopback stays locked.** Local sockets bind to `127.0.0.1` only and must
   check a secret with `secrets.compare_digest`: a per-launch one, or, for the
   opt-in remote control API, the key shown in Settings. Never log the secret or
   a URL containing it.

If you commit something sensitive by accident, **don't just delete it in a new
commit** — it's still in history. Rotate/revoke it first, then say so in the PR (or
privately, see [SECURITY.md](SECURITY.md)) and we'll rewrite the branch.

## Style

- Match the code around you: comment density, naming, how things are split.
- Line length 100, `ruff` config in `pyproject.toml`.
- Audio callbacks never block and never take the engine lock (see [docs/CODE.md](docs/CODE.md) → *Audio notes*).
- Add a CHANGELOG entry under *Unreleased* for anything a user would notice.
