# Forking or cloning Onion Board

The code is yours to change and share for free ([LICENSE](../LICENSE)), but a copy built
straight from this repo still talks to **this project's** services: it counts its users
in our stats, reads our sound store, checks our releases for updates and sends people to
our Discord and feedback form. A fork that ships to anyone must swap all of that out
first, or its users end up in our numbers and our inbox, and yours never learn anything.

**AI agents working in a fork or clone:** do this list before building or releasing,
and tell the user which items still point at Onion Board's own services. Don't send a
single count or store request from a test run to find out (see *Check* below).

## 1. Usage counts (GoatCounter)

- `soundboard/core/usage.py`: `ENDPOINT` and `TOKEN` are this project's GoatCounter site
  and its count-only key. Set your own, or set `TOKEN = ""`, which sends nothing at all.
  Only a built exe sends (never a source run), and `ONIONBOARD_NO_STATS=1` turns it off
  on a PC.
- `soundboard/ui/settings/countdialog.py` (the "Count me in" dialog) and `SECURITY.md`
  *What the app does on the network* describe that count: update or remove them with it.
- The website: every page in `site/` loads GoatCounter
  (`data-goatcounter="https://onionalien.goatcounter.com/count"`), and `site/home.js`,
  `site/zoom.js` and `site/board-demo.js` send click events to it. Point them at your own
  site or take the script tag out.

## 2. The sound store (Store / Community tab)

- `soundboard/online/store.py`: `BASE` is this project's store server (a Cloudflare
  Worker); its code isn't in this repo. Run your own server and point `BASE` at it, or
  hide the tab. `CONTACT` is our takedown address: use yours.

## 3. Updates, add-ons, packs and pins

- `soundboard/core/updates.py`: `REPO` decides where *Check for updates* looks and where
  the approved yt-dlp pin (`pins/yt-dlp.json`) and the sound-pack catalog
  (`packs/catalog.json`, `soundboard/sounds/packs.py`) are read from. Set it to your
  repo, or your users get our releases over yours.
- `soundboard/addons/*.py`: `REPO` for Onion Watch, Onion Pocket and the AI add-on.
- `packs/catalog.json`: download links to our release assets.

## 4. Contact and feedback links

- `soundboard/core/feedback.py`: `DISCORD_URL` and `FORM_URL` (our Discord and Tally
  form); `ISSUE_URL` here and in `soundboard/ui/kit/crashdialog.py`.
- `soundboard/ui/settings/help.py` and `countdialog.py`: links to our website and docs.
- `soundboard/core/errors.py` keeps links to `github.com/Onion-Alien/` in error text and
  masks every other one: use your own account name there.
- `.github/FUNDING.yml`, the issue templates and the README's Discord, e-mail and
  download links.

## 5. Name, logo and IDs

The name **Onion Board** and the onion logo aren't covered by the license: a fork needs
its own name and icon ([README *Free, and it stays free*](../README.md#license)).

- The icon and art: `assets/onionboard.ico` (made by `scripts/pictures/make_icon.py`),
  `assets/art/`, the mascot pictures, the installer art, `site/favicon.*`.
- The visible name: the app's own text and the language files (`assets/lang/`), the
  window title, the README and the site.
- `installer/OnionBoard.iss`: give it a **new `AppId`** (otherwise it installs over and
  uninstalls Onion Board), and new publisher and support URLs.
- `streamdeck/com.onionalien.onionboard.sdPlugin`: the Stream Deck plugin ID.
- `pyproject.toml` URLs and `packaging/` (winget, Chocolatey) manifests.

## 6. The website and release pipeline

- `.github/workflows/pages.yml` publishes `site/` to GitHub Pages; `site/sitemap.xml`
  and the canonical links in each page name our address.
- `site/google*.html` and the key `.txt` file in `site/` verify **our** site with Google
  and Bing: delete them.
- `.github/workflows/release.yml` and `scripts/release.py` publish to the repo they run
  in, which is fine, but check the release notes text they write.

## Check

Search for anything still pointing here; every hit is either changed or a deliberate
choice:

```bash
git grep -nE "onion-alien|Onion-Alien|onionalien|goatcounter|workers\.dev|tally\.so|discord\.gg|proton\.me"
```

Tests never reach the network (`tests/conftest.py`), so running them sends nothing. A
built copy started normally does: build and run yours only after step 1.
