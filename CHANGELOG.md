# Changelog

Changes not released yet are in [changelog.d/](changelog.d/), one file per change.

## 2.8.0 — 2026-10-31

- Playlists found by a YouTube search say how many videos they have ("8 videos") on
  their card, so a short one is easy to tell from a huge one before opening it.
- Edit sound: clicking Save a copy now adds the edited copy and leaves the original as it
  was (it saved the edits onto the original and made no copy).
- Edit sound: a window opened for the next sound no longer shows the last one's
  "Deleted … Undo" row, and its Preset list has presets saved in another Edit window.
- Edit sound: the effects line says 1.25x when the speed is 1.25x (it said 1.2x).
- Fixed: on a busy PC short of memory the window could freeze for 10-30 seconds while
  Windows was slow to list the sound devices, or when settings were saved after a quiet
  spell.
- Live controls: change one of your presets after picking it and Save preset turns into
  Update, saving the change into it. Its menu also has Reset (back to how it was saved)
  and Save as a new preset.
- Edit sound has the player now: play / pause, stop, skip, the seek line, Sounds for
  others, Hear it myself, the Now playing chips and Stop all, over Save. A big Edit sound
  window no longer hides the only way to pause the song.
- Uninstalling no longer asks for Windows' permission a second time over the mic helper's
  folder, and deleting your data now removes ProgramData's folder too. Installing again
  before restarting no longer loses the mic helper at that restart.
- The credits of the Arabic, German, Spanish, Hebrew, Hindi, Italian, Japanese, Korean,
  Russian, Swedish, Turkish and Ukrainian translation models now say their licence (MIT or
  CC0, from Argos Translate) and that each includes a Stanza tokenizer (Apache-2.0).
- Settings → About has a "Star Onion Board on GitHub" button next to Source code.
- Edit sound has an Advanced view (the Simple | Advanced switch next to its tabs): a bigger
  window with the waveform big across the top (a time ruler, zoom with the buttons or
  Ctrl+scroll, the fades drawn where they happen) and Speed & loudness, Effects and the
  Equalizer side by side. Effects lists only the ones that are on, with Add effect to pick
  more. It remembers which view you used last.
- Edit sound has Undo and Redo for the trim, effects and fades (Ctrl+Z, and Ctrl+Shift+Z or
  Ctrl+Y).
- Edit sound's Preset and Voice boxes now line up.
- Live controls show a playing sound's unsaved Edit sound changes while they're what plays
  (they showed its saved effects until Save).
- Before it changes Discord's voice settings, the app now keeps only those settings, not
  a copy of Discord's settings file (which can hold your Discord login). Copies older
  versions kept are deleted when the app starts.
- Uninstalling now asks whether to delete your sounds and settings too (No keeps them;
  Yes puts them in the Recycle Bin), and removes Onion Pocket's firewall rule.
- The installer now says before it adds FFmpeg through winget, the FFmpeg download bar
  says where it comes from and how to switch it off, and the VB-Cable box says it's
  VB-Audio's driver and not open source.
- The privacy page and SECURITY.md now say exactly what the app reads and writes in
  Discord's settings, and where the copy it keeps before a change is.
- When Bun sets Discord up for your sounds and turns its noise filter off, it now turns on
  Clean mic in its place, so background noise still stays out of your voice. The Discord,
  game, Zoom/Teams and Steam guides point to Clean mic too.
- New privacy page (docs/PRIVACY.md): what the app sends, how to turn each part off,
  what it changes on your PC and how to remove it all.
- Where Onion Board tells you to switch off Discord's, a game's or a meeting app's noise
  suppression, it now says Clean mic on the Voice tab takes out the noise instead.
- Edit sound: Reset effects on a playing pad that was saved with effects no longer gets stuck at "Applying to the playing sound: 0%".
- Edit sound: the trim's waveform shows where the sound is playing now.
- Live controls show what's playing: the song's own effects from Edit sound (speed, pitch, bass, reverb, echo…) plus Live controls' own, which stay on for the next song.
- The Categories menu on a pad now shows a subcategory as "Parent › name", so one with the same name as a category no longer looks like a broken copy of it.
- When the mic effect can't start on your mic, the log now says what was in the way: its
  file taken away (often an antivirus), Windows' Audio enhancements switched off, or no
  log ever written. A failed add-on install logs the last lines its step printed.
- Save your own presets: Live controls has a Save preset button and a My presets row
  (one click puts back the speed, pitch, effects and volume; right-click to rename or
  delete, with Undo), and Edit sound → Effects has Save as preset, with yours in the
  Preset list for every sound.
- A pasted playlist link (YouTube, a SoundCloud set and other sites) now shows its videos
  as cards with Add all, instead of saying "That's a playlist". Up to the first 30 videos.
- YouTube search results have a Videos / Playlists switch beside Back. Open on a playlist
  shows its videos with Add all, and Back goes back to the playlists.
- Playlist cards in YouTube search also have Add all, to add every video without opening
  the playlist.
- Taking the mic effect off a mic no longer stops halfway with an error, leaving its notes
  behind.
- A link you already have in your Sounds no longer counts as a failed download in the
  anonymous usage count.

## 2.7.3 — 2026-10-30

- Adding a sound you already have now shows you where it is: the board jumps to a tab that
  has it (All, when it isn't on the one showing) and a yellow ring pulses round it for a few
  seconds.
- Live controls: with *Keep pitch* off, a note under Pitch says how much the speed moves the pitch (Nightcore: +4.5 st), and the total with your own pitch on top. The Pitch slider only holds the shift on top, so it read 0 st.
- A Voice tab that's switched on (Clean mic, the voice changer, an AI voice, another
  language) shows a small green dot after its name instead of blue words, and the card at
  the foot of the sidebar lists each one in green under *On* and *Stop all*, one click to
  its tab. The lines there (Tor, a proxy, Lite mode) now sit centred between the buttons.
- The laser duel between the two logos on the Triggers page looks like one now: each logo
  charges up, fires a glowing bolt that knocks the other one into a wobble with a
  shower of sparks, and in the last round the beams clash in the middle.
- Live controls: a Volume slider (0 to 400 %) with quick buttons, on the Sounds, Radio and Apps tabs. Over 100 % the loudest bits are rounded off instead of crackling. Presets leave it where it is; Reset puts it back to 100 %. *Save as new pad* keeps it.
- Fixed: "Make your own voice" (and other windows opened from a card on the Voice tab) drew a black background with unreadable words in light themes like Retro 98.
- Changing the theme no longer freezes the window for half a second or more on a full
  board: only what's on screen is restyled at once, the hidden tabs and closed windows
  just after.
- The Apps tab no longer re-reads the running programs every 5 seconds after you leave it
  when no program there is remembered, sent, recorded or clipped. Cards that went quiet are
  tidied up when you open the tab again.
- Bun's loading screen comes up about twice as fast when you open Onion Board (half a
  second instead of over a second, and about 1 s instead of 2 s right after installing),
  so there's no blank wait that makes it look like nothing happened. Opening it a second
  time meanwhile still just brings the first one up, with no second loading screen.
- Fix: a sound pressed right after the app opens, while it's still loading, now plays
  as soon as it's ready instead of being ignored (pads, hotkeys and the control API).
- The usage count no longer reports a failed start when Onion Board was opened twice at
  once (the installer's last page and a double-click on the desktop icon): the copy that
  quit as the second launch was counted as a start that died.
- Onion Board no longer says your mic or speakers can't be found right after it starts
  (and keeps trying every few seconds) when Windows lists the sound devices slowly.
- Clean mic has Mic settings (the cog next to its switch), laid out like a voice chat
  app's voice settings: Input volume, Input sensitivity (automatic, or your own level on a
  live bar), Noise suppression (Off, Light, Normal, Strong) and Automatic gain control,
  plus presets: Normal, Loud room, Just my voice and Quiet room. They only change your
  voice, before your sounds are added.
- The window no longer freezes while Windows is slow to list the sound devices (a slow
  audio driver, or a headset being plugged in or out): it shows the last list it had
  and picks up the new one when Windows answers.
- The anonymous usage count says a little more when a download, a web search, getting
  FFmpeg, the mic effect's set-up or an add-on install fails for a reason it had no word
  for: the error's type and the line of the app's code, a web status or Windows error
  number, or which wait ran out. Never the message, a link, a path or a title.
- Bun's games: quick draw, rock paper scissors and tic-tac-toe are gone. In their place are
  three harder ones he picks at random along with Pong: Dodgeball (dodge his throws, hit
  him while he winds up), Home run (bat at the ball's height, swing on time, leave the
  ones outside the box) and Whack-a-Bun (20 Buns before 5 get away, never the carrots).
  He gets quicker as the points go in, so winning takes real play. The Grid Master and
  Rock Solid achievements now go with Whack-a-Bun and Home run.
- **Clean mic** also filters out deep rumble (desk bumps, low hum), and on Normal and
  Strong turns your mic down between your words, so a TV or someone talking across the
  room doesn't come through while you're quiet. Your words aren't touched, and it adds
  no delay.
- *Clean up my mic* is gone from *Edit voice*: **Clean mic** on the Voice tab does that
  job now, for every voice and with no voice on. If you used the voice changer with
  *Clean up my mic* on, Clean mic is switched on for you (Normal) the first time you
  start this version. Saved voices and share codes that still have the old effect load
  as before, without it.
- When the setup guide's mic test fails (the mic won't open, or nothing is heard for 10
  seconds), or putting your sounds into your mic doesn't work, a "Didn't work? Send us a
  report" button shows under the message. It first shows what the form will be filled
  with (Windows version, the mic's name, direct or cable, a short error code), then opens
  the feedback form in your browser. Nothing is sent unless you submit it.
- The anonymous usage count now says how the setup guide's mic test went (heard you, stayed
  quiet, wouldn't open, no mic, or Windows' privacy settings keeping apps off the mic), so
  mics that don't work can be found and fixed. Never the mic's name; off with Usage count.
- The pause sign on a paused sound is now two tight bars; some fonts spaced them far apart.
- Live controls: new presets people actually use: Nightcore (1.3x, pitch rises with it), Slowed + reverb, Bass boosted, Chipmunk, Deep voice and Underwater. Blown out, Concert hall, Canyon and Phone call are gone. On the Radio and Apps tabs, Nightcore and Slowed + reverb change the pitch instead of the speed.
- Fix: when Clean mic isn't in your copy, a small empty box no longer flashes up on
  screen for a moment while the app starts.
- Fix: a notice from a job that finished after its window or dialog was closed no longer
  shows an error; it is just skipped.
- An invite from a name in Cyrillic, Chinese, Korean or another non-Latin script now
  greets your friend with that name on their first start (the installer used to turn it
  into question marks, so no greeting showed).
- New **Clean mic** tab, first on the Voice tab: it takes fans, keyboards and other
  background noise out of your mic while you talk, free and on your own PC (about 5% of
  one CPU core, ~30 ms). Light or Normal; it works with or without a voice on, stays on
  from last time, and its chip in the Voice tab's bottom bar turns it off. *Hear the
  difference* records 5 seconds and plays them back as they were and cleaned, in your
  headphones only.

## 2.7.2 — 2026-10-27

- A big board no longer freezes for seconds when its sounds change with many Onion Watch
  triggers set up, or when you switch themes: dropdowns are measured once after they're
  filled, not once per item.
- Two more freezes on PCs short of memory: checking which game is in front (for *Who's
  listening*) asked Windows on the window's own thread every few seconds, and one PC
  sat in it for minutes; it now runs on a helper thread. The anonymous usage count
  reads its saved problem reports there too, never on the window.
- The anonymous daily count now says why a fix from the Mic effect card failed (a fixed
  reason word such as `code-8` or `unverified`, never the message), and counts No to
  Windows' prompt on its own instead of as a failure.
- The old website address (onion-alien.github.io/onion-board) shows the whole site again
  instead of forwarding, so old links work as before, downloads included. onionalien.com
  stays the main address.
- Saved clips survive a damaged clip list (a power cut mid-save): they're found again
  from their files instead of being deleted at the next start.
- Restarting the app (a language change, a reset) no longer hands the browser and the
  update installer the old copy's dead connection as your proxy.
- A sound pack that's too big to import is no longer kept in *My sound packs*.
- Resetting *Settings* keeps how the app goes online: Tor, a proxy, Offline mode and the
  features you switched off stay as they are.
- Restore points no longer keep your API key, Twitch login or proxy, and restoring one
  never brings back a key you have since changed.
- The usage count no longer saves up what happened while *Count me in* was off to send
  once it's back on, and nothing goes out in the moment after you switch it off.
- A link download that names no size is stopped once it passes the size limit, instead
  of filling the disk.
- A very long title or page from a site can no longer freeze the app while it's read.
- The app log names the proxy's kind only, never its address.
- Twitch: a sign-in renewed while the link restarted is kept (you were signed out), and
  Disconnect clears the older copies of your settings too.
- Auto push-to-talk lets go of the key when the app stops answering, so a frozen app
  never leaves your game's mic open.
- The local relay and the control API drop connections that are too slow to send their
  request, and the control API answers "busy" instead of dropping requests when many
  local tools call it at once. A web page can no longer lock a phone out of Onion Pocket,
  and a request that sends the same value twice is refused.
- Removing an add-on removes its old copies too, so one can't come back by itself.
- First start no longer moves in another program's `%APPDATA%\Soundboard` folder.
- Discord set-up keeps a copy of only the file it changes, for two weeks, not of all of
  Discord's stored data.
- Installing a Windows voice no longer runs a script file from your temp folder as admin.
- Onion Pocket no longer starts when Windows can't say whether the network is Public:
  it's turned away as on a Public network, never taken as a home one.
- The player's Video button no longer freezes the window for a moment while it checks the
  video is still there (on a sleeping drive, say), and sound files dragged into the
  sounds folder no longer make the window stutter while the folder is looked through.
- A tidy-up under the hood with a few small speed-ups: the live pitch effect no longer
  copies its history on every audio block, list-view pads and the EQ curve take less
  work to draw, and the status card no longer redraws twice a second while Tor connects.
- The installer and the Stream Deck plugin no longer keep the build PC's local time in
  their files' time stamps.
- Settings → About has an Invite a friend card: copy a link to the download page with your
  name or gamertag on it, and the app says who invited them on their first start. The download
  is counted, but never your name.
- The website moved to https://onionalien.com/onionboard/ (Onion Watch:
  https://onionalien.com/onionwatch/). The Website button in Settings > About, the
  Stream Deck plugin and the README now open it, and the old address forwards there.
- A sound playing when your headphones switch to a device at another sample rate (Windows'
  default output moving to SteelSeries Sonar's 96 kHz Gaming device, say) keeps playing
  there instead of stopping, and a device Windows refuses to start for a moment right
  after such a switch is tried again at once instead of showing an error.
- SteelSeries Sonar users: when Windows restarts its audio (a driver or Windows update,
  another app's installer) while Onion Board is open, Sonar moves your mic to another
  device, often a silent virtual cable, so Discord stops hearing your voice. Onion Board
  now notices and sets Sonar's mic and channels back within seconds.
- Updating while Discord was still open after you'd closed Onion Board no longer lists
  Onion Board as running, and Discord's voice clean-up still comes back on when Discord
  closes (the update used to end the small helper that does it). Uninstalling now
  puts it back at once, or says how to if Discord is still open.
- Settings > Achievements: every achievement is now worth points by its rarity (Common 10
  up to Super Rare 200), and your total score shows at the top of the page.
- The mic helper and the mic effect's admin step can no longer be steered by a folder
  link another account on the PC puts in Onion Board's shared folders: they work through
  handles to folders they checked, and a link is removed, never followed. The helper
  updates once (one Windows prompt).
- The removal tool no longer follows a link someone put at `%ProgramData%\OnionBoard`.
- Names and titles from the web, other soundboards, backups and packs always show as the
  text they are: one that looked like HTML could make Windows contact another server,
  around the proxy, Tor and Offline mode.
- A board file from another soundboard that lists sounds on a network share no longer
  makes Windows connect to that server: those sounds are left out.
- A custom voice program that's a script (`.bat`, `.cmd`, `.ps1`) or a shell no longer
  gets the line to say on its command line, where Twitch chat could run commands; use
  `{text_file}` or the program's input instead.
- Twitch: a "no such sound" reply posted from your account goes through the blocked words
  and link rule first and counts for the cooldown, and a viewer's name read out in chat
  TTS is filtered too. Twitch signing you out also resets *Let the developer see this
  channel's name*.
- Backups no longer carry the auto push-to-talk key, Twitch chat rules, the store's vote
  id, privacy switches or this PC's Discord state, and a sound pack can't take a key every
  app uses (Space, a letter, Ctrl+C).
- Onion Pocket's firewall step adds one rule for Onion Board only, not a second one for
  any program on that port.
- Quitting only puts back a Discord that Onion Board set up itself.
- A voice server's key is never sent on to another site by a redirect, and a carrier's
  NAT or a tailnet (the shared address range) counts as the home network.
- Live voice no longer writes what you said into its log, and its log goes with the app
  log when *Keep an app log* is off.
- Admin steps start Windows' own tools from System32, never by name.
- The installer's Cancel for the extras stops them again.

## 2.7.1 — 2026-10-23

- SteelSeries Sonar: with Sonar's Gaming device (a 7.1 device) as your headphones,
  you now hear your sounds. The app couldn't open it ("That audio device doesn't
  support that many channels") and stayed silent in your ears.
- Direct mic: when the background mic helper can't set up your mic (mostly on
  Windows 10), clicking set-up now asks Windows once and does it that way, instead of
  failing with "code 1" every time. A set-up that worked is no longer reported as
  failed when the helper itself couldn't be set up afterwards.
- Direct mic: after setting up, the app checks with a short, very quiet test sound (never
  in your own headphones) that your sounds really come out of your mic, and adds what it
  found to the anonymous usage count. Nothing changes on screen yet.
- A headset pulled out while the app is open now says so in plain words ("Can't open
  ... Plugged in? It's tried again by itself.") instead of a raw device error.
- Fixed a crash while the app was starting: on a slow start, the check that notes where start-up is waiting could itself crash the app.
- Direct mic: setting up on SteelSeries Sonar's mic in a quiet room no longer restarts
  all your sound three more times, restarts Sonar and calls the set-up failed when
  Windows wouldn't let the app listen to the mic just before.
- Direct mic: setting up, repairing or removing the mic effect checks its work: after
  Windows' audio restarts, the effect has to have started on your mic and every mic it
  touched has to open in apps again. If not, the audio restarts once more, and if it's
  still not right the app says so (with an error code) instead of "done" while your
  sounds never reach the mic.
- Direct mic: with SteelSeries Sonar on, a set-up, repair or removal no longer leaves
  Sonar's mic silent in Discord and other voice chats, or its sound on the wrong
  device: the devices Sonar used are set back through Sonar itself after Windows' audio
  restarts, in its streamer mode too. Sonar is no longer restarted for it (SteelSeries GG restarts Sonar only 3
  times, then leaves it off). It's restarted once only when it won't take its devices
  back, or when its mic had already lost its device (after a set-up with 2.7.0), so
  that its mic has a device again.
- Direct mic: the quiet check sound played after setting up no longer breaks the sound
  sent to others: it stopped your sounds and your voice reaching Discord and games until
  the app was closed, with an "audio callback failed" error.
- Direct mic: uninstalling Onion Board after the mic effect was already off no longer
  restarts all of Windows' sound for nothing (it cut every app's sound for a moment, and
  with SteelSeries Sonar on, it could restart Sonar).
- Direct mic: Sonar is no longer restarted when, after Windows' audio restarts, it won't
  take back one of its Game / Chat / Media / Aux channels while its mic is fine (Sonar
  picks those again itself). That could use up SteelSeries GG's 3 restarts of Sonar in
  a few set-ups, and then Sonar stayed off.
- SteelSeries Sonar users who set up direct mic with an earlier version: Windows' audio
  restart made Sonar switch its mic to the first device it lists, which isn't always
  yours (a webcam, a virtual cable). If Discord hears you badly or not at all through
  Sonar, pick your mic again in SteelSeries GG > Sonar. This version keeps it.
- Direct mic: the mic helper updates once (Windows asks one more time), so set-ups
  through it get these fixes too.
- Once you've connected Twitch, the Twitch card has a box (off until you tick it) that
  lets the Onion Board developer see your channel's name with the daily usage count,
  so they can see who streams with it. Disconnect unticks it.
- Pilot Bun's world on the Languages card is 3D now: a lit, turning Earth with drifting
  clouds, a night side and glowing air, and Bun's plane is a real 3D model flying low
  over the curve of the world, with a contrail and his shadow on the ground.
- Fix: on a PC short on memory, the app could freeze for 10 seconds to minutes at a
  time, sounds included, while it sat in the background (and Windows could call it Not
  Responding). Its memory clean-up read the whole app back from disk; it now waits until
  you're back in the window and the PC has memory to spare.
- 18 new secret achievements to find: poke the Onion Alien on Settings > About, add or
  listen through an hour-long sound, play 10 sounds at once, max out the pitch, play a
  sound on Halloween, Christmas or New Year, and a few more. There's an old cheat code
  hidden in the main window too.
- No "Text-to-speech isn't available" pop-up at launch when Windows speech is slow to start: nobody asked for speech yet. Saying a line still tells you if it can't be spoken.
- On a first launch right after installing, the loading screen (Bun) no longer gives up
  when its first frame is slow: it used to vanish, and nothing showed until the window
  was up, up to a minute later. A start that slow now also notes where it waited, in
  `startup-stall.txt` in the settings folder.
- The installer no longer asks about FFmpeg: the app needs it for M4A, AAC and video
  files, so it is always added when it is missing (not in Offline mode).
- Direct mic: a mic whose headset software adds its own effect (some gaming headsets do)
  no longer goes silent in every app when that effect won't run alongside Onion Board's:
  the mic now goes on without the headset's effect.
- Fixed: after the PC had slept, a crash or a closed-from-Task-Manager exit was counted as "frozen" in the anonymous problem count. The exit check now uses the same sleep-proof clock as the freeze check.
- Fixed two causes of the app freezing for seconds on PCs short of memory: the audio
  device check no longer starts a new background task every half minute, and a safety
  check over the app's windows no longer runs while the app sits in the tray.
- Direct mic: a headset whose software adds a Windows 11 style effect to the mic
  (Logitech G HUB's Blue VO!CE, Windows' own Voice Clarity) keeps that effect with
  Onion Board's effect on. It used to be switched off, without a word, while direct
  mic was on.
- Fixed the window freezing for as long as the PC's drive stalls (half a minute on some
  drives): a memory check the window runs every few seconds looked on disk for a
  Windows file each time. It looks once now.

## 2.7.0 — 2026-10-22

- The tick next to "Your sounds go into your mic" now sits level with the text.
- The tutorial cards' quiet button says OK instead of Not now.
- Lite mode: Pilot Bun on the Languages card flies round the globe again, at half the
  frames, instead of sitting still like a broken picture.
- **Voice > Languages**: with Offline mode on and speech recognition not installed yet, the Languages tab hides (nothing there could work or be installed); once installed it stays, as it works offline. Before it is installed, the card no longer shows an ON / OFF switch and "Pick a language" with no languages to pick.
- The Voice tab's bar has a Reset button: it turns every voice off and forgets them, and
  empties the voice changer's mix, so Voices ON no longer brings an old voice back. Undo
  puts it all back.
- AI voices: an AI voice that gets stuck loading now tries once more by itself, then
  says it couldn't load, instead of staying on "starting…" forever. Picking another voice
  while it loads no longer says "switching to…" (you still hear the backup voice until
  it's ready), and the voice bar's chip names the voice you picked.
- Live controls has a **Save as new pad** button beside Reset: it copies the sound playing
  now, with the speed, pitch and effects you dialled in, as a pad of its own (named
  "… (modified)", which you can change). Its Edit sound window shows those effects and can
  take them off.
- The anonymous usage count now also says whether Live controls is opened and changed
  (which control, never the values), which achievements were earned and roughly how
  many, and whether Lite mode, Connect Twitch, Voice tab recordings, the voice search
  and the Stream Deck plugin are used. A long daily count goes in parts (the counter
  takes 100 at a time). Everything it can send is listed in SECURITY.md.
- AI voices: the Make your own voice window is tidied up: no emoji box next to the name, more room under the heading, the sliders and their values lined up, and Hear it beside Save and Cancel. You can pick a picture for your voice's card; without one it gets the My own mix picture.
- AI voices: Make your own voice works when the app runs from source too. It used to do nothing there, because your voices were only written into a downloaded copy of the add-on; the add-on now also reads them from your own voices file.
- A settings file whose sound list was blanked out (`"sounds": null`) no longer opens as an
  empty board: like other damage, it is set aside, your last good copy is loaded and you
  are told.
- A download whose last piece never arrives now stops within seconds, instead of asking the
  site for it again hundreds of times over a minute first.
- Tab no longer stops on every sound: it goes from the categories to your sounds once
  (the arrow keys move between them), then on to the player bar, so Stop all and
  Settings are a few presses away however many sounds you have.
- A headset pulled out while the app is open no longer stays in the headphones list,
  where picking it did nothing.
- Chat text read out by the voice (!say and chat-to-speech) no longer reads HTML tags
  and codes like "&amp;" letter by letter: they're taken out, or turned back into "&".
- Switching Keep window on top no longer turns the whole window white for a moment.
- Settings opens without the Audio page jumping down as its mic row comes in.
- Picking a device in Settings no longer makes the drop-downs twitch.
- The Apps tab's cards show together instead of jumping in one by one, and opening or
  closing a program's window view, or filtering Achievements, no longer jitters.
- "Hear what they hear" comes back in full after the window is made narrow and wide again.
- Edit sound and Edit voice are split into tabs instead of one long page: Edit sound has
  Sound, Trim & speed, Effects (in groups) and Equalizer; Edit voice has Main, Change the
  voice, Character and Room, each tab saying how many of its effects are on.
- The Languages card's speech recognition install now looks like the AI voices one: a
  glowing Install button beside Bun flying a little plane round the world.
- Clicks that used to give no answer now do: saving a voice says its name on a card,
  Say with an empty box says to type a line first, Undo after removing a sound says
  it's back, and the Radio list says it's finding stations while it loads.
- Importing several sounds: each pad shows up on the board as soon as its sound is in,
  not a moment after the count says so.
- Live controls no longer opens with plain, unthemed sliders, ticks and buttons after the theme was switched or a page was built while it was closed.
- Screen readers: the Sounds search box says it takes a pasted link too, each Apps card's
  volume says which program it's for, and the Up next chip reads as a button.
- After Pause in the clip editor, the keys (Home, Ctrl+Right, Shift+End…) go straight to
  the waveform instead of the Pause button.
- Up next: long names now fill the list's whole width before they're cut short, and its
  chip says how many are waiting ("3 waiting"), so the number isn't read as counting the
  sound playing too.
- AI voices: the voices you made come first under All, before the ready-made ones.
- Stream Deck: the length and On / Off on small (72 px) keys are bigger and easy to read.
- Clearer in four places: the bottom strip says "Mic muted" when your mic isn't sent,
  Community's dropdown has a line between the orders (Trending, Most liked, Newest) and
  the categories, Trim says your file stays whole, and the Triggers tab says your game's
  window has to be open.
- The Silent But Deadly badge now counts with sending switched off too.
- A sound whose file was moved or deleted now says "its file is gone" and where it was,
  instead of FFmpeg's own error text.
- The setup guide's "Where do your sounds go?" step keeps a plain Next when sending isn't
  set up, with a line saying only you will hear your sounds, and the cable button now just
  says "Install the cable" (its tooltip says what that means). The look step names the
  board's theme when it isn't one of the nine.
- Cancel while Onion Watch is being added now really stops it: it used to install it
  anyway when the click came after the download. Once it's installing, Cancel goes away.
- The Help and community button at the sidebar's foot is Bun now, and its menu ends with Turn into Bun.
- Turn into Bun puts Bun right in the middle of where the window was, instead of a corner or wherever he stood last time.
- Uninstalling now removes the empty Onion Board program folder too (your sounds and
  settings in %APPDATA%\OnionBoard are still kept).
- A damaged settings file no longer leaves a second, scary error in the log when it is
  recovered at start-up; a settings file saved with a byte-order mark keeps its language.
- Stream Deck keys now show a pad's hotkey when it's a combo like Ctrl+Alt+7; before, only
  short keys like F7 fit on a key.
- Community: sort by Newest again, from the dropdown next to the search box.
- Community: Tab goes straight to the cards, not first to the list itself.
- Fix: on a PC short on resources, a long song could start cutting out partway through,
  because the part that reads ahead of it stopped for good. It now carries on.
- Mute mic during sounds: your mic comes back as soon as the sound ends (or you press
  Stop all). It could stay muted for others when your headphones were a moment behind.
- Mic effect: a mic Windows' registry names differently from the mic list is now found
  by asking Windows directly, instead of "Windows doesn't know this mic". When the
  set-up fails, its message has a "Use the cable" button. A mic effect problem no
  longer ends the first-run tour as if the tour had broken: the mic's own message says
  what went wrong.
- Adding a sound from YouTube (or another site) that fails because the site refused it, the
  connection dropped or the download got stuck now tries once more by itself before showing
  an error, asking YouTube in a different way the second time.
- Up next: taking sounds out with the list open now shrinks it at once, instead of leaving an empty gap over the rows until it was reopened.
- Play on a YouTube search result starts about 10 seconds sooner: it no longer waits for
  YouTube's video picture, which Play never shows.
- A pad no longer plays on top of a song you played from a search: like other sounds,
  the song stops (set the pad to Overlap to play over it). Clicking a song's name in
  Up next also stops what's playing before it starts.
- Fewer themes give Bun a floppy ear: Onion, Slate, Paper, Carbon, Retro 98, Amber Terminal,
  Vaporwave and Vampire now have both ears up.
- The Twitch card in Settings → Remote has a *Twitch guide* that walks through channel
  points, alerts and chat commands step by step, and *Copy AI prompt*: a message for
  ChatGPT or Claude that knows your rewards and sounds, so it can help with the rest.
- A voice card that's on says so when you point at it: clicking it again turns the voice
  changer off.
- Bluetooth earbuds (AirPods and the like) work as your mic like any other: no more
  warnings about call quality when you pick them. If their mic drops out while they
  keep playing, the mic card says so in one line instead of "Is your headset plugged
  in?", and a mic whose sound is coming in is never called unplugged.
- *Straight into my mic* works with Equalizer APO on the same mic. Setting Equalizer APO
  up on the mic after Onion Board no longer makes the two start each other over and over
  (which could stop Windows' sound), the repair no longer wraps it back, and taking
  Onion Board off hands Equalizer APO the mic's own effect again.
- Lite mode really stops the animations now: Bun and Hoot are still pictures (sounds,
  music and the mic don't move them), and the guide's ring, the download banner, the
  achievement pop-up and the playing pads hold still too.
- The On Air card says "Lite mode" while it's on; a click opens Appearance.
- Settings > Appearance > Look is easier to read: its settings sit in three small groups
  (Colour, Size and speed, Background), on/off and size are beside each setting's name,
  and the long explanations are shorter.
- Settings > Achievements has two new switches: *Show pop-ups* turns the "Achievement
  unlocked" pop-up off, and *Pop-up sound* turns its chime on. The chime is now off by
  default.
- The first-launch guide's last part is now two steps: pick a look and your language,
  then "A few handy switches" in four cards: your tabs, Discord, Internet and This PC.
  New on it: Use less data and Offline mode (for a phone hotspot, a capped plan or no
  internet) and Keep window on top, so you don't have to find them in Settings.
- Speak another language: no more empty gap between the card's intro and its language cards.
- The voice changer no longer remembers last run's voice when it was left off: after a restart,
  turning it ON starts from your own mix instead of an old pick. Left on, it still comes back.
- The Onion Alien easter egg on About no longer keeps the CPU busy while he sits on the empty window: only he is redrawn, and less often.
- Textured themes (Carbon and others) keep their pattern on a hovered card or box,
  and the buttons on a hovered box in Settings no longer blend into it.
- Live controls: typing a minus into Speed (like `-999`) now gives the slowest speed
  instead of dropping the minus and jumping to the fastest.
- Stream alerts: a raid sent with only an amount now says that many people in `{count}`,
  and a field with no value (a tip with no amount) is left out instead of read out as
  `{amount}`.
- The first-run tour's card moves with the window straight away when it's made narrow
  (it used to sit off the right edge for a moment).
- Bringing sounds over from another soundboard ends with "✓ Added 3 sounds to Soundpad",
  so you know which category they went in.
- Live controls: a speed, pitch or effect value typed into its box and confirmed with Enter
  now stays; Enter used to also press Reset and put it straight back.
- Lite mode now runs the audio in 20 ms blocks instead of 10, so the app uses noticeably
  less CPU with nothing playing. Your voice goes out about 20 ms later in lite mode.
- AI voices use about a third less CPU in lite mode (or with *Use less CPU* on): they
  run a lighter copy of the same voice model, which converts 40 ms at a time, so you
  are about 40 ms further behind. Needs AI voices 0.2.0 (update it under More options).
- The Voice changer, AI voices and Languages cards share one tidy bar over their voices:
  a dropdown picks the group (with how many each holds), a search box finds a voice or
  language by name, and the cards / list switch sits at the end, in the same place on
  all three.
- Making the window narrower no longer makes the Sounds tab's search box wider: it used to
  jump bigger each time a toolbar button lost its words, then shrink again a few pixels later.
- The Radio tab no longer jumps up and down by a few pixels at the width where its refresh
  button comes and goes.
- Downloads, searches, the radio list and the store use less CPU: the app no longer reads
  Windows' certificate list again for every connection.
- The bars across the top of the window (an urgent fix, "Set up for it?", FFmpeg missing,
  the language offer, *Enjoying Onion Board?*) now all look the same: slim, with a coloured
  edge, a bold heading and their buttons lined up.
- The red "You're hearing your mic output" banner is gone: the lit *Hear what they hear*
  button already shows it's on.
- The "Did you know?" tips bar is gone, and with it *Show tips* in Settings → General.
- Picking a voice or flipping Voices ON / OFF while an add-on was installing could
  freeze the window, and the sounds playing, for a second or more. The Voice tab no
  longer checks the disk on every click.
- Lite mode now also slows the meters and the playing screen (15 updates a second while
  something plays, 5 with only the mic), so the app uses less CPU while it sits open.
- The app uses a little less CPU while it sits open in every mode: a safety check that
  went over every window class 10 times a second now runs when something new loads.
- First start is now three steps instead of up to six. Your mic and headphones share one
  page, then where your sounds go, then "Make it yours".
- "What will you use Onion Board for?" is gone. On the last step, Voice starts ticked and
  Radio, Apps and Triggers are tick boxes to opt in to, each with an ⓘ saying what it's for.
- Bun now sets Discord up for your sounds himself. He saves how Discord is set for talking,
  then switches off what chops up your sounds (noise suppression, echo cancellation,
  automatic gain and sensitivity). If Discord is open, he asks before closing it for a few
  seconds, then opens it again on its voice settings. Settings → Audio → Audio recovery's
  *Put Discord back* undoes it. The setup guide's last step ("Set up Discord for me when I
  finish"), the Setup tab's Discord button, the Fix Discord bar and the Discord guide all
  do this now.
- Earning an achievement now pops up "Achievement unlocked" at the bottom of the screen,
  the classic console way, with its chime in your headphones only (never in the call).
- Importing from another soundboard (Soundpad, Resanance and others) no longer asks "are you sure?" first: picking it is enough. Sounds that can't be brought over are listed in a short note instead.
- Every achievement now has its own badge: Bun dressed up for it (a crown, a beret, the
  bat, Robo-Bun, the rare Golden, Ice, Galaxy and Rainbow looks and more) in a rim of
  its rarity's colour.
- Settings > Achievements has filters: All, Earned or Not yet, and a rarity.
- Bun now waves when the mouse comes onto a theme card in Settings, and clicking the
  board or Onion Watch logo on the Triggers tab fires their laser duel, also on PCs
  with Windows' Animation effects turned off. Lite mode still keeps them still.
- The logo, the level meters, the loading and download bars, the download scribe, the radio
  map's pop-in, the theme cards' wave and the logos' laser duel now draw 24 frames a
  second instead of 30 to 60, so the window uses a little less CPU while it's open.
- Mic effect set-up: fewer failures. A mic that sends no sound itself after the set-up
  (a headset switched off) no longer counts as a failed set-up: your sounds go in, and
  a warning says the mic is silent. A picked mic Windows no longer knows is swapped for
  Windows' default mic instead of stopping. A step that failed once is tried again,
  the same mic part already there is kept instead of written over, and a slow PC gets
  longer for Windows' audio to stop and for the effect to load.
- New: Settings > Achievements (under Show advanced). 56 achievements for using the app,
  from your first sound played to 100 hours of voice changing; most stay secret (???)
  until you find them. Each badge wears its rarity's colour, like the rare loading
  screens. They're counted on your PC only and never sent anywhere.
- Bun makes you work for his Pong game now: spam-clicking no longer piles up. Once he has gone red, it takes five more pokes before he fetches his bat.
- The Community tab's dropdown starts with Trending (picked when it opens) and Most liked,
  then the categories, the biggest first.
- Triggers tab: before Onion Watch is installed, Hoot now sleeps in a little bed with
  z's floating up instead of dancing to your sounds. Click him to wake him up; he goes
  back to bed when you leave the tab.
- The onion on Settings > About has a secret. Try clicking him. A lot.
- Edit sound's effects now change a sound while it plays: pick a preset, a speed or a voice
  and the playing sound switches to it at the same spot (a slow voice shows how far it is,
  and the sound plays on as it was meanwhile). Cancel puts it back; Save no longer stops it.
- A big "Reset effects" button sits beside Save, glowing while any effect is on: every effect off at once, and a playing
  sound goes back to plain straight away.
- The Community tab has an Onion Board category, first in the list: only the sounds players
  shared here and the app's own sounds, without the ones from other sites.
- The control API's status now says whether "mute my mic while a sound plays" is on, so a phone remote can show that switch.
- The Community tab shows a small "New" label until you first open it.
- Voice "setups" are now called voice combos, so they're not mixed up with the Setup tab.
- The Voice tab's My voice combos row has a Share button: send a combo to the store or
  copy it as a code for a friend.
- The Community tab opens on Trending: the sounds that are popular right now. Votes and
  Added still sort the list.
- Voice add-ons (AI voices, live voice, translation): when one crashes without saying why, the message now ends with the last line it printed (the actual error) instead of only "code 1", and a reason it did give is no longer replaced by a plain "stopped".
- AI voices: when the AI voice can't start, it now says why (for example "not enough free memory") instead of "exited before connecting (code 1)".
- Downloads now show in a small card in the bottom-right corner, on every tab, instead of
  a big banner across the top that pushed the page down. Minimise it to a pill (it still
  shows how far it's got and how many failed), and once everything is added it folds to
  the pill by itself, then goes; hovering keeps it up.
- Each added sound in the card has a play button and Show, which takes you to its pad.
- **Use less CPU** moved up beside the Voice tab's tabs, since it's for every voice now:
  translating your speech or a stream also uses the smaller speech model (if it's
  downloaded) and simpler translations. AI voices already use as little as they can.
- Radio map: a city's stations all listed at its centre now keep spreading apart as you zoom in, instead of staying one overlapping clump the same size at every zoom.
- The Stream Deck plugin comes with every release now: double-click
  `com.onionalien.onionboard.streamDeckPlugin` and Stream Deck installs it. The Streamer
  guide (Settings → Remote) links to it and says how to set up a *Play sound* key.
- Developers: a source copy run from the temp folder (a throwaway worktree) keeps its own profile, `%APPDATA%\OnionBoard-dev`, so a branch under test can't empty the real sound cache or change the real settings.
- The Voice tab's Languages card now works like Voice changer and AI voices: a big ON / OFF
  next to its name, All / Favorites / Downloaded chips, cards or a list, and a card per
  language. Languages you haven't downloaded are grey: click one and it asks to download
  and install it. Click a language to turn it on, click it again to turn it off. The
  computer voice's own Start moved under More options.
- **Connect Twitch.** Settings → Remote has a Twitch card: click *Connect Twitch*, say yes on
  twitch.tv, and Onion Board plays your sounds when viewers redeem channel points, cheer,
  follow, sub, gift subs or raid. Pick a sound (or a random one) for each channel point reward
  and each alert, right there. Chat can use !sound, !random and !sounds, and the answer is
  posted back in chat. No Streamer.bot or other bot needed. Twitch has its own switch in
  Settings > Privacy & security.
- The control API's `/api/alerts` takes `&reward=` for channel points, so each reward can play
  its own sound.
- Voice tab: every tab with something on gets its blue border at once. With the AI voice
  on and another language spoken for it, Languages lights up beside AI voices (it only did
  while the computer voice spoke).
- Settings opens straight away after you've looked at About, Add-ons, Connection, Data,
  Updates or Remote: it was built again from scratch every time (about half a second on a
  slower PC), and only those pages are now refreshed when you open them again.
- Switching to and from the Setup tab no longer works out the whole window's layout from
  scratch each time (about a tenth of a second each way on a slower PC).
- **Stream Deck plugin.** Onion Board now has its own plugin for the Stream Deck app: add a
  *Play sound* key and pick the sound from a list (no copying links or keys). The key takes
  the pad's colour and lights up while it plays. There are also *Stop all sounds*, *Random
  sound* and a *Switch* key for Live / Muted, the voice changer, your mic or hotkeys that
  shows whether it's on. It finds Onion Board by itself once Settings → Remote → *Remote
  control* is on.
- The control API's `/api/status` now also says whether hotkeys are on (`hotkeys`).
- New on the voice changer card: Use less CPU, for slower PCs. Hiss removal goes off, the
  robot voices and echoes get a little simpler and live voice uses the smaller speech
  model when it's downloaded: the voice changer uses about a quarter less CPU. It's on
  by itself in lite mode.
- Live voice and translations use about a third less CPU: their speech recognition no
  longer keeps the processor busy between sentences.
- The voice changer uses less CPU: the robot voices (Robot, Talkbox, Autotune, Mecha) about
  a third less for that effect, and Clean up my mic, which runs under every voice, about a
  quarter less. The voices sound the same.
- Switching themes no longer redraws the whole board on every frame of its fade.
- Onion Board gives its memory back to Windows after 30 seconds in the tray or minimised
  (with nothing playing): Task Manager shows about 35 MB there instead of ~350 MB.
- AI voice and voice changer samples you listen to no longer pile up in memory: only the
  last 16 are kept.
- Bun and Hoot use about half the CPU while they move: a frame where they have moved less
  than a quarter of a pixel shows the picture already drawn, and a frame where nothing
  moved is not drawn again. They look and move the same.
- New: Lite mode in Settings > Appearance > Look, for slower PCs. One switch turns off
  the animations, Bun's and the logo's idle moves and the theme textures, at once;
  everything else works the same. A slower PC gets one suggestion to try it.
- The board uses less CPU while it sits idle: the audio engine does less work on blocks
  where nothing plays, and Bun and Hoot reuse the shapes that don't change between frames.
  Nothing you hear or see changes.
- The onion menu at the foot of the tab rail is down to Join the Discord, Send feedback and Report a problem (What's new is the version under the app's name).
- Skipping the first-run tour no longer fills a new board with 25 starter sounds in a
  Starter tab: the board stays as you left it. Boards that already got them keep them.
- The first launch looks cleaner: the loading screen hands over to a plain window with
  the logo, the setup guide fades in over it, and the app fades in once you finish or
  close the guide (no half-set-up app behind it any more).
- The first setup guide now ends with "Make it yours": pick your language, one of nine
  themes, and whether Onion Board starts with Windows.
- If Onion Board crashes or Windows closes it as Not Responding, Windows now starts it
  again by itself (after it had been open for a minute or more), without taking the
  focus from your game, and it says it restarted.
- Bun's arm now comes from his shoulder when he holds something (the mic, the bat, the hammer, his idle skits' props), instead of poking out from behind his body or floating as a third paw.
- Switching themes takes about half as long, so it no longer freezes the app on slower PCs
  or ones short on memory.
- The Community tab's Bun and the sad Bun on a "something went wrong" card no longer
  animate nonstop: after 30 seconds with nothing going on they hold still (using no CPU)
  until a sound, a click or a new problem wakes them. The Community tab used half of a
  slower PC's core just sitting open.
- Hoot on the Triggers tab (before Onion Watch is installed) holds still after 30 seconds
  with nothing going on too; the mouse coming near him, a click or a sound wakes him.
- The Voice tab's red Stop is now one big Voices ON / OFF switch. OFF turns off every voice
  changing your mic (voice changer, AI voice, computer voice, translating) and ON brings
  back exactly what was on. With nothing to bring back it says what ON turns on.
- New hotkey, All voices on / off (Settings > Hotkeys > Mic and voice): the same switch,
  from inside a game.
- Click a voice in the Voice tab's bottom bar to turn just that one off (it stays there,
  grey) and click it again to turn it back on. Right-click opens its card; its ✕ turns it
  off for good.
- The Apps tab's Bun no longer keeps animating while nothing plays: after 30 seconds he
  holds still (using no CPU) until a sound, the radio or a click wakes him.
- The Community tab shows each sound as a card, two side by side on a wide window. Play
  plays it now, even over a sound from the tab that's still playing, and turns Pause
  (then Resume) with a Stop button while it plays. Play next waits for what's playing,
  and Add puts it in your Sounds.
- AI voices now look and work like the Voice changer: the same on/off switch at the top
  right, the same cards or list view (one setting for both), and the same bar at the
  bottom for the voice that's on, with Edit voice (its pitch), Make your own voice and
  Hear it. Make your own voice is also a card under Mine.
- The Voice changer and AI voices cards have a big ON/OFF switch right next to their
  name, and clicking the voice that's on turns it off again.
- Community tab: playing a shared link no longer slides the list away when the bar at
  the top opens; the row you clicked stays under the mouse.
- Voice tab: no more big empty gap under the part buttons on a short part (Languages,
  Add-ons); My setups is one line again.
- Fix: the Discord check could get stuck on "checking" for good when it couldn't make its
  test sound. It now says what went wrong, and you can run it again.
- Switching tabs is quicker: the sidebar's status is no longer worked out and laid out
  again on every switch when nothing on it changed.
- Voice tab: the part buttons (Voice changer, AI voices, ...) and My setups scroll away with the
  voices, so a short window shows more of them.
- Edit sound opens at once after a theme change and when Onion Board started with
  Windows: a ready-made one is built under the theme fade, or a while after sign-in,
  instead of on the first click (about a second on slower PCs).
- Settings > Hotkeys in a narrow window: each key sits under its words, which no longer wrap a
  word a line.
- Narrow windows: the Sounds search box says "Search" or "Search sounds" instead of a cut "Sea…",
  and the Voice tab's line box says "Type here" (Save as sound goes down to its +).
- The red "Couldn't open the store" card no longer squeezes its lines on top of each other in a
  short, narrow window.
- Settings > Overlay shows your overlay hotkey again (its button was blank).
- The installer is about 5 MB smaller again: the voice changer's seven background loops
  are now Ogg Vorbis instead of FLAC. They sound the same and still loop without a click.
- The installer is about 11 MB smaller: files the app carries twice (the mic helper's own
  copy of Python) are stored in it once, and the mic helper and the app no longer carry
  parts they never run (the rest of the app in the helper, test tools, PortAudio builds
  for other systems). Everything installs and works as before.
- **Recordings** (Voice tab) and **Saved clips** (Apps tab) have a new look: each clip is a row with a round play button, its name, where it came from and when ("Today 14:02"), its waveform (which fills in as it plays) and its length. A **Live** label shows while one plays through your mic.
- The row you point at (or pick) gets its buttons: play through mic, add to Sounds and more. Space plays a clip for you, Enter plays it through your mic, Esc stops it.
- Voice tab: "No mic open" is no longer cut off in some languages and themes (the mic meter gives way instead).
- Click either header logo on the Triggers tab for a short laser duel with Onion Watch. Other tabs keep the usual logo wobble.
- The Back button over online search results is red with a soft glow now, so the way back to your sounds is easy to spot.
- The store's *Share a sound* button, greyed out while the store can't be reached, has an even edge all round again (its top edge looked cut off).
- + Subcategory and the Apps tab's + Category also open a name box in place now, instead of a pop-up.
- The + next to the category tabs now opens a name box right where the new tab goes: type, press Enter to add it, Esc to cancel. No more pop-up.
- Voice tab: a Record button next to Stop records your voice straight away (as others hear it while the voice changer is on). Saved takes go in a new Recordings list above it, where you can play one to yourself, play it through your mic, or add it to your Sounds.
- Drag sounds in the Up next list by their grip to change the order, and use a sound's ▶ to play it now (the rest keep waiting).
- Free sound packs is now only in the Library menu, not in the Add menu as well.
- Selected tabs, mode tiles, filter chips and on-state buttons now have the same glossy finish as the main buttons.
- Stop the bottom playback and audio controls from repeatedly shifting sideways when the output meter runs out of room.
- Make Reset bigger and easier to click in Live controls on the Sounds, Radio and Apps tabs.

## 2.6.3 — 2026-10-17

- New installs start with Textured themes (each theme's own pattern on the panels). If
  you already picked Plain or Textured, that stays.
- Opening Onion Board at the wrong moment of an update could make the update fail and
  leave the app unable to start until it was reinstalled. The installer now closes any
  copy opened meanwhile before it finishes, and the app steps aside while it installs.

## 2.6.2 — 2026-10-17

- Opening Onion Board while an update is installing no longer shows "Unhandled exception
  in script" error boxes: it steps aside, and the installer opens it once it's done.
- The window no longer freezes for seconds right after installing, when a tab is first
  opened while the radio player is getting ready in the background.

## 2.6.1 — 2026-10-17

- A number you type into a box (speed, pitch, effects, volume, trim) now counts after a
  short pause or a click anywhere else, without pressing Enter. Enter in the Live controls
  no longer presses Reset all, which put a typed speed straight back to 1x.
- Clicking Restart to update no longer freezes the window while Windows checks the
  downloaded installer, and an update closing the app is no longer counted as a crash.
- Sound modes (Game, Voice chat, Advanced) no longer change how sounds play in your
  own headphones: only what others get is shaped, and *Hear what they hear* still
  lets you listen to it.
- Picking a voice while no mic is open now says why nothing changes ("No mic is open")
  on the Voice tab, instead of doing nothing.
- Saved clips whose sound file was deleted outside Onion Board no longer stay in the
  list as clips that can't play.

## 2.6.0 — 2026-10-17

- A link that failed after a few added ones no longer turns a roomy window into the
  mini player (taking the search box with it, so later links did nothing): the download
  list folds to fit instead.
- A search that fails because the site is down no longer tells you to close and reopen
  Onion Board: waiting is what fixes it.
- Chat's `!random <category>` under a category limit now says the category is outside
  chat's one (it said "no such category" for a real one) and gives the bot a line to post.
- Screen readers: the Live controls button is called "Live controls" (not "1x"), the Up
  next chip says what it shows ("Up next 3"), and a limited-edition theme card says until when.
- Voice backgrounds now use bundled CC0 audio clips for rain, wind, engine, crowd,
  spaceship and fire, with a new rain-on-a-window option. They work offline; previews
  and live playback use the same clips, and source credits ship with the app.
- Quick setup: pressing X or Esc while Bun is putting your sounds into your mic now says "Bun's almost done, one moment" instead of doing nothing.
- **You can see your mic being set up now.** On the Setup tab, the boxes in the mic card
  fold away and back out instead of blinking out, and when your sounds land in your mic
  its box lights up green with a tick. Off when Windows' animation effects are off.
- Autotune voice: a hard T-Pain style snap. It now sticks to the notes of one key and jumps cleanly between them (no flicker), with a brighter, doubled sound.
- Voice bar: each chip (voice changer, AI voice, computer voice, language) has its own ✕, so you can turn one off without stopping them all.
- Voice backgrounds have softer rain and fire, smoother wind and hums, and voiced crowd
  babble. The talk gate starts quietly, and typed speech includes edited backgrounds
  and sounds picked from the board.
- **"Hear what they hear" no longer squeals on speakers.** With speakers as your headphones
  output, the mic hears them, and loud enough the sound loops into a squeal. The app now
  hears that squeal starting and switches the playback off by itself (and says why), and
  turning it on with speakers warns you first. Talking, singing and shouting are left alone.
- The Halloween theme's cobweb texture is redrawn: cobwebs now cover the whole card instead of a grid of tiny stamped webs.
- The loading screen's card has a soft glow in its theme's colours instead of one flat
  colour (High Contrast stays flat), and shows the version small in its top-right corner.
- **Bun got a little cuter.** A fluffy poof on his chest, a belly button, longer feet with
  neater toe beans that fit inside them, and longer, floppier ears. His ears lost the grey
  strip and the odd pale corner at the bend, and the pad prints on his waving paw are the
  right way up now.
- Rare loading screens now name their tier: Uncommon (Golden Bun), Rare (Ice Bun),
  Legendary (Galaxy Bun) and Super Rare (Rainbow Bun), with more room under the dots.
- New installs play a sound with one click (Settings > General > Play pads with one click;
  your existing setting is kept).
- The setup steps lead with putting your sounds into your mic: that button glows, the
  virtual cable comes after "or", and installing the cable asks first (it's only for
  people who know they need it).
- Clearer words: the rail's Live button says On, the search button says Search online, the
  ear button says Listen, the Voice tab's Discord tip and the Privacy page are in plainer
  words, and the setup card is shorter.
- Settings > Audio shows the everyday cards; speech servers, buffering and the duplicate mic
  switch are under More audio settings (Show advanced).
- The chain-link mark on a sound kept outside the library shows while you point at it.
- After a few days of heavy use (open 2 hours or more on 3 different days), a slim bar
  asks once, ever, "Enjoying Onion Board?" with Bun holding up a survey: a thumb up or
  down, then a few optional words. It waits for a calm moment (never over a game) and
  only shows while the anonymous usage count is on; the answer goes with a one-off
  random ID, never linked to you.
- Settings > About: a shorter note, said by a new mascot, the Onion Alien, in a speech bubble that types itself out.
- While the Community store's server is having trouble, **Share a sound** and **Share a voice**
  are greyed out and say why, instead of letting you fill in the form and then fail. They come
  back by themselves once the server answers again (Refresh checks).
- When something doesn't work (a search that can't get through, the radio that can't
  connect, the Community store that can't load, a voice that can't switch on), sad Bun
  now says so on a red card with Try again and Report a problem, instead of a line of red
  text. The tutorials do the same instead of vanishing, and carry on after Try again.
- **Bun and Hoot have a personality in every theme.** Click them and they talk in their
  outfit's character: a sea captain in Ocean, a wizard in Midnight, Dracula in Vampire, a
  hacker in Hacker, a little witch in Halloween, and so on (four lines for Bun, three for
  Hoot, in every theme and language).
- Bun no longer sits still on the loading screen: each launch he does one of 13 acts,
  picked at random (headbanging, karaoke, building, batting practice, a party, a nap,
  Robo-Bun booting up, plugging in his headphones, hopping, drumming, an ear wiggle,
  peekaboo, a spin), and waves goodbye as the window comes up. In October he wears a
  witch hat and in December a Santa hat.
- Rare loading screens, with a glowing border and their drop rate: Golden Bun (1/50),
  Ice Bun (1/500), Galaxy Bun (1/5000) and Rainbow Bun (1/50000).
- A game that runs as admin keeps its keys from other programs, so hotkeys went quiet
  in it with no word why. Now the board tells you when such a game is in front, with a
  *Restart as admin* button.
- New limited-edition Halloween theme, the first card in Settings > Appearance > Themes:
  pumpkin orange and witch purple with cobwebs, a jack-o'-lantern logo, and Bun and Hoot
  in witch's hats. Use it by 31 October and it's yours to keep; after that it's gone.
- Settings > Appearance has two tabs instead of six: Themes (with Textured or Plain on
  top) and Look (highlight colour, size, live tabs and background together).
- Finish in the setup guide now means done: it no longer opens again on the next start when
  sending wasn't set up (the Setup tab's Step-by-step guide still opens it).
- Bun shows his buttons, Back to the board among them, for a few seconds as he appears, so the
  way back is seen even before you hover over him.
- Importing from another soundboard puts its sounds straight into their own category (for example "Resanance"), shown from the first sound on, instead of All.
- No more "Keep them?" box after an import you already said yes to.
- **When the Community store is down, it says so.** Instead of "Couldn't open the store",
  you get "Sorry, the store's down" with a sad Bun kicking at the ground, and Try again.
- Control API: `/api/alerts?type=raid` alone now lists that type's rules instead of an
  error, and `/api/event?test=1` without a type sends a test follow.
- The mini player's red "All" pill is read out as "Stop all" by screen readers.
- **Bun DJs in Live controls.** While Live controls is open, Bun sits left of its title tapping
  sound pads and scratching a record, in every tab that has it (Sounds, Radio, Apps).
- Dropdown lists and button menus now open with a small gap from their button instead of
  stuck to it (the Store's category list, the Radio filters, Settings and the rest).
- Radio map: the most played stations stand out now, as bigger glowing dots (the more
  plays today, the bigger), and the rest are small plain dots. Stations crowded on one
  spot (a whole city's) spread out round it at every zoom, so each can be seen and clicked.

## 2.5.0 — 2026-10-17

- **A maximised window stays maximised:** close or restart Onion Board while it's maximised and it
  opens maximised again, and bringing it back from the taskbar or the tray no longer turns it
  into a normal-sized window.
- Speak another language: no more empty box under Install speech recognition before it's installed.
- The voice bar has an Effects button: a small pop-up where you add rain, wind, a crowd,
  a fire, an engine or spaceship hum, a sound from your board, or an extra Robot, Radio,
  Echo or Reverb on top of any voice, each with one slider and a ✕. They stay when you
  pick another voice. Edit voice is still there for every setting ("Advanced: Edit voice").
- The anonymous usage count (if it's on) now also says, by name only, whether the
  newest features get used: the voice changer's Background, hiding a category from All,
  setup share codes, the phone remote and control API, and its chat commands and alerts.
  SECURITY.md lists each one.
- Voice tab: the tabs at the top are bigger with a line under them, and My setups sits in its own slim box with smaller buttons, so the tabs, your setups and the card below no longer run together.
- Pressing "Not now" on two tabs' how-tos within a minute switches the rest off, so
  clicking through the tabs isn't held up on every one. Settings → General turns them
  back on.
- Switching the Community tab off in Settings while its list was loading made the tab
  say "Couldn't open the store" instead of "The store is off". It says it's off now, and
  the list comes back as soon as the tab is switched on again.
- The Community tab refuses shared sounds, links and voices whose name or tags hold a link
  or a blocked word, and blocked words can't sneak past with accents, spaces, dots,
  look-alike numbers (b4d) or stretched letters. A refused share now says why.
- A category can be left out of All: right-click its tab, Advanced, Hide its sounds from All.
  Handy for a big imported pack you only want on its own tab. Advanced also holds the
  random-sound hotkey and Export as a sound pack now.
- The voice changer has a Background: rain, wind, an engine, a crowd, a spaceship hum or a
  crackling fire behind your voice, each with its own level, or up to four sounds from
  your board. Every one has a "Speed and pitch" button for its speed, pitch, bass, muffle
  and reverb, with quick picks like "Next room" and "Through a wall". It plays only while
  you talk unless you switch that off.
- "Make it yours" is now called "Edit voice".
- Onion Board now opens in front of your other windows when you start it (for example from
  the installer's last page), instead of behind your browser. A start with Windows still
  stays quiet in the tray.
- The control API (Settings → Remote) takes chat commands: a bot like Streamer.bot sends
  each chat line to `/api/chat` and viewers can use `!sound`, `!sounds`, `!random`, `!say`,
  `!voice` and `!stop`, with cooldowns, who may use each, a category chat is kept to,
  blocked words, and a reply for the bot to post back. It can read chat aloud too.
- Alerts and donations: `/api/event` plays a sound, a random one from a category, says a
  thank-you or puts on a voice for a while for follows, subs, bits, raids, tips, channel
  points or TikTok gifts, set per type and amount with `/api/alerts`. It also reads what
  Twitch, StreamElements, Streamlabs and Ko-fi send. `/api/feed` lists what they did.
- The control API reaches the newer parts of the app: the Apps tab, My setups, a random
  voice (or any voice for some seconds), all hotkeys off / on, *Mute my mic while a sound
  plays*, and sound search. A POST can send its values as JSON or a form.
- Share codes work for My setups now: right-click a setup → Copy share code, and Import a
  code (next to Save what's on) adds it, AI voice and language included. AI voices get codes
  too, from the Share a voice window. Old voice codes still import.
- A setup someone else made no longer turns on a different voice of yours that happens to
  have the same name.
- Bun wears his theme's look everywhere now: his paw holding a skit's prop or the
  download bar's quill, and his ears popping out of the build cloud, are his theme's
  fur instead of plain white. Pictures of him (help cards, the theme switch, message
  boxes, the Appearance cards) and the small Bun in the setup guide no longer cut off
  the tip of an upright ear or the sides of a wide collar.
- Hoot the owl (in the Triggers tab) dresses for every theme like Bun does: his own
  feather colour, eye colour, belly marks, ear tufts and beak. Dark keeps plain teal Hoot.
- A bug no longer pops up an "Onion Board hit a problem" window while you use the app. It's saved on your PC and, with the usage count on, counted a minute later so it gets fixed. Settings → About shows *See report* if you want to send one yourself.
- Tor: switching on Offline mode after Tor couldn't connect now says Tor stays off in
  Offline mode, instead of still showing the old connection error.
- Fixed a short freeze the quick-setup guide could cause on its last step, where it keeps
  checking Discord's settings.
- Setting up the mic effect no longer says it can't find your mic after you plug it into
  another USB port (Windows renames it "2- …" there).
- The anonymous usage count (if it's on) now also says, by name only, which newer features
  get used: Live controls setups, list view, voice keys, auto push-to-talk, the voice
  leveler, Up next, Bun's games, the Store's order and categories. SECURITY.md lists each one.
- The Free sounds tab is now called Community, with a new look: it sits in the middle
  of the window, Bun greets you in his headphones at the top (he cheers when you add a
  sound and looks sad when nothing turns up), and every sound and voice has a coloured
  picture of what it is. A sound's bars bounce on its picture while it plays, and the
  chips have pictures too.
- A working mic no longer looks broken before your sounds are in it. The Setup tab
  says "Your mic works" in green, with its level, above "Your sounds aren't in your mic
  yet", and the sidebar and the mic card say "1 step left" instead of "Not set up". The
  quick-setup guide says the same on its mic and send steps.
- "What others hear" gets a "Voice only" tag until your sounds are in your mic, and its
  meter no longer moves with sounds nobody else hears yet.
- The guide's last step no longer shows an empty box when your sounds aren't in your
  mic yet, when only you hear them, or when the virtual cable is missing.
- Picking a setup with an AI voice in Live controls asks first, since it takes a while.
  A sound made in the AI voice says when it's ready to play.
- Updating no longer opens the setup guide again for people who already used an earlier
  version (it did when the guide was finished before sounds reached voice chat). The
  first thing after an update is now What's new.
- What's new covers this version again (it had stopped at 1.9.20), in your language, and
  an update over several versions shows only the newest few changes instead of a long list.
- 13 new voice changer voices: Drunk, Choir, Goblin, Fairy, Zombie, Evil twin, Giant,
  Mecha, Ship computer, Pilot, Drive-thru speaker, Old film and Cathedral, each with its
  own picture.
- A Random voice card after the last voice: it turns on one of the voices shown, picked
  at random (from your favorites when Favorites is picked). Settings → Hotkeys has a
  Random voice key for it.
- Hear it for the voice changer: a short line said in the voice, in your headphones
  only, from the bar under the voices or a voice's right-click menu.
- Wobble's Vibrato now reaches 40 ms, enough for a slow sway of a semitone or two.
- Bun and Hoot have been redrawn in a softer storybook style: rounder faces, sparkly eyes,
  little brows, head tilts, Bun's floppy ear and tail, stubby arms that clasp when he hopes
  and fold when he's cross, and Hoot's open beak when he cheers. Every outfit, act and
  Easter egg is still there.
- Bun looks different in every theme: his fur, ears, tail (fluffy, long, a tuft, a heart),
  eye colour, markings (an eye patch, spots, a mask), nose and ear colours, and paw prints
  under his feet. Dark keeps plain Bun.
- Each theme card in Settings shows Bun dressed for that theme, and he waves when you
  point at it.
- Clearer icons: a solid speaker, mic, headphones, eye and gear, and rounder sound
  bars.
- Live controls on the Sounds, Radio and Apps tabs has **My setups**: put one of the voice
  setups you saved on the Voice tab on everything playing. Its voice changer voice is on
  at once. With an AI voice, a sound is made in that voice first (it pauses and carries
  on from the same spot) and the radio or a program waits while the AI voice gets ready,
  with a progress bar and Cancel.
- Store → Voices: share your voice changer voices, AI voices and setups with everyone, and
  get theirs. Hear any of them first, vote on them, report bad ones. Only settings are
  shared, never your voice. Right-click one of your voices or setups → Share to the store.
- Cards or a list, everywhere: two little icons at the top right of the Sounds, Apps and
  Voice tabs switch between them, the one in use lit. Apps' list puts each program on one
  line (level, Send, Record, volume); Voice's list shows a small picture beside each name,
  more voices on the screen. Each tab remembers its choice. On Sounds the switch replaces
  the Cards / List items in the order menu.
- The AI voices have pictures now, drawn like the voice changer's.
- Live controls (the speed, pitch and effects box on Sounds, Radio and Apps) is a pop-up
  again: it opens right above its button and a click anywhere outside closes it, instead
  of a separate window you had to drag and close. The sound modes' *What do these do?*
  and a sound's source details work the same way.
- The sound store checks every shared file from end to end, not just its first bytes: a
  program, script or web page dressed up as an MP3 or WAV is refused, and sound names lose
  markup and the hidden characters that can make "x.exe" look like "x.mp3". The app also
  keeps a store download only when it really starts like the sound it says it is.
- Your voice setups can be renamed to anything you like: right-click one under My setups
  and pick Rename.
- Six new AI voices: Atlas (a deep storyteller), Sarge (a barking drill sergeant), Nana (an
  older woman), Zoe (a young woman), Onyx (a very low woman's voice) and Bean (a little kid).
  They need no new download.
- Muted for over a minute: the Live switch gets a yellow ring (and, with the side bar open, shows how long it's been muted), so a forgotten mute isn't mistaken for a broken app.
- Saving a sound with a voice (or any slow effect) shows how far it is: a progress bar and
  time left in the Edit window, which you can now close while it carries on, and a bar
  with a percentage on the pad. An ✕ on either stops it and the sound keeps its old
  effects. Pressing the pad meanwhile says why it can't play yet. The render now runs
  outside the app, so long songs no longer make the app lag or the audio stutter.
- Bun's Easter egg game: Pong's paddle now follows the mouse even when it leaves the court (it no longer sticks), and holding an arrow key glides it smoothly instead of needing fast taps.
- Bun now picks a game at random when he challenges you: Pong, quick draw, rock paper scissors or tic-tac-toe, each with its own sounds in your theme's style. Another game at the end switches to a different one.
- The Community tab's stop button is easy to see in every theme now (it was black on a
  near-black row in Amber Terminal and other dark themes). Record buttons keep their red
  when switched on in Hacker and other green or red themes, Setup's "Straight into my mic"
  icon shows on its filled button, and a few icons on buttons in Barbie, Flashbang and
  Retro 98 are darker so they read.
- Switching the theme, its texture or your highlight colour blends now instead of flashing:
  the dimming and Bun fade in over a tenth of a second (they used to appear in one frame),
  and the old look fades a little more gently into the new one.
- Radio: the first station you play asks once who should hear it (just you, or you
  and others), and the app remembers. The Send button now says "Send to others" and is
  outlined in your theme colour while only you hear the radio, and the line under the
  list has a "Send to others" link right where you're looking.
- Hoot moves like Bun now: his ear tufts and wings trail behind his hops and wobble back,
  a landing squashes him a little, and his acts ease in and out instead of snapping (waking
  up when the mouse comes near, a click cutting a beg short). His dance bob no longer jumps
  at the end of each beat and lands right on the hit.

## 2.4.0 — 2026-10-17

- Free sounds: switching it off in Settings > Privacy & security while its list was still
  loading now says *The store is off* with a way to Settings, instead of
  *Couldn't open the store*.
- Fixed an error that could pop up when an Undo card closed after the page it belonged to
  was already gone.
- The first-run tour is one card now, and it can't be clicked away by accident: clicks
  around it do nothing until the search step, which has a Not now button. Add a sound
  and it says well done.
- Radio, Apps, Triggers, Voice and Store each show a quick how-to the first time you
  open them: do the thing (play a station, pick a voice…) or press Not now. Turn them
  off in Settings > General > Show tutorials.
- Up next is now one chip with how many sounds wait. Click it for the whole list: every
  name in full, a ✕ on each (even the 10th of 13, which you couldn't reach before) and
  Clear for all of them.
- Sounds can be said in a voice: right-click a pad → Effects → *Voice* opens picture cards
  of every voice changer voice, the AI voices and your setups (Favorites and your own
  first). A voice changer voice and an AI voice can go on together. It's laid on once
  and kept; the original file is never changed.
- Voice tab → *My setups*: save the voice changer voice, AI voice and language you have
  on as one named setup, turn it all on again with one click, or put it on sounds.
- Spamming Play and Add on lots of search results works: up to 30 Adds wait their turn
  (it was 3), and a Play or Add clicked on a song that's still downloading isn't lost
  when you click another song or type a new search. That used to blank the download
  bar while the song kept downloading.
- Bun has a little skit for every theme, played now and then while he's idle (on an
  empty board, in Bun mode): in Blood Moon he grabs the moon out of the sky, takes a
  bite and finds it's cheese; in Retro 98 his shades drop onto his face; in Brainrot his
  propeller lifts him off the ground; and so on. Themes without an outfit juggle.
- Sound store: Myinstants' sounds are in the store's list now, with thumbs up and down like
  the rest (they play and download from Myinstants). Every sound has a category to pick,
  and Top, New and Trending are buttons on the card instead of a menu.
- The Store tab is now called Free sounds, so nobody mistakes it for a shop: every sound
  in it is free.
- Stream Deck and other control-API presses right after the app starts are answered at
  once, not after a few seconds or with "the app is busy": the update check and the
  start-up work behind the loading screen no longer hold them up.
- Bun mode's Bun dances to what's playing: on the beat, and in the song's style. He
  headbangs to rock and metal, hops side to side to electronic music, nods along to
  hip-hop, sways with his eyes shut to something calm and talks along when someone's
  speaking. His notes come out on the beat and grow and shrink with him, and he gets
  bored, then sad, when nothing has played for a while.
- Sound store: the share window, the README and the website now say how to get a sound
  taken down: email onionboard.contact@proton.me.
- Hotkeys no longer take the key away from your game: press F1 (or W) in a game and the
  game still gets it while your sound plays. Settings → Hotkeys → *Keys in games* turns
  it off if you'd rather only Onion Board got the key. The overlay's number keys are
  still kept from the game while it's open.
- Settings: every drop-down now has a name a screen reader says (Audio buffering, your mic
  and headphones, Send my sounds to, download and video quality, radio stations, and the
  overlay's), instead of a bare "combo box".
- The Chat tab is gone. Chat was switched off for everyone on 2026-10-17, and the tab is
  now removed from the app. Settings saved with it open just fine.

## 2.3.1 — 2026-10-17

- Chat: with nobody talking, the Chat tab no longer asks the server again and again
  without a pause; it waits for news and asks at most about once a second.
- Chat and the sound store: reports now count once per internet address, so one person
  can't mute someone or take a sound off the store with made-up installs. Mutes and bans
  cover the address too, and reports and votes have their own limits.
- Search results and the store: a title with HTML in it shows as plain text in its tooltip.
- Settings: with the Sounds or Radio tab underneath, pressing Space on a box you clicked now
  ticks it, instead of playing or pausing the sound.

## 2.3.0 — 2026-10-16

- Pong with Bun opens again in the installed app: it stopped with a missing-module error.
- Renaming a category or subcategory to a name that's cut back to the one it already has
  now says names can be up to 30 characters, instead of doing nothing.
- New Chat tab: one anonymous, text-only room for everyone using Onion Board. It is off until
  you add it (+ More tabs, or Settings > Tabs) and shows its rules the first time you open it.
  You get a made-up name like Cute Onion or Red Car, new every time you open the app, links
  are blocked, and you can mute a name or report a message (enough reports mute someone for an hour). It has its own switch in
  Settings > Privacy & security.
- New Store tab: free CC0 sounds anyone can use. Hear one first, add it to your Sounds in
  one click, and give it a thumbs up or down so the best ones come first. Share your own
  there too, as a file or as a link to a video (only the link is shared: right-click a
  sound you downloaded and pick *Share to the store*). Shared sounds show up once they've
  been checked, and you can report one that breaks the rules. The store has its own
  switch in Settings > Privacy & security, and you can hide the tab like the others.
- **Trending on Myinstants**: the Search button's menu now has a line that shows the meme
  sounds people play most on Myinstants right now (the ones for your country). Play one
  once or add it as a pad, like any search result; no words to type.
- A new install's board no longer stays empty: if you skip the first-run tour (or leave it)
  without adding anything, 25 short starter sounds (air horn, vine boom, bruh, rimshot…)
  are added for you, in a tab of their own called Starter. They come with the app (under
  1 MB, no download), and you can delete or rename them like any sound. Add a song during
  the tour and they aren't added.
- Every voice on the Voice tab can have its own hotkey: right-click its card and pick
  *Set a hotkey…*. The key turns the voice changer on with that voice, so you can swap
  between voices in a call without opening the app.
- The tray icon has a *Voice changer* menu: turn it on or off, or pick one of your
  starred and saved voices.
- Closing Onion Board now puts Discord's noise suppression, echo cancellation and
  automatic volume back the way you talk, so your plain voice sounds right without
  the board. If Discord is still open, a notification says so and it's done the
  moment Discord closes. "Put Discord back for talking on close" switches it off.
- New free pack in *Free sound packs*: the General sound pack, 483 sounds in 20 categories
  (memes, comedy, game show, crowds, animals, video game, combat, sci-fi, magic, horror,
  nature and more). All CC0.
- Bun moves more smoothly and feels more alive: twice the frame rate, ears that trail
  behind his hops and wobble as they settle, a squash on every landing, and quicker,
  more natural blinks (now and then a double blink).
- Your voice now stays at one volume while you talk, loud or quiet, so friends don't
  have to keep turning you up and down with voice chat's own automatic volume off.
  Settings has a "Keep my voice at one volume" box to switch it off.

## 2.2.2 — 2026-10-16

- AI voices: a voice card only lights up while the AI voice is on, like the Voice changer
  cards, instead of the saved voice looking switched on when it was off.
- Fixed a short freeze while the mic effect is on: re-checking the mic effect's state no
  longer starts a new thread each time (the window waited for Windows to start it).
- The FFmpeg check no longer fails with an error when Windows can't look at winget's
  FFmpeg shortcut; it carries on looking elsewhere.
- Settings > Connection: the Get Tor button now sits right next to the Tor choice.
- Mic effect set-up no longer says your mic isn't plugged in while the meter shows it
  working: it now finds the mic the same way the meter does (spacing and case ignored).
- The anonymous usage count (if you left *Count me in* on) now sends the tabs and features
  you used since the last daily count when you close the app, instead of a day later, so
  the last day before someone stops using the app is counted too. Same names as
  before; the close waits 2 s at most.

## 2.2.1 — 2026-10-16

- A link whose download kept getting cut off no longer sits on "Adding… 90%" for good: after
  a minute without new data it stops and says "The download stopped moving. Try again."
- Radio: in a narrow window, where the map is hidden, the search box and the station count no longer tell you to click a dot on the map.
- Mic effect set-up: when your picked mic can't be found, it now says why. If Windows no longer knows that mic, or two mics have names alike, it asks you to pick your mic again in Setup → Devices instead of saying it isn't plugged in.
- Setup's Onion Pocket card says it's waiting for Windows to allow it while Windows asks
  about the firewall, instead of "it couldn't start".
- Making a new category (or subcategory) with a name you already have now says
  "There's already a …" and goes to it, instead of doing nothing you could see.
- Auto push-to-talk presses the game's key as a sound starts. With the board minimised it
  came up to a quarter of a second late, so a game that only sends while the key is held
  cut the start of the sound.
- Fixed a rare freeze while sending sounds straight into your mic: the check for apps recording your mic (every 2 seconds) no longer starts a new thread each time, which could leave the window stuck. MIDI, the Onion Pocket network check and two Settings pages got the same fix.
- Opening Settings no longer reads every language file again each time: the list of languages is read once, so Settings can't stall on a slow disk or while a virus scanner is busy.
- Setup's Devices card now says when your headphones or mic won't open (unplugged), and
  stops once they're back. Before, only a toast said it, and it faded.
- On a slow first start (the virus scan checking a just-installed FFmpeg), the app waits up to a minute for FFmpeg to answer instead of 8 seconds, so it no longer calls a working FFmpeg broken and downloads it again.
- Settings > Updates no longer says "Get FFmpeg" when FFmpeg is installed: the FFmpeg row now checks and shows "Working" even when Updates is opened before Data & quality.
- Adding a free sound pack puts it in one tab named after it ("Streamer") with its
  categories inside, instead of also making an empty tab for each of its categories.
- Opening the Radio tab for the first time no longer freezes the whole window for several
  seconds on a slow or busy disk.
- FFmpeg got by the installer no longer shows as *FFmpeg won't start (some of its files are gone)* the first time the app opens, and the app no longer downloads a second copy of it: on PCs where winget can't make its usual shortcut to FFmpeg, the app now finds it in winget's own folder.
- Importing the same soundboard yourself while the installer's import of it is still
  running no longer adds every sound twice, or asks "Keep your imported sounds?" after
  you already said yes.

## 2.2.0 — 2026-10-15

- Stop all now silences the sound effects too: the echo and reverb no longer keep
  ringing for a second or two after it. A short fade keeps it click-free.
- Stopping the radio is instant: the last fraction of a second it had queued no longer
  plays on after you press Stop.
- Settings: clicking Show advanced / Hide advanced fast no longer makes the page you're on lose and regain its highlight, and the Settings search box no longer opens a right-click menu (Ctrl+C / Ctrl+V still work).
- Voice changer and AI voices: hovering a voice's star shows a circle around it on every card, not just the picked one.
- Clicking a button, dragging a slider or picking from a drop-down no longer leaves a focus ring on it: the ring shows while you hold it (or while its menu is open) and goes when you let go. Switching tabs no longer rings the new page's first button (the info button beside Your mic).
- The Apps tab's empty page now matches the Sounds tab's: the same text size under Bun, and Bun sits in the middle from the start.
- Pressing Re-scan devices while a sound plays no longer stops it: the sound carries on from where it was once the devices are back.
- Updates install themselves when you open Onion Board: the loading screen checks for a new version, shows *Updating to X… 42%* with a bar while it downloads, installs it, and the new version opens saying *Updated to X*. If there's nothing new, or you're offline, the app just opens. Untick *Install updates by themselves* in Settings → Updates to be asked instead.
- Bun and Hoot are bigger on the pages where they wait in the middle: Apps with nothing playing, an empty Sounds tab and while a search loads.
- Opening the *Radio* tab for the first time while a sound plays no longer cuts the
  sound out for a moment: the map's country outlines are made a part at a time, with
  a rest between, instead of all at once.
- Dragging the window's edge is smoother: while it's held, the window only re-measures
  what changed, and measures everything once you let go (up to 44 % less work a step,
  most on the Setup and Voice tabs).
- Count me in now also counts the newest features (voice groups and Favorites, AI voices,
  Free packs, the colour wheel, Show advanced, yt-dlp's buttons, the headset and 0% volume
  warnings), each as a name only. SECURITY.md lists every one.
- Opening *Free sound packs* while a sound plays no longer cuts the sound out for a
  moment: the window fills in a pack (or a sample's tile) at a time, with a rest
  between, instead of building everything at once.
- The app does less work on every event it handles, so dragging the window's edge is a
  little smoother (5-9 % less work a step on most tabs).
- AI voices: clicking a voice turns the AI voice on with it, like the voice changer's voices. No more picking a voice and then pressing Start.
- Settings → Updates → yt-dlp has a *Force update* button: when YouTube or another
  site stops working and no approved yt-dlp fixes it yet, it installs the newest
  yt-dlp right away, after a warning that the app's makers haven't approved it yet.

## 2.1.0 — 2026-10-15

- New installs get a short first-run tour: right after the setup guide, on the empty
  board, Bun points at the search box (type a song, press Enter), then at the first
  result to add it, or at *Add sounds* for your own files when you're offline. Any
  click goes through to what's under it, and it ends for good once you go elsewhere.
- The app looks for a new version every hour instead of every 6, so updates reach you
  sooner (Settings → Updates still turns it off).
- yt-dlp updates (Settings → Updates → *Update now* / *Reinstall*, and the opt-in
  *Update automatically*) now only install a version the app's makers approved,
  checked against yt-dlp's signed release, once it has been out for 3 days, instead
  of whatever is newest on PyPI.
- Speak another language is simpler: pick the language first (Don't translate is the
  first choice, no separate switch), then Said by names the voice others will hear, then
  one button that says what it does (Start speaking Chinese). Computer voice, speed and
  deleting a language moved under More options.
- Voice tab cards no longer get squeezed when the window is narrow (controls shorter than
  they should be, text cut off).
- Settings → Updates now has one *Helper programs* card listing FFmpeg, yt-dlp, the
  JavaScript engine and Tor, each saying how it updates. yt-dlp's *Reset downloader*
  is now called *Reinstall*, like FFmpeg's, and its *Update automatically* box (still
  off by default) sits on its row. Data & quality no longer repeats these.
- FFmpeg and Tor copies the app downloaded now follow app updates: when an update names
  a newer version, the app fetches it (checked against its SHA-256) at the next start.
  Tor waits while Connection is set to Tor.
- AI voices look like the Voice changer now: a picture card per voice under Men, Women,
  In between & fun and Mine, with the same row of buttons to show one group and a star
  for Favorites. The All voices window is gone: Hear it, Make your own voice and
  changing or deleting your own voices sit under the cards.
- The Voice changer's voices are sorted into groups (Funny, Scary, Robots & sci-fi,
  Disguise, Radio & places, Mine), with a row of buttons to show just one group.
- Star a voice in its corner to add it to Favorites, its own button above the voices.
- Settings search lands on the page that really uses the word: "tor" opens Connection,
  not the first page with those letters inside another word.
- Screen readers now name the Sounds page and the Hear what they hear switch, also
  when a narrow window hides the switch's words.
- At 1100 px and other in-between window sizes, controls no longer go missing for no
  reason: the speed and effects button, the radio's volume, Record and map, and the Say
  bar's Stop were hidden when only the levels strip at the bottom needed less room, and
  stayed hidden until the window was made much wider.
- Playing a sound with the Sounds volume at 0% now says that nobody else hears it, with a
  button to set it back to 100% (you still heard it yourself, so it looked like it worked).
- Import a code with nothing pasted now says "There's no code there." instead of quietly
  doing nothing.
- Closing the quick setup guide right after "Play a test sound" no longer shows an
  error report.
- Fixed a rare error report when a right-click menu opened after sounds were removed
  from the board.
- Category, subcategory and sound names now say why when they can't be used as typed:
  an empty box (or only spaces) asks for a name, a name that's too long says how long
  it can be, and a subcategory can't take its own category's name. Tabs and line breaks
  in a typed name become spaces. Renaming a sound to a name another sound has says so.
- Restoring a backup brings back a removed sound that shared its audio with a sound still
  on the board, instead of calling it "already in your library".
- Importing from another soundboard says which category the sounds go in.
- A pasted link through a proxy that doesn't answer now says the proxy couldn't be reached
  and where to change it, instead of "The site is having trouble right now".
- A download cut off part-way says so in plain words instead of the downloader's own text.
- After Offline mode or a site's switch changes in Settings > Privacy & security, the line
  under a pasted link says the new state instead of the old one.
- Win+L and Ctrl+Alt+Del can't be saved as hotkeys any more: Windows keeps them for itself,
  so they never played. Keys other apps use (Ctrl+C, Ctrl+V, Alt+Tab, Alt+F4...) still work,
  with a heads-up that they stop doing their usual job while Onion Board is open.
- A sound, category or other action can't take the Stop everything key any more, so there's
  always a key that stops every sound.
- The remote API's /api/pause on an idle board now answers "not paused" instead of "paused".
- A radio station that plays a few seconds and drops again and again is now given up on
  with a message, instead of being reopened for ever while the tab still says it plays.
- A free pack whose download is a damaged zip is no longer kept: the window says so, and
  the pack's button stays *Add to my board* instead of *Add again*.
- Pressing a free pack's *Add to my board* with Offline mode on now answers with a message.
- After a device re-scan (the Re-scan button, or plugging in new headphones), a headset
  pulled out was never noticed: no warning, and it didn't come back by itself when plugged
  in again. It's watched again after every re-scan.
- Setup tab: a headset that's switched off or unplugged no longer looks broken. A mic
  that sends nothing at all now asks "Is your headset on?", and a picked mic that's
  unplugged asks "Is your headset plugged in?" with no Repair or set-up button. Both go
  away by themselves once it's back.
- The green tick and red cross on the Setup tab's mic card now sit level with their words in every theme's font, with a little space either side (they hung low in the default font).
- Settings > Data & quality: under FFmpeg, the other helper programs now have a row each
  too: yt-dlp (its version, with Update now), the JavaScript engine YouTube downloads use
  (QuickJS from the app, or a faster Deno, Node or Bun if it's on the PC) and, once it's
  here, Tor (its version, with Update Tor).
- Every card in Settings has an icon by its heading now, like Audio recovery (the theme
  groups and FFmpeg too), and a heading that fits stays on one line instead of wrapping
  half-way across the card.
- Settings opens on Audio and lists the everyday pages first (Audio, Appearance, Hotkeys,
  Tabs, General, About). The rest (Overlay, Privacy, Connection, Data, Updates, Add-ons,
  Remote) sit behind a Show advanced switch, which remembers being open and opens by
  itself when a link goes to one of them.
- A hotkey has to be one a keyboard (or a MIDI pad) can really press: text like "Ctrl"
  alone, a key that doesn't exist or the same modifier twice isn't saved any more, and a
  message says why (it used to be saved and shown as working). A bad one in older
  settings or a backup is dropped when it loads.
- A message that changes in place (like a hotkey's) now grows to show all its words
  instead of being cut off.
- Settings opens at once again after you looked at About, Updates, Help or another page
  that shows live info: a fresh copy is now made ahead while the app is idle, instead of
  building Settings again on the next click.
- Muted while your mic is still sent: the sidebar now says "Only your mic" instead of
  "Muted", since others still hear your plain voice. The streamer guide and the remote
  control help say the same.
- "Get Tor" now downloads Tor 15.0.25 (was 15.0.24), the current Tor Expert Bundle.
- A search picture that never ends now stops at its size limit even while the window is
  busy, instead of piling up in memory first.
- Small blank windows no longer flash up for a moment when the app starts: a few labels
  and buttons were shown before they were put in place.
- Settings > Appearance is shorter: the language stays on top and themes, highlight colour, theme style, interface size, live tabs and the playing-sound background are now tabs in one box, and settings search jumps to the right tab.
- Sounds added from your PC are copied into the library by default, so they keep working if the original is moved or deleted (switch it off in Data & quality to link instead).
- Sounds no longer skip now and then while the app tidies up its memory: the tidy-up
  now runs in small, quick steps, and the big one waits until nothing is playing.
- The taskbar, shortcut and exe icon now fill their whole square like other apps' icons, so it no longer looks smaller and slightly low next to them.
- The open sidebar's Live and Stop all buttons now say what they do ("Live" / "Muted", "Stop all") beside their icons, and "Not configured" is its own rounded button inside the card instead of a strip along its bottom edge.
- Fix: with the mic effect on, the board's audio no longer runs four times as often as
  it needs to while the effect hasn't sent your mic yet: it mixed sounds 400 times a
  second instead of 100, and on a slower PC the window stopped answering for a few
  seconds at a time.
- Give Hothead a new fiery icon and add artwork for Singing monk, Dalek, Haunted radio and Underwater.
- Double-clicking a pad plays it wherever the two clicks land on it, and a quick second click no longer starts a drag or shows the "pads are sorted" note.
- Languages: speak in your own language, not just English. The live voice listens in the app's language (or the one you type under More options), turns it into English with its speech recognition, then into the language you picked; speaking the picked language itself just says it. Anyone not speaking English gets the accurate recognition model by default.
- New translation add-ons: Ukrainian and Filipino.
- Languages: a progress bar while the speech model downloads the first time.
- Opening *Free sound packs* while a sound plays no longer makes the sound skip: the
  window no longer rebuilds its pack cards when the online list arrives, and each card
  is built in about 2 ms instead of 30.
- Zooming the radio map no longer makes a playing sound skip: it draws only the town
  names that fit (it drew every town in view, hundreds over Europe, in one go).
- A song played from a search and then added to your sounds is one song now: playing
  its pad starts it again from the top instead of a second copy playing over the first,
  and Play on a search result already on your board plays its pad.
- No more stray outlined square where the two scroll bars meet on a narrow Setup page.
- After Stop on the Voice tab, the bar under the voices that names the picked voice goes away too, instead of looking as if the voice were still on.
- Developers: `scripts/merge_pr.sh` merges again by itself when another merge lands at the same
  moment.
- Developers: the translation files now merge by text, so two changes that both add
  texts no longer conflict.
- Setup: the "other ways to send your sounds" tiles under Your mic stack one under the
  other when the window is narrow, instead of cutting off "Another device" and its button.
- Voice changer: a new **Singing monk** voice and effect. A monk sings what you say: every
  syllable becomes one of his sung notes, following the ups and downs of your voice on a
  five-note scale around his own low note. His voice is measured off the Delay Lama synth,
  vowel by vowel. *Follow my tune* and *Words* (how much of your consonants still comes
  through) are on its card.
- The Voice tab's **Stop** is a big red button with its word now, instead of a small square.
- Settings: the back arrow and cog beside the "Settings" heading line up with the word in every theme, also in the ones with their own font (Hacker, Amber Terminal, Retro 98, Comic Sans), where they sat up to 2 px low.
- Setup → Devices: *Also send to* is now *Also play on*, and its tip says mics aren't
  listed there (it read like "send into another mic").
- Your mic card: a **Change mic** button next to Reinstall and Remove opens the mic list;
  your sounds follow the mic you pick.
- Fixed a crash in the Apps tab when closing a card's Clip editor (most often from its
  big view): one small error while laying the cards out could break a card for good.
- Triggers: the + after Play can show your sounds by category, so you find the one you
  want faster (with an Onion Watch that has the new sound menu).
- Record a sound: a new **Both** choice records your voice and what's playing at once,
  as one sound. What's playing goes down while you talk, so your voice stays on top.
- The list view has its own Row size (Small, Medium or Large) where the slider sits. "Pad size" is now "Card size", and it only shows with the cards it sizes.
- Your voice no longer gets buried under your sounds: while you talk, your sounds now go
  down to half (Setup → Who's listening, "While I talk, lower my sounds"). It's switched
  on for everyone who had it off; pick Off there to turn it back off.
- A category's right-click menu is shorter: *Play them all* (in order / shuffled) and
  *Show this when a program is in front* are gone. Program rules you already made still
  work, and Settings → General still lists them to remove.
- Free sound packs: every pack's sounds to try now show up the first time you open the
  window. Some packs (often Halloween and GM) used to stay empty until you reopened it.
- The Radio tab no longer has a *Last 15s* button: use *Record* to save the radio as a sound.
- Apps tab: the Clip editor opens from a scissors button beside the eye on each card, a
  full-size button instead of the small link at the bottom. The eye's window picture is
  bigger too (up to 320 px tall).
- A web address whose name leads to your own PC or home network (a link, or a redirect
  to one) is now refused for pictures, packs, previews and updates too, the same way
  downloads already refused it.
- Hoot's speech bubble in the Triggers tab now breaks a long translation onto two lines
  instead of saying nothing.
- Bun's animations are livelier. When a cable install fails, his hammer snaps and his
  ears droop with a sigh. He dives into a dust cloud for his tools instead of getting cut
  off at the edge, and builds a little speaker as he hammers. Robo-Bun's gadget is easy to
  see, with sparks and glowing ears. A click gets a proper happy hop, music notes show up
  on dark themes, and now and then he yawns, looks round or taps his foot.
- Bun has new outfits in ten themes: a flower crown (Lilac), a frog hat (Swamp), a
  backwards racing cap (Carbon), an amber eye shade and a pencil (Amber Terminal), a red
  moon and little horns (Blood Moon), a hazmat hood and radiation badge (Toxic), a
  turtleneck and reading glasses (Slate), a mint sprig (Mint), a captain's hat (Ocean)
  and dizzy spiral eyes (Flashbang). Hacker's hood no longer vanishes on its dark
  background.
- Bun takes his glasses off when he naps, and his smug brows and tears no longer show
  through sunglasses. Hoot the owl's bands and hood strings fit him properly.
- Bun mode: the mini player has a new Bun button that turns the window into a small Bun
  floating over your screen. He sings along while a sound plays, builds while a download
  runs, and says notices and errors in a bubble. Hover for play, stop, Live and mic;
  scroll to resize him. Click him to get the mini player back, or grow him past his
  biggest for the full board. Your hotkeys keep working the whole time.
- *Free sound packs* lists the everyday packs first (Streamer, Esports, Podcast), then
  Halloween, then the GM starter pack.
- Pong with Bun has sounds now: crisp hits that climb a note with every hit of a rally,
  a chime every 5 hits, a little ting for a hit off the tip of your paddle, and cheers
  or a sad trombone at the end. Each theme has its own style of sound. They play in your
  headphones only, and the speaker button beside Close mutes them.
- Changing theme: Bun and the dimmed picture in the middle of the window now already
  show the theme you're switching to (its colours, headphones and outfit), not the one
  you're leaving.
- YouTube downloads keep all their formats on PCs without Deno or Node: the app now ships
  a small JavaScript engine (QuickJS) for yt-dlp to solve YouTube's player challenge, and
  uses Deno, Node or Bun instead when one is installed.
- Two new free sound packs in *Free sound packs*: a Halloween pack (49 sounds: screams,
  evil laughs, monsters, jump scares, a haunted house and spooky music) and a streamer pack
  (57 sounds: stream music, follower and sub alerts, hype, fails and chat reactions).
- Yes/no and warning boxes use the app's own icons in your theme's colours instead of
  Windows' old ? and ! pictures, with the question as a bold heading and more room.
  Boxes that ask for a name are wider, with OK as the main button.
- Recently deleted, the program picker and Custom destination modes show a proper
  empty state in the middle of the list, not a grey line in its corner. Custom
  destination modes is laid out as a card with a heading; the long explanation is
  behind its ⓘ.
- The crash box is shorter: a heading with an icon, and the report itself folded
  away behind Show the report.
- Restore points, Reset and What's new put their main button first, like every
  other box. The chat and streamer guides start their steps right under the intro.
- The download banner always shows Bun on the left, writing the download down, with the
  sound's picture beside him. In a queue he stays: he ties up the scroll, then unrolls it
  for the next one, and the banner no longer jumps between picks (the title, the overall
  bar and Stop all keep their places).
- A link that fails to download because the downloader (yt-dlp) is out of date now shows
  an *Update downloader* button: one click gets the newest and tries the link again.
- Updating the downloader never breaks it any more: it skips a yt-dlp that needs a newer
  Python than the app has, and a downloaded copy that won't start is dropped for the
  built-in one (and never fetched again).
- Windows switching your default output, the setup guide's cable step and closing the
  setup guide no longer freeze the window while a stuck device is being recovered.
- Voice changer: four new effects, **Harmony** (two more voices at intervals from yours),
  **Ring modulator** (the Dalek), **Flanger** (jet-plane swirl to under water) and
  **Wobble** (vibrato and tremolo), and three new voices built on them and the rest:
  Dalek, Haunted radio and Underwater.
- Dark and Light themes are now neutral grey: a near-black window with charcoal cards
  and hairline borders, and an off-white window with pure white cards. The blue tint and
  the faint satin texture are gone.
- Textured (Settings → Appearance) now also gives every theme a soft glow of its two
  accent colours behind the cards, and the theme cards in Settings preview each theme's
  pattern and glow. Plain is a flat window with flat cards.
- Slate, Forest and Lilac got new patterns (pinstripes, crosshatch, frost): the old
  brushed-metal and satin ones were too faint to see.
- Voice changer: Reverb is a real room now: a Pre-delay slider keeps your voice clear in
  front of it, and early reflections (the first bounces off the nearest walls) arrive
  before the tail. Saved voices keep their tail: Size, Brightness and Mix mean what
  they did.
- About 150 tooltips that only repeated what the button already shows are gone: the
  play, stop and skip buttons, close and back arrows, the voice tiles, every effect's
  switch, fold arrow and Reset, the hotkey clear buttons, the EQ bands and the mascots.
  Screen readers still hear each one's name.
- Free sound packs: the window is bigger, and every pack shows six of its sounds with
  their pictures. Click one to hear it before adding the pack (only you hear it, in your
  headphones).
- Bringing your sounds over from Soundpad, Resanance, Soundux or EXP Soundboard (from the
  menu, a drop, or the installer's box at start-up) no longer freezes the window while the
  board is read and its sound files checked, even ones on a network drive that's offline.
- A sound added or brought back while the board was still loading could be loaded twice at once
  and saved garbled, so it played wrong every time after. Each load now has its own file.
- Free sound packs are stored once, not twice: an added pack's download becomes the
  kept copy (about 60 MB back for the three built-in packs), and copies an older version
  doubled up are cleaned up on start. Removing a pack now leaves nothing behind.
- Switching YouTube off in Privacy & security now also stops YouTube pictures: a sound's picture from a YouTube link and the thumbnails in web search results go under the switch of the site they come from, not under *Other pasted links*.
- Network activity says why a sound's picture from a link went online.
- Onion Pocket: a request read off the Wi-Fi can no longer be sent again after Onion Board or its phone server restarts.
- The anonymous usage count no longer loses a tab opened or a sound downloaded while a count is being sent.
- Settings → Remote: turning it on, a new port and *New key* are saved in the background, and *New key made* shows only once the key is really saved (a failed save says so instead).
- Importing from Resanance: a damaged or crafted board file with documents nested very
  deep is skipped as unreadable instead of crashing the app.
- Export: a sound whose file can't be read (another program has it open, or it was
  moved mid-export) is left out instead of failing the whole backup, and the app says
  how many were left out.
- Straight into my mic: one bad block of your mic no longer stops your mic going in for
  good. It's skipped, the error shows like any other audio error, and the rest goes on.
- The stream output does no work while nothing plays, like your send device and
  headphones already did.
- The voice changer no longer ends up running at your mic's old sample rate (the wrong
  pitch) when you change an effect just as the mic changes rate.
- Search result pictures now give up after 15 seconds of no data and stop at 5 MB, and
  are decoded in the background, so a huge or endless picture can't eat memory or freeze
  the window.
- A translation model download now stops at about one and a half times the model's size
  (300 MB if no size is listed), so a broken or bad mirror can't fill your disk. Every
  download (FFmpeg, Tor, Python, updates, translation) now shares one capped, checked copy.
- With a direct connection, a site or radio station whose name answers with a public
  address first and your router's address a moment later can no longer reach your home
  network: the name is looked up once, checked, and the connection goes to the address
  that was checked.
- A background job that fails (setting up the mic effect, removing the virtual cable, an export, an update check…) now always says so and frees its button, instead of leaving it busy until the app restarts.
- A sound removed just before the app crashed or the PC lost power is no longer lost:
  on the next start it's in Recently deleted, with its name, hotkey and effects.
- Changing the audio buffering, the stream output (Also send to) or a device in the
  setup guide no longer freezes the window while a stuck device is being recovered.
- Importing a backup or sound pack, dropping a zip, and *Reset to how it came* no longer
  freeze the window while a big archive (or one on OneDrive) is read.
- Network activity's Totals window and its "Keep a history" switch no longer freeze the
  app while a big saved history is read: the file is read and written in the background.
- A website can no longer make Onion Board reach into your PC or home network: a
  redirect, or a link's preview picture, pointing at 127.0.0.1, 192.168.x or a .lan
  name is refused (custom voice servers on your own network still work).
- Settings, the bin, saved voices and restore points are now flushed to the disk before
  they replace the old file, so a power cut can no longer leave them empty.
- Removing many sounds (a whole sound pack) no longer freezes the window when the Undo bar goes: they go into Recently deleted in the background, with one save of its list.
- Searches and downloads no longer wait 30 seconds each when the background download helper can't start: the app notices at once and does them itself.
- Straight into the mic: once the mic effect stopped sending its clean mic, mic check, voice effects and recordings could play your voice at the wrong pitch until the mic was reopened. The mic goes back to its own rate now.
- Voice changer: the Distortion effect runs at four times the rate, so a hard crunch is
  harmonics of your voice instead of aliasing fizz; the Compressor reads your level every
  millisecond and has Attack and Release sliders with a soft knee; a new **Studio polish**
  effect (de-esser, warmth, lookahead limiter) runs last; *Podcast voice* uses it.
- The checks on Windows' default output and on Discord's settings each keep one thread
  of their own instead of starting a new one every few seconds, which could hold up the
  window (*Not Responding*) while Windows started it.
- An AI voices download that fails (offline, the connection dropped) no longer saves a
  crash report: the tab says what happened.
- Categories can now have subcategories. Right-click a category tab and pick "Add
  subcategory…" (or click "+ Subcategory" under the tabs): small chips under the tabs
  show just that group, and "All" shows everything in the category. Sounds can be in
  several subcategories, and pads, the pad menu and the bulk Categories menu know about
  them. Older settings load as they were.
- Free sound packs now arrive as one tab named after the pack, with their categories
  (Tavern, Combat…) as subcategories inside it, instead of adding a tab for each. Packs
  you already added keep their tabs; Backup → My sound packs → "Put its categories in
  one tab" tidies one up.
- A new version that was still in its first 30 minutes is now offered once they're up,
  instead of at the next check up to 6 hours later. An urgent fix you missed is no
  longer held back while a newer version settles.
- The clip editor's waveform keeps a steady scale: Louder and Quieter visibly change it,
  near-silence stays small, and it no longer jumps as a loud bit scrolls past.
- Trim zooms to what's left instead of leaving it as a sliver at the left edge.
- The Clip editor button's tip says what it opens.
- The PC going to sleep with Onion Board open no longer counts as the app freezing (the
  freeze check now counts only time the PC is awake), so *Count me in*'s freeze numbers
  show real freezes. A freeze that held up the whole app, not only the window, now says
  so, to tell the two causes apart.
- Fix a rare crash while the app closed or rebuilt its tabs (the hidden tab bar's last
  events).
- Find saved clips by name, app or creation date, and group them automatically by app and day.
- Replace the 200-clip limit with cleanup after seven days without use. Settings > Tabs offers Keep forever; automatic cleanup supports Undo.
- Fill large clip lists in small batches so the interface remains responsive.
- Fold saved clips down to one header and reopen them with their search and list height preserved.
- Apps recordings go to Saved clips first. The editor says Save to clips, and the result offers Show clips; Add to Sounds creates a sound when wanted.
- Give textured Dark, Light and Lilac themes a soft brushed satin finish instead of speckled grain.
- Keep the taskbar right-click menu icon in the theme colours when starting through a source launcher.
- Sharpen playback and volume slider knobs by drawing pixel-aligned circles without soft transparent borders.
- Hide empty saved clips and their resize grip while keeping Undo available and restoring the saved height when clips return.
- Disable the clip editor's Edit button when none of its menu actions are available.
- Fixed the anti-meridian hairline in the settled flat map by aligning adjacent world tiles to a shared pixel boundary.
- Show Live or Muted above the compact sidebar's output switch, with a crossed-out broadcast icon while muted.
- Search provider icons now follow the current theme accent, including after changing themes.
- Radio's stations panel now follows the active theme's texture and the Plain/Textured appearance setting.
- Use the active theme accent for application tiles without an executable icon.
- Settings search now finds themes by name; searching for themes or colours shows every theme group.
- Fixed a thin background gap between flat map world copies at fractional display scales.
- Feedback follow-ups resize immediately when their checkbox changes, without a delayed snap.
- Live tabs default to a small icon dot, listed first in Settings. Theme's colour comes before More colours.
- The Voice status bar uses a compact stop button so translated mic status text fits in narrow windows.
- Keep audio meters smooth while playing with the window visible behind a game or another app.
- Stop level meters flashing between colours when audio hovers around a warning threshold.
- Give the Apps clip editor a larger waveform and full-size controls, preview and trim actions, and a roomier edit menu. Saving returns to live audio automatically, while Undo can restore the previous selection.
- Keep saved clips directly below the app cards, with larger rows and visible preview, rename, delete and Add to Sounds actions. Move optional duplicate headphone monitoring into the program menu.
- Resize the saved clips list by dragging its grip, keep the chosen height for next time, or double-click the grip to fit the clips again.
- Let the UI timer slow down while playback is paused with sounds waiting in Up next.
- Keep compact-window layout changes together while resizing, and move the playing-tab marker with its tab.
- Hothead now has a crunchy megaphone sound during normal speech, with extra blowout when shouting. Autotune tracks quieter microphones and blends in a tuned robotic voice so its effect is audible even on notes that are already in tune.
- Apps window views keep their last picture when the source is minimised, label it clearly, and offer Restore for live updates without switching focus. Open views also refresh while another app has focus.
- New versions are offered 30 minutes after they come out instead of a day, and while the newest is that fresh no older version is offered.
- An urgent fix still shows its update banner when a normal release came out after it: the banner now installs the newest version.

## 2.0.4 — 2026-10-13

- Fix an error report that could pop up when a menu opened over the board (right-clicking a sound, for one).

## 2.0.3 — 2026-10-13

- When the FFmpeg backup download fails on both sites, the message now says what went
  wrong on each, not just the last one.
- Trying the mic set-up again right after "Your mic sends no sound" now restarts
  Windows' audio for that mic again, instead of taking its silence as a switched-off
  headset and leaving it stuck.
- *Count me in* now says why a mic effect set-up failed, and why fixing it by itself
  failed, as one fixed word (the admin prompt left open, the admin step not starting
  or stopping half-way, a silent mic, the mic helper, a missing mic, or the admin
  step's exit code), so failed set-ups can be fixed. Never the message or the mic's
  name.
- Count FFmpeg startup failures and verified recovery in the anonymous usage flags, remembering an unresolved failure across app restarts.
- Fix the FFmpeg backup download by pinning version 9.0.2, available from both download sources with the same verified checksum.

## 2.0.2 — 2026-10-12

- A mic that sends only silence because the headset is switched off or its mic muted no longer makes a mic set-up or repair restart Windows' audio over and over, and the messages ask about the headset first instead of telling you to restart your PC.
- The quick setup guide's mic step follows changes made outside it (a repair, Remove, or a Windows update taking the mic effect off) instead of still saying it works.

## 2.0.1 — 2026-10-12

- Skip with a sound waiting for a web search's song now stops the song, instead of playing your sound on top of it.
- Apps tab: an eye button on each program card with a window shows a small live picture of that window under the card.
- Added a persistent Stop voice effects button across the Voice tabs to turn off all voice modifiers and translation in one click.
- The app opens with the focus on the page you left it on, not on the Sounds button in the side menu: a tab other than Sounds no longer opens with Sounds outlined as if it were picked too.
- A web search's Play waits for the sound you're playing (it goes in *Up next*) instead of playing over it, and a sound set to play next waits for a web search's song. A looping background sound doesn't hold anything up.
- Setup tab: when your sounds go straight into your mic, its card has *Reinstall* and *Remove* for the mic effect, after the same are-you-sure box as Settings.

## 2.0.0 — 2026-10-12

- An add-on folder Windows won't let Onion Board read (locked by an antivirus, no permission, or a link it refuses to follow) is now skipped as a broken add-on, instead of closing the app at start-up.
- Settings: the Discord, feedback, bug report and Support buttons now live together on the
  About page (the duplicate *Feedback and problems* card is gone), and *Add-ons & help* is
  now just *Add-ons*.
- Dropdown menus settle closed during rapid repeated clicks and reopen after a short pause.
- Cards with pictures no longer flicker blank and back while the window is resized:
  each keeps its picture, stretched, until the new size is ready.
- A song played from a web search no longer stays stuck in the player bar: ■ now takes it
  out, and so does picking another site once it's over.
- Make plain and primary button hover shades easier to see in every theme, while keeping their words readable. Keep section colour tokens readable on every card surface.
- Wrap the selected voice name in narrow windows so longer translations stay visible.
- Keep focus on buttons while checking updates, reloading voices, downloading or installing add-ons, and cancelling a translation download. Ignore repeat clicks until the work finishes.
- Quick setup no longer jumps around: clicking between the first step's choices keeps the window the same size, Back / Next no longer flash it to the full screen height for a moment, and opening and shutting the Discord tip near the bottom of the screen puts the window back where it was instead of walking it up.
- Quick setup stays open while Bun puts your sounds into your mic: Back, Next, Esc and the X wait until it's done, so it can't be closed half-way.
- Bottom-strip icons follow the capital height of each theme's font.
- Setup: when your sounds go into your mic, the card shows the other ways (the virtual cable, another device) as two tiles that say what each one is for, like the setup guide, instead of a "use the cable" and a "remove the cable" button side by side with no reason and an empty card under them.
- The mini player's mic button shows a mic icon, struck through when muted, so "Mic on" reads as the state it's in.
- "This won't mute you yet" has a *Don't show this again* box, for people who play on the cable on purpose.
- The Discord warning on the Voice changer card now always shows (until Got it), instead of popping in when you pick a voice and pushing the voices down.
- Card heading icons stay level with the text when changing to a theme with its own font.
- *Also send to*: a device's − button is a small button again, not a bar across the
  rest of the Devices card.
- The side menu's *How it works* button moved from under the tabs down to the bottom,
  just above Settings, so it isn't mistaken for a tab.
- Radio: the map's corners are smoothly rounded like the stations card, not cut into
  little steps.
- Running the installer while Onion Board is open in a way Windows can't close (another
  account, a remote session) now offers to close it and carries on, instead of
  stopping with nothing changed (a silent install just closes it).
- *Straight into my mic*: after putting the effect back without a prompt, Onion Board
  now checks the mic really sends sound again (that check failed every time before).
- *Straight into my mic*: if the mic effect's file is deleted (by a cleaner or an
  antivirus, say), the board now notices and puts it back by itself, instead of your
  sounds silently no longer reaching the mic.
- Settings heading: in themes with their own font (Amber Terminal, Hacker, Comic Sans)
  the back arrow and the cog sit on the same line as "Settings" again, instead of a
  couple of pixels higher.
- Theme textures are back, and now every theme has one: scanlines, carbon fibre, waves,
  ruled paper, onion rings and more. Panels stay plain unless you pick Textured in
  Settings > Appearance > Theme style.
- A ⏭ Skip button next to ■ in the player (and the mini player), plus a "Skip to the next sound" hotkey in Settings → Hotkeys: the next sound in Up next starts at once. With nothing waiting it stops the sound.
- A damaged settings file no longer loses pads: the ones still readable in it, and sound
  files in your library no pad uses, are put back on the board, and the message says how
  many came back.
- The "Settings were restored" message now stays until you close it (newer messages no
  longer push it away) and has an Open folder button.
- "Others hear it" keeps its words in a narrow window: the little % numbers make room
  instead, so the box is never an empty square beside the mic icon.
- The open side rail's Live button now reads the right way round for screen readers
  ("Live, on" while others hear you), like every other switch.
- The taskbar preview's Stop button says "Stop everything" on its small hover tip; the
  full sentence stays on Stop all's own tooltip.
- An urgent Onion Watch fix now shows its banner on the Triggers tab only, not across the whole board.
- The first click on the Triggers tab is as quick as any other (~30 ms, was ~220 ms): it's shown once behind the loading screen, like Settings.
- SoundCloud searches no longer ask SoundCloud's picture server about every result's full-size
  cover: fewer connections per search, and none to it at all with search pictures off.
- Settings and Edit sound are built behind the loading screen, so even their first open after starting is almost instant (about 20 ms instead of 100-300 ms).
- Settings and Edit sound open again almost at once (about 15 ms instead of 100-300 ms): a closed one is kept and reused instead of being built again each time.
- Count me in also counts Pause, Stop all, the taskbar buttons, add-on set-ups and
  repairs, restore points and sounds set to play over each other (names only, listed in
  SECURITY.md).
- The board is ready the moment it appears: your sounds finish loading and the window draws itself while the loading screen is still up, instead of in the first half-second after.
- The loading dots under Bun now light up one after another even with Windows'
  Animation effects off (they just don't grow or hop), so you can see it's working.
- Editing a very long sound: Preview with effects plays within a second (it renders only the first 30 seconds of a sound over 5 minutes, not all of it), and saving new effects again stops the render still going instead of running both.
- The Triggers tab opens instantly: Onion Watch now loads behind the loading screen when the app starts, not the first time you click the tab.
- Unticking "Others hear it" while your sounds aren't in your mic yet now says your voice still goes out (voice apps take your mic straight from Windows) and offers the one-click set-up.
- The Triggers tab opens about twice as fast: Onion Watch's tab is made right on the board's page instead of being moved there when done (with the next Onion Watch update).
- Live voice and AI voices no longer need you to install Python. When your PC has no
  suitable Python, the add-on gets its own copy (about 15 MB) that stays in the add-on's
  folder and goes when you remove it. The installer's live voice box works without
  Python too.
- If the Python one of those add-ons was set up with goes away (uninstalled or
  upgraded), the Voice tab now says so and offers Repair, instead of the add-on just
  failing to start.
- Very long sounds (an hour or more) start at once and no longer cut out: the app reads the next couple of minutes ahead while one plays instead of the whole file on every press or skip, and on a 44.1 kHz device it no longer makes a full copy of a song over 20 minutes long.
- The "What others hear" meter now moves when you talk before your sounds are set up in your mic: voice apps hear your real mic then, so it was showing nothing while others heard you.
- Resizing the window no longer makes the sound cards jump: they keep their height as a row gains or loses one, and names stay on one line (cut with "…", the whole name shows on hover).
- New: OnionBoardCleanup.exe, a separate download linked from the README, takes
  everything of Onion Board off a PC whose uninstall didn't finish (the mic effect, the
  mic helper, the app, shortcuts, logs). Your sounds stay unless you ask.
- Live controls and a pad's Effects: "no change" (1x, +0 dB) now sits in the middle of every slider, like the pitch one, with a small notch to find it again.
- The Sounds toolbar, the category tabs and the sound cards now line up on both sides.
- Sound cards now stretch to fill the row, so there's no empty strip on the right in a narrow window. Pad size still picks roughly how big they are.
- Downloads: the progress bar fills once per sound and never jumps back to empty. Looking the link up, downloading (even in parts) and converting are now one bar, and the download banner's top line shows how far the whole list has got.
- Web search and link songs: a Play that finishes downloading while another song plays
  no longer cuts it off. It waits in *Up next* and plays when that song ends, so five
  Plays play all five, in the order you clicked. Click its chip to play it now, its ✕
  to take it out; Stop all clears them.
- The row above the pads shows *Now playing* first, then *Up next* on the same line:
  as many as fit, then "+n more". In a narrow window Up next steps aside instead of
  stacking chips on top of each other. In Arabic the row reads right to left.
- Closing a warning or tip bar at the top of the window no longer jumps the keyboard focus to the Sounds tab.
- Thin leftover lines no longer show behind and between the sound cards after scrolling at 125 % / 150 % display scaling
- Setup tab: Your mic and Who's listening are the same height with their titles on one line, and Equalizer and volume sits under Who's listening.
- Setup tab: Devices, Connect your chat and Equalizer and volume are always open; they no longer fold shut.
- Card headings: the ⓘ, the heading icon and the status pill sit exactly level with the title.
- Settings: the "Settings" heading is the size of the "Onion Board" name beside it, level with it, with a cog after it; the back arrow sits level with its letters
- Stop all (the red button on the side) and the Stop everything hotkey now also turn the
  voice changer, the AI voice and the computer voice off, not just sounds, the radio and
  programs.
- The Voice tab's Custom tab is now part of Add-ons: custom voices (voice servers and voice packs) sit under the add-ons list, one tab fewer.
- Muted with "Hear what they hear" on no longer silences your own headphones: your sounds
  keep playing for you, only others stop hearing them.
- Screen readers now say each theme card's name and the Overlay page's Size and
  Background sliders.
- Side bar: the Live switch and the stop square are now two matching buttons, Mute and Stop all, centred in the card; the Tor, proxy and Offline lines are centred too, their icons level with their words.
- Radio tab: the buttons no longer shift a few pixels when you click Play / Stop or Send.
- Round buttons and other drawn shapes keep their left and top edge on 125 % / 150 % Windows scaling (the play button looked flat on its left).
- Sounds brought over from another soundboard (Soundpad, Resanance, Soundux, EXP) now
  also go in a category named after it, so they're easy to find. Their own categories
  come over as before.
- The taskbar and tray icon no longer flicker while a sound plays (the onion kept
  losing and getting back its layers). Only the logo inside the app glows now.
- Plain **F12** works as a hotkey again. Windows won't hand it out the usual way, so Onion Board now watches the key itself, and the "can't be a hotkey" warning at every start is gone.
- Playing a sound now stops the one already playing, so only one sound plays at a time
  (before, a new sound played on top of the old one). Want sounds to layer? Set a sound's
  "On press" to Overlap.
- Language picker: a drop-down right under the Language button instead of a window, each language with its own letter on a coin (ß, Ñ, Я, あ, ع) in the theme colour; arrow keys walk the list.
- Flashbang: the language tiles, the Radio Favorites / Recent switch and the map's + / − buttons get a light grey fill instead of vanishing white on white.
- The player's seek line now runs the whole width of its bar when no sound is picked, instead of stopping at an empty gap.
- New look: the app font is now Bahnschrift. New Lilac theme: Dark's greys with a touch of purple.
- The sidebar's On Air card is now one slim Live row: the switch (Live or Muted) and a
  Stop all button side by side, with a yellow "Setup needed" strip under it only while
  something needs a click.
- Dragging the sidebar wider keeps the icon column until about 60%, then opens all the
  way, so it never shows a squeezed half-open layout.
- Setup: the virtual mic's buttons are one height and sit together in one group, and the
  main one is shorter: *Straight into my mic instead*.
- Radio and Apps: *Record* is as tall as *Send*, and *Send* (and Triggers' *Get Onion
  Watch*) has the usual space between its icon and its words. In a narrow window the
  Radio bar's buttons no longer stretch across it.
- Updating saves a restore point first (*Before update*, in Settings > General >
  Restore points), so the settings, hotkeys and pad list from before the update can be
  put back. Restoring it keeps the sounds where the update moved them.
- If the app is closed or the PC loses power while the first start after an update is
  moving sound files into their folders, the next start puts them back and finishes
  the job, instead of some sounds showing as missing.
- Mic effect: a mic that comes back silent from the audio restart gets up to three more restarts. If it's still silent after those, the set-up says so (and what to do) instead of "Done".
- Setup tab: a mic with the effect on that sends nothing but silence for 20 seconds (during a call, say) shows "Your mic sends no sound" with a one-click Repair. It goes away at the first sound.
- The anonymous usage count (Count me in) now also says whether the mic effect set up
  and kept working, whether Onion Board's own updates went through, and which of the
  newer parts get used (On Air, the Voice tab's tabs, Radio, the Setup tab's folded
  cards, Audio recovery, imports, the theme). Names from a fixed list only, as before;
  the full list is in SECURITY.md.
- Hover the app's taskbar button: the preview has buttons to play the last sound again,
  pause, stop all, play a random sound and go Live / Muted, like Discord's mute button.
- Putting the mic effect on or off no longer can leave your mic sending pure silence
  (to every app, Windows' own mic test included) when a voice chat grabbed the mic the
  moment Windows' audio came back. After the restart Onion Board listens to the mic for
  a second, and if it hears nothing but digital silence it restarts the audio once more.
- Every theme: words and icons on a switched-on button (On Air, Send, the Voice tab's
  tabs) stay readable, including on its hover and its lit top, and with your own
  highlight colour. The icons no longer stay white on bright fills like High Contrast's yellow.
- Links and small accent words (privacy links, effect values, a ticked menu row, What's
  new) use a readable shade of the accent: Flashbang's were yellow on white.
- Radio's and Apps' Send is on in your highlight colour like every other switch, not
  recording red.
- A sound's details left open across a theme switch now take the new theme's colours.
- "Add to my mic" mode: if the board freezes for a moment mid-sound, the sound now fades
  out instead of stopping dead with a click.
- The Setup tab is tidier: your mic and Who's listening stay in view, and Devices,
  Connect your chat and Equalizer and volume fold into one line each with a short
  summary (the devices in use, EQ on or off). Click a line to open it. Hotkeys are in
  Settings → Hotkeys.
- Mic effect fixes from a code review: turning sounds off in "add to my mic" mode now
  fades out instead of playing the last queued bit; Windows can no longer unload the
  effect while it's still handing it out; a mic stream that paused for a while no longer
  writes over another app's entry when it comes back; and a second copy of the board
  starting up can no longer take over the mic from the first one.
- The Voice tab has tabs of its own: Voice changer, AI voices, Languages, Custom and
  Add-ons, one card at a time instead of a long page of folding cards. It opens on the
  one you used last.
- Voices are picture cards now, as many a row as the window fits. The voice you picked
  sits in a bar under them with Make it yours, and that bar never scrolls out of sight.
- The voice changer's on/off is a switch at the top of its card.
- AI voices and Languages group their settings into neat boxes, and Clear (what the
  voice said) only shows once something has been said.
- Mic effect: when checking the mic helper keeps failing, the app now tries again once a minute
  instead of on every redraw of the mic card.
- Mic effect: putting the PC's clock forward an hour or more can no longer make the mic helper
  delete an answer before the app has read it.
- Mic effect: on a slow PC the mic helper is no longer given up on after 20 s while Windows
  is still starting it, and an admin step still writing its log is waited for instead of
  being cut off after 5 minutes.
- Mic helper: its build lists every file with a checksum, and the admin step only sets up
  a build that matches; a damaged installed helper is noticed at once and replaced at the
  next Windows prompt, instead of every mic step waiting on a helper that can't start.
- Mic card: when another account removes the mic helper (or sets it up), the card's "click
  Yes when Windows asks" and the fix-by-itself follow the change after every mic step and
  when the window comes back after a while, without a restart.
- Apps tab: a program that goes quiet now says `quiet on <device>` on its card instead of
  `playing on <device>`.
- Mic helper: a laptop going to sleep, or the clock being corrected, while the helper puts
  the mic effect on no longer makes the app think it died and ask Windows (which then
  failed on the lock, code 4); a dead helper is still noticed after the clock went back.
- Mic helper: a request left while the helper is busy with another (a second account's) waits its turn instead of giving up after 20 s and sending Windows' prompt into the lock (code 4).
- Mic card: an admin step that didn't finish (the prompt left open, admin rights denied) is an error with what to do, not "You clicked No".
- Mic helper: a repair now puts the helper back when one of its files went missing (a virus scanner) or it was packed differently, instead of the mic step waiting 20 seconds and asking Windows again every time.
- Remote control: `/api/queue` answers `"playing"` instead of `"queued"` when nothing was playing and the sound started at once.
- Triggers tab: loading Onion Watch no longer runs its stand-alone start file, which logged an error about a second app every time the tab loaded.
- Setup tab: the mic card is rebuilt for the mic helper. It's one status box (what's happening, your mic's name and its live level) with a pill in the heading, and it only asks for a click when it needs one: the first set-up, a No on Windows' prompt, or a fix that didn't work.
- When a Windows or driver update takes Onion Board off your mic, the app puts it back by itself at start-up through the mic helper (no click, no prompt): a toast says "Fixing your mic…", then "Done".
- "Click Yes when Windows asks" only shows when Windows will actually ask.
- A mic repair or update restarts Windows' audio once instead of twice (about 18 s instead of 35 s).
- Bun's set-up show plays only for the first set-up, and its progress bar keeps moving on a slow PC instead of stopping at 92%.
- Mic helper: work and school (Microsoft account) Windows accounts now get it too instead of Windows' prompt every time, and on a PC with several accounts each one that set it up keeps it.
- Mic helper: if it stops half-way, the app notices within seconds and asks Windows instead of waiting five minutes; uninstalling also clears a half-removed helper, and its logs no longer grow forever.
- Pressing Enter over and over in the search box (or the Radio tab's search) no longer
  starts the same search again each time: it waits for the one already running.
- Search results: the back button is now a short "Back" (hover still says "Back to my sounds") and sits as far in from the top of the results panel as from its side.
- Web search and pasted links: "No results", "Can't use this link" and other search
  messages now show in the middle of the results area, where "Searching…" was, instead of
  a corner under Back. The "Search this without Tor" button has the Tor icon.
- Effects on long sounds no longer need gigabytes of memory: speed, pitch, EQ, boost,
  reverse and voice effects are worked out a few seconds at a time and saved straight to
  disk. An hour-long sound with an effect used to need about 10 GB; now about 100 MB.
- *Straight into my mic* asks for Windows' permission once. After that, repairing it
  after a Windows update, switching to another mic, taking it off and uninstalling go
  through a small helper without asking again. Only a new version of the mic effect
  itself asks once more.
- Setting up the mic effect also clears what older versions left on other mics.
- Adding a long sound no longer takes gigabytes of memory: it's read and saved a second at a time. A 1-hour MP3 used about 4.5 GB while it was added, now about 30 MB, and a sound up to the 2-hour limit costs the same.
- Playing a long link before adding it no longer loads the whole thing into memory.
- *Straight into my mic*: an older mic part is now updated cleanly: *Install update* takes
  the old part off completely, then puts the new one on, under one Windows prompt. If the
  new one won't go on, it's tried once more, and if that fails the old part is put back,
  so your mic is never left without one. A copy Windows still holds is removed at the
  next restart.
- An older mic part is no longer called optional: the update offer comes back each time
  the board opens until it's done, and the Setup tab shows an amber *Update your mic
  part* box with an *Update now* button (instead of "Nothing to set").
- While the mic is being set up, Bun works on the left, under the buttons, instead of in
  the middle.
- Fixed overlapping radio station-list loads occasionally failing to save their cache.
- Keep sounds reaching the mic when Windows quickly restarts its audio engine or another recording app takes over the mic effect.
- Reimporting sounds already in your library alongside an empty or unreadable file now reports the duplicates separately from the skipped files, as a warning.
- Align toast action text, such as See why, with the status icon.
- **Radio tab: plain words when something's wrong.** When the station list's server is down it now says so (*it's not you*), with a sad Bun on the map; offline says check your internet; a station that won't play says it isn't on the air. No more error text with the whole web address in it, and each reason shows once.
- Tests no longer leave download folders in the real temp folder.
- FFmpeg (needed for M4A, AAC and video files, pad pictures from videos and saving videos) is checked while the app loads. When it's missing or won't start, the app gets it by itself once the window is up, with a progress bar and *Stop*: winget first, then its own checked download of the same build, with retries. Offline mode, Low data mode, the FFmpeg download switch and *Don't ask again* keep it from downloading; the bar then says why, with *Fix it*.
- Settings → Data & quality always shows FFmpeg now: working (with its version), missing or won't start, with *Reinstall*, *Get FFmpeg* or *Fix it*, and the download's progress. A fix shows up at once, no restart.
- Add sounds is now one *Add* menu: sound files, a whole folder, Record, a link or a free
  pack. A stray click opens the menu instead of a file box, and the toolbar has one
  button less (Record moved into it).
- **Also save the video** no longer breaks Add as sound for SoundCloud (it has no video), or for YouTube without FFmpeg (it has no single video files any more): the sound is added and the bar says why no video was kept, naming FFmpeg when that's what's missing. Before, both failed with a wrong *That video isn't available any more*.
- The On Air card in the side bar now says when the app goes online through a proxy or Tor (and how far Tor got), or not at all in Offline mode, and when a phone remote or the remote control is listening. One click opens its Settings page.
- Sounds added from a TikTok link no longer get names like "Me &amp; you", and a pasted
  Myinstants page no longer adds " - Sound Button" to the name.
- With a proxy or Tor that isn't answering, a download now says so instead of telling you
  to check your internet connection.
- Voice tab: Speak in has its own on/off switch, off by default. Turning on a voice
  changer voice or the AI voice no longer starts translating by itself after you switched
  it off; picking a language still switches it on.
- Setup tab: the Equalizer card folds to its heading and on/off row while the EQ is off (seven flat sliders and an empty curve took a third of the tab).
- Setup tab: Connect your chat shows once your sounds reach a mic. Until then (nothing set up yet, or Nobody) its Step-by-step guide button is in the mic card.
- Typing only spaces into the Settings search box no longer closes the app with an error.
- Setup tab: with the virtual cable picked but not installed, Devices no longer also says "Nothing picked: only you will hear sounds" under the setup line.
- Setup tab: when your sounds go straight into your mic, the mic card says "Nothing to set." and one short line; what to do if a voice app chops your sounds up is behind the card's ⓘ.
- Setup tab: the My mic dropdown now lines up with My headphones and Send my sounds to.
- Setup tab: Who's listening has a proper gap between the mode buttons and the line about the picked mode.
- The control API's `/api/status` `explain` line stays in English like the rest of its JSON, whatever language the app is set to.
- The "Your virtual mic" card shows a proper red cross and green tick, and "Into your mic: not running" fits on one line.
- Setup's cards no longer get squeezed (buttons drawn over their text) after your mic's status changes; the same fix covers the Voice tab's effect columns and other layouts that rearrange themselves.
- Setting up your mic: "Done" shows when it really works (the card turns green and Bun cheers), not while it still reads "starting…" and Bun is still hammering.
- After removing the virtual cable, "Use the virtual cable instead" is gone until you restart: sending to the removed cable lost your mic.
- Re-scan devices ignores extra clicks while it shows what it found, and Also send to's rows aren't rebuilt when nothing changed (no more flashing device names).
- Switching themes does far less work while sounds or the mic effect are running, so it
  freezes the window much less: the app no longer answers ~28,000 small style questions in
  Python on every switch.
- The download banner is one list now: a summary line ("Adding 3 sounds", how many
  failed) over a row per song, the one downloading with its bar, the ones waiting, the
  ones that failed with Retry and the ones added already. No more "+2 queued" button to
  open. A short window folds it to the running song, then to the summary line, instead
  of switching to the mini player.
- Every one of the 31 themes checked on every screen: the picked theme card in Settings no longer fills with the accent colour (its name was grey on grey in Carbon), and the accent-coloured *Add sounds* and icons stay readable in light themes with a pale accent (Flashbang).
- Theme switches make about a third fewer slow style calls.
- Audio recovery in Settings now lists every mic as its own row: its name (two mics
  with the same name are numbered, unplugged ones marked), whether the mic effect is
  on it, which one Onion Board uses, and every action it can take as a button, with
  nothing hidden in a menu. A mic with the effect gets its fix when it needs one, a
  clean reinstall and remove; a mic without it gets Install and "Clean up leftovers",
  which safely takes out anything Onion Board left on that mic. Every action works
  only on its own mic. The mic effect works on one mic at a time, so installing it on
  another mic says it moves there and where your sounds will go.
- Radio and Apps: Redline shows its gauge again, for the pitch (-36 to +36 st, red past ±24), with quick pitch buttons under it.
- Radio: with no saved station list (a first start, a reset), the most listened-to 300 stations show in a second or two instead of waiting 5-15 s for all 3000; the full list fills in behind them.
- Radio: Popular, the star and Recent are the same height, and the star sits centred when the window is small.
- Switching theme no longer shows a half-styled window: Bun covers it for a moment, then it fades to the new theme.
- Switching theme does less work (a drag-and-drop helper no longer checks every restyle event).
- Menus and dropdowns show clearly which row the mouse is on, in every theme.
- The download banner and its rows get the theme gradient: the accent lit at the top left,
  in full on themes whose own colours match it (Lava, Ocean, Onion, Barbie) and softer on
  the rest, a light green tint when a song is added and a light red one when it fails.
  High Contrast stays flat.
- The download queue no longer gets stuck on "Processing audio…" under the ✓ after the last song was already added: a late update can't undo a finished (or failed) download, and the banner goes away as it should.
- Make the loading dots easier to see with a left-to-right accent highlight, growth and hop beneath Bun.
- Smooth the playback button's circular edge and keep Live tab badges, download controls and source icons crisp on scaled screens.
- Make Play the filled accent button on search results, with a dark outlined Add button and clearer icons.
- Settings → Appearance can show the first playing or paused sound's whole thumbnail behind the sound cards, with adjustable opacity, rounded corners and padding. Off by default.
- Give the collapsed sidebar equal visible spacing above and below the output toggle.
- Fix the playback bar staying grey until seeking: its fill now follows normal playback in both players.
- Leave room between the Settings back arrow's hover highlight and its heading.
- If Onion Board crashes while it is still loading (before its window appears, e.g. a
  broken install), that start-up failure is now noticed and counted on the next start
  instead of leaving no trace, so it can be fixed. A problem Onion Board catches and
  shows you as a warning, rather than letting it crash, is now counted too (only the
  error's type and the line of its own code, never your data).
- A tick box you click no longer keeps a white ring around it.
- Downloads: the "Add as sound" box at the top of the download bar and in its queue looked like a button. It is now a plain status tag with an icon: "Adding to sounds" (or "Playing once"), and "Waiting to add" for each queued row.
- Plain F12 as a hotkey: the app now says Windows keeps that key for itself (it blamed another program before), and the hotkey picker won't take it.
- A settings save that hit a file another program had open for a moment (an antivirus scan) is tried again instead of showing "Couldn't save your settings".
- The Discord warning bar (*Fix Discord*) and the "Looks like you're using Discord.
  Set up for it?" bar no longer appear together: while Discord's own settings are
  hurting your sounds, only the warning shows.
- The seek bar no longer looks a few seconds in when a sound starts at 0:00.
- Picking speakers or a headset under *Send my sounds to* now asks, when you leave
  Settings, whether you meant it: Discord and games don't hear sounds sent there. It
  offers *Use my mic*, the virtual cable (or installing it from Setup), or *Keep it*
  for OBS, Voicemeeter or a mixer. A virtual cable is never asked about.
- Adding several sounds at once shows a corner card with Bun, the count and a bar. Each
  sound shows up on the board, ready to play, as soon as it's in, and closing the card
  only hides it: the rest keep coming and the finished card (Undo) still appears.
  Its Stop skips the files not started yet; Undo takes off the ones already in.
- Every close ✕ (notices, tip and warning bars, the download bar, queue chips, hotkey
  rows) is drawn the same crisp way and can no longer be cut off or squashed.
- The small On Air toggle on the side bar sits closer to Stop all, and its dot turns green once your sounds are set up and working (yellow still means not set up).
- A pad whose sound plays from its own file elsewhere on your PC (*Copy into library*
  off) shows a small link mark before its length. Hover the mark to see where the file is.
- The button that shows and hides the tab names is now a side-panel icon instead of a plain arrow.
- Radio: a station that drops out and reconnects no longer freezes the window.
- When the sidebar is narrow, a dot on the On Air icon (not on the open/close arrow) says sending isn't set up; clicking the icon opens Setup. The arrow keeps its dot for the other alerts (offline, update).
- The quick setup guide is tidier: no empty band under each step's words, mic and speaker
  tiles only as tall as their names, the test sound card lined up with everything else,
  and the "Another device" list gets its own heading.
- Bun the bunny and Hoot the owl dress up for each theme: a crown in Royal, a cape and fangs in Vampire, laser eyes in Deep Fried, an onion hat in Onion, and more.
- Clearer words: the mini player's mic button says your sounds still play when it's muted,
  a link to a page with no sound says so plainly, and the "Keep your imported sounds?"
  box says how to get removed sounds back.
- Main buttons look richer: a soft gradient from your theme's colour into its second colour, a light top edge, and a deeper look while pressed. Text stays as readable as before in every theme.
- Clearing the "All hotkeys off / on" key (or giving it to something else) while hotkeys
  are off turns them back on, instead of leaving them off until a restart.
- When a damaged or missing settings file is restored from a backup, the restored copy
  is saved straight away, instead of waiting for the next change.
- The sidebar switch now says "On Air" while others hear you and "Off Air" when it is off (it used to say "Others hear"), and sits right after its words. Dragging the sidebar open, its card shows from 80%, a little smaller until it fits at full size.
- The sidebar status says "Not configured" only when nothing is picked to send your sounds to; a picked cable or device that fails says "Not working".
- **The quick setup guide looks designed now.** Mics and headphones are tiles (the product name big, "Microphone" small under it), four across, and your voice level moves along the picked mic's tile. A step bar shows where you are, Back / Next are bigger with bolder arrows, and everything lines up on the same edges.
- **"Where do your sounds go?" says plainly whether it works**: a green "Working" card with the mic Onion Board's audio driver is on, an amber one when it needs a repair, a grey one when it isn't set up. The virtual cable and another device moved into an "Optional" card, each with why you'd want it.
- **Switching from a working mic driver to the cable asks first**, and offers to tell us what went wrong with the driver.
- **The last step is shorter**: the Discord tip is a small pill you open if you want it, and the "Bring my ... sounds over" button is gone (the installer's tick boxes and Backup > Import from another soundboard do it).
- The mini player no longer gets covered by corner cards: with pads showing they're small
  icons at the top (hover to read, click to make the window bigger; nothing closes), and
  at its smallest they wait. Errors stay until the window is big enough to read them.
- Results and problems that showed as a line inside a panel are corner cards now: text-to-
  speech errors, a translation or speech download that failed or was cancelled, an add-on
  install that failed, Apps and Radio clip results, the clip editor's copy / paste results
  and errors, the clip shelf, Radio's station errors and list refresh, sound pack downloads,
  "No audio device" in the link bar, and copying a remote-control link. A voice added from
  a share code says so even with the voice window closed. Hints and progress stay put.
- Fixed a rare error while the window opens: a Discord settings check that finished before the window was built tripped over the app-setup bar.
- **The mic part's update asks first.** An older mic part no longer starts its update (and Windows' permission prompt) by itself at start: a small card offers it a second after the window opens, never from the tray, once per version. *Install update* checks your mic is still set up the same, then Windows asks; *Not now*, Escape or closing installs nothing, and Setup keeps the update button. Saying No in Windows' prompt is a short note now, not an error box.
- After the installer brings your sounds over from another soundboard, one box asks whether to keep them; Remove takes them all off again (Undo and Recently deleted still have them).
- "Removed X · Undo" is a corner card with an Undo button now, everywhere: removed sounds,
  deleted voices and AI voices, forgotten programs, deleted clips and modes, and the
  "Game mode for X" switch. When it goes, the thing is in Recently deleted as before.
- Turning *Hear what they hear* on or off while a sound plays no longer clicks, and
  clicking it over and over no longer makes a fuzzy buzz: the sound fades across.
- Give Add sounds a music-note icon in place of the plus.
- Buttons with an icon and words have the same, slightly wider gap between them everywhere.
- Local sound imports now link to the original file by default. Settings > Data & quality > Local sounds can keep a library copy instead. Both modes use the same decoded cache for playback, speed and effects; downloads, recordings and ZIP imports still keep their own files.
- Added Audio recovery in Settings: update the mic effect, clean reinstall it, or restore normal microphone operation by removing it. The card shows where the mic effect stands (Ready, Update available, Off) and offers the one fix it needs, including a repair when Windows has switched the effect off; the rarer actions sit in its ⋯ menu. Recovery runs in the background, verifies the resulting setup, and refuses to change mic settings if Windows audio cannot be stopped.
- Fixed icons and cards staying highlighted after opening a popup and moving the mouse away.
- A smaller, calmer startup splash with a steady Bun, the app name and three gentle loading dots. It follows your theme and Windows' Animation effects setting.
- Pop-up boxes that only told you something are corner cards now, so they don't stop
  what you're doing: couldn't use a picture, export failed, import failed, settings
  imported, settings restored, couldn't open Windows' sound settings, an update that
  couldn't download or start (with *Open the download page*), "Onion Board is up to date"
  (with *What's new*), sounds that weren't imported (with *See why*), a voice share code
  that isn't one, and a problem in the app (with *Report it*). Questions still ask.
- A corner card's long button (*Open the download page*) sits under the words instead of
  squeezing them into a thin column.
- The little note that floated over the bottom of the page is gone: everything it said
  (device problems, drop-outs, hotkeys off, "Up next", "Category: Memes", the volume,
  pasted pictures, a hotkey taken from something else…) now shows as a corner card in the
  right colour, and goes when it's over. A hotkey that took another one's key says so in
  one yellow card instead of a yellow note and a green card at once.
- The installer is shorter: a one-line welcome, a three-line privacy page, no group headings in the list of extras, and no "Keep a history" box (it's in Settings > Connection). "Where did you hear about Onion Board?" lost GitHub and its fine print.
- The virtual cable box is left out of the installer when a cable already works, instead of showing greyed out.
- Messages now show as cards in the bottom corner, above the player: green when
  something worked, yellow for a warning, red for an error (with a Copy button), up to
  three at once, and the same message twice is counted (×2) instead of stacking.
- Adding sounds shows "Adding 3 of 12…" with a bar, then one result with *Undo*, or
  *See why* when some files were skipped (a list of what and why, sorted into plain
  groups, that you can copy). The new pads light up once so you can see where they went.
- Dragging files over the window says what dropping them will do ("Drop to add 4 files").
- The installer's virtual cable box moved to the bottom of the list under "Advanced", with plainer wording (most people don't need it).
- Setup keeps the "Use the virtual cable instead" button when the mic effect works, for people who prefer the cable.
- A station's error line on the Radio tab stays up for 30 seconds instead of 4.
- The message after a damaged settings file says which folder holds both files.
- Adding a very short sound (under 0.3 s) shows a note that it may be barely heard.
- Closing Onion Board while a link is still downloading now asks first, instead of dropping the download silently.
- A link that can't be used now also shows its reason as a message, not only in the results panel.
- Settings are saved 100 ms after a change instead of 400 ms, so a crash loses less.
- After a restart or an audio buffering change, a message says your sounds are back on your mic.
- Installing the virtual cable no longer shows a PowerShell or console window: Windows asks once for VB-Audio's own signed setup ("VB-Audio Virtual Cable Installer").
- The installer downloads the cable while you're still picking boxes and asks Windows' permission the moment you click Install, instead of at the very end after a pause. The window keeps working meanwhile, and Cancel still works.
- Cancel the install after the cable went in, and the installer now says the cable is still on your PC and where to remove it.
- Cancel works while the installer downloads its extras (FFmpeg, live voice, Tor): it stops the one running and skips the rest, and says where to add them later.
- Updating: if another program (antivirus, a leftover process) is holding one of the app's files open, the installer now stops before changing anything and says so, instead of failing halfway and leaving an app that will not start.
- Installer: the list of extras (virtual cable, voice-to-speech, Tor...) no longer flashes the row under the mouse as you move it.
- Straight into my mic: changing the audio buffering (or any quick reopen of the mic) no longer leaves your sounds off the mic until Onion Board restarts.
- Quitting no longer reopens the mic or speakers when closing takes a moment: once Onion Board is shutting down, its device watchdog leaves them closed.
- Closing Free sound packs before the online list loaded no longer offers a crash report a moment later. Search results and link downloads that finish after their panel closed are dropped quietly too.
- Sidebar: an onion button between Settings and the arrow opens Join the Discord, Send feedback, Report a problem, the GitHub page and What's new. It sits exactly halfway at every sidebar width, and the small › on the sidebar card has a sharp tip again.
- Apps category headings work from the keyboard: Tab reaches each one (its line turns
  the accent colour), and the Menu key or Shift+F10 opens Rename / Delete. Tab goes
  heading, its cards, then the next heading, as they're shown.
- The Apps tab's own categories (Browsers, Music & media, Calls & chat, Games, Other)
  show in your language, in their headings and a card's Categories menu. They're
  still saved under their English names, so switching language or version keeps them.
- Apps cards show a program's own name, the way Windows' volume mixer does: *VLC media
  player* and *OBS Studio* instead of *Vlc* and *Obs64*. A program without one keeps
  the name from its file.
- Settings: *Play pads with one click*'s explanation sits under its words like every
  other option's; the overlay's *Open overlay* button and *Auto-hide after* choice
  are as wide as their words, beside what they belong to; *While I talk, lower my
  sounds* stays on one line.
- Triggers tab: without Onion Watch, the tab itself shows its card (the logo, one
  line, what it does in four points, *Get Onion Watch* and Hoot), centred, lighting
  up under the mouse. No more window popping up on entering the tab, and no empty
  page once it was closed.
- Apps: the Menu key or Shift+F10 opens a program card's menu (it was right-click only).
- Developers: `scripts/precommit.ps1` runs only the quick checks (about 10 s) and leaves the tests to CI; `-Tests` runs the picked tests here. The test picker no longer counts everything `conftest.py` imports for a test that borrows a helper from it.
- Settings > Appearance: the two *Live tabs* choices sit side by side, like the
  Connection choices (they wrap when Settings is narrow).
- Voice tab: *Make it yours* sits beside the voice changer's on/off switch, so you no
  longer scroll past every voice to find it. In *Speak another language*, *More
  options* comes right after the voice and speed, before the box of what was said.
- The *Type a line* bar has no volume slider of its own any more: a typed line plays
  like a sound, so the volumes at the bottom set how loud it is.
- The line above the Settings cog sits halfway between Stop all and the cog, with the
  same gap on both sides.
- The sidebar's output card is now **Others hear**: one line under it says "Not connected ›" (click it to set up) or "Connected", with even spacing all round.
- Switching **Others hear** off now cuts only your sounds, the radio and programs: your own voice still goes out while "Send my mic to others" is on and no voice changer is on. With a voice changer on, off is silence as before.
- A tab's "About this tab" card follows the theme like the rest of the app: its close
  is the app's own x icon (named Close for screen readers), its title and text use the
  shared sizes, and closing it puts the focus back on the tab you opened it from. Its "Click outside to close" line is gone
  (it still closes that way).
- Every "Reset" beside an effect, the live controls or a sound's effects looks the same:
  a small Reset with the reset arrow ("Reset all" is just Reset now; its tooltip says
  what goes back).
- The sound modes' "What do these do?" is an ⓘ beside the "Who's listening" heading.
- Edit sound's "Save as new sound" is "Save a copy".
- The sound mode buttons (Game, Voice chat, Clean, Advanced) have pictures, the same as
  the mode button in the sidebar.
- The Colour menus name their colours (Purple, Blue…) instead of showing codes like
  #1fb6ff, and tick the current one on its own colour dot, the same in the selection
  menu and on a category tab.
- A program's Categories menu on the Apps tab ticks the category it's in and shows
  "Music & media" properly (it read "Music _media"); its menus have icons, and Remove
  and Delete category are in red.
- The menu for picked pads no longer starts with an empty row.
- New *Interface size* in Settings > Appearance: make the whole app bigger or smaller
  (80 to 150%), on top of Windows' display scaling. Applies after a restart.
- The Sounds toolbar, the player bar and the mic bar are now all the same height, with
  the same 36 px buttons, so the top of the window no longer looks heavier than the
  tab rail.
- Settings is now a page in the main window instead of a separate window: the tab bar
  on the left and the player and volume strip at the bottom stay, so you can still
  play and stop sounds while you change settings. The back arrow, Escape or any tab on
  the left takes you back. The Settings cog is just its icon now, highlighted while
  open. Shrinking the window too small closes Settings; opening Settings from the mini
  player grows the window just enough to show it.
- Edit sound no longer locks the rest of the app: sounds, hotkeys and the board keep
  working while it's open. It still saves only on Save; removing a sound closes its
  Edit sound window without saving.
- On a full-screen window the search box no longer runs across the whole screen; the
  seek bar, the levels and the drop box still use the window's width.
- The volume numbers (100%, 70%) sit right beside their sliders and on the same line as
  the words around them, not floating off to the side a pixel low.
- Straight into my mic set-up and Windows voice downloads no longer fail on Windows in languages whose tools answer with letters like "ü".
- Hints, sound lengths and other grey text now read clearly in every theme, also on a
  button under the mouse and in the inset boxes, and the grey "Search…" text in empty
  boxes is no longer see-through (4.5:1 contrast or better everywhere).
- Radio: the info line no longer keeps saying "Searching…" for a few seconds after the results are in or the search box is cleared.
- Setup in a narrow window: the cards now go Devices, Your virtual mic, Connect your chat and Who's listening before the Equalizer and Volume, so the setup button isn't pushed below the EQ.
- Line up the sidebar's Sound output card: its icons share the tab icons' column, every line of words (including "Set up output") starts on one line, icons sit centred on their words, and long translations wrap instead of being cut off.
- Dragging the sidebar open is smoother: icons stay in one centred column until halfway, then tab names show with a compact header, and the full sidebar appears once everything fits.
- The sidebar's attention dot stays beside the expand arrow.
- Group the expanded sidebar's output switch and connection status, with visible labels and a broadcast icon.
- Keep Stop all visible and leave the listening mode picker on Setup instead of duplicating it on the sidebar.
- Drag the sidebar's inner edge to open or close it, bounded by its existing widths.
- The buttons that open a folder are now the same small folder icon everywhere
  (Settings, the Voice tab, a crash report), with the words in the tooltip.
- The bulk colour menu marks the selected sounds' shared colour. Mixed colours leave every option unmarked until a colour is chosen.
- The empty and populated soundboards use the same "Drop sound files here" hint.
- The anonymous daily usage count (*Count me in*) also says which of the newer features
  were used that day, as names from a fixed list (the first start's "What's it for?"
  answer, the Get Onion Watch window, Get FFmpeg, the download bar, a sound's source
  menu, Apps categories, Settings search and a few more). Nothing extra is sent on a
  click: each is a yes for the day in the one daily message. SECURITY.md lists them.
- The daily usage count goes by the day on your PC's clock, not every 24 hours: using
  the app in the evening and again the next afternoon counts as two days (it used to
  count as one, and the second looked like a day off). Still one count a day.
- Count me in also counts sounds fetched from a link or a web search: which site
  (YouTube, TikTok…), pasted link or search, how many a day, and failed sites. Never the
  link, its title or what you searched for (SECURITY.md lists every name).
- In a narrow window the levels strip at the bottom no longer drops your headphones'
  volume and the level of what others hear: it shows what others hear, with your mic and
  headphones as icons beside it. Click one to show its controls instead.
- The "Make it yours" button no longer gains "…" once a setting is on, and its count
  reads properly in every language; the last tips and hints that still named labels
  with "…" match the menus now.
- Menus, buttons and other labels no longer end in "…": the trailing dots are gone
  everywhere except the progress messages (Loading, Scanning and the like).
- Corrected a number of menu and button translations across the shipped languages:
  wrong or awkward wording for Edit, Rename, Advanced, Import, Fades, Search
  languages, Make it yours and more, and the Onion Watch and Onion Pocket names in
  their Remove labels.
- Settings: the Tab key now moves from the category list into the open page and on to Done, so every setting can be reached with the keyboard or a screen reader.
- Settings: the first card on every page now lines up with the top of the search box, and Done has the same room above it as below and beside it.
- Settings search: typing a page's name opens that page (hotkey opens Hotkeys), and a search that finds nothing says so instead of showing an empty window.
- Switching tabs off and on quickly, then opening *+ More tabs*, can no longer close the
  app with a crash now and then (Radio most often).
- A sound added from a web link (YouTube, TikTok, SoundCloud, Instagram, X, Myinstants
  and the rest) remembers where it came from: right-click it for *Open on YouTube*,
  *Copy link* and *Details* (channel, upload date, length, views), and a text file
  with the same next to the sound in your Sounds folder. Nothing extra is asked of the site: it's all from the download itself.
- The pad right-click menu is shorter: *Effects* and *Add picture* moved into
  **Edit** (its *Effects* tab, and a *Picture* row you can set from a file or a
  link), and *Show the file in its folder* is now *Open file location*, as Windows
  calls it. Edit's Sound tab is in three cards: Look, Playback and Timing.
- Submenus (Categories, the site's menu, and every other one) open just outside their
  menu instead of covering its edge, on either side and in right-to-left languages.
- Settings → Data & quality → Downloads → *Remember where it came from* (on by default)
  switches it off: new downloads keep no link or text file and the menu hides it; what
  was saved before stays. The *Details* box's bin button deletes one sound's info and
  its text file (it asks first; the sound stays).
- The Tab key now goes from the side rail into the page. It used to stop on the rail's
  last button, so the board, the search box and every setting were out of reach without
  a mouse.
- Screen readers now name the player's seek slider ("Playback position").
- Apps tab: a program saved in a category that no longer exists shows up in its usual
  category instead of vanishing from the tab.
- Radio tab: screen readers now name the Play / Stop button, the country, quality and
  sort boxes, the station list and the Popular / Favorites / Recent buttons, also when
  a small window shows them as icons only.
- Closing the app while a radio station is still connecting no longer prints an error.
- Control API: `/api/volume` and `/api/radio_volume` now say their real range (0-1000 %,
  100 is normal) in the help and the error messages.
- Fixed a rare crash after switching a tab off (or closing a window) while it was still busy in the background: what the background work held is now always let go of on the window's own thread.
- The search button picks the site (YouTube, YouTube Music, SoundCloud, TikTok,
  Myinstants) from its menu, in place of the row of site buttons over the results.
- Show more under the search results loads the next 20, up to 200.
- Back to my sounds is a plain button, lined up with the cards.
- Open search results follow a theme switch (Play buttons stayed dark in Light).
- Menus show the picked item in the accent colour.
- Side rail: the header is the name over a plain version number (no "from source" or
  byline; the title bar still says it, and hovering the header shows who made it).
- Side rail: the bottom is three groups with thin lines between them: what needs attention
  (not connected, offline, update) on top, then Live, who's listening and Stop all, then
  Settings with the open / shut arrow beside it.
- The header onion no longer cries when clicked ten times; a click still gives it a wobble.
- Side rail, shut: only Live, Stop all, Settings and the arrow stay (the warnings and
  "Listening" show on the open rail; a small dot on the arrow says a warning is waiting),
  and hovering a tab shows its name and key.
- Ctrl+1 to Ctrl+9 jump to the tabs in the rail's order; Ctrl+Tab and Ctrl+Shift+Tab step
  through them. Clicking the version in the header opens What's new.
- Stop all has its own icon (two squares), so it's not mistaken for the player's Stop.
- Side rail: more room between each button's icon and its name (about 10 px instead of 4).
- The Voice tab says "Voice effects off: mic unchanged" with a colon, not a long dash, in every language.
- A download bar at the top of every tab (and in the mini player) shows a web link's
  download as it goes: looking it up, how much has downloaded, then processing, with
  a Cancel button and how many picks wait their turn.
- Search cards stay clickable while one downloads: a new Play replaces the one still
  loading, and Add waits its turn (up to 3 waiting).
- Videos up to 2 hours long can be added or played (was 15 minutes).
- A link with no picture shows Bun writing the music down on a little scroll while it
  downloads: the opening of a well-known piece (Fur Elise, Canon in D, Twinkle twinkle
  and 26 more) as real sheet music, as much of it as has downloaded.
- The download bar can be minimised to one slim line (the song, how far it's got and
  how many wait); a click opens it again. On Setup it lines up with the cards.
- A download that worked shows a tick for a second before the next one takes its
  place; one that failed flashes red and waits in the queue list with Retry.
- Click a waiting song in the queue list to download it next.
- Play once while other songs download goes next in the queue (it doesn't wait behind
  the Adds), and a newer Play replaces one still waiting.
- Tab no longer gets stuck in Settings' network activity list when it has rows.
- In a narrow window the download bar keeps its progress bar: Stop all moves into the
  queue list and "+2 queued" reads "+2".
- Settings > Data & quality can now get FFmpeg itself (a Get FFmpeg button), so M4A, AAC
  and video files can be played and added without re-running the installer; the message
  when a file can't be played now says where to get it.
- **Uninstalling the mic effect is more reliable.** Taking *Straight into my mic* off a mic now keeps going if one mic can't be put back (it used to stop at the first one and leave the rest set up), removes the ring file with everything else, checks that Windows' audio really stopped before it changes a mic's effects (retrying once, and saying so if it wouldn't), and waits longer for the admin step so a slow PC isn't reported as a failure.
- **An uninstall cut off half-way finishes on the next run.** If taking the effect off is interrupted (a crash, a reboot) after it's already removed from the mic's effect slot, running it again now puts the rest of the mic's settings back. Before, it mistook the half-done state for Windows having reset the mic and left some of the change behind.
- Web search results now sit right under the toolbar: the empty category bar that
  used to leave a gap above the Back to my sounds and site buttons is hidden while
  results show, and the results' top padding is gone.
- **The mic effect now names itself.** `obmic.dll` (the Windows audio effect behind *Straight into my mic*) carries a version resource, so Windows' file Properties and security tools see "Onion Board" rather than a nameless, unsigned DLL. The build stays byte-identical for the same version.
- Apps tab: cards can be dragged anywhere on their surface to reorder or move between
  categories. Category section headers can be dragged to reorder sections.
- Apps tab: add custom categories with the "+ Category" toolbar button, or rename and
  delete categories from their section heading menu.
- Align Setup cards in two consistent columns, with Devices and Your mic at the top, and stack them in smaller windows.
- Show the Onion Watch install prompt in a dismissible dialog when entering Triggers without the add-on, with a button to reopen it.
- Data & quality settings keep dropdowns beside their labels and folder buttons together,
  with enough room for the video folder path and complete dropdown choices.
- **Builds no longer pick up another program's DLLs.** A build made on a PC with another program's ICU on PATH failed at start ("DLL load failed while importing QtWidgets"): `build.ps1` now runs PyInstaller with only Windows' folders on PATH, and `scripts/vc_runtime.py` deletes any bundled ICU DLL (Qt uses Windows' own).
- Empty sound boards show the same drop-file box as populated boards, below Bun,
  with instructions for adding sounds inside it.
- Fixed Voice cards briefly jumping to the wrong position when rapidly opening and
  closing them.
- Voice cards now use a consistent order: the start or power control at the top, followed by the description and settings. The computer voice status sits beside Start and wraps at narrow widths.
- Setup: Volume & shortcuts now sits below the equalizer in the left column,
  making better use of the available space.
- Removed the sidebar's How it works button and its app explanation popup.
- Fix the radio map's square corner backing: its container and splitter now reveal the window behind the map's smooth rounded corners.
- Voice tab: the "Type a line" bar moved to the top of the tab, so the bottom only has your mic level and the mixer.
- Restarting Windows, logging off or installing an update while Onion Board is open no longer counts as an unclean exit (it came in as "while-closing" or "pc-restarted") or saves a crash report.
- Tests: the highlight-colour test no longer writes its test board ("Boom", "Airhorn") into the real settings folder; a check stops tests from undoing every patch at once again.
- Switching the Radio tab off and on again (Settings → Tabs) can no longer crash the
  app now and then.
- Setup no longer has the *Test your local mix* card (Record 6s). To check what others
  get, use *Hear what they hear* or your chat app's microphone test.
- The side menu starts open on a new install, so the tabs show their names and not
  just icons. The button at the bottom still shuts it, and that choice is kept.

- Themes use clean, flat cards and a faint accent glow, without window grain,
  dark background fades or panel textures. High Contrast keeps its strong outlines.

- Quick setup: on the very first launch the guide starts by asking what you'll use Onion
  Board for. *Just sounds* changes nothing, *Streaming* adds the Apps tab and links
  the *Streamer guide* on the last step, *Competitive games* adds the Triggers tab
  (Onion Watch), and *Show me everything* adds every tab. It's asked once only; Settings →
  Tabs changes it later.
- Mini player shows connection status and a microphone mute switch. Expanded sidebar
  actions have labels; Setup puts devices first. Sounds groups
  library tools, Voice opens its presets on first visit, and secondary text reads more
  clearly. The full-width drop target is preserved.
- Add sounds and Record are flat icon buttons like the rest of the Sounds toolbar
  (Add sounds in the accent colour), with a divider before the search box.
- AI voices puts Start and live status at the top, with a wider voice picker,
  grouped pitch controls and shorter explanatory text in every language.
- The note that pops up above the player ("Added … to Sounds", device changes and so
  on) now sits centred over the page instead of jammed in the bottom-left corner on
  top of the sidebar, and is no wider than 560 px.
- YouTube and YouTube Music searches are about a second faster after the first one:
  YouTube's page settings are kept for an hour instead of being fetched before every
  search (Direct connection only; if a search with them fails, it's done again the old
  way, with fresh ones).
- *Straight into my mic*: when Windows starts running the mic effect after Onion Board
  opened (it loads it late sometimes), your sounds switch to it within a second instead
  of staying on the virtual cable until the app was restarted. If Windows takes the
  effect off, they go back to the cable the same way.
- The log no longer warns about "a native error was caught and survived" for Windows
  error code 0x8001010d and its kin: COM raises and handles those itself, so they're
  harmless. They no longer count as a crash at the next start either.
- The Voice tab's status bar (mic level and what others hear) moved from the top to
  just above the *type a line* bar at the bottom, and keeps the same height when a
  voice turns on or off, so nothing jumps.

## 1.9.28 — 2026-10-10

- AI voices: when the AI voice stops, the message says "Others now hear your real
  voice" (it said "my"), and no longer ends the error with two full stops.
- Quick setup: when *Straight into my mic* is already set up and working, the guide uses
  it instead of saying the virtual cable is connected and offering to set the mic up
  again (and *Straight into my mic instead* switches at once, no admin prompt).
- The quick setup guide no longer opens on every start after you close it with the X;
  it's still in the Setup tab (*Step-by-step guide*). Its buttons are all the normal
  size now (the big mic button and the wide Next button were oversized).
- *Straight into my mic*: a damaged link file between the board and the mic effect
  that said the wrong sample rate is made again, instead of your sounds going out at
  the wrong speed and pitch.
- Switching a tab off, or closing a window, while it's still loading something (the
  voice list, a picture, Discord's settings) can no longer crash the app.
- Starting the app (or changing theme) no longer makes every Desktop icon blink and
  redraw. Recolouring the app's own shortcuts used to tell Windows to rebuild its whole
  icon cache; now it only refreshes those shortcuts.
- When a mic or headphones won't open (for example while Windows' audio restarts),
  the message now says it's the audio device, not "It isn't a sound file that can be
  read, or it's damaged."
- Closing *Show this when a program is in front…* while it's still finding your open
  programs can no longer crash the app.
- A settings change made just as the background saver went idle is no longer lost
  (it could go unsaved until the next change, or be dropped at quit).
- Closing *Show this when a program is in front…* while it's still finding your open
  programs can no longer crash the app.
- Importing a backup whose settings name `read_only` no longer stops the app saving
  for the rest of the session (the imported sounds were gone after a restart), and a
  settings file naming it is no longer set aside as damaged.
- A pad's *Picture → From a link* no longer opens a file on this PC or a network share
  when the web page names one as its preview picture: only web pictures are fetched.
- A Myinstants sound whose download was cut short is no longer added half-finished:
  it says the connection dropped, so you can try again.
- A slow download from a site that doesn't say how big the file is no longer stops
  after 5 minutes with "The download stopped moving".
- A backup made after going back to an older version no longer carries the newer
  version's settings it doesn't know, which could be private to your PC.
- The remote control API answers a volume of `inf` or a malformed signature with a
  clear refusal instead of an error or a dropped connection.
- Updating the downloader (yt-dlp) no longer fails now and then when a search or
  download starts at the same moment.
- Switching off *Count me in* in Settings while in Tor mode no longer sends the last
  anonymous opt-out count, as the privacy page promises.
- A glitch from the mic (a broken sample from its driver) can no longer switch off
  parts of your voice effect for the rest of the session and let your real voice
  through.
- The left navigation rail blends into the window with a soft theme tint and a
  subtle divider, keeping the selected tab easy to spot.
- Fixed a build that wouldn't start ("DLL load failed while importing QtWidgets: The
  specified procedure could not be found") when the PC it was built on had an older
  Microsoft C++ runtime: the build now keeps only the newest copy.
- **Robo-Bun sets up AI voices.** While AI voices download and install, a little
  robot bunny runs off, comes back with a wrench and builds, with a moving bar and
  short steps like "Installing the voice engine" instead of pip's output. He cheers
  when it's done. If it fails, the real error still shows.
- Setup stacks its columns when translated controls need more room, keeping them
  visible without sideways scrolling.
- Radio's station panel clips to its rounded corners, and genre buttons keep their
  curves at compact heights.
- Restoring sounds after a reset preserves both the originals and new recordings
  with the same filename, including their pictures.
- Importing or resetting a pack keeps matching personal sounds independent of it.
- Folder packs detect equal-size content changes, so resetting uses the right archive.
- A removed web download can be added again in the same session.
- AI failure status describes the selected fallback: built-in voice, real mic or silence.

- Dropdown menus on the Sounds tab (Backup, Shortcuts, Order and view) open with a
  short gap clear of their buttons.
- **Polished playback transport controls.** The sound player's Play/Pause button uses an accent-pill style with clean high-contrast icons that adapt across all themes, and the Stop button uses a sleek secondary surface with a subtle danger outline on hover. Both buttons use smooth filleted vector glyphs with optical centering.
- The search box on the Sounds tab has a tidier gap between the magnifying glass
  and placeholder text.

- **Quick setup mic animation and clear navigation.** Putting sounds straight into your
  mic from the step-by-step setup guide now plays the Bun speaker-building animation
  directly inside the wizard, and success toasts no longer appear over or block the
  Back and Next buttons.
- The Radio tab's random button always plays a random popular station, whatever list,
  search or filters are showing. Before, it did nothing on an empty list such as
  Favorites with no favorites yet.
- The Sounds toolbar is a rounded card like the panels around it, with the search box
  set into it.
- Apps cards are grouped under Browsers, Music & media, Calls & chat, Games and Other
  headings. Left-drag a card's header to reorder it within its category for the
  current session. Unrecognized applications appear in Other.
- The Sounds toolbar sits on one smooth surface with evenly sized controls, bigger
  icons, a microphone for Record and a box for Backup. Search sits right after Add
  and Record; the folder, Backup, hotkeys and Recently deleted come after it.
- Idle Apps cards disappear after ten minutes without sound and return when sound
  resumes. Sending, remembered programs, recordings and clip edits stay available.
- Tab help uses a wider, rounded card with a clear heading, readable text and Bun
  the bunny, or Hoot the owl for Onion Watch. Click outside or press Escape to close.
- **Reorder sidebar tabs.** Hold the left mouse button on a tab and drag it up or
  down. The new order is remembered next time you open the app.
- **Centered sidebar status buttons.** When the sidebar is extended, the status icons
  at the bottom (Live, sound mode, Stop all and status pills) are horizontally centered.

- The Setup microphone card has a grouped audio flow, clearer setup guidance,
  and a separate optional update notice.
- **Polished Voice card headers.** Each card has a theme-coloured icon badge, balanced vertical padding and a narrower layout.
- Web search has a padded header and evenly sized source buttons with site icons.
- **No stray outline on Sounds.** Sidebar tabs show a focus ring only during
  keyboard navigation, so startup focus no longer looks like a second selected tab.
- The Voice tab's off state says "Voice effects off — mic unchanged" as plain
  status text. It no longer looks clickable or opens the voice changer.
- **Cards and the file-drop hint stay in sync.** Resizing, moving, adding or filtering sounds clears the old drop-area border and label as soon as the cards move.
- Floating status notes, including headphones changes and added sounds, disappear
  after eight seconds. Clicking dismisses them completely, so resizing the window
  cannot bring them back.
- Removed redundant hover tooltips from About this tab, More tabs, Settings and
  the sidebar arrow; their labels and screen-reader help remain available.

- **Readable voice meter.** The Voice tab's status chips no longer squeeze the
  mic meter into a tiny bar. It fills the available space and takes at least
  half the bar in roomy windows; status chips wrap below when needed.
- Live effects open over the app in a draggable window, stay open while using the
  board, and keep their position when reopened or when Redline is toggled.
- The speed gauge enters its red zone at 8x, like a car rev counter.
- Web search results no longer flash tiny windows while their cards are being built.
- The tray menu now shows a board icon beside **Open Onion Board**.
- The recording window has clearer source choices, a larger timer and a compact
  studio panel, with matching styling for trimming and saving a take.
- Web search and the Radio map have rounded outer corners, matching the other panels.
- Added missing menu icons, including sorting and Backup, and fixed checked menu icons disappearing against dark backgrounds.
- Adding and playing the same web result share one download. Repeated clicks no
  longer queue a duplicate import, and a failed download finishes both actions
  together. A thumbnail save failure no longer reports a successful audio import
  as failed.
- ***Count me in* also counts roughly how long the app was open** since the last daily count (under 15 minutes, up to an hour, 1-3 hours, 3-8 hours or more), so we can tell quick checks from all-evening use. Never the times of day; nothing is sent while it's off.
- **Clearer privacy text for *Count me in*.** It now says plainly that the random ID sent with the anonymous count links your counts together, so we can see how people use the app over time (which tabs, which versions, whether they come back) and what to improve. The only new thing sent is a short tag made from that same ID, so one person's days link up; switching *Count me in* off sends one last anonymous count (no ID) so we know how many people opted out, then nothing at all.
- **Shorter, plainer *Count me in* text.** Settings says it in one line (anonymous usage stats once a day; never your name, IP address or device info), and the eye next to it opens a small table of everything it sends, with an example and why, plus links to the full list and GoatCounter's privacy policy. The installer says the same.
- **Far fewer admin prompts for the mic part.** The mic part came out of every build
  with different bytes even when it hadn't changed, so each new version (and switching
  between two copies of the app) read it as "outdated" and asked Windows for admin
  to update it. Builds of the same code are now byte-for-byte the same, so it only
  asks when the mic part really changed. Picking *My mic* with an older copy that
  still works no longer asks either (the update stays optional), and right after
  it's set up the app no longer asks a second time while Windows is still loading it.

## 1.9.27 — 2026-10-09

- **Free sound packs.** *Backup → Free sound packs…* on the Sounds tab adds a
  whole ready-made board in one click, starting with the 67-sound GM pack for
  tabletop games. Made your own? *Share a pack* sends it in;
  once its sounds are checked as CC0 it shows up for everyone. It has its own
  switch in Settings → Privacy & security.
- **No more skips while you click around.** A sound playing no longer stutters
  when a tab opens for the first time (Apps, Radio, Triggers), during a web
  search, or while a link is looked up.
- **The player follows you.** Play, pause, stop and seek sit under the tabs, so a
  sound can be stopped from any tab. Every sound playing gets its own chip, and
  stopping one of two no longer looks like it stopped both.
- **Pasted links show a card** with the video to Play or Add; nothing downloads
  until you pick. Dead, playlist and soundless links say so in plain words.
- **Offline mode hides what only works online** instead of greying it out, and
  an *Offline* chip in the header says it's on.
- **Tabs:** *+ More tabs* sits right after the last tab and shows what each tab
  does; right-click a tab to hide it.
- **Voice tab** opens tidy with every card folded; *Custom voices* has its own
  card. Hothead now works on any mic, Walkie-talkie's clicks are off, and
  *Female voice* is now *High voice*.
- **Setup guide:** Bun reacts at normal talking volume (and doesn't cheer when
  the mic set-up fails), with bigger device tiles and tidier buttons.
- Bun, the owl and the logo move smoothly at a steady 30 fps.
- **Fixes:** 43 texts that were English in every language are translated; a
  sound on the Undo bar no longer gets added back as a dropped-in file; queue
  double-clicks no longer remove or stop the next sound; toasts keep all their
  lines in a small window.

## 1.9.26 — 2026-10-08

- **Bun sets up your mic.** While *Straight into my mic* is being set up, Bun
  rolls in and hammers a speaker together instead of a greyed-out button. If it
  works, the speaker plays and he cheers; if not, it pops and he shuffles off.
- **Pasted TikTok links work again.** They all failed with "Unexpected response";
  TikTok pads now get their picture too.
- **Smoother voice changer.** A changed voice could turn back into your own
  mid-call; dragging sliders while talking no longer clicks or drops out.
- **Fewer pointless error pop-ups.** A window closed a moment too early no longer
  shows an error report (it's still counted so it gets fixed).

## 1.9.25 — 2026-10-08

- **Fix:** an error report could pop up if the mic set-up finished after the
  quick-setup guide had already been closed.

## 1.9.24 — 2026-10-08

- **Set up for the app you're using.** When Discord, Zoom, Teams, a browser call,
  TeamSpeak, Mumble or a game with a known voice chat starts listening, a slim bar
  asks "Looks like you're using Discord. Set up for it?". *Set up* picks the right
  sound mode and shows what's left to check; next time that app starts, the mode
  switches by itself (with Undo). Settings → General lists the apps it remembers.
- **More for your Stream Deck and chat.** Remote control can now switch the voice
  changer straight to a voice, say a typed line in the computer voice (a channel
  point reward that reads out what the viewer wrote), queue a sound or play a whole
  category in a row, and turn *Hear what they hear* on or off. The Streamer guide's
  *Copy AI prompt* knows all of it, and lists your voices too.
- **Fixes:** *Send feedback* and *Report a problem* opened the Documents folder
  instead of the browser; the Sounds tab now lights up for a song played from the
  web search, like the Radio tab does.

## 1.9.23 — 2026-10-08

- **Safer mic set-up.** The one-time *Straight into my mic* set-up locks down its own
  data folder, brings back the Windows audio services it restarts, and puts your mic
  back as it was if anything goes wrong half-way.
- **The anonymous usage count says a little more** (only if *Count me in* is on; it
  still never sends names, sounds or files). Along with the daily count: rough
  buckets for how long ago it was installed, how many sounds your board has and how
  many you played, where your sounds go, the app's language, and which features you
  used. A new install also counts its first steps (added a sound, played one, one
  reached others) once each. The full list is in SECURITY.md.

## 1.9.22 — 2026-10-08

- **The mic update from 1.9.21 happens by itself.** If you set up *Straight into my
  mic* before 1.9.21, the first start of this version moves Onion Board's part of
  your mic for you: click *Yes* when Windows asks (once). No button to find.

## 1.9.21 — 2026-10-08

- **Your sounds reach every app that uses your mic.** Some apps open the mic in a way
  that went around Onion Board (Discord's *Studio* profile is one), so they heard your
  voice but not your sounds. Onion Board now sits in the part of the mic those apps
  can't skip. If you set up *Straight into my mic* before this version, the Setup tab
  offers the update (Windows asks once, and your sound drops out for a second).

## 1.9.20 — 2026-10-08

- **Sort your pads.** The new button by the search box sorts them *A–Z*, *Newest* or
  *Most played*, or keeps *My order* (the one you drag). Each sound now keeps a play
  count, starting from this version.
- **List view.** The same button shows the pads as one-line rows, several columns of
  them, with each sound's hotkey: hundreds of sounds on one screen.
- **Quick volume on a pad.** Hold Ctrl and turn the mouse wheel over a pad, or use
  the volume slider in its right-click menu, instead of opening *Edit* every time.
- **Save a typed line as a sound.** *Save as sound* beside *Say* on the Voice tab
  keeps the line, in the voice you picked, as a pad on the Sounds tab.
- **A colour per category.** Right-click a category → *Colour*: a dot on its tab and
  on the in-game overlay shows which one is up.
- **Small tidy-ups:** the ⓘ beside the tabs is on every tab now (a line on what the
  tab is for), the Apps tab's *Effects* and *Card size* controls wait until a
  program shows up, and the transport bar's time is blank until a sound is picked.
- **The Setup tab says the one-time setup once.** Before it's done, the card no
  longer shows two red crosses ("Your mic ✗ off", "Virtual mic ✗ not installed
  yet") over the orange step that explains it; nothing is wrong yet.
- **Search in Settings.** A box above the categories: type a word and only the
  cards with it stay, on the pages that have one (Ctrl+F gets you there).
- **More in a pad's right-click menu:** *Rename…* (just the name), *Duplicate* (a
  second pad with the same sound and its own file, for its own effects or hotkey) and
  *Show the file in its folder*.
- **Pads work from the keyboard.** On a pad, F2 renames it, Alt+Enter opens Edit
  and Delete removes it (it already removed the picked ones); Ctrl+F anywhere on
  the Sounds tab jumps to the search box. Arrows, Enter and Space worked already.
- **Mid-size windows keep the words that matter.** The *Listening* dropdown no longer
  stands alone as a bare “Clean” (its label goes with it), and *Record* keeps its word
  instead of becoming a lone red dot, until the window is really small.
- **Lighter on the CPU while sounds play.** The filters behind every voice chat mode,
  the EQ, the live effects and the voice changer do their per-block bookkeeping in one
  step instead of several, and the mono downmix for voice chat does its sums in bulk:
  playing a few sounds costs about a sixth less of a core, the live effects about a
  fifth less. Nothing sounds different.

## 1.9.10 — 2026-10-08

- **Links no longer break your browser.** Clicking a link in the app (the Discord
  invite, release notes, Report a bug…) while your browser was closed started the
  browser with the app's own network settings, so every site in it asked for a
  password ("The proxy 127.0.0.1 is requesting a username and password"). Links now
  open the browser exactly as if you'd opened it yourself. If it happened to you,
  closing the browser and opening it again fixes it.
- **A hotkey taken off a sound says so.** Giving an app hotkey (Stop everything, the
  overlay, push-to-talk…) a key a pad or category already had takes it off that one,
  as before, but now a message names what lost it, like setting a pad's key already did.
- **The Voice tab starts with the voice changer.** *Speak another language* moved
  under the voice changer and AI voices, so the voices are on screen the moment
  the tab opens.

## 1.9.9 — 2026-10-08

- **Pick your language.** *Settings → Appearance → Language* opens a window of
  languages, each in its own name, with a search. Every text in the app now comes in
  all 32 languages (machine-translated where no one has yet, so expect a few odd
  words). Windows set to one of them gets a one-time offer to switch; the app doesn't
  switch by itself.
- **Says when an app skips your sounds.** With *Straight into my mic*, an app that
  opens the mic in "raw" mode (bypassing Windows' sound effects) gets none of your
  sounds. The warning bar now names the app, so you know which one to fix.
- **Stream output is a row under *Also send to*.** Pick *Clean, for streaming* on a
  row to get the old Stream output (OBS) mix, with its volume and *Include my voice*
  under it. Your stream setting carries over.
- **Faster theme switch.** Switching theme in Settings no longer freezes the window
  for seconds.
- Setting up *Straight into my mic* no longer flashes an "Audio device problem — mon"
  error while Windows' audio restarts on purpose.
- **Triggers tab: Onion Watch 0.9.3.** A trigger's *Test* now shows in *Playing now*
  with its own stop, and its button says *Stop* while it plays. The Triggers tab is
  in your language too.
- Fewer hover tips that only repeated a button's name; dropdowns lose the empty gap
  before their arrow.
- Small fixes: the header logo restarts after restoring a minimised window, the Radio
  map shows country names before the station dots, the clip editor's "Listening…"
  fits small cards, and the radio's empty-clip messages say "on the radio".
- Old add-on copies left over from updates are cleaned up at start-up.
- **No more freezes when a headset drops out.** Unplugging a headset, Bluetooth
  cutting out or the PC waking from sleep could freeze the window for seconds while
  the app reopened the device. That now happens in the background, and so do
  *Re-scan devices* and picking a device by hand: the window stays usable while a
  slow driver answers.
- **No more short freezes on a slow or sleeping disk.** Pad pictures, the Discord
  guide's settings, the *Remove the virtual cable* check and a pad's video are now
  read in the background, so bringing the window back from the tray or picking a pad
  no longer waits for the disk. A pad shows its plain card for a moment until its
  picture is in.
- **28 more languages to speak in.** The Voice tab's *Speak in* list grows from 5
  to 33: Italian, Portuguese (Brazil and Portugal), Dutch, Polish, Czech, Slovak,
  Slovenian, Hungarian, Romanian, Bulgarian, Greek, Danish, Swedish, Norwegian,
  Finnish, Catalan, Japanese, Korean, Traditional Chinese, Thai, Vietnamese,
  Indonesian, Malay, Hindi, Arabic, Hebrew and Turkish. Each is a one-time download
  (66–125 MB) and uses Windows' free voice for it. Language names now show in the
  app's own language.
- **Setup and Voice tabs fit a big screen.** Full screen, their cards no longer
  stretch to half the screen each: the pages stay a readable width in the middle,
  and buttons, voice lists and sliders keep their own size instead of becoming bars
  across the whole card.
- **AI voices: pick by who and how high.** *All voices* sorts them under Men,
  Women and In between & fun (your own last), lowest first, with chips to show only
  one kind and only low, middle or high voices.
- **Live controls on the Radio and Apps tabs.** The Sounds tab's speed / pitch /
  effects popup now has a twin on the Radio bar and the Apps tab: change the pitch
  (Redline up to ±36 st) and add bass, treble, muffle, reverb, echo, distortion or a
  preset to the radio, or to every program you send. No speed there: a live stream
  can't be played faster than it arrives.
- **You can switch the app log off.** *Keep an app log* (Settings → Connection,
  under Network activity) stops `onionboard.log` being written and deletes it. The
  log can name a site a download or radio station failed on, so Network activity no
  longer says "nothing here is logged". With the log off, a crash report still gets
  the run's last lines, from memory.
- **The Radio tab speaks your language.** Its buttons, genres, filters, messages and
  the map's tips were still English in every language; now they follow the app's.
- **Triggers come back on at start-up.** With watching on, Onion Watch could miss
  starting with the window (an error while the window was still being built) and
  only picked up once the Triggers tab was opened.

## 1.9.8 — 2026-10-07

- **Onion Board has a Discord.** Chat, get help and hear about new versions: *Join
  the Discord* in Settings, the tray icon's menu, *What's new* and the installer's
  last page (it only opens when you click it).
- **Discord's automatic input sensitivity is caught too.** In a real call it kept
  cutting songs out in bursts: up to a third of a high-pitched song went missing,
  none once it was off. The *Fix Discord* bar and the Discord guide now say when
  *Automatically determine input sensitivity* is on and how to switch it off.
- **Lighter on memory.** The Radio tab's HD 3D globe is gone: the flat map (the
  default since October) is now the only map, and if you had the globe picked you
  get the map. That takes the whole built-in web browser out of the app, so the
  download and install get much smaller. Windows no longer get a graphics-card
  device each (about 30 MB and 16 threads per window, never given back), the maths
  library stops parking ~30 idle threads and up to 1 GB of reserved memory, the
  radio's decoder loads only once you open the Radio tab, and unused picture-format
  plug-ins (PDF and co.) no longer load at start-up.

- **Triggers tab: Onion Watch 0.9.2.** Lighter too (closed trigger cards cost almost
  nothing, and with watching off it doesn't load its maths libraries), and a green
  *READY* is no longer mistaken for a red one. The board offers the add-on's
  update by itself.

## 1.9.7 — 2026-10-07

- **Important fix: Discord wiping out your sounds on Straight into my mic.** Measured
  on a real Discord: its default noise suppression (Krisp / Voice Isolation) lets a
  song through for about a second, then wipes it out, and its **Studio** profile,
  which Onion Board used to tell you to pick, makes Discord skip Onion Board
  entirely, so none of your sounds got through. Onion Board now reads Discord's own
  voice settings while it runs and shows a bar across the window when one of them is
  in the way (*Fix Discord* opens the steps). The Discord guide, the setup guide, the
  Setup tab and the voice changer's warning now say the right thing for your mic:
  *Input Profile* **Custom**, *Noise Suppression* **None**, *Echo Cancellation* off
  (Studio stays the clean choice on the virtual cable). The guide shows each of your
  Discord settings with a ✓ or what to switch, and updates as you change them.
  It also catches Discord's *Advanced Voice Activity*: in a real call it let only
  about 2 seconds of a 25-second song through (the Mic Test never shows it).
- **Onion Board starts speaking your language.** When Windows is set to one of 19
  languages (Deutsch, Español, Français, Italiano, Nederlands, Polski, Português
  (Brasil), Türkçe, Bahasa Indonesia, Tiếng Việt, Русский, Українська, العربية, हिन्दी,
  ไทย, 简体中文, 繁體中文, 日本語, 한국어), the main window and the Sounds tab are in
  it; the rest follows. The same languages and words as Onion Watch's Triggers tab.
  Arabic is shown right to left. Hong Kong and Macau get Traditional Chinese.
- **Record a bit of what's playing.** The Sounds tab's **Record** window has a new
  *What's playing* choice: press Record, play a sound, a web search result or the
  radio (or catch a song already playing), then Stop, cut the ends and save it as a
  pad, named after what played. Your mic isn't in it. The window no longer blocks
  the board while it's open.
- **Space plays and pauses everywhere on Sounds and Radio**, not just on a pad: after
  clicking a web result's *Play*, a slider or a station, Space pauses (it used to
  click the button again and download the song a second time). Typing in a box and
  buttons reached with Tab keep their own Space.
- **You can see what's playing.** The web result in the player shows bouncing bars
  (or a pause sign) on its picture, gets an outline, and its *Play* becomes
  *Pause* / *Resume*. The Radio's bottom bar shows the station and song with moving
  bars; click it to find the station in the list.
- **One click plays a radio station** (clicking the one playing doesn't restart it).
- **The Radio's *Only me / LIVE* button is now *Send / Sending***, the same as a
  program's on the Apps tab.
- **Back to my sounds** stands out after a web search: a bigger red button.
- **More AI voices, and a way to tell them apart.** Six new voices: Duke (an older,
  gravelly man), Riley (a young guy), River (somewhere between a man and a woman),
  Ivy (a husky woman), Squeak (a tiny cartoon voice) and Titan (a giant). Under the
  voice list it now says who each one sounds like and how high it is. The new
  **All voices** button opens every voice as a card with a few lines about it and
  **Hear it**, a short sample in your headphones only. **Make your own voice** blends
  two voices and sets how deep and how high it is. No new download: AI voices you
  already have get the new voices too.
- **"Did you know?" tips.** Once the setup guide is done, Onion Board shows a short
  tip about one feature at most once a day, with a *Show me* button that takes you
  there. Never while a game is up, and each tip only once. *Show tips* in
  *Settings → General* turns them off.
- **Switch category when a program is in front.** Right-click a category tab →
  *Show this when a program is in front…* and pick your game (or any program). When
  it comes to the front, the board and the overlay show that category by themselves
  (and its hotkeys, with *hotkeys per category*); when it closes, the board goes back
  to what it showed before. Pick another category by hand and it stays. All the
  programs you've set are listed in *Settings → General*, with a switch for all of it.
- **The search box keeps its room** on the Sounds tab in mid-size windows.
- **Buttons in the guides aren't cut off any more** ("Copy the mic na…"): a window
  with a row of buttons grows wide enough to show them all.
- **Record a sound with your mic.** New **Record** button next to *Add sounds*:
  record your own voice (or, while the voice changer is on, your changed voice),
  then drag the ends to cut it, listen in your headphones, name it and *Save*. The
  quiet bits at both ends are already cut off. Up to 15 minutes; nobody hears you
  while you record.
- **A simpler first window.** A new install starts with just Sounds, Voice and Setup.
  The other tabs wait under **+ More tabs** beside the tabs: click one and it's added
  and opened. *Choose tabs in Settings…* in the same menu shows them all. Your tabs
  stay as they are if you already use Onion Board.
- **Instant replay and the Apps tab work on Windows 10.** They needed a Windows 10
  build normal PCs never get; any Windows 10 updated to version 2004 or newer works.
- **Fewer update prompts.** A new version is offered once it's been out a day, so a
  quick follow-up fix replaces it instead of asking you twice. Fixes for something
  serious still show up straight away, and *Check now* always finds the newest.
- **The loudest effect preset is now called *Deep fried*.** Same sound as before.
- **Search no longer looks up likes and comments** for each YouTube result. Results
  show their views as before, load with fewer requests, and YouTube is less likely to
  take you for a bot.
- **Instant replay reminds you to ask first.** Setting its key now says that in some
  places recording a call needs everyone's OK.
- **A broken mic-effect file can't cut out all of Windows' sound.** If the file *Straight
  into my mic* reads is damaged or tampered with, it just passes your mic through until
  the file is right again.

## 1.9.6 — 2026-10-06

- **New voice: Secret detective.** A disguised TV voice: yours plus a copy a fifth
  lower, lined up, thin and boxy with a metallic ring. Its knobs are all in *Make
  it yours*, so you can build it (or your own spin on it) by hand.
- **New voice knobs.** *Tone* has a *Mid* slider. *Pitch & voice* has *Gap between
  voices* (the lower copy lined up with you, or trailing like an echo), *Blur on
  the new voice*, and *Voice size on my voice too* (below 100 % Mix, your own voice
  underneath gets the new throat size as well, so it doesn't give you away). Your
  saved voices sound as before.
- **Every voice has a picture.** The eight voices that showed a "?" now have their
  own picture.
- **No blank window flashing up** when you open *Edit sound*.
- **Important fixes get a banner.** When a new Onion Board or Onion Watch fixes
  something serious, a banner across the top of the window says what it fixes,
  with an *Update now* button. You can hide it until the next start, but it can't
  be skipped for good. Normal updates keep the small *Update* button.
- **Updates show up sooner.** The app now checks for a new version every 6 hours
  instead of once a day. The setting is now called *Check for updates*.

## 1.9.5 — 2026-10-06

- **Switch off the tabs you don't use.** New *Settings → Tabs*: untick Radio, Apps,
  Triggers or Voice and that tab is gone from the window and doesn't load at all,
  next start included, so nothing of it runs in the background. Tick it again any
  time and it's back straight away. Sounds and Setup always stay.
- **No voice gaps in Straight into my mic.** When the board ran late (a busy PC),
  your voice could drop out or stutter for the people listening. It now stays
  smooth.
- **Onion Watch's Playing now bar clears on time.** The Triggers tab tells Onion
  Watch (0.8.0 or newer) the moment a trigger's sound ends, instead of it guessing.

## 1.9.4 — 2026-10-06

- **Simpler Devices card.** *Setup → Devices* is now just *My headphones*, *My
  mic*, and *Send my sounds to*, which is *My mic* unless you pick something else:
  *Nobody* (only you hear them) or any device by name (Voicemeeter, a device OBS
  captures, a virtual cable). The old two-step "Send to others through" + "Send
  into (the cable)" pair is gone.
- **Send your sounds to more than one place at once.** New *Also send to* under
  Devices (and in Settings → Audio): **+ Add a device** for each extra output (− takes
  one off), and each gets a copy of what others hear, for example your mic for
  Discord plus Voicemeeter and a device OBS captures for the stream.
- **A sound from web search can't get lost any more.** Played a pad, then a search
  result over it, then stopped the pad? The search's sound kept playing with no way
  to reach it but Stop all. Now it gets its own chip in the *Now playing* row (with
  its own stop button), and stopping the sound in the player moves the player to
  whatever is still playing.
- **Phone remote (Onion Pocket) is harder to knock over.** A device on the same
  Wi-Fi can no longer stall the app by opening thousands of connections: the
  remote servers keep at most 32 connections open (8 per device) and close the
  rest straight away.
- **Phone remote: the key stays out of web addresses.** The phone key is only
  accepted in a request header, never in the address, so it can't end up in a
  browser's history. Stream Deck links on this PC still work as before.
- **Phone remote: never on public Wi-Fi.** If Windows calls the network Public
  (a café's or a hotel's Wi-Fi), the phone remote doesn't listen at all, even
  if Windows Firewall would let it through, and it turns itself off if the
  network becomes Public while it runs.
- **Phone remote: your key stays on your phone.** With Onion Pocket 0.2.2 the
  phone no longer sends its key over the Wi-Fi with every tap: it signs each tap
  with the key, and Onion Board takes each signature only once, for that one
  tap, within five minutes. Someone reading your Wi-Fi's traffic can't copy the
  key or replay a tap. Older Onion Pocket versions keep working as before.
- **Clip editor copy and paste do what you'd expect.** A click places the cursor
  (a slight wobble of the mouse no longer picks a sliver), Ctrl+V always says
  what it pasted and where, and pasting right after copying puts a second copy
  in after it instead of silently swapping it for itself.
- **No more minutes of silence in the clip editor.** Left open while nothing
  plays, it keeps only what the program actually played: silence before it
  isn't kept, and long gaps close up to half a second.
- **Setup tab: the mic-part update reads as optional.** When your sounds are
  already in your mic, a newer mic part no longer sits next to "Nothing to set"
  as if something were wrong: it's marked optional, on its own line and button.

## 1.9.3 — 2026-10-06

- **Your mic, start to finish.** The installer no longer ticks the virtual cable,
  and the setup guide and the Discord and game steps name your own mic instead of
  CABLE Output. The Setup tab stops saying your sounds are "also on the virtual
  cable" and no longer warns you to pick a cable while your mic is working. The
  cable is only offered as the backup: *Use the virtual cable instead*.
- **Remove the virtual cable.** Once your sounds are in your mic, the Setup tab
  offers to uninstall VB-Cable (one Windows prompt). Keep it if another program
  uses it. The mic button also shows when it's busy setting up.
- **No crash when the Apps tab closes mid-scan.** Switching the Apps tab off, or
  quitting, while it was reading the list of programs could crash the app.
- **Radio: no grid while zooming.** Zooming the map no longer flashes a bare grid,
  and you can move round the map while stations are still loading.
- **Clip editor: saved clips get a list.** Save in an app's clip editor now keeps
  the bit in *Saved clips* at the bottom of the Apps tab: double-click plays it,
  F2 renames it, right-click adds it to your Sounds, sends it, copies it or
  deletes it (with Undo). They're kept between runs.
- **Copy a bit, paste it on the Sounds tab.** Ctrl+C in the clip editor, then
  Ctrl+V on the Sounds tab adds it as a new sound. The "Copied" message no
  longer gets cut off.
- **Big view for the clip editor.** The button at the right of the editor's
  buttons gives that program the whole tab and a tall waveform. Card size goes
  much wider too, and opening one card's editor no longer stretches the cards
  beside it.
- **The Sounds tab is lighter on a big board.** Scrolling draws only the pads that
  come into view instead of every pad on screen, and switching categories, dragging
  a pad to a new place and saving do less work, so they stay smooth with hundreds of
  sounds.

- **"Where did you hear about Onion Board?"** A new install with *Count me in*
  ticked asks on the installer's last page: YouTube, Reddit, GitHub, Google, a
  friend, or Other. Your pick goes once with the anonymous first-start count;
  *Rather not say* is picked unless you change it.

## 1.9.2 — 2026-10-05

- **Straight into my mic is steadier.** If Onion Board crashes or freezes, your
  mic no longer stutters for a moment when it comes back; it just carries on.
  After a short hiccup, the small safety delay it adds now goes back down on its
  own while the board keeps running. Mics that run at 44.1 kHz or 16 kHz sound
  cleaner, and setting it up or removing it is safer. Already using it? The
  Setup tab offers the update with one click (your current one keeps working
  until then).

## 1.9.1 — 2026-10-05

- **Straight into your mic is now the main way, for everyone.** Updating moves
  settings that used the virtual cable to *Straight into my mic* (once: pick the
  cable again on the Setup tab and it stays). Already set up on your mic? Nothing to
  do. Not yet? The Setup tab leads with one click (Windows asks for permission once),
  and until you click it your sounds keep going through the cable. Nobody goes
  silent: while your sounds go into your mic, the virtual cable (if you have one)
  gets them too, so a voice app still set to *CABLE Output* keeps hearing you, and
  the app tells you once that you can set it back to your normal mic. The header
  no longer sends mic users to the cable, and an older copy of the mic part keeps
  working, with its update offered instead of demanded.
- **A rare crash when the PC was busy is fixed.** Python tidied up its memory on
  whichever thread happened to be running, sometimes a sound or network thread, and
  that could free a part of the window while it was still ticking. It now tidies up
  on the window's own thread only (which also keeps that work off the audio threads).

## 1.9.0 — 2026-10-05

- **No virtual cable needed any more:** *Straight into my mic* puts your sounds into
  the mic Discord and your games already use. One click and one Windows permission
  prompt, and there's nothing to pick in Discord or the game. Your voice changer, mic
  volume, voice EQ, gate, ducking and mute all still work; your mic meter and mic
  check hear only you; Discord and a game can use the mic at the same time. If
  Onion Board closes, your mic is just your mic again. New users start with it;
  if you already use the virtual cable, nothing changes until you click *Straight
  into my mic instead* on the Setup tab. If a Windows update takes it off your mic,
  the Setup tab offers a one-click repair (or the cable). Uninstalling Onion Board
  puts your mic back exactly as it was.
- **Simpler sound modes:** *Who's listening* is now four modes: **Game**, **Voice
  chat**, **Clean** and **Advanced**. Game and Voice chat work out the exact voice
  chat by themselves (the game's own voice engine, or the app listening to the
  virtual cable) and shape your sounds for it; Clean sends them exactly as mixed;
  Advanced is the full list and your custom modes, as before. *What do these do?*
  explains each one and what it's doing right now, and every mode's tooltip says
  it too. Your old choice carries over, and older versions still read it.
- **Smoother everywhere, less CPU.** Nothing should feel laggy now:
  - Sounds: clearing the search or going back to "All" on a big board no longer
    stalls; typing in search, dragging Pad size and scrolling a board of pad
    pictures stay smooth.
  - Radio: typing in the station search no longer stutters (the list updates when
    you pause typing); genre, country and quality filters, play, stop and starring
    a station are faster.
  - Setup → Discord check and the Apps tab (switching a program off, Stop all,
    removing a program) no longer freeze the window, for up to several seconds.
  - Speed & pitch and volume sliders drag smoothly; changing the AI voice, its pitch
    or "Match the voice", or stopping it, no longer freezes the window for a moment;
    Voice tab sliders, presets and Refresh do less work.
  - The window appears sooner at startup (Onion Watch loads just after it).
  - Less CPU while idle, in the in-game overlay (none for paused sounds), on the
    Apps tab while hidden or behind a game, and in the setup guide. Bun in
    headphones rests between notes.
- **Switching to the Radio tab no longer freezes the app.** Since 1.8.0 the flat
  map threw its drawing away whenever you left the tab and drew the whole world
  again on the way back, freezing the window each time (longer on big screens).
  Now it keeps the drawing for a minute, and any redraw happens a slice at a time
  so nothing waits for it.
- **Anonymous usage count:** once a day the installed app sends a "still here"
  with just its version number and a random ID made on your PC, so we can see if
  anyone uses Onion Board. No name, sounds, settings or games. New installs have it
  on (the installer's *Count me in* box); if you installed an earlier version it
  stays off unless you switch it on. Settings → Privacy & security → *Count me in*
  turns it on or off at any time, and Offline mode, a proxy and Tor apply to it too.
- A removed long sound's audio no longer stays on disk for 10 minutes or more when
  it was still playing (or just brought back with Undo) as it was removed.

## 1.8.0 — 2026-10-05

- **AI voices (optional add-on):** talk, and others hear a different person: your
  words, timing and tone in another voice, live, on your own PC's CPU. Pick one of
  six characters on the Voice tab (Bear, Max, Brick, Sage, Nova, Pixie); *Match the
  voice* moves your pitch to where that voice sits, and a slider goes higher or
  lower. About one CPU core while you talk, nothing while you're quiet, roughly
  75 ms behind you. It isn't in the app or its installer: *Get AI voices* downloads
  it (about 40 MB plus a 15 MB runtime, needs Python 3.12+), and *Remove AI voices*
  takes it all off again. If it ever stops, a built-in voice preset covers you so
  your real voice isn't heard (or pick your own voice / silence). The voice changer's
  effects still work on top of it.
- Live voice-to-speech hands your mic to its helper without polling: no wake-ups at
  all while nothing is sent.
- **Much less memory for long sounds:** sounds over about 30 seconds stay on disk
  until they play instead of all being loaded at start-up (a board of 100 songs
  held about 3.5 GB). A pressed sound is read in first, so it starts and plays
  as smoothly as before, even from a slow drive.
- Lighter on the CPU: Hoot (the Triggers tab's owl) draws 10 frames a second
  while he only sways, live echo and helmet effects, sped-up sounds and a sent
  program's level check do less work, the settings backups are rotated at most
  once an hour, and download progress updates the window 10 times a second
  instead of hundreds.
- The flat radio map lets go of its picture (tens of MB) while it's hidden.
- Switching Tor off in Settings no longer freezes the window for up to 3 seconds.
- Smaller fixes: a relayed connection whose other end stopped reading is closed
  after 5 minutes instead of holding on for good; Tor's control connection is
  closed when its login fails; animations no longer restart in a minimised window.
- **Clip editor on the Apps tab:** open *Clip editor* under a program's card and it
  keeps that program's last minute as a live, scrolling waveform. Press on it to
  freeze, drag across the bit you want, and press Space to hear it in your
  headphones, Enter to save it as a sound, or **Send** to play it straight back to
  whoever's listening. Cut, copy and paste (also between programs), delete, keep
  only the selection, fades, louder / quieter, reverse, silence and undo are in its
  **Edit** menu and on the usual keys; Ctrl+scroll zooms. It's off until you open
  it: a closed editor doesn't listen, keep audio or draw anything.

## 1.7.2 — 2026-10-05

- Tab help now uses a crisp, theme-aware information icon in a larger square
  button, with consistent hover and keyboard-focus styling across tabs.

- **More to control from your phone and Stream Deck:** the control API (and so
  Onion Pocket) can now change the live speed, pitch and effects (bass, treble,
  reverb, echo… and the presets), switch who's listening (Discord, Steam voice…),
  and run the radio: list your favourite, recent and popular stations or search,
  play / stop, a random station, star one, go live, hear it yourself, and its
  volume. Changes made this way show on the PC's own sliders and buttons.
  Onion Pocket 0.2.0 puts it all on your phone: new **Radio** and **Sound**
  tabs (Settings → Remote offers the update).

## 1.7.1 — 2026-10-04

- **Onion Pocket updates itself from Settings:** when a newer Onion Pocket is out,
  Settings → Remote shows *Update Onion Pocket to …* on its card. One click downloads
  it (checked like before) and swaps it in while Onion Board runs: your phones stay
  paired, and the port and on/off stay as they were. If it can't update, the old
  one keeps working. (Onion Pocket 0.1.1 stops Onion Board freezing while Windows'
  firewall prompt is up.)
- Your phone shows an Onion Watch alarm: while a trigger rings, its pad lights up in
  Onion Pocket (and the Stream Deck API's status), and stopping that sound stops the
  alarm too.

## 1.7.0 — 2026-10-04

- **Pick your own highlight colour:** Settings → Appearance → *Highlight colour*. A
  rainbow slider (previews while you drag), *More colours…* for any colour, and
  *Theme's colour* to go back. It stays when you change theme, and changes in a
  blink.
- The play bar under your pads starts right after the sound's name: a short name
  like *Pick a sound* no longer leaves a big empty gap before it.

## 1.6.9 — 2026-10-04

- Recently deleted keeps Close beside its other actions. Sound pad menus no longer
  include Preview, and Apps / Triggers information is centered on the tab row.
- Newer Onion Watch cards can show each sound's volume and hotkey.
- **Your pads on your phone, with Onion Pocket:** Settings → Remote → *Get Onion
  Pocket* downloads the free add-on from GitHub (checked like Onion Watch). Scan its
  code with your phone's camera and your pads appear in the phone's browser (iPhone
  or Android, nothing to install): a tap plays the sound on the PC. Off by default;
  it has its own key, only answers phones on your home network, and never touches
  your mic. Windows' admin prompt for its firewall rule names Onion Board. It's
  optional: if it can't be downloaded or doesn't load, its card is simply left out.
- Settings: card headings line up with the text under them (they sat 3 px to the
  right).
- The control API's `/api/sounds` also gives each pad's colour.
- Radio: a station (or its redirect) pointing at this PC (`127.0.0.1`, `localhost`)
  is refused in Direct mode too, as it already was through a proxy or Tor.
- **Dozens of small fixes from a full code audit** (audio, voice and speech, network and Tor,
  saved data, the main window and its panels). An update download that's cut off
  part-way now says why in plain words, Settings opens faster without a stray little
  window, and What's new no longer shows twice after going back a version.

## 1.6.8 — 2026-10-04

- **Searching YouTube no longer gets you taken for a bot so easily.** Since 1.6.5 every
  YouTube search looked up each result's likes and comments the way a Play does
  (the video page, then several of YouTube's player APIs and its player script):
  dozens of requests within seconds, enough for YouTube to answer the next *Play*
  or *Add* with "Sign in to confirm you're not a bot". Each look-up is now a single
  page, one at a time, a second apart, and they stop for 30 minutes the moment
  YouTube asks for a bot check or slows requests down (your own *Play* and *Add*
  still go through). The message no longer suggests updating yt-dlp, which can't
  help with that, and says what causes it.

## 1.6.7 — 2026-10-04

- **A much better voice changer.**
  - **Sounds like a person, not a cartoon:** pitch now has *Natural sound*, which
    keeps the shape of your voice where a real person's would be, and *Voice size*
    (a bigger or smaller throat). Deep voice and Demon stop sounding muddy, and the
    new *Female voice* and *Male voice* sound like someone else instead of a
    chipmunk or a giant. Pitch also moves in half steps.
  - **Clean up my mic**, on to start with: a noise gate that learns your room by
    itself and hiss removal, before any effect. Fan hum and hiss used to come out
    as warble; between words the noise now drops from about -48 dB to -70 dB.
  - **New voices:** Female voice, Male voice, Talkbox, Autotune, Masked caller,
    Anonymous, Dark lord and Hothead (talk normally, shout and it blows out like a
    megaphone). Walkie-talkie now clicks when you start talking and goes "kshh"
    when you stop.
  - **New effects:** Autotune (gentle to full T-Pain), Monster growl (a voice an
    octave below yours, no extra delay), Helmet, Shout blowout, and Robot's
    *Follow my pitch* (a talkbox that sings the note you speak).
  - **Shows the delay:** a label tells you how far behind your real voice the
    changed one is. The pitch voices cost about 50-70 ms; the rest about 10 ms.
  - **Hear my voice is just your voice:** it no longer plays your sounds in your
    headphones too (the mixer's *Hear what they hear* still plays everything).
  - **A tidier Voice tab:** *Make it yours* keeps pitch, voice size, autotune and
    mic clean-up in view under the voices; every other effect is a card with an
    on/off switch, grouped, with what it does written on it and a Reset.
  - Your saved voices and older settings load as before and sound the same: the
    new controls start where the old sound was.
- **Sliders jump to where you click:** click anywhere on a slider's bar (volume,
  seek, speed, fades, everything) and it goes straight there, instead of creeping
  a step towards it; you no longer have to grab the circle. The circles are no
  longer cut off flat at the top and bottom, and light up when you point at them.
- **Getting Onion Watch shows real progress:** the bar under *Get Onion Watch*
  used to sit full while nothing seemed to happen. It now glides while the app asks
  GitHub for the newest version, installs and starts it, shows the download's real
  percentage in between, and the button says which step it's on.
- **Space pauses the sound you're on:** with a pad selected, Space pauses it while
  it plays and carries on from there when pressed again, like a media player,
  instead of starting it over. A sound that isn't playing still starts.
- **Live tabs are green to start with:** a tab whose feature is on (a sound
  playing, the voice changer, the radio) gets a soft green tint and a green icon.
  Prefer the old look? Settings → Appearance → *Live tabs* (now first, above the
  themes) picks the tint or a small green dot, one or the other. The tint lines up
  with the open tab's underline instead of sticking out past it.
- **Tidier small things:** no blank pad windows flash up behind the splash on
  start, and Bun sits on the splash nodding to his headphones; Settings →
  Connection → Network activity has no empty space under its list, and *Open log*
  works without a saved history (it shows this run's list, still not saved);
  *Start in the tray* is only ticked once *Start when I sign in* is on; the
  overlay's *Show preview* closes on any click or key instead of making Windows
  ding at every click while it's up; *Check now* in Settings → Updates sits on
  the left with its result beside it, not alone on a line of its own.

## 1.6.6 — 2026-10-04

- **Bring your board over from another soundboard.** Coming from Soundpad,
  Resanance, Soundux or EXP Soundboard? The installer spots it and offers a box,
  "Bring my sounds over from …"; leave it ticked and the first start copies your
  sounds in with their names, categories (tabs) and hotkeys. Your old app keeps its
  own copies and nothing of it is changed. Already installed: **Backup → Import from
  another soundboard**, the button in the setup guide, or drop its saved board file
  (a Soundpad `.spl`, for one) on the window. Sounds already on your board are
  skipped, and a hotkey something here already uses is left off. Nothing is looked
  at until you tick the box or click Import.
- **Quitting no longer crashes with Onion Watch watching:** closing the app with the
  Triggers tab watching could end in a Windows "stopped working" report after
  everything was already saved. It now ends cleanly.
- **The Triggers tab counts every trigger:** with more than 50 it said "Your 50
  triggers…".
- **Tidier small things:** the radio map's "Finding stations…" sits on a card
  instead of over the country names; the radio's filter boxes wrap onto more rows
  instead of reading "All coun"; Settings → Connection → Network activity fits its
  columns, Last included, without a scroll bar; the Voice tab points at the *Install
  speech recognition* button instead of an install.bat; the AI setup prompt's
  random-sound link no longer names a "Memes" category you don't have (it answered
  "not found"); and a computer-voice line no longer fails right after Windows speech
  had to be restarted.

## 1.6.5 — 2026-10-04

- **Sounds no longer stutter for the people you're talking to while the app is
  busy.** Whenever the window was drawing, the radio was loading or Onion Watch was
  checking the screen, what went into the virtual cable could break up: each piece
  of audio waited its turn behind the rest of the app and took 15 ms to make
  instead of half a millisecond, longer than it had. Starting a radio station made
  it worst. It now keeps pace whatever else the app is doing.
- **No more window freezes while you game:** the check for which game is in front
  (for the voice chat suggestion) looked the game up on disk every 3 seconds, and a
  drive that had gone to sleep froze the window for seconds at a time, with your
  sound hotkeys waiting behind it. It doesn't touch the disk any more.
- **The Radio tab doesn't freeze when it loads:** reading and saving the list of
  stations took the window (and the sound) away for up to a second. It's done in
  the background now.
- **Pressing a pad is lighter:** the first press of a long sound on a 44.1 kHz
  device no longer stops the window while the sound is converted (up to a second
  for a long song), each press no longer works out the sound's make-up gain again,
  and a press, a sound starting or stopping no longer redraws every pad on the
  board.
- **Myinstants search works again:** every search failed with "The site refused the
  download (403)".
- **No virtual cable needed: send your sounds anywhere.** Setup → Devices (and
  Settings → Audio → Devices) has **Send to others through**: *The virtual cable*
  (as before), *Another device* (Voicemeeter, a mixer, a capture card, a second
  sound card or any output OBS captures) or *Nowhere* (only you hear them, plus the
  stream output). With another device, Onion Board sends into the one you pick and
  never swaps the cable back in, stops asking you to install the cable, and the
  header pill turns green once it's sending (*Sending to: …*); the Setup tab says
  how to pick it up in OBS. *Nowhere* is for streamers whose OBS takes the sounds
  from Desktop Audio or the stream output: nothing goes out as a mic, and nothing
  nags. The setup guide's cable step has the same choice (*I don't use the
  cable*). The send device can't be your headphones (you'd hear everything twice,
  your own voice included), and *Nowhere* frees the cable to be the stream output.
  While nothing goes out to others, the header's Live switch says so (*Only you
  hear sounds*, or *Live — stream output only*) instead of *others hear you*.
- **Watch a pad's video:** a sound made from a video file, or from a link added
  with *Also save the video* on, now has a **Video** button in the player. It
  opens the video in its own window, in step with the sound: it plays, pauses,
  seeks and speeds up with it. The sound still goes out as normal; the video is
  only on your screen. Older versions of the app leave the links alone.
- **Settings → About:** the version, links to the website, source and license,
  ways to get in touch (feedback form, bug report, private security report), a
  note from the author, and the fine print in plain words. Instant replay's
  hotkey hint now also says to only keep clips of people who are fine with it.
- **Send feedback opens a form that needs no account:** Settings → Add-ons &
  help → Send feedback now opens a short form with your version filled in,
  instead of a GitHub bug report. The app still sends nothing itself.
- **Save your own voices:** Voice → Fine-tune effects has **Save as a voice…**.
  Name the mix and it gets its own button under *Pick a voice*, next to the
  built-in ones; right-click it to rename or delete it. A deleted voice can be put
  back with Undo, or from *Recently deleted* for 30 days. Saved voices go along
  with a backup's settings, and older versions of the app leave them alone.
- **Random voice shows what it did:** the dice is now the last voice button
  instead of a small button in the corner, and rolling it opens Fine-tune with
  the effects it set lit up for a few seconds.
- **The voice pictures are back** on the voice changer's buttons.
- **Keep the network activity list between starts:** tick *Keep a history
  between starts* under Settings → Connection → Network activity (or the new box
  on the installer's *Pick what you want* page) and every connection is saved on
  this PC and listed again next time, up to the last 1000. Off by default; nothing
  is sent anywhere, Clear empties it, and unticking it deletes the file.
- **Network activity totals:** **Totals…** beside Simple / Detailed opens a table
  of how much data went to each site (or each server): connections, sent,
  received, first and last time, sortable, and Copy pastes it into a spreadsheet.
  With a kept history it adds up the whole saved file, not just the 1000 the list
  shows. **Open log** opens that file.
- **Reset, with an undo:** Settings → General → Start over opens a short guide:
  tick what to reset (settings, hotkeys and optionally each sound's hotkey,
  sounds, Recently deleted, programs, audio devices), check the summary, and the
  app restarts with just those parts back to the start. A restore point is saved
  first, holding the settings and any sounds or bin it cleared, so **Restore
  points…** puts it all back (sounds added since are kept). The last 5 are kept.
- **Remote control for streamers, the easy way:** Settings → Remote has a
  **Streamer guide** (Stream Deck keys, channel points and chat commands through
  Streamer.bot, a panic button, with each link ready to copy) and **Copy AI
  prompt**, a message for ChatGPT / Claude that explains the links and lists your
  sounds so it can set up whatever tools you use with you (your key stays out of
  it unless you tick the box). The API can now also mute you (`/api/live`), switch
  the voice changer and mic, set the volume and category, replay the last sound
  and save the instant replay; `/api/help` lists every endpoint, and a mistyped
  sound name answers with what it probably meant.
- **The mini player always shows your sounds:** a web search's words stay in the
  search box, which also filters the pads, so a window made small afterwards
  showed a blank mini player (no pads, not even Bun). The mini player now shows
  every pad, and a board whose pads are all filtered out says so instead of
  showing nothing.
- **UI polish:** consistent painted icons replace emoji controls and search stats;
  search and app cards highlight on hover, with keyboard focus and playback on
  search cards. Compact voice controls, an Apps card-size slider that remembers
  its setting, and activity dots beside volume sliders reduce visual clutter.
  Country names now lead the flat map's label hierarchy, with quieter town names.
- **Honest download progress:** audio cards stay at 0% while preparing, show real
  download progress, and keep that progress visible while processing the audio.
- **Readable network activity:** theme-aware headers and alternating rows,
  bounded resizable columns, full-text tooltips and horizontal scrolling keep
  long entries from hiding the rest of the log.

- **A narrow window stays the whole app:** every tab now fits down to where the
  mini player takes over (about 440 px wide). The tab icons' spacing alone held
  it at about 480 px, so a narrow window turned into the mini player on whatever
  tab you were on.
- **Web search results that keep up with your clicks:** a result's *Play* or
  *Add* shows a progress bar on its card (and the percentage on the button), and
  the other cards wait until it's done, so a second click no longer cancels the
  first one (which then never played). *Add* then *Play* on the same card plays
  as soon as it's added, without downloading it again. Cards show views, likes
  and comments (YouTube's likes and comments fill in a moment later; YouTube
  hides dislike counts). The caption over the results and the paste-a-link hint
  are gone.
- **A smaller download: only the part of scipy that's used ships.** The app's own
  code no longer uses scipy, and the Triggers tab (Onion Watch) needs only its FFTs,
  so the build bundles scipy.fft, plus scipy.ndimage for Onion Watch 0.5.6, and
  leaves out the rest (signal, stats, optimize and the others): the installer is
  about 15 MB smaller and the installed app over 30 MB. Onion Watch 0.5.6 keeps
  working as it is. Its matcher is also a little quicker: 50 pictures are
  checked about every 300 ms at its 1% CPU share. Third-party effects modules that
  import other parts of scipy have to bring their own replacement; numpy, soxr and
  scipy.fft are still there.
- **Network activity** (Settings → Connection): see every connection the app
  makes, to check for yourself where it goes, and why: each one says what caused
  it (*You searched YouTube for “…”*, *You clicked Check now*, *Automatic update
  check*). *Simple* lists each server with why and what it was for, how often and
  how much data; *Detailed* lists each connection with its cause, route (direct, proxy, Tor), result, bytes each way, and the request,
  answer and encryption where the app can read them. Requests a switch turned
  away show as blocked. Kept in memory only: nothing is saved, logged or sent,
  and logins and key-like values in addresses are masked.
- **Tidier search results and category tabs:** web search results open with a
  *← My sounds* back button at the start of their header (it was *Back to my
  sounds*, alone at the far right), and the category tabs step aside while the
  results show, since they only pick pads. It brings back all your sounds: the web
  search left in the search box used to filter them down to the ones matching it. New categories are made with a small
  *+* right after the last tab instead of a *+ Category* button across the window.
- **City and town names on the radio maps:** zoom in on the flat map or the 3D
  globe and the cities and towns that have stations are named, so you can find
  your own place and its stations. Only the places in view are named, a few dozen
  at most, and none while zoomed out, so the maps stay as light as before. Search
  finds stations by city or region too, with or without accents ("zurich" finds
  Zürich).
- **Offline from the first start:** the installer's *Your privacy* page has an
  *Offline mode* box. Ticked, it switches Offline mode on before the app first opens
  (`OnionBoard.exe --set-offline`), so it never goes online, not even once, and
  unticks the installer's own downloads (VB-Cable, FFmpeg, live voice, Tor). It's
  ticked already when reinstalling over an app that's in Offline mode. Silent installs
  use `/OFFLINE=1`, which skips those downloads unless `/TASKS=` names them.
- **Search results and Apps as cards:** web search results are a grid of cards
  (picture on top, title, channel and length, Play and Add), as many across as
  the window fits, instead of full-width rows. The Apps tab shows each program as
  a card too, several side by side.
- **Restoring a maximized window no longer makes it the mini player:** the Radio
  tab's genre chips asked for room as if each sat on its own line (~300 px)
  whenever the window was big enough to show them, and every tab counts towards
  what the window needs. Widening a narrow window (e.g. 640 to 900 px with search
  results showing) could do the same: the window judged what fits by sizes Qt
  hadn't re-measured yet, brought back the long status pill, then found it too wide.
- **Get Onion Watch:** Hoot stands in the middle of his side of the card.
- **Better EQ:** the 7-band EQ and the voice *Tone* effect now follow the analog EQ
  curve they describe all the way up the treble. The 6 kHz and 12 kHz bands used to
  come out up to ~2 dB off (narrower and lop-sided, worst at 44.1 kHz); now they're
  within ~0.3 dB at every sample rate. The drawn EQ curve shows the same thing.
- **No more clicks when you move an EQ slider:** changing a band, a preset or a voice
  effect's knob crossfades from the old sound to the new over ~20 ms instead of
  switching at once, however small the audio buffer. Turning the EQ on or off,
  setting it back to flat or pointing it at something else fades too.
- **Our own filter engine:** all of the app's audio filters (EQ, voice effects,
  destination modes, the smart mono downmix, the limiter's look-ahead) now run on
  Onion Board's own code instead of scipy, and float32 audio is filtered more
  accurately than before.
- **Cleaner bottom bars:** My mic, What others hear and My headphones are three
  separate boxes. Each volume is a speaker icon, a slider and a plain % you can
  still click and type into (a typed volume applies on Enter, not digit by digit:
  "150" no longer dips a live mic through 1 % and 15 % on the way); the mic and
  radio level meters sit under their own volume slider. The Radio bar groups Play, random and star together, and its
  live button just says "Only me" or "LIVE".
- **Sounds playback controls:** the empty selection says "Pick a sound" with a
  tooltip explaining the controls, so the instruction fits instead of cutting off.

- **Settings categories:** a sidebar keeps all categories visible. Privacy &
  security groups online permissions, Connection holds proxy and Tor controls,
  Updates holds automatic update preferences, and Add-ons & help holds Onion
  Watch, feedback and support. Short labels and wrapped hints fit small windows.
  Theme previews use as many columns as fit, cards have space beside the scrollbar,
  and selected checkboxes and radio buttons show distinct ticks and centre dots.
- **Tor status:** leaving Offline mode refreshes the connection status immediately;
  Tor still starts only when needed.
- **Get Onion Watch:** retry a temporary GitHub gateway error once through the
  same connection and privacy gate, avoiding a cached failure. A persistent
  gateway error asks you to retry instead of blaming your internet connection.

- **Switch off anything that goes online**: Settings → Privacy & security has a switch
  for each thing the app does online (finding and downloading sounds, with one per
  site; updating yt-dlp; radio; Onion Board updates; add-ons; voice and speech-model
  downloads; custom voice servers; installing the virtual cable), and *Offline mode*
  on top that switches them all off. Off means no connection at all, through a proxy
  or not: the Radio tab says it's off instead of loading, the search bar only searches
  your own sounds, and the buttons that would go online are greyed with the reason.
- **More private radio**: the radio maps (the country outlines, the 3D globe and its
  Earth pictures) now come with the app instead of being downloaded, so opening the
  Radio tab doesn't contact a CDN at all. Stations play over `https` when the
  directory lists an `https` address for them. The app no longer tells Radio Browser
  which stations you play unless you turn that on in the new **Privacy** section
  (Settings → General), which also explains what the app sends where. Update checks
  no longer send the app's version number.
- **Privacy & security, the first tab in Settings**: what the app does online by
  itself, each with its own switch (checking for new versions, updating yt-dlp,
  telling Radio Browser what you play), the proxy setting below, and what goes online
  only when you ask. The installer's last page points to it. The General page no
  longer runs off the right edge of the window (the Remove Onion Watch button and the
  ends of the hints were cut off).
- **Send everything through a proxy**: Settings → Connection
  can send everything the app fetches (searches, downloads, the radio directory and
  its stations, thumbnails, updates, add-ons, translation models) through a SOCKS5
  or HTTP proxy, such as Tor's `socks5h://127.0.0.1:9050`. Site names are looked up
  by the proxy, not on your PC. If the proxy can't be reached, nothing is fetched,
  with a message saying why: the app never quietly goes direct. *Test* checks the
  address first, and switching applies at once (a playing station reconnects the
  new way).
- **Tor (optional)**: press **Get Tor** under Settings → Privacy & security →
  *Connection* (or tick *Private connection (Tor)* in the installer, unticked by
  default), then pick **Tor** there. The app doesn't ship Tor: it downloads the Tor
  Project's own (about 22 MB, through your proxy if you use one), checks it against
  a pinned checksum and shows how far the download has got. Where Tor is blocked,
  the download may be too. The sites you search and download from and the radio stations you
  play then see a Tor address instead of yours. Tor only runs while that's picked,
  shows how far it's got (*Connecting… 45%*, *Connected*), and until it's connected
  nothing is fetched: the app never goes direct behind your back. **New identity**
  switches to a different Tor route. **Hide that I'm using Tor** disguises the
  connection (Snowflake, or obfs4) for networks where Tor is blocked or frowned on;
  it's slower. YouTube often turns Tor away: the app tries up to three other Tor
  routes, then offers *Try this one without Tor*, which you have to click. Radio
  stations reconnect if their Tor route breaks. The switches above hold over Tor
  too: Offline mode never starts Tor, and *Get Tor* has a switch of its own.
- **The installer has a "Your privacy" page**, before the boxes: in plain words,
  what the app connects to and when, and what the *Private connection (Tor)* box
  does, with a link to the full list.
- A radio station that drops now really reconnects; before, the retry could end up
  replaying what was already received instead of opening the stream again.
- **Your headphones follow Windows' default output**: switch Windows from your
  headset to your speakers (or back) while the app is open and the sounds you hear
  move with it, instead of playing on the device you just switched away from. Picking
  a different headphones device by hand stops the following; picking Windows'
  default again turns it back on.
- **The Radio tab is much lighter**: it opens on a flat world map instead of the 3D
  globe. The map is drawn by the app itself (no web engine running behind it) and
  only redraws while you drag, zoom or hover a dot. It fills the whole area (no
  empty bands), names the countries as you zoom in, and wraps round sideways, so
  dragging stays smooth even zoomed all the way out. Hover a dot for the station,
  click to play, drag to move, scroll to zoom, double-click to zoom back out. The
  3D globe is still there: the map's **HD** button opens it (it's the
  old light globe; the spinning one with stars is gone), and **2D** goes back.
- **Less work behind a game**: with the window open but another program in front,
  the meters update 10 times a second instead of 30, and the logo, the mascots and
  the live-tab dots stop moving until you come back. Level meters only redraw when
  their bar changes, pads on another tab skip their visualiser, and the Apps tab
  no longer reloads every program's icon each refresh.

## 1.6.4 — 2026-10-03

- **A Sounds folder button** on the Sounds tab (also in the *Backup* menu) opens the
  folder your sounds are kept in. Sound files you drag into that folder join the board
  by themselves, once they've finished copying, including ones put there while the
  app was closed.
- **A short window keeps its pads**: below a certain height the window turns into
  the mini player, which only kept the pads above it when two rows of them fit. With
  big pads (or display scaling) that left an empty space above the player. One row
  is enough now.
- **Onion Watch 0.5.6** (Triggers tab, offered there as an update): the bottom bar's buttons have room around
  them, *Duplicate* and *Delete* sit on the *Fine-tune* line instead of a row of their
  own, and a trigger's pictures open big when clicked.

## 1.6.3 — 2026-10-03

- **Custom voices are easy to find**: an *Add voices…* button right beside the Voice
  list, and a *Custom voices* card in Settings → Audio (add a voice server, open the
  voices folder, or jump to them on the Voice tab). They used to be only at the bottom
  of the Voice tab's folded *More options*.

## 1.6.2 — 2026-10-03

- **A tidier right-click menu on a sound**: short names in three groups (play, change,
  share / remove), with what each does in its tooltip. The hotkey shows in the menu
  (*Hotkey: Ctrl+Alt+1* → Change… / Remove hotkey), and the picture options are one
  entry.
- **Giving a sound a key that's already used says so**: "F2 plays “Airhorn” now — it
  was the key for “Boom”" (or *Stop everything*, or a category's random key), instead
  of quietly taking it.
- **The hotkey is near the top of Edit…**, under the name and volume, not below the
  timings.
- **Fixed: a screen trigger's sound could still play after the trigger was deleted**
  (or the sound taken off it) when its pad was set to *Wait first* or *Queue*.
- **Fixed: "Up next" stayed in the status line** after the queue ran out, was cleared,
  or its last sound was taken out with ✕.

## 1.6.1 — 2026-10-03

- **Custom text-to-speech voices** (Voice tab → More options → *Custom voices*): use
  a TTS server running on your PC (Kokoro, AllTalk, openedai-speech, LocalAI — any
  OpenAI-style `/v1/audio/speech` address, or one that takes `{text}` in the URL),
  a TTS program, or Piper voice packs dropped into the voices folder. They show up
  in the Voice list next to the Windows voices, follow the Speed slider, and work
  for typed lines and *Talk as a computer voice*.
- **A frozen window is noted down**: if Onion Board stops responding for 5 seconds,
  what it was doing is saved beside the crash reports, so a freeze can be fixed even
  when it can't be repeated. Nothing is shown or sent.
- **The queue shows above the pads**: *Up next* lists the sounds waiting, each with a
  ✕ to take it out (the status line that said so could be hidden).
- **The stream output can't be another end of the cable you already send into** (VB-Cable's
  "CABLE In 16ch" next to "CABLE Input"): everyone in the call would have heard
  everything twice.
- **Settings tidied**: the per-category hotkey sets are with the category keys; the
  stream output's rows line up; *Hotkey sounds* says which keys beep.
- **Onion Watch 0.5.5** (Triggers tab, offered there as an update): a cleaner trigger
  card, one line until you open it, settings grouped into Watch for / Then / Fine-tune;
  and sounds stop when their trigger or sound is removed.

## 1.6.0 — 2026-10-03

- **Stream output for OBS** (Settings → Audio): send what others hear to a device of
  its own and add it to OBS as its own audio track — your sounds, screen triggers,
  live radio and programs, and your voice (with the voice changer) if you like. It's
  clean: no voice chat shaping, still stereo, with its own volume. A second virtual
  cable (VB-Cable A+B) or any output you don't listen on works. Sounds set to *Only
  others hear it* go to the stream too.
- **One key, a random sound from the category you're on.** The new *Next category*
  / *Previous category* hotkeys switch the category in-game, with a beep for each
  step along (one for the first, two for the second…; a low one for All). The
  *Play a random sound* key, and the overlay, follow the category you switch to.
- **A set of hotkeys per category** (Settings → Hotkeys): turn on *Sound hotkeys only
  work in the category showing* and the same key can play a different sound in each
  category.
- **More hotkeys** (Settings → Hotkeys): play the last sound again, sounds louder /
  quieter by 10%, send my mic on / off, voice changer on / off, change my voice only
  while a key is held, and *All hotkeys off / on* (so they type normally in chat).
- **Queue sounds.** A sound's *On press* can be *Queue*: it waits for the sounds
  playing to finish. Right-click any pad → *Play next*, or a category → *Play them
  all, in order* / *shuffled*. *Stop everything* clears the queue.
- **New per-sound options** (Edit…): *Only others hear it* (not played in your
  headphones), *Wait first* (up to 10 s between the press and the sound) and
  *Cooldown* (presses are ignored for up to 60 s, so nobody can spam it).
- **One click plays a pad**, if you'd rather (Settings → General). Off by default.
- **Triggers tab: a sound clicked on a trigger card plays to you alone** (not into
  the call), and stops when it's taken off the card or the trigger is deleted.
- **Onion Watch 0.5.4** (Triggers tab, offered there as an update): alarms stop by
  themselves when you're back (the game moves, you alt-tab back, it's gone, you touch
  the mouse or keys, or only on Stop), and characters and creatures cut out of a
  game as transparent PNGs are matched properly.
- **Send feedback and Report a problem** (Settings → General): open a bug report in
  your browser with your version filled in. Nothing is sent from the app.
- **Remove Onion Watch** from Settings → General → *Add-ons*, not only from the end of
  the Triggers tab's More menu.
- **Fixed: Recently deleted on the Triggers tab could crash** with "No module named
  onionwatch.ui.deleted" after Onion Watch was updated while Onion Board was open. An
  add-on is now loaded in full when it starts, so replacing it on disk can't break the
  running copy.

## 1.5.9 — 2026-10-02

- **Headsets with "Virtual" in their name show up again.** Onion Board took any
  device named "...Virtual..." for a virtual cable and hid it, so a headset like
  "Speakers (HyperX Virtual Surround Sound)" was missing from the quick setup's mic
  and headphones lists: no microphone found, and your own sounds played on the wrong
  speakers while everyone in the call heard them fine. Only real cables (VB-Cable,
  Voicemeeter, Virtual Audio Cable) are hidden now.
- **Input and output in Settings.** Settings → Audio now has your mic, your
  headphones and the cable at the top, with a Re-scan button for a headset plugged
  in after Onion Board started. (The same pickers are still on the Setup tab.)

## 1.5.8 — 2026-10-01

- **Your settings are never swapped for an older copy just because they were busy.**
  If another program (OneDrive, an antivirus) still held `config.json` at startup,
  Onion Board treated it as damaged and loaded an older backup over it. It now waits
  longer, and if the file is still locked it loads the backup without saving over
  your newest settings.
- **Settings from a newer version are kept.** Opening a config written by a newer
  Onion Board keeps a copy (`config.json.newer`) before anything is saved, so the
  newer version's extra settings aren't lost.
- **A sound brought back gives up a hotkey that's been taken meanwhile.** If you gave
  a removed sound's key to Stop all (or another action) and then brought the sound
  back with Undo or Recently deleted, its pad showed a key that never played it.
- **Tweaking a voice preset no longer replaces "My own mix".** Picking a preset,
  nudging a slider and moving on to another voice used to save the nudged preset
  over the mix you'd made.
- **Bringing back a sound can't strand its files.** If its picture couldn't be moved
  back, the sound's audio was left outside Recently deleted and the sound couldn't
  come back; now the entry stays whole.
- **Turning off a MIDI controller lets go of the pads held on it**, so hold-to-play
  sounds stop instead of playing on.
- **A failed yt-dlp update can't break downloads.** If swapping in the new copy
  failed halfway, downloads could stay broken until a restart; the working copy is
  now put back, and leftovers from an interrupted update are tidied at startup.
- **Radio stations can't point into your home network by name.** A station whose
  web address resolved to your router or another device on your network is now
  refused, as stations with such an address already were.
- Smaller fixes: a file named only with underscores (like `_.wav`) became a pad that
  vanished on the next start; two long sounds that differed only near the end could
  be taken for the same sound when restoring a backup; a device name or error text
  with `<` or `&` in it could show garbled in the Discord and game guides; another
  program's `%APPDATA%\Soundboard` folder with a `sounds` folder in it could be
  mistaken for this app's old one.

## 1.5.7 — 2026-10-01

- **Push-to-talk can't get stuck down any more.** With an admin window or a Windows
  prompt in front, Windows can refuse the key-up after a sound; Onion Board now keeps
  trying until it goes through, instead of leaving your game's push-to-talk held.
- **A glitch from a captured program can't silence your call.** One broken block of
  audio from a program on the Apps tab could leave the people you're talking to
  hearing nothing until a restart; it's now turned into a moment of silence.
- **Recently deleted can't be wiped by a locked file.** If an antivirus or OneDrive was
  holding the bin's list just as you deleted a sound, everything else in the bin was
  lost from the list. Now it waits, and never saves over a list it couldn't read.

## 1.5.6 — 2026-10-01

- **The app icon follows your theme everywhere**: the taskbar's right-click menu,
  a taskbar pin and the Onion Board shortcuts on your Desktop and Start menu (so
  Start search too) now show the icon in your theme's colours, not always purple.
- **The version is on show**: in the title bar, the taskbar, the tray icon's
  tooltip and under the logo, so you can tell at a glance which one you're running.
- **The Radio globe no longer vanishes when you move the window** to another spot or
  screen, leaving its country names floating on an empty background. It redraws as
  you move, and the names hide whenever the globe can't be shown.
- **A friendlier wait while searching YouTube**: instead of a line of text in the
  corner, Bun or Hoot keeps you company in the middle of the results, over a sliding
  loading bar, until the results are in.

## 1.5.5 — 2026-10-01

- **Country and island names on the Radio globe**, so you can find places without
  knowing the map. Zoomed out you see the big countries; zoom in and the smaller
  ones and islands (Hawaii, the Caribbean, the Pacific) appear. Names never pile on
  top of each other, and the **Aa** button on the globe hides them.
- **Small windows work properly**: the mini player showed a blank space with a
  sideways scroll bar when you had no sounds; now it shows the "drop sounds here"
  bunny. Pads shrink to fit instead of running off the edge (two a row in the mini
  player, names never cut in half), a short window hides the mixer before squeezing
  the pads, and the Voice and Apps tabs no longer cut off on the right when narrow.
- **A tidier Settings window.** General had grown to a dozen cards, so it's split
  up: **Audio** (your mic, Who's listening, buffering), **Updates** (app updates
  and the downloader) and **Remote** (Stream Deck and scripts) are tabs of their
  own, and the hotkey beeps are on the Hotkeys tab. General keeps the window,
  tray, backup and support settings.

## 1.5.4 — 2026-09-30

- **Smoother Radio tab**: the globe is now light by default. It only draws while you
  use it, skips the stars and terrain, pins the 1,000 most-listened stations and
  stops drawing while the app is in the background, so the rest of the app no
  longer stutters. The **HD** button on the globe brings back the full, spinning
  version, and it's remembered.
- **✕ on the Apps tab works on any program**: it used to do nothing on a program
  you'd never sent. Now it takes the program off the list (it stays off, even
  while it runs) with an Undo bar, and *Forgotten programs…* brings it back.
- **Removing a sound asks first** (from a pad's menu, picked pads or the Delete
  key), and a *Recently deleted (n)* button beside Backup shows what's in the bin.
- *Remove Onion Watch…* is in Onion Watch's *More* menu instead of a row of its
  own under the Triggers tab.

## 1.5.3 — 2026-09-30

A mini player for small windows, a Recently deleted bin, and Onion Watch can be
removed.

- **Mini player**: make the window too small to use and it turns into a small
  player — what's playing, play / pause, stop, the seek bar, Live and Stop all —
  with your pads above it when there's room. Drag it bigger and the whole window
  comes back.
- **Resizing no longer flickers**: dragging the window's edge used to make parts
  of it flash in two places; now only the controls that actually need to hide or
  come back change.
- The tab bar never shows scroll arrows, and the category bar's arrows match the
  theme instead of looking like stock Windows buttons.
- **Onion Watch can be removed**: *Remove Onion Watch…* under the Triggers tab
  uninstalls the add-on after asking. Your triggers and their pictures are kept
  for when you get it again, and getting it again needs no restart.
- **Recently deleted**: a removed sound is kept for 30 days (Backup → *Recently
  deleted sounds…*) with its audio, picture and pad settings, and can be brought
  back after its Undo bar is gone. Forgetting a program on the Apps tab can be
  undone too (*Forgotten programs…*), and so can removing a custom mode. Picking a
  voice preset no longer wipes *My own mix*.
- **Controls sit next to what they control**: the Voice tab's mic meter and *Hear
  my voice* share the voice changer's on/off row, the computer voice's Voice and
  Speed come before its Start button, and Setup → *Test it* has its own *Hear what
  they hear* button.
- **The Apps tab's meters move live** instead of jumping every 1.5 seconds.
- **Themes**: dropdowns and menus are readable on every theme (they drew black on
  light ones), selected rows and ticked boxes read better, and switching theme
  recolours everything, the tray icon included.
- **Quitting always quits**: an invisible copy could be left running, so the next
  start said Onion Board was already running.

## 1.5.2 — 2026-09-30

*Who's listening* has a mode for every kind of game voice chat, and suggests the
right one for the game you're playing.

- ***Who's listening* has one mode per voice chat engine**: Discord, Vivox, Epic
  Online Services, Steam voice, Unity voice (Photon / Dissonance) and Low bandwidth
  (8 kHz), each saying which kinds of games use it. Every engine's own mic cleanup
  and voice gate were tested on 99 songs, from 808 trap to chipmunk vocals, to tune
  its mode: in every one, songs arrive within about 2 dB of playing the file
  straight in. The old *Game voice* mode is now called *Vivox*; your saved choice
  carries over.
- **The picker suggests the right mode for the game you're playing** when it can
  tell (Vivox and Unity voice games): the game's install folder is checked for its
  voice library. It only suggests; nothing switches on its own, and the game
  itself is never touched.
- **The game voice chat guide says how to choose**, and the Steam guide reminds you
  to pick *Steam voice*.
- **Livelier mascots.** When the board has no sounds, Bun begs for one in a speech
  bubble, cheers up while you drag files over him and hops for joy when clicked;
  Hoot waits the same way on the Triggers tab, and a glum Bun sits on an empty Apps
  tab.
- **Livelier pads**: a smooth hover, a press, a flash when a sound starts, and a
  breathing glow while it plays. The overlay's keys are drawn as keycaps.
- **Small fixes**: long app names end in "…" instead of being cut mid-word, "EQ off"
  is readable, and empty-state text has better contrast in the Light theme.
- **The installer is packed differently**, so virus scanners stop mistaking it for
  malware. It's a bit bigger to download.

## 1.5.1 — 2026-09-30

Songs come through game voice chat as loud as they should, bass and all. Tested on
99 songs, from 808-heavy trap to chipmunk-pitched vocals, through a model of a game
voice chat measured in a real game.

- **The *Who's listening* modes no longer turn bass-heavy songs down.** A song was
  levelled with its deepest bass counted, then the voice chat threw that bass away,
  so an 808 track reached your friends about 11 dB quieter than playing the file
  straight into the game. The Game, Discord and Steam modes now remove that bass
  themselves, give each sound back the level it took, and turn it into harmonics
  the chat keeps: every kind of song now arrives about as loud as the original,
  with the bass still there and less pumping on the kicks. Custom modes get the
  same choice (*Deep bass* in the mode editor).
- **The game voice chat guide explains push-to-talk better.** Some games' anti-cheat
  ignores keys pressed by other programs, so *Auto push-to-talk* can't open the mic
  there: hold the key yourself. And on voice activation some games send only
  speech, never music.

## 1.5.0 — 2026-09-30

The Triggers tab becomes Onion Watch.

- **The Triggers tab is now the Onion Watch add-on.** Onion Watch is the Triggers
  tab grown into its own project, and it plugs back in here: click *Get Onion
  Watch* on the tab and it's downloaded, checked and there in a moment, no
  restart. On top of what the tab did, it can watch a game's own window even while
  other windows cover it, tell two copies of a game apart, cut the picture straight
  out of the game window, and ring until you stop it (in your headphones, with a
  red Stop bar on the tab; Stop all stops it too). Your triggers and their pictures
  are kept as they were and work again as soon as it's installed. Nothing is
  downloaded until you click, and a newer Onion Watch is offered on the tab with
  the app's own update check.

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
