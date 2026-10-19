# Onion Board for Stream Deck

A plugin for Elgato's Stream Deck app that plays your Onion Board sounds.

| Key | What it does |
|---|---|
| **Play sound** | Plays the sound you pick from a list. The key takes the pad's colour, shows its name and lights up while it plays. |
| **Stop all sounds** | Stops everything that's playing. |
| **Random sound** | A random sound: from any category, the one showing in Onion Board, or one you pick. |
| **Switch** | Live / Muted, the voice changer, "others hear my mic" or hotkeys, on and off. The key shows which it is, even when you change it in the app. |

It talks to Onion Board's control API (Settings → Remote → *Remote control*, off by
default). There's nothing to copy: the plugin reads the port and key from Onion Board's
`%APPDATA%\OnionBoard\config.json` (it never writes to it) and only connects to
`127.0.0.1`. If that doesn't work (a portable copy, say), a key's settings have *Connect by
hand* for the port and key from Settings → Remote.

## The files

Plain JavaScript for the Node 24 that Stream Deck 7.1+ runs plugins with: no libraries and
no build step.

- `com.onionalien.onionboard.sdPlugin/manifest.json`: the plugin and its four keys.
- `bin/plugin.js`: Stream Deck starts this; it connects and hands every event to…
- `bin/actions.js`: what each key does and keeping keys up to date (asks `/api/status`
  every second while a key is showing, every 3 s while Onion Board can't be reached).
- `bin/onionboard.js`: finding the API, the requests, drawing a key (SVG).
- `ui/`: a key's settings panel in the Stream Deck app.
- `imgs/`: made by `scripts/pictures/make_streamdeck_icons.py` (the icons from the app's
  logo); don't edit them by hand.

## Trying it

```bash
node --test streamdeck/test/
```

runs the tests (a stand-in for Onion Board's API; CI runs them too). To try it in the real
Stream Deck app, with [Elgato's CLI](https://github.com/elgatosf/cli):

```bash
npx @elgato/cli@1.10.2 link streamdeck/com.onionalien.onionboard.sdPlugin
npx @elgato/cli@1.10.2 restart com.onionalien.onionboard
```

## Packing

```bash
npx @elgato/cli@1.10.2 validate streamdeck/com.onionalien.onionboard.sdPlugin
npx @elgato/cli@1.10.2 pack streamdeck/com.onionalien.onionboard.sdPlugin -o dist
```

makes `dist/com.onionalien.onionboard.streamDeckPlugin`: double-clicking it installs the
plugin. `build.ps1` does this after the installer (`scripts/buildtools/pack_streamdeck.py`)
and every release carries the file. The manifest's `Version` is the app's plus `.0`:
`scripts/release.py` moves both, and Stream Deck only updates a plugin whose version went up.
