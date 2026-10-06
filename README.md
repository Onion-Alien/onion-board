<p align="right"><img src="https://hits.sh/github.com/Onion-Alien/onion-board.svg?view=total&label=total%20visits&color=6b8e23" alt="total visits"></p>

# Onion Board

A free soundboard for Windows. Press a pad or a hotkey, even in-game, and **your
friends in Discord or your game hear the sound**, with your voice or without it.
Or send it to your stream, or keep it to your own headphones.

## ⬇️ [Download Onion Board for Windows](../../releases/latest/download/OnionBoardSetup.exe)

<!-- release -->
Version **1.9.6** · Windows 10 / 11 · free, no account, no ads, anonymous usage count you can switch off ·
[VirusTotal: 66 of 66 clean](https://www.virustotal.com/gui/file/800165727a34f556ef256564a4ea95a1526fefa1a7e154d607eb08ab42f4553f) ·
[what's new](CHANGELOG.md)
<!-- /release -->

![Onion Board's sound pads](docs/screenshots/sounds.png?v=5d4d4efc)

| | |
|---|---|
| ![Voice changer and text-to-speech](docs/screenshots/voice.png?v=c7aa5887) | ![Screen triggers](docs/screenshots/triggers.png?v=74911d4a) |
| **Voice**: change your voice live, or type and a computer voice says it | **Triggers**: a sound the moment "YOU DIED" shows up in your game |
| ![Send a program's sound](docs/screenshots/apps.png?v=8fc8871d) | ![Setup at a glance](docs/screenshots/setup.png?v=b52be90b) |
| **Apps**: send one program's sound (music, a video) to your friends | **Setup**: one look tells you whether others can hear you |

## What it does

- **Sounds into Discord and games.** By default they go straight into your own mic:
  one click in the app, and Discord and games hear them through the mic they already
  use, with no virtual cable to install. Or, as a backup, the free virtual cable; or
  any other output you pick (Voicemeeter, a mixer, a capture card, OBS); or nowhere,
  so only you hear them. Your voice goes along, or tick it off and send only sounds.
- **One-click sounds**: search YouTube, SoundCloud and Myinstants inside the app and
  add a sound in one click, drag in files, or record one with your mic.
- **Hotkeys that work in-game**, an in-game overlay, MIDI pads, Stream Deck support,
  and your pads on your phone with the optional Onion Pocket add-on. Open your game
  and the board switches to that game's sounds by itself.
- **Bring your board over** from Soundpad, Resanance, Soundux or EXP Soundboard:
  sounds, names, categories and hotkeys, in one click.
- **Effects on any sound**: trim, speed, pitch, bass boost, reverse. One-click
  *Deep fried*, *Nightcore*, *Slowed + reverb*.
- **Voice changer, text-to-speech** and live voice-to-speech, plus optional **AI
  voices** that make you sound like someone else, live on your own PC.
- **Instant replay**: one key turns the last 30 seconds you heard into a pad.
- **Share a program's sound** (music, a video) with your friends, and grab the bit you
  want from it in the **clip editor**.
- **Screen triggers**, **world radio**, a **clean stream output for OBS**, and 31 themes.

The full list is in [docs/FEATURES.md](docs/FEATURES.md).

## 📱 Your pads on your phone

<img align="right" width="220" src="https://raw.githubusercontent.com/Onion-Alien/onion-pocket/main/docs/screenshots/phone.png" alt="Onion Pocket on a phone: colourful pads by category, two playing, Stop all and the volume, and the Pads, Radio and Sound tabs at the bottom">

With the free **[Onion Pocket](https://github.com/Onion-Alien/onion-pocket)** add-on,
your phone becomes a remote for your board. Scan a QR code on your PC with your
phone's camera, tap a pad, and it plays on the PC, into Discord or your game like
any other pad. Its **Radio** tab runs the radio (your favourites, popular stations,
search, live or just for you) and its **Sound** tab changes the speed, pitch, bass
and effects of what's playing, and who's listening.

- **Nothing to download on your phone.** It opens in the phone's browser, on iPhone
  or Android. No app, no account.
- **One click to get it:** Settings → Remote → **Get Onion Pocket**. It comes
  straight from its GitHub release and is checked before it's installed.
- **Safe by default.** It's off until you switch it on, and only phones on your own
  Wi-Fi can reach it, with their own key from the QR code. *Forget phones* locks
  them all out again.
- **It can't touch your mic.** A phone can play your pads, run the radio, change the
  live speed, pitch and effects, and mute you. Never your mic, the voice changer or
  your files.
- Windows asks once to let phones through its firewall; that rule only covers your
  home network. Use it at home rather than on public Wi-Fi.

Optional: if you never get it, nothing changes.

<br clear="right">

## Get started

1. **[Download `OnionBoardSetup.exe`](../../releases/latest/download/OnionBoardSetup.exe)**
   and double-click it. Leave the boxes as they are and click through to **Install**.

   Or, if you use [winget](https://learn.microsoft.com/windows/package-manager/winget/),
   install it from a terminal with no clicks (and update it later with
   `winget upgrade OnionAlien.OnionBoard`; new versions reach winget a day or two
   after the release):

   ```
   winget install OnionAlien.OnionBoard
   ```
2. **Follow Bun the bunny's four steps**: your mic, your headphones, where your
   sounds go, and what to set in Discord or your game.
3. **Pick where your sounds go** (step 3 of Bun's guide, or later on the *Setup* tab →
   Devices → *Send my sounds to*):
   - **My mic** (the default): click **Put my sounds straight into my
     mic** and **Yes** when Windows asks (once). Discord and games keep your normal
     mic, so there's nothing to pick there. In Discord, set *User Settings → Voice &
     Video → Input Profile* to **Studio** so it doesn't filter your sounds out.
   - **A virtual cable** (the backup, if your mic won't take it; pick it by name): installs the free
     VB-Cable; in Discord or your game, set your microphone to `CABLE Output` (and
     Discord's *Input Profile* to **Studio**).
   - **Any other device** by name: any output but your headphones, such as Voicemeeter, a
     mixer, a capture card or a second sound card. Nothing is installed. In OBS add
     it as an *Audio Output Capture*; in Voicemeeter or a mixer, send that input on
     to wherever it should go.
   - **Nobody**: only you hear your sounds (and the *Stream output* if you set one).
     Nothing to change in Discord or your game.
4. **Drag sounds onto the window** and double-click a pad to play it. Right-click a
   pad for a hotkey or **Effects…**.

> **Windows or your browser may warn you.** That's normal for a free app that isn't
> code-signed (that costs hundreds a year). Edge / Chrome: **⋯ → Keep**. Blue
> *"Windows protected your PC"* box: **More info → Run anyway**.

### Something's not right?

- **Friends hear nothing:** the pill at the top should have a tick (✓), not a warning
  sign. Straight into your mic, it reads *In your mic — Discord / games hear your sounds*, and Discord or the
  game must be using that same mic. With the cable, it reads *Your mic in Discord /
  games* and their app's microphone must be `CABLE Output`. With another device, it
  reads *Sending to:* and whatever sits on the other end (OBS, Voicemeeter, your
  mixer) must be picking that device up. With *Nobody*, only you hear sounds, on
  purpose.
- **They hear sounds but not you:** tick **Others hear it** under *My mic*.
- **Check it yourself:** *Setup → Record 6s → play back* records what others get (it
  works any way but *Nobody*).
- **Switch how sounds go out any time:** *Setup → Devices → Send my sounds to*.
- **More than one place at once** (streamers): *Setup → Devices → Also send to →
  + Add a device*, once per extra output that should get a copy (− takes one off).
- **Have the virtual cable from before?** Once your sounds are in your mic, the
  *Setup* tab offers to remove it. Keep it if another program uses it.
- **Still stuck?** [Open an issue](../../issues/new/choose) and attach
  `%APPDATA%\OnionBoard\onionboard.log` (skim it first: it has your device names).

Your sounds and settings live in `%APPDATA%\OnionBoard\` and survive reinstalls.

### Is it safe?

- **Why Windows warns you:** the app isn't code-signed yet, so Windows doesn't know
  it. Every release is scanned on VirusTotal (the link is at the top).
- **What needs admin:** only the one-click *straight into my mic* step. It adds a
  small audio effect to your mic inside Windows' audio engine, backs up that mic's
  settings first, and puts them back when you switch it off or uninstall. The details
  are in [SECURITY.md](SECURITY.md#what-straight-into-my-mic-changes-on-your-pc).
- **What goes online:** only what you ask for (searches, downloads, the radio), an
  update check, and an anonymous daily count you can switch off. Every request is
  listed in [SECURITY.md](SECURITY.md#what-the-app-does-on-the-network), and the app
  shows each one live under *Settings → Connection → Network activity*.
- **Getting rid of it:** uninstall it like any app. Your mic goes back the way it was;
  your own sounds stay in `%APPDATA%\OnionBoard\` until you delete them.

<a id="license"></a>

## Free, and it stays free

[MIT with the Commons Clause](LICENSE): use it anywhere, monetized streams included,
change it and share your version for free. Nobody may sell it; if you paid for
Onion Board, you were ripped off. The name and logo aren't covered, so your own
version needs its own name.

Onion Board comes with no sounds. Only play what you have the right to use. It isn't
affiliated with YouTube, SoundCloud, Myinstants, Discord, VB-Audio or any other
service it mentions.

### Support Onion Board

**Chip in** (crypto only for now; trust only the addresses on
`github.com/Onion-Alien/onion-board`):

| Coin | Address |
|---|---|
| **Bitcoin** (BTC) | `bc1qrr382vd6xsfavyuqvwxjy5watfd4fqr0tufyk7` |
| **Ethereum** (ETH, USDC…), also Base, Arbitrum, Polygon, Optimism | `0x11C66De40F99628aA52234Ae3aCa550Da5491A32` |

A star or telling a friend helps just as much.

## For developers

Run from source: double-click `scripts\install.bat` (finds Python 3.12+, makes `.venv`,
adds shortcuts, optionally the virtual cable), then `scripts\run.bat`.

- [docs/DEVELOPING.md](docs/DEVELOPING.md): setup, checks, build, release
- [docs/CODE.md](docs/CODE.md): code layout, the installer, audio notes
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) ·
  [docs/BACKUP-FORMAT.md](docs/BACKUP-FORMAT.md)
- `scripts\docs.py` rebuilds the screenshots and this page's version line
