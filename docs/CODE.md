# How Onion Board works inside

For people changing the code. Using the app needs none of this: the
[README](../README.md) covers that. The edit → check → build → release loop is in
[DEVELOPING.md](DEVELOPING.md); the rules are in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Sending sounds to others: straight into your mic, the virtual cable, or something else

Setup → Devices → *Send my sounds to* (also Settings → Audio → Devices) picks
the route (`Config.route`, `library.ROUTES`):

- **Straight into my mic** (new users start here, `Config.first_start`): Onion Board
  puts a small Windows audio effect on the real mic (`native/directmic/obmic.cpp`, an
  "APO" like Equalizer APO's, built with MinGW by `scripts/build_directmic.py`), so
  Discord and games hear the sounds through the mic they already use. Soundpad works
  the same way. One admin prompt sets it up (`main.py --direct-mic install <endpoint>`,
  `soundboard/directmic.py`'s admin part): the DLL goes to `Program Files\Onion Board
  Mic`, is registered, and takes the mic's stream-effect slot (SFX; Windows runs only
  stream effects in front of each app's recording, after the mic's own endpoint
  effect). An effect the driver had in that slot is saved and run first, inside ours.
  Every value changed is noted under `HKLM\SOFTWARE\OnionBoard\MicPlugin`, before
  anything changes and kind for kind, so `--direct-mic uninstall` (and the
  uninstaller's `--direct-mic remove`) puts the mic back exactly, even after a set-up
  that was killed half-way. If Windows already took the effect off (a driver update,
  "Reset sound settings"), what the driver put there stays and only the notes go. The
  admin step stops Windows' audio for a moment; a helper started first brings it back
  whenever that process ends, killed or not.

  Board ↔ effect: `%ProgramData%\OnionBoard\MicPlugin\ring2.bin`, a shared file
  (layout in `directmic.py`'s docstring). The effect publishes the **clean mic**
  (before anything of the board's) and the board takes its mic from there: the meter,
  mic check, OBS voice and voice changer never hear its own sounds come back. For each
  stretch of clean mic the board renders the same stretch of what others hear
  (`DirectMicStream`, on the mic's clock: no drift), and in *replace* mode (the
  default) the effect puts that whole send mix, processed voice included, in place of
  the mic about 20 ms later, so every mic feature works as with the cable. Each app
  recording the mic runs its own instance with its own slot in the file. When the
  board is late with a block (a busy PC) the effect fills the gap with the clean mic
  from the moment that block would have been made from (the board publishes a sync
  pair, ring frame -> mic frame, minus its own voice delay), so the voice goes on
  without a skip or a repeat, at the board's mic level (muted stays muted; a changed
  voice goes quiet rather than let the real one out). When it's gone the plain mic
  fades back in. After a hiccup the effect reads a little further behind the board
  (stepping back where it's quiet), and closes that gap again in a quiet moment once
  the board keeps time. A mic at another rate
  than 48 kHz gets the board's mix through a windowed-sinc resampler (no fold-back of
  the highs on 44.1 / 16 kHz mics). Only one board writes the file at a time
  (`board_pid`: a second copy of the app says so instead). Nothing read from the file
  is trusted (anyone signed in can write it); `test_effect_survives_a_fuzzed_ring`
  checks that.
  `directmic.status()` notices a mic Windows took the effect off ('wiped') or one with
  an older copy of it ('outdated'); the Setup tab offers a one-click repair, or the
  cable. Tests run the real DLL in `testhost.exe`, which loads it the way Windows does.
- **The virtual cable** (the fallback). Settings on the cable route moved to the mic
  route once in 1.9.1 (`Config.mic_first`); a route picked after that stays. While the
  mic isn't set up yet the mic route sends through the cable, and once it is, the
  cable still gets the same mix (`engine.CableTap`, drift-tracked onto the cable's
  clock), so a voice app still set to the cable keeps working. The cable itself is a
  free audio driver (VB-Audio Virtual Cable) that acts like a pipe: the app plays into one end and Discord or the game uses the
  other end as a microphone. It isn't included in this repo because VB-Audio's
  licence doesn't allow redistributing it. `installer\install-vbcable.ps1` downloads
  the current pack from [vb-audio.com](https://vb-audio.com/Cable/), checks the
  installer is signed by VB-Audio, and runs it. Windows asks for admin permission.
  The app's *Install the free virtual cable* button runs the same script. Other
  virtual cables (VB-Cable A/B, Voicemeeter) are detected too.
- **Another device** (`device`): any output you pick by name (Voicemeeter, a mixer, a capture
  card, a second sound card, an output OBS captures). No cable is needed, the app
  never swaps the cable in or asks to install it, and the send device can't be the
  headphones.
- **Nobody** (`off`): only you hear the sounds, plus the optional stream output.

The route belongs to this PC: backups don't carry it and resetting the audio devices
puts it back to straight into the mic. The rest of this page says "what others hear" for
whichever of these the route picked.

Optional: `winget install Gyan.FFmpeg.Essentials` adds m4a/aac/video support (the
installer's *Play M4A, AAC and video files* box runs the same command). The app
finds ffmpeg on `PATH` or in winget's `Links` folder.

## Where things are stored

Settings and imported sounds live in `%APPDATA%\OnionBoard\`. Its `cache\` folder
holds each sound decoded and ready to play (int16 at 48 kHz), so later starts don't
decode anything; it's safe to delete and is rebuilt as needed. The `icons\` folder
there holds the app icon in each theme you've used, which the app's own Desktop and Start
menu shortcuts point at (a reinstall resets them; the next start re-themes them).

## Code layout

Run from source with `scripts\run.bat` (or `python -m soundboard`); `main.py` at the root is
the launcher the shortcuts and PyInstaller use. The app is the `soundboard` package:

| file | what it does |
|---|---|
| `soundboard/__main__.py` | `python -m soundboard` |
| `soundboard/app.py` | entry point: log file, crash hooks, runtime tuning, single instance, the window |
| `soundboard/singleinstance.py` | named mutex + local socket so a second launch just raises the first |
| `soundboard/ui/mainwindow.py` | the main window: pads, transport, tabs, the audio panel, test mode, auto push-to-talk |
| `soundboard/ui/widgets.py` | hand-painted widgets: meter, EQ curve, seek slider, pads (picture, spectrum visualizer while playing) and their grid |
| `soundboard/ui/panel.py` | volume boxes, the equalizer panel (emit values; the window applies them) a wrapping row layout (`Flow`) and a grid of equal-width cards (`CardGrid`) |
| `soundboard/ui/dialogs.py` | per-sound Edit dialog: the Sound tab (name, volume, hotkey, fades…) and the Effects tab |
| `soundboard/ui/padbatch.py` | picking several pads (Ctrl / Shift+click, Ctrl+A) and changing them together: delete with one Undo, colour, volume, fades, categories |
| `soundboard/ui/busy.py` | click feedback for buttons: a greyed-out *Scanning…* while the work runs, then a short *✓ done* on the button (`run_busy`, `hold`, `flash`) |
| `soundboard/ui/a11y.py` | screen-reader names for icon-only controls, taken from their tooltips as the focus moves |
| `soundboard/ui/quietbox.py` | no Windows "ding" from information/warning message boxes (same picture, shown as a pixmap); only critical errors keep their sound |
| `soundboard/ui/weblinks.py` | web links (http/https/mailto) open through a helper started with the user's own environment, so a browser the app starts doesn't inherit the relay's proxy variables |
| `soundboard/shuffle.py` | the random-sound hotkeys' shuffle bag (every sound once before repeats, never twice in a row) |
| `soundboard/remote.py` | opt-in local control API for Stream Deck / scripts: HTTP on `127.0.0.1`, token-guarded, answered on the UI thread; also writes the AI setup prompt. With `lan=True` it's the server "remote" add-ons (Onion Pocket) get: local-network peers only, wrong keys locked out, never on a network Windows calls Public |
| `soundboard/netcategory.py` | whether Windows calls the network an address is on Public / Private / Domain (Network List Manager over COM, no admin), so the phone remote never listens on a café's Wi-Fi |
| `soundboard/ui/remotehost.py` | Onion Board as the host of a "remote" add-on such as Onion Pocket: its settings (never in a backup), a lan server offering a list of actions, and Settings' look for its card on Settings → Remote |
| `soundboard/ui/linkbar.py` | the Sounds tab's link bar: a link pasted into *Search sounds* is looked up with yt-dlp, then added as a sound or played once |
| `soundboard/ui/ytsearch.py` | the Sounds tab's web search: Enter in *Search sounds* shows YouTube or SoundCloud hits as a grid of cards (thumbnail, title, length) in place of the pads; *Play* / *Add* hand one to the link bar; the one in the player shows a bouncing equalizer and *Play* becomes *Pause* |
| `soundboard/ui/spacekey.py` | Space plays / pauses on the Sounds and Radio tabs wherever the focus is (not in text boxes, or on a button reached with Tab) |
| `soundboard/ui/speedpitch.py` | movable live controls windows: speed, pitch and effects for Sounds, and pitch and effects for Radio and Apps; the speed gauge turns red at 8x |
| `soundboard/livefx.py` | live effects on every playing sound (the speed & pitch popup): bass, treble, muffle, reverb, echo, distortion and presets; not saved |
| `soundboard/soundfx.py` | per-sound effects: trim, speed / pitch (phase vocoder + soxr), EQ, boost, reverse and any voice effect, rendered off the audio thread; the presets |
| `soundboard/i18n.py` | translations: `_()` / `ngettext()` look the English up in the language picked (`assets/lang/<code>.json`) and fall back to it; Windows' language, plural rules, the pseudo-language `xx` and `unwrapped_texts` for layout checks (see [TRANSLATING.md](TRANSLATING.md)); `scripts/i18n_extract.py` lists missing / unused texts |
| `soundboard/tips.py` | *Did you know?* tips: the list (each with where *Show me* goes), which one is due (after setup, once a day, never during a game), and the fullscreen-in-front check; the main window shows the bar |
| `soundboard/ui/recordmic.py` | the Sounds tab's *Record a sound* window: a mic take (`Engine.start_mic_take`) or what's playing (`Engine.start_play_take`: sounds + radio, no mic), spooled by `recorder.MicTake`, raw or through the voice changer, trimmed and added as a pad; not modal |
| `soundboard/catswitch.py` | Switch category when a program is in front: `Switcher.poll()` (one foreground lookup a second, only while a rule exists; back to the old category when the program closes) and the open programs for picking one (`windowed_programs`) |
| `soundboard/ui/programpick.py` | the program picker for a category's *Show this when a program is in front…* |
| `soundboard/ui/trim.py` | the Effects tab's trim control: waveform with start / end handles and exact-time boxes |
| `soundboard/backup.py` | export / import of the board as a plain zip (JSON + original audio + pictures), sound packs and single sounds; see [BACKUP-FORMAT.md](BACKUP-FORMAT.md) |
| `soundboard/otherboards.py` | Import from another soundboard: what the readers share (Entry rows, the list of sources, the installer's queued-import note); only when the user asks (Backup menu, setup guide, the installer's boxes, or a dropped board file) |
| `soundboard/soundpad.py`, `resanance.py`, `soundux.py`, `expboard.py` | the readers: Soundpad's `soundlist.spl` XML, Resanance's LiteDB 5 `Resanance.db` (read page by page, no LiteDB needed), Soundux's `config.json`, EXP Soundboard's board JSON (found through Java's Preferences in the registry) |
| `soundboard/autostart.py` | *Start with Windows*: the per-user `Run` registry value (`--tray` starts it hidden) |
| `soundboard/shellicon.py` | the app icon in the theme's colours outside its windows: writes `%APPDATA%\OnionBoard\icons\onionboard-<hash>.ico`, puts it on the main window's relaunch properties (taskbar right-click menu, a pin) and on this copy's own *Onion Board* Desktop / Start menu / taskbar-pin shortcuts |
| `soundboard/updates.py` | "is there a newer version?" (GitHub Releases, every 6 hours; an "Urgent: …" line in the notes gets a banner) and the self-update: downloads the release's installer, checks its SHA-256, runs it silently and reopens the app |
| `soundboard/feedback.py` | where *Join the Discord*, *Send feedback* and *Report a problem* (Settings → Add-ons & help, Settings → About, the tray menu) go: the Discord invite, a no-account form or a GitHub issue, opened in the browser with the version filled in; the app sends nothing |
| `soundboard/errors.py` | other libraries' errors (yt-dlp, libsndfile, PortAudio, Windows, network) in plain words, minus their "report this to us" lines and command-line tips; the original stays in the log and in the report. Ones the user can't fix get a *Report it* link/button: a pre-filled issue on this repo, opened in the browser |
| `soundboard/hangwatch.py` | notes down a frozen window: if the UI thread stops answering for 5 s, its stack goes into the log and a report beside the crash reports (nothing shown or sent) |
| `soundboard/uigc.py` | Python's garbage collection on the UI thread only: a collection on another thread could free a Qt object with a running timer there and crash the app |
| `soundboard/ui/icons.py` | the line icons, drawn in code and recoloured with the theme |
| `soundboard/ui/art.py` | optional pictures from `assets/art` (voice tiles, the computer voice, its languages); emoji / painted icons when missing |
| `soundboard/ui/responsive.py` | small windows: what hides, in which order, as the window shrinks |
| `soundboard/ui/fit.py` | dialogs grow to fit their wrapped text instead of clipping it (`fit.watch(self)` in every dialog's `__init__`) |
| `soundboard/ui/setupwizard.py` | the first-run guide with Bun (mic, headphones, where your sounds go: straight into your mic, or the cable or another way out, then Discord) and the Steam help |
| `soundboard/ui/bunnywidget.py` | Bun animated: bobs, blinks, talks along with your mic and throws music notes |
| `soundboard/ui/whatsnew.py` | the *What's new* window shown once after an update, with what the release added, a button to the settings it's about and a link to the Discord (`NOTES`, newest first: add one per release) |
| `soundboard/ui/splash.py` | The start-up splash: Bun and a spinner mid-screen while a cold start loads |
| `soundboard/ui/langpick.py` | the language picker (Settings → Appearance → Language): a window of language tiles, each in its own name, with a search |
| `soundboard/ui/sidebar.py` | the tab rail down the main window's left: one icon per tab, opened out to show their names (the tab widget's own bar is hidden) |
| `soundboard/ui/livedot.py` | marks a tab whose feature is live (a highlight-coloured icon, with the rail's bar beside it, or a small dot), e.g. the Voice tab while your voice is being changed |
| `soundboard/ui/logowidget.py` | the header logo animated: a breathing glow and sheen, flaring with embers while sounds play |
| `soundboard/ui/overlay.py` | the in-game overlay: a panel of pads that never takes focus, driven by number keys or clicks, on a chosen monitor and spot (or wherever it was dragged) |
| `soundboard/ui/voicepanel.py` | the Voice tab: voice changer, text-to-speech, live voice-to-speech, add-ons list |
| `soundboard/voicefx/` | the voice-effect chain and the built-in effects (pitch, robot, radio, …) |
| `soundboard/speech/` | Windows text-to-speech (`tts.py`), custom voices — local TTS servers, TTS programs, Piper packs (`customvoices.py`), the live voice-to-speech client (`live.py`, `service.py`, `protocol.py`) translation model downloads (`translation.py`) and one-click Windows voice installs (`winvoices.py`) |
| `soundboard/modules.py` | finds, loads and installs add-ons in `modules\`: effects, services, translations and the Triggers tab's package (its host interface version checked first); installs a module zip only if it stays in its own folder; at start-up deletes old and half-swapped add-on copies, keeping the newest per add-on and any in use |
| `soundboard/pocketaddon.py` | the Onion Pocket add-on (Settings → Remote → *Get Onion Pocket*): its latest GitHub release, downloading and checking it, installing it, and whether a newer one than the running copy is out (`check_update`, for the *Update Onion Pocket* button; `MainWindow.load_remote_addon` swaps it in); any failure is just `None` (`ONIONBOARD_ONION_POCKET_ZIP` uses a local zip instead) |
| `soundboard/firewall.py` | Windows Firewall rules for remote add-ons: Onion Board runs itself as admin (`--firewall-rule NAME PORT`, handled in `main.py`) so Windows' prompt names it |
| `soundboard/aiaddon.py` | the optional AI voices add-on: its `ai-voices` GitHub release, downloading and checking it, installing and removing it (`ONIONBOARD_AI_VOICES_ZIP` uses a local zip instead). Not shipped with the app or its installer |
| `soundboard/speech/aivoice.py` | AI voices in the mic chain: `VoiceSource` (`VoiceChain.source`: talk gate with pre-roll, jitter buffer, the backup voice if the helper stalls) and `AiVoiceController` (starts the helper: a `ServiceHost` with audio coming back) |
| `soundboard/ui/aivoicepanel.py` | the Voice tab's AI voices card: *Get AI voices*, install, pick a voice, pitch, start/stop, CPU readout, remove |
| `soundboard/ui/aivoicebrowser.py` | the AI voices card's *All voices* window (a card per voice: who it sounds like, how high, *Hear it*, *Use*) and the *Make your own voice* editor (blend two voices, deeper/brighter, how high) |
| `soundboard/speech/aivoicelist.py` | the AI voices to pick from: the built-in list (same as the add-on's `voices.json`), writing it and your own voices into the installed add-on (`sync`, so old downloads get new voices), and your own voices' file and bin (`%APPDATA%\OnionBoard\ai-voices.json`) |
| `soundboard/speech/aipreview.py` | *Hear it*: a Windows voice says a line, the add-on's converter turns it into the voice offline (its own Python, `-c`), kept for the run |
| `soundboard/watchaddon.py` | the Onion Watch add-on: its latest GitHub release, downloading and checking it, installing it, and whether a newer one is out (`ONIONBOARD_ONION_WATCH_ZIP` uses a local zip instead) |
| `soundboard/ytdl.py` | yt-dlp for the link bar and web search: searches YouTube / SoundCloud, downloads one video's audio, and updates yt-dlp on request or opt-in (SHA-256-checked PyPI wheels in `%APPDATA%`, loaded ahead of the bundled copy by an import hook) |
| `soundboard/thumbs.py` | pad pictures: a link's video thumbnail, a file's cover art / first frame (ffmpeg), or a picture you pick or drop on a pad, scaled into `%APPDATA%\OnionBoard\thumbs` |
| `soundboard/videos.py` | which pads came from a video (an imported video file, or a link added with *Also save the video*), in `videos.json` beside the config; `ui/videowindow.py` is the player's **Video** window, muted and kept in step with the pad's sound |
| `soundboard/savedvoices.py` | the voice changer's saved voices and their bin, in `%APPDATA%\OnionBoard\voices.json` (not the config, so older versions can't drop them), and their share codes (`OB1-…`: name + effect numbers, checked and clamped on import) |
| `soundboard/trash.py` | Recently deleted: removed sounds (files and pad) and forgotten programs, kept 30 days in `%APPDATA%\OnionBoard\deleted` so they can be brought back |
| `soundboard/reset.py` | Settings → General → Reset: puts the parts picked (settings, hotkeys, sounds, the bin, programs, devices) back to the start at the next launch, after saving a restore point in `%APPDATA%\OnionBoard\restore-points` that undoes it |
| `soundboard/bunny.py` | Bun the mascot, drawn in code (setup guide and installer art) |
| `soundboard/winkeys.py` | global hotkeys (`RegisterHotKey`, and when each is let go, for hold-to-play) and key presses (`SendInput`), no hooks |
| `soundboard/midi.py` | MIDI pad controllers as hotkeys (`midi:note 36:LPD8`): Windows' winmm over ctypes, a device opened only while a hotkey uses it, busy / unplugged devices retried |
| `soundboard/replay.py` | instant replay: process loopback of everything but Onion Board into a ring buffer, saved as a pad on its hotkey |
| `soundboard/appaudio.py` | the Apps tab's capture: lists the programs with an audio session (WASAPI sessions, over ctypes) and taps one program's audio with Windows' per-process loopback (a copy: the program still plays on your speakers), pushed into the engine as its own source |
| `soundboard/ui/triggerstab.py` | the Triggers tab: Hoot (`ui/owl.py`) and *Get Onion Watch* until the add-on is installed, then the add-on's own tab, with a bar when an update is out and a button to remove it |
| `soundboard/ui/taboff.py` | what stands in, hidden, for a tab switched off in *Settings → Tabs* (`Config.tabs_off`): the real Apps / Triggers / Voice tab is never built (Radio's stand-in is `RadioOff`) |
| `soundboard/ui/triggershost.py` | Onion Board as the Onion Watch add-on's host: the board's sounds and playing them (a ringing trigger loops in the headphones), `Config.screen`, the trigger pictures' folder, the theme's colours |
| `soundboard/ui/alsosend.py` | Setup → Devices → *Also send to* (`cfg.also_send`): a row per extra output with a − button, and **+ Add a device**; each gets a copy of what others hear (`Engine.set_copy_devices`, one `CableTap` each). Also built into Settings → Audio |
| `soundboard/ui/appspanel.py` | the Apps tab: one card per program (level, **Send**, where it goes once a stream output is set: call, stream or both, volume, *Hear it myself*, and its *Clip editor*); programs you switch on are remembered by .exe and folder (a second program of the same name gets its own card, in `cfg.apps_paths`) and picked up again when they run |
| `soundboard/directmic.py` | straight into my mic: the shared ring with the mic effect, `DirectMicStream` (the send output on the mic's clock), status / repair checks, and the one-prompt admin install / uninstall |
| `native/directmic/` | the mic effect (`obmic.cpp`, runs inside Windows' audio engine) and `testhost.cpp`, which loads it like Windows does for the tests; `fuzzhost.cpp` throws hostile ring files at it (`scripts/fuzz_directmic.py`) |
| `soundboard/engine.py` | real-time audio: WASAPI streams (mic in, what others hear out (your mic, the cable or another device), headphones out, the optional stream output for OBS), mixing (sounds, radio and captured programs), pause/seek, live speed / pitch, limiter, watchdog |
| `soundboard/eq.py` | 7-band equalizer and presets: matched peak / shelf bands that keep their analog shape up to Nyquist; a change crossfades in (no clicks) |
| `soundboard/dsp.py` | the app's own filter maths (it no longer imports scipy): `sosfilt` / `lfilter` run as block matrix products with a parallel prefix scan for the state (float64 state, so float32 audio stays accurate), Butterworth design, matched EQ bands, `SmoothSos` (click-free design changes), an O(n) running minimum |
| `soundboard/net.py` | every outgoing connection (Settings → Privacy & security): direct, or through a SOCKS5 / HTTP proxy with names resolved by the proxy and no fallback to direct; and the per-feature switches and Offline mode, which refuse a switched-off feature's requests before any lookup. `urlopen(feature=…)` for urllib, and a loopback relay (per-launch secret, the feature as its user name) for FFmpeg, yt-dlp, Qt's network managers and child processes, in every mode |
| `soundboard/netlog.py` | Connection → *Network activity*: every connection `net.py` makes or refuses (feature, why: the click or timer that caused it, server, route, result, bytes each way, request lines and TLS where the app can read them), in memory only unless *Keep a history* is on |
| `soundboard/ui/netactivity.py` | the *Network activity* view: Simple (one row per server) and Detailed (one row per connection, with everything about the picked one), Copy and Clear |
| `soundboard/tor.py` | the app's own Tor (Connection → *Tor*): starts `tor.exe` only when needed, writes its torrc in `%APPDATA%\OnionBoard\tor`, ties it to the app with a job object, speaks its control port (cookie auth, bootstrap progress, `NEWNYM`) and hands `net.py` its SOCKS port once connected; optional Snowflake / obfs4 bridges |
| `soundboard/torget.py` | *Get Tor* (Settings, and the installer's Tor box via `OnionBoard.exe --get-tor`): downloads the Tor Expert Bundle through `net.urlopen`, checks its pinned SHA-256 and unpacks only tor.exe, lyrebird, pt_config.json and the licences into `%APPDATA%\OnionBoard\tor\bin` (the app doesn't ship Tor) |
| `soundboard/quality.py` | Settings > Data & quality: download size, keeping the video, the radio's bitrate cap and patience, and web search extras (low data mode) |
| `soundboard/radio.py` | Radio tab back end: the Radio Browser directory client (stations, search, a day's cache), the stream player (Qt Multimedia decodes, a `QAudioBufferOutput` hands 48 kHz PCM to the engine; the decoder's DLLs preload on a thread when the tab first opens) and the map's land outlines (SHA-384-checked) |
| `soundboard/ui/radiopanel.py` | the Radio tab: search bar, the map (click a dot to play), station list, favourites, Send / record / last 15 s, the now-playing strip |
| `soundboard/ui/flatmap.py` | the Radio tab's world map, painted by Qt (no web engine) |
| `soundboard/ui/appstate.py` | stops decorative animations (logo, mascots, live dot) while another program is in front |
| `soundboard/ui/clipeditor.py` | the Apps tab's clip editor, folded away under each card until opened: the live waveform of the program's last minute, drag to select, play in your headphones / save as a sound / send out, the Edit menu and its keys |
| `soundboard/ui/clipshelf.py` | the Apps tab's *Saved clips* list under the cards: what the clip editor's Save keeps; double-click plays, F2 renames, right-click adds to Sounds / sends / copies / deletes (Undo bar) |
| `soundboard/clipshelf.py` | the saved clips without the window: FLACs in `%APPDATA%\OnionBoard\clips` and their `index.json`; deleted ones' files are tidied on the next start |
| `soundboard/clipedit.py` | the clip editor without the window: `LiveBuffer` (the last minute and its waveform, filled on the capture thread) and `Take` (cut, paste, fades, gain, reverse, with undo capped by memory) |
| `soundboard/recorder.py` | the Radio tab's clip recorder: a rolling last-15-seconds buffer plus a recording spooled to disk; `MicTake`, a mic (or what's-playing) recording spooled the same way (Record a sound) |
| `soundboard/mapped.py` | long sounds stay on disk: decoded cache files over ~30 s (or past a RAM budget) are memory-mapped, and warmed (first second read, the rest prefetched) before they play |
| `soundboard/library.py` | decoding (bounded to 15 min), the int16 decoded-audio cache (plus each sound's rendered effects version), loudness levelling, duplicating a sound, imports and clips (FLAC), versioned config with backups, saved on a background thread (`Saver`) so a slow disk never freezes the window |
| `soundboard/usage.py` | the anonymous usage count (*Count me in*, feature `usage_stats`): a daily "still here" to GoatCounter with the version and a random `stats_id`, a one-off first start (with the installer's *Where did you hear about Onion Board?* answer, tidied by `heard_tag`) and *Update now*; with the daily one the tabs opened (`stats_tabs`) and `about()`: age, route, sound and play buckets, language and the `FEATURES` used (`used()` → `stats_used`, kept at quit by `remember`); a new install's first `STEPS` once each (`step()`; `settle` marks them done for copies counted before); problem counts soon after a start (`crash/` `error/` `freeze/` per new report in `crash-reports\`, plus the error type and the deepest `soundboard/…py:line` of its stack (`_report_event`; never the message), past `stats_problems_seen`, and `unclean-exit/<version>/<why>` when `running.txt` was left by a run that never reached `mark_stopped`; the why from `exitwatch.py`); installed copies only, never from source. `--usage-count on/off` is the installer's box, `--uninstall-count` the uninstaller's `uninstall/<version>` |
| `soundboard/theme.py` | colour themes (tokens → stylesheet, also read by the painted widgets) and the logo |
| `soundboard/settings.py` | Settings window, global hotkey actions, hotkey capture dialog |
| `soundboard/wheelguard.py` | mouse wheel scrolls the page instead of changing sliders / dropdowns (installed per widget) |
| `soundboard/exitwatch.py` | a black box for the next start: `last-run.json` (heartbeat every 30 s, window stuck or not, a quit started) and `native-crash.txt` (faulthandler's stacks on a native crash), emptied at a clean quit. After an unclean exit `check_last` reads them plus Windows' Application log (wevtutil, this run's pid) and says why (`native-crash`, `windows-error`, `not-responding`, `while-closing`, `frozen`, `pc-restarted`, `ended`): in the usage event and a report in `crash-reports\` (not counted again as an error) |
| `soundboard/applog.py` | rotating log in `%APPDATA%\OnionBoard\onionboard.log`, written on its own thread (a log line never waits for the disk); unhandled exceptions (any thread) and Qt warnings land there; each distinct crash is saved, scrubbed of personal paths, to `crash-reports\` and offered to the user. `report()` does the same for an error code caught but didn't expect. The PC's situation (disk full, a file in use, access denied, no memory, network down) is said in plain words instead, with no report saved. `ONIONBOARD_DEBUG=1` for more. *Keep an app log* off (config `app_log`): memory only, the last lines kept for crash reports |
| `soundboard/ui/feedbackdialog.py` | *Send feedback*: "What would you improve?" picks (sent with the usage count, `usage.improve`), then a thank you with the feedback form |
| `soundboard/ui/crashdialog.py` | the "Onion Board hit a problem" dialog: the report, *Copy report*, *Report on GitHub* (copies it, opens a new issue in the browser), *Open folder* |
| `soundboard/testcheck.py` | analysis for the Record-6s test (finds your voice in the output by cross-correlation) |
| `soundboard/destination.py` | destination modes (Setup tab / Settings → *Who's listening*), one per voice chat engine: shapes the sounds bus for the listener's voice codec — sub-bass harmonics, a low cut with each sound's level given back, codec ceiling, gentle compressor (custom modes), mono |
| `soundboard/profiles.py` | the simple sound modes over *Who's listening*: Game, Voice chat, Clean, Advanced. Each is a family of destination modes and picks one from detector `Hint`s (what voicesdk sees); a later per-program list would be one more detector. Stored as `dest["simple"]` beside `dest["mode"]` |
| `soundboard/voicesdk.py` | which *Who's listening* mode suits: first the program recording what others hear (`Listeners`: your mic on the mic route, plus the virtual cable's far end; Discord, TeamSpeak and Mumble by name, a game by its files), else the voice engine of the game in front, from the voice libraries in its install folder (the exe path is read with the least access Windows has; nothing touches the game). A suggestion, switched to by itself only when the picker's box says so |
| `soundboard/ui/deleted.py` | the Recently deleted window (Bring back / Delete for good) |
| `soundboard/ui/resetguide.py` | the Reset guide (pick → check → reset and restart) and the Restore points window |
| `soundboard/ui/destpanel.py` | the mode picker and the custom-modes editor |
| `soundboard/codecsim.py` | development bench: runs audio through Discord's and ~20 game voice stacks' Opus pipelines (ffmpeg's libopus, plus Discord's ~94 Hz capture high-pass, measured in a real call) and measures what's lost, including a frame-by-frame spectral distance that hears noise fill and warble |
| `soundboard/chatsim.py` | development tool: simulates a voice chat's mic cleanup (noise suppression, gain control, gate) so the bench and tests can measure it and check the Discord check against it |
| `soundboard/realproc.py` | development tool: the same mic cleanup with the real libraries (WebRTC's audio processing via LiveKit, RNNoise), from the bench environment (`requirements-bench.txt`) |
| `soundboard/proxsim.py` | development tool: proximity chat on the listener's side (distance fade, walls, walkie-talkies and radios) from each game's published or decompiled defaults |
| `soundboard/chatcheck.py` | the Discord check: a test sound, and how to tell from Discord's Mic Test playback whether its noise suppression, gate or gain control is changing your sounds |
| `soundboard/ui/chatguide.py` | the Discord and game voice-chat guides (the settings that keep sounds clean) and the check that runs from them |
| `soundboard/ui/streamguide.py` | the streamer guide for remote control (Stream Deck keys, channel points, chat commands, with the links to copy) and the prompt that lets an AI assistant set it up |
| `soundboard/sendfx.py` | the send stage before what others hear (your mic, the cable or another device): phase-aware mono downmix, lookahead peak limiter, ducking under your voice |
| `soundboard/cableremove.py` | the Setup tab's *Remove the virtual cable* (offered once straight into the mic works): runs VB-Audio's own setup program from Program Files with `-u -h`, as admin; other kinds of cable are left alone |
| `soundboard/cableformat.py` | reads both ends of the virtual cable's Windows format and sets them to 48 kHz, so the cable passes sound through unconverted |
| `modules/` | add-ons shipped with the app: `retro-fx` (an effects module, the example to copy), `live-voice` (a service module with its own Python environment) and `translate-zh/es/fr/de/ru` (translation modules: a manifest naming a model that's downloaded only when picked). Remote add-ons such as Onion Pocket are installed into `%APPDATA%\OnionBoard\modules`. `ai-voices` (real-time voice conversion: onnxruntime + a Beatrice 2 model, see its README) lives here too but isn't built into the app: it's downloaded from its own release (`scripts/make_ai_voices_zip.py` packs it) |
| `build.ps1`, `installer/` | the PyInstaller build and the Inno Setup installer (`installer/OnionBoard.iss`); `installer/install-vbcable.ps1` downloads VB-Cable, checks its signature and installs it (used by the app and the installer) |
| `assets/onionboard.ico` | the .exe, installer and shortcut icon, generated by `scripts/make_icon.py` |
| `scripts/` | `install.bat` / `install.ps1` / `run.bat` (run from source: set up `.venv` and shortcuts, then launch), `build_directmic.py` (builds the mic effect `obmic.dll` with MinGW-w64's g++; `--testhost` also builds the test host), `fetch_tor.py` (unpacks Tor into the gitignored `vendor\tor` to try Tor mode from source), `prepare_art.py` (turns generated pictures into `assets/art/<key>.png`, see its README), `make_icon.py` (regenerates `assets/onionboard.ico` from the logo in `theme.py`), `make_bunny.py` (renders the installer artwork from `bunny.py`; `--preview` for a sheet of poses), `pick_tests.py` (the test files a branch's changes need: CI runs only those on a PR; `--local` adds uncommitted files), `precommit.ps1` (ruff, the sensitive scan, the translation check and the picked tests in one command), `release.py` (a release's version bump: `__version__`, the changelog heading, the release line), `check_sensitive.py` (secrets / personal-data scan, also the pre-commit hook; your own patterns go in a root `.sensitive-patterns`, see `sensitive-patterns.example`), `make_notices.py` (third-party licences for the build), `prune_build.py` (drops the unused parts of Qt from the PyInstaller output; `--dry-run` lists them), `vc_runtime.py` (keeps one, the newest, Microsoft C++ runtime in the PyInstaller output, so an older `msvcp140.dll` from the build PC can't stop Qt loading; `--dry-run` lists the copies), `version_info.py` (writes the .exe's version resource from `soundboard.__version__`, so Windows and its firewall prompt name it "Onion Board"), `codec_bench.py` (what voice chat does to your sounds, in numbers), `discord_roundtrip.py` (the same measured through a real Discord call to a second client), `dest_fit.py` (which *Who's listening* mode suits each game), `game_capture.py` (which mic Windows gives a game, its resampling and ducking), `steam_voice_roundtrip.py` (Steam's own voice codec, measured on one PC), `game_roundtrip.py` (a real game, recorded by a friend in the lobby, whose PC runs `game_listener.py`), `docs.py` (the README and website in one go: the screenshots, the version and VirusTotal line from `docs/release.json`, the sitemap dates; `--tour` re-records the tour), `screenshots.py` (renders `docs/screenshots/` offscreen from made-up demo data; set `ONIONBOARD_ONION_WATCH_ZIP` to an Onion Watch module zip to include the Triggers tab) `promo.py` (renders the Triggers promo clips: a made-up game scene drawn with QPainter, a synthesized trombone, ffmpeg) and `tour.py` (records the feature tour `docs/screenshots/tour.webp` from the real app, driven in a window parked off-screen, with the same made-up data as the screenshots) |
| `tests/` | pytest suite: ring buffer, engine mixing/guards/watchdog, cache and imports, recorder, hotkey parsing, EQ, levelling, config, test analysis, the main window built on Qt's offscreen platform (no window, no devices, no hotkeys) including shrinking it, the overlay, setup guide, voice panel, speech and effects, per-sound effects (speed and pitch measured by frequency and length, every preset, the effects cache, the Edit dialog) and live speed / pitch, the web search, the Triggers tab and its add-on (a made-up one: loading it and refusing one it can't host, zip installs that stay in their folder, downloads checked against GitHub's SHA-256, updates), and the Radio tab against a local stand-in for the directory and a station (parsing untrusted station data, search, cache and mirror failover, a stream decoded to 48 kHz and measured by frequency, dead stations, the map's stations and clicks) |

Developing:

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest
```

`pyproject.toml` holds the package metadata (version comes from `soundboard/__init__.py`),
the ruff and pytest settings, and a `soundboard` GUI entry point for `pip install .`.

## The installer

`build.ps1` builds the mic effect (`scripts\build_directmic.py`, MinGW-w64), runs
PyInstaller and produces `dist\OnionBoard\OnionBoard.exe` (one folder,
`directmic\obmic.dll` included), then compiles `installer\OnionBoard.iss` with Inno Setup 6
(`winget install JRSoftware.InnoSetup`) into **`dist\OnionBoardSetup.exe`**, the one
file to hand out. It installs per user (no admin), adds the Desktop and Start menu
shortcuts and opens the app, whose setup guide puts the sounds straight into the mic.
The add-ons in `modules\` (all but `ai-voices`) always come along in `{app}\modules`.
Its *Pick what you want* page (Inno Setup tasks) covers VB-Cable, unticked, only for
those who'd rather use the cable (downloaded and signature-checked by
`installer\install-vbcable.ps1`), FFmpeg via winget (offered only when ffmpeg is
missing and winget exists), setting up live voice-to-speech (*live-voice* runs its
`install.bat --quiet` when Python is present), Tor, keeping the network activity
history, *Count me in* (the usage count; ticked, the last page asks where they heard
about the app) and the Desktop shortcut. Uninstalling runs `--direct-mic remove`
first (the mic put back as it was; Windows asks only if the effect is on a mic) and
offers to remove VB-Cable too. Before the boxes, the *Your privacy* page
says what the app connects to and has an *Offline mode* box: ticked, the installer
runs `OnionBoard.exe --set-offline` (Offline mode in `config.json` before the first
start) and unticks the boxes that download. Silent installs use the defaults or the
previous install's choices; `/OFFLINE=1` is the Offline mode box, and skips the
download boxes unless `/TASKS=` or `/MERGETASKS=` names them. The installer artwork is Bun the mascot, drawn in code by
`soundboard/bunny.py` and rendered by `scripts\make_bunny.py` (`--preview` writes a sheet of
every pose). Settings live in `%APPDATA%\OnionBoard\` either way.
Saving `config.json` keeps the last three good copies next to it
(`config.json.1` … `.3`, rotated at most once an hour); a damaged file is set aside as `config.json.broken-<time>` and
the newest backup is used, so the pad list is never silently reset.

## Audio notes

- Sounds are held as int16 stereo at 48 kHz (half the size of float32; the
  engine scales them in the same multiply as the gain): short ones in RAM, long ones
  memory-mapped from the cache (`mapped.py`). Only the first 15 minutes of a
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
  instant. Sounds are read at a fractional rate with cubic interpolation (like a
  tape). A pitch shifter on the sounds bus (the voice changer's WSOLA pitch effect,
  one per channel: 30 ms pieces spliced where the waveforms line up, then resampled;
  about 50 ms of delay; switching it on or off crossfades) then puts the pitch back
  when *Keep pitch when changing speed* is on, and adds the pitch slider on top.
- Radio recordings are spooled to a 16-bit WAV as they happen instead of growing in
  RAM, and the resampled copies kept for non-48 kHz devices are capped at 512 MB (LRU).
  A press never waits for a copy: until it's made (on a thread) the sound is read
  from the 48 kHz original at the device's rate, like the live speed does.
- **The send stage** (`soundboard/sendfx.py`) is the last thing before what others hear (your mic,
  the cable, or the device the route picked).
  Everything Discord and games send is one channel, so the sounds are downmixed
  here first, per band: a band that is mostly out of phase between left and right
  is summed with the right channel flipped, and wide stereo gets back the power a
  plain average loses (a plain average took out-of-phase bass down 25 dB). Your
  mic is never touched by it. Then a lookahead peak limiter (3 ms) holds the send
  at -3 dBFS, because Opus puts peaks back up by ~2.5 dB and the listener's decoder
  clips them; it turns the level down around a peak instead of bending the
  waveform. Optionally the sounds duck under your voice while the mic hears you.
- Every device is opened at its **native** sample rate and resampled with soxr.
  Windows' built-in `auto_convert` resampler was measured garbling VB-Cable audio
  (about 70% junk), so it's never used.
- *Send my mic* off (sounds only) keeps the mic stream open, so the meter, the tests
  and live voice-to-speech still hear it; only its mix into what others hear is skipped.
- Virtual cables are hidden from the app's mic list. Picking the cable as the app's
  own mic makes a feedback loop (a loud screech).
- Hotkeys use Windows' `RegisterHotKey`, not a keyboard hook. The app is never in
  the path of your other keypresses, so it can't lag or stick your keys. A hotkey
  you pick is reserved for the app, so don't use one your game needs.
- Auto push-to-talk can't press keys in a game that runs as administrator unless
  Onion Board also runs as administrator (Windows blocks it). Keys are injected with
  `SendInput`, modifiers and key in one call.
- Windows draw the ordinary way (no `QT_WIDGETS_RHI`). Forcing GPU drawing, as up to
  1.9.7 for the Radio tab's 3D globe, gave every window its own Direct3D device (16
  driver threads and ~30 MB each, never freed).
- `OPENBLAS_NUM_THREADS` is set to 2 when the `soundboard` package is first imported,
  before numpy loads (a value you set yourself wins). numpy's and scipy's OpenBLAS
  otherwise start a pool of one thread per CPU each and reserve ~32 MB per thread: about
  1 GB of commit and 30 idle threads. Add-on helper processes (`net.child_env`) get the
  variable removed again, so their own maths isn't capped by the app's choice.
- Drop-outs reported by the audio driver are counted and shown in the status line.
  **⚙ Settings → Audio → Audio buffering: Safer** trades a little delay for bigger
  buffers if a device keeps crackling.
- A stream whose callback stops (headset unplugged, sample rate changed, PC woke from
  sleep) is reopened automatically after 1.5 s of silence from it; a device that failed to open
  is retried every few seconds. That reopening, and the re-scan when Windows lists a
  device PortAudio can't open, runs on the engine's one device thread
  (`engine.DeviceWorker`), never the UI thread: a driver can take seconds to close or
  open a stream when a headset is unplugged, Bluetooth drops or the PC wakes. One
  recovery at a time (`devices.claim()`); `engine.DEVICES` is held while streams open
  or close, and the device lists answer from their last copy during a re-scan.
- The audio callbacks never take the engine lock: the voice list is an immutable tuple
  swapped by the UI thread. An exception inside a callback is logged once and that
  block is silent; the stream keeps running.
