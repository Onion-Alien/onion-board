# Soundboard

A free soundboard for Windows gamers. Press a button (or a hotkey, even in-game)
and **your friends in Discord or your game hear the sound** through your mic. Your
voice goes along with it, or switch that off and send **only the sounds**.

## ⬇️ [Download Soundboard for Windows](../../releases/latest/download/SoundboardSetup.exe)

One file, `SoundboardSetup.exe`. Download it, double-click it, done.
Windows 10 or 11.

<sub>Other downloads: [all versions](../../releases) ·
[source code (zip)](../../archive/refs/heads/main.zip), only if you want to build
it yourself.</sub>

Version: **0.2.0**. See [CHANGELOG.md](CHANGELOG.md).

---

## Get started (no computer skills needed)

**1. [Download `SoundboardSetup.exe`](../../releases/latest/download/SoundboardSetup.exe).**

**2. Double-click it.** If Windows shows a blue *"Windows protected your PC"*
box, click **More info → Run anyway**. That appears for most small programs that
aren't from a big company.

**3. Pick what you want.** The installer shows a list of tick boxes. If you're not
sure, leave them as they are and click **Install**.

| Box | What it's for | Ticked already? |
|---|---|---|
| **The free virtual cable** | The part that lets Discord and games hear your sounds. You need it. | ✅ yes |
| **Play M4A, AAC and video files** | Lets you add `.m4a` files and videos as sounds. Only shown if your PC doesn't have it yet. | ✅ yes |
| **Set up live voice-to-speech now** | You talk, and everyone hears a computer voice say your words instead. Needs [Python](https://www.python.org/downloads/) installed first, and a 300 MB download. You can also set it up later from the *Voice* tab. | no |
| **Desktop shortcut** | An icon on your Desktop. | ✅ yes |

**4. Click Yes** when Windows asks for permission. That's the virtual cable
being installed.

**5. Answer Bun's four questions.** Soundboard opens with a short guide hosted by
Bun the bunny 🐰:
- *Which mic do you talk into?* Pick yours and say something. The bar should move.
  There's a **Send my voice too** box here. Untick it if you only want your sounds
  to go out.
- *Where do you listen?* Pick your headphones and play the test chime.
- *The virtual cable* is checked (and installed if it's missing).
- *Tell Discord or your game* which mic to use.

**6. Change one setting in Discord or your game.** Set your **microphone / input
device** to **`CABLE Output`**. In Discord that's *User Settings → Voice & Video →
Input Device*. If a game has no mic setting, the Setup tab's *"Game has no
microphone setting?"* button shows you how to make it Windows' default mic.

**7. Add sounds and play.** Drag sound files onto the window (or click **Add sounds**),
then click a pad. Right-click a pad to give it a hotkey that works in-game, or
**Effects…** to make a sped-up, slowed, pitched or ear-rape version of it.

Got a link instead of a file? Paste it into **Search sounds** (YouTube,
SoundCloud, TikTok, X, Reddit, a direct link to an audio or video file — most
media sites, via [yt-dlp](https://github.com/yt-dlp/yt-dlp)). It's looked up and
you get **Add as sound** (or press Enter) and **Play once**, which plays it
through your mic without keeping it.

### Your voice, or just the sounds?

Next to **My mic** at the bottom of the window there's a **send** box:

- **Ticked** (normal): others hear **your voice and your sounds** together. Your
  mic works like it always did, plus sounds.
- **Unticked** (sounds only): others hear **only the sounds**, never your mic.
  Handy if you talk through a different app, or just want to be the DJ.

The same switch is in **⚙ Settings → General → Your mic** and in the setup guide.

### Something's not right?

- **Friends can't hear anything:** check Discord or the game uses
  **`CABLE Output`** as its mic, and that Soundboard's *"Your mic in Discord /
  games"* pill is green.
- **They hear sounds but not you:** tick **send** next to *My mic*.
- **Check it yourself:** the *Setup* tab's **Record 6s → play back** records
  exactly what others get and tells you whether your voice and sounds are in it.
- **An `.m4a` or video won't add:** run the installer again and tick *Play M4A,
  AAC and video files*.
- **The Browser tab looks stuck or blank:** click **Show page** in the mini-player,
  or turn off **Lite** at the bottom of the tab.
- **Something else:** the log is `%APPDATA%\Soundboard\soundboard.log`. Attach it
  to a [bug report](../../issues/new/choose) (it contains your device names and
  file paths, so skim it first).
- **Start the guide again:** *Setup* tab → *Step-by-step guide*.

Your sounds and settings are kept in `%APPDATA%\Soundboard\` and survive
reinstalling or uninstalling.

---

## What it can do

- **Pads:** add by button or drag-and-drop (files or folders). Plays mp3, wav, ogg,
  flac, m4a and more, and pulls the audio out of video files. Search, reorder,
  resize, set colours.
- **Per sound:** global hotkey (works in-game), volume, loop, and what pressing
  again does (restart / overlap / toggle).
- **Effects on any sound** (right-click a pad → **Effects…**, or the *Effects* tab
  of **Edit…**): speed and pitch (separately, or together like a record player
  with *Tape mode*), a 7-band EQ, a boost up to +36 dB that clips on purpose,
  play backwards, and every voice effect (echo, reverb, distortion, radio, robot,
  add-on effects too). One-click presets: **Ear rape**, Bass boosted,
  Slowed + reverb, Nightcore, Chipmunk, Demon, Fast / Slow-mo (same pitch), Old
  radio, Reversed. *Preview* plays it to you only; **Save** changes that pad,
  **Save as new sound** keeps the original and adds the edited version as its own
  pad. Pads with effects show **FX**; *Reset* goes back to the original. The
  original file is never changed.
- **Your mic on or off:** send your voice with the sounds, or sounds only.
- **Transport bar:** play/pause, stop, a seek slider, and **speed & pitch while
  it plays** (the `1x` button: 0.25×–2×, ±12 semitones, keep the pitch or not).
  That's for listening and isn't saved; use Effects to keep a version.
- **Any window size:** shrink it down to 300 × 300 and it stays usable. Less
  important controls tuck away as it gets smaller and come back when it grows.
- **Global hotkeys** (set in **⚙ Settings → Hotkeys**, the overlay key in
  **⚙ Settings → Overlay**; all work in-game):
  - Stop all, and pause/resume all.
  - Browser: record start/stop (Ctrl+Alt+R), save last 15s (Ctrl+Alt+C),
    play/pause (Ctrl+Alt+P) and LIVE on/off (Ctrl+Alt+L).
  - **In-game overlay** (the <kbd>`</kbd> key by default): a small panel of your
    sounds over the game. Number keys play them, and the game keeps your mouse
    and keyboard.
  - Auto push-to-talk: holds your game's PTT key while a sound plays.
  - Hotkeys that record or save a clip beep in your headphones (only you hear
    it), so you know it worked.
- **Voice tab:** voice changer (pitch, robot, radio, echo, reverb, distortion,
  8-bit bitcrusher, plus add-on effects; it starts off every time the app
  opens, and a big ON / OFF button shows which it is), text-to-speech with Windows' built-in
  voices, and **live voice-to-speech**: press *Start talking as the voice* and each
  sentence you say is spoken by a computer voice instead of yours. Speech
  recognition runs on your PC (the first time, the Voice tab's *Install speech
  recognition* button downloads it, about 300 MB; needs Python 3.12+).
- **Volumes:** sounds → them, your voice → them, your headphones. Exact % boxes go
  up to 1000%; a soft limiter stops hard clipping. "Level volumes" makes every
  sound equally loud.
- **7-band equalizer** on your voice, your sounds, or both, with presets.
- **Test mode:**
  - **Hear what they hear:** your mic plus the sounds exactly as others get them
    (a red banner shows while it's on).
  - **Record 6s → play back:** records the virtual cable's output, plays it back,
    and reports whether your voice and sounds are in it and whether the balance
    is off.
- **Browser tab:** a built-in browser (YouTube, SoundCloud, clip sites…) with
  an ad blocker. Whatever it plays goes live through your mic, no downloading.
  - **LIVE** off means only you hear it, handy for finding the right spot first.
    It starts off every time the app opens.
  - Its own volume, plus "Hear it myself".
  - **Speed & pitch** (the `1x` button): slow a video down or speed it up, with or
    without changing its pitch, and shift the pitch on its own. It applies to
    every video and embed you play until you press *Reset*, and what's recorded
    or clipped has it too. At normal speed the site's own speed menu works as usual.
  - **Record** and **Last 15s** save what played as a new pad, with dead air
    trimmed.
  - **Add as sound** downloads the open video's audio (YouTube, SoundCloud and
    most video sites, via [yt-dlp](https://github.com/yt-dlp/yt-dlp)) and adds
    the whole thing as a pad. YouTube's m4a/webm audio needs FFmpeg, like a
    dropped m4a file does. Settings → General has *Update now* and *Reset
    downloader* for when downloads start failing, and an opt-in box to update
    yt-dlp from PyPI automatically (off by default).
  - **Lite** (on by default): while a video plays, the page is swapped for a
    small player (title, seek bar, play/pause, ±10 s, next) and YouTube drops to
    144p, so the browser costs your game almost nothing. A YouTube video you open
    goes straight to the small player, and it stays there while paused. Opening
    another site brings the page back; sound-button sites never collapse.
  - Stop all also pauses the browser, and auto push-to-talk holds while it's live.
  - Logins and cookies persist in `%APPDATA%\Soundboard\browser\`.
  - It only opens YouTube, SoundCloud and the big sound-clip sites (MyInstants,
    101 Soundboards, Voicy, Voicemod Tuna, Freesound, ZapSplat, SoundBible,
    Pixabay, Mixkit, Orange Free Sounds, Bandcamp) and TikTok; a link anywhere else is refused.
    Qt's browser has no Safe Browsing, so it stays off the rest of the web. It
    never downloads files either.
  - Embedded players (a YouTube or SoundCloud embed on another site) are captured
    too. If two players in different frames play at once, the one that started
    first is what goes out.
  - Limits: Qt's browser has no DRM (no Spotify / Netflix) and no H.264 (Twitch
    won't play). Media from another site without CORS plays, but only for you.
- **⚙ Settings:** themes (Dark, Light, Toxic green, Ocean; they switch live),
  hotkeys, overlay, window and audio options.

### How it works

```
🎤 your mic ── send ✓ / ✗ ──┐
                            ├─►  Soundboard mixes them  ─►  CABLE Input ═══ pipe ═══► CABLE Output
🔊 your sounds ─────────────┘                                                          (Discord / game mic)
```

The virtual cable is a free audio driver that works like a pipe: Soundboard plays
into one end, and Discord or the game uses the other end as a microphone. You hear
the sounds in your own headphones separately.

---

## Advanced (for developers and tinkerers)

Everything below is for building from source, changing the code or debugging.
You don't need any of it to use Soundboard.

### Install from source (any Windows PC)

1. Download or clone this folder.
2. Double-click **`install.bat`**. It:
   - finds Python 3.12+ (offers to install 3.13 with winget if you have none)
   - installs the Python packages into `.venv`
   - adds **Soundboard** shortcuts to the Desktop and Start menu
   - offers to install the free **virtual cable** (VB-Cable)
3. Open Soundboard. The setup guide (also under *Setup* → *Step-by-step guide*)
   tells you the one setting to change in Discord or your game.

#### The virtual cable

It's a free audio driver (VB-Audio Virtual Cable) that acts like a pipe: the app
plays into one end and Discord or the game uses the other end as a microphone.
It isn't included in this repo because VB-Audio's licence doesn't allow
redistributing it. `install-vbcable.ps1` downloads the current pack from
[vb-audio.com](https://vb-audio.com/Cable/), checks the installer is signed by
VB-Audio, and runs it. Windows asks for admin permission. The app's *Install the
free virtual cable* button runs the same script. Other virtual cables
(VB-Cable A/B, Voicemeeter) are detected too.

Optional: `winget install Gyan.FFmpeg.Essentials` adds m4a/aac/video support (the
installer's *Play M4A, AAC and video files* box runs the same command). The app
finds ffmpeg on `PATH` or in winget's `Links` folder.
Settings and imported sounds live in `%APPDATA%\Soundboard\`. Its `cache\` folder
holds each sound decoded and ready to play (int16 at 48 kHz), so later starts don't
decode anything; it's safe to delete and is rebuilt as needed.

### Code layout

Run from source with `run.bat` (or `python -m soundboard`); `main.py` at the root is
the launcher the shortcuts and PyInstaller use. The app is the `soundboard` package:

| file | what it does |
|---|---|
| `soundboard/__main__.py` | `python -m soundboard` |
| `soundboard/app.py` | entry point: log file, crash hooks, runtime tuning, single instance, the window |
| `soundboard/singleinstance.py` | named mutex + local socket so a second launch just raises the first |
| `soundboard/ui/mainwindow.py` | the main window: pads, transport, tabs, the audio panel, test mode, auto push-to-talk |
| `soundboard/ui/widgets.py` | hand-painted widgets: meter, EQ curve, seek slider, pads and their grid |
| `soundboard/ui/panel.py` | volume boxes and the equalizer panel (emit values; the window applies them) |
| `soundboard/ui/dialogs.py` | per-sound Edit dialog: the Sound tab (name, volume, hotkey…) and the Effects tab |
| `soundboard/ui/linkbar.py` | the Sounds tab's link bar: a link pasted into *Search sounds* is looked up with yt-dlp, then added as a sound or played once |
| `soundboard/ui/speedpitch.py` | the live speed & pitch button and its popup (Sounds transport and Browser bar) |
| `soundboard/soundfx.py` | per-sound effects: speed / pitch (phase vocoder + soxr), EQ, boost, reverse and any voice effect, rendered off the audio thread; the presets |
| `soundboard/ui/icons.py` | the line icons, drawn in code and recoloured with the theme |
| `soundboard/ui/responsive.py` | small windows: what hides, in which order, as the window shrinks |
| `soundboard/ui/fit.py` | dialogs grow to fit their wrapped text instead of clipping it (`fit.watch(self)` in every dialog's `__init__`) |
| `soundboard/ui/setupwizard.py` | the first-run guide with Bun (mic, headphones, cable, Discord) and the Steam help |
| `soundboard/ui/bunnywidget.py` | Bun animated: bobs, blinks, talks along with your mic and throws music notes |
| `soundboard/ui/overlay.py` | the in-game overlay: a click-through panel of pads driven by number keys |
| `soundboard/ui/voicepanel.py` | the Voice tab: voice changer, text-to-speech, live voice-to-speech, add-ons list |
| `soundboard/voicefx/` | the voice-effect chain and the built-in effects (pitch, robot, radio, …) |
| `soundboard/speech/` | Windows text-to-speech (`tts.py`) and the live voice-to-speech client (`live.py`, `service.py`, `protocol.py`) |
| `soundboard/modules.py` | finds, loads and installs add-ons in `modules\` |
| `soundboard/ytdl.py` | the Browser tab's *Add as sound*: downloads the open video's audio with yt-dlp, and updates yt-dlp on request or opt-in (SHA-256-checked PyPI wheels in `%APPDATA%`, loaded ahead of the bundled copy by an import hook) |
| `soundboard/adblocker.py` | the Browser tab's ad blocker (EasyList / uBlock lists, refreshed every few days) |
| `soundboard/bunny.py` | Bun the mascot, drawn in code (setup guide and installer art) |
| `soundboard/winkeys.py` | global hotkeys (`RegisterHotKey`) and key presses (`SendInput`), no hooks |
| `soundboard/engine.py` | real-time audio: 3 WASAPI streams (mic in, cable out, headphones out), mixing, pause/seek, live speed / pitch, limiter, watchdog |
| `soundboard/eq.py` | 7-band biquad equalizer and presets |
| `soundboard/browser.py` | Browser tab: Qt WebEngine view; an isolated-world script in every frame taps page media with an AudioWorklet and streams 48 kHz int16 PCM over a loopback WebSocket (per-launch secret) into the engine; clip recorder |
| `soundboard/library.py` | decoding (bounded to 15 min), the int16 decoded-audio cache (plus each sound's rendered effects version), loudness levelling, duplicating a sound, imports and clips (FLAC), versioned config with backups |
| `soundboard/theme.py` | colour themes (tokens → stylesheet, also read by the painted widgets) and the logo |
| `soundboard/settings.py` | Settings window, global hotkey actions, hotkey capture dialog |
| `soundboard/wheelguard.py` | mouse wheel scrolls the page instead of changing sliders / dropdowns (installed per widget) |
| `soundboard/applog.py` | rotating log in `%APPDATA%\Soundboard\soundboard.log`; unhandled exceptions and Qt warnings land there (plus one dialog for a UI-thread crash). `SOUNDBOARD_DEBUG=1` for more |
| `soundboard/testcheck.py` | analysis for the Record-6s test (finds your voice in the output by cross-correlation) |
| `make_icon.py` | regenerates `soundboard.ico` (shortcut icon) from the logo in `theme.py` |
| `make_bunny.py` | renders the installer artwork from `bunny.py` (`--preview` for a sheet of poses) |
| `modules/` | add-ons shipped with the app: `retro-fx` (an effects module, the example to copy) and `live-voice` (a service module with its own Python environment) |
| `build.ps1`, `installer/` | the PyInstaller build and the Inno Setup installer |
| `install.bat`, `install.ps1`, `run.bat` | run from source: set up `.venv` and shortcuts, then launch |
| `install-vbcable.ps1` | downloads VB-Cable, checks its signature, installs it (used by the app and the installer) |
| `scripts/` | `check_sensitive.py` (secrets / personal-data scan, also the pre-commit hook) and `make_notices.py` (third-party licences for the build) |
| `tests/` | pytest suite: ring buffer, engine mixing/guards/watchdog, cache and imports, recorder, hotkey parsing, EQ, levelling, config, test analysis, the main window built on Qt's offscreen platform (no window, no devices, no hotkeys) including shrinking it, the overlay, setup guide, voice panel, speech and effects, per-sound effects (speed and pitch measured by frequency and length, every preset, the effects cache, the Edit dialog) and live speed / pitch, the ad blocker, and the browser tab end to end: a headless page's audio (top frame and iframe) reaching the engine through the worklet and socket, and its speed reaching every page |

Developing:

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest
```

`pyproject.toml` holds the package metadata (version comes from `soundboard/__init__.py`),
the ruff and pytest settings, and a `soundboard` GUI entry point for `pip install .`.

#### Building an .exe

`build.ps1` runs PyInstaller and produces `dist\Soundboard\Soundboard.exe` (one folder,
QtWebEngine included), then compiles `installer\Soundboard.iss` with Inno Setup 6
(`winget install JRSoftware.InnoSetup`) into **`dist\SoundboardSetup.exe`**, the one
file to hand out. It installs per user (no admin), adds the Desktop and Start menu
shortcuts and opens the app. Its *Pick what you want* page (Inno Setup tasks) covers
VB-Cable (downloaded and signature-checked by `install-vbcable.ps1`), FFmpeg via winget
(offered only when ffmpeg is missing and winget exists), the add-ons in `modules\`
(copied to `{app}\modules`; *live-voice* then runs its `install.bat --quiet` when
Python is present) and the Desktop shortcut. Silent installs use the defaults or the
previous install's choices. The installer artwork is Bun the mascot, drawn in code by
`soundboard/bunny.py` and rendered by `make_bunny.py` (`--preview` writes a sheet of
every pose). Settings live in `%APPDATA%\Soundboard\` either way.
Every `config.json` save keeps the last three good copies next to it
(`config.json.1` … `.3`); a damaged file is set aside as `config.json.broken-<time>` and
the newest backup is used, so the pad list is never silently reset.

#### Audio notes

- Sounds are held in RAM as int16 stereo at 48 kHz (half the size of float32; the
  engine scales them in the same multiply as the gain). Only the first 15 minutes of a
  file are ever decoded. Video, m4a, aac and wma imports are stored as FLAC of their
  audio rather than a copy of the source, so the library is small and stays playable
  without ffmpeg. Re-importing a file that's already in the library is refused by
  content fingerprint.
- **Per-sound effects are baked in ahead of time**, never run on the audio thread:
  the sound is rendered once in the background (the pad says *applying effects…*)
  and cached as `cache\<id>.<settings-hash>.npy`, next to the untouched original.
  Changing the effects renders a new version and the old one is pruned. Speed and
  pitch are independent: a soxr resample sets the pitch, then a phase vocoder with
  identity phase locking (phase from the mid signal, shared by both channels)
  stretches it to the length the speed asks for. *Tape mode* with no extra pitch is
  a pure resample. Voice effects run per channel in 2048-frame blocks, with room
  for echo / reverb tails, and a module effect that throws is skipped.
- **Live speed / pitch** (the `1x` buttons) works differently, because it has to be
  instant. Sounds are read at a fractional rate with linear interpolation (like a
  tape). A pitch shifter on the sounds bus (a crossfaded two-head delay line, 70 ms
  window) then puts the pitch back when *keep pitch* is on, and adds the pitch
  slider on top. Browser speed is the page's own `playbackRate` /
  `preservesPitch`, sent to every frame over the tap socket. Its pitch goes
  through the same shifter as it's fed to the engine.
- Browser recordings are spooled to a 16-bit WAV as they happen instead of growing in
  RAM, and the resampled copies kept for non-48 kHz devices are capped at 512 MB (LRU).
- Every device is opened at its **native** sample rate and resampled with soxr.
  Windows' built-in `auto_convert` resampler was measured garbling VB-Cable audio
  (about 70% junk), so it's never used.
- *Send my mic* off (sounds only) keeps the mic stream open, so the meter, the tests
  and live voice-to-speech still hear it; only its mix into the cable is skipped.
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
