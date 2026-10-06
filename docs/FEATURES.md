# Everything Onion Board does

The full list. The [README](../README.md) has the short version and how to get started.

- **Pads:** add by button, drag-and-drop (files or folders), or by dropping files into
  the sounds folder (**Sounds folder** opens it; they join the board by themselves). Plays mp3, wav, ogg,
  flac, m4a and more, and pulls the audio out of video files. Search, reorder,
  resize, set colours. **Pictures on pads:** right-click → *Add picture…*, or drop or
  paste (Ctrl+V) a picture onto a pad; a link's thumbnail or a file's cover art is
  used by itself. **Pads from videos** have a *Video* button that shows the video in
  step with the sound (only you see it). **Pick several pads** with Ctrl+click,
  Shift+click or Ctrl+A to change their colour, volume, fades or categories, export
  them or remove them together (one Undo).
- **Record a sound with your mic:** the **Record** button next to *Add sounds*.
  Record your own voice, or your voice through the voice changer while it's on;
  after *Stop* the quiet ends are already cut off, drag the start and end to cut
  more, *Preview* plays it in your headphones only, then name it and *Save* to add
  the pad (it joins the category showing). Up to 15 minutes, spooled to disk as it
  records; nobody hears you while you record.
- **Categories:** the tabs above the pads (the *+* after the last tab makes one). Right-click a
  pad → *Categories* to put it in any number of them; right-click a category to
  rename, export or delete it. The in-game overlay shows the same category, and
  its **R** key (numpad **\***) switches to the next one. Right-click a category to
  give it a random-sound hotkey, or to *Play them all* (in order or shuffled). With
  *Use hotkeys per category* (Settings → Hotkeys) each category is its own set of
  keys: one key, a different sound per category.
- **Switch category when a program is in front:** right-click a category →
  *Show this when a program is in front…* lists the programs open now (with their
  icons) and *Browse for a program…*. When one of them comes to the front, the board
  and the overlay switch to that category (with the category beep, if beeps are on);
  when it closes, the board goes back to the category it showed before. Alt-tabbing
  away changes nothing; a category you pick by hand while it's in front stays. Rules
  match the program's file name (`game.exe`), so they survive a reinstall and go
  into backups. The tab's tooltip lists its programs; *Stop showing this for…* in the
  same menu, or *Settings → General → Switch category by program* (every rule, a
  *Remove* each, and *Switch by itself* to turn it all off).
- **Remove can be undone:** *Removed “…” · Undo* stays up for 10 seconds. After that
  the sound waits in **Recently deleted** (the *Backup* menu, or the bin button that
  shows while it holds sounds) for 30 days, and *Bring back* returns it exactly as it
  was. Only when it ages out does its audio file go to the Recycle Bin.
- **Backup / share (*Backup* button, or Settings → General):** *Export everything*
  writes every sound (picture, effects, hotkey, categories) and your settings to
  one `.zip`; import it on a new PC (which audio devices and where sounds go stay
  per PC). A category or a single pad exports as a sound pack to share; importing
  skips sounds you already have. *Import from another soundboard* brings sounds over
  from Soundpad, Resanance, Soundux or EXP Soundboard. The format is a plain
  zip of JSON and the original audio files — see
  [BACKUP-FORMAT.md](BACKUP-FORMAT.md).
- **Per sound:** global hotkey (works in-game) or MIDI pad, volume, loop, what
  pressing again does (restart / overlap / toggle), **Solo** (stops every other
  sound first), **Queue** (waits for the sounds playing to finish; right-click any
  pad → *Play next* does it once), **Only others hear it** (not in your
  headphones), a **wait** before it plays, a **cooldown** against spamming, **fade in /
  fade out**, and **Hold to play** (plays only while you hold its key or pad down, like
  an air horn).
- **Effects on any sound** (right-click a pad → **Effects…**, or the *Effects* tab
  of **Edit…**): speed and pitch (separately, or together like a record player
  with *Tape mode*), **trim** (drag the start and end on the sound's waveform, or
  type exact times — keep one line out of a 4-minute video), a 7-band EQ, a boost
  up to +36 dB that clips on purpose,
  play backwards, and every voice effect (echo, reverb, distortion, radio, robot,
  add-on effects too). One-click presets: **Deep fried**, Bass boosted,
  Slowed + reverb, Nightcore, Chipmunk, Demon, Fast / Slow-mo (same pitch), Old
  radio, Reversed. *Preview* plays it to you only; **Save** changes that pad,
  **Save as new sound** keeps the original and adds the edited version as its own
  pad. Pads with effects show **FX**; *Reset* goes back to the original. The
  original file is never changed.
- **Your mic on or off:** send your voice with the sounds, or sounds only.
- **Where your sounds go** (Setup → Devices → *Send my sounds to*, also in
  Settings → Audio): **straight into your mic** (the default for everyone, and
  updating from the cable moves you here once: one click and one Windows permission
  prompt, then Discord and games hear your sounds through the mic they already use,
  with nothing to pick there; voice changer, mic volume, gate, ducking and mute all
  still work, and the Setup tab offers a one-click repair if a Windows update takes it
  off), **the virtual cable** (the backup: *Use the virtual cable instead* on the
  Setup tab, or the installer's box, unticked; Discord or the game uses its *CABLE
  Output* as a mic. Once your sounds are in your mic, the Setup tab offers to remove
  the cable), **another device** (any output
  but your headphones: Voicemeeter, a mixer, a capture card, a second sound card, any
  output OBS captures as an *Audio Output Capture*) or **nowhere** (only you hear your
  sounds, and the stream output if you set one). With another device the app never puts
  the cable back, never asks you to install it, and the header pill gets a tick once
  it's sending. With nowhere nothing nags. The choice is per PC and isn't in backups.
- **Stream output for OBS** (Settings → Audio → *Stream output*): what others hear,
  without the voice chat shaping, on a device of its own (a second virtual cable such
  as VB-Cable A+B, or any output you don't listen on). In OBS add it as an *Audio
  Output Capture* (or, for a cable, *Audio Input Capture* of its Output end) and your
  sounds and screen triggers are their own track, with their own volume. Your voice
  goes with them unless you untick it.
- **Transport bar:** play/pause, stop, a seek slider, and **speed, pitch and live
  effects while it plays** (the `1x` button: 0.25×–2×, ±12 semitones, keep the pitch
  or not, plus bass, treble, muffle, reverb, echo, distortion and presets on every
  sound playing). That's for listening and isn't saved; use Effects to keep a version.
- **Any window size:** less important controls tuck away as it gets smaller and come
  back when it grows. Small enough (below roughly 440 × 380) it becomes a mini
  player with your pads and the play / stop controls, down to 260 × 120.
- **Global hotkeys** (set in **⚙ Settings → Hotkeys**, the overlay key in
  **⚙ Settings → Overlay**, the most-used ones from the keyboard button on the Sounds
  tab; all work in-game):
  - Stop all, and pause/resume all.
  - A random sound (from the category showing), the last sound again, next /
    previous category (beeps tell you which), sounds louder / quieter, your mic on /
    off, the voice changer on / off or only while a key is held, and **all hotkeys
    off / on** for when you need to type.
  - **In-game overlay** (by default the key left of <kbd>1</kbd>: <kbd>`</kbd> on a
    US keyboard; where that key types a letter, like ö or ñ, it's Alt + that key):
    a small panel of your sounds over the game. Number keys play them, and the game keeps your mouse
    and keyboard. Settings → Overlay: tap to open or hold to show, number row or
    numpad, hide after picking or after a while, which monitor and where (or drag
    it), its size and background, and *Show preview*.
  - Auto push-to-talk: holds your game's PTT key while a sound plays.
  - **Instant replay:** set its key and the last 30 seconds of everything your PC
    plays (a friend in Discord, the game, a video; not Onion Board's own sounds)
    are kept in memory. Press it after something funny and it becomes a pad.
    Nothing is saved or sent anywhere until you press it; clear the key to switch
    it off. Needs Windows 11, or Windows 10 version 2004 or newer.
  - Hotkeys can beep in your headphones (only you hear it), so you know they
    worked.
- **Radio tab:** internet radio from all over the world, from the free
  [Radio Browser](https://www.radio-browser.info) directory. Click a dot on the
  world map to tune in (hover one for its country, genres, quality and how popular
  it is; drag to move, scroll to zoom: zoomed in, the cities and towns with stations
  are named), or search by name, genre, country or city. The
  map's **HD** button swaps it for a 3D globe you can spin (heavier: it runs a web
  engine); **2D** on the globe goes back. Star stations for
  *★ Favorites*; *Popular* and *Recent* list the most played and the ones you had on. It plays in your headphones, goes out through
  your mic when you press **LIVE**, and can *Record* or save the *Last 15s* as a pad.
- **Apps tab:** send one program's sound (a music player, a browser, a video, a
  call in another app) to whoever's listening, without touching any other program.
  Each program is a card with its level, a **Send** switch, its own volume, *Hear it
  myself* and **Record** (waits for the program to make a sound, then adds it to your
  Sounds as a pad). Programs you switched on are picked up again next time they run.
  Under each card, the **Clip editor** keeps that program's last minute as a live
  waveform: freeze it, drag across the bit you want, Space to hear it, **Send** to
  play it to others, or **Save** to keep it in *Saved clips* at the bottom of the tab
  (double-click plays, F2 renames, right-click adds it to your Sounds, sends, copies
  or deletes it with Undo). Cut, copy, paste, fades, louder / quieter, reverse and
  undo are in its *Edit* menu; Ctrl+C there and Ctrl+V on the Sounds tab makes a new
  sound; the big-view button gives one program the whole tab. A closed editor
  doesn't listen or keep anything. A program you removed comes back, settings and
  all, from *Forgotten programs…*.
- **Voice tab:** voice changer (21 ready voices, from Female / Male voice and Demon to
  Autotune, Talkbox, Masked caller and Dark lord; pitch with a natural-sound mode and a
  voice-size control, autotune, mic clean-up (noise gate + hiss removal), monster growl,
  robot / talkbox, helmet, shout blowout, radio with walkie-talkie clicks, echo, reverb,
  distortion, 8-bit bitcrusher, plus add-on effects; *Save as a voice…* keeps your own
  mix as a voice button (*Make it yours…* tweaks it, a share code copies it to a
  friend and *Import a code…* adds theirs; removed ones wait in *Recently deleted*),
  and the dice picks a random one; it shows how much delay the
  voice adds, starts off every time the app opens, and a big ON / OFF button shows
  which it is), **AI voices** (optional: *Get AI voices* downloads about 55 MB, needs
  Python 3.12+; six characters turn your voice into someone else's, live on your own
  CPU, about 75 ms behind you; *Remove AI voices* takes it all off again), text-to-speech with Windows' built-in
  voices or your own (*More options → Custom voices*: a TTS server on your PC such as
  Kokoro or AllTalk — any OpenAI-style `/v1/audio/speech` address — a TTS program, or
  Piper voice packs dropped into the voices folder), and **live voice-to-speech**:
  press *Start talking as the voice* and each sentence you say is spoken by a
  computer voice instead of yours. Speech recognition runs on your PC (the first time, the Voice tab's *Install speech
  recognition* button downloads it, about 300 MB; needs Python 3.12+).
  *Speak in* makes the voice say it in Chinese, Spanish, French, German or
  Russian: talk in English and it's translated on your PC. Each language is an
  add-on you download only if you pick it (65–195 MB), and it needs that
  language's Windows voice (Settings → Speech → Add voices, free).
- **Triggers tab:** plays a sound when a picture shows up in your game: a
  game's "YOU DIED", a rare spawn, a queue popping. It's the
  [Onion Watch](https://github.com/Onion-Alien/onion-watch) add-on: the tab's
  *Get Onion Watch* button downloads it from its GitHub release (checked against
  the SHA-256 GitHub lists) and it appears right there, no restart. Pick the
  game's window (it's watched even while other windows cover it, and two copies of
  a game are told apart) or a screen, cut the thing to watch for straight out of
  it (or paste a Win+Shift+S cut, or add a file), pick sounds from your board,
  and choose the wait, how soon it may play again and how close a match must be,
  with the live match % next to it. A trigger plays once each time the picture
  appears, or rings until you stop it. Its sounds play through the board like a
  pad; a ringing one loops in your headphones. Triggers from before the add-on
  (Onion Board 1.4 and older) carry over as they were. When a newer Onion Watch
  is out, the tab offers it (only while *Check for updates* is
  ticked). *Remove Onion Watch…* in its *More* menu uninstalls it (after asking);
  your triggers are kept for when you get it again.
  Everything happens on your PC: the screen is never saved or sent anywhere. If
  a game still shows up black, set it to Borderless or Windowed fullscreen.
- **Sound modes** (Sounds tab's *Listening* box, Setup → *Who's listening*,
  Settings → Audio): **Game** and **Voice chat** shape your sounds for the voice
  chat on the other end, working out which one by themselves; **Clean** sends them
  as mixed; **Advanced** picks an exact voice chat or your own custom mode.
  *What do these do?* explains each.
- **Mute my mic while a sound plays** (Setup → *Who's listening*): others hear
  only the sound, clean, and your mic comes back the moment it ends. Or the
  opposite, *While I talk, lower my sounds*.
- **Volumes:** sounds → them, your voice → them, your headphones. Exact % boxes go
  up to 1000%; a soft limiter stops hard clipping. "Level volumes" makes every
  sound equally loud.
- **7-band equalizer** on your voice, your sounds, or both, with presets.
- **Test mode:**
  - **Hear what they hear:** your mic plus the sounds exactly as others get them
    (a red banner shows while it's on).
  - **Record 6s → play back:** records what goes out (your mic, the cable's output end, or the
    mix sent to another device), plays it back, and reports whether your voice and
    sounds are in it and whether the balance is off. Not available when sounds go
    nowhere.
- **Connect your chat** (Setup tab): *Make it sound clean in Discord* (the Discord
  settings that stop it chopping up your sounds, with a check that listens to what
  Discord does to them), *Set up game voice chat*, *Zoom, Teams or a browser call*,
  *Game has no microphone setting?*, and the *Step-by-step guide* with Bun (mic,
  headphones, where your sounds go, then Discord). **Also send to** (Setup → Devices)
  gives extra outputs a copy of what others hear, each with a − to remove it.
- **Search the web for sounds** from the Sounds tab: Enter in *Search sounds* lists
  results (thumbnail, title, length) in place of the pads, from YouTube, YouTube
  Music, SoundCloud, **Myinstants** (short meme sound buttons) or TikTok sounds
  (reposted on YouTube); *Play* plays one once, *Add* keeps it as a pad (only the
  audio is downloaded, via [yt-dlp](https://github.com/yt-dlp/yt-dlp)). Instagram
  and most other sites have no search without an account, so paste a link to the
  video instead.
  YouTube's m4a/webm audio needs FFmpeg, like a dropped m4a file does. Settings →
  Updates has *Update now* and *Reset downloader* for when downloads start
  failing, and an opt-in box to update yt-dlp from PyPI automatically (off by
  default).
- **"Did you know?" tips:** after the setup guide, a short tip about one feature at
  most once a day, with a *Show me* button that opens the right place. Never while a
  game is up (the overlay open or a fullscreen program in front), each one only once;
  *Show tips* in Settings → General turns them off.
- **Data & quality** (Settings): *Use less data*, download quality, the radio's
  bitrate limit, *Slow or patchy connection* (waits longer before giving up), *Also
  save the video* for links, and *Show pictures and like counts* in search results.
- **Screen readers:** buttons that only show an icon are read out by name.
- **⚙ Settings:** 31 themes in four groups — Classic (Dark, Light, true-black
  Midnight, High Contrast…), Colourful, Wild (Synthwave, Hacker, Amber Terminal…)
  and Meme (Flashbang, Deep Fried, Retro 98, Comic Sans…); they switch live —
  your own highlight colour, how live tabs show (a tint or a dot, in the highlight colour), plus hotkeys, overlay, window and audio options. A category sidebar keeps every
  page visible: **Privacy & security** groups online permissions and Offline mode;
  **Connection** holds Direct, proxy and Tor; **Data & quality** holds download
  sizes, radio quality and search extras; **Updates** holds update scheduling
  and maintenance; **General** holds the window (*Keep window on top*, *Play pads with
  one click*), tips, startup, backups and *Start over* (*Reset…* just the parts you
  pick, with a restore point first; *Restore points…* undoes it); **Tabs** switches
  off the Radio, Apps, Triggers or Voice tab so it doesn't load at all;
  **Add-ons & help** holds Onion Watch, feedback and support; **About** holds the
  version and links. The other categories are Appearance, Audio (devices, *Also
  send to*, the stream output and buffering: Low or Safer, with a count of drop-outs),
  Hotkeys, Overlay and Remote. Changes apply immediately.
- **MIDI pads and macro keypads:** a pad controller (Akai LPD8 / MPD, Launchpad,
  any USB MIDI keyboard) works without extra software: set a hotkey and hit a pad
  instead of pressing a key. Pads work for sounds, stop / pause, random sounds and
  the overlay. A controller is only opened while a hotkey uses it, so your music
  app can have your other MIDI gear. On Windows only one program can use a MIDI
  device at a time: if one is busy, Onion Board says so and picks it up once it's
  free. A cheap USB macro keypad works too: set its keys to F13–F24 (keys nothing
  else uses) and use those as hotkeys.
- **Stream Deck and scripts (optional, off by default):** Settings → Remote →
  *Remote control* lets programs on this PC play your sounds: a Stream Deck
  (Bitfocus Companion, Touch Portal, its website buttons), AutoHotkey or a script.
  It only listens on this PC and needs the key shown there (*Copy an example link* gives a
  ready-made "play a random sound" link). Besides playing and stopping sounds it can
  mute you (a panic button), switch the voice changer and mic, change the volume and
  category, save the instant replay, change the live speed, pitch and effects,
  switch who's listening and run the radio; `/api/help` lists it all. New to it? The
  **Streamer guide** there walks through Stream Deck keys, channel points and chat
  commands (Streamer.bot), and **Copy AI prompt** gives ChatGPT / Claude everything
  it needs (the links, your sounds) to set up whatever tools you use with you.
- **Your pads on your phone (Onion Pocket add-on, optional, off by default):**
  Settings → Remote → *Get Onion Pocket* downloads and installs it (from its GitHub
  release, checked first); then its card is there. Scan the
  code with your phone's camera and your pads show up in its browser (iPhone or
  Android, nothing to install); a tap plays the sound on the PC. It has its own key
  (*Forget phones* makes a new one), only answers phones on your home network, and
  can play, stop and mute sounds, never touch your mic. Meant for your home Wi-Fi,
  not public Wi-Fi. When a newer Onion Pocket is out, its card offers *Update Onion
  Pocket to …*: one click and the new one runs, phones still paired.
- **Privacy:** Settings → Privacy & security has a switch for each thing the app
  does online, and **Offline mode** switches them all off (the installer can set it
  before the first start). Everything can go through a SOCKS5 / HTTP proxy or
  **Tor** (*Get Tor* downloads the Tor Project's own, checked first), and never
  quietly goes direct if that fails. **Network activity** (Settings → Connection)
  lists every connection the app makes and why. By itself it only checks for updates
  and sends an anonymous daily count (version + a random ID); each has its own switch.
- **Runs in the background:** closing the window keeps it in the tray (hotkeys and
  the overlay keep working; right-click the tray icon for *Open Onion Board*, *Stop
  all sounds* or *Quit*). Optionally
  **starts when you sign in**, straight to the tray (Settings → General).
- **Updates itself:** every few hours it checks GitHub for a new version (untick it in
  Settings → Updates). *Update now* downloads it, checks it's the file GitHub lists,
  and on *Restart now* installs it and reopens the app, keeping your sounds and
  settings. Nothing is downloaded until you click. An **important fix** (a release
  whose notes have an `Urgent: …` line, for Onion Board or Onion Watch) shows as a
  banner across the window with the reason and an *Update now* button; it can be
  hidden until the next start, but not skipped for good.

## How it works

Straight into your mic (the default):

```
🎤 your mic ──► Windows' audio engine ──► Onion Board's effect ──► Discord / game (same mic)
                                              ▲         │ clean mic
🔊 your sounds ─► Onion Board mixes them ─────┘         ▼ (your voice changer, gate, volume…)
```

Onion Board puts a small Windows audio effect on your mic (like Equalizer APO or
Soundpad do). It hands Onion Board your clean voice, and puts back what you send:
your processed voice plus your sounds, about 20 ms later. Close Onion Board and your
mic is just your mic again.

With the virtual cable:

```
🎤 your mic ── send ✓ / ✗ ──┐
                            ├─►  Onion Board mixes them  ─►  CABLE Input ═══ pipe ═══► CABLE Output
🔊 your sounds ─────────────┘                                                          (Discord / game mic)
```

The virtual cable is a free audio driver that works like a pipe: Onion Board plays
into one end, and Discord or the game uses the other end as a microphone. You hear
the sounds in your own headphones separately.

Not using the cable? Setup → Devices → **Send my sounds to** → any device by name
sends the same mix into that output instead (Voicemeeter, a mixer, a capture card,
OBS), *My mic* puts it in your mic, and *Nobody* keeps it to your headphones and the
stream output.
