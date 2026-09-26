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
- Global hotkeys (all set in **⚙ Settings → Hotkeys**, and all work in-game):
  - Stop all, and pause/resume all.
  - Browser: record start/stop (Ctrl+Alt+R), save last 15s (Ctrl+Alt+C),
    play/pause (Ctrl+Alt+P) and LIVE on/off (Ctrl+Alt+L).
  - Auto push-to-talk: holds your game's PTT key while a sound plays.
  - Hotkeys that record or save a clip play a short beep in your headphones (only
    you hear it), so you know it worked without leaving the game.
- **⚙ Settings**: themes (Dark, Light, Toxic green, Ocean; they switch live),
  hotkeys, and window options.
- Volumes: sounds → them, your voice → them, your headphones. Exact % boxes
  go up to 1000%; a soft limiter stops hard clipping.
- "Level volumes" makes every sound equally loud.
- 7-band equalizer on your voice, your sounds, or both, with voice and music presets.
- Test mode:
  - **Listen to my mic output**: hear your mic plus the sounds exactly as others do
    (a red banner shows while it's on).
  - **Record 6s → play back**: records the virtual cable's output (what others get), plays it back,
    and reports whether your voice and sounds are in it and whether the balance is off.
- **Browser → mic** tab: a built-in browser (YouTube, SoundCloud, clip sites…). Whatever
  it plays goes live through your mic, so you don't have to download anything first.
  - **LIVE** toggle: off means only you hear it, which is handy for finding the right spot first.
  - Its own volume, plus "Hear it myself".
  - **⏺ Record clip** (click again to stop) and **⏪ Clip last 15s** (instant replay)
    save what played as a new pad on the Sounds tab, with dead air trimmed.
  - Stop all also pauses the browser, and auto push-to-talk holds while it's live.
  - Logins and cookies persist in `%APPDATA%\Soundboard\browser\`.
  - Limits: Qt's browser has no DRM (no Spotify / Netflix) and no H.264 (Twitch
    won't play). Media from another site without CORS plays, but only for you. The
    tab tells you when that happens.

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
Settings and imported sounds live in `%APPDATA%\Soundboard\`. Its `cache\` folder
holds each sound decoded and ready to play (int16 at 48 kHz), so later starts don't
decode anything; it's safe to delete and is rebuilt as needed.

## Code layout

| file | what it does |
|---|---|
| `main.py` | PySide6 UI, auto push-to-talk, startup (single instance, crash hooks, runtime tuning) |
| `applog.py` | rotating log in `%APPDATA%\Soundboard\soundboard.log`; unhandled exceptions and Qt warnings land there (plus one dialog for a UI-thread crash). `SOUNDBOARD_DEBUG=1` for more |
| `winkeys.py` | global hotkeys (`RegisterHotKey`) and key presses (`keybd_event`), no hooks |
| `engine.py` | real-time audio: 3 WASAPI streams (mic in, cable out, headphones out), mixing, pause/seek, limiter |
| `eq.py` | 7-band biquad equalizer and presets |
| `browser.py` | Browser tab: Qt WebEngine view; an isolated-world script taps page media via WebAudio and streams 48 kHz PCM over QWebChannel into the engine; clip recorder |
| `library.py` | decoding (bounded to 15 min), the int16 decoded-audio cache, loudness levelling, imports and clips (FLAC), config |
| `theme.py` | colour themes (tokens → stylesheet, also read by the painted widgets) and the logo |
| `settings.py` | Settings window, global hotkey actions, hotkey capture dialog |
| `make_icon.py` | regenerates `soundboard.ico` (shortcut icon) from the logo in `theme.py` |
| `testcheck.py` | analysis for the Record-6s test (finds your voice in the output by cross-correlation) |
| `tests/` | pytest suite for the device-free parts: ring buffer, engine mixing/guards/watchdog, hotkey parsing, EQ, levelling, config, test analysis |

Developing:

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest
```

### Audio notes

- Sounds are held in RAM as int16 stereo at 48 kHz (half the size of float32; the
  engine scales them in the same multiply as the gain). Only the first 15 minutes of a
  file are ever decoded. Video, m4a, aac and wma imports are stored as FLAC of their
  audio rather than a copy of the source, so the library is small and stays playable
  without ffmpeg. Re-importing a file that's already in the library is refused by
  content fingerprint.
- Browser recordings are spooled to a 16-bit WAV as they happen instead of growing in
  RAM, and the resampled copies kept for non-48 kHz devices are capped at 512 MB (LRU).
- Every device is opened at its **native** sample rate and resampled with soxr.
  Windows' built-in `auto_convert` resampler was measured garbling VB-Cable audio
  (about 70% junk), so it's never used.
- Virtual cables are hidden from the app's mic list. Picking the cable as the app's
  own mic makes a feedback loop (a loud screech).
- Hotkeys use Windows' `RegisterHotKey`, not a keyboard hook. The app is never in
  the path of your other keypresses, so it can't lag or stick your keys. A hotkey
  you pick is reserved for the app, so don't use one your game needs.
- Auto push-to-talk can't press keys in a game that runs as administrator unless
  Soundboard also runs as administrator (Windows blocks it).
- Drop-outs reported by the audio driver are counted and shown in the status line.
  **⚙ Settings → General → Audio buffering: Safer** trades a little delay for bigger
  buffers if a device keeps crackling.
- A stream whose callback stops (headset unplugged, sample rate changed, PC woke from
  sleep) is reopened automatically within about a second; a device that failed to open
  is retried every few seconds.
- The audio callbacks never take the engine lock: the voice list is an immutable tuple
  swapped by the UI thread. An exception inside a callback is logged once and that
  block is silent; the stream keeps running.
