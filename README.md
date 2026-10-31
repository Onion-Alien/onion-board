<div align="center">

<img src="site/favicon.png" width="96" alt="Onion Board">

# Onion Board

### The free soundboard that plays sounds through your mic.

Press a pad or a hotkey, even in-game, and your friends in Discord or your game hear it.<br>
No virtual cable, no fiddly setup: Bun the bunny sets it up for you.

[![Latest release](https://img.shields.io/github/v/release/Onion-Alien/onion-board?label=version&color=6b8e23)](../../releases/latest)
![Windows 10 / 11](https://img.shields.io/badge/Windows-10%20%2F%2011-0078d4)
[![Free forever](https://img.shields.io/badge/price-free%20forever-6b8e23)](#free-and-it-stays-free)
[![Discord](https://img.shields.io/badge/Discord-join%20us-5865f2?logo=discord&logoColor=white)](https://discord.gg/FhKGaWCWHM)
[![GitHub stars](https://img.shields.io/github/stars/Onion-Alien/onion-board?style=flat&label=stars&color=6b8e23)](https://github.com/Onion-Alien/onion-board/stargazers)
<img src="https://hits.sh/github.com/Onion-Alien/onion-board.svg?view=total&label=total%20visits&color=6b8e23" alt="total visits">
<img src="https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FOnion-Alien%2Fonion-board%2Fbadges%2Finstalls.json" alt="app installs">
<img src="https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FOnion-Alien%2Fonion-board%2Fbadges%2Fpacks.json" alt="sound pack downloads">

## [⬇️ Download for Windows](../../releases/latest/download/OnionBoardSetup.exe)

<!-- release -->
Version **2.8.0** · Windows 10 / 11 · free, no account, no ads, anonymous usage count you can switch off ·
[VirusTotal: 67 of 67 clean](https://www.virustotal.com/gui/file/0721f9f42805cbfe5bd5dd10745654f9a8073b8eb74ad71383c92b72ce18a8d1) ·
[what's new](CHANGELOG.md)
<!-- /release -->

**[Website](https://onionalien.com/onionboard/)** · **[Discord](https://discord.gg/FhKGaWCWHM)** · **[Report a problem](../../issues/new/choose)**

If it helps you, a star helps other people find it. ⭐

<br>

![Onion Board's sound pads](site/screenshots/sounds.png?v=52563ccb)

<sub>Works with **Discord** · **your games** · **Zoom** · **Google Meet** · **OBS** · **Voicemeeter** · **Stream Deck** · **MIDI pads**</sub>

</div>

## Everything a soundboard should do, and then some

| | |
|---|---|
| 🎤 **No virtual cable**<br>Sounds go straight into the mic you already use in Discord and games, with your voice or without it. | 🔎 **One-click sounds**<br>Search YouTube, SoundCloud and Myinstants in the app and add a sound in one click. Or drag in files. |
| ⌨️ **Hotkeys that work in-game**<br>Plus an in-game overlay, MIDI pads and a [Stream Deck plugin](https://github.com/Onion-Alien/onion-board/releases/latest/download/com.onionalien.onionboard.streamDeckPlugin). Open your game and the board switches to its sounds. | 📦 **Bring your board over**<br>Coming from Soundpad, Resanance, Soundux or EXP Soundboard? Sounds, names and hotkeys come with you in one click. |
| 🎛️ **Effects on any sound**<br>Trim, speed, pitch, bass boost, reverse. One-click *Deep fried*, *Nightcore*, *Slowed + reverb*. | 🤖 **Voice changer and text-to-speech**<br>Change your voice live, or type and a computer voice says it, in 33 languages. Optional AI voices: 12 characters, or blend your own. |
| ✅ **Checks Discord for you**<br>Spots the Discord settings that would cut your sounds out and shows how to fix them. | 🧹 **Clean mic**<br>Takes fans, keyboards and room noise out of your voice before your sounds are mixed in, so they come through whole. |
| 📱 **Your pads on your phone**<br>With the free [Onion Pocket](https://github.com/Onion-Alien/onion-pocket) add-on: scan a QR code, tap a pad, it plays on your PC. | 📻 **And more**<br>Instant replay (the last 30 seconds as a pad), recording with your mic, screen triggers, world radio, sharing a program's sound, a clean OBS output, 32 themes, 32 languages. |

<div align="center">

**32** languages &nbsp;·&nbsp; **31** themes &nbsp;·&nbsp; **12** AI voices &nbsp;·&nbsp; **0** ads, accounts or cables &nbsp;·&nbsp; **$0** forever

<sub>The full list is in [docs/FEATURES.md](docs/FEATURES.md).</sub>

</div>

## A closer look

| | |
|:---:|:---:|
| ![Clean mic, voice changer and text-to-speech](site/screenshots/voice.png?v=29bd0f26) | ![Screen triggers](site/screenshots/triggers.png?v=3389b572) |
| **Voice** · clean the noise out of your mic, change your voice live, or type and a computer voice says it | **Triggers** · a sound the moment "YOU DIED" shows up in your game |
| ![Send a program's sound](site/screenshots/apps.png?v=2229b7e5) | ![Setup at a glance](site/screenshots/setup.png?v=a01ddaa5) |
| **Apps** · send one program's sound (music, a video) to your friends | **Setup** · one look tells you whether others can hear you |

## Get started in about a minute

1. **[Download `OnionBoardSetup.exe`](../../releases/latest/download/OnionBoardSetup.exe)** and run it.
2. **Meet Bun.** Bun the bunny asks which mic and headphones you use and sets the rest up.
3. **Into your mic.** Click **Put my sounds straight into my mic** (Windows asks once). Discord and games
   keep your normal mic, so there's nothing to pick there.

Then drag sounds onto the window, and right-click a pad to give it a hotkey.

> [!TIP]
> **In Discord** (*User Settings → Voice & Video*): set *Input Profile* to **Custom**, *Noise Suppression*
> to **None** and turn *Echo Cancellation* off. Onion Board reads these and warns you if one is in the way.
> For less background noise, switch on **Clean mic** on the *Voice* tab instead: it cleans your voice before
> your sounds are added, so they aren't touched.

<details>
<summary><b>Install with winget instead</b></summary>

```
winget install OnionAlien.OnionBoard
```

Update later with `winget upgrade OnionAlien.OnionBoard` (new versions reach winget a day or two after
the release).
</details>

<details>
<summary><b>Other ways to send your sounds</b> (virtual cable, Voicemeeter, OBS, nobody)</summary>

Pick it in Bun's step 3, or later under *Setup → Devices → Send my sounds to*:

- **A virtual cable**, the backup if your mic won't take it: installs the free VB-Cable. In Discord or
  your game, set your microphone to `CABLE Output` (and Discord's *Input Profile* to **Studio**).
- **Any other device** by name: Voicemeeter, a mixer, a capture card or a second sound card. Nothing is
  installed. In OBS add it as an *Audio Output Capture*.
- **Nobody**: only you hear your sounds. Nothing to change in Discord or your game.

Streamers: *Also play on → + Add a device* sends a copy to more than one place.
</details>

## Questions

<details>
<summary><b>Why does Windows or my browser warn me?</b></summary>

The app isn't code-signed yet (a certificate costs hundreds a year), so Windows doesn't know it.
Edge / Chrome: **⋯ → Keep**. Blue *"Windows protected your PC"* box: **More info → Run anyway**.
Every release is scanned on VirusTotal (the link is at the top).
</details>

<details>
<summary><b>My friends hear nothing</b></summary>

- The pill at the top should have a tick (✓), not a warning sign. Straight into your mic, it reads
  *In your mic — Discord / games hear your sounds*, and Discord or the game must use that same mic.
  With the cable, their microphone must be `CABLE Output`.
- They hear sounds but not you? Tick **Others hear it** under *My mic*.
- *Hear what they hear* at the bottom plays what others get.
- Still stuck? Ask in the [Discord](https://discord.gg/FhKGaWCWHM), or [open an issue](../../issues/new/choose)
  and attach `%APPDATA%\OnionBoard\onionboard.log` (skim it first: it has your device names).
</details>

<details>
<summary><b>What needs admin, and why?</b></summary>

Only the one-click *straight into my mic* step. It adds a small audio effect to your mic in Windows'
audio engine, backs up that mic's settings first, and puts them back when you switch it off or
uninstall. Windows asks once; a small helper then does repairs and changes of mic without asking again.
The details are in [SECURITY.md](SECURITY.md#what-straight-into-my-mic-changes-on-your-pc).
</details>

<details>
<summary><b>What goes online?</b></summary>

Only what you ask for (searches, downloads, the radio), an update check, and an anonymous daily count
you can switch off. Every request is listed in [SECURITY.md](SECURITY.md#what-the-app-does-on-the-network),
and the app shows each one live under *Settings → Connection → Network activity*.
</details>

<details>
<summary><b>How do I get rid of it?</b></summary>

Uninstall it like any app. Your mic goes back the way it was; your own sounds stay in
`%APPDATA%\OnionBoard\` until you delete them. If the uninstall didn't finish, run
[OnionBoardCleanup.exe](https://github.com/Onion-Alien/onion-board/releases/download/cleanup-tool/OnionBoardCleanup.exe):
it lists what's left and takes it all off when you say so.
</details>

<details>
<summary><b>How does Onion Pocket (the phone remote) stay safe?</b></summary>

It's off until you switch it on (*Settings → Remote → Get Onion Pocket*), only phones on your own Wi-Fi
can reach it, each with its own key from the QR code, and *Forget phones* locks them all out again.
A phone can play pads, run the radio and mute you, never touch your mic, the voice changer or your
files. Nothing to install on the phone: it opens in its browser.
</details>

## Meet Onion Watch

Our other free app: **[Onion Watch](https://github.com/Onion-Alien/onion-watch)** plays a sound when
something shows up in your game (a rare spawn, a queue pop, *YOU DIED*), even while you're alt-tabbed.
It's also Onion Board's *Triggers* tab.

<a id="license"></a>

## Free, and it stays free

[MIT with the Commons Clause](LICENSE): use it anywhere, monetized streams included, change it and share
your version for free. Nobody may sell it; if you paid for Onion Board, you were ripped off. The name
and logo aren't covered, so your own version needs its own name. Forking it?
[docs/FORKING.md](docs/FORKING.md) lists what to swap for your own (usage counts, the sound store,
update checks, links, name and logo).

Onion Board comes with no sounds: only play what you have the right to use. It isn't affiliated with
YouTube, SoundCloud, Myinstants, Discord, VB-Audio or any other service it mentions.

**Copyright and takedowns:** if a sound in the Community tab (or anything else here) is yours and shouldn't
be, email **onionboard.contact@proton.me** with the sound's name and why, and it comes down. Anyone
can also press *Report* on a sound in the Community tab.

**Like it?** A ⭐ or telling a friend helps a lot.

<details>
<summary><b>Chip in</b> (crypto only for now)</summary>

Trust only the addresses on `github.com/Onion-Alien/onion-board`.

| Coin | Address |
|---|---|
| **Bitcoin** (BTC) | `bc1qrr382vd6xsfavyuqvwxjy5watfd4fqr0tufyk7` |
| **Ethereum** (ETH, USDC…), also Base, Arbitrum, Polygon, Optimism | `0x11C66De40F99628aA52234Ae3aCa550Da5491A32` |
</details>

## For developers

Run from source: double-click `scripts\install.bat` (finds Python 3.12+, makes `.venv`, adds shortcuts),
then `scripts\run.bat`. Start with [docs/DEVELOPING.md](docs/DEVELOPING.md) (setup, checks, build,
release) and [docs/CODE.md](docs/CODE.md) (code layout, installer, audio). Also:
[CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [docs/PRIVACY.md](docs/PRIVACY.md) · [docs/BACKUP-FORMAT.md](docs/BACKUP-FORMAT.md) · [docs/CONTROL-API.md](docs/CONTROL-API.md).
`scripts\docs.py` rebuilds the screenshots and this page's version line.
