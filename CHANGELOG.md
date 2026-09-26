# Changelog

## Unreleased

## 0.2.0 — 2026-09-26

### Added
- **Any window size.** The window shrinks down to 300 × 300 and stays usable:
  as it gets smaller, labels shorten, buttons drop to icons, the less-used controls
  tuck away (pad size, meters, extra volume boxes, quick links, then the mixer strip)
  and the Setup and Voice pages go to one column. Everything comes back as it grows.
  It used to stop at about 1070 px wide.
- The version is shown in the title bar.

### Changed
- **Add-ons always come with the app.** The retro effect and the live
  voice-to-speech add-on are part of every install, so the Voice tab always offers
  *Install speech recognition* and then *Start talking as the voice*. Before, the
  live-voice add-on was only there if its installer box was ticked, and otherwise the
  tab just said to put a folder you didn't have into the add-ons folder. The
  installer's box now means "set it up now" (it can also be done later from the tab).
- Python 3.12 or newer is needed to run from source or to set up live voice (the
  pinned numpy and SciPy need it); the docs and `install.ps1` said 3.11.

### Fixed
- **Browser tab stuck after switching sites.** With Lite on, clicking another site
  (say SoundCloud) while a YouTube video played left the page hidden behind the
  mini-player, and the stalled-playback watchdog then flashed it 2 px tall; clicks did
  nothing. Loading any new page now brings it back, and the watchdog only acts on a
  player that has actually loaded something.
- Numpad **+** can be used as a hotkey (it was saved under a name that couldn't be
  read back, so it silently never worked). A hotkey that can't be read is now listed
  as not working instead of being skipped.
- A settings file that is valid JSON but damaged no longer stops Soundboard from
  starting: the last good backup is used, and a damaged sound entry is skipped.
- The Record-6s test gives up with a message if the virtual cable's output goes away
  mid-test, instead of leaving the button disabled.
- Sounds added while the library was still loading at startup kept their decoded
  cache (it was pruned against the list from before they were added).
- The play / pause button takes the new theme's colour straight away.
- Closing the setup guide with X or Esc shows the devices picked in it in the
  Devices card (only *Finish* used to refresh them).
- Removing a sound also stops its headphone preview; quitting mid-recording no
  longer leaves `recording.tmp.wav` behind.
- The Setup tab's *Hotkeys & auto push-to-talk* button showed an underlined "a"
  instead of the "&".
- `pip install .` included only part of the package; `install.ps1` couldn't use a
  plain `python` when the `py` launcher was missing.

- **Restart only when the cable needs it.** After installing VB-Cable, Soundboard
  checks whether Windows has brought the CABLE devices up. Usually it has and you
  carry on; if Windows needs a restart first, the installer offers *Restart now*, and
  the setup guide shows a Restart button instead of offering to install the cable
  again (installing over a cable that's waiting for a restart is what VB-Audio warns
  against).
- **Sounds only.** The *send* box next to My mic (also in Settings → General and
  the setup guide's mic page) decides whether your voice goes out with the sounds.
  Unticked, others hear only the sounds; the mic stays open so the meter, the tests
  and live voice-to-speech keep working. The Record-6s test knows about it.
- **Installer: pick what you want.** A page of tick boxes: the virtual cable,
  M4A/AAC/video support (installs FFmpeg with winget, offered only when it's
  missing), the retro voice effect and live voice-to-speech add-ons, and a Desktop
  shortcut. The app also finds ffmpeg in winget's Links folder, so m4a works right
  after installing without a restart.
- **README:** a plain-English *Get started* section first; the technical details
  moved under *Advanced*.
- **Ad blocking in the browser tab.** Requests are filtered by Brave's adblock engine
  (new `adblock` dependency) using the EasyList, EasyPrivacy and uBlock Origin lists,
  which are downloaded in the background, cached and refreshed every four days. On
  YouTube a script strips the ad fields out of the player data, the same way uBlock
  Origin's json-prune scriptlet does. If an ad gets through anyway, it's muted, jumped
  to its end and skipped, so it never reaches your mic.
- Push-to-talk keys are injected with `SendInput` (modifiers and key in one call)
  instead of the legacy `keybd_event`. A hotkey another program owns is reported the
  moment registration fails (a signal from the hotkey thread) rather than on a timer,
  and a hotkey thread that fails to start is logged instead of silently ignored.
- A settings save that fails (disk full, antivirus lock) shows once in the status line
  instead of raising inside a timer. Closing the window stops the tick timers and any
  test-capture stream still open.
- **Package layout.** The code is now the `soundboard` package (`soundboard/ui/` for
  the window, widgets, dialogs and panel pieces; `main.py` stays as the launcher), with
  `pyproject.toml` (metadata, entry point, ruff and pytest settings) and `build.ps1`
  to make a self-contained `dist\Soundboard\Soundboard.exe` with PyInstaller.
- **Settings can't be lost.** `config.json` carries a version number and migrations,
  every save keeps the last three good copies, and a damaged file is set aside and the
  newest backup used instead of silently resetting to defaults. Sounds inside the
  library are stored by file name, so `%APPDATA%\Soundboard` can be moved or restored.
- **Browser audio path rebuilt.** Page audio is now captured by an AudioWorklet on
  Chromium's audio thread (ScriptProcessor stays as a fallback for pages whose CSP
  forbids it) and streamed to the app as raw 16-bit PCM over a WebSocket on
  127.0.0.1 with a per-launch secret: no more base64 inside JSON over QWebChannel,
  and no decoding on the UI thread. Embedded players in iframes are captured too
  (when two frames play at once the first keeps the mic until it goes quiet). Stop
  all pauses media in every frame. The mini-player is only polled while the tab is
  visible. The address bar accepts ports, paths and `localhost`.
- **Lighter UI.** The mouse-wheel guard is installed on the dropdowns, sliders and
  number boxes themselves instead of on the whole application, where it ran a Python
  call for every event of every object (mouse moves, paints, the web view's stream).
  The red mic-check banner pulses with an opacity animation instead of rewriting its
  stylesheet 30 times a second. Importing, reordering or deleting a sound updates the
  pad grid in place instead of recreating every pad. Sound lookups are a dict.
- **Faster starts, half the RAM.** Each sound is decoded once and kept in
  `%APPDATA%\Soundboard\cache\` as int16 at 48 kHz; after that a sound loads by reading
  one file instead of decoding and resampling. In memory a 4-minute song is 46 MB
  instead of 92. Orphaned cache files are pruned at start; the folder is safe to delete.
- Only the first 15 minutes of a file are decoded (a two-hour podcast used to be read
  in full and then cut). ffmpeg decodes get a 2-minute timeout instead of hanging the
  import forever.
- Importing a video (or m4a/aac/wma) stores a FLAC of its audio instead of copying the
  whole file into the library. Recorded clips are FLAC too (were float WAV, 4× bigger).
- Importing a file that's already in the library is refused ("already in your library
  as …") using a content fingerprint, including the same file twice in one drop.
- Browser **Record clip** spools to disk as it records instead of holding up to 700 MB
  of chunks in RAM at the 15-minute cap.
- Resampled copies for devices not at 48 kHz are now an LRU cache capped at 512 MB.
- **Log file**: `%APPDATA%\Soundboard\soundboard.log` (rotating). Unhandled exceptions,
  worker-thread errors and Qt warnings all land there; a crash on the UI thread also
  shows one dialog with the path. Previously, under `pythonw.exe`, they vanished.
- **Audio streams are self-healing**: a callback that stops (headset unplugged, sample
  rate changed in Windows, PC back from sleep) is detected within about a second and
  the stream reopened; a device that failed to open is retried every 5 s. An exception
  inside an audio callback no longer kills the stream: it's logged once, the block is
  silent, and audio continues.
- **Drop-outs are counted** (from the driver's own underflow/overflow flags) and shown
  in the status line and in Settings → General. New **Audio buffering: Low / Safer**
  option for devices that crackle at low latency.
- The audio thread no longer waits on the UI: the voice list is an immutable snapshot
  (no lock in the callbacks), the interpreter's thread switch interval is 1 ms instead
  of 5, and the garbage collector runs far less often.
- Fixed: with no headphone device open, **Preview** in the Edit dialog played the sound
  out to Discord / the game.
- Fixed: the resampled-audio cache could serve a stale block if a freed array was
  reallocated at the same address (only when a device isn't at 48 kHz).
- Fixed: a hotkey of `ctrl++` (the + key) never parsed.
- EQ runs entirely in float32 (no per-block float64 round trip).
- Dependencies are pinned in `requirements.txt`; `requirements-dev.txt` adds ruff and
  pytest. New `tests/` suite (66 tests, no audio device needed) and `ruff.toml`.

- **Browser hotkeys** (global, work in-game): record start/stop (Ctrl+Alt+R), save
  the last 15s (Ctrl+Alt+C), play/pause (Ctrl+Alt+P), LIVE on/off (Ctrl+Alt+L).
  Record/save hotkeys confirm with a short beep in your headphones only.
- **⚙ Settings window** (top right) with every hotkey in one place, themes and window
  options. Giving a key to one action takes it off any other action or sound.
- **Themes**: Dark, Light, Toxic (green) and Ocean (blue). They switch instantly and
  are remembered.
- **New logo**: a microphone whose head is an equalizer, on a gradient. Shown in the
  header (in the theme's colours), the taskbar and the shortcuts (`make_icon.py`
  regenerates `soundboard.ico`).

- **🍃 Lite mode** for the Browser tab (on by default), to keep it light while you
  play. When something starts playing, the page is swapped for a small player (title,
  time, ⏪10s ⏯ 10s⏩ ⏭), so nothing is drawn or decoded as video, and YouTube drops to
  144p. **Show page** brings the page back to pick something else. Measured on an HD
  video: browser CPU roughly halved (40% → 20% of a core), audio unchanged.

- Opening the Browser tab no longer makes the window vanish and reappear. The window
  is now GPU-rendered from the start (`QT_WIDGETS_RHI`), so Qt doesn't have to
  rebuild it when the browser first appears.
- The "Only me — click to go live" button label is no longer cut off.

- Only one Soundboard can run. Opening it again brings the existing window to the
  front instead of starting another copy (repeated launches had piled up dozens of
  `pythonw.exe` processes). The lock is a named mutex, which Windows frees if the app crashes.
- Browser → mic no longer stutters every few seconds. Chromium's audio clock and the
  output devices' clocks drift apart, so the browser buffers now track the drift
  (speed nudged by at most 2%, no clicks) instead of running dry.
- Quiet passages in browser audio are streamed too, so sound after a pause in the
  video isn't delayed by re-buffering.

## 0.1.0 — 2026-09-26

First version.

- Sound pads with import (button, drag-and-drop, folders), search, reorder, colours, sizes.
- Per-sound hotkeys, volume, loop and press modes (restart / overlap / toggle).
- Global hotkeys use Windows' `RegisterHotKey`, so they never sit in the input path
  (no stuck keys or input freezes). Warns when another program already owns a hotkey.
- Mixes mic + sounds into a virtual cable at each device's native rate, with soxr resampling.
- Works on any setup: virtual cables (VB-Cable, A/B, Voicemeeter) are detected and
  paired automatically, and the card shows the real device names. With no cable, a
  one-time setup step offers an Install button.
- `install.bat` / `install.ps1`: one-click setup (Python, packages, shortcuts, virtual
  cable). `install-vbcable.ps1` downloads VB-Cable from the official site and checks its
  signature before running it.
- **Browser → mic** tab: a built-in browser whose audio goes live through your mic
  (LIVE toggle, own volume, hear-it-myself). **Record clip** and **Clip last 15s** turn
  what played into new sound pads. Stop all pauses it, and auto push-to-talk covers it.
- Headphone monitoring, loudness levelling, soft limiter.
- Transport bar: play/pause, stop, seek.
- Global stop-all and pause-all hotkeys, auto push-to-talk. Push-to-talk always releases
  the exact key it pressed.
- Volume controls with plain-language labels and typed % (up to 1000%).
- 7-band EQ for voice, sounds or both, with presets.
- Test mode: live mic-output monitor with red banner, and a 6-second record/playback
  check of the real cable output that reports voice/sound presence and balance.
- Simple main panel with a plain-English "How it works" card. Devices, sound options,
  EQ and hotkeys sit under a collapsible ⚙ Advanced section.
- The mouse wheel scrolls the panel and never changes dropdowns, sliders or number boxes.
- Virtual cables are excluded from the mic list, which prevents a feedback loop.
