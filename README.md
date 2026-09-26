# Soundboard

A gaming soundboard for Windows. It mixes **your mic + your sounds** into one
virtual mic, so Discord and games hear both, while you hear the sounds in your
headphones.

Version: **0.1.0** — see [CHANGELOG.md](CHANGELOG.md).

## How it works

```
🎤 your headset mic ─┐
                     ├─►  Soundboard mixes them  ─►  CABLE Input ═══ pipe ═══► CABLE Output
🔊 your sounds ──────┘                                                          (Discord / game mic)
```

The only setting you change outside the app: in **Discord / your game, pick
`CABLE Output (VB-Audio Virtual Cable)` as your microphone.** If a game has no
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
  - **Record 6s → play back**: records the real `CABLE Output`, plays it back,
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

## Requirements

- Windows 10/11
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (free)
- Python 3.11+ (built with 3.13)
- Optional: ffmpeg on PATH, for m4a/aac/video files

## Install & run

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run.bat
```

`run.bat` starts it without a console window. Settings and imported sounds are
stored in `%APPDATA%\Soundboard\` (`config.json` plus a `sounds\` folder), so they
survive updates.

## Code layout

| file | what it does |
|---|---|
| `main.py` | PySide6 UI, hotkeys, auto push-to-talk |
| `engine.py` | real-time audio: 3 WASAPI streams (mic in, cable out, headphones out), mixing, pause/seek, limiter |
| `eq.py` | 7-band biquad equalizer and presets |
| `browser.py` | Browser tab: Qt WebEngine view; an isolated-world script taps page media via WebAudio and streams 48 kHz PCM over QWebChannel into the engine; clip recorder |
| `library.py` | decoding, loudness levelling, saving clips, config |
| `testcheck.py` | analysis for the Record-6s test (finds your voice in the output by cross-correlation) |

### Audio notes

- Every device is opened at its **native** sample rate and resampled with soxr.
  Windows' built-in `auto_convert` resampler was measured garbling VB-Cable audio
  (about 70% junk), so it's never used.
- Virtual cables are hidden from the app's mic list. Picking the cable as the app's
  own mic makes a feedback loop (a loud screech).
- If a game runs as administrator, hotkeys only work if Soundboard does too.
