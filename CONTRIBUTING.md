# Contributing

Thanks for helping. Setup is in [docs/DEVELOPING.md](docs/DEVELOPING.md), code layout in [docs/CODE.md](docs/CODE.md)
and how the UI should look in [docs/DESIGN.md](docs/DESIGN.md); this file is the rules.

## Before you open a PR

Set up once (details: [DEVELOPING.md](docs/DEVELOPING.md) section 1):

```
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
git config core.hooksPath .githooks
```

The hooks run the secrets check before every commit and record commit times in UTC
(a local time zone in a public repo says where you live).

Then, before every PR:

```
powershell -ExecutionPolicy Bypass -File scripts\precommit.ps1
.venv\Scripts\python -m pytest tests\test_<module>.py
```

`precommit.ps1` runs ruff, the sensitive scan, the translation check and the
[docs/CODE.md](docs/CODE.md) module check in about 10 seconds; for the tests, the
files you touched are enough (`python scripts\pick_tests.py` lists them). CI runs
the same checks plus the tests your change needs on Windows, and the whole suite on
main after the merge. Not on Windows? The tests run on Linux and macOS too, skipping
the ones that need Windows: [DEVELOPING.md](docs/DEVELOPING.md#3-check-it-headless).

- **A fix comes with a test** that fails without it. The PR template's
  `Regression test:` line names it, or says `none: <why>`.
- **Text a user sees is translated in the same PR**, into every catalog in
  `assets/lang/`: CI fails otherwise ([docs/TRANSLATING.md](docs/TRANSLATING.md)).
- **Anything a user would notice** gets a changelog file (*Style* below).
- **UI changes** follow [docs/DESIGN.md](docs/DESIGN.md); put pictures of the
  change in the PR.

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
3. **No files from your own app data.** Don't commit `config.json`, `onionboard.log`
   or anything from `%APPDATA%\OnionBoard\` (`config.json` can hold a proxy password
   and the remote control key; the log holds your paths).
4. **No audio you don't have the rights to.** Tests generate their audio in code
   (`numpy`); keep it that way. No copyrighted sound effects, music or clips.
5. **No bundled third-party binaries.** Dependencies come from PyPI via
   `requirements.txt`; VB-Cable is downloaded when someone chooses to install it,
   because its licence forbids redistribution. Don't add `.exe`, `.dll` or driver files. Native code (the
   mic effect in `native/directmic/`) is committed as source and built by `build.ps1`.
6. **Assets must be ours.** Icons and artwork are drawn in code (`theme.py`,
   `icons.py`, `bunny.py`), except pictures made for this project in `assets/art/`
   (see its README); the app works without them. Other images, fonts or sounds need
   a licence that allows redistribution, noted in the PR.
7. **No new network calls without saying so.** Anything that talks to the
   internet goes in the table in [SECURITY.md](SECURITY.md#what-the-app-does-on-the-network)
   in the same PR. No telemetry beyond the opt-out anonymous usage count
   (`soundboard/core/usage.py`); anything new it sends goes in SECURITY.md's *The anonymous
   usage count* and the app's own table of it (`ui/countdialog.py`) in the same PR.
8. **Loopback stays locked.** Local sockets bind to `127.0.0.1` only and must
   check a secret with `secrets.compare_digest`: a per-launch one, or, for the
   opt-in remote control API, the key shown in Settings. Never log the secret or
   a URL containing it. The one server that listens beyond this PC, the opt-in one for
   remote add-ons such as Onion Pocket, answers local-network addresses only and needs
   its own key. Treat anything read from the mic effect's shared file as untrusted:
   any signed-in user can write it.

If you commit something sensitive by accident, **don't just delete it in a new
commit** — it's still in history. Rotate/revoke it first, then say so in the PR (or
privately, see [SECURITY.md](SECURITY.md)) and we'll rewrite the branch.

## Style

- Match the code around you: comment density, naming, how things are split.
- Line length 100, `ruff` config in `pyproject.toml`.
- Audio callbacks never block and never take the engine lock (see
  [docs/CODE.md](docs/CODE.md) → *Audio notes*).
- Disk, network, device and process calls never run on the Qt UI thread: run them on a
  worker (`soundboard/ui/kit/worker.py`) and only apply the answer on the UI thread. A
  worker's answer checks its owner (a tab, a dialog) still exists before touching it.
- For anything a user would notice, add a new file `changelog.d/<branch-name>.md` with
  your `- ` lines (see [changelog.d/README.md](changelog.d/README.md)). Don't edit
  `CHANGELOG.md`: releases fill it in, and separate files never merge-conflict.
