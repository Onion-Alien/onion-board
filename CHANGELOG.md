# Changelog

## Unreleased

## 1.2.1 — 2026-09-27

- **Installing an update while Onion Board is open works.** The installer's
  request to close the app used to just hide it to the tray, so setup stopped
  with "unable to close all applications". It now closes properly (logging off
  or shutting Windows down with the app open is handled the same way).
- **Custom destination modes: the form works straight away.** With no custom
  modes yet, its fields ignored clicks and typing until you pressed *Add*. Now
  the first thing you type makes the mode.

## 1.2.0 — 2026-09-27

- **New Triggers tab: play a sound when something shows up on your screen.**
  Give it a picture (paste one cut with Win+Shift+S, or pick a file), for example
  a game's "YOU DIED", and the sound to play. It plays straight away or after a
  wait you set, once per appearance, with a cooldown and an adjustable match
  level that shows the live match next to it. Checks every 100 ms by default
  (down to 16 ms). It sees fullscreen games too, and transparent parts of a
  picture (a cut-out icon) are ignored, so it matches whatever is behind them.
  Watching is remembered, so it carries on next time the app opens.
- **Who's listening is on the Setup tab.** The Discord / Steam / game voice modes
  (and *Custom modes…* for any other codec) were only in Settings → General; they
  now have their own card under Devices. Settings keeps a copy, and the two stay
  in step.

## 1.1.0 — 2026-09-27

- **Installing the virtual cable no longer takes over your speakers.** Windows
  often makes "CABLE Input" the default speakers (and "CABLE Output" the default
  mic) when the cable installs, which silenced the PC until you switched back by
  hand. The installer now remembers your defaults and puts them back.
- **Two new themes:** Cherry Blossom (light sakura pink) and Carbon (graphite grey
  with a carbon-fibre weave).
- **Uninstalling offers to remove the cable again after a reinstall.** The installer
  now asks Windows whether a cable is really there instead of looking for files VB-
  Audio's uninstaller leaves behind, so it remembers when it was the one that
  installed the cable.
- **A much smaller download.** The build now leaves out the parts of Qt the app
  never uses (QML, 3D, charts, Chromium's developer tools, translations) and
  compresses harder: about a third of the previous installer size, and the
  installed app is about 60% smaller. Every build proves the trimmed app still
  starts (`OnionBoard.exe --selftest`, headless) before it's packaged.
- **Less CPU while hidden.** In the tray or minimised, the window's 30-a-second
  meter and visualiser timer slows to 4 a second (push-to-talk, the device
  watchdog and the test recording carry on as before), and the Programs tab
  re-reads the audio sessions every 5 s instead of every 1.5 s.
- **Nothing pops up over your game.** A crash report for an error that didn't stop
  the app waits until Onion Board is in front again instead of appearing over
  whatever you're doing, and the "settings were restored" notice waits for the
  window to be opened when the app started hidden in the tray.

## 1.0.0 — 2026-09-27

The first public release, as **Onion Board** (it was called Soundboard). Your
sounds and settings move over by themselves the first time it starts.

- **New licence: MIT with the Commons Clause.** Still free to use (streams and
  videos included), copy, change and share, but not to sell. 0.1.0 and 0.2.0
  stay plain MIT.

- **Uninstalling asks whether to remove the virtual cable too** (Yes by default
  only if Onion Board installed it; say No if another program uses it).
- **Settings → General → Support Onion Board** opens the project page's Support
  section, if you'd like to chip in.

### Security and fixes from the pre-release audit

- A pasted Myinstants link could write a file outside the download folder, and
  the clean-up afterwards could delete that folder. Link file names are now
  sanitized, and only the app's own temp folders are ever deleted.
- Names that come from the web (video and channel titles, radio stations, window
  titles) and your own sound names are shown as plain text: before, text that
  looked like HTML was drawn as HTML, which could load pictures from other PCs.
- Upgrading from Soundboard 0.1.0 no longer loses every sound, and the data
  folder still moves over if the installer already made the new one.
- Importing a backup or sound pack: bad numbers are ignored, the total size and
  your free disk space are checked first, and imported speech settings only
  accept the app's own models.
- If `config.json` goes missing, it's restored from its automatic backups.
- The virtual-cable installer unpacks into a folder only admins can write to
  and checks VB-Audio's certificate by name.
- Radio stations that point into your own PC or home network are skipped.
- A sound can no longer get stuck "playing" (holding push-to-talk down) when
  an audio device drops out; after Windows restarts a stalled device, sounds
  that were playing carry on through it instead of going silent there.
- Turning pitch or speed on while a sound plays no longer cuts out for a moment.
- "&" in a sound or category name no longer creates a hidden keyboard shortcut.
- The Radio, Voice and Apps tabs stop their meters while you're on another tab,
  so the app idles more quietly on a laptop battery.
- Text-to-speech works on Windows set to other languages, and installing voices
  works when your Windows user name has an apostrophe in it.

### Everything else new since 0.2.0

- **The Browser tab is gone; search the web from the Sounds tab instead.** Its
  audio stuttered, the page hitched when switching modes, and it cost the game
  a whole Chromium. Type in *Search sounds* and press Enter (or *Search*): the
  results replace the pads, and the **YouTube** / **SoundCloud** buttons above
  them switch sites. *Play* plays a result once, *Add* keeps it as a pad — only
  the audio is downloaded. TikTok, Instagram, X, Reddit and the rest have no
  search without an account, so paste a link to the video instead. The
  Browser hotkeys (record, last 15 s, play / pause, LIVE) went with it; the
  Radio tab keeps its own *Record* and *Last 15s*.
- **Pick several pads at once.** Ctrl+click adds or removes a pad, Shift+click
  picks a range, Ctrl+A picks everything showing, Esc clears. A bar under the pads
  (or right-clicking a picked pad) changes them all: colour, volume, fades,
  categories, export, or *Delete* — one *Undo* brings them all back.
- **Fade in / fade out per sound.** *Edit…* → *Fade in* / *Fade out* (up to 10 s).
  Stopping a sound fades it out instead of cutting it, and one that isn't looping
  fades over its last seconds. *Stop everything* still cuts straight away.
- **A "play a random sound" hotkey.** Settings → Hotkeys: plays a random sound from
  the category showing, never the same one twice in a row. Each category can have
  its own (right-click its tab → *Set a random-sound hotkey…*).
- **Remote control for Stream Deck and scripts (opt-in).** Settings → General →
  *Remote control* starts a small API on `127.0.0.1`: `/api/play?name=Airhorn`,
  `/api/random?category=Memes`, `/api/stop`, `/api/pause`, `/api/sounds`… Every
  request needs the key shown there. Works with a Stream Deck's API-request /
  website buttons, Bitfocus Companion, Touch Portal, AutoHotkey or `curl`.
- **Screen readers.** Pads are real buttons now: a screen reader reads each
  sound's name, then whether it's playing, its hotkey, length and categories.
  Tab and the arrow keys move between pads, Enter or Space plays, Ctrl+Space
  picks, the Menu key opens a pad's menu. Icon-only buttons (■, ✕, ⚙…) get names
  from their tooltips.
- **Trim a sound.** Right-click a pad → *Effects…* → *Trim*: drag the start and
  end handles on the waveform (or type exact times) and only that part plays —
  keep one line out of a 4-minute video. It's stored with the sound's effects, so
  the file is never cut and *Keep all* undoes it at any time. Presets keep the trim.
- **Categories.** Tabs above the pads (*+ Category*); a sound can be in several
  (right-click a pad → *Categories*). Search finds category names too. The in-game
  overlay shows the same category, and **R** (numpad **\***) switches category
  from inside the game.
- **Remove can be undone.** No more "Are you sure?": *Removed “…” · Undo* stays
  up for 10 seconds, and afterwards the audio file goes to the Recycle Bin
  instead of being deleted.
- **Backup, move to a new PC, share.** *Backup → Export everything* writes every
  sound (with its picture, effects, hotkey and categories) and your settings to
  one `.zip`; *Import…* (or dropping the zip on the pads) brings it back on any
  PC. Categories and single pads export as sound packs; importing skips sounds
  you already have, and a backup's settings are only used if you say so (your
  devices are never touched). The format is documented in
  `docs/BACKUP-FORMAT.md`.
- **Keeps running in the tray.** Closing the window no longer stops your hotkeys:
  the app stays in the tray (right-click → *Quit* to exit; switch it off in
  Settings → General). New: *Start with Windows*, straight to the tray.
- **Update check (opt-in).** Settings → General → *Tell me when a new version is
  out* asks GitHub once a day and shows an *Update* button when there is one. It
  never downloads anything itself; *Check now* works without the opt-in.
- **When something breaks, you can tell us in two clicks.** Any error the app
  didn't expect — on any thread, not just the window's — now opens a *hit a
  problem* window with the full report: what failed, where, and the last lines
  of the log, with your Windows user name and folders already blanked out.
  *Report on GitHub* copies it and opens a new issue for you to paste into;
  *Copy report* lets you send it any other way. Nothing is sent by itself. The
  same bug won't pop up twice, and a report is kept in
  `%APPDATA%\OnionBoard\crash-reports\` (last 10). If the app can't start at
  all, it now says why instead of silently not appearing.
- **Who's listening (Settings → General).** Voice chat runs your sounds through
  a mono voice codec. Measured: it drops the sub-bass under 100 Hz everywhere,
  and Steam voice cuts everything above 12 kHz (some game codecs above 8 kHz);
  100 Hz–6 kHz gets through untouched. Pick where your sounds are going —
  Discord, Steam voice, game voice, low-bandwidth game voice — and they're
  shaped to survive it: the bass that would be lost becomes harmonics the codec
  keeps, the level is evened out for the service's gate and auto gain, what
  you monitor is what they hear. *Custom modes…* describes any other service by
  the same knobs. Off (the default) sends sounds exactly as mixed. For
  developers, `scripts/codec_bench.py` is the measuring tool behind it.
- **Apps tab: send one program's sound through your mic.** Pick any program
  that's playing — a music player, a browser, a game, even a call in another
  app — and its sound goes out to whoever's listening, on its own volume, without
  touching anything else you play. It's a copy: the program keeps playing on your
  speakers as before. Each program has **Send**, a volume and *Hear it myself*;
  programs you switch on are remembered by their .exe and picked up again next
  time they run. Auto push-to-talk counts them, and Stop all switches them off.
  Uses Windows' per-process loopback (Windows 11, or Windows 10 build 20348+).
- **Fewer restarts after installing the virtual cable.** If Windows says the new
  cable needs a restart, the installer first tries to wake it without one:
  it restarts the cable's devices and the Windows audio service, then waits
  longer for it to come up. You only get asked to restart if that fails too.
  It now asks for permission once, up front. In the setup guide, **Install it
  now** sets Bun off: he dashes away, there's a cartoon dust cloud, and he comes
  back with a hammer and a plank and builds while a checklist shows each step
  (downloading, installing, checking, waking it up). If Windows still wants a
  restart, restart whenever suits you: after you next log in, Onion Board opens
  by itself (once) on the cable step. Bun welcomes you back when it's working,
  or you can **try once more without restarting**. This uses a per-user RunOnce
  entry, so there's no background task and nothing is left behind.

- **Renamed to Onion Board.** Was Soundboard. `%APPDATA%\Soundboard` is migrated
  to `%APPDATA%\OnionBoard` automatically on first launch (settings, sounds,
  cache, browser profile — nothing is lost). The exe, log file name, debug env
  var (`ONIONBOARD_DEBUG`) and app identifiers changed to match.

- **Radio tab.** Listen to ~60 000 internet radio stations from around the world
  (the free, open [Radio Browser](https://www.radio-browser.info) directory). A 3D
  globe shows the most-listened ~3000 as dots: spin it, hover for the name, click
  to tune in. Or search by name, genre or country. Stars keep your favourites.
  The radio has its own volume, *Hear it myself* and **LIVE** (off every launch),
  so it can go out through your mic like a sound, and *Record* / *Last
  15s* turn it into pads. Stop all stops it too, and auto push-to-talk counts it.
  Hovering a dot shows a card with the station's country and region, genres,
  language, audio quality, plays today (and the trend), votes and when it was last
  checked working. Zoom with the scroll wheel, Ctrl +/− or the corner buttons;
  ☾ / ☀ switches between the daytime Earth and the city-lights night view.

- **Voice changer voices rebuilt.** The pitch shifter is now a WSOLA splice
  shifter (the SoundTouch approach) instead of a two-head delay line, so Chipmunk,
  Deep voice and Demon no longer warble; Robot is a 16-band vocoder (words on a
  synth buzz) instead of a ring modulator; the reverb is a damped Freeverb that no
  longer rings like a pipe or piles up bass. New building blocks: Compressor,
  Tone (bass / presence / treble) and Chorus, and Echo repeats can darken. The
  voices are now Chipmunk, Deep voice, Demon, Robot, Alien, Ghost, Walkie-talkie,
  Old telephone, Megaphone, Stadium announcer, Cave and Podcast voice, each
  levelled to come out about as loud as your real voice. Pitch latency is ~50 ms.
- **Pictures on pads.** A sound added from a link (YouTube, TikTok, SoundCloud…)
  gets the video's thumbnail; an imported mp3/m4a/video gets its cover art or
  first frame (with ffmpeg). Right-click a pad → *Add picture…* to pick any image,
  or drop an image file onto a pad; *Remove picture* takes it off.
- **Pads show what's playing.** A playing pad now has a live spectrum
  visualizer (bars that bounce with the sound, with falling peak caps), a thin
  progress line along the bottom and a glowing border, instead of a flat fill.
- **The computer voice speaks other languages.** *Speak in* on the Voice tab: talk
  in English and the voice says it in Chinese, Spanish, French, German or Russian.
  Each language is an add-on you download only when you pick it (65–195 MB, an
  offline Argos Translate model), so translation runs on your PC and what you say
  never leaves it. It uses that language's Windows voice, and tells you how to add
  one if it's missing. Existing live-voice installs need *Update speech
  recognition* (More options) once, for the translation tokenizer.
- **More Windows voices.** Text-to-speech now also finds the newer Windows voices
  (Mark, George, Susan… and any language voice you add in Windows settings), not
  just the classic desktop ones.
- **Add or play a sound from a link.** Paste a link into *Search sounds* on the
  Sounds tab (YouTube, SoundCloud, TikTok, X, Reddit, direct audio/video links and
  most other media sites, via yt-dlp). It's looked up and shows its title, then
  **Add as sound** (or Enter) downloads its audio into your Sounds, and **Play
  once** plays it through your mic without keeping it. Adding after playing reuses
  the same download.
- **Effects on any sound.** Right-click a pad → *Effects…* (or the new *Effects*
  tab in *Edit…*) to change its speed and pitch (separately, or together with
  *Tape mode*), EQ, boost (up to +36 dB, which clips on purpose), play it backwards,
  or add any voice effect (echo, reverb, distortion, radio, robot, add-on effects).
  Presets include **Ear rape**, Bass boosted, Slowed + reverb, Nightcore, Chipmunk,
  Demon and Reversed. *Preview* plays it to you only. *Save* changes the pad, and
  *Save as new sound* keeps the original and adds the edited version as its own
  pad. The original file is never touched, and pads with effects show **FX**.
- **Speed and pitch while you listen.** A `1x` button on the Sounds transport
  slows down or speeds up (0.25×–2×) and shifts the pitch (±12 semitones) of
  whatever is playing, keeping the pitch when the speed changes or not. It isn't
  saved; use Effects to keep a version.

- **Voice tab redesigned so it's obvious how to use it.** The voice changer comes
  first: one big switch (green when on: everyone hears your changed voice), a grid
  of voices to click (Chipmunk, Robot, Old telephone…; clicking one turns it on), a
  *Hear my voice* button and a mic meter right there, and the individual effects
  folded under *Fine-tune effects*. It says plainly that there's nothing to start:
  it works on your mic whenever it's on. Live voice-to-speech is now *Talk as a
  computer voice*, with its rarely-changed options under *More options*.

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
