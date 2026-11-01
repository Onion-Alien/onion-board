# How Onion Board works inside

For people changing the code. Using the app needs none of this: the
[README](../README.md) covers that. The edit → check → build → release loop is in
[DEVELOPING.md](DEVELOPING.md); the rules are in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Sending sounds to others: straight into your mic, the virtual cable, or something else

Setup → Devices → *Send my sounds to* (also Settings → Audio → Devices) picks
the route (`Config.route`, `library.ROUTES`):

- **Straight into my mic** (new users start here, `Config.first_start`): Onion Board
  puts a small Windows audio effect on the real mic (`native/directmic/obmic.cpp`, an
  "APO" like Equalizer APO's, built with MinGW by `scripts/directmic/build_directmic.py`), so
  Discord and games hear the sounds through the mic they already use. Soundpad works
  the same way. One admin prompt sets it up (`main.py --direct-mic install <endpoint>`,
  `soundboard/mic/micadmin.py`): the DLL goes to `Program Files\Onion Board
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

  **The mic helper** (`soundboard/mic/michelper.py`): that first admin step also
  installs `obmichelper.exe` in `Program Files\Onion Board Mic Helper` (the admin part
  above frozen on its own by `scripts/buildtools/build_michelper.py`: no Qt, no numpy and none of
  the app modules that can't load without them, ~18 MB,
  with its own copy of `obmic.dll`) and a scheduled task, `\Onion Board\Mic helper`,
  that runs it as SYSTEM. The task has no trigger: it runs only when the app starts it,
  does the job and exits, so nothing stays in the background. Only the accounts that
  set it up (and admins) may start it: every account that went through the prompt
  (`users.txt` in its folder; `S-1-5-21-…` and Entra ID `S-1-12-1-…` accounts). The app
  adds `--for <its SID>` to set-up steps, so a standard user typing an admin's password
  gets it, not the admin; `install_helper` checks it's a real account with a profile
  here. After `schtasks /create` it reads the task back (`verify_task`) and deletes it
  unless it is exactly ours. From then on every admin step the app wants
  (`directmic._elevated`: set-up, repair, another mic, clean-up, removal) goes to the
  helper first, with no prompt: the app writes a one-line request into
  `%ProgramData%\OnionBoard\MicHelper\requests\`, starts the task, and reads the exit
  code from `...\results\` (admins only). The helper runs only the commands in
  `michelper.allowed()`, each with a mic GUID at most, through the same
  `directmic.cli` as the admin copy. It installs only the DLL it carries, so it's used
  for setting up only while its DLL is the app's (`stamp.txt`: `HELPER_VERSION` + the
  DLL's SHA-256); a new effect DLL makes the app ask Windows once more, and that prompt
  updates the helper. A helper older than `MIN_HELPER_VERSION` isn't used at all (raise
  it when the helpers out there have a bug). No helper, or one that doesn't answer:
  Windows' prompt, as before. The Setup tab's mic card fixes a mic Windows took the
  effect off by itself (`MicControl._show_mic_status` / `_auto_fix` in `ui/window/miccontrol.py`): through the
  helper only (`install(..., ask_windows=False)`, never a prompt nobody clicked), once
  per time it's found off; a fix that fails or doesn't hold turns the card into a Try
  again button. `michelper.ready()` keeps its last answer (`known()`, `will_ask()`) so
  the UI thread knows whether Windows will ask and says "click Yes" only then. A clean
  reinstall (`admin_reinstall`) restarts Windows' audio once for the whole job.
  Every step restarts all of Windows' audio (`_audio_off`; restarting only the changed
  mic with `pnputil` left a USB headset's mic without the effect), then checks its work
  (`_after_restart`): the effect's "initialize: endpoint" line in its `apo.log`, and each
  mic that opened before the step opening again (`appaudio.mic_opens`); one more restart
  if not, then exit code 8 or 9 instead of "done". SteelSeries Sonar loses its devices
  in a restart (its mic sends only zeros): `_sonar_keep` / `_sonar_back` read them from
  its local server (`127.0.0.1` only) before and set them again after, so it isn't ended.
  While the helper works on a request it touches
  `results\<id>.ack` every `BEAT_S`: `ask()` keeps waiting while it's fresh (past
  `wait_s`: a prompt now would only hit the lock, code 4), gives up `STALE_S` after it
  stops (killed, crashed) and takes the request back; no `.ack` and no answer, the full
  `wait_s` (helpers before 5). `scripts/directmic/sim_directmic.py` kills a helper at every step;
  `tests/test_michelper_task.py` registers a real SYSTEM task on CI's Windows runners.
  `michelper.ready()`/`installed()` run `schtasks`: never on the UI thread (it logs a
  warning if they are). The uninstaller's `--direct-mic remove` runs `remove-all` when
  any piece of a helper is there (`leftover()`): the effect off every mic, then the
  task is deleted and the helper's files go (those in use at the next restart). When the admin code changes, bump
  `HELPER_VERSION` (`tests/test_michelper.py` fails until it is).

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
  an older copy of it ('outdated'); the Setup tab offers a one-click repair (no prompt
  once the mic helper is there), or the cable. Tests run the real DLL in `testhost.exe`, which loads it the way Windows does.
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
installer runs the same command whenever FFmpeg is missing). The app
finds ffmpeg on `PATH` or in winget's `Links` folder.

## Where things are stored

Settings and imported sounds live in `%APPDATA%\OnionBoard\`. Its `cache\` folder
holds each sound decoded and ready to play (int16 at 48 kHz), so later starts don't
decode anything; it's safe to delete and is rebuilt as needed. The `icons\` folder
there holds the app icon in each theme you've used, which the app's own Desktop and Start
menu shortcuts point at (a reinstall resets them; the next start re-themes them).

## Code layout

Run from source with `scripts\run.bat` (or `python -m soundboard`); `main.py` at the root is
the launcher the shortcuts and PyInstaller use. The app is the `soundboard` package, a
folder per part of the app:

- `core/`: start-up and the plumbing: logs and errors, updates, backups, the usage count
- `audio/`: the real-time engine, effects and filters, replay and recording
- `mic/`: getting sounds into voice chat: the mic effect and its helper, routes, voice setups
- `sounds/`: the library, packs, pad pictures and videos, saved clips
- `online/`: every connection, Tor, downloads, radio, the store
- `addons/`, `control/` (the local API, MIDI, hotkeys), `win/` (Windows-only helpers),
  `sim/` (voice-chat simulators), `speech/`, `voicefx/`, `style/`, `otherboards/`
- `ui/`: `window/` (the main window and its controllers), `kit/` (shared widgets, the
  theme), one folder per tab (`sounds/`, `voice/`, `apps/`, `radio/`, `store/`,
  `triggers/`), `setup/`, `settings/`, `bun/`
- `i18n.py` stays at the top: add-ons look it up by that name

Problem reports count a file as ours up to two folders below `soundboard/`
(`ui/window/x.py`); `tests/test_usage.py` fails if a module sits deeper.

| file | what it does |
|---|---|
| `soundboard/__main__.py` | `python -m soundboard` |
| `soundboard/core/app.py` | entry point: log file, crash hooks, runtime tuning, single instance, the window |
| `soundboard/core/earlystart.py` | the loading screen from main.py, right after the start-up breadcrumb and before app.py's heavy imports: takes the single-instance lock first (a second launch shows nothing), then the language, interface size, QApplication and Bun; app.main() reuses them |
| `soundboard/core/singleinstance.py` | named mutex + local socket so a second launch just raises the first |
| `soundboard/ui/window/mainwindow.py` | the main window: pads, transport, tabs, the audio panel, test mode, auto push-to-talk |
| `soundboard/ui/window/windowparts.py` | `WindowParts`, the base of MainWindow's mixins below: the window's parts `WindowBuilder` makes, and (for the type checker only) what MainWindow provides; empty at run time |
| `soundboard/ui/window/windowtoasts.py` | MainWindow's toasts (a mixin): `toast`, `say`, `tell`, `unsay`, where the cards stand and how they show, growing the window when a shrunk card is clicked |
| `soundboard/ui/window/windowtabs.py` | MainWindow making its tabs (a mixin): Radio, Voice, Apps, Triggers and Store or their stand-ins when switched off, the Store's links and samples, sharing a voice, loading the Onion Watch add-on |
| `soundboard/ui/window/windowlife.py` | MainWindow's life (a mixin): the tray icon and its menu, quitting and restarting, Windows ending the session, starting with Windows, the usage count |
| `soundboard/ui/window/windowoptions.py` | MainWindow's settings changes (a mixin): `set_option` and saving, Use less CPU for voice, the EQ, always on top, pad width, single click, the master switch (`set_sending`) |
| `soundboard/ui/window/hearcheck.py` | *Hear what they hear* in the main window (a mixin): the switch, the speakers warning, stopping when the mic squeals |
| `soundboard/ui/kit/widgets.py` | small shared widgets (the placeholder fitter, the inline name box, the window's painted root, click focus, `SteadyTabs`), and where the hand-painted widgets below are imported from: it re-exports them all |
| `soundboard/ui/kit/meters.py` | painted gauges: the level meter, the EQ curve, the loading bar, the "now playing" equalizer, and the spectrum / loudness a playing pad shows |
| `soundboard/ui/kit/seek.py` | the player's seek row: `CrispSlider`, the click-to-seek `SeekSlider`, the sound name beside it (`NameAndSeek`, `EdgeMatch`) and the time text |
| `soundboard/ui/kit/pad.py` | one sound's pad (`Pad`): the hand-painted button on the board (picture, spectrum visualizer while playing), its sizes and colours |
| `soundboard/ui/kit/padgrid.py` | the board: `PadGrid`, the grid that lays out the pads (the empty board's Bun, dropped files) |
| `soundboard/ui/kit/layouts.py` | `take_out` and `widget_at`: take an item out of a layout, or read its widget, without leaving Qt items or PySide wrappers behind |
| `soundboard/ui/kit/playbutton.py` | playback button with a smooth circular edge in full and mini views |
| `soundboard/ui/kit/pixels.py` | `snap_to_pixels` (from the style kit's `appstate.py`): every hand-painted widget calls it first so its edges land on whole pixels at 125 % / 150 % scaling |
| `soundboard/ui/kit/plaintext.py` | `plain_tip`: text from outside the app (web titles, names from boards, backups and packs) as rich text that says exactly that text, for tooltips and message boxes (Qt reads HTML-looking text as HTML) |
| `soundboard/ui/kit/restyled.py` | sizes worked out from a widget's text (`measured`, `on_restyle`), worked out again when its style or font changes: the window is built with the app's style sheet off (`theme.styled_after`) and `again()` re-runs them all once it's back on |
| `soundboard/ui/kit/iconrow.py` | label icons aligned to the first line's capital ink using the current font metrics |
| `soundboard/ui/kit/glowbutton.py` | `GlowButton`: a primary button with a soft accent glow, for the install a card needs before it works (AI voices, speech recognition) |
| `soundboard/ui/kit/panel.py` | the bar, card and heading helpers every tab is built from, icon, info, fold and reset buttons, tiles, the view toggle and the empty list's picture; the volume boxes, the equalizer, `Flow` and `CardGrid` live in the `panel*` modules below (still importable from here) |
| `soundboard/ui/kit/panellabels.py` | a section's title, a number label as wide as its widest value, a hint's muted words (`panel` re-exports them) |
| `soundboard/ui/kit/panellayouts.py` | `ShownStack`, keeping focus off a page switched away, `Flow` (wrapping) and `CardGrid` (`panel` re-exports them) |
| `soundboard/ui/kit/panelcontrols.py` | `VolumeControl` (slider + typed %), `EqPanel` (the equaliser) and `UndoBar` (`panel` re-exports them) |
| `soundboard/ui/sounds/dialogs.py` | per-sound Edit dialog: the Sound tab (name, volume, hotkey, fades…) and the Effects tab |
| `soundboard/ui/sounds/editadvanced.py` | Edit sound's Advanced view: the waveform big on top (zoom, ruler, fades), the Speed & loudness, Effects and Equalizer pages side by side (tabs when narrow), only the effects that are on plus the Add effect picker, the Simple / Advanced switch |
| `soundboard/ui/sounds/editsummary.py` | the top of Edit sound's Simple view: the sound's length and a chip with an × for everything on it |
| `soundboard/ui/sounds/editdialogparts.py` | part of the Edit dialog: its Source line, the fade cells, the render and live-preview progress, the picture, the pad colour, the name check and the hotkey |
| `soundboard/ui/sounds/editplayer.py` | the player in Edit sound: the board's player bar again (play / pause, stop, skip, name and seek line, time, Sounds for others, Hear it myself), the Now playing chips and Stop all; the board's player sets it as it sets its own |
| `soundboard/ui/sounds/tabhelp.py` | a tab's help pop-up (the ? button), with Bun or Hoot beside it (`dialogs` re-exports it) |
| `soundboard/ui/window/languagecontrol.py` | the main window's language (`MainWindow.langctl`): offering Windows' language once, turning it down, switching |
| `soundboard/ui/window/miccontrol.py` | straight into the mic and the virtual cable in the main window (`MainWindow.micctl`): the mic effect's status, putting it on the mic (and back by itself), the mic helper, its update offer, falling back to the cable; installing, removing and fixing the cable; Windows' mic settings |
| `soundboard/ui/window/netcontrol.py` | the main window following the network and privacy switches (`MainWindow.netctl`): Offline mode, a feature switched off, the proxy / Tor and remote-control lines on the output card, how far Tor is |
| `soundboard/ui/window/padcontrol.py` | a pad's own controls in the main window (`MainWindow.padctl`): its right-click menu, volume slider and nudges, its picture, and the View menu (sort, grid or list, row size, pad size) |
| `soundboard/ui/window/routecontrol.py` | where the main window's sounds go (`MainWindow.routectl`): the device pickers, the route (the mic, a cable, or only you), the extra send outputs and OBS's device, what the mic button and mute do |
| `soundboard/ui/window/removecontrol.py` | taking sounds off the board (`MainWindow.rmctl`): asking first, removing one or several, the Undo bar, the Recently deleted bin and restoring from it |
| `soundboard/ui/sounds/padbatch.py` | picking several pads (Ctrl / Shift+click, Ctrl+A) and changing them together: delete with one Undo, colour, volume, fades, categories |
| `soundboard/ui/kit/busy.py` | click feedback for buttons: a greyed-out *Scanning…* while the work runs, then a short *✓ done* on the button (`run_busy`, `hold`, `flash`) |
| `soundboard/ui/setup/cableconfirm.py` | the are-you-sure box before the virtual cable: what it means (CABLE Output in every app), and the mic as its main button |
| `soundboard/ui/kit/worker.py` | `run(fn, signal, name, error=…)`: work on a thread whose answer always comes back to the UI, the error value when it raises (so no busy flag or button stays stuck), nothing when its owner is gone |
| `soundboard/ui/kit/topbar.py` | `TopBar`: the one look of every bar across the top of the window (a stripe in its tone, icon, bold heading then the rest, buttons, ✕, all centred however the words wrap) |
| `soundboard/ui/kit/toast.py` | the result cards in the window's bottom corner (`busy.toast` / `MainWindow.toast`): green / yellow / red, up to three stacked above the player, a repeat counted as ×2, an action button (Undo, See why), Copy on problems, a bar for progress |
| `soundboard/ui/sounds/importreport.py` | what an import skipped and why, sorted into plain groups: the toast's summary line and the *See why* list you can copy |
| `soundboard/ui/window/aboutcontrol.py` | the main window's About menu (`MainWindow.aboutctl`): the version, Join the Discord, Send feedback, the website |
| `soundboard/ui/window/alertcontrol.py` | the urgent bar in the main window (`MainWindow.alertctl`): an important fix for Onion Board or Onion Watch, Discord's own settings hurting your sounds, apps recording your mic around the mic effect; one at a time, each can be hidden |
| `soundboard/ui/window/appsetupcontrol.py` | set up for the app you're using, in the main window (`MainWindow.appsetctl`): noticing the voice app or game in front, the bar offering to set up for it (Yes / Not now / x, Undo), its checks once done, picking where sounds go by itself |
| `soundboard/ui/window/buncontrol.py` | Bun mode in the main window (`MainWindow.bunctl`): the window goes and the floating Bun takes its place, Back / Open the full board, Bun saying the toasts, starting as Bun |
| `soundboard/ui/window/categorycontrol.py` | categories in the main window (`MainWindow.catctl`): the category tabs and sub-category row, picking, adding, renaming, deleting and colouring them, a sound's categories, switching category while a chosen program is in front |
| `soundboard/ui/window/controller.py` | the base of the main window's feature controllers: a QObject the window owns, so timers and signals aimed at a controller stop with the window |
| `soundboard/ui/window/devicecontrol.py` | the audio devices of the main window (`MainWindow.devctl`): opening them on a worker one job at a time, re-scans, the latency, following Windows' default output, getting a lost device back |
| `soundboard/ui/window/editcontrol.py` | the Edit sound windows of the main window (`MainWindow.editctl`): one per sound plus a spare kept built, saving or saving a copy when one closes, closing them when their sound goes, Duplicate, Open file location, rendering a sound again |
| `soundboard/ui/window/ffmpegcontrol.py` | FFmpeg in the main window (`MainWindow.ffctl`): the check at start-up, getting it by itself when it's missing or won't start, Fix it / Get FFmpeg / Reinstall, and the top bar with how far it is and Stop |
| `soundboard/ui/window/fitcontrol.py` | the main window fitting its size (`MainWindow.fitctl`): what gives way as it gets smaller (the rail, the mixer, the category bar, the Setup page's columns, the toolbar), the mini player, laying it all out again |
| `soundboard/ui/window/hotkeycontrol.py` | hotkeys in the main window (`MainWindow.hkctl`): registering them (per category when they follow it), what each key does pressed or let go, push-to-talk, MIDI and instant replay, setting a sound's, a category's or an app-wide key (a combo does one thing), the keyboard menu, all hotkeys off |
| `soundboard/ui/window/importcontrol.py` | getting sounds in, in the main window (`MainWindow.impctl`): Add sounds / folder / link, dropped files, the sounds folder's loose files, other soundboards; its backups and sound packs are the mixins below |
| `soundboard/ui/window/importbackup.py` | backups in the main window (a mixin of `ImportControl`): exporting the board, a category or some sounds, importing a backup with its settings and hotkeys |
| `soundboard/ui/window/importpacks.py` | sound packs in the main window (a mixin of `ImportControl`): the Free packs page in the tabs' place, a pack's category, tidying, resetting and removing a pack |
| `soundboard/ui/window/invitecontrol.py` | the "{name} invited you to Onion Board" toast on a first start, from the installer's `invited-by` note (`soundboard.core.invite`) |
| `soundboard/ui/window/searchcontrol.py` | the Sounds tab's search box (`MainWindow.searchctl`): filtering the pads as you type, a link pasted in it, searching YouTube and other sites from it |
| `soundboard/ui/window/settingscontrol.py` | the Settings page of the main window (`MainWindow.setctl`): opening it on a page in the window's place, growing the mini player for it, closing and keeping it, building it (and a spare Edit sound) ahead of time |
| `soundboard/ui/window/soundscontrol.py` | the board's sounds coming in (`MainWindow.soundctl`): loading them all on a worker, each one's audio arriving, a clip, recording or download made into a sound, moving and renaming a pad |
| `soundboard/ui/window/statuscontrol.py` | what the main window says about its audio (`MainWindow.statusctl`): the devices' status line and card, and the Setup tab's flow (what you hear, what others hear, the set-up buttons and which one is the main one) |
| `soundboard/ui/window/tabcontrol.py` | the main window's tabs (`MainWindow.tabctl`): which are on and shown, switching them on and off, the More tabs menu, a tab's right-click menu, moving a tab's place, the tab keys, counting which tab was opened |
| `soundboard/ui/window/themecontrol.py` | the main window's look (`MainWindow.themectl`): applying a theme, the Live colour, the background texture, the live tab's tint, the onion logo |
| `soundboard/ui/window/tipcontrol.py` | tips and help in the main window (`MainWindow.tipctl`): a tip once things settle, Show me, tips off, a tab's About this tab, the mic tips, the Help menu |
| `soundboard/ui/window/enjoycontrol.py` | *Enjoying Onion Board?* (`MainWindow.enjoyctl`): the slim bar with Bun's survey, a thumb up or down and a few optional words, shown once ever at a calm moment; sends with `usage.survey` |
| `soundboard/ui/window/tickcontrol.py` | the main window's tick (`MainWindow.tickctl`): the timer that moves the meters, the now-playing time and the pads' progress, how fast it runs (fast while something moves and the window is seen, slower when quiet or hidden), waking it |
| `soundboard/ui/window/transportcontrol.py` | the main window's transport and what plays behind it (`MainWindow.transctl`): the play / pause / stop / seek row, the playing sound's picture as the board's background, a sound's video |
| `soundboard/ui/window/updatecontrol.py` | Onion Board's own updates in the main window (`MainWindow.updctl`): the check (and Onion Watch's), the update card's states, the download with Cancel, installing it, What's new |
| `soundboard/ui/window/windowbuild.py` | building the main window's parts (`MainWindow.builder`): the frame (tab rail, tabs, mixer strip, the bars on top); the pages come from the mixins it inherits (below); runs once while the window is made |
| `soundboard/ui/window/playerbuild.py` | building the mini player and the mixer strip (`PlayerBuild`, a mixin `WindowBuilder` inherits) |
| `soundboard/ui/window/soundsbuild.py` | building the Sounds page: its toolbar, the search box, the pads and the bars around them (`SoundsPageBuild`, a mixin `WindowBuilder` inherits) |
| `soundboard/ui/window/setupbuild.py` | building the Setup page: its cards and the step-by-step guide (`SetupPageBuild`, a mixin `WindowBuilder` inherits) |
| `soundboard/ui/window/dropveil.py` | the veil over the window while files are dragged in: "Drop to add 4 files" |
| `soundboard/ui/window/themecover.py` | a still of the window with Bun over it while a theme switch restyles every widget, faded in and out (the kit's `style/cover.py`): never a half-styled frame or a flash |
| `soundboard/ui/kit/a11y.py` | screen-reader names for icon-only controls, taken from their tooltips as the focus moves |
| `soundboard/ui/kit/numberbox.py` | every number box takes a typed value on a pause or a click away, and Enter in one presses no window button |
| `soundboard/ui/kit/quietbox.py` | no Windows "ding" from information/warning message boxes (same picture, shown as a pixmap); only critical errors keep their sound |
| `soundboard/ui/kit/modals.py` | every dialog stays see-through until its first paint (no white flash on Windows); a left click on a window a modal dialog blocks closes that dialog as Cancel, unless it has `KEEP_OPEN` |
| `soundboard/ui/kit/weblinks.py` | web links (http/https/mailto) open through a helper started with the user's own environment, so a browser the app starts doesn't inherit the relay's proxy variables |
| `soundboard/audio/shuffle.py` | the random-sound hotkeys' shuffle bag (every sound once before repeats, never twice in a row) |
| `soundboard/control/remote.py` | opt-in local control API for Stream Deck / scripts: HTTP on `127.0.0.1`, token-guarded, answered on the UI thread (the endpoints, the server, `RemoteControl`, `apply`). With `lan=True` it's the server "remote" add-ons (Onion Pocket) get: local-network peers only, wrong keys locked out, never on a network Windows calls Public. It re-exports the app side below, so older imports keep working |
| `soundboard/control/remotedispatch.py` | the control API's app side: `dispatch` carries out one request on the window (sounds, status, the play queue, key pictures) and hands the tabs' requests to `remotetabs.py` |
| `soundboard/control/remotetabs.py` | the control API's requests for the tabs: the Voice tab, live speed / pitch / effects, Who's listening, the Apps tab, My voice combos, the mic gate and the radio |
| `soundboard/control/remoteparams.py` | the control API's helpers for a request's values: `on=` switches, numbers, volume boxes, finding a sound or category by name |
| `soundboard/control/remoteprompt.py` | the control API's AI setup prompt (`setup_prompt`): what to paste into an AI assistant so it can set up a Stream Deck, Streamer.bot, Touch Portal… |
| `soundboard/online/twitch.py` | Settings → Remote's *Connect Twitch*: signing in with Twitch's device code, refreshing the token, and the Helix calls (who signed in, channel point rewards, EventSub subscriptions, a chat reply); blocking, through `net` (feature `twitch`) |
| `soundboard/control/keyimage.py` | a pad drawn as a Stream Deck key with the board's own card (`Pad`: theme, picture, name, hotkey, length) for `/api/key_image`, and the `look` tag that says when it changed |
| `soundboard/control/twitchlink.py` | the live Twitch link (`MainWindow.twitch`): the sign-in's steps, then the EventSub socket (`QWebSocket` through the relay), its keepalive, moves and reconnects; events go to `streamapi` (chat lines to the chat commands with the reply posted back, the rest to the alerts) |
| `soundboard/ui/settings/twitchcard.py` | Settings → Remote's *Twitch* card: connect (the code), what each channel point reward and alert plays (the alerts' own rules), chat commands on / off, disconnect, the guide and AI prompt buttons |
| `soundboard/ui/settings/twitchguide.py` | The Twitch card's *Twitch guide* (step by step) and *Copy AI prompt* (the card, the rewards and alerts set now, the chat rules, the sounds, and the control API calls for the extras) |
| `soundboard/control/streamapi.py` | the control API's streamer endpoints: chat commands (`/api/chat`, with who may, cooldowns and blocked words), alerts and donations (`/api/event`: reads Twitch EventSub, StreamElements, Streamlabs and Ko-fi JSON too; what each type does is set with `/api/alerts`, a channel point rule may name its reward) and the feed of what they did; never connects anywhere itself (`twitchlink` brings Twitch's events) |
| `soundboard/online/netcategory.py` | whether Windows calls the network an address is on Public / Private / Domain (Network List Manager over COM, no admin), so the phone remote never listens on a café's Wi-Fi |
| `soundboard/ui/window/playbackcontrol.py` | playing sounds in the main window (`MainWindow.playctl`): a pad played, queued or waiting its turn, the now-playing chips and Up next, Space, play / pause, stop, skip, seek, play the last one again, a random sound, the cue beep, the effects preview |
| `soundboard/ui/window/achievepop.py` | the "Achievement unlocked" pop-up: a console-style toast at the bottom middle of the screen (an orb pops, a bar slides out with the points and name), over games, never taking focus or clicks; queued one at a time, from any thread (`achievements.on_unlock`), with its chime in the headphones only |
| `soundboard/ui/window/upnext.py` | Up next above the pads: one chip with how many sounds wait, and its pop-up list (every name, a ✕ on each, Clear) |
| `soundboard/ui/window/remoteaccess.py` | remote control in the main window (`MainWindow.remctl`): the control API started / stopped to match the settings, and the phone-remote add-ons (Onion Pocket): starting, updating in place, removing, stopping them at quit |
| `soundboard/ui/settings/remotehost.py` | Onion Board as the host of a "remote" add-on such as Onion Pocket: its settings (never in a backup), a lan server offering a list of actions, and Settings' look for its card on Settings → Remote |
| `soundboard/ui/setup/pocketcard.py` | Onion Pocket's card on the Setup tab (`MainWindow.pocket_card`), only while it's installed: on the left in Connect your chat's place (that moves right); shut it says if phones can reach the board, its fold opens the add-on's own controls |
| `soundboard/ui/sounds/linkbar.py` | the Sounds tab's link bar: a link pasted into *Search sounds* is looked up with yt-dlp, then added as a sound or played once |
| `soundboard/ui/window/downloadbar.py` | persistent top download bar across tabs and in mini player mode: parsing, download progress with live percentage, processing stages, queue badge, and cancel button |
| `soundboard/ui/window/downloadlook.py` | part of `DownloadBar`: its look in the theme (style sheet, gradients) and lining up its two lines of text |
| `soundboard/ui/window/downloadplace.py` | part of `DownloadBar`: where it sits (banner or corner card above the player bar), folding to its pill and gliding between them |
| `soundboard/ui/window/downloadrows.py` | part of `DownloadBar`: the list of picks waiting, up next, added and failed, and retrying a failed one |
| `soundboard/ui/window/downloadbits.py` | the download card's sizes and timings and its clickable queue row and summary line (`downloadbar` re-exports them) |
| `soundboard/ui/window/downloadparts.py` | the download card's parts: the smooth progress bar, the title label and kind tag, the tick / cross flash when a pick ends, a pick's title and source in words, the pictures' rounded corners, the accent glow's strength |
| `soundboard/ui/sounds/ytsearch.py` | the Sounds tab's web search: Enter in *Search sounds* shows YouTube or SoundCloud hits as a grid of cards (thumbnail, title, length) in place of the pads; *Play* / *Add* hand one to the link bar; the one in the player shows a bouncing equalizer and *Play* becomes *Pause*; it re-exports the cards' names below |
| `soundboard/ui/sounds/ytcard.py` | one web search hit's card (`ResultRow`): the thumbnail (`Thumb`, with the download's progress and the player's equalizer over it), title, channel, counts, *Play* / *Add* |
| `soundboard/ui/sounds/ytlabels.py` | words on the web search's cards: view / like counts and `ClampLabel` (a label cut to a few lines with an ellipsis; the Store's cards use it too) |
| `soundboard/ui/sounds/ytwaiting.py` | the web search's loading view (`SearchingView`: Bun or Hoot over a sliding bar) and its *Back* button (`BackHome`) |
| `soundboard/sounds/sourceinfo.py` | where a sound added from a web link came from: link, channel, upload date, length and views picked from the download's own yt-dlp reply, kept as `SoundMeta.source` and as a text file next to its audio |
| `soundboard/ui/sounds/sourcedialog.py` | the pad menu's *Details* for a downloaded sound: its picture, title, channel and dates, with *Open on YouTube*, *Copy link* and *Delete info* |
| `soundboard/ui/window/spacekey.py` | Space plays / pauses on the Sounds and Radio tabs wherever the focus is (not in text boxes, or on a button reached with Tab) |
| `soundboard/ui/window/konami.py` | The Konami code typed in the main window: every Bun on screen cheers, a toast, and the Old School achievement |
| `soundboard/ui/window/winwatch.py` | one event filter on the main window's own native window, for what watches the whole window (Space, the drop veil); no app-wide Python filter |
| `soundboard/ui/sounds/speedpitch.py` | live controls pop-ups: speed, pitch and effects for Sounds, and pitch and effects for Radio and Apps; the speed gauge turns red at 8x |
| `soundboard/ui/sounds/soundpanel.py` | Live controls' speed, pitch, volume and effect knobs with their typed values, quick buttons and presets: one set of widgets for the Live controls pop-up and Edit sound |
| `soundboard/audio/livefx.py` | live effects on every playing sound (the speed & pitch popup): bass, treble, muffle, reverb, echo, distortion and presets; not saved |
| `soundboard/mic/livesetup.py` | a voice setup from Live controls on a live stream (the radio, a captured program): its voice changer at once, its AI voice once its helper is ready |
| `soundboard/audio/mypresets.py` | your own presets: Live controls' (speed, pitch, effects, volume) and Edit sound's (a sound's effects) under a name, in `%APPDATA%\OnionBoard\my-presets.json` |
| `soundboard/audio/soundfx.py` | per-sound effects: trim, speed / pitch (phase vocoder + soxr), EQ, boost, reverse and any voice effect, rendered off the audio thread a piece at a time (`render_into`; `library.render_cached` writes it straight into the cache file, so a long sound is never all in memory); the presets |
| `soundboard/audio/achievechime.py` | the achievement pop-up's chime, made in code: a rising bloop, a bright bell chord and a short stereo echo |
| `soundboard/i18n.py` | translations: `_()` / `ngettext()` look the English up in the language picked (`assets/lang/<code>.json`) and fall back to it; Windows' language, plural rules, the pseudo-language `xx` and `unwrapped_texts` for layout checks (see [TRANSLATING.md](TRANSLATING.md)); `scripts/checks/i18n_extract.py` lists missing / unused texts |
| `soundboard/core/langnames.py`, `langnames_data.py` | language names in the app's language for the *Speak in* list; the data file is generated from Unicode CLDR by `scripts/buildtools/make_langnames.py` (don't edit it) |
| `soundboard/core/tips.py` | is a game (or anything filling a monitor) in front? The top bars and the tours wait until it isn't |
| `soundboard/ui/sounds/recordmic.py` | the Sounds tab's *Record a sound* window: a mic take (`Engine.start_mic_take`) or what's playing (`Engine.start_play_take`: sounds + radio, no mic), spooled by `recorder.MicTake`, raw or through the voice changer, trimmed and added as a pad; not modal |
| `soundboard/sounds/catswitch.py` | Switch category when a program is in front: `Switcher.poll()` (one foreground lookup a second, only while a rule exists; back to the old category when the program closes) |
| `soundboard/ui/sounds/splicepanel.py` | Edit sound Advanced's splices: the Add splices switch and the Splices pop-up (each splice's times, play, remove, Combine splices) |
| `soundboard/ui/sounds/trim.py` | the Effects tab's trim control: waveform with start / end handles and exact-time boxes; big in the Advanced view (ruler, zoom, fades drawn, splices: parts marked with two clicks, numbered, joined to play back to back) |
| `soundboard/core/backup.py` | export / import of the board as a plain zip (JSON + original audio + pictures), sound packs and single sounds; see [BACKUP-FORMAT.md](BACKUP-FORMAT.md) |
| `soundboard/sounds/packs.py` | free sound packs: the list (`packs/catalog.json` in this repo, with a built-in copy for offline) of ready-made boards in the backup format, added in one click; each pack's preview zip (`samples`); links packs, fetched from Myinstants into a pack zip on Add (`download_links`) |
| `soundboard/online/store.py` | the sound store (Store tab): the list, fetching a sound, votes, reports and uploads, talking to the project's own server |
| `soundboard/ui/store/storetab.py` | the *Store* tab: free CC0 sounds to hear, add, vote on or report; it re-exports the names of the pieces below |
| `soundboard/ui/store/storerow.py` | one sound's card on the *Store* tab (`SoundRow`): its tile, *Play* / *Add* / vote buttons and who shared it |
| `soundboard/ui/store/storeshare.py` | the *Store* tab's *Share a sound* window (`ShareDialog`): a file or a link, then a thank-you |
| `soundboard/ui/store/storefit.py` | `StoreFit`, a mixin of `StoreTab`: the toolbar on one row or two and as many cards a row as fit the tab's width |
| `soundboard/ui/store/storeplay.py` | `StorePlay`, a mixin of `StoreTab`: *Play* / *Stop* / *Play next*, hearing a sound first in your headphones, a shared link's card following the player |
| `soundboard/ui/store/storelook.py` | the *Store* tab's pictures: a sound's emoji tile (from its name, tags and category; bars bounce while it plays), the banner with Bun |
| `soundboard/online/storevoices.py` | the Store's community voices: packing your voice changer voices, AI voices and voice combos to share (settings only), checking every voice from the store again, taking one into your own lists, its *Hear it* sample, and share codes for any of them (`OB2-…`, read back through the same checks; old `OB1-…` voice codes still read) |
| `soundboard/ui/store/storevoices.py` | the Store tab's *Voices*: a row per community voice and the *Share a voice* window |
| `streamdeck/` | the Stream Deck plugin (plain Node 24, no libraries): `bin/onionboard.js` finds the control API's port and key in `config.json` and draws the keys, `bin/actions.js` the keys (Play sound, Stop all, Random, Switch), `ui/` a key's settings panel; its README says how to try and pack it. Pictures: `scripts/pictures/make_streamdeck_icons.py` |
| `soundboard/ui/sounds/packsdialog.py` | the *Free sound packs* page (Sounds tab → Backup, in the tabs' place): search, filter chips and a grid of packs to add, each one's *Preview* (a few of its sounds as pads, preloaded), and where to share your own |
| `soundboard/otherboards/` | Import from another soundboard. `__init__.py`: what the readers share (Entry rows, the list of sources, the installer's queued-import note); only when the user asks (Backup menu, setup guide, the installer's boxes, or a dropped board file) |
| `soundboard/otherboards/soundpad.py`, `resanance.py`, `soundux.py`, `expboard.py` | the readers: Soundpad's `soundlist.spl` XML, Resanance's LiteDB 5 `Resanance.db` (read page by page, no LiteDB needed), Soundux's `config.json`, EXP Soundboard's board JSON (found through Java's Preferences in the registry) |
| `soundboard/control/adminfront.py` | games run as admin: notices a full-screen admin window in front (Windows keeps its keys from the board) so the hotkeys can say why they're quiet and offer *Restart as admin* (`ui/window/hotkeycontrol.py`); starts the board again through Windows' admin prompt |
| `soundboard/core/autostart.py` | *Start with Windows*: the per-user `Run` registry value (`--tray` starts it hidden) |
| `soundboard/win/shellicon.py` | the app icon in the theme's colours outside its windows: writes `%APPDATA%\OnionBoard\icons\onionboard-<hash>.ico`, puts it on the main window's relaunch properties (taskbar right-click menu, a pin) and on this copy's own *Onion Board* Desktop / Start menu / taskbar-pin shortcuts |
| `soundboard/win/thumbbar.py` | the buttons in the taskbar's hover preview of the main window (play last, pause, stop all, random, Live / Muted), through `ITaskbarList3`; the window's `nativeEvent` hands it the clicks |
| `soundboard/core/updates.py` | "is there a newer version?" (GitHub Releases, every hour; an "Urgent: …" line in the notes gets a banner) and the self-update: downloads the release's installer, checks its SHA-256, runs it silently and reopens the app |
| `soundboard/core/feedback.py` | where *Join the Discord*, *Send feedback* and *Report a problem* (Settings → About, the tray menu) go: the Discord invite, a no-account form or a GitHub issue, opened in the browser with the version filled in; the app sends nothing |
| `soundboard/core/errors.py` | other libraries' errors (yt-dlp, libsndfile, PortAudio, Windows, network) in plain words, minus their "report this to us" lines and command-line tips; the original stays in the log and in the report. Ones the user can't fix get a *Report it* link/button: a pre-filled issue on this repo, opened in the browser |
| `soundboard/core/hangwatch.py` | notes down a frozen window: if the UI thread stops answering for 5 s, its stack goes into the log and a report beside the crash reports, with every thread's CPU use over 0.5 s (`cpu_times`) and, once it answers again, how long it lasted (`applog.note_freeze_end`; nothing shown or sent) |
| `soundboard/core/pollthread.py` | one thread kept for a timer's repeated look-up (Windows' default output, Discord's settings), so the UI never waits in Thread.start for a new one each time |
| `soundboard/core/threadnames.py` | each Python thread's name given to Windows too (SetThreadDescription), so profilers and crash dumps tell the threads apart |
| `soundboard/core/overridepin.py` | keeps every Python override of a Qt method alive: in PySide 6.11 one exception inside a Qt callback can free another class's override, and the next call runs freed memory |
| `soundboard/core/uigc.py` | Python's garbage collection on the UI thread only: a collection on another thread could free a Qt object with a running timer there and crash the app |
| `soundboard/ui/kit/icons.py` | the line icons, drawn in code and recoloured with the theme |
| `soundboard/ui/kit/iconshapes.py` | the line icons' drawings: `SHAPES`, each icon's name to the function that draws it on a 24x24 grid |
| `soundboard/ui/voice/art.py` | optional pictures from `assets/art` (voice tiles, the computer voice, its languages); emoji / painted icons when missing |
| `soundboard/ui/window/responsive.py` | small windows: what hides, in which order, as the window shrinks |
| `soundboard/ui/settings/routewarn.py` | the question on leaving Settings when "Send my sounds to" was just set to speakers or a headset: My mic, the virtual cable (use or install), or keep it |
| `soundboard/ui/kit/fit.py` | dialogs grow to fit their wrapped text instead of clipping it (`fit.watch(self)` in every dialog's `__init__`) |
| `soundboard/ui/setup/setupwizard.py` | the first-run guide with Bun (mic, headphones, where your sounds go: straight into your mic, or the cable or another way out, then Discord; on the first launch, then a language and a look): its frame (the steps, Back / Next, the motion); each step's page is a mixin below |
| `soundboard/ui/setup/devicestep.py` | the guide's mic and headphones step: device tiles, the live level and the test sound |
| `soundboard/ui/setup/cablestep.py` | the guide's *where your sounds go* step: the mic effect, the virtual cable's installer (and the restart it may need, `resume_after_restart`) or another way out; *Switch to the virtual cable?* |
| `soundboard/ui/setup/discordstep.py` | the guide's last step: what to pick in Discord (or a game, Steam, OBS), read back from Discord's own settings on a kept thread |
| `soundboard/ui/setup/lookstep.py` | the guide's first-launch steps (*Make it yours*): the tabs to start with, a language, a look, the privacy switches and *Set up Discord for me* |
| `soundboard/ui/setup/wizardkit.py` | the guide's shared sizes (tiles, margins, gaps, Bun's size) and small builders (`_header`, `_label`, `_card`) the steps and the chat guides use |
| `soundboard/ui/setup/wizardparts.py` | the guide's own widgets: the step bar, the page stack that fades between steps, its scroll area and the cable step's status card |
| `soundboard/ui/setup/testtune.py` | the guide's test sound: a short 8-bit fanfare made in numpy |
| `soundboard/ui/setup/miclater.py` | *Your sounds aren't in your mic yet*: shown after a guide finished without the mic effect |
| `soundboard/ui/setup/steamguide.py` | the Steam voice chat help (where Steam picks the mic, its noise cancellation) |
| `soundboard/ui/setup/setupbackdrop.py` | the first launch's plain backdrop behind the guide: the loading screen hands over to its logo, which glides to the corner, and it fades to the app when the guide closes |
| `soundboard/ui/setup/coach.py` | Guided tours: the dimmed window, the yellow ring, one card with Bun and the step's button; holds clicks outside until the action step's Not now; something failing turns the card red (Try again, Close, Report a problem) and lets the window go |
| `soundboard/ui/kit/oops.py` | The red "didn't work" card: sad Bun, what went wrong, what to do, Try again and Report a problem (search results, the store, the radio map, the voice tab) |
| `soundboard/ui/setup/firsttour.py` | Bun's first-run tour of the empty board after that guide: the search box (or offline the Add button), the results, then "Nice" once a sound is added |
| `soundboard/ui/setup/tabtours.py` | Each tab's quick how-to on its first visit (Radio, Apps, Triggers, Voice, Store); Settings > General > Show tutorials |
| `soundboard/ui/bun/bunnywidget.py` | Bun animated: bobs, blinks, talks along with your mic and throws music notes |
| `soundboard/ui/bun/bunbits.py` | the animated Bun's timings, colours and small parts: blinks, springs, dancing to hits, the floating notes and the dust, junk and sparks round him (`bunnywidget` re-exports them) |
| `soundboard/ui/bun/bunbuild.py` | part of `BunnyWidget`: the building act (`build()`, `stop_building()`) and the dust, junk and sparks it throws |
| `soundboard/ui/bun/bundance.py` | part of `BunnyWidget`: dancing to what's playing and the springy layer over his pose |
| `soundboard/ui/bun/bunpaint.py` | part of `BunnyWidget`: painting his kept picture, the speaker and gadget he builds, the flying bits, his bubble, dust and scuffle |
| `soundboard/ui/bun/onionalien.py` | the Onion Alien, the author's mascot, drawn in code like Bun and Hoot: he says the note on Settings > About in a speech bubble, typed out a letter at a time |
| `soundboard/ui/bun/bunmode.py` | Bun mode: the mini player as a floating Bun over everything, showing what the app is doing |
| `soundboard/ui/bun/notebun.py` | Bun the note-taker: Send feedback's picture by its heading, a notebook in his paws, scribbling as picks are ticked and words typed, then a bow and a heart on Send; his box fitted to how he looks in the theme |
| `soundboard/ui/bun/pilotbun.py` | Pilot Bun: the Languages card's install picture, Bun flying a little 3D plane low over a lit, turning 3D Earth (numpy per pixel; the plane depth-buffered; rests after a while; still in lite mode) |
| `soundboard/ui/bun/scribebun.py` | Bun the scribe: the download banner's picture for a sound with no thumbnail, writing a well-known piece as sheet music on a scroll as the download comes in |
| `soundboard/ui/bun/bunpong.py` | the Easter egg: poke Bun enough and he challenges you to a game picked at random; the dialog the games play in (its sounds: `pongsounds.py`) |
| `soundboard/ui/bun/bunpongbase.py` | what Bun's games share: the court's colours and timings, sparks and speech bubbles, and `Game`, the base every game builds on (`bunpong` re-exports it) |
| `soundboard/ui/bun/bunpongcourt.py` | Pong itself (`Court`): serving, Bun's paddle guessing where the ball goes, your paddle, hits and rallies (`bunpong` re-exports it) |
| `soundboard/ui/bun/bungames.py` | Bun's other Easter egg games: dodgeball, home run, whack-a-Bun |
| `soundboard/ui/kit/choicetile.py` | ChoiceTile (a choice as a fixed-size tile: icon, name, tick, optional level bar; the setup guide's devices) and FoldPill (a small pill that opens something under it) |
| `soundboard/ui/setup/micupdate.py` | the offer to update the mic part: a card over the window a second after it opens; Windows is asked only after *Install update* |
| `soundboard/ui/setup/setupshow.py` | Bun building your mic on the Setup tab while Onion Board goes onto it (Windows asking, then loading) |
| `soundboard/ui/kit/reveal.py` | Boxes that fold away and out instead of blinking (the Setup tab's mic card), and the green flash when the mic starts working |
| `soundboard/ui/setup/whatsnew.py` | the *What's new* window shown once after an update, with what the release added, a button to the settings it's about and a link to the Discord (`NOTES`, newest first: add one per release) |
| `soundboard/ui/bun/splash.py` | the start-up splash: Bun's act, the name and chasing dots mid-screen while a cold start loads |
| `soundboard/ui/bun/splashacts.py` | Bun's start-up acts (one picked at random each launch), rare Buns, the season's hat, his goodbye wave |
| `soundboard/ui/settings/langpick.py` | the language picker (Settings → Appearance → Language): a drop-down of languages, each with its letter coin and its own name, with a search |
| `soundboard/ui/window/sidebar.py` | the tab rail down the main window's left: one icon per tab, opened out to show their names (the tab widget's own bar is hidden) |
| `soundboard/ui/window/railsizes.py` | the tab rail's sizes (shut, open, its buttons and icons), shared by the rail's parts |
| `soundboard/ui/window/railtabs.py` | the tabs on the rail: the tab widget whose own bar is hidden (`SideTabs`), a rail button per tab (`RailTab`), a tab's "New" pill |
| `soundboard/ui/window/onaircard.py` | the rail's On Air card (`OutputBlock`): the Live switch, who's listening, Stop all and the status lines under them (`Line`: offline, Tor, proxy, remote control) |
| `soundboard/ui/window/updatecard.py` | Onion Board's own update at the rail's foot (`UpdateCard`): a small card open, a button with a filling ring shut |
| `soundboard/ui/window/moretabs.py` | *+ More tabs*' dropdown: a card for each switched-off tab (its picture, what it's good for, Add) |
| `soundboard/ui/settings/lite.py` | lite mode (Settings > General): the switch the animations, Bun, the logo and the textures ask, and whether this PC looks slow enough to suggest it |
| `soundboard/ui/window/livesize.py` | the window's edge being dragged (Windows' WM_ENTERSIZEMOVE / WM_EXITSIZEMOVE): each step fits with Qt's cached sizes, letting go measures it all fresh |
| `soundboard/ui/window/livedot.py` | marks a tab whose feature is live (a highlight-coloured icon, with the rail's bar beside it, or a small dot), e.g. the Voice tab while your voice is being changed |
| `soundboard/ui/window/newsounds.py` | new sounds marked like unread mail: a glow on each new card until the mouse goes over it or you leave Sounds, and a count ("3 new", with an arrow while more are coming in) on the Sounds tab while you are elsewhere |
| `soundboard/ui/kit/glow.py` | `Glow(button)`: a slow accent glow round the one button a step wants pressed (the setup card's mic button) |
| `soundboard/ui/bun/logowidget.py` | the header logo animated: a breathing glow and sheen, flaring with embers while sounds play |
| `soundboard/ui/triggers/logoduel.py` | a silent laser exchange between the Board and Watch logos when clicked on the Triggers tab |
| `soundboard/ui/sounds/overlay.py` | the in-game overlay: a panel of pads that never takes focus, driven by number keys or clicks, on a chosen monitor and spot (or wherever it was dragged) |
| `soundboard/ui/sounds/overlaysettings.py` | the overlay's settings and where it goes: its keys, modes and positions, picking the monitor and placing it (`overlay` re-exports them) |
| `soundboard/ui/sounds/overlaywindow.py` | the overlay's window: the tiles and buttons, dragging, fading, following the game's monitor, painting in cached layers |
| `soundboard/ui/voice/voicepanel.py` | the Voice tab: lays out its cards and bottom bar; its parts are mixins in the four files below |
| `soundboard/ui/voice/voicecombos.py` | the Voice tab's side of My voice combos: what's on as a setup, turning one back on, its share code, picture and words |
| `soundboard/ui/voice/voiceswitch.py` | the Voice tab's on / off: each voice (voice changer, AI voice, computer voice) or all together with Undo, and the voice that's on saying the translated lines |
| `soundboard/ui/voice/voicecards.py` | the Voice tab's cards and tabs: each card's head and badge, switching tabs, the status bar's chips and the cards' on / off states |
| `soundboard/ui/voice/voicebar.py` | the bar of a voice with no cards of its own (the computer voice, a voice server's, Clean mic): picture, name, kind, Effects (none for Clean mic), Edit |
| `soundboard/ui/voice/voiceaddons.py` | the Voice tab's add-ons list and finding add-ons again (in the background, going on or offline) |
| `soundboard/ui/voice/cleanmicpanel.py` | the Voice tab's Clean mic card (its first tab): on / off, the Mic settings button (offering Strong's download when it's picked), your mic and the cleaned mic's meters, and Hear the difference (5 s recorded, played as it was and cleaned, in your headphones) |
| `soundboard/ui/voice/cleanmicsettings.py` | Clean mic's Mic settings, laid out like a voice chat app's: presets, Input volume, Input sensitivity (automatic or a level on a live bar), Noise suppression (Off, Light, Normal, Strong) and Automatic gain control |
| `soundboard/ui/voice/voicefxpanel.py` | the Voice tab's voice changer card (`VoiceFxPanel`): picking, saving and sharing voices, Edit voice's effect cards |
| `soundboard/ui/voice/voicefxtiles.py` | part of `VoiceFxPanel`: the voice tiles: rolling a random voice, hearing one, the tiles and where they go (grid or list, groups, favourites, search) |
| `soundboard/ui/voice/voicefxsaved.py` | part of `VoiceFxPanel`: your saved voices: naming, saving, renaming, deleting (with undo), a tile's menu, and voice codes |
| `soundboard/ui/voice/voicefxcards.py` | part of `VoiceFxPanel`: the effect cards: what's on top of the voice, the delay it adds, new effect types, folding and laying out the cards |
| `soundboard/ui/voice/voicetiles.py` | the voice changer's voice cards (`VoiceTile`), the groups they're shown in, their sizes, and `BigSwitch` |
| `soundboard/ui/voice/effectrow.py` | one effect's card in the voice changer (`EffectRow`) and which Edit voice tab it's on; `on_top`: an effect that isn't part of the voice |
| `soundboard/ui/voice/fxcontrols.py` | the voice changer's small controls: `Switch` and `ParamSlider` (an effect setting's slider with its name and value) |
| `soundboard/ui/voice/groupbar.py` | the bar over the voice cards on the Voice changer, AI voices and Languages cards: the group dropdown (with counts), the search box and the cards / list switch |
| `soundboard/ui/voice/backdroprow.py` | the voice changer's Background card (built-in sounds and board sounds behind your voice) and its Speed and pitch pop-up |
| `soundboard/ui/voice/effectspopup.py` | the voice bar's Effects pop-up: bundled CC0 background sounds, board sounds and the extra Robot, Radio, Echo and Reverb on top of any voice, one slider and a ✕ each |
| `soundboard/ui/sounds/voicepicker.py` | Edit sound → Effects → Voice: picture cards of the voice changer's voices, the AI voices and your setups, to lay a voice over a sound |
| `soundboard/ui/voice/voicesetupsbar.py` | the Voice tab's My voice combos row: save what's on, turn a setup back on, delete with Undo |
| `soundboard/ui/voice/speechpanel.py` | the Voice tab's Languages card: text-to-speech, live voice-to-speech, translation; its parts are mixins in the three files below |
| `soundboard/ui/voice/speechsay.py` | the Languages card's text-to-speech: saying a typed line, saving it as a sound, the computer voices and their settings |
| `soundboard/ui/voice/speechtiles.py` | the Languages card's language cards: their pictures, chips, favorites and the cards / list view |
| `soundboard/ui/voice/speechlangs.py` | the Languages card's translation: picking and downloading a language, the live voice speaking in it, who says the lines |
| `soundboard/ui/voice/livevoice.py` | the Languages card's live voice: Start, translating for the AI voice or voice changer, the helper's events |
| `soundboard/ui/voice/livesetups.py` | My voice combos in the three Live controls (`MainWindow.livesetups`): picks a setup, makes a sound again in its AI voice before it plays, Cancel |
| `soundboard/ui/voice/speechinstall.py` | the Languages card's downloads and installs: Windows voices, translation models, speech recognition |
| `soundboard/ui/voice/voicestatus.py` | the Voice tab's status bar: your mic level and a chip for everything changing what others hear |
| `soundboard/ui/voice/voiceservers.py` | the Add-ons tab's voice servers: a row each with whether it answers, its on / off switch and its settings |
| `soundboard/voicefx/` | the voice-effect chain and the built-in effects (pitch, robot, radio, …); `backdrop.py` makes the Background's loops; `cleanmic.py` is Clean mic, RNNoise run first on every mic block (its `rnnoise.dll` from `scripts/buildtools/fetch_rnnoise.py`; without it Clean mic isn't offered); `deepfilter.py` is its Strong, DeepFilterNet's plugin DLL downloaded on first use and run on a thread of its own |
| `soundboard/voicefx/builtin/` | the built-in effects, one family to a module: `pitch.py` (pitch, harmony, growl), `synth.py` (robot, singing monk, ring modulator), `tone.py` (compressor, tone, radio, distortion, shout, helmet), `modulation.py` (chorus, flanger, wobble), `space.py` (echo, reverb and the Effects pop-up's copies), `background.py`, `polish.py`; `parts.py` holds the filters, delay lines, STFT and pitch tracker they share, `presets.py` the built-in voices, `texts.py` their translated names. `__init__.py` imports them in the order they run (registration order is chain order) |
| `soundboard/speech/` | Windows text-to-speech (`tts.py`), custom voices — local TTS servers, TTS programs, Piper packs (`customvoices.py`), the live voice-to-speech client (`live.py`, `service.py`, `protocol.py`) translation model downloads (`translation.py`), which language you speak and the speech model that hears it (`spoken.py`) and one-click Windows voice installs (`winvoices.py`) |
| `soundboard/addons/modules.py` | finds, loads and installs add-ons in `modules\`: effects, services, translations and the Triggers tab's package (its host interface version checked first); installs a module zip only if it stays in its own folder; at start-up deletes old and half-swapped add-on copies, keeping the newest per add-on and any in use |
| `soundboard/addons/pocketaddon.py` | the Onion Pocket add-on (Settings → Remote → *Get Onion Pocket*): its latest GitHub release, downloading and checking it, installing it, and whether a newer one than the running copy is out (`check_update`, for the *Update Onion Pocket* button; `RemoteAccess.load_remote_addon` swaps it in); any failure is just `None` (`ONIONBOARD_ONION_POCKET_ZIP` uses a local zip instead) |
| `soundboard/online/firewall.py` | Windows Firewall rules for remote add-ons: Onion Board runs itself as admin (`--firewall-rule NAME PORT`, handled in `main.py`) so Windows' prompt names it |
| `soundboard/addons/aiaddon.py` | the optional AI voices add-on: its `ai-voices` GitHub release, downloading and checking it, installing and removing it (`ONIONBOARD_AI_VOICES_ZIP` uses a local zip instead). Not shipped with the app or its installer |
| `soundboard/speech/aivoice.py` | AI voices in the mic chain: `VoiceSource` (`VoiceChain.source`: talk gate with pre-roll, jitter buffer, the backup voice if the helper stalls) and `AiVoiceController` (starts the helper: a `ServiceHost` with audio coming back) |
| `soundboard/speech/soundvoice.py` | a sound said in an AI voice: runs the clip once through the AI voices helper (off the UI thread) and lines it back up |
| `soundboard/ui/voice/aivoicepanel.py` | the Voice tab's AI voices card: *Get AI voices*, install, remove, the add-on's voices; its parts are mixins in the three files below |
| `soundboard/ui/voice/aivoicecards.py` | the AI voices card's voice cards (chips, Favorites, cards / list, their pictures) and the bar under the voice that's on |
| `soundboard/ui/voice/aivoicemine.py` | the AI voices card's own voices (make, edit, delete with Undo), pitch and the backup voice |
| `soundboard/ui/voice/aivoicerun.py` | the AI voices card's settings, start / stop, CPU readout and what it says while starting, running or failing |
| `soundboard/ui/voice/aivoicebrowser.py` | the AI voices card's *Hear it* samples and the *Make your own voice* editor (blend two voices, deeper/brighter, how high) |
| `soundboard/speech/aivoicelist.py` | the AI voices to pick from: the built-in list (same as the add-on's `voices.json`), writing it and your own voices into the installed add-on (`sync`, so old downloads get new voices), and your own voices' file and bin (`%APPDATA%\OnionBoard\ai-voices.json`) |
| `soundboard/speech/aipreview.py` | *Hear it*: a Windows voice says a line, the add-on's converter turns it into the voice offline (its own Python, `-c`), kept for the run |
| `soundboard/addons/watchaddon.py` | the Onion Watch add-on: its latest GitHub release, downloading and checking it, installing it, and whether a newer one is out (`ONIONBOARD_ONION_WATCH_ZIP` uses a local zip instead) |
| `soundboard/online/ytdl.py` | yt-dlp for the link bar and web search, its names in one place (`ytdl.download_audio`, `ytdl.search`, ...): the code is in the four modules below; setting a name here (a test's stand-in) sets it where that code reads it |
| `soundboard/online/ytsites.py` | what ytdl's parts share: the sites and their switches (`site_of`, `site_allowed`), the errors, the lock that keeps a new yt-dlp from being swapped in mid-download, a search result (`Result`), and trying again when a site turns Tor away |
| `soundboard/online/ytupdate.py` | updating yt-dlp on request or opt-in: only versions listed in `pins/yt-dlp.json`, which `scripts/pinbump/ytdlp.py` adds after checking their PyPI attestations; wheels checked against the list's SHA-256 into `%APPDATA%`, loaded ahead of the bundled copy by an import hook; Force update, Reinstall, the daily check |
| `soundboard/online/ytfetch.py` | downloading one link's audio (yt-dlp in its helper process, or a Myinstants file directly), looking a link up, yt-dlp's options and its errors in plain words, keeping the video |
| `soundboard/online/ytsearch.py` | web search: YouTube / SoundCloud through yt-dlp, Myinstants' search and trending pages |
| `soundboard/core/jobprogress.py` | one download job's progress as one bar that only goes forward: looking the link up, the download (in parts too) and converting are stretches of it; `batch()` for the download bar's whole list |
| `soundboard/online/jsengine.py` | the JavaScript engine yt-dlp gets for YouTube's player challenge: Deno, Node or Bun if installed and new enough, else the bundled QuickJS (`scripts/buildtools/fetch_qjs.py`); none is fine |
| `soundboard/online/ytworker.py` | yt-dlp's look-ups and downloads in a helper process, so its long GIL-holding parsing never makes a sound stutter |
| `soundboard/audio/renderworker.py` | a slow effects render (a song said in an AI voice, a long sound) in a helper process at low priority, with progress and cancel, so it never stutters the audio or lags the window |
| `soundboard/sounds/thumbs.py` | pad pictures: a link's video thumbnail, a file's cover art / first frame (ffmpeg), or a picture you pick or drop on a pad, scaled into `%APPDATA%\OnionBoard\thumbs` |
| `soundboard/sounds/videos.py` | which pads came from a video (an imported video file, or a link added with *Also save the video*), in `videos.json` beside the config; `ui/sounds/videowindow.py` is the player's **Video** window, muted and kept in step with the pad's sound |
| `soundboard/ui/sounds/videowindow.py` | the player's *Video* window: a video pad's picture, following the pad's own audio (play, pause, seek, speed) |
| `soundboard/mic/savedvoices.py` | the voice changer's saved voices and their bin, in `%APPDATA%\OnionBoard\voices.json` (not the config, so older versions can't drop them), and their share codes (`OB1-…`: name + effect numbers, checked and clamped on import; the packing every code uses) |
| `soundboard/mic/voicesetups.py` | voice setups (a voice changer voice, an AI voice and a language under one name), in `%APPDATA%\OnionBoard\voice-setups.json` |
| `soundboard/core/trash.py` | Recently deleted: removed sounds (files and pad) and forgotten programs, kept 30 days in `%APPDATA%\OnionBoard\deleted` so they can be brought back |
| `soundboard/core/reset.py` | Settings → General → Reset: puts the parts picked (settings, hotkeys, sounds, the bin, programs, devices) back to the start at the next launch, after saving a restore point in `%APPDATA%\OnionBoard\restore-points` that undoes it |
| `soundboard/ui/bun/bunny.py` | Bun the mascot, drawn in code (setup guide and installer art) |
| `soundboard/ui/bun/bunpalette.py` | Bun's colours and the spots on his 100 x 120 canvas (`bunny` re-exports them) |
| `soundboard/ui/bun/bunshapes.py` | the small painting helpers Bun is drawn with: ellipses, glows, shading, strokes, arcs, his paw pads |
| `soundboard/ui/bun/bunprops.py` | what Bun holds and wears on top: his props, the nightcap, the music notes, stars and sparkles |
| `soundboard/ui/bun/bunskits.py` | Bun's idle skits, one per theme outfit (Blood Moon's cheese moon, Retro 98's "deal with it" shades, ...) and juggling for the rest: functions of time that pose him and queue drawings, played by `BunnyWidget` now and then while he's idle |
| `soundboard/ui/bun/bunacts.py` | Bun at work beside a window's title (`ActBunny`, an act on a loop and one-offs): snipping a waveform in Edit sound, the mic and a REC light in Record a sound, a bin in Recently deleted, a parcel in Free sound packs, a present in What's new |
| `soundboard/ui/bun/bunskitkit.py` | what Bun's skits are made of: the `Kit` a skit fills in for a frame, the timing curves and the small drawings they share (`bunskits` re-exports them) |
| `soundboard/ui/bun/bunskitsprops.py` | the theme skits from Blood Moon to Toxic: the cheese moon, the shades, the propeller, the frog's fly, ... the Geiger counter |
| `soundboard/ui/bun/bunskitsmoves.py` | the theme skits from Forest to Flashbang: the falling leaf, coffee, the coconut, ... the laptop and the flashbang |
| `soundboard/ui/bun/bunsymbols.py` | what flies out of Bun's headphones besides notes, by theme (every theme its own: Barbie's hearts, Vampire's bats and blood drops, Toxic's radiation signs, ...) and how each is drawn |
| `soundboard/ui/bun/bunbubble.py` | Bun's speech bubble, the same wherever he talks (his widget, the games, Bun mode): beside his face, its tail pointing at his mouth |
| `soundboard/audio/groove.py` | what the playing song sounds like, from the stretch just played: its tempo, where the beats fall and a guess at its style (rock, electronic, hip-hop, calm, speech), and whether it's music at all (a soundbite or someone talking isn't: Bun says it along with it instead); Bun mode's Bun dances to it |
| `soundboard/style/` | the style kit, shared with Onion Watch (which carries an exact copy; imports nothing else from the app, `tests/test_style_kit.py`): `palettes.py` (the themes' colours, `finish()` works out the derived tokens), `textures.py` (Textured's tiles), `bunnyfit.py` (Bun's outfit for each theme, drawn in layers by `bunny.py`; [MASCOT.md](MASCOT.md)), `owl.py` (Hoot alive, `OwlWidget`, wearing the same outfits; re-exports `owllooks.py`, his colours and look per theme, and `owldraw.py`, his shapes and `draw_owl`), `mascotlines.py` (what Bun and Hoot say when clicked, in each theme's character), `appstate.py` (`active`, `pause_in_background`, `snap_to_pixels`), `cover.py` (a still of a window, fading in and out over a theme switch: `ui/window/themecover.py` puts Bun on it), `hooks.py` (the current theme and translation, connected by `theme.py`) |
| `soundboard/sounds/pongsounds.py` | the Pong game's sounds, made in code: hits that climb a scale through a rally, chimes, cheers; a style of sound per theme |
| `soundboard/control/winkeys.py` | global hotkeys (`RegisterHotKey`, and when each is let go, for hold-to-play) and key presses (`SendInput`), no hooks |
| `soundboard/control/midi.py` | MIDI pad controllers as hotkeys (`midi:note 36:LPD8`): Windows' winmm over ctypes, a device opened only while a hotkey uses it, busy / unplugged devices retried |
| `soundboard/audio/replay.py` | instant replay: process loopback of everything but Onion Board into a ring buffer, saved as a pad on its hotkey |
| `soundboard/audio/appaudio.py` | the Apps tab's capture: lists the programs with an audio session (WASAPI sessions, over ctypes) and taps one program's audio with Windows' per-process loopback (a copy: the program still plays on your speakers), pushed into the engine as its own source; the one module the app, the mic helper and the tests use: the parts below are reached through it, and a name patched on it is patched in the part that uses it |
| `soundboard/audio/appcom.py` | appaudio's COM plumbing over ctypes: Windows' audio constants and interface ids, the structures, the `Com` wrapper, the device enumerator, playback devices' names and form factors, capture bytes turned into stereo float32 |
| `soundboard/audio/appprocs.py` | appaudio's running programs: each process's path, start time and .exe description, whether it still runs, its tree's root (shared helpers folded into the program that started them), window titles |
| `soundboard/audio/appmics.py` | Windows' endpoints asked now (not PortAudio's start-up list): whether a mic opens and is silent (the mic helper runs this, without numpy), a short recording of one, the active devices' names |
| `soundboard/ui/triggers/triggerstab.py` | the Triggers tab: Hoot (`style/owl.py`) and *Add Onion Watch to this tab* until the add-on is installed, then the add-on's own tab, with a bar when an update is out and a button to remove it |
| `soundboard/ui/window/taboff.py` | what stands in, hidden, for a tab switched off in *Settings → Tabs* (`Config.tabs_off`): the real Apps / Triggers / Voice tab is never built (Radio's stand-in is `RadioOff`) |
| `soundboard/ui/triggers/triggershost.py` | Onion Board as the Onion Watch add-on's host: the board's sounds and playing them (a ringing trigger loops in the headphones), `Config.screen`, the trigger pictures' folder, the theme's colours |
| `soundboard/ui/setup/alsosend.py` | Setup → Devices → *Also play on* (`cfg.also_send`): a row per extra output with a − button, and **+ Add a device**; each gets a copy of what others hear (`Engine.set_copy_devices`, one `CableTap` each). Also built into Settings → Audio |
| `soundboard/ui/apps/appspanel.py` | the Apps tab: one card per program (level, **Send**, call/stream output, volume, *Hear it myself*, and its *Clip editor*); recordings and editor saves go to Saved clips first, and Add to Sounds creates a pad; programs are remembered by .exe and folder |
| `soundboard/ui/apps/approw.py` | the Apps tab's cards (`AppRow`), their category headings and `AppGrid`, the program lister off the UI thread, and the .exe / folder keys programs are remembered by |
| `soundboard/ui/apps/approwparts.py` | part of an Apps card (`AppRow`): fitting it to its width, where it sends, and showing the program's state, status, sending, recording and icon |
| `soundboard/ui/apps/applister.py` | the program lister off the UI thread (`_Lister`) and the .exe / folder keys and saved volume (`approw` re-exports them) |
| `soundboard/ui/apps/appcapture.py` | the Apps tab's capture, Record and clip editor half (`AppsTab.capctl`): one capture per card while it's sent, recorded or its clip editor listens; saving to Saved clips |
| `soundboard/ui/apps/windowview.py` | the Apps tab's eye button: a small live picture of a program's window under its card (a worker grabs about 4 a second, only while open, on screen and the app is in front) |
| `soundboard/win/winshot.py` | finds a program's main window and copies a shrunk picture of it (PrintWindow + halftone StretchBlt); says when it's minimised, gone or black |
| `soundboard/win/exeicon.py` | a program's icon read from its .exe on the thread that listed the programs, not on the UI thread (the shell call held the GIL and made sounds skip) |
| `soundboard/mic/directmic.py` | straight into my mic: what the app asks of the mic effect (install / repair / remove through the mic helper or Windows' prompt, why a step failed, in words); the one module the app, the helper and the tests use: the parts below are reached through it, and a name patched on it is patched in the part that uses it |
| `soundboard/mic/micbase.py` | the mic effect's names and places, shared by its parts: its COM class, the registry keys and effect slots it uses on a mic, where its files go |
| `soundboard/mic/micring.py` | the mic effect's ring (the shared file the board writes what others hear into and the effect publishes the clean mic through) and `DirectMicStream`, the send output on the mic's clock |
| `soundboard/mic/micstate.py` | the mic effect on this PC's mics, read without admin: the recording devices, which carry the effect, its status and the repair checks |
| `soundboard/mic/micadmin.py` | the mic effect's admin part, all the mic helper runs: putting it on a mic and taking it off, Windows' audio restarted around it (mic apps, SteelSeries Sonar, mics left silent), `cli` |
| `soundboard/mic/sonarkeep.py` | while the app's mic is SteelSeries Sonar's: Sonar's devices noted while the mic works, and set back when Windows' audio restarted and Sonar moved them (its mic onto a silent cable); the look-ups and the setting are directmic's |
| `soundboard/core/cleanup.py` | `OnionBoardCleanup.exe`, the separate download (the `cleanup-tool` release) that takes everything of Onion Board off a PC whose uninstall didn't finish: the mic effect off every mic through `directmic`'s own uninstall, the mic helper, the app folder, its Installed apps entry, shortcuts, start-up entry, `ProgramData\OnionBoard`; the user's sounds only if they say so. Built by `scripts/buildtools/build_cleanup.py` |
| `soundboard/core/uninstallclean.py` | the uninstaller's tidy-up of what's outside the app's folder (`OnionBoard.exe --uninstall-cleanup [--data]`): Onion Pocket's firewall rule, and on the user's Yes their `%APPDATA%\OnionBoard` (to the Recycle Bin) and `ProgramData\OnionBoard`; one admin prompt, only when one of those needs it |
| `soundboard/mic/michelper.py` | the mic helper: the first admin prompt also installs `obmichelper.exe` (the admin part alone, with its own effect DLL) in Program Files and an on-demand SYSTEM scheduled task; after that, setting up, repairing, switching mics and removing go through it without a prompt. Only another effect DLL asks again |
| `soundboard/mic/safefs.py` | folder work for the mic effect's admin step and the mic helper in folders other accounts can write to: a folder opened once and checked to be a real one, everything in it opened, read, renamed and deleted relative to that handle, links removed and never followed |
| `soundboard/mic/micprobe.py` | after a set-up works: a quiet probe played into the mic only, found again in the mic by cross-correlation (`score`); other mics with sound before the set-up (`alive`) that send only zeros after it were cut off by it (an app between the mic and a voice chat) |
| `soundboard/mic/mictest.py` | the quick setup's mic test, its last result (pass / fail, when) under HKCU\Software\OnionBoard: the uninstaller's feedback form reads it |
| `soundboard/mic/rawmic.py` | apps that record the mic in raw mode (Discord's Studio profile, some games), which skips the mic effect and so hears none of the sounds |
| `native/directmic/` | the mic effect (`obmic.cpp`, runs inside Windows' audio engine) and `testhost.cpp`, which loads it like Windows does for the tests; `fuzzhost.cpp` throws hostile ring files at it (`scripts/directmic/fuzz_directmic.py`) |
| `soundboard/audio/engine.py` | real-time audio: WASAPI streams (mic in, what others hear out (your mic, the cable or another device), headphones out, the optional stream output for OBS), mixing (sounds, radio and captured programs), pause/seek, live speed / pitch, limiter, watchdog. `Engine` itself holds the state and what the UI calls (play, stop, seek, captured programs, radio); the parts below are reached through `engine`, and a name patched on it is patched in the part that uses it |
| `soundboard/audio/devicelist.py` | the sound devices PortAudio lists: finding one by its saved name, which are virtual cables and each one's mic side, opening an output at its native rate, `CableTap` (a copy of what others hear played into the cable) |
| `soundboard/audio/enginerender.py` | the engine's mixing (a mixin `Engine` inherits): the voices playing on an output read into a block at the live speed, then the sounds bus's pitch, live effects, EQ and the destination's processing |
| `soundboard/audio/enginebus.py` | the engine's stream callbacks and their buses (a mixin `Engine` inherits): what goes out on the send, the headphones and OBS's device, the mic block and what it feeds, the send's limiter, gate and howl guard |
| `soundboard/audio/engineparts.py` | the engine's plain parts: the ring buffers between audio clocks, the stream resampler, the sounds' `Voice`, captured programs' `AuxSource`, the live pitch shifter, the device thread and the small sample helpers (`engine` re-exports them all) |
| `soundboard/audio/soundcache.py` | the engine's sound cache (a mixin `Engine` inherits): each sound's copy at a device's rate, made once off the audio thread, and its low-cut shares; `prepare`, `forget` |
| `soundboard/audio/enginedevices.py` | the engine's devices (a mixin `Engine` inherits): opening each output and the mic at its native rate, the straight-into-my-mic stream and its cable copies, the watchdog that reopens a stalled stream, `shutdown` |
| `soundboard/audio/enginetakes.py` | the engine's recordings (a mixin `Engine` inherits): starting, stopping and handing over the setup test's recording and the mic / playback takes |
| `soundboard/audio/howl.py` | the howl stopper: *Hear what they hear* on speakers can make the mic hear itself and squeal; `HowlGuard` (run on the mic block by the engine) catches one loud pure note that holds still and switches the playback off. `is_speaker` tells a speaker from headphones for the warning when it's turned on |
| `soundboard/audio/eq.py` | 7-band equalizer and presets: matched peak / shelf bands that keep their analog shape up to Nyquist; a change crossfades in (no clicks) |
| `soundboard/audio/dsp.py` | the app's own filter maths (it no longer imports scipy): `sosfilt` / `lfilter` run as block matrix products with a parallel prefix scan for the state (float64 state, so float32 audio stays accurate), Butterworth design, matched EQ bands, `SmoothSos` (click-free design changes), an O(n) running minimum |
| `soundboard/online/net.py` | every outgoing connection (Settings → Privacy & security), its names in one place (`net.urlopen`, `net.allowed`, ...): the code is in the four modules below; setting a name here sets it where that code reads it, and the setting's state is read from where it lives |
| `soundboard/online/netconfig.py` | the Connection setting (direct, or a SOCKS5 / HTTP proxy, or Tor) and the per-feature switches and Offline mode, which refuse a switched-off feature's requests before any lookup; the features' names, the proxy address, who is told of a change |
| `soundboard/online/netconnect.py` | `connect()`: straight to a site, or through the proxy / Tor with names resolved by the proxy and no fallback to direct; the Test button; cutting off open sockets when the setting changes |
| `soundboard/online/nethttp.py` | `urlopen(feature=…)` for urllib: connections through `connect()`, each response counted in the activity list, the shared TLS context, redirects that may not lead into the home network, capped reads |
| `soundboard/online/netrelay.py` | a loopback relay (per-launch secret, the feature as its user name) for FFmpeg, yt-dlp, Qt's network managers and child processes, in every mode, and the environment those get (`child_env`, `own_env`) |
| `soundboard/online/netlog.py` | Connection → *Network activity*: every connection `net.py` makes or refuses (feature, why: the click or timer that caused it, server, route, result, bytes each way, request lines and TLS where the app can read them), in memory only unless *Keep a history* is on |
| `soundboard/ui/settings/netactivity.py` | the *Network activity* view: Simple (one row per server) and Detailed (one row per connection, with everything about the picked one), Copy and Clear |
| `soundboard/online/tor.py` | the app's own Tor (Connection → *Tor*): starts `tor.exe` only when needed, writes its torrc in `%APPDATA%\OnionBoard\tor`, ties it to the app with a job object, speaks its control port (cookie auth, bootstrap progress, `NEWNYM`) and hands `net.py` its SOCKS port once connected; optional Snowflake / obfs4 bridges |
| `soundboard/online/torget.py` | *Get Tor* (Settings, and the installer's Tor box via `OnionBoard.exe --get-tor`): downloads the Tor Expert Bundle through `net.urlopen`, checks its pinned SHA-256 and unpacks only tor.exe, lyrebird, pt_config.json and the licences into `%APPDATA%\OnionBoard\tor\bin` (the app doesn't ship Tor) |
| `soundboard/online/ffmpegget.py` | *Get FFmpeg* (Settings > Data & quality): runs the installer's own install (the `Gyan.FFmpeg.Essentials` package through `winget`) so M4A, AAC and video files can be played and added without re-running the installer; the app doesn't ship FFmpeg |
| `soundboard/online/pyget.py` | a Python for the add-ons that run in their own environment (live voice, AI voices): the PC's own 3.12 or 3.13 when it has one, else python.org's build (its nuget.org package, SHA-256 pinned) unpacked into the add-on's own `.python` folder, which goes with the add-on; the app doesn't ship Python |
| `soundboard/online/quality.py` | Settings > Data & quality: download size, keeping the video, the radio's bitrate cap and patience, and web search extras (low data mode) |
| `soundboard/online/radio.py` | Radio tab back end, its names in one place (`radio.RadioPlayer`, `radio.Station`, ...): the code is in the four modules below; setting a name here sets it where that code reads it |
| `soundboard/online/radiostation.py` | Radio Browser's addresses, a station (`Station`) and which stream may be played from it, searching text, reading the directory's answers gently, what to say when it can't be reached |
| `soundboard/online/radiomap.py` | the map's data: its land outlines (shipped, SHA-384-checked) and country labels, each station's dot, the town names |
| `soundboard/online/radiodir.py` | the Radio Browser directory client (`RadioDirectory`): stations for the map (a day's cache), search, the click a station start sends; the bitrate cap and patience from Settings > Data & quality |
| `soundboard/online/radioplayer.py` | the stream player (`RadioPlayer`): Qt Multimedia decodes, a `QAudioBufferOutput` hands 48 kHz PCM to the engine, dropped streams are reopened; the decoder's DLLs preload on a thread when the tab first opens |
| `soundboard/ui/radio/radiopanel.py` | the Radio tab: search bar, the map (click a dot to play), station list, favourites, Send / record / last 15 s, the now-playing strip |
| `soundboard/ui/radio/radiomap.py` | part of `RadioTab`: the flat map, its dots and town labels, picking a station on it, the popular and remembered stations, and the directory being down |
| `soundboard/ui/radio/radiosearch.py` | part of `RadioTab`: searching as you type, the matches already known, and the phone remote's station lists |
| `soundboard/ui/radio/radioinfo.py` | part of `RadioTab`: the info line, the now-playing title and buttons, favourites, the Live switch, fitting a narrow window, volume, hearing and recording |
| `soundboard/ui/radio/radiobits.py` | the Radio tab's timings and list sizes and its steady-width button text (`radiopanel` re-exports them) |
| `soundboard/ui/radio/radiolist.py` | the Radio tab's station list (`RadioTab.listctl`): Popular / Favorites / Recent, the genre chips, country / quality / sort filters and the painted station rows |
| `soundboard/ui/radio/flatmap.py` | the Radio tab's world map, painted by Qt (no web engine): dots, town names, zoom and drag; it re-exports the names of the pieces below |
| `soundboard/ui/radio/mapparts.py` | the Radio map's small parts: Bun's loading card, colour fills, the stations' dot sizes and glow, moving dots that would cover each other apart |
| `soundboard/ui/radio/maptiles.py` | `MapTiles`, a mixin of `FlatMap`: the world drawn in tiles once per zoom, a slice at a time, with the last whole view stretched in for them meanwhile |
| `soundboard/ui/radio/maplabels.py` | `MapLabels`, a mixin of `FlatMap`: where the country names go at each zoom, drawn once over the stations popping in |
| `soundboard/ui/kit/appstate.py` | stops decorative animations (logo, mascots, live dot) while another program is in front |
| `soundboard/ui/apps/clipeditor.py` | the Apps tab's clip editor, folded away under each card until opened: the live waveform of the program's last minute, drag to select, preview in headphones, Save to clips, the Edit menu and its keys |
| `soundboard/ui/apps/clipshelf.py` | the Apps tab's *Saved clips* and the Voice tab's *Recordings* (one widget): rows painted by `ClipRowDelegate` (round play button, name, where · when, waveform that fills as it plays, Live pill, length), one set of row buttons (through mic, add to Sounds, more) that follows the hovered or picked row; search, app/day groups, batched rows, background inactivity cleanup and waveform drawing; Space / double-click plays, Enter sends, Esc stops, F2 renames, Del deletes (Undo bar) |
| `soundboard/ui/apps/cliprows.py` | how the clips list draws its rows: the row sizes, `ClipRowDelegate`, the length and date text and the resize handle (`clipshelf` re-exports them) |
| `soundboard/ui/apps/clipshelfactions.py` | part of `ClipShelf`: playing, sending, renaming, adding, copying and deleting clips, their menu, and the clean-up with its undo |
| `soundboard/sounds/clipshelf.py` | saved clip FLACs and their `index.json` in `%APPDATA%\OnionBoard\clips` (Recordings: `voice-clips`); creation and last-use times, 48-bar waveform `peaks` (drawn on save, `fill_peaks` for older clips), seven-day retention, bulk deletion and restoration; cleanup files go after Undo expires, manual deletions on the next start |
| `soundboard/sounds/clipedit.py` | the clip editor without the window: `LiveBuffer` (the last minute and its waveform, filled on the capture thread) and `Take` (cut, paste, fades, gain, reverse, with undo capped by memory) |
| `soundboard/audio/recorder.py` | the Radio tab's clip recorder: a rolling last-15-seconds buffer plus a recording spooled to disk; `MicTake`, a mic (or what's-playing) recording spooled the same way (Record a sound) |
| `soundboard/audio/mapped.py` | long sounds stay on disk: decoded cache files over ~30 s (or past a RAM budget) are memory-mapped, and warmed (first second read, the next two minutes prefetched) before they play; the engine keeps the minutes ahead prefetched while they play |
| `soundboard/core/memtrim.py` | memory back to Windows: 30 s in the tray or minimised with nothing playing, garbage is collected and the working set emptied (Task Manager ~350 -> ~35 MB); `ui/window/tickcontrol.py` decides when |
| `soundboard/sounds/library.py` | the sound library's names in one place (`library.Config`, `library.load_sound`, ...): the code is in the modules below; setting a name here (a test's temporary folder) sets it where that code reads it |
| `soundboard/sounds/paths.py` | where the library keeps its files: `APP_DIR` (`%APPDATA%\OnionBoard`) and the sounds, cache, pad pictures and `config.json` in it, read as `paths.X` when used so they can be pointed elsewhere |
| `soundboard/sounds/config.py` | the settings (`Config`) and each sound's (`SoundMeta`): defaults, what a saved value may be (`clean_setting`), loading `config.json` (backups, salvage, older and newer versions, the move from `%APPDATA%\Soundboard`) |
| `soundboard/sounds/saving.py` | writing `config.json` atomically with rotated backups and the `privacy.json` copy, on a background thread (`Saver`) so a slow disk never freezes the window |
| `soundboard/sounds/tags.py` | sound categories and their *Category / Sub* subcategories: cleaning typed names, matching the board's spelling, which sounds a Sounds tab view shows |
| `soundboard/sounds/levels.py` | int16 / float32 audio, loudness levelling (`level_gain`), waveform peaks, trimming the silence off a recording |
| `soundboard/sounds/cachefiles.py` | the int16 decoded-audio cache (plus each sound's rendered effects version, `render_cached`), and pruning what no sound uses |
| `soundboard/sounds/decoding.py` | decoding (bounded to 2 h; long sounds streamed into the cache a second at a time), loading a sound as it plays (`load_sound`), and writing the library's own copies (MP3 or FLAC) |
| `soundboard/sounds/files.py` | the sound files in the library's folders: names, imports and clips, duplicating, deleting (to the Recycle Bin) and tidying files from older versions |
| `soundboard/win/winpath.py` | paths through folder links newer Windows 11 refuses to follow (error 448): the same path resolved past the link |
| `soundboard/win/systools.py` | Windows' own tools (netsh, taskkill, powershell, schtasks…) by their full path in System32, never found by name in a folder someone else can write to |
| `soundboard/core/usage.py` | the anonymous usage count (*Count me in*, feature `usage_stats`): a daily "still here" to GoatCounter with the version and a random `stats_id`, a one-off first start (with the installer's *Where did you hear about Onion Board?* answer, tidied by `heard_tag`) and *Update now*; with the daily one the tabs opened (`stats_tabs`) and `about()`: age, route, sound and play buckets, language and the `FEATURES` used (`used()` → `stats_used`, kept at quit by `remember`); a new install's first `STEPS` once each (`step()`; `settle` marks them done for copies counted before); problem counts soon after a start (`crash/` `error/` `freeze/` per new report in `crash-reports\`, plus the error type and the deepest `soundboard/…py:line` of its stack (`_report_event`; never the message; a freeze also its caller, the library call it was stuck in, how long it lasted and who was busy: `_freeze_tag`), past `stats_problems_seen`, `unclean-exit/<version>/<why>` when `running.txt` was left by a run that never reached `mark_stopped`; the why from `exitwatch.py`), `startup-failed/<version>` (with the native stacks or Windows' error) when `bootmark.py`'s `starting.txt` was left by a run that died during start-up, and `warned/<version>/<type>@<soundboard/…py:line>` (`warned()`, from `errors.warn`/`html`, or `warned_at()` for the mic effect's admin step raising, read back from its log by `directmic.raised_why`) for a reportable problem the app handled and showed itself, and `failed/<version>/<what>/<detail>` (`failed()`, `FAILED`) for a failure whose fixed reason was only "other" or "timed out": the type and place from `error_detail`, a number or `timeout_kind`'s word); installed copies only, never from source. `--usage-count on/off` is the installer's box, `--uninstall-count` the uninstaller's `uninstall/<version>` |
| `soundboard/core/usagenames.py` | every name the usage count may send: the tabs, `FEATURES`, the download and mic-effect failure reasons, the first `STEPS`, the routes, the Improve picks, the language and Twitch login patterns (`usage` re-exports them) |
| `soundboard/core/usagetags.py` | the usage count's words, pure functions that send nothing (usage.py re-exports them): `user_tag` (the hashed `ref`), `heard_tag` (the installer's answer, `HEARD`), `other_tag` (typed words, dashed, with addresses and numbers dropped), `download_site` (`DL_SITES`), the rough buckets (`bucket`, `age_bucket`, `open_bucket`, `download_bucket`, `launch_bucket`, `ach_bucket`, `score_bucket`), `os_tag`, `theme_tag` and `ach_tag` |
| `soundboard/core/usagereports.py` | the usage count's problem events, read out without sending (usage.py re-exports them): `problems` (each new report in `crash-reports\` as `_report_event`: the kind, version, error type and our own `soundboard/…py:line`, a freeze's `_freeze_tag`), `mark_running` / `mark_stopped` (`running.txt`, for `unclean-exit/`), `startup_failed`, and `_tb_where` for `warned()` |
| `soundboard/core/continents.py` | each country's continent (ISO code), for Seven Seas in `core/achievements.py` |
| `soundboard/core/achievements.py` | Settings > Achievements' counting, kept on this PC (the usage count sends only which were earned, how many and their score, roughly): `ALL` (each achievement's stat, goal, rarity, hidden), `POINTS` (each rarity's worth: `score()`), counts and sets in `cfg.achievements` fed by `usage.used()` (`EVENTS`), plays, radio stations, Store upvotes, themes, voices, sounds added (`sounds_now`) and the voice / apps / radio live time (`live()`, added up on the window's usage tick: no timer of its own); `on_unlock` feeds the pop-up (`ui/window/achievepop.py`). The page is `ui/settings/achievements.py`; its badges are Bun drawn in a scene per achievement by `ui/settings/badges.py` (`SCENES`: draw_bunny's props, poses, outfit pieces and rare looks, an icon chip, a backdrop), unless `assets/art/achievement-<id>.png` exists |
| `soundboard/core/enjoy.py` | when *Enjoying Onion Board?* is due: open time per day (`enjoy_days`, fed by `usage.open_tick`), due after `DAYS_NEEDED` days of `DAY_S` or more, `enjoy_state` done once it has shown |
| `soundboard/ui/settings/countdialog.py` | *What Count me in sends*: the table behind the eye button by Settings' *Count me in* (keep it in step with `usage.py` and SECURITY.md) |
| `soundboard/ui/kit/theme.py` | the current theme (its colours from the style kit's `palettes.py` → stylesheet, also read by the painted widgets); it re-exports the logo and the style sheet text |
| `soundboard/ui/kit/themesheet.py` | the app style sheet's text (`STYLE`, `POLISH_STYLE`, `OUTLINE_STYLE`), filled with a theme's colours by `theme.stylesheet()` |
| `soundboard/ui/kit/indicators.py` | the pictures the style sheet draws controls with (tick, radio circle, chevrons), painted in the theme's colours and saved to the temp folder |
| `soundboard/ui/kit/logo.py` | the app logo: the onion mark (a jack-o'-lantern in Halloween), `app_icon`, `logo_pixmap`, `logo_image` |
| `soundboard/ui/settings/settings.py` | Settings (a page inside the main window: `MainWindow.open_settings`): the dialog, its search and its card helpers; the pages are in `ui/settings/` (`HOTKEY_ACTIONS`, `HotkeyDialog` and `pretty_key` still import from here, for older code) |
| `soundboard/ui/kit/hotkeypick.py` | hotkey names and the key picker: the global hotkey actions (`HOTKEY_GROUPS`, `HOTKEY_ACTIONS`), how a combo reads (`pretty_key`) and the window asking for one (`HotkeyDialog`). Pads, menus, Edit sound and Settings import them from here, so none of them loads the Settings window |
| `soundboard/ui/settings/` | Settings' pages, one module each (`help.py`: Add-ons and About, `audio.py`, `appearance.py` (with the theme cards), `keys.py`: Hotkeys and Overlay (with the hotkey capture dialog), `general.py`, `connection.py`: Connection and Updates, `privacy.py`: Privacy, Data and Offline mode, `addons.py`: Add-ons and Remote, `heading.py`: the heading row). Each is a QObject the dialog owns (`SettingsDialog.<page>`, `Page` in `__init__.py`); the widgets they build stay on the dialog (declared on `Built`, which it inherits) |
| `soundboard/ui/setup/audiorecovery.py` | Settings audio recovery card, confirmation dialogs and background mic-effect repair, clean reinstall and removal |
| `soundboard/ui/kit/wheelguard.py` | mouse wheel scrolls the page instead of changing sliders / dropdowns (installed per widget); the app style (`AppStyle`): snug dropdowns, and submenus that open just outside their menu |
| `soundboard/core/exitwatch.py` | a black box for the next start: `last-run.json` (heartbeat every 30 s, window stuck or not, a quit started) and `native-crash.txt` (faulthandler's stacks on a native crash), armed `arm_early` (app.py, before the window) and again at `start()`, emptied at a clean quit. After an unclean exit `check_last` reads them plus Windows' Application log (wevtutil, this run's pid) and says why (`native-crash`, `windows-error`, `not-responding`, `while-closing`, `frozen`, `pc-restarted`, `ended`): in the usage event and a report in `crash-reports\` (not counted again as an error) |
| `soundboard/core/profile.py` | the profile folder: `%APPDATA%\OnionBoard`, `OnionBoard-dev` for a source copy in the temp folder (a throwaway worktree), or `ONIONBOARD_PROFILE_DIR`. Small, so `bootmark.py` and the splash read it before the sound library loads |
| `soundboard/core/bootmark.py` | the start-up breadcrumb: main.py leaves `starting.txt` (version + pid) before the heavy imports, and app.py removes it once `running.txt` is written; a crash report applog.py saves before that removes it too (that report is the trace, counted as `error/`). One still there at the next start means the last run died during start-up, counted as `startup-failed/<version>` (usage.py); also `startup-stall.txt`: from the loading screen until the window is up, faulthandler writes every thread's stack in it every 10 s (`watch_stall` / `stop_stall`), so a slow start says where it waited |
| `soundboard/core/installmark.py` | is the installer replacing the files right now: `installer/OnionBoard.iss` leaves `installing.txt` beside the exe from `ssInstall` until it opens the app again, and main.py quits quietly on a normal start while it's there (before importing anything else of the app; only `os`, `sys`, `time`). Also `ONE_OFF`, the installer's and other one-off commands that still run |
| `soundboard/core/invite.py` | Invite a friend: the onionalien.com/invite/ link with a name on it (Settings → About), the name rule the site and the installer share, and the installer's `invited-by` note for the first start. Nothing is counted or sent |
| `soundboard/core/applog.py` | rotating log in `%APPDATA%\OnionBoard\onionboard.log`, written on its own thread (a log line never waits for the disk); unhandled exceptions (any thread) and Qt warnings land there; each distinct crash is saved, scrubbed of personal paths, to `crash-reports\` with no window (the usage count sends its type and line a minute later, `on_problem()`; Settings → About lists this run's, `recent()`); only one that stops the app starting shows the dialog. `report()` does the same for an error code caught but didn't expect. The PC's situation (disk full, a file in use, access denied, no memory, network down) is said in plain words instead, with no report saved. `ONIONBOARD_DEBUG=1` for more. *Keep an app log* off (config `app_log`): memory only, the last lines kept for crash reports |
| `soundboard/ui/kit/feedbackdialog.py` | *Send feedback*: "What would you improve?" picks (sent with the usage count, `usage.improve`), then a thank you with the feedback form |
| `soundboard/ui/kit/failreport.py` | "Didn't work? Send us a report" under a mic failure (the setup guide's mic test, the mic effect's set-up): shows what the feedback form gets, then opens it (`feedback.micfail_url`) |
| `soundboard/ui/kit/crashdialog.py` | the "Onion Board hit a problem" dialog (when start-up fails, or *See report* in Settings → About): the report, *Copy report*, *Report on GitHub* (copies it, opens a new issue in the browser), *Open folder* |
| `soundboard/mic/testcheck.py` | analysis for the Record-6s test (finds your voice in the output by cross-correlation) |
| `soundboard/mic/destination.py` | destination modes (Setup tab / Settings → *Who's listening*), one per voice chat engine: shapes the sounds bus for the listener's voice codec — sub-bass harmonics, a low cut with each sound's level given back, codec ceiling, gentle compressor (custom modes), mono |
| `soundboard/mic/sharestore.py` | `destination.cut_shares` of long sounds kept on disk between starts, keyed by the cache file's name, size and time |
| `soundboard/mic/profiles.py` | the simple sound modes over *Who's listening*: Game, Voice chat, Clean, Advanced. Each is a family of destination modes and picks one from detector `Hint`s (what voicesdk sees); a later per-program list would be one more detector. Stored as `dest["simple"]` beside `dest["mode"]` |
| `soundboard/mic/appsetup.py` | the *Looks like you're using Discord. Set up for it?* bar: when a voice chat app or a game starts listening, offers the simple mode that suits it once, then switches by itself the next time (with Undo) |
| `soundboard/mic/voicesdk.py` | which *Who's listening* mode suits: first the program recording what others hear (`Listeners`: your mic on the mic route, plus the virtual cable's far end; Discord, TeamSpeak and Mumble by name, a game by its files), else the voice engine of the game in front, from the voice libraries in its install folder (the exe path is read with the least access Windows has; nothing touches the game). A suggestion, switched to by itself only when the picker's box says so |
| `soundboard/ui/sounds/deleted.py` | the Recently deleted window (Bring back / Delete for good) |
| `soundboard/ui/settings/resetguide.py` | the Reset guide (pick → check → reset and restart) and the Restore points window |
| `soundboard/ui/setup/destpanel.py` | the mode picker and the custom-modes editor |
| `soundboard/sim/codecsim.py` | development bench: runs audio through Discord's and ~20 game voice stacks' Opus pipelines (ffmpeg's libopus, plus Discord's ~94 Hz capture high-pass, measured in a real call) and measures what's lost, including a frame-by-frame spectral distance that hears noise fill and warble |
| `soundboard/sim/chatsim.py` | development tool: simulates a voice chat's mic cleanup (noise suppression, gain control, gate) so the bench and tests can measure it and check the Discord check against it |
| `soundboard/sim/realproc.py` | development tool: the same mic cleanup with the real libraries (WebRTC's audio processing via LiveKit, RNNoise), from the bench environment (`requirements-bench.txt`) |
| `soundboard/sim/proxsim.py` | development tool: proximity chat on the listener's side (distance fade, walls, walkie-talkies and radios) from each game's published or decompiled defaults |
| `soundboard/sim/chatcheck.py` | the Discord check: a test sound, and how to tell from Discord's Mic Test playback whether its noise suppression, gate or gain control is changing your sounds |
| `soundboard/mic/discordcfg.py` | Discord's own voice settings, read from its files (its LevelDB web storage, read only): which ones are wiping out sounds |
| `soundboard/mic/discordtalk.py` | puts Discord's voice clean-up back the way you talk when the board closes: one record appended to its LevelDB log, only while Discord is closed (else the `--discord-restore` helper waits for it to close), after a backup |
| `soundboard/ui/setup/chatguide.py` | the Discord and game voice-chat guides (the settings that keep sounds clean) and the check that runs from them |
| `soundboard/ui/setup/streamguide.py` | the streamer guide for remote control (Stream Deck keys, channel points, chat commands, with the links to copy) and the prompt that lets an AI assistant set it up |
| `soundboard/audio/sendfx.py` | the send stage before what others hear (your mic, the cable or another device): phase-aware mono downmix, lookahead peak limiter, ducking under your voice, levelling your voice |
| `soundboard/mic/cableremove.py` | the Setup tab's *Remove the virtual cable* (offered once straight into the mic works): runs VB-Audio's own setup program from Program Files with `-u -h`, as admin; other kinds of cable are left alone |
| `soundboard/mic/cableformat.py` | reads both ends of the virtual cable's Windows format and sets them to 48 kHz, so the cable passes sound through unconverted |
| `modules/` | add-ons shipped with the app: `retro-fx` (an effects module, the example to copy), `live-voice` (a service module with its own Python environment) and the `translate-<language>` modules, one per *Speak in* language (a manifest naming a model that's downloaded only when picked). Remote add-ons such as Onion Pocket are installed into `%APPDATA%\OnionBoard\modules`. `ai-voices` (real-time voice conversion: onnxruntime + a Beatrice 2 model, see its README) lives here too but isn't built into the app: it's downloaded from its own release (`scripts/buildtools/make_ai_voices_zip.py` packs it) |
| `build.ps1`, `installer/` | the PyInstaller build and the Inno Setup installer (`installer/OnionBoard.iss`); `installer/install-vbcable.ps1` downloads VB-Cable, checks its signature and installs it (used by the app and the installer) |
| `assets/onionboard.ico` | the .exe, installer and shortcut icon, generated by `scripts/pictures/make_icon.py` |
| `scripts/` | Subfolders hold the development-only tools: `pictures/` (the README and website screenshots, promo art, icons, Bun's installer art and picture sheets), `voicetests/` (measuring what game and Discord voice chat do to the sounds), `directmic/` (building, checking, fuzzing and kill-testing the mic effect) `checks/` (the checks precommit and CI run: translations, types, the module table, sound packs, UTC commit times) and `buildtools/` (the steps `build.ps1` runs, the add-on zips and the downloads a build or a source run needs); everything else sits at the top. `install.bat` / `install.ps1` / `run.bat` (run from source: set up `.venv` and shortcuts, then launch), `directmic/build_directmic.py` (builds the mic effect `obmic.dll` with MinGW-w64's g++; `--testhost` also builds the test host), `buildtools/build_cleanup.py` (freezes `soundboard/core/cleanup.py` into the one-file `dist\OnionBoardCleanup.exe` for the `cleanup-tool` release), `buildtools/build_michelper.py` (freezes the mic helper `obmichelper.exe` with the effect DLL into `build\michelper`; a `--console` build with its Python archive beside the .exe, both to avoid antivirus false positives; warns but still builds on PyInstaller's stock bootloader), `buildtools/build_bootloader.ps1` (rebuilds PyInstaller in `.venv` with a bootloader compiled by gcc, as virus scanners flag the stock one; `build.ps1` runs it when needed), `directmic/sim_directmic.py` (fuzzes the mic effect's admin install / uninstall against a fake registry, killing it at every write, and the mic helper killed at every step), `buildtools/fetch_tor.py` (unpacks Tor into the gitignored `vendor\tor` to try Tor mode from source), `pictures/prepare_art.py` (turns generated pictures into `assets/art/<key>.png`, see its README), `pictures/make_icon.py` (regenerates `assets/onionboard.ico` from the logo in `ui/kit/logo.py`), `pictures/make_bunny.py` (renders the installer artwork from `bunny.py`; `--preview` for a sheet of poses), `pictures/site_mascots.py` (writes the website's Bun and Hoot into `site/index.html` and `site/home.css` from `bunny.py` and `owl.py`, in each theme of the site's look switcher), `pick_tests.py` (the test files a branch's changes need: CI runs only those on a PR; `--local` adds uncommitted files), `precommit.ps1` (ruff, the sensitive scan and the translation check in one command; `-Tests` adds the picked tests), `release.py` (a release's version bump: `__version__`, the changelog heading, the release line), `checks/check_code_doc.py` (this table lists every module: CI's pick job), `check_sensitive.py` (secrets / personal-data scan, also the pre-commit hook; your own patterns go in a root `.sensitive-patterns`, see `sensitive-patterns.example`), `buildtools/make_notices.py` (third-party licences for the build), `buildtools/prune_build.py` (drops the unused parts of Qt from the PyInstaller output; `--dry-run` lists them), `buildtools/installer_dupes.py` (lists the build's files with the same bytes as another for the installer, which then stores each once), `buildtools/vc_runtime.py` (keeps one, the newest, Microsoft C++ runtime in the PyInstaller output, so an older `msvcp140.dll` from the build PC can't stop Qt loading; `--dry-run` lists the copies), `buildtools/version_info.py` (writes the .exe's version resource from `soundboard.__version__`, so Windows and its firewall prompt name it "Onion Board"), `voicetests/codec_bench.py` (what voice chat does to your sounds, in numbers), `voicetests/discord_roundtrip.py` (the same measured through a real Discord call to a second client), `voicetests/dest_fit.py` (which *Who's listening* mode suits each game), `voicetests/game_capture.py` (which mic Windows gives a game, its resampling and ducking), `voicetests/steam_voice_roundtrip.py` (Steam's own voice codec, measured on one PC), `voicetests/game_roundtrip.py` (a real game, recorded by a friend in the lobby, whose PC runs `voicetests/game_listener.py`), `docs.py` (the README and website in one go: the screenshots, the version and VirusTotal line from `site/release.json`, the sitemap dates; `--tour` re-records the tour), `pictures/screenshots.py` (renders `site/screenshots/` offscreen from made-up demo data; set `ONIONBOARD_ONION_WATCH_ZIP` to an Onion Watch module zip to include the Triggers tab) `pictures/promo.py` (renders the Triggers promo clips: a made-up game scene drawn with QPainter, a synthesized trombone, ffmpeg) and `pictures/tour.py` (records the feature tour `site/screenshots/tour.webp` from the real app, driven in a window parked off-screen, with the same made-up data as the screenshots) |
| `docs/`, `site/` | `docs/` is the reference docs (this file, DEVELOPING, DESIGN, FEATURES, ...); `site/` is the website at onionalien.com/onionboard, published by `.github/workflows/pages.yml` on every push to main that changes it (its pages, tab icons, `screenshots/` shared with the README, `release.json`, `sitemap.xml` and the search engines' ownership files) |
| `tests/` | the pytest suite, fully headless (Qt's offscreen platform, silent stand-in audio devices, a throwaway profile; nothing is heard or shown): one `test_<module>.py` per module or feature, `conftest.py` for the guards that keep runs fast and isolated, `test_mainwindow.py`'s `window` fixture for a real main window; `offwindows.py` stands in for Windows off it. Running them: [DEVELOPING.md](DEVELOPING.md) section 3 |

`pyproject.toml` holds the package metadata (version comes from `soundboard/__init__.py`),
the ruff and pytest settings, and a `soundboard` GUI entry point for `pip install .`.

## The installer

`build.ps1` turns the app into **`dist\OnionBoardSetup.exe`**, the one file to hand
out (how to build, install silently and uninstall: [DEVELOPING.md](DEVELOPING.md)
sections 4 and 5). `installer\OnionBoard.iss` is Inno Setup 6, and its header comment
lists every page and box. In short:

- Per user, no admin, into `%LOCALAPPDATA%\Programs\OnionBoard`, with the Start menu
  shortcut (the Desktop one is a box). The add-ons in `modules\` (all but `ai-voices`)
  always come along in `{app}\modules`.
- *Your privacy*: what the app connects to, and an *Offline mode* box (ticked: runs
  `OnionBoard.exe --set-offline` before the first start and unticks the boxes that
  download).
- *Pick what you want*: FFmpeg via winget (only offered when it's missing and winget
  is there), live voice-to-speech (`--install-addon live-voice`), Tor (`--get-tor`),
  *Count me in* (ticked, the last page asks where they heard about the app), the
  Desktop shortcut, and under *Advanced* the virtual cable, unticked
  (`installer\install-vbcable.ps1`).
- *Bring your sounds over*, only when Soundpad, Resanance, Soundux or EXP Soundboard
  has a board on the PC: the ticked ones are copied in at the app's first start.
- Then it opens the app, whose setup guide puts the sounds straight into the mic.
  Uninstalling runs `--direct-mic remove` first (the mic put back as it was; Windows
  asks only if the effect is on a mic) and offers to remove VB-Cable.
- The artwork is Bun, drawn by `soundboard/ui/bun/bunny.py` and rendered by
  `scripts\pictures\make_bunny.py` (`--preview` writes a sheet of every pose).

Settings live in `%APPDATA%\OnionBoard\` either way. Saving `config.json` keeps the
last three good copies next to it (`config.json.1` … `.3`, rotated at most once an
hour); a damaged file is set aside as `config.json.broken-<time>` and the newest
backup is used, so the pad list is never silently reset.

## Audio notes

- Local imports link to their original absolute path by default. Settings > Data &
  quality > Local sounds can enable `Config.copy_local_sounds` for new imports.
  Downloads and extracted ZIP files always keep a library file. Both modes decode
  at import and use the same int16 cache (including memory mapping, prefetch and
  effect caches), so live speed, pitch and bass have the same playback path. After
  cache eviction the source must be available again; external files are never moved
  or deleted when removing their pads. Backups include the linked audio itself,
  converting linked videos to audio rather than exporting the whole video.
- Sounds are held as int16 stereo at 48 kHz (half the size of float32; the
  engine scales them in the same multiply as the gain): short ones in RAM, long ones
  memory-mapped from the cache (`mapped.py`). Only the first 2 hours of a
  file are ever decoded, a second at a time: a sound over a minute (`STREAM_S`) is
  resampled, levelled and written into its cache (and its converted copy) piece by
  piece, never held whole, so a long import costs about as much memory as a short
  one. Video, m4a, aac and wma imports are stored as FLAC of their
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
- **Edit sound on a playing sound** is heard at once instead: what can run live
  (`soundfx.live_split`: the speed, pitch, Live controls stages and boost) goes on that
  one sound (`Engine.set_sound_live`), read faster like the live speed and run through
  its own `livefx.SoundStage`, over a copy with the rest baked in (only a trim, reverse,
  EQ or voice change makes a new one). Save bakes it all in as above and swaps it in
  under it. The stages and boost are the bake's own `LiveFx` code and match it to the
  sample; the speed and pitch match its length and pitch, not its exact waveform.
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
- **The send stage** (`soundboard/audio/sendfx.py`) is the last thing before what others hear (your mic,
  the cable, or the device the route picked).
  Everything Discord and games send is one channel, so the sounds are downmixed
  here first, per band: a band that is mostly out of phase between left and right
  is summed with the right channel flipped, and wide stereo gets back the power a
  plain average loses (a plain average took out-of-phase bass down 25 dB). Your
  mic is never touched by it. Then a lookahead peak limiter (3 ms) holds the send
  at -3 dBFS, because Opus puts peaks back up by ~2.5 dB and the listener's decoder
  clips them; it turns the level down around a peak instead of bending the
  waveform. Optionally the sounds duck under your voice while the mic hears you.
  Your voice gets one stage of its own, before the sounds are added (on by default,
  `VoiceLeveler`): a slow automatic volume that brings your talking level to about
  -20 dBFS and holds still between words, so the voice chat's own automatic gain
  (which pumps and cuts the sounds) can stay off without friends riding your volume.
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
- Windows draw the ordinary way (no `QT_WIDGETS_RHI`). Forcing GPU drawing gives every
  window its own Direct3D device (16 driver threads and ~30 MB each, never freed).
- `OPENBLAS_NUM_THREADS` is set to 2 when the `soundboard` package is first imported,
  before numpy loads (a value you set yourself wins). numpy's and scipy's OpenBLAS
  otherwise start a pool of one thread per CPU each and reserve ~32 MB per thread: about
  1 GB of commit and 30 idle threads. Add-on helper processes (`net.child_env`) get the
  variable removed again, so their own maths isn't capped by the app's choice.
- Drop-outs reported by the audio driver are counted and shown in a toast (key "audio").
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

### Voice background recordings

The voice changer bundles seven CC0 loops in `assets/backgrounds/`, including the
extra rain-on-a-window choice, as Ogg Vorbis (quality 5; each decodes to exactly the
samples of the FLAC it was made from, so the baked-in loop seam stays put). `credits.json` carries source pages, creators,
licenses and file hashes; the packaged third-party notices include these credits.
`voicefx/backdrop.py` decodes and caches active loops on its worker, including
neutral settings. The audio callback only reads the finished loops, and preview
loading also runs on a worker. A missing loop stays silent without falling back
to synthesis. Source runs read `assets/backgrounds`; packaged builds read the
bundled `backgrounds` directory. Playback requires no network access.
