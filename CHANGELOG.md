# Changelog

## Unreleased

## 1.4.2 — 2026-09-30

Better help for game voice chat, from testing what ~20 games' voice chats do to
your sounds.

- **The project moved to [github.com/Onion-Alien/onion-board](https://github.com/Onion-Alien/onion-board)**
  and its website to [onion-alien.github.io/onion-board](https://onion-alien.github.io/onion-board/).
  The old addresses still lead there. Updates keep working: this version takes an
  installer from either address.
- **"Game has no microphone setting?" now covers voice chat too.** Windows keeps
  a separate *default communication device*, and that's the one many games' voice
  chat asks for. The steps now set the cable as both, not just the default device.
- **The game voice chat guide names more of the settings that mangle sounds**:
  *denoiser* and *background sound removal* as well as noise suppression. The AI
  denoisers in VRChat and Minecraft's Simple Voice Chat take music out almost
  completely.

## 1.4.1 — 2026-09-29

A fix for the new self-update.

- **The app opens again properly after an update.** After *Update now → Restart
  now*, the new version installed fine but crashed as it reopened ("Importing the
  numpy C-extensions failed"): it was started with the old version's internal
  settings. The installer now reopens it the way a double-click does, and the app
  starts the installer without them. If an update left you with that error, just
  open Onion Board again: the new version is installed and works.
- **The update window's notes read properly**: plain text, whole sentences, no
  stray `**` marks.

## 1.4.0 — 2026-09-29

Drum pads, instant replay and hold-to-play: play your sounds from a MIDI pad
controller, clip what a friend just said and play it straight back at them.

- **MIDI pad controllers work as hotkeys.** Plug in an Akai LPD8 / MPD, a
  Launchpad or any USB MIDI keyboard, click a hotkey and hit a pad instead of
  pressing a key. No extra software needed. Pads play sounds and can do anything
  a hotkey does (stop, pause, random sound, the overlay). A controller is only
  opened while a hotkey uses it, so your music app keeps your other MIDI gear. If
  another program has it open, Onion Board says so and picks it up once it's free.
- **Instant replay.** Give *Save what you just heard* a key (Settings → Hotkeys)
  and the last 30 seconds of everything your PC plays (a friend in Discord, the
  game, a video; not Onion Board's own sounds) are kept in memory. Press it after
  something funny and it's a new pad. Nothing is saved or sent anywhere until you
  press it.
- **Hold to play.** A sound can play only while its hotkey or pad is held down, and
  stop the moment you let go, like an air horn (Edit → *Hold to play*).
- **Solo sounds.** A new *On press* choice, *Solo*, stops every other sound
  before it plays.
- **Mute my mic while a sound plays** (Setup → *Who's listening*): others hear
  only the sound, and your mic comes back the moment it ends.
- **Voice changer and Discord:** while the voice changer is on, a notice explains
  that Discord deletes most of a changed voice unless its *Input Profile* is
  *Studio*, with a *Show me how* button. Measured in a real call: on the default
  Voice Isolation only about 20% of a Deep voice got through; on Studio 93%, at the
  same volume.
- Developers: `scripts/discord_roundtrip.py` measures what a second client in a real
  Discord call receives (raw vs the app vs Discord mode, plus the mic path). The
  codec bench now models Discord's ~94 Hz capture high-pass, found in that test.

## 1.3.3 — 2026-09-29

Onion Board now updates itself, plus 25 new themes and an overlay you can drag
anywhere. This is the last version you have to install by hand: from here on the
*Update* button at the top does it for you.

- **Onion Board updates itself.** When a new version is out the *Update* button
  at the top offers *Update now*: it downloads the new installer in the
  background, checks it's exactly the file on GitHub, and when you click
  *Restart now* installs it and opens the app again. Your sounds and settings
  are kept, and the virtual cable isn't touched. The daily check for a new version
  is now on by default (untick it in Settings → General); it only reads GitHub's
  release list. Coming from 1.3.2 or older, install this version by hand once.
- **Triggers see fullscreen games on a portrait monitor.** A rotated monitor never
  got Desktop Duplication (it fell back to GDI, which sees fullscreen games as
  black); its sideways frames are now read and turned upright.
- **25 new themes, 31 in all**, grouped in Settings → Appearance: Classic
  (Midnight for OLED screens, Slate, Arctic, Paper, High Contrast), Colourful
  (Vampire, Forest, Mocha, Sunset, Royal, Onion, Mint), Wild (Synthwave with a
  neon grid, Vaporwave, Blood Moon, Lava, and Amber Terminal and Hacker with CRT
  scanlines and a terminal font) and Meme (Flashbang, Barbie, Swamp, Deep Fried,
  Retro 98, Comic Sans, Brainrot).
- **Put the overlay where you want it.** Drag it by any empty part (its title,
  its edges) and it opens there from then on — on any monitor. Settings → Overlay
  picks the monitor (the game's, the main one, or a particular screen, say a
  second monitor next to the game) and one of nine spots.
- **The logo reacts to everything that plays.** The glowing onion in the header
  followed only what others hear, so the radio or a program on *Only me* left it
  still, and talking into your mic made it flare. It now glows with any sound, the
  radio or a captured program, wherever they go, and never with your voice. The
  title bar, taskbar and tray icons glow along with it.

## 1.3.2 — 2026-09-29

A fresh coat of paint: the same app, tidier controls and pictures for the voices.

- **A cleaner look.** Dropdowns have a slim arrow and open as a list below the box
  with rounded, highlighted rows; number boxes (Triggers' Wait, Not again for,
  Match) get matching arrows; menus, tooltips and scrollbars are tidied up; sound
  chips on a trigger are round again; a clearer Settings gear and folder icon.
  Nothing has moved.
- **Pictures for the voices.** Voice changer tiles, the computer voice and its
  languages can show a picture (from `assets/art`), and while one is on the Voice
  tab shows it. Missing pictures fall back to the emoji and icons as before.
- **The window still shrinks to small sizes with the new look.** The Triggers tab's
  "Check every" list got wider with its new arrow and held the window at a larger
  minimum width; it now gives way like the screen list beside it.

## 1.3.1 — 2026-09-28

A bug-fix release from testing the whole app for real on a two-monitor PC, plus
three Triggers upgrades that came out of it.

- **The in-game overlay opens on the monitor your game is on.** On a second
  monitor it used to appear on the main one (Qt 6 names screens differently from
  Windows, so the overlay never recognised the game's monitor).
- **Triggers work on HDR screens.** A monitor with HDR (advanced colour) on hands
  the app its frames in a different format than it announces; the copy came
  out black, so nothing ever matched. A screen where nothing moves is read
  straight away now too.
- **Triggers: the screen picker no longer cuts off the screen's size.**
- **Triggers can watch several screens at once.** Each trigger can pick its own
  screen on its card, so a picture on your second monitor and one on your main
  monitor both work at the same time. The picker at the bottom stays the screen
  for triggers that don't pick one.
- **A trigger can look for several pictures and play several sounds.** Add up
  to 100 pictures to one trigger (any of them fires it) and give it a list of
  sounds, played one at random (each once before any repeats), in order, or all
  at once.
- **The Radio and Apps tabs light up while they're sending sound**, like Triggers
  and Voice already did, and a live tab's name is tinted too, not just the dot.
- **The window shrinks to small sizes again** (the new Triggers screen pickers
  stopped it).

## 1.3.0 — 2026-09-28

Sound quality on the other end. Measured, not guessed: the codec Discord and
games use keeps nearly everything, so most of the damage came from voice chat's
own mic cleanup, a cable converting on the way through, and how the sound was
sent. Onion Board now fixes what it can itself and tells you exactly which
setting to flip for the rest.

- **Your sounds come through clean in Discord.** Discord cleans up your mic for
  talking, and left on, that cleanup treats music and sound effects as noise and
  chops them up. The setup guide and the Setup tab now say what to switch off
  (Discord: *Input Profile → Studio*), with a guide for game voice chat too.
- **Check Discord.** With Discord's *Let's Check* running, one click plays a short
  test into your mic, listens to what Discord plays back, and tells you exactly
  which Discord setting is still hurting your sounds: noise suppression, the
  voice-activity gate cutting quiet parts, or automatic gain control pumping the
  volume.
- **Loud sounds don't crackle on the other end.** Voice chat's codec pushes peaks
  back up after it squeezes them, so a loud song that left here at full volume
  clipped in your friends' ears. Onion Board now leaves room for that, with a real
  limiter that turns the level down around a peak instead of distorting it.
- **Stereo sounds don't lose parts in mono.** Every voice chat sends one channel.
  Out-of-phase bass and wide stereo effects used to cancel out when Discord or a
  game mixed them down; Onion Board now does the mix-down itself, smarter, before
  they get the chance. On by default (Setup tab → *Who's listening* → *Send in
  mono*).
- **Lower my sounds while I talk** (Setup tab → *Who's listening*): your sounds dip
  under your voice so a song doesn't bury what you say. Off, a little, half or a
  lot.
- **Speeding up or slowing down sounds live sounds cleaner** (better interpolation).
- **The virtual cable passes your sound through untouched.** Windows sometimes
  puts one end of the cable on 44.1 kHz, and the cable then converts everything on
  the way through. The Setup tab spots it and fixes it in one click (the setup
  guide does it for you).

## 1.2.3 — 2026-09-27

A bug-fix release from a feature-by-feature test of the whole app.

- **Onion Board always starts.** A damaged setting (from an old backup, a
  hand-edited config, or an add-on with a broken slider) used to stop the app
  from opening, every time: a huge volume or EQ value, a broken voice changer,
  text-to-speech or "Who's listening" setting, a bad Apps-tab volume or API port.
  The damaged value now just goes back to its default.
- **Hotkeys don't fight each other or your keyboard.**
  - On keyboards other than US English, the default overlay key (the one left of
    1) types a letter or everyday punctuation, such as ö, ñ or the UK ' key, and
    Onion Board took it away from typing everywhere. There it's now Alt + that
    key, and hotkeys show the character your keyboard really prints.
  - The game's push-to-talk key can no longer also be one of Onion Board's
    hotkeys (it used to catch its own key presses instead of the game).
  - Renaming or deleting a category updates its random-sound hotkey straight
    away, and a numpad overlay key closes the overlay again.
- **The in-game overlay shows what's playing** (progress, Pause/Resume) while the
  main window is in the tray, which is how it's normally used.
- **Backups and the Sounds tab are sturdier.** Sounds in less common formats
  (.au, .caf, .w64) come back when you restore a backup. Restoring right after
  deleting all your sounds brings them back instead of skipping them. "Save as
  new sound" keeps the copy's categories and fades, Undo no longer brings back a
  category you just renamed or deleted, imported sounds join an existing category
  whatever its capitals, empty audio files are refused with a clear message, and
  the Edit dialog no longer lowers some volumes by 1%.
- **Triggers are more reliable.** Big pictures and full-screen screenshots are
  kept at their real size, so they match; cut-outs with thin outlines are found;
  a graphics-driver reset or a screen briefly unplugging no longer switches
  watching off; a refused picture no longer replaces the trigger's old one; tiny
  pictures no longer slow every check down; screens plugged in later show up.
  A trigger whose sound was removed says so instead of claiming it played.
- **Voice tab.** "Windows default" really speaks in the default voice after you've
  used another one, a saved voice that has since been uninstalled falls back to
  the default, and a line the voice can't read (Chinese with an English voice,
  say) says so instead of staying silent. Add-ons whose `module.json` was saved
  with a byte-order mark (Notepad) load.
- **Record 6s** no longer says your voice isn't getting through when the voice
  changer is on; in computer-voice mode it says your real voice is muted instead
  of blaming the send switch. Live speed / pitch no longer changes the test
  playback, cue beeps or previews.
- **The "Old radio" effect** no longer adds 3 seconds of static to a sound (before
  it, when reversed), and slowing down long sounds uses far less memory.
- **Radio.** Favourites and stations you've played pick up a station's new stream
  address instead of staying on a dead one; a radio volume of 0 is remembered;
  when one directory mirror answers with a maintenance page the next one is used;
  "Last 15s" only holds (and is named after) the station that played. Station
  links can no longer reach your PC or home network with an address written in
  an unusual form (like `127.1`).
- **Links and web search.** One slow link lookup no longer holds up every search
  and download; pressing *Add* on a second result while one is downloading adds
  it next instead of doing nothing; typing a link by hand looks it up once.
- **Local control API (Stream Deck).** A request answered "busy, try again" no
  longer runs later as well, so a retrying button can't play a sound twice.
- **Settings.** "Start with Windows" shows off when it's been switched off in Task
  Manager, and ticking it turns it back on there; *App updates* only says "You
  have the newest version" after it really checked.
- **Readable on light themes.** Green, amber and red status text (setup guide,
  header, warnings everywhere) was hard to read on Light and Cherry Blossom; each
  theme now has its own readable shades.
- **Setup guide.** Closing it without finishing no longer swaps in another mic or
  headphones for a headset that happens to be unplugged.
- **Problem reports** that came up while you were in a game now really appear when
  you switch back, and hide your Windows user name more thoroughly (short `~1`
  paths, web-style paths, device names).
- **Odds and ends.** Launching Onion Board again while it's still starting brings it
  to the front. A settings file saved by Notepad (with a byte-order mark) no longer
  counts as damaged. First start no longer adopts another program's
  `%APPDATA%\Soundboard` folder. Opening Settings over and over no longer makes
  theme changes slower. Updating clears out the old version's program files.

## 1.2.2 — 2026-09-27

- **Triggers keep working when a game switches display mode.** When a game went
  into (or out of) exclusive fullscreen at another resolution, the screen capture
  quietly froze on its last picture or went black, and the tab told you to switch
  to borderless. The capture now follows the screen's real size, rescales your
  pictures to it, says "Waiting for the screen to come back" while the switch
  happens, and starts itself afresh if it can't recover.

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
