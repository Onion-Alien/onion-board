# Changelog

## Unreleased

- The left navigation rail blends into the window with a soft theme tint and a
  subtle divider, keeping the selected tab easy to spot.
- **Robo-Bun sets up AI voices.** While AI voices download and install, a little
  robot bunny runs off, comes back with a wrench and builds, with a moving bar and
  short steps like "Installing the voice engine" instead of pip's output. He cheers
  when it's done. If it fails, the real error still shows.
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
