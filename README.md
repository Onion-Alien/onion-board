# Onion Board

A free soundboard for Windows. Press a pad or a hotkey, even in-game, and **your
friends in Discord or your game hear the sound through your mic**, with your voice
or without it.

## ⬇️ [Download Onion Board for Windows](../../releases/latest/download/OnionBoardSetup.exe)

<!-- release -->
Version **1.6.5** · Windows 10 / 11 · free, no account, no ads, no tracking ·
[VirusTotal: 68 of 68 clean](https://www.virustotal.com/gui/file/4267e4cf1ebdff01fcfacfea926fb13a1d88fdb82cce048f473b8155d8560ac6) ·
[what's new](CHANGELOG.md)
<!-- /release -->

![Onion Board's sound pads](docs/screenshots/sounds.png)

| | |
|---|---|
| ![Voice changer and text-to-speech](docs/screenshots/voice.png) | ![Screen triggers](docs/screenshots/triggers.png) |
| **Voice**: change your voice live, or type and a computer voice says it | **Triggers**: a sound the moment "YOU DIED" shows up in your game |
| ![Send a program's sound](docs/screenshots/apps.png) | ![Setup at a glance](docs/screenshots/setup.png) |
| **Apps**: send one program's sound (music, a video) to your friends | **Setup**: one look tells you whether others can hear you |

## What it does

- **Sounds into Discord and games** through a free virtual cable the installer sets up.
  Your mic goes along, or tick it off and send only sounds.
- **Hotkeys that work in-game**, MIDI pads, an in-game overlay, Stream Deck support.
- **Add sounds from anywhere**: drag in files, or search YouTube and SoundCloud
  inside the app.
- **Effects on any sound**: trim, speed, pitch, bass boost, reverse. One-click
  *Ear rape*, *Nightcore*, *Slowed + reverb*.
- **Voice changer, text-to-speech** and live voice-to-speech.
- **Instant replay**: one key turns the last 30 seconds you heard into a pad.
- **Screen triggers**, **world radio**, a **clean stream output for OBS**, and 31 themes.

The full list is in [docs/FEATURES.md](docs/FEATURES.md).

## Get started

1. **[Download `OnionBoardSetup.exe`](../../releases/latest/download/OnionBoardSetup.exe)**
   and double-click it. Leave the boxes as they are and click **Install**, then
   **Yes** when Windows asks (that's the virtual cable).
2. **Answer Bun the bunny's four questions**: your mic, your headphones, the cable.
3. **In Discord or your game, set your microphone to `CABLE Output`.**
   (Discord: *User Settings → Voice & Video → Input Device*, and set *Input Profile*
   to **Studio** so it doesn't filter your sounds out.)
4. **Drag sounds onto the window** and double-click a pad to play it. Right-click a
   pad for a hotkey or **Effects…**.

> **Windows or your browser may warn you.** That's normal for a free app that isn't
> code-signed (that costs hundreds a year). Edge / Chrome: **⋯ → Keep**. Blue
> *"Windows protected your PC"* box: **More info → Run anyway**.

### Something's not right?

- **Friends hear nothing:** their mic must be **`CABLE Output`**, and the *Your mic
  in Discord / games* pill in Onion Board should be green.
- **They hear sounds but not you:** tick **Others hear it** under *My mic*.
- **Check it yourself:** *Setup → Record 6s → play back* records exactly what others get.
- **Using Voicemeeter, a mixer or OBS instead of the cable?** *Setup → Devices →
  Send to others through → Another device*.
- **Still stuck?** [Open an issue](../../issues/new/choose) and attach
  `%APPDATA%\OnionBoard\onionboard.log` (skim it first: it has your device names).

Your sounds and settings live in `%APPDATA%\OnionBoard\` and survive reinstalls.

## Free, and it stays free

[MIT with the Commons Clause](LICENSE): use it anywhere, monetized streams included,
change it and share your version for free. Nobody may sell it; if you paid for
Onion Board, you were ripped off. The name and logo aren't covered, so your own
version needs its own name.

Onion Board comes with no sounds. Only play what you have the right to use. It isn't
affiliated with YouTube, SoundCloud, Myinstants, Discord, VB-Audio or any other
service it mentions.

**Chip in** (crypto only for now; trust only the addresses on
`github.com/Onion-Alien/onion-board`):

| Coin | Address |
|---|---|
| **Bitcoin** (BTC) | `bc1qrr382vd6xsfavyuqvwxjy5watfd4fqr0tufyk7` |
| **Ethereum** (ETH, USDC…), also Base, Arbitrum, Polygon, Optimism | `0x11C66De40F99628aA52234Ae3aCa550Da5491A32` |

A star or telling a friend helps just as much.

## For developers

Run from source: double-click `scripts\install.bat` (finds Python 3.12+, makes `.venv`,
adds shortcuts, offers the virtual cable), then `scripts\run.bat`.

- [docs/DEVELOPING.md](docs/DEVELOPING.md): setup, checks, build, release
- [docs/CODE.md](docs/CODE.md): code layout, the installer, audio notes
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) ·
  [docs/BACKUP-FORMAT.md](docs/BACKUP-FORMAT.md)
- `scripts\docs.py` rebuilds the screenshots and this page's version line
