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
  - Embedded players (a YouTube or SoundCloud embed on another site) are captured too.
    If two players in different frames play at once, the one that started first is
    what goes out; the other is heard by nobody until the first stops.
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

Run from source with `run.bat` (or `python -m soundboard`); `main.py` at the root is
the launcher the shortcuts and PyInstaller use. The app is the `soundboard` package:

| file | what it does |
|---|---|
| `soundboard/app.py` | entry point: log file, crash hooks, runtime tuning, single instance, the window |
| `soundboard/singleinstance.py` | named mutex + local socket so a second launch just raises the first |
| `soundboard/ui/mainwindow.py` | the main window: pads, transport, tabs, the audio panel, test mode, auto push-to-talk |
| `soundboard/ui/widgets.py` | hand-painted widgets: meter, EQ curve, seek slider, pads and their grid |
| `soundboard/ui/panel.py` | volume boxes and the equalizer panel (emit values; the window applies them) |
| `soundboard/ui/dialogs.py` | per-sound Edit dialog |
| `soundboard/winkeys.py` | global hotkeys (`RegisterHotKey`) and key presses (`SendInput`), no hooks |
| `soundboard/engine.py` | real-time audio: 3 WASAPI streams (mic in, cable out, headphones out), mixing, pause/seek, limiter, watchdog |
| `soundboard/eq.py` | 7-band biquad equalizer and presets |
| `soundboard/browser.py` | Browser tab: Qt WebEngine view; an isolated-world script in every frame taps page media with an AudioWorklet and streams 48 kHz int16 PCM over a loopback WebSocket (per-launch secret) into the engine; clip recorder |
| `soundboard/library.py` | decoding (bounded to 15 min), the int16 decoded-audio cache, loudness levelling, imports and clips (FLAC), versioned config with backups |
| `soundboard/theme.py` | colour themes (tokens → stylesheet, also read by the painted widgets) and the logo |
| `soundboard/settings.py` | Settings window, global hotkey actions, hotkey capture dialog |
| `soundboard/wheelguard.py` | mouse wheel scrolls the page instead of changing sliders / dropdowns (installed per widget) |
| `soundboard/applog.py` | rotating log in `%APPDATA%\Soundboard\soundboard.log`; unhandled exceptions and Qt warnings land there (plus one dialog for a UI-thread crash). `SOUNDBOARD_DEBUG=1` for more |
| `soundboard/testcheck.py` | analysis for the Record-6s test (finds your voice in the output by cross-correlation) |
| `make_icon.py` | regenerates `soundboard.ico` (shortcut icon) from the logo in `theme.py` |
| `tests/` | pytest suite: ring buffer, engine mixing/guards/watchdog, cache and imports, recorder, hotkey parsing, EQ, levelling, config, test analysis, the main window built on Qt's offscreen platform (no window, no devices, no hotkeys), and the browser tab end to end: a headless page's audio (top frame and iframe) reaching the engine through the worklet and socket |

Developing:

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts
uff check .
.venv\Scripts\python -m pytest
```

`pyproject.toml` holds the package metadata (version comes from `soundboard/__init__.py`),
the ruff and pytest settings, and a `soundboard` GUI entry point for `pip install .`.

### Building an .exe

`build.ps1` runs PyInstaller and produces `dist\Soundboard\Soundboard.exe` (one folder,
QtWebEngine included). Zip that folder for a PC without Python; the virtual cable is still
installed from inside the app. Settings live in `%APPDATA%\Soundboard\` either way.
Every `config.json` save keeps the last three good copies next to it
(`config.json.1` … `.3`); a damaged file is set aside as `config.json.broken-<time>` and
the newest backup is used, so the pad list is never silently reset.

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
  Soundboard also runs as administrator (Windows blocks it). Keys are injected with
  `SendInput`, modifiers and key in one call.
- The window is GPU-composited from the start (`QT_WIDGETS_RHI=1`) so the browser
  tab can appear without rebuilding it. On a machine whose GPU driver or remote-desktop
  session can't do that, set `QT_WIDGETS_RHI=0` before launching.
- Drop-outs reported by the audio driver are counted and shown in the status line.
  **⚙ Settings → General → Audio buffering: Safer** trades a little delay for bigger
  buffers if a device keeps crackling.
- A stream whose callback stops (headset unplugged, sample rate changed, PC woke from
  sleep) is reopened automatically within about a second; a device that failed to open
  is retried every few seconds.
- The audio callbacks never take the engine lock: the voice list is an immutable tuple
  swapped by the UI thread. An exception inside a callback is logged once and that
  block is silent; the stream keeps running.
