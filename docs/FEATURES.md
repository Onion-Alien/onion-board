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
  them or remove them together (one Undo). **From the keyboard:** arrows move
  between pads, Enter or Space plays, F2 renames, Alt+Enter opens Edit, Delete
  removes (the picked pads, or the one you're on) and Ctrl+F jumps to the search box.
  Right-click a pad for *Rename*, *Duplicate* (a second pad with its own file, for
  its own effects or hotkey) and *Open file location*.
- **Record a sound with your mic, or from what's playing:** **Add** → *Record*. Record your own voice, your voice through the voice changer while
  it's on, or *What's playing*: a bit of a sound, a web search result or the radio as
  you hear it (the window stays out of the way, so you can play it while it records);
  after *Stop* the quiet ends are already cut off, drag the start and end to cut
  more, *Preview* plays it in your headphones only, then name it and *Save* to add
  the pad (it joins the category showing). Up to 15 minutes, spooled to disk as it
  records; nobody hears you while you record.
- **Categories:** the tabs above the pads (the *+* after the last tab makes one). Right-click a
  pad → *Categories* to put it in any number of them; right-click a category to
  rename, export or delete it. The in-game overlay shows the same category, and
  its **R** key (numpad **\***) switches to the next one. Right-click a category to
  give it a random-sound hotkey. With
  *Use hotkeys per category* (Settings → Hotkeys) each category is its own set of
  keys: one key, a different sound per category.
- **Remove can be undone:** *Removed “…” · Undo* stays up for 10 seconds. After that
  the sound waits in **Recently deleted** (the *Backup* menu, or the bin button that
  shows while it holds sounds) for 30 days, and *Bring back* returns it exactly as it
  was. Only when it ages out does its audio file go to the Recycle Bin.
- **Backup / share (*Backup* button, or Settings → General):** *Export everything*
  writes every sound (picture, effects, hotkey, categories) and your settings to
  one `.zip`; import it on a new PC (which audio devices and where sounds go stay
  per PC). A category or a single pad exports as a sound pack to share; importing
  skips sounds you already have, and asks before a pack's hotkeys take keys your
  sounds already use. *Backup → My sound packs* lists the packs you imported: reset
  one to how it came (its pads' edits undone, removed ones back) or remove it in one
  go. *Import from another soundboard* brings sounds over
  from Soundpad, Resanance, Soundux or EXP Soundboard. The format is a plain
  zip of JSON and the original audio files — see
  [BACKUP-FORMAT.md](BACKUP-FORMAT.md).
- **Per sound:** global hotkey (works in-game) or MIDI pad, volume, loop, what
  pressing does: **Solo**, the default (one sound at a time: it stops every other
  sound first), **Overlap** (layers over the others), **Toggle**, **Queue** (waits for the sounds playing to finish; right-click any
  pad → *Play next* does it once), **Only others hear it** (not in your
  headphones), a **wait** before it plays, a **cooldown** against spamming, **fade in /
  fade out**, and **Hold to play** (plays only while you hold its key or pad down, like
  an air horn).
- **Effects on any sound** (right-click a pad → **Edit** → *Effects*): speed and pitch (separately, or together like a record player
  with *Tape mode*), **trim** (drag the start and end on the sound's waveform, or
  type exact times — keep one line out of a 4-minute video), a 7-band EQ, a boost
  up to +36 dB that clips on purpose,
  play backwards, and every voice effect (echo, reverb, distortion, radio, robot,
  add-on effects too). One-click presets: **Deep fried**, Bass boosted,
  Slowed + reverb, Nightcore, Chipmunk, Demon, Fast / Slow-mo (same pitch), Old
  radio, Reversed. *Preview* plays it to you only; **Save** changes that pad,
  **Save a copy** keeps the original and adds the edited version as its own
  pad. Pads with effects show **FX**; *Reset* goes back to the original. The
  original file is never changed.
- **Your mic on or off:** send your voice with the sounds, or sounds only.
- **Where your sounds go** (Setup → Devices → *Send my sounds to*, also in
  Settings → Audio): **straight into your mic** (the default: one click and one
  Windows permission prompt, then Discord and games hear your sounds through the mic they already use,
  with nothing to pick there; voice changer, mic volume, gate, ducking and mute all
  still work, and the Setup tab offers a one-click repair if a Windows update takes it
  off; after the first permission prompt, repairs and changes of mic don't ask again), **the virtual cable** (the backup: *Use the virtual cable instead* on the
  Setup tab, or the installer's box, unticked; Discord or the game uses its *CABLE
  Output* as a mic. Once your sounds are in your mic, the Setup tab offers to remove
  the cable), **another device** (any output
  but your headphones: Voicemeeter, a mixer, a capture card, a second sound card, any
  output OBS captures as an *Audio Output Capture*) or **nowhere** (only you hear your
  sounds, and the stream output if you set one). With another device the app never puts
  the cable back, never asks you to install it, and the header pill gets a tick once
  it's sending. With nowhere nothing nags. The choice is per PC and isn't in backups.
- **Stream output for OBS** (Setup → Devices → *Also play on* → a device set to *Clean,
  for streaming*; one at a time, with its volume and *Include my voice* under it): what others hear,
  without the voice chat shaping, on a device of its own (a second virtual cable such
  as VB-Cable A+B, or any output you don't listen on). In OBS add it as an *Audio
  Output Capture* (or, for a cable, *Audio Input Capture* of its Output end) and your
  sounds and screen triggers are their own track, with their own volume. Your voice
  goes with them unless you untick it.
- **Transport bar:** play/pause, stop, a seek slider, and **speed, pitch and live
  effects while it plays** (the `1x` button: 0.25×–2×, ±12 semitones, keep the pitch
  or not, plus bass, treble, muffle, reverb, echo, distortion and presets on every
  sound playing). That's for listening and isn't saved; use Effects to keep a version.
- **Cards or a list:** two icons at the top right of the Sounds, Apps and Voice tabs.
  The list fits many more on the screen: sounds as one-line rows, each program on one
  line, voices as a small picture beside the name. Each tab remembers its choice.
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
  - A game that runs as administrator: Windows doesn't let other programs hear the
    keys pressed in it, so hotkeys (and auto push-to-talk) work there only when Onion
    Board runs as administrator too.
    When a full-screen game like that comes to the front, the board says so, with a
    *Restart as admin* button.
- **Radio tab:** internet radio from all over the world, from the free
  [Radio Browser](https://www.radio-browser.info) directory. Click a dot on the
  world map to tune in (hover one for its country, genres, quality and how popular
  it is; drag to move, scroll to zoom: zoomed in, the cities and towns with stations
  are named), or search by name, genre, country or city. Star stations for
  *★ Favorites*; *Popular* and *Recent* list the most played and the ones you had on. One click plays a station; it plays in your headphones, goes out through
  your mic when you press **Send**, and can *Record* it as a pad.
  The bar's live controls change the pitch (up to ±36 semitones with *Redline*) and
  add bass, treble, muffle, reverb, echo, distortion or a preset.
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
  sound; the big-view button gives one program the whole tab. The tab's live
  controls change the pitch and effects of every program you send. A closed editor
  doesn't listen or keep anything. A program you removed comes back, settings and
  all, from *Forgotten programs*.
- **Clean mic** (the Voice tab's first tab): fans, keyboards and other background noise
  taken out of your mic while you talk, inside Onion Board and before your sounds are
  mixed in, so the sounds are never touched (that's why Discord's and games' own noise
  suppression can stay off). On this PC, with or without a voice on, and it stays on from
  last time; its chip in the Voice tab's bottom bar turns it off. Strength: *Light*
  (noise turned well down, your voice most natural), *Normal* (RNNoise, about 5% of one
  CPU core, ~30 ms) or *Strong* (DeepFilterNet: nearly everything but your voice goes,
  about twice Normal's CPU; a one-time ~50 MB download the first time it's picked, which
  *Remove Strong's download* takes off again). It also filters out deep rumble (desk
  bumps, low hum) and, on Normal and Strong, turns your mic down between your words. *Mic
  settings* (the cog) is laid out like a voice chat app's: presets *Normal*, *Loud room*,
  *Just my voice* and *Quiet room*, *Input volume*, *Input sensitivity* (automatic, or
  your own level on a live bar), *Noise suppression* (Off, Light, Normal, Strong) and
  *Automatic gain control*. *Right now* shows your mic and the cleaned mic side by side;
  *Hear the difference* records 5 seconds and plays them as they were and cleaned, in
  your headphones only.
- **Voice tab:** voice changer (25 ready voices, from Deep, High and Male voice and
  Demon to Autotune, Talkbox, Masked caller, Dark lord, a Dalek and a singing monk; pitch with a natural-sound mode and a
  voice-size control, autotune, monster growl,
  robot / talkbox, harmony, ring modulator, helmet, shout blowout, radio with walkie-talkie
  clicks, flanger, wobble (vibrato and tremolo), echo, reverb (with pre-delay and early reflections),
  distortion (oversampled, so it crunches without fizz), a studio polish (de-esser,
  warmth and a lookahead limiter), plus add-on effects such as an 8-bit bitcrusher;
  *Save as a voice* keeps your own
  mix as a voice button (*Edit voice* tweaks it, a share code copies it to a
  friend and *Import a code* adds theirs; removed ones wait in *Recently deleted*),
  and the dice picks a random one; it shows how much delay the
  voice adds, starts off every time the app opens, and a big ON / OFF button shows
  which it is), **AI voices** (optional: *Get AI voices* downloads about 55 MB, needs
  Python 3.12+; 12 characters turn your voice into someone else's, live on your own
  CPU, about 75 ms behind you. *All voices* shows each as a card with **Hear it**,
  sorted under Men, Women and In between & fun, with chips for low, middle or high
  voices; **Make your own voice** blends two and sets how deep and high it is;
  *Remove AI voices* takes it all off again), text-to-speech with Windows' built-in
  voices or your own (*More options → Custom voices*: a TTS server on your PC such as
  Kokoro or AllTalk — any OpenAI-style `/v1/audio/speech` address — a TTS program, or
  Piper voice packs dropped into the voices folder), and **live voice-to-speech**:
  press *Start talking as the voice* and each sentence you say is spoken by a
  computer voice instead of yours. Speech recognition runs on your PC (the first time, the Voice tab's *Install speech
  recognition* button downloads it, about 300 MB; needs Python 3.12+).
  *Speak in* makes the voice say it in one of 35 languages (Chinese, Spanish,
  French, German, Japanese, Portuguese…): talk in your own language and it's translated on
  your PC. Each language is an add-on you download only if you pick it (65–196 MB), and it needs that
  language's Windows voice (Settings → Speech → Add voices, free).
- **Triggers tab:** plays a sound when a picture shows up in your game: a
  game's "YOU DIED", a rare spawn, a queue popping. It's the
  [Onion Watch](https://github.com/Onion-Alien/onion-watch) add-on: the tab's
  *Add Onion Watch to this tab* button downloads it from its GitHub release (checked against
  the SHA-256 GitHub lists) and it appears right there, no restart. Pick the
  game's window (it's watched even while other windows cover it, and two copies of
  a game are told apart) or a screen, cut the thing to watch for straight out of
  it (or paste a Win+Shift+S cut, or add a file), pick sounds from your board,
  and choose the wait, how soon it may play again and how close a match must be,
  with the live match % next to it. *Test* plays a trigger's sound now (it shows in
  *Playing now*, and its button says *Stop* while it plays). A trigger plays once each time the picture
  appears, or rings until you stop it. Its sounds play through the board like a
  pad; a ringing one loops in your headphones. When a newer Onion Watch
  is out, the tab offers it (only while *Check for updates* is
  ticked). *Remove Onion Watch* in its *More* menu uninstalls it (after asking);
  your triggers are kept for when you get it again.
  Everything happens on your PC: the screen is never saved or sent anywhere. If
  a game still shows up black, set it to Borderless or Windowed fullscreen.
- **Sound modes** (Sounds tab's *Listening* box, Setup → *Who's listening*,
  Settings → Audio): **Game** and **Voice chat** shape your sounds for the voice
  chat on the other end, working out which one by themselves; **Clean** sends them
  as mixed; **Advanced** picks an exact voice chat or your own custom mode.
  Only what's sent is shaped: your own playback stays as mixed, unless you turn on
  *Hear what they hear*.
  *What do these do?* explains each.
- **Mute my mic while a sound plays** (Setup → *Who's listening*): others hear
  only the sound, clean, and your mic comes back the moment it ends. Or the
  opposite, *While I talk, lower my sounds*.
- **Volumes:** sounds → them, your voice → them, your headphones. Exact % boxes go
  up to 1000%; a soft limiter stops hard clipping. "Level volumes" makes every
  sound equally loud.
- **7-band equalizer** on your voice, your sounds, or both, with presets.
- **Test mode:** *Hear what they hear* plays your mic plus the sounds exactly as others
  get them (its button stays lit while it's on).
- **Connect your chat** (Setup tab): *Make it sound clean in Discord* (Bun sets Discord
  up himself, see *Discord set-up* below), *Set up game voice chat*, *Zoom, Teams or a
  browser call*, *Game has no microphone setting?*, and the *Step-by-step guide* with Bun
  (your mic and headphones, where your sounds go, then Discord). **Also play on** (Setup → Devices)
  gives extra outputs a copy of what others hear, each with a − to remove it.
- **Search the web for sounds** from the Sounds tab: Enter in *Search sounds* lists
  results (thumbnail, title, length) in place of the pads, from YouTube, YouTube
  Music, SoundCloud, **Myinstants** (short meme sound buttons) or TikTok sounds
  (reposted on YouTube); *Play* plays one once, *Add* keeps it as a pad (only the
  audio is downloaded, via [yt-dlp](https://github.com/yt-dlp/yt-dlp)). Instagram
  and most other sites have no search without an account, so paste a link to the
  video instead.
  The Search button's menu also has **Trending on Myinstants**: the meme sounds people
  play most there right now (the ones for your country), with nothing to type.
  YouTube's m4a/webm audio needs FFmpeg, like a dropped m4a file does. Settings →
  Updates → *Helper programs* lists FFmpeg, yt-dlp, the JavaScript engine and Tor,
  with *Update now* and *Reinstall* for when downloads start failing, and an
  opt-in box to update yt-dlp automatically (off by default). A yt-dlp update only
  installs a version this project approved (`pins/yt-dlp.json`, checked against
  yt-dlp's signed PyPI release and added by a reviewed pull request) once it has been
  out for 3 days, and never one older than the built-in copy. When a site breaks and
  no approved version fixes it yet, *Force update* installs PyPI's newest yt-dlp right
  away, after a warning that it isn't approved yet. FFmpeg and
  Tor copies the app downloaded follow the app: an app update that names a newer
  version fetches it (checked against its SHA-256) at the next start.
- **Discord check:** while it runs, Onion Board reads Discord's own voice settings
  and shows a bar across the window when one would cut your sounds out (Noise
  Suppression, the Studio profile on your mic, Echo Cancellation, automatic input
  sensitivity, Advanced Voice Activity); *Fix Discord* has Bun set it up.
- **Discord set-up:** Bun saves how Discord is set for talking, then switches off what
  chops up your sounds (Custom profile, noise suppression, echo cancellation, automatic
  gain and sensitivity off). Discord has to be closed while he writes: if it's open, he
  asks first, closes it, and opens it again on its voice settings. A copy of its settings
  folder is kept first. Discord's own noise suppression stays off: *Clean mic* on the
  Voice tab takes the background noise out of your voice instead, without touching your
  sounds. *Put Discord back* (Settings → Audio → Mic effect) undoes it,
  and *Put Discord back for talking on close* does it whenever Onion Board closes. On the
  virtual cable you still pick *CABLE Output* as Discord's mic; its guide shows where. With *Straight into my mic*, an app that opens your mic
  in "raw" mode (and so skips your sounds) is named in a warning bar too.
- **Your language:** Settings → Appearance → *Language* opens a searchable list of English
  and 32 other languages, each in its own name (Arabic right to left). Windows set to one of them
  gets a one-time offer to switch.
- **Tabs:** a new install starts with Sounds, Voice and Setup; the rest wait under
  **+ More tabs** and are added when clicked. Settings → Tabs switches any of Radio,
  Apps, Triggers or Voice off so it doesn't load at all.
- **Community:** *Join the Discord* (Settings, the tray menu, *What's new*) opens the
  Onion Board Discord for help and news.
- **Data & quality** (Settings): *Use less data*, download quality, the radio's
  bitrate limit, *Slow or patchy connection* (waits longer before giving up), *Also
  save the video* for links, and *Show pictures and like counts* in search results.
- **Screen readers:** buttons that only show an icon are read out by name.
- **⚙ Settings** (a search box above the categories keeps only the cards with the word
  you type; changes apply at once):
  - **Privacy & security:** a switch for each thing the app does online, and Offline mode.
  - **Connection:** direct, a proxy or Tor, *Network activity*, and *Keep an app log*
    (off stops `onionboard.log` being written and deletes it).
  - **Data & quality:** download sizes, radio quality and search extras.
  - **General:** the window (*Keep window on top*, *Play pads with one click*), tips,
    starting with Windows, backups and *Start over* (*Reset* just the parts you pick,
    with a restore point first; *Restore points* undoes it).
  - **Tabs:** switch the Radio, Apps, Triggers or Voice tab off so it doesn't load at all.
  - **Appearance:** 33 themes in four groups, switched live, the season's limited edition first (Halloween in
    October, Fireworks in November): Classic (Dark, Light,
    true-black Midnight, High Contrast…), Colourful, Wild (Synthwave, Hacker, Amber
    Terminal…) and Meme (Flashbang, Deep Fried, Retro 98, Comic Sans…); your own
    highlight colour, how live tabs show (a tint or a dot), the language, the
    interface size.
  - **Audio:** devices, *Also play on*, the stream output and buffering (Low or Safer,
    with a count of drop-outs).
  - **Hotkeys**, **Overlay**, **Updates** (when to check, maintenance), **Add-ons**
    (Onion Watch and Onion Pocket), **Remote**, and **About** (version, links, the
    Discord, feedback, bug reports and support).
- **MIDI pads and macro keypads:** a pad controller (Akai LPD8 / MPD, Launchpad,
  any USB MIDI keyboard) works without extra software: set a hotkey and hit a pad
  instead of pressing a key. Pads work for sounds, stop / pause, random sounds and
  the overlay. A controller is only opened while a hotkey uses it, so your music
  app can have your other MIDI gear. On Windows only one program can use a MIDI
  device at a time: if one is busy, Onion Board says so and picks it up once it's
  free. A cheap USB macro keypad works too: set its keys to F13–F24 (keys nothing
  else uses) and use those as hotkeys.
- **Stream Deck and scripts (optional, off by default):** Settings → Remote →
  *Remote control* lets programs on this PC play your sounds: a Stream Deck (with
  the [Onion Board plugin](https://github.com/Onion-Alien/onion-board/releases/latest/download/com.onionalien.onionboard.streamDeckPlugin), a *Play sound* key per sound
  picked from a list, lit while it plays; or Bitfocus Companion, Touch Portal, website
  buttons), AutoHotkey or a script.
  It only listens on this PC and needs the key shown there (*Copy an example link* gives a
  ready-made "play a random sound" link). Besides playing and stopping sounds it can
  mute you (a panic button), switch the voice changer on or straight to a voice,
  say a typed line in the computer voice, queue sounds or play a whole category in
  a row, turn the mic and *Hear what they hear* on or off, change the volume and
  category, save the instant replay, change the live speed, pitch and effects,
  switch who's listening, run the radio, send a program from the Apps tab, put on one
  of *My voice combos*, switch every hotkey off while you type, and take **chat commands**
  (`!sound`, `!random`, `!say`… with cooldowns and who may use each) and **alerts and
  donations** (follows, subs, bits, raids, tips, channel points, TikTok gifts) from
  Streamer.bot, Firebot, TikFinity and the like; `/api/help` lists it all and
  [CONTROL-API.md](CONTROL-API.md) explains it. New to it? The
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
  and sends an anonymous daily count (version, tabs opened, and a random ID that shows how people use the app over time); each has its own switch.
  Little touches that follow the time of day read your PC's clock and never send it.
- **Runs in the background:** closing the window keeps it in the tray (hotkeys and
  the overlay keep working; right-click the tray icon for *Open Onion Board*, *Stop
  all sounds* or *Quit*). Optionally
  **starts when you sign in**, straight to the tray (Settings → General).
- **Updates itself:** each time it starts, and every hour after, it checks GitHub for
  a new version (untick it in Settings → Updates). One found as it starts installs
  itself behind the loading screen (*Updating to X… 42%*): downloaded, checked against
  the file GitHub lists, installed, and the new version opens, keeping your sounds and
  settings (untick *Install updates by themselves* to always be asked). Found later, *Update now* downloads it and *Restart now* installs it. An **important fix** (a release
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

It works with Equalizer APO on the same mic, whichever went on first: your EQ still
runs, Onion Board's sounds still get through, and taking either off leaves the other
working.

With the virtual cable:

```
🎤 your mic ── send ✓ / ✗ ──┐
                            ├─►  Onion Board mixes them  ─►  CABLE Input ═══ pipe ═══► CABLE Output
🔊 your sounds ─────────────┘                                                          (Discord / game mic)
```

The virtual cable is a free audio driver that works like a pipe: Onion Board plays
into one end, and Discord or the game uses the other end as a microphone. You hear
the sounds in your own headphones separately.

Setup → Devices → **Send my sounds to** picks between these, any other output by name
(Voicemeeter, a mixer, a capture card, OBS) or *Nobody* (your headphones and the
stream output only).
