<p align="right"><img src="https://visitor-badge.laobi.icu/badge?page_id=Onion-Alien.onion-board" alt="visitors"></p>

# Onion Board

A free soundboard for Windows. Press a pad or a hotkey, even in-game, and **your
friends in Discord or your game hear the sound**, with your voice or without it.
Or send it to your stream, or keep it to your own headphones.

## ⬇️ [Download Onion Board for Windows](../../releases/latest/download/OnionBoardSetup.exe)

<!-- release -->
Version **1.9.0** · Windows 10 / 11 · free, no account, no ads, anonymous usage count you can switch off ·
[VirusTotal: 69 of 69 clean](https://www.virustotal.com/gui/file/c19238cbe0e32c81066dc8dae6084aafe5925e0dfc4cee31a25c7062a22c7967) ·
[what's new](CHANGELOG.md)
<!-- /release -->

![Onion Board's sound pads](docs/screenshots/sounds.png?v=40b665fb)

| | |
|---|---|
| ![Voice changer and text-to-speech](docs/screenshots/voice.png?v=ea48680a) | ![Screen triggers](docs/screenshots/triggers.png?v=5a7e3f8b) |
| **Voice**: change your voice live, or type and a computer voice says it | **Triggers**: a sound the moment "YOU DIED" shows up in your game |
| ![Send a program's sound](docs/screenshots/apps.png?v=ddf57f61) | ![Setup at a glance](docs/screenshots/setup.png?v=a211385e) |
| **Apps**: send one program's sound (music, a video) to your friends | **Setup**: one look tells you whether others can hear you |

## What it does

- **Sounds into Discord and games.** The easy default is a free virtual cable the
  installer offers to set up. Or send them to any other output you pick (Voicemeeter,
  a mixer, a capture card, OBS), or nowhere, so only you hear them. Your mic goes
  along, or tick it off and send only sounds.
- **Hotkeys that work in-game**, MIDI pads, an in-game overlay, Stream Deck support,
  and your pads on your phone with the optional Onion Pocket add-on.
- **Add sounds from anywhere**: drag in files, or search YouTube and SoundCloud
  inside the app.
- **Effects on any sound**: trim, speed, pitch, bass boost, reverse. One-click
  *Ear rape*, *Nightcore*, *Slowed + reverb*.
- **Voice changer, text-to-speech** and live voice-to-speech.
- **Instant replay**: one key turns the last 30 seconds you heard into a pad.
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
   and double-click it. Leave the boxes as they are and click through to **Install**,
   then **Yes** when Windows asks (that's the free virtual cable; untick it if you'll
   send sounds to another device or nowhere).
2. **Follow Bun the bunny's four steps**: your mic, your headphones, where your
   sounds go, and what to set in Discord or your game.
3. **Pick where your sounds go** (step 3 of Bun's guide, or later on the *Setup* tab →
   Devices → *Send to others through*):
   - **The virtual cable** (the default): in Discord or your game, set your
     microphone to `CABLE Output`. (Discord: *User Settings → Voice & Video → Input
     Device*, and set *Input Profile* to **Studio** so it doesn't filter your sounds
     out.)
   - **Another device**: any output but your headphones, such as Voicemeeter, a
     mixer, a capture card or a second sound card. Nothing is installed. In OBS add
     it as an *Audio Output Capture*; in Voicemeeter or a mixer, send that input on
     to wherever it should go.
   - **Nowhere**: only you hear your sounds (and the *Stream output* if you set one).
     Nothing to change in Discord or your game.
4. **Drag sounds onto the window** and double-click a pad to play it. Right-click a
   pad for a hotkey or **Effects…**.

> **Windows or your browser may warn you.** That's normal for a free app that isn't
> code-signed (that costs hundreds a year). Edge / Chrome: **⋯ → Keep**. Blue
> *"Windows protected your PC"* box: **More info → Run anyway**.

### Something's not right?

- **Friends hear nothing:** the pill at the top should be green. With the cable, it
  reads *Your mic in Discord / games* and their app's microphone must be `CABLE
  Output`. With another device, it reads *Sending to:* and whatever sits on the other
  end (OBS, Voicemeeter, your mixer) must be picking that device up. With *Nowhere*,
  only you hear sounds, on purpose.
- **They hear sounds but not you:** tick **Others hear it** under *My mic*.
- **Check it yourself:** *Setup → Record 6s → play back* records what others get (it
  needs the cable or another device, not *Nowhere*).
- **Switch how sounds go out any time:** *Setup → Devices → Send to others through*.
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
adds shortcuts, offers the virtual cable), then `scripts\run.bat`.

- [docs/DEVELOPING.md](docs/DEVELOPING.md): setup, checks, build, release
- [docs/CODE.md](docs/CODE.md): code layout, the installer, audio notes
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) ·
  [docs/BACKUP-FORMAT.md](docs/BACKUP-FORMAT.md)
- `scripts\docs.py` rebuilds the screenshots and this page's version line
