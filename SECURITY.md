# Security policy

## Reporting a vulnerability

**Please don't open a public issue for security problems.**

Use GitHub's private reporting instead: go to the repository's **Security** tab →
**Report a vulnerability**. Include what you found, how to reproduce it, and which
version (it's in the title bar).

You'll get an acknowledgement within a week. Fixes ship in a normal release and
the CHANGELOG credits you unless you'd rather not be named.

## Supported versions

Only the latest release gets security fixes.

## What counts

In scope, for example:

- The Radio tab showing a station's name / country as rich text (it's
  community-edited data).
- Another local process or web page connecting to the app's loopback sockets
  (module link) without the per-launch secret.
- Anything reaching the local control API (Settings → Remote → *Remote
  control*, off by default) without its key, from another machine, or through a
  web page (e.g. DNS rebinding), or making it do more than the actions `/api/help`
  lists (`ENDPOINTS` in `soundboard/control/remote.py`).
- The phone remote's server (Onion Pocket, off by default) answering without its key,
  from outside the local network, or doing more than the actions it lists.
- The installer or `installer/install-vbcable.ps1` running something that isn't what it
  claims to be (e.g. the VB-Cable signature check being bypassable).
- Crafted audio / video files that cause code execution, not just a failed import.
- *Straight into my mic* (how sounds reach others by default; see [below](#what-straight-into-my-mic-changes-on-your-pc)):
  its effect DLL runs inside Windows' audio engine
  (`audiodg.exe`, as LOCAL SERVICE). Anything another local user or program can write
  into `%ProgramData%\OnionBoard\MicPlugin\ring2.bin` (signed-in users may write it,
  by design) that crashes the audio engine, runs code in it, or reads or writes outside
  the file is in scope; the effect takes the sizes once and checks every sample. So is
  the admin step (`--direct-mic install / uninstall`) installing any DLL but the app's
  own copy, touching any device but a mic Windows lists, or leaving a mic's effect
  settings changed after an uninstall. So is the mic helper (`obmichelper.exe`, run as
  SYSTEM) doing anything for anyone but the account that set it up, running any
  request outside its fixed list, installing any DLL but its own, or writing through
  a link someone planted. Others on
  the PC hearing or changing what goes into your mic through that file is a known part
  of the design (anyone signed in can already record and play audio).
- Anything that sends the user's data off the machine without them asking.
- With a proxy set (Settings → Connection), any request the
  app makes that goes around it, or a DNS lookup of a site's name on this PC
  (see *Through a proxy* below for what it covers).
- The proxy relay on `127.0.0.1` accepting a request without its per-launch secret.

Out of scope:

- **Modules** (`%APPDATA%\OnionBoard\modules\`) are Python code that runs with
  your user's full permissions, exactly like any program you download. A
  malicious module being malicious isn't a vulnerability in Onion Board; a
  module escaping into something the user never installed is. The same goes for
  custom voice programs (a `"command"` in `%APPDATA%\OnionBoard\voices\`, or the
  `piper.exe` there): they're programs you chose to run.
- Games' anti-cheat reacting to global hotkeys or `SendInput` (auto push-to-talk);
  see [Anti-cheat](#anti-cheat) for what the app does and doesn't touch.
- Bugs in Qt that are already fixed upstream. Tell us if the pinned PySide6 is
  behind on security releases, though — that's in scope.

## What the app does on the network

The short version, for users: [docs/PRIVACY.md](docs/PRIVACY.md). So you know what
normal looks like when auditing it:

| When | Where | Why | Switch |
|---|---|---|---|
| You paste a link into *Search sounds* on the Sounds tab | that link's site, via `yt-dlp` (only `http`/`https` links) | looks the link up (title, length); *Add as sound* / *Play once* then download its audio stream (and thumbnail, for the pad's picture) into a temp folder, which is deleted once it's imported, or when the link is cleared or the app closes. The link, channel, upload date, length and view count from that same reply are kept with the sound (and in a text file next to it); nothing extra is fetched for them | `sounds_web` |
| You press Enter in *Search sounds* (or its *Search* button) | `youtube.com` via `yt-dlp` (`music.youtube.com` with *YouTube Music* picked), and `i.ytimg.com` — or, with *SoundCloud* picked above the results, `soundcloud.com` / `api-v2.soundcloud.com` via `yt-dlp`, and `i1.sndcdn.com` — or, with *Myinstants* picked, `www.myinstants.com` directly (its search page, then the picked `.mp3` itself; yt-dlp can't fetch it) | one page of search results for what you typed (titles, channels, lengths, view counts) and their thumbnails; nothing more is fetched per result (no video page, no like or comment look-ups); no audio is downloaded until you press *Play* or *Add* on a result, which then works like a pasted link | `sounds_web` |
| You pick *Trending on Myinstants* in the *Search* button's menu | `www.myinstants.com` directly (its trending page, which sends you on to the one for your country, then the picked `.mp3` itself) | one page of its trending sound buttons (titles and their `.mp3` links); no audio is downloaded until you press *Play* or *Add* on one | `sounds_web` (Myinstants' switch) |
| You press *From a link* under *Picture* in a sound's *Edit…* window and paste a link | the link's site; for a YouTube video link, `i.ytimg.com` instead (its thumbnail, straight away); for a web page, then the server of the preview picture it names (its `og:image` / `twitter:image`, only an `http`/`https` one, never one on this PC or a file share) | gets that one picture (up to 15 MB) for the pad, or the page around it and then its preview picture. Nothing else is fetched, and nothing is sent but the request itself | `sounds_web`: each request under the switch of the site it goes to (YouTube for `youtube.com` / `i.ytimg.com`, SoundCloud, Myinstants, else *Other pasted links*) |
| You open *Free sound packs* (Sounds tab → Backup) | `raw.githubusercontent.com` | reads this project's list of free sound packs (`packs/catalog.json`: each pack's name, description, download link and SHA-256). Nothing else is sent | `sound_packs` |
| You open *Free sound packs*, the first time for each pack | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads that pack's small preview zip (a few of its sounds, cut short, with their pictures; only from this project's own `github.com/…/releases/download/` link, HTTPS only) into `%APPDATA%\OnionBoard\packs\previews\` and checks it against the SHA-256 in the list; after that it's read from there. Pressing one plays it to your headphones only. Nothing else is sent | `sound_packs` |
| You press *Add to my board* on a pack there | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads that pack's zip (only from this project's own `github.com/…/releases/download/` link, HTTPS only) into `%APPDATA%\OnionBoard\packs\` and checks it against the SHA-256 in the list; a file that doesn't match is deleted. Its sounds are then imported like a dropped backup zip | `sound_packs` |
| You open the *Store* tab, search it, change its order or press *Show more* | `onion-board-store.onion-alien.workers.dev` (this project's own server, on Cloudflare) | reads a page of the sound store's list (names, tags, vote counts). It sends a random id this install made for itself (`store_id` in the config: not tied to you, the PC or the app's other ids) so the list can show your own votes; the server keeps only a salted hash of it, and a salted hash of your address only to stop one address flooding the store | `sound_store` |
| You press ▶ or *Add* on a sound there | the same server | downloads that sound (up to 4 MB) into `%APPDATA%\OnionBoard\store\`; *Add* then imports it like a dropped file. A shared *link* has no file on the server: ▶ / *Add* hand it to the link downloader, exactly as if you had pasted it on the Sounds tab (that site, its own switch) | `sound_store` |
| You press 👍 / 👎 or report a sound there | the same server | sends your vote (or the reason picked) with the random id above, so one install gets one vote per sound. The server logs each vote, report and share with its time and the two salted hashes (never the id or address itself), to spot abuse, and deletes those lines after 90 days. A separate security log keeps every refused call and every vote, report and share for 30 days: when, what was asked and answered, the same two salted hashes, the browser or app name it sent, the country and network name Cloudflare gives for the address, and for a refused upload its file name and first 16 bytes | `sound_store` |
| You press *Share* in the *Share a sound* window (or *Share to the store* on a downloaded sound's right-click menu) | the same server | uploads the file you picked, the name and tags you typed and that you ticked the agreement (it's yours, CC0); or, for *A link*, only the link (to a video or sound site), name and tags. It waits to be checked before anyone else sees it | `sound_store` |
| A YouTube look-up or download whose player challenge yt-dlp has to solve | nothing: a JavaScript engine on this PC (Deno, Node or Bun when one is installed at a version yt-dlp supports, else the app's own QuickJS, `qjs.exe`) | yt-dlp hands it the YouTube player script it already downloaded and reads back the answer. The engine is started as a local program with a script file only; it makes no connections of its own | `sounds_web` (it only runs as part of a YouTube request) |
| You click *Connect Twitch* (Settings → Remote; nothing until you do), and from then on while the app runs and you're connected | `id.twitch.tv`, `api.twitch.tv`, `eventsub.wss.twitch.tv` | signing in uses Twitch's device code: you say yes on twitch.tv, so your password never goes through the app; Twitch hands back a token for what the card needs (channel point rewards and redemptions, bits, subs, follows, reading chat and posting a chat command's reply), stored in `config.json`, never exported with a backup or logged. While connected the app keeps one socket open to Twitch's event service (EventSub) for your channel's redemptions, cheers, follows, subs, raids and chat lines, and asks Twitch's API who you are, your rewards' names, to send those events, and to post a reply in your chat. Your channel's name is never sent anywhere else unless you tick the card's *Let the Onion Board developer see this channel's name* (see [the usage count](#the-anonymous-usage-count-count-me-in)). *Disconnect* asks Twitch to revoke the token and forgets it. Its own switch in Settings > Privacy & security; Offline mode, the proxy and Tor apply | `twitch` |
| When you click *Update now* / *Reset downloader* (Settings → Updates) or *Update downloader* (on a link that failed to download), or — only if you tick *Update automatically*, off by default — once a day and after an *Add as sound* that failed | `raw.githubusercontent.com`, `files.pythonhosted.org` | reads this project's list of approved `yt-dlp` versions (`pins/yt-dlp.json`: each version with the address and SHA-256 of its `yt-dlp` and `yt-dlp-ejs` wheels). A version gets on it through a reviewed pull request, opened by a weekly job once the wheels' PyPI attestations show they were built and uploaded by yt-dlp's own GitHub release workflows. The app takes the newest listed version that runs on its Python, has been on PyPI for at least 3 days and is newer than what it has (never older than the built-in copy); if there is one, it downloads those two wheels from PyPI's file server, checks each against the list's SHA-256 (not PyPI's), and unpacks them into `%APPDATA%\OnionBoard\yt-dlp\`. That code then runs inside the app, like the bundled copy it replaces. `pypi.org` itself isn't asked | `ytdlp_update` |
| You click *Force update* (Settings → Updates, yt-dlp) and then *Install anyway* in its warning | `pypi.org`, `files.pythonhosted.org` | for when downloads broke and no approved version fixes them yet: asks PyPI for its newest final `yt-dlp` release that runs on the app's Python (not on the approved list, not 3 days old), downloads its wheel and the `yt-dlp-ejs` wheel it pins, checks each against PyPI's own SHA-256 only, and unpacks them into `%APPDATA%\OnionBoard\yt-dlp\`. Never older than the copy in use. *Reinstall* goes back to an approved version | `ytdlp_update` |
| Unless you untick *Check for updates* (Settings → Updates): as the app starts (installed app with *Install updates by themselves* ticked) or 45 s after start, then about every hour; or when you click *Check now* | `api.github.com` | asks for this project's latest release (version number, release page, the first lines of its notes, and its installer's download link and SHA-256). If it isn't an urgent fix, it also asks for the last 10 releases, to see whether one you skipped was urgent. The automatic check offers a release once it's been out 30 minutes (an urgent fix right away). With *Install updates by themselves* (Settings → Updates; **on by default** in the installed app) a newer version is downloaded and installed as the app starts, or while it runs when no sound is playing, the same checked way as *Update now* below; untick it and a newer version is only announced, and nothing is downloaded until you click *Update now* | `app_update` |
| You click *Update now* on a newer version, or *Install updates by themselves* (on by default) installs it (installed app only; a copy running from source only opens the release page) | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads that release's `OnionBoardSetup.exe` (only from this project's own `github.com/…/releases/download/` link, HTTPS only) into `%APPDATA%\OnionBoard\updates\` and checks it against the SHA-256 GitHub lists for it; a file that doesn't match is deleted. When you click *Restart now* the app closes and runs it silently over the installed copy (never the virtual cable, FFmpeg or live-voice extras), then the installer opens the app again. Downloaded installers are removed on the next start | `app_update` |
| Unless you untick *Count me in* (the installer, or Settings → Privacy & security): once a day, once on *Update now*, and on closing the app if anything waits for the next count (installed app only) | `onionalien.goatcounter.com` (GoatCounter) | the anonymous usage count: the version, a random ID made on this PC, which tabs and features were used and problem counts, as fixed names and buckets. Exactly what, when and what never: [The anonymous usage count](#the-anonymous-usage-count-count-me-in) below | `usage_stats` |
| You open the Radio tab (or start the app with Radio as the last tab you used: the app reopens it), or a phone remote / the control API asks for the popular stations or searches them | `*.api.radio-browser.info` | the station directory: the ~3000 most-listened stations with a location (cached for a day), your searches, and — only if you tick *Share play counts* (Settings → Privacy & security, off by default) — a "click" when you start a station (Radio Browser's own popularity count). Nothing else about you is sent. The map's country outlines ship with the app and load from its own folder: no CDN is contacted | `radio` |
| You play a radio station | that station's stream server (the address listed for it in the directory; its `https` address when the directory lists one, so the network in between can't see which station) | the stream itself, decoded by Qt Multimedia (FFmpeg) and played through the app's audio engine | `radio` |
| You speak a line with a custom voice server you added (Voice tab → More options → *Custom voices*; a `.json` with a `"url"` in `%APPDATA%\OnionBoard\voices\`) | the address you gave it (normally a TTS server on your own PC, e.g. `127.0.0.1`) | sends the line's text (and the voice / model / API key you entered) and gets the spoken audio back. Nothing is sent until you add one | `voice_servers` |
| You install the app and FFmpeg isn't on this PC yet (always, no box, but the installer's options page says so first; not in Offline mode or on the app's own updates) | `winget` (Microsoft's package source, then the FFmpeg build it points to) | installs `Gyan.FFmpeg.Essentials` | — (the installer) |
| FFmpeg is missing or won't start when the app starts (checked behind the loading screen by running `ffmpeg -version` on this PC; the download starts once the window is up and shows on a bar with *Stop*), and not in Offline mode, Low data mode, with this switch off or after *Don't ask again*; or you press *Fix it*, *Get FFmpeg* or *Reinstall* (the bar, or Settings → Data & quality; pressing it while this switch is off switches it back on) | first `winget` (Microsoft's package source, then the FFmpeg build it points to; it goes direct, not through the app's proxy or Tor, so it's skipped when Connection is set to either); if that's missing or doesn't work, `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`), then `www.gyan.dev` (the FFmpeg builder's own site) | winget installs `Gyan.FFmpeg.Essentials` (about 100 MB): a plain install, then `--force`, then `winget uninstall` and a fresh install while it still won't start. Otherwise the app downloads a pinned essentials build's zip (`ffmpeg-9.0.2-essentials_build.zip`, about 115 MB) through the app's connection setting, up to 3 tries on each site, checks it against the SHA-256 pinned in `soundboard/online/ffmpegget.py` (a file that doesn't match is deleted, never unpacked) and keeps only `ffmpeg.exe`, `ffprobe.exe` and the licence, in `%APPDATA%\OnionBoard\ffmpeg\bin` | `ffmpeg_download` |
| You install the virtual cable (only if you choose to: sounds go straight into your mic by default, so its box in the installer is unticked; also the setup guide's and Setup tab's *Install the free virtual cable* button) | `vb-audio.com` | downloads VB-Cable; the installer's signature is checked before it runs | `setup_downloads` (not the installer's box) |
| You press *Get Tor* / *Update Tor* (Settings → Connection), or tick *Private connection (Tor)* in the installer (unticked by default) | `dist.torproject.org`, or `archive.torproject.org` once dist no longer has this version (through your proxy if *Connection* is set to one; when updating, through the Tor that's already there if Tor is picked) | downloads the Tor Project's Tor Expert Bundle for Windows (about 22 MB), checks it against the SHA-256 pinned in `soundboard/online/torget.py` (taken from the release's GPG-signed checksum list; a download that doesn't match is thrown away) and unpacks only `tor.exe`, `lyrebird.exe`, `pt_config.json` and their licence texts into `%APPDATA%\OnionBoard\tor\bin\`. The app doesn't ship Tor. Where Tor is blocked, this download often is too | `tor_download` |
| Install from source (`scripts/install.ps1`) | PyPI, and `winget` if you accept installing Python | the app's `requirements.txt` | — |
| You install a module (its Install button, its `install.bat`, or the installer's *live voice* box) | PyPI, via `pip`, plus whatever the module fetches | that module's `requirements.txt`; *live-voice* downloads a Whisper speech model from Hugging Face (via `faster-whisper`), and picking a different model in the Voice tab downloads that one the first time it starts. Each time live voice starts, `faster-whisper` also asks `huggingface.co` whether the model has changed (no audio or text is sent) | `addons` (pip); `voices` (the speech model) |
| You install or repair live voice or AI voices (Voice tab, or the installer's *live voice* box) and this PC has no Python 3.12 or 3.13 of its own (or the one it was set up with is gone) | `api.nuget.org` (python.org's own `python` package) | downloads Python 3.12.10 (about 15 MB) through the app's connection setting, checks it against the SHA-256 pinned in `soundboard/online/pyget.py` (a file that doesn't match is deleted, never unpacked) and unpacks it into that add-on's own `.python` folder. Nothing is installed on the PC; it goes when the add-on does | `addons` |
| You click *Add Onion Watch to this tab* on the Triggers tab | `api.github.com` | asks for the Onion Watch project's latest release (version number, release page, the first lines of its notes, and its add-on zip's download link and SHA-256) | `addons` |
| Right after that, or when you click *Update* on the Triggers tab | `github.com` → GitHub's release download server (`release-assets.githubusercontent.com`) | downloads `OnionWatch-module.zip` (only from `github.com/Onion-Alien/onion-watch/releases/download/`, HTTPS only) into `%APPDATA%\OnionBoard\updates\`, checks it against the SHA-256 GitHub lists for it, and unpacks it into `%APPDATA%\OnionBoard\modules\onion-watch\` only if every file stays inside that folder. That code then runs inside the app, like any module. The zip is deleted afterwards | `addons` |
| Once Onion Watch is installed, with the update check above (only while *Check for updates* is ticked) | `api.github.com` | asks for Onion Watch's latest release too. A newer one is only offered on the Triggers tab; nothing is downloaded until you click *Update* | `addons` |
| You pick a language under *Speak in* (Voice tab) and press its *Download* button | `argos-net.com` | downloads that language's translation model (65–196 MB) once, checks it against the SHA-256 in its add-on's `module.json`, and unpacks only the model files into `%APPDATA%\OnionBoard\translation\`. Translating what you say then happens on your PC | `voices` |
| You press *Install the … voice* under *Speak in* (Voice tab) and say Yes to Windows' permission prompt | Windows Update (Microsoft) | Windows itself (`Add-WindowsCapability`, run elevated) downloads and installs its free text-to-speech voice for that language, the same as Settings → Speech → Add voices. The app only starts it and reads back whether it worked | `voices` |
| You press *Support Onion Board* (Settings → About) | `github.com`, in your own web browser | opens this project's page at its Support section | — (your browser) |
| You press *Report on GitHub* in the crash window | `github.com`, in your own web browser | opens a new-issue page; the report is only put on your clipboard, and nothing is posted unless you paste it and submit | — (your browser) |
| You press *Join the Discord* (Settings → About, the tray icon's menu, the *What's new* window, or the installer's last page), *Send feedback*, *Report a problem* or *Report a security issue* (Settings → About), a *Report it* link beside an error message, *Yes* to "Would you tell us why?" after uninstalling, or *Website* / *Source code* / *Licenses* (Settings → About) | `discord.gg` (the Onion Board Discord server), `tally.so` (the no-account feedback form), `github.com` or `onionalien.com`, in your own web browser | opens that page with the app's version (and, for *Report it*, the error's text) filled in; the app sends nothing itself, and nothing is posted unless you submit it there | — (your browser) |
| While a module runs (e.g. live voice) | `127.0.0.1` only | module link, guarded by a random per-launch secret | — (this PC) |
| You turn on *Remote control* (Settings → Remote; off by default) | listens on `127.0.0.1` only (port 7474 unless you change it) | lets a Stream Deck, AutoHotkey or a script on this PC use the actions `/api/help` lists: list, play, queue, stop and pause sounds, switch category, the volume, mute you (Live / Muted) or your mic, the voice changer and a typed line in the computer voice, *Hear what they hear*, the instant replay, live speed / pitch / effects, who's listening, and the radio. Never files, other settings or anything outside the app. Every request needs the key shown in Settings. Unlike the sockets above the key survives restarts (a Stream Deck button has to keep working), so it's stored in `config.json`; it's never exported with a backup or logged, and *New key* replaces it. Requests for any other `Host` are refused and no CORS headers are sent, so web pages can't use it. The Onion Board Stream Deck plugin (`streamdeck/`) reads the port and key from `config.json` on this PC (never changes it) and only ever connects to `127.0.0.1` | — (this PC) |
| You click *Get AI voices* (Voice tab) | `api.github.com`, then `github.com` → GitHub's release download server | asks for this project's `ai-voices` release (its title's version, its notes, and its add-on zip's download link and SHA-256), then downloads `AiVoices-module.zip` (about 40 MB: the add-on's code and its voice model; only from `github.com/Onion-Alien/onion-board/releases/download/`, HTTPS only) into `%APPDATA%\OnionBoard\updates\`, checks it against the SHA-256 GitHub lists for it and unpacks it into `%APPDATA%\OnionBoard\modules\ai-voices\` only if every file stays inside that folder. Its install then fetches `onnxruntime` and `numpy` from PyPI (the module row above). The zip is deleted afterwards. While an AI voice runs nothing goes online: your mic goes to its helper over `127.0.0.1` and back | `addons` |
| The AI voices add-on finds its voice model missing (its install step, `helper.py --download`) | the address in its `voices.json` (`model.url`, HTTPS only) | downloads the model zip and keeps it only if it matches the SHA-256 written there. Unused when the add-on came with its model (the normal case) | `addons` |
| You click *Get Onion Pocket* (Settings → Remote) | `api.github.com`, then `github.com` → GitHub's release download server | the same as *Add Onion Watch to this tab* above, for the Onion Pocket project: its latest release, then `OnionPocket-module.zip` (only from `github.com/Onion-Alien/onion-pocket/releases/download/`, HTTPS only), checked against the SHA-256 GitHub lists for it and unpacked into `%APPDATA%\OnionBoard\modules\onion-pocket\` only if every file stays inside that folder. The zip is deleted afterwards | `addons` |
| You open Settings → Remote with Onion Pocket installed (at most once an hour), and *Update Onion Pocket to …* on its card when you click it | `api.github.com`; on the click, `github.com` → GitHub's release download server | the same release lookup as *Get Onion Pocket*: is its latest release newer than the installed one? Nothing else is sent, and nothing is downloaded until you click. Then the same checked download as above; the running copy is stopped and the new one started with your settings and key unchanged. If anything fails the old copy keeps running | `addons` |
| You install the Onion Pocket add-on and turn it on (Settings → Remote → *Let phones on this Wi-Fi use it*; off by default) | listens on this PC's address on the local network only (port 7475 unless you change it); answers only local-network addresses (private / link-local), and never listens on a network Windows calls Public (a café's or a hotel's Wi-Fi), even if Windows Firewall would let it, nor on one whose kind Windows can't say (taken as Public, never as home): it checks when it starts and every 30 seconds after (an unreadable answer stops it the second time in a row) | serves the phone page and lets a phone on your Wi-Fi list, play, stop and pause sounds, change the volume and category, and mute you; never the mic, the voice changer or the replay. It has its own key, separate from *Remote control*'s, given to the phone in the QR code's `#fragment` (browsers never send that part); every request needs it, and an address that gets it wrong 5 times in a row is ignored for a minute. Onion Pocket 0.2.2 and newer never send the key itself: each request carries a one-time HMAC-SHA256 signature made with it (over the time, a random nonce and the request), taken once and only within 5 minutes of this PC's clock. Stored in `config.json`, never exported with a backup or logged; *Forget phones* replaces it. **Plain HTTP**: someone else on the same network who can read its traffic sees only one-time signatures (Onion Pocket 0.2.2+; older versions send the key itself), but someone who can change that traffic on its way could still take the key, so use it at home, not on public Wi-Fi. The page loads nothing from anywhere else (hash-only Content-Security-Policy, `connect-src 'self'`). Turning it on (or *Let it through Windows Firewall*) adds one inbound rule after Windows' admin prompt, which Onion Board itself asks for (`OnionBoard.exe --firewall-rule`, so the prompt names it): that port and this program, TCP, Private networks, local subnet only | — (this network) |
| The mic effect's set-up, repair or removal (its admin step) while SteelSeries Sonar is running | `127.0.0.1` only: SteelSeries GG's own local server (its address read from GG's `coreProps.json`; any other address is refused), then Sonar's | reads which devices Sonar's channels and mic use before the step restarts Windows' audio, and sets the same ones again after it (the restart drops them, and Sonar's mic would send only silence). Nothing else is read or sent | — (this PC) |
| While the app runs with SteelSeries Sonar's mic as its mic | `127.0.0.1` only, the same two servers as the row above | every 30 s while the mic works: which devices Sonar's channels and mic use; when the mic drops out and comes back within a minute (Windows' audio restarted, which makes Sonar move them), sets the same ones again if Sonar moved any. Nothing else is read or sent | — (this PC) |
| Always | a local named pipe (`OnionBoard.App`) | single instance: a second launch asks the first to come to the front. It only accepts that one request | — (this PC) |

To see it happen, Settings → Connection → *Network activity* lists every
connection the app makes or refuses while it runs (`soundboard/online/netlog.py`):
server, feature, why (what you did that caused it, or the app's own timer), route,
result, bytes, and the HTTP request line, answer and TLS
version where the app can read them (inside a radio or yt-dlp `https` tunnel it
can't). The list is kept in memory only (at most 1000 entries) unless you tick
*Keep a history between starts* there (or the installer's `/KEEPNETLOG=1`; off by
default): then each connection is also saved to
`%APPDATA%\OnionBoard\network-activity.jsonl` as it ends and listed again on the
next start (Clear empties it; unticking deletes it). The file keeps more than the
list shows, for *Totals*: up to about 10 MB (at 5 MB it moves to `.old`, and the
`.old` before it goes). It's never written to the
log or sent anywhere, and it never holds proxy passwords, the relay's secret, request
headers or bodies; query values whose names look like keys or tokens are masked.
`tor.exe`'s own connections to the Tor network and everything under *Not covered*
below aren't in it.

### The anonymous usage count (*Count me in*)

On for new installs, off for copies installed before it existed; untick it in the
installer or Settings → Privacy & security (feature switch `usage_stats`). It only
runs in the installed app: a copy running from source never sends it.

**When:** once a day (the first start on a new day on your PC's clock, or a whole day
since the last one), 60 s after start, and checked every 6 hours for an app left
running; also once when you click *Update now*. And when you close the app, if
anything waits for the next count (tabs opened and features used since the last one,
one-off and problem events), those go then, so a last day of use isn't lost: the same
names the next count would send, never the daily count itself, and the close waits
2 s at most (if it can't send, they wait for the next count as before).

**Where and how:** one HTTPS POST to `onionalien.goatcounter.com/api/v0/count`
(GoatCounter, a privacy-friendly counter; the website counts its visits and downloads
there too, without cookies and without your IP address). The key in
`soundboard/core/usage.py` can only add counts, not read them.

**Always in it:** the path `/app/<version>`, a random ID made on this PC (`stats_id` in
`config.json`) and a short tag made from it (`u-` and 12 letters of its hash, as the
count's referrer). They let one person count once and show how each person uses the
app over time (which tabs, which versions, whether they come back, where they stop),
only to fix errors and see which features need work. The ID isn't tied to your name,
account or anything else about you.

**Once-only events:**

- The very first send: `first-start` (`first-start/heard-<where>` if you picked where you
  heard about the app on the installer's last page: YouTube, Reddit, Google, a friend,
  or a short name you typed under Other; a typed answer that looks like an email
  address, a link or a number is dropped, not sent).
- *Update now* sends `update-now/<from>-to-<to>`, and the first start of a new version
  (however it was installed) `updated/<from>-to-<to>`, so an update that didn't finish
  can be told apart.
- A new install's first steps, once each, when they happen: `step/added-sound`,
  `step/played-sound`, `step/sent-to-others` (a copy counted before these existed never
  sends them), and switching on a tab a new install starts without:
  `step/added-radio-tab`, `step/added-apps-tab`, `step/added-triggers-tab`.
- Events that couldn't be sent yet wait in `config.json` (`stats_pending`) for the next
  send.

**The daily count also says, each as a bucket or a name from a fixed list:**

- the tabs you opened since the last one (`tab/sounds`, `tab/radio`…: names only,
  nothing about what you did there);
- how long ago it was installed (`age/day-1`, `age/days-2-7`, `age/days-8-30`,
  `age/days-31-plus`);
- where your sounds go (`route/mic`, `route/cable`, `route/device`, `route/off`);
- how many sounds your board has and how many you played since the last one
  (`sounds/…` and `played/…`: `0`, `1-10`, `11-50` or `51-plus`);
- how long the app was open since the last one (`open/under-15m`, `15m-1h`, `1-3h`,
  `3-8h` or `8h-plus`; added up every 5 minutes while it runs, never the times of day,
  and a sleeping PC doesn't count);
- how many sounds you fetched from a link or a web search (`downloads/0`, `1`, `2-5`,
  `6-20` or `21-plus`) and how many times you started it (`launches/0`, `1`, `2-5` or
  `6-plus`) since then;
- the system (`os/win11`, `os/win10`, `os/win-older`, `os/linux` or `os/other`: never
  the exact version) and the app's theme (`theme/dark`: a built-in theme's name, else
  `other`);
- the language the app is showing and whether you picked it in Settings
  (`lang/de/picked`; `lang/en/default` when you haven't picked one) and Windows' own
  display language, as one of the languages the app comes in (`lang-windows/de`, `en`
  when none fits): language codes only, never your region or other locale settings;
- how many of Settings > Achievements you've earned (`achievements/0`, `1-2`, `3-5`,
  `6-10`, `11-20` or `21-plus`) and their score (`ach-score/0`, `1-50`, `51-150`,
  `151-400`, `401-1000`, `1001-2000` or `2001-plus`);
- **which features you used or have set up since then**, as `used/<name>`: only the
  names in `FEATURES` in `soundboard/core/usage.py`, each a yes or no for the day, never how
  many times or what you did with them. Some examples by area:
  - tabs: `used/more-tabs-opened`, `used/more-tabs-added-radio`, `used/more-tabs-closed`,
    a tab hidden from its right-click menu (`used/tab-hidden-voice`), Ctrl+1 to 9 or
    Ctrl+Tab (`used/tab-keys`);
  - the tabs the first start began with, as one of a few names (`used/use-normal`: no
    extra tabs, `use-streamer`: Apps, `use-games`: Triggers, `use-all`: Radio, Apps and
    Triggers, `use-custom`: any other mix, or `use-skipped` when the guide was closed
    before its last step), the setup guide closed on a step, its send step skipped, or
    finished with or without your sounds going out (`used/setup-closed-mic`,
    `setup-closed-headphones` from older versions, `setup-closed-send`,
    `setup-closed-last`, `setup-skipped-send`, `setup-finished`,
    `setup-finished-not-sending`), its *Set up Discord* ticked (`used/setup-discord`),
    the Setup tab's *Step-by-step guide* (`used/setup-guide-opened`);
  - Bun's first-run tour of the empty board shown, searched from, a first sound added
    (`tour-files` in the version for Offline mode), put off, or ended by an error
    (`used/tour-shown`, `tour-searched`, `tour-added`, `tour-files`, `tour-skipped`,
    `tour-failed`; `tour-ignored` from
    older versions; never what was searched);
  - a tab's quick how-to the first time it's opened, shown, done, put off or ended by
    an error (`used/tour-radio-shown`, `tour-radio-done`, `tour-radio-skipped`,
    `tour-radio-failed`, the same for
    `apps`, `triggers`, `voice` and `store`), and two put off quickly, which switches
    the rest off (`used/tours-quit`);
  - sounds from the web: the site (`used/dl-youtube`, `dl-tiktok`, `dl-soundcloud`,
    `dl-instagram`, `dl-x`, `dl-reddit`, `dl-twitch`, `dl-myinstants` or `dl-other`), a
    pasted link or a search pick (`used/dl-link`, `dl-search`), *Add as sound* or *Play
    once* (`used/dl-add`, `dl-play`), the download queue (`used/dl-queue`), a pick
    already in your Sounds (`used/dl-already-have`), the sites a download failed on
    (`used/dl-failed-youtube`…), the download bar's Cancel, Retry and one-line view
    (`used/dl-cancel`, `dl-retry`, `dl-bar-small`), *Show more* under search results
    (`used/search-show-more`), *Trending on Myinstants* opened (`used/search-trending`), and a downloaded sound's *Open on…*, *Copy link*,
    *Details* and its info deleted (`used/source-open`, `source-copy-link`,
    `source-details`, `source-deleted`): never the link, its title or what you searched;
  - FFmpeg: *Get FFmpeg* clicked or failed, got by itself or that failing, a file that
    needed it, a copy that won't start and one working again after a failure
    (`used/get-ffmpeg`, `get-ffmpeg-failed`, `get-ffmpeg-auto`, `get-ffmpeg-auto-failed`,
    `needs-ffmpeg`, `ffmpeg-broken`, `ffmpeg-recovered`; a yes/no marker stays locally
    until it works);
  - the mic effect: put on by a click, put back by itself or updated, No at Windows'
    admin prompt, a set-up or fix-by-itself that failed, not working when its wait ran
    out, Windows having taken it off (`used/mic-effect-on`, `mic-effect-fixed`,
    `mic-effect-updated`, `mic-effect-said-no`, `mic-effect-failed`,
    `mic-effect-fix-failed`, `mic-effect-no-load`, `mic-effect-taken-off`), why it
    wasn't working when the wait ran out as one word (`mic-effect-no-load-<why>`:
    `off-route`, `wiped`, `not-on`, `no-stream`, `not-running`), and why a
    set-up or fix failed as one word (`mic-effect-failed-<why>` /
    `mic-effect-fix-failed-<why>`: `unanswered` (the admin prompt left open),
    `no-start`, `stuck`, `silent`, `no-helper`, `no-mic`, `no-mic-off` (unplugged or
    switched off), `no-mic-unsure` (two mics with names alike), `no-mic-gone` (not known
    to Windows), `no-effect`, the admin step's
    exit code as `code-1` to `code-6`, `code-8` (the effect didn't start on the mic) and
    `code-9` (a mic stopped opening), or `code-other`), and for exit code 1 which part
    of the admin step stopped and what Windows said, as words read from its log
    (`mic-effect-code-1-at-<part>`: `register`, `mic-settings`, `ring`, `files`, `audio`,
    `rights`, `other`; `mic-effect-code-1-<what>`: `denied`, `in-use`, `missing`,
    `other`, and Windows' error number as `err-2`, `err-3`, `err-5`, `err-32`, `err-33`,
    `err-87`, `err-1224`, `err-1314`, `err-other` or `err-none`), and for exit code 6
    which of Windows' audio services wouldn't stop (`mic-effect-code-6-<which>`:
    `audio`, `builder`, `both`, `other`): never the message or the mic's name; Settings' *Audio recovery* (`used/recovery-repair`, `recovery-remove`…, `recovery-said-no` for No to Windows'
    prompt, and `recovery-failed` with its reason word: `recovery-failed-code-8`,
    `-unverified`, `-leftovers`, `-not-removed`, `-error`…; never the message);
  - Onion Board's own update cancelled, failing to download or to start, its *Copy
    error*, *Later*, one that didn't finish, one installing itself as the app started
    (`used/update-cancelled`, `update-download-failed`, `update-install-failed`,
    `update-copy-error`, `update-later`, `update-didnt-finish`, `update-auto`), the version clicked for What's new
    (`used/whats-new`), a restore point saved before an update and one put back
    (`used/restore-point-update`, `restore-point-used`);
  - add-ons: one set up, failing to (and at which step, from a fixed list:
    `addon-failed-live-voice-pip`, `-download`, `-timeout`…; never the error itself),
    repaired, a Python got for it or that failing
    (`used/addon-installed-ai-voices`, `addon-installed-live-voice`, `addon-failed-…`,
    `addon-repaired`, `addon-got-python`, `addon-python-failed`; another add-on is
    `other`); the Triggers tab's *Add Onion Watch* window shown, Add clicked or closed
    (`used/watch-prompt-shown`, `watch-prompt-get`, `watch-prompt-closed`) and which
    kinds of trigger and options are set up and which of its buttons were used
    (`used/triggers-mode-colour`, `used/triggers-pack-import`…: never the triggers,
    pictures or windows themselves);
  - the rest of the app: the Voice tab's tabs and *Speak in* (`used/voice-tab-fx`,
    `voice-tab-ai`, `voice-tab-speak`, `voice-tab-addons`, `translate-on`),
    `used/voice-changer`, `used/youtube`, a radio station played or one that wouldn't
    play and the station list not loading (`used/radio-played`, `radio-failed`,
    `radio-list-down`: never which station), the Apps tab's cards or sections dragged
    and categories added, renamed or deleted (`used/apps-reorder`,
    `apps-category-added`…), Settings' search used and one that found nothing
    (`used/settings-search`, `settings-search-nothing`: never what was typed), the mini
    player's mic switch (`used/mini-mic-mute`), a pad's Effects tab and a picture from a
    file or a link (`used/pad-effects`, `pad-picture-file`, `pad-picture-link`), Edit
    sound opened, saved (`edit-opened`, `edit-saved`, `edit-advanced-saved`, `edit-copy`),
    its summary's × or a preset used (`edit-summary-off`, `edit-preset`) and which of its
    settings a save changed, by name only (`edit-name`, `edit-hotkey`, `edit-trim`,
    `edit-speed`, `edit-knobs`, `edit-eq`... the list in `usagenames.EDIT_SETTINGS`), *On
    Air* switched off or on and a line of its card clicked (`used/on-air-off`,
    `on-air-on`, `on-air-line`), a file import stopped or one that skipped files
    (`used/import-stopped`, `import-skipped`), *Pause*, *Stop all* and the taskbar
    preview's buttons (`used/pause`, `stop-all`, `taskbar-buttons`), the pop-up saying
    unticking *Others hear it* can't mute your mic yet and its *Set it up*
    (`used/mute-warning-shown`, `mute-warning-setup`);
  - voices: the voice changer's groups, a voice starred, *Make it yours*, *Randomize*,
    *Save as a voice* and a share code copied or imported (`used/voice-group`,
    `voice-favorite`, `voice-tweak`, `voice-random`, `voice-saved`, `voice-code-shared`,
    `voice-code-imported`), and AI voices switched on, a group picked, a voice starred,
    *Hear it* and one of your own made (`used/ai-voice`, `ai-voice-group`,
    `ai-voice-favorite`, `ai-voice-hear`, `ai-voice-made`): never which voice, its name
    or its code;
  - *Free packs* opened, a sample heard and which built-in pack was added
    (`used/packs-opened`, `pack-heard`, `pack-added-streamer`, `-esports`, `-general`, `-podcast`,
    `-halloween`, `-gm-starter`, or `-other` for a newer one); a colour from the colour
    wheel (`used/custom-colour`: never the colour); Settings' *Show advanced* and which
    of its pages were looked at (`used/settings-advanced`, `settings-page-audio`,
    `settings-page-privacy`…); yt-dlp's *Update now*, *Reinstall*, *Force update* and
    one failing (`used/ytdlp-update`, `ytdlp-reinstall`, `ytdlp-force`, `ytdlp-failed`:
    never the error); the mic card asking whether your headset is plugged in or on
    (`used/mic-unplugged`, `mic-silent`, `mic-silent-after-setup`: never the mic's
    name); how the setup guide's mic test went when its step was left (`used/mic-test-heard`,
    `mic-test-silent`, `mic-test-no-open`, `mic-test-no-mic`, or `mic-test-blocked` when
    Windows' microphone privacy switch keeps apps off it: never the mic's name); a sound played at 0% Sounds volume and its *Set to 100%*
    (`used/sound-vol-0`, `sound-vol-0-fixed`); a hotkey that was refused
    (`used/hotkey-refused`: never which key); a Live controls setup picked for sounds,
    the radio or programs, one that speaks in another language, *Not now* on its "this
    may take a while" question, and one cancelled while it got ready
    (`used/live-setup-sounds`, `live-setup-radio`, `live-setup-apps`,
    `live-setup-language`, `live-setup-said-no`, `live-setup-cancel`: never the
    setup's name or the language); a Voice tab setup
    saved or renamed (`used/voice-setup-saved`, `voice-setup-renamed`); the *Up next*
    list opened and cleared, a row played now or dragged (`used/upnext-opened`,
    `upnext-cleared`, `upnext-play-now`, `upnext-reordered`); the Live switch's
    "muted a long time" ring shown (`used/muted-ring`); the tray's Voice changer menu
    used (`used/tray-voice-toggle`, `tray-voice-pick`: never which voice); *What's new*
    shown after an update and its Settings button (`used/whats-new-shown`,
    `whats-new-page`); which of Bun's games opened (`used/egg-game-pong`, `-dodge`,
    `-homerun`, `-whack`, `-other`); the Store tab's *New* or *Trending* order and a category
    picked (`used/store-sort-new`, `store-sort-trending`, `store-category`: never which
    category);
    a My setups share code copied (`used/setup-code-shared`: never the setup); the
    control API or a phone remote add-on answering a request (`used/remote-used-api`,
    `remote-used-phone`: never what it asked); a control API chat command or alert
    carried out (`used/api-chat-command`, `api-alert`, `api-alert-donation`: never the
    viewer's name, the message or the amount); a rare loading screen (`used/splash-gold`,
    `splash-ice`, `splash-galaxy`, `splash-rainbow`), Bun or Hoot clicked into talking
    (`bun-talk`, `hoot-talk`); the note that hotkeys can't reach a game run as admin and
    its *Restart as admin* (`admin-game`, `admin-restart`: never the game); the red
    "didn't work" card's *Try again* and *Report a problem* (`oops-retry`,
    `oops-report`); the Community tab's "store's down" or "down for maintenance" page and
    a web search's site being down (`store-down`, `store-maintenance`,
    `search-site-down`); the setup guide's "almost done" note, the virtual cable's "only
    if you need it" box and its mic button (`setup-wait-note`, `cable-confirm`,
    `cable-confirm-mic`); the Voice tab saying no mic is open, a voice bar chip's close
    button, a background sound heard before adding it, the mini player's *Full board*
    (`voice-no-mic`, `voice-chip-off`, `voice-background-hear`, `mini-full-board`); the
    Voice tab's *Voices* switch and a voice bar chip clicked on or off (`voices-master`,
    `voice-chip-toggle`); a
    deleted category's *Undo*, and the "you're muted" note on a sound and its *Go live*
    (`category-undo`, `muted-note`, `muted-go-live`: never which category or sound);
    *Live controls* opened and something changed in it, on the Sounds tab, the radio
    or the programs (`used/live-opened-sounds`, `live-changed-radio`…), which of its
    controls or presets (`used/live-speed`, `live-pitch`, `live-keep-pitch`,
    `live-redline`, `live-reset`, `live-fx-bass`, `live-fx-reverb`…,
    `live-preset-canyon`…: never the values); an achievement earned, by its name in the
    fixed list (`used/ach-first-blood`, `ach-golden-bun`…) and the page's filters used
    (`used/achievements-filter`); Connect Twitch clicked or failing, and a chat line or
    another event coming in from Twitch (`used/twitch-login`, `twitch-login-failed`,
    `twitch-chat`, `twitch-event`: never the channel, viewer or message), its guide and
    *Copy AI prompt* (`twitch-guide`, `twitch-prompt-copied`); the Lite mode hint on a
    slower PC and its *Turn on* (`lite-suggested`, `lite-suggested-on`); a Voice tab
    recording or an Apps tab saved clip played, sent through the mic, added to Sounds,
    copied or deleted (`used/voice-rec-play`, `voice-rec-mic`, `saved-clip-add`…: never
    the recording); a voice searched for (`used/voice-search`: never the words); the
    Stream Deck plugin answered (`remote-stream-deck`); *Play next* on a Community card
    (`store-play-next`); *Reset effects* in Edit sound (`pad-effects-reset`); the app
    started again by Windows after it crashed or hung (`crash-restarted`); the onion on
    Settings > About poked, eating the window, or given back early (`egg-onion-poked`,
    `egg-onion-eaten`, `egg-onion-please`);
  - and every day they're set: *Remember where it came from* off, own Apps categories,
    the side menu kept shut, a proxy, Tor or Offline mode, the playing sound's picture
    behind the board, the mic helper set up, and any sound set to play other than one at
    a time (`used/source-off`, `apps-own-categories`, `rail-shut`, `net-proxy`,
    `net-tor`, `net-offline`, `playing-bg`, `mic-helper`, `press-overlap`,
    `press-toggle`, `press-solo`, `press-queue`: never the proxy's address or which
    sounds); the Sounds, Apps or Voice tab shown as a list, hotkeys set not to reach the
    game, a key for a voice, an auto push-to-talk key, the voice leveler off, and a sound
    with a voice (or an AI voice) laid over it (`used/view-list-sounds`,
    `view-list-apps`, `view-list-voice`, `hotkeys-share-off`, `voice-hotkeys`,
    `auto-ptt`, `voice-leveler-off`, `sound-voice`, `sound-ai-voice`: never the key,
    the voice or which sounds); the voice changer's Background on, and with board
    sounds in it, a category hidden from *All*, and the control API's chat commands and
    alerts set up (`used/voice-background`, `voice-background-sounds`,
    `hidden-from-all`, `api-chat-rules`, `api-alerts`: never which sounds, category,
    commands or alerts); the themes' Plain look instead of Textured
    (`used/textures-off`); Lite mode on and *Use less CPU* picked on or off by hand
    (`used/lite-mode`, `light-voice-on`, `light-voice-off`); Twitch connected
    (`used/twitch-connected`: never the account); the achievement pop-ups and their
    chime on (`used/achievement-popups`, `achievement-chime`).
- **Your Twitch channel's name, only if you ask:** once you're connected, the Twitch card
  (Settings → Remote) has a box, *Let the Onion Board developer see this channel's name*,
  off until you tick it. While it's ticked and you're connected, the daily count adds
  `twitch-channel/<login>` (your channel's Twitch login, nothing else about it), so the
  developer can see who streams with Onion Board. Unticking it, *Disconnect* (which also
  unticks it, so another account is asked again) or switching the count off stops it;
  it isn't restored from a backup.

**Problems, as counts only, soon after a start:**

- `crash/<version>`, `error/<version>` or `freeze/<version>` for each crash or freeze
  report saved in `crash-reports\` since the last send, with where it happened in
  Onion Board's own code: the error's type (such as `KeyError`) and the file and line
  (such as `soundboard/audio/engine.py:1090`, which anyone can look up in the public source),
  the line that called it and the Python library function it was raised or stuck in
  (such as `threading.wait`). A freeze also says how long it lasted
  (`lasted-under-10s`, `lasted-10-30s`, `lasted-30s-2m`, `lasted-2m-plus` or
  `never-ended`) and whether the window itself was busy, another part of the app was
  (with its line of Onion Board's code) or nothing was (`busy-window`,
  `busy-thread@…`, `idle`). That, the kind and the version are all that's read from a
  report: never the error message, paths, devices or log lines. The report itself
  never leaves your PC unless you post it.
- `warned/<version>/<type>@<soundboard/…py:line>`: an error the app caught and showed
  you as a warning instead of crashing, or that stopped the mic effect's set-up (the
  type and the line, never the message).
- `failed/<version>/<what>/<detail>`: a download, search, FFmpeg get or check, mic effect
  set-up or add-on install that failed for a reason the count's fixed words don't
  cover, with what was known where it failed: the error's type (yt-dlp's own, for a
  download) and the line of Onion Board's code it came from, a web status
  (`http-403`), a Windows error or exit number (`err-5`, `exit-2`), or which wait ran
  out (`helper`, `connect`, `read`). Never the message, a link, a path or a title.
- `unclean-exit/<version>/<why>` when the last run ended without the app closing
  itself: `native-crash`, `windows-error`, `not-responding`, `while-closing`, `frozen`,
  `pc-restarted` or `ended`; for a crash also the error's name (such as
  `access-violation`) and the Windows file or the line of Onion Board's code it
  happened in (such as `Qt6Core.dll`). The app works this out on your PC, from its own
  notes and Windows' Application log.
- `startup-failed/<version>`, once, for a run that died before it got that far (a
  crash while a module or Qt loaded), with the same kind of detail when it's there (the
  native stacks faulthandler caught, or Windows' own error for that run's process).
- More than 10 problems in one send are cut to 10 plus one `problems-dropped/<bucket>`
  (`1-10`, `11-50`, `51-plus`).

**Send feedback** ("What would you improve?") sends your picks right away, with a
one-off random session instead of this PC's ID, so they can't be linked to you or to the
daily count: `improve/sounds`, `improve/looks`… (only the names in `IMPROVE` in
`soundboard/core/usage.py`), the follow-up ticks that open under a pick
(`improve/sounds/memes`, only the names in `IMPROVE_MORE`), and what you typed under
*Something else* or *Fewer bugs* as dashed words (`improve/other/more-anime-sounds`,
`improve/bugs/said/crashes-when-i-alt-tab`, at most 100 and 200 characters; anything
that looks like an email address, a link or a long number is taken out first).

**Enjoying Onion Board?** (a bar shown once ever, after the app was open 2 hours or
more on 3 different days, and only while the count is on) sends your thumb the same way, with
a one-off random session: `feedback/positive` or `feedback/negative`, what you typed
under it as dashed words (`feedback/positive/more-meme-sounds`, at most 100 characters,
cleaned like the above), and `feedback/shown` / `feedback/dismissed` when it's shown or
closed without a thumb.

**Switching it off** (the installer's box, or Settings) sends one last
`opt-out/installer` or `opt-out/settings` with no ID, tag or session, so it can't be
tied to anything sent before (only when it was on until then, never in Offline or Tor
mode, and the installer waits at most 5 s); after that nothing is sent.
**Uninstalling** sends one `uninstall/<version>` (the uninstaller runs
`OnionBoard.exe --uninstall-count`; not in Tor mode, and it gives up after 15 s).

**Nothing else:** no user name (except the Twitch channel above, if you tick its box), PC name, sounds, settings, devices, games or crash
messages, and the app doesn't send its IP address in the message (GoatCounter sees the
connection's address like any site, and isn't asked to look it up or keep it).

### Switches and Offline mode

Settings → Privacy & security has a switch for each feature in the *Switch* column
above, grouped into Sounds and radio, Voices, Updates and add-ons, and Setup downloads,
and *Offline mode*, which switches them all off. The installer's *Your privacy* page
has the same *Offline mode* box (or `/OFFLINE=1` for a silent install): it's written to
`config.json` before the app first starts, so the app never goes online at all, and
it unticks the installer's own downloads (VB-Cable, live voice, Tor) and skips FFmpeg.
Connection settings live on Settings → Connection; automatic update preferences
live only on Settings → Updates. Changing a category does not change permissions.
Off means fully off, in every
Connection mode: every request names its feature, and `soundboard/online/net.py` refuses a
switched-off one (or one that names none) before anything is looked up or connected.
FFmpeg and Qt connect from C++, so they always go through the app's loopback relay,
Direct mode included; the relay's per-launch login names the feature, and the relay
refuses a switched-off one. Programs the app starts get their own feature's login
(`pip`: add-ons; the live-voice helper: voices, plus `HF_HUB_OFFLINE=1` while that's
off, so it only uses a speech model it already has). Sounds from the web also have a
switch per site (YouTube, SoundCloud, Myinstants, other links). Everything is on by
default, except what was already opt-in (yt-dlp's automatic updates, play counts).

A change applies to what's already running, not only to what starts next: switching
a feature off, turning on *Offline mode* or changing the Connection setting cuts that
feature's open connections, so a download in progress (an update, a model, a sound)
stops instead of finishing the old way, and a playing radio station stops (or, after
a Connection change, reconnects the new way). The update download also checks its
switch between chunks.

Not covered: links you open in your own browser (Support, feedback and report
buttons, Report on GitHub, release pages), the installer's own downloads (FFmpeg, VB-Cable, live voice), and
Windows Update installing a voice or the PowerShell VB-Cable download (they can't go
through the app's connection, so their buttons are disabled while their switch is off).
A custom voice that's a program you added may go online on its own; it gets the
voice servers' login, but one that ignores proxy settings can't be stopped.

### Through a proxy

Settings → Connection → *Through a proxy* sends what the app
fetches through a SOCKS5 (`socks5h://host:port`; `socks5://` and a bare `host:port`
mean the same) or HTTP (`http://host:port`, via `CONNECT`) proxy. All of it goes
through `soundboard/online/net.py`:

| What | How it reaches the proxy |
|---|---|
| Update checks and downloads, the yt-dlp updater, Myinstants, translation models, Onion Watch, AI voices, Onion Pocket, Tor's download, custom voice servers, the usage count, a sound's picture from a link | `net.urlopen()`: connections are opened by the proxy, and site names are sent to it unresolved |
| yt-dlp (searches, link look-ups, downloads, and the ffmpeg it may start) | its `proxy` option, set to the relay |
| Radio Browser and search thumbnails (Qt's network managers; a thumbnail goes under the switch of the site its server belongs to) | an HTTP proxy setting pointing at the relay |
| Radio streams (Qt Multimedia / FFmpeg), including redirects, HLS playlists and segments, and ICY titles | the `http_proxy` environment variable, pointing at the relay |
| Programs the app starts while the proxy is on (`pip` installing a module, the AI voices helper's model download, the live-voice helper's Hugging Face download / check) | `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`, pointing at the relay. A helper already running keeps the setting it started with |

The relay is a small HTTP proxy inside the app that listens on `127.0.0.1` only,
needs a random per-launch secret (Basic auth, compared with
`secrets.compare_digest`) and makes every onward connection through the proxy. It
refuses targets on this PC or the home network (loopback, private and link-local
addresses, `.local`, `.lan`).

In Direct mode the relay still carries FFmpeg's and Qt's connections (that's where
their switches are enforced). There, names are looked up on this PC anyway, so the
relay looks a name up first and refuses one that leads to this PC or the home network:
a radio station (or a stream redirect) whose name resolves to `127.0.0.1` or a router
address isn't played. FFmpeg's environment has no `no_proxy` list, so a redirect to
`127.0.0.1` or `localhost` goes through the relay too instead of straight to this PC,
and the relay refuses it in every mode: every station comes from Radio Browser, so
nothing the radio plays lives on this PC. (For the other features, Direct mode keeps
this PC reachable through the relay, as it was before the relay ran there.)

- **Fails closed.** If the proxy is unreachable, refuses, or its address can't be
  used, the request fails with a message saying so. Nothing falls back to a
  direct connection. A mode this version doesn't know (from a newer version's
  `config.json`) counts as a proxy with no address: nothing goes online.
- **DNS** goes through the proxy. While it's on, the radio player no longer looks a
  station's name up on this PC to check it isn't on the home network (that would
  tell your DNS server which station it is); the relay refuses home-network
  addresses instead.
- **Stays direct:** `127.0.0.1`, `::1` and `localhost` (a custom voice server on
  this PC, module links, the remote-control API). A custom voice server elsewhere
  on your network goes through the proxy like anything else. Radio streams are the
  exception: nothing a station sends the player to on this PC is reached.
- **Switching** applies at once: Qt's network managers are switched and their kept
  connections dropped, open relayed connections are closed, and a playing radio
  station reconnects.
- **Not covered**, because the app doesn't make these requests itself: pages it
  opens in your web browser (*Support*, the feedback and report buttons, *Report on GitHub*, a release page), the
  installer's downloads (VB-Cable, `winget`), Windows Update (*Install the … voice*)
  and the VB-Cable installer the setup guide starts (Windows PowerShell uses
  Windows' own proxy setting, not this one). The config keeps the proxy address
  (with any password in it) in `config.json`. It's never exported with a backup
  or written to the log.

### Through Tor

Settings → Connection → *Tor* sends everything above
through the app's own Tor instead of a proxy: the same paths and rules (fails
closed, DNS through Tor, loopback stays direct), with Tor's SOCKS port on
`127.0.0.1` as the proxy. Off by default. The app doesn't ship Tor: it's only
on your PC once you press *Get Tor* or tick *Private connection (Tor)* in the
installer (see *Get Tor* in the table above); a source checkout can also use
`scripts/buildtools/fetch_tor.py`. Uninstalling leaves it in `%APPDATA%\OnionBoard\tor\bin\`
with your settings; delete that folder to remove it.

| When | Where | Why |
|---|---|---|
| Tor mode is on and the app first needs the network (or you pick *Tor* in Settings) | the Tor network: Tor's directory authorities and relays (or, with *Hide that I'm using Tor*, the Snowflake broker via a CDN plus WebRTC volunteers, or the built-in obfs4 bridges) | `tor.exe` connects ("bootstraps"). Its data folder is `%APPDATA%\OnionBoard\tor\` (directory cache, the control-port cookie); it logs at notice level with `SafeLogging` (no addresses) to the app only |

- **What it is.** `tor.exe` and `lyrebird.exe` are the Tor Project's own Windows
  Expert Bundle (`dist.torproject.org`), unmodified. The download is checked
  against a SHA-256 pinned in `soundboard/online/torget.py`, taken from the
  release's GPG-signed `sha256sums-signed-build.txt`. Antivirus programs sometimes
  flag `tor.exe` (a false positive common to Tor).
- **Only while it's needed.** Tor starts when Tor mode is on and something goes
  online, and stops when you switch Tor mode off or the app quits. It's tied to
  the app three ways (a Windows job object that kills it with the app, even after a
  crash; `TAKEOWNERSHIP` on its control connection; `__OwningControllerProcess`).
  Its SOCKS and control ports are on `127.0.0.1`, picked by Tor, and the control
  port needs the cookie only the app can read.
- **The switches still hold.** A feature that's switched off is refused before
  Tor is asked, so it never starts Tor; in Offline mode `tor.exe` isn't started at
  all, and one that's running stops. *Try this one without Tor* only skips the
  Connection setting: that site's switch still has to be on.
- **Waits, then fails.** Until Tor has connected, a request waits (the app shows
  how far Tor has got) and then fails if Tor doesn't make it. It never goes direct.
- **YouTube** often turns Tor away ("Sign in to confirm you're not a bot", HTTP
  429 / 403). The app then asks Tor for a new identity (`SIGNAL NEWNYM`: new
  circuits, usually another exit) and tries again, up to 3 times. If YouTube still
  refuses, it says so and offers *Try this one without Tor* (search: *Search this
  without Tor*). Only that click makes that one request directly, and the site then
  sees your own address.
- **Radio** streams reconnect over a new circuit if theirs breaks (more retries
  and more time than without Tor).
- **New identity** (Settings) sends `NEWNYM`: new connections leave from a
  different exit. Connections already open (a playing station) keep theirs.
- **What Tor hides:** your IP address from every site the app contacts (YouTube,
  SoundCloud, Myinstants, Radio Browser, radio stations, GitHub, PyPI), and which
  sites those are from your internet provider. With *Hide that I'm using Tor* the
  provider also can't easily tell that it's Tor at all.
- **What it can't hide:** what you send. YouTube still sees a Tor exit asking
  for that video; Radio Browser still gets your searches (and your plays, if you
  tick that box); a custom voice server still gets the text. The exit relay can
  see a plain `http://` radio stream (the app prefers `https` where the directory
  lists one). Everything under *Not covered* above stays outside Tor too.
  Connecting looks like Tor to your provider unless *Hide that I'm using Tor* is
  ticked.

No telemetry, analytics or crash upload beyond the anonymous usage count above (crash counts, never crash reports)
(*Count me in*). Its random ID does link your counts together over time, only to fix errors and see which features need work; untick *Count me in* and one last anonymous `opt-out` count goes, then nothing. The update check only reads the public
release list; a new version is installed by itself only while *Install updates by themselves* is ticked (on by
default: untick it in Settings → Updates and nothing is installed unless you click *Update now*). *Export* only writes a zip where you save it; nothing is uploaded. Logs and
settings stay in
`%APPDATA%\OnionBoard\`.

## What *Straight into my mic* changes on your PC

Sounds reach Discord and games through your own mic by default: a small Windows audio
effect (`native/directmic/obmic.cpp`, built from source with the app; `soundboard/mic/directmic.py`)
mixes them into the mic. It's the one part of the app that needs admin, and it never
goes online.

- **Setting it up** (one click in the setup guide or on the Setup tab, then Windows'
  admin prompt; a one-click repair the same way if Windows takes it off): the app runs its own exe again as admin with
  `--direct-mic install <mic id>`. The id must be a recording device Windows lists,
  and the DLL copied is always the one inside the app, never a path from the command
  line. That step copies it to `%ProgramFiles%\Onion Board Mic\` (which only admins
  can change; the file is named after its SHA-256), registers it as an audio effect under
  `HKLM\SOFTWARE\Classes` (`CLSID\{C55E76FE-…}` and
  `AudioEngine\AudioProcessingObjects`), and puts it in that one mic's stream-effect
  slot (`MMDevices\Audio\Capture\<mic>\FxProperties`). An effect the mic's driver
  had there is kept and run first, inside ours. Every value is noted under
  `HKLM\SOFTWARE\OnionBoard\MicPlugin` before it changes. Windows' audio stops for a
  few seconds while this happens; a helper started first brings it back however the
  admin step ends, along with the services that run on it (Windows' MIDI service...).
  One admin step runs at a time, every command it runs has a time limit, and a set-up
  that fails half-way puts the mic back as it was. It logs to
  `%ProgramData%\OnionBoard\directmic-admin.log`.
- **The mic helper** (so Windows asks once, not on every repair or change of mic): the
  first set-up also copies `obmichelper.exe` (only the admin step above, with its own
  copy of the effect DLL) to `%ProgramFiles%\Onion Board Mic Helper\` (admins only) and
  registers a scheduled task, `\Onion Board\Mic helper`, that runs it as SYSTEM. It has
  no trigger and isn't a service: it runs only when Onion Board starts it, for the few
  seconds a job takes. The task's permissions let only the Windows accounts that set it
  up (and admins) start it: each user account (local, domain or work / school) that
  went through Windows' prompt for it, listed in `users.txt` in its folder. A standard
  user who typed an admin's password there counts as the one who asked: the app passes
  its account (`--for`), and the admin step accepts only a real user account with a
  profile on this PC. Another account setting it up never takes it away from the first.
  After registering, the task is read back from Task Scheduler and deleted again unless
  it really runs as SYSTEM, has no trigger, runs our program and has exactly those
  permissions. The app asks for a job with a one-line file in
  `%ProgramData%\OnionBoard\MicHelper\requests\` (those accounts may add files there
  and change only their own, nothing else) and reads the answer from `...\results\`
  (admins only, so nothing can steer what SYSTEM writes). The helper opens each request
  without following links, checks on that open handle that it is a small plain file
  with one name, and reads it from the same handle. While it works on a job it keeps a
  heartbeat file in `results\`: the app waits as long as that is fresh (a second admin
  copy now would fail), and falls back to Windows' prompt soon after it stops (a helper
  killed half-way). A request is only ever matched against a fixed list
  (`install`, `reinstall`, `cleanup` or `uninstall` with a mic id, `uninstall`,
  `remove-all`), never used as a path or shown, and anything else is refused. The
  helper installs only the DLL inside its own Program Files folder, so it can't be
  used to put any other code into Windows' audio: a new version of the effect still
  needs Windows' prompt, which also updates the helper. It logs what it does to
  `%ProgramData%\OnionBoard\michelper.log` (made at its first request; kept to about
  1 MB, with one older copy, as is `directmic-admin.log`, where the steps run after
  Windows' prompt go). `obmichelper.exe` isn't code-signed; each release's
  VirusTotal scan covers it.
- **The data folders**: anyone signed in can make folders in `%ProgramData%`, so before
  writing anything there the admin step makes `%ProgramData%\OnionBoard` a real folder
  owned by Administrators that only admins can change (a link someone put there is
  removed, never followed; so is anything inside not made by an admin), and sets
  `MicPlugin`'s own access on the folder itself, without walking what's inside.
- **The shared file**: `%ProgramData%\OnionBoard\MicPlugin\` lets LOCAL SERVICE (the
  audio engine), WRITE RESTRICTED and signed-in users make and change files in it, but
  not delete, rename or swap the folder itself, nor make folders in it (admins and SYSTEM
  have full access; store apps none). The board writes what others hear there, and the effect writes the
  clean mic back, so the board's meter and voice changer hear only you. Every app
  recording that mic runs its own copy of the effect. When the board is closed or
  late, the effect crossfades back to the plain mic. Since others can write the file,
  the effect trusts nothing in it: a damaged, cut-short or tampered file (even one
  that makes reading it fault) gets the plain mic passed through, never a crash of
  Windows' audio engine. `scripts/directmic/fuzz_directmic.py` tests this.
- **Taking it off**: uninstalling Onion Board runs `--direct-mic remove`, which (through
  the mic helper, or else after Windows' prompt, and only if the effect or the helper
  is there at all) does what `--direct-mic uninstall` (as admin) does: put every mic's
  values back from the notes, unregister the effect and delete `Onion Board Mic` and the
  notes. Then the helper's task is deleted and its files and `MicHelper` folder
  removed (files in use at that moment, at the next restart); any piece of it counts,
  a task without its folder or a half-done update's folder too. The helper is for the
  whole PC: on a PC with several accounts, one of them uninstalling takes it away for
  all (the next set-up asks Windows again). What can't be cleaned up: a helper left by
  deleting the app's folder by hand (no uninstaller runs), or by uninstalling a version
  older than the helper after going back to it. That task never runs on its own; the
  next Onion Board install's first set-up replaces it and its uninstall removes it, or
  delete the task `\Onion Board\Mic helper` and `%ProgramFiles%\Onion Board Mic Helper`
  by hand. Taking the effect off a mic in Setup keeps the helper, so putting it back
  needs no prompt. If Windows already took the effect off (a
  driver update, *Reset sound settings*), what's there now stays. The shared file and
  the admin log stay in `%ProgramData%\OnionBoard\`, unless you say Yes to the
  uninstaller's *Also delete your sounds and settings?*: then, once the effect and the
  helper are off, that folder goes too (`soundboard/core/uninstallclean.py`, in the
  same admin step that removes Onion Pocket's firewall rule, which every uninstall
  does on a PC that has one).
- **The virtual cable**, the fallback, is VB-Audio's own signed driver: installed by
  `installer/install-vbcable.ps1` only when you ask, and removed by VB-Audio's own
  uninstaller (Setup tab → *Remove the virtual cable*, or the uninstaller's question),
  both after Windows' admin prompt.

## What the app reads and writes in Discord's settings

Discord's own noise suppression, echo cancellation and automatic gain wipe sounds out,
so the app checks them and, when you press the setup guide's Discord button, switches
them off (`soundboard/mic/discordcfg.py` reads, `soundboard/mic/discordtalk.py` writes).
None of it ever goes online, and nothing from those files is written to the log.

- **Where:** Discord keeps its settings in its web storage, a LevelDB folder at
  `%APPDATA%\discord\Local Storage\leveldb` (and the same for Discord PTB, Canary and
  Development). The same folder also holds Discord's login.
- **Reading:** the app scans those files for one entry, `MediaEngineStore` (Discord's
  voice settings, as JSON), and keeps only the voice switches it needs from it. Nothing
  else in the folder is parsed, kept or shown, the login included.
- **Writing:** only after you press the Discord button and say Yes to Discord being
  closed (it ends a call): the app closes Discord, adds one new `MediaEngineStore`
  record to the end of the folder's log file, reads it back, and undoes it if anything
  is off. How you had it is saved in `%APPDATA%\OnionBoard\config.json` (the voice
  switches only), and put back when Onion Board closes (unless you untick *Put Discord back for
  talking on close* on the Setup tab), by Settings → Audio → *Put
  Discord back*, and by the uninstaller.
- **Copies:** before each write, the voice settings it replaces (the `MediaEngineStore`
  JSON, nothing else) are saved to `%APPDATA%\OnionBoard\discord-backup\<client>\<time>.json`,
  so they can be put back by hand. Discord's own files are never copied, and the app
  never reads, copies or keeps Discord's login token. At most 3 per client are kept,
  none older than 14 days, and only on this PC. Delete the `discord-backup` folder to
  remove them; the uninstaller's *Also delete your sounds and settings?* removes them
  with the rest. Older versions copied Discord's log file there instead (which could
  hold the login): the app deletes those copies a few seconds after it starts.

## Anti-cheat

Onion Board never touches a game's process: it doesn't inject code into it, read
or write its memory, hook it, or install a kernel driver of its own. What it does
use is plain Windows APIs that any desktop app can call:

| Feature | What it does | Touches the game? |
| --- | --- | --- |
| *Straight into my mic* | an audio effect DLL that Windows loads into its own audio engine (`audiodg.exe`), not into the game ([details](#what-straight-into-my-mic-changes-on-your-pc)). It isn't code-signed | no |
| Hotkeys | `RegisterHotKey`: Windows tells the app when one of its own key combos is pressed. No keyboard or mouse hook. With *Games get the key too* (Settings → Keys in games, on by default) the app also gets a copy of every key press through Windows' Raw Input (`RIDEV_INPUTSINK`), to spot its own combos without taking them from the game; key presses are never logged, stored or sent, only matched against your hotkeys. Untick it and only `RegisterHotKey` is used | no |
| Auto push-to-talk | `SendInput` holds the push-to-talk key you set, only while a sound is going out | sends that one key, like a keyboard would |
| MIDI pads | reads the controller through Windows' MIDI API | no |
| Overlay | a separate always-on-top window that never takes focus, drawn by the app itself | no (drawn on top, not inside) |
| Onion Watch screen triggers (add-on) | copies the game window's picture (`PrintWindow`, or the screen through `BitBlt` / DXGI desktop duplication) and compares it with your pictures. It plays sounds; it never presses keys itself | reads pixels only |
| App audio / game detection | Windows' per-app audio capture, and `OpenProcess` with `PROCESS_QUERY_LIMITED_INFORMATION` (the least access there is, as Task Manager uses) just to read a program's name and whether it's still running. A refused handle is treated as "running" | a name-only handle, closed at once |

None of the anti-cheats checked (Riot Vanguard, Easy Anti-Cheat, BattlEye, FACEIT)
publish a rule against any of this: their published rules target vulnerable or blocked
kernel drivers, code loaded into the game, and cheats or macros that play the game
for you. The app has been used in real Valorant (Vanguard) and Fortnite (Easy
Anti-Cheat) parties without a complaint (Vanguard ignores the injected push-to-talk key,
so hold it yourself there), but no one can promise what an anti-cheat will do next, so
if one ever complains, please
[open an issue](https://github.com/Onion-Alien/onion-board/issues).
Two sensible habits: set your push-to-talk key to the game's push-to-talk only (never
a key that moves or shoots), and don't build Onion Watch triggers that react to
gameplay in a way that helps you play.

## For users filing bug reports

`%APPDATA%\OnionBoard\onionboard.log` contains file paths that include your
Windows user name. Skim it and replace anything personal before attaching it to a
public issue. It can also name a site a download or radio station failed on.
*Keep an app log* (Settings → Connection) switches it off and deletes it. Crash reports (Settings → About's *See report*, and
`%APPDATA%\OnionBoard\crash-reports\`) already have your home folder, user name
and computer name replaced — still skim them before posting.
