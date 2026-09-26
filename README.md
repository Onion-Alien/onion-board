# Soundboard

A gaming soundboard for Windows. It mixes **your mic + your sounds** into one
virtual mic, so Discord and games hear both, while you hear the sounds in your
headphones.

Version: **0.1.0** — see [CHANGELOG.md](CHANGELOG.md).

## How it works

```
🎤 your mic ─────────┐
                     ├─►  Soundboard mixes them  ─►  CABLE Input ═══ pipe ═══► CABLE Output
🔊 your sounds ──────┘                                                          (Discord / game mic)
```

The only setting you change outside the app: in **Discord / your game, pick the
virtual cable's output (for VB-Cable that's `CABLE Output`) as your microphone.** If a game has no
mic setting, the app's *"Game has no microphone setting?"* button walks you
through making the cable Windows' default mic.

## Features

- Pads: add by button or drag-and-drop (files or folders). Plays mp3, wav, ogg, flac,
  m4a and more, and pulls the audio out of video files. Search, reorder, resize,
  set colours.
- Per sound: global hotkey (works in-game), volume, loop, and what pressing again
  does (restart / overlap / toggle).
- Transport bar: play/pause, stop, and a seek slider to jump anywhere in the track.
- Global hotkeys: stop all, pause/resume all, and auto push-to-talk (holds your
  game's PTT key while a sound plays).
- Volumes: sounds → them, your voice → them, your headphones. Exact % boxes
  go up to 1000%; a soft limiter stops hard clipping.
- "Level volumes" makes every sound equally loud.
- 7-band equalizer on your voice, your sounds, or both, with voice and music presets.
- Test mode:
  - **Listen to my mic output**: hear your mic plus the sounds exactly as others do
    (a red banner shows while it's on).
  - **Record 6s → play back**: records the virtual cable's output (what others get), plays it back,
    and reports whether your voice and sounds are in it and whether the balance is off.

## Install (any Windows PC)

1. Download or clone this folder.
2. Double-click **`install.bat`**. It:
   - finds Python 3.11+ (offers to install 3.13 with winget if you have none)
   - installs the Python packages into `.venv`
   - adds **Soundboard** shortcuts to the Desktop and Start menu
   - offers to install the free **virtual cable** (VB-Cable)
3. Open Soundboard. The *How it works* box tells you the one setting to change in
   Discord or your game.

### The virtual cable

It's a free audio driver (VB-Audio Virtual Cable) that acts like a pipe: the app
plays into one end and Discord or the game uses the other end as a microphone.
It isn't included in this repo because VB-Audio's licence doesn't allow
redistributing it. `install-vbcable.ps1` downloads the current pack from
[vb-audio.com](https://vb-audio.com/Cable/), checks the installer is signed by
VB-Audio, and runs it. Windows asks for admin permission. The app's *Install the
free virtual cable* button runs the same script. Other virtual cables
(VB-Cable A/B, Voicemeeter) are detected too.

Optional: `winget install Gyan.FFmpeg.Essentials` adds m4a/aac/video support.
Settings and imported sounds live in `%APPDATA%\Soundboard\`.

## Code layout

| file | what it does |
|---|---|
| `main.py` | PySide6 UI, hotkeys, auto push-to-talk |
| `engine.py` | real-time audio: 3 WASAPI streams (mic in, cable out, headphones out), mixing, pause/seek, limiter |
| `eq.py` | 7-band biquad equalizer and presets |
| `library.py` | decoding, loudness levelling, config |
| `testcheck.py` | analysis for the Record-6s test (finds your voice in the output by cross-correlation) |

### Audio notes

- Every device is opened at its **native** sample rate and resampled with soxr.
  Windows' built-in `auto_convert` resampler was measured garbling VB-Cable audio
  (about 70% junk), so it's never used.
- Virtual cables are hidden from the app's mic list. Picking the cable as the app's
  own mic makes a feedback loop (a loud screech).
- If a game runs as administrator, hotkeys only work if Soundboard does too.
