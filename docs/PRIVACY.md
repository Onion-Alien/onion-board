# Privacy

Onion Board has no accounts, no ads and no tracking. Your sounds, settings and logs stay
on your PC. This page says, in short, what the app sends, how to turn each part off,
what it changes on your PC and how to take it all off again. The full detail (every
server, every switch, every value) is in [SECURITY.md](../SECURITY.md).

## What is sent

**One thing goes out on its own: the anonymous usage count** (*Count me in*). It's on
for new installs and only runs in the installed app (never from source).

- **What:** the app's version, a random ID made on your PC (not tied to your name,
  account, PC or any other ID), and names from a fixed list: which tabs and features you
  used that day (yes or no, never what you did with them), rough buckets (how many
  sounds, how long the app was open, Windows 10 or 11, the app's language and Windows'
  language, the theme) and the names of problems it hit (a crash, a failed download),
  with the error's type and the file and line in Onion Board's own code where it
  happened. Never your sounds, file names, searches, links, mic names, error messages or anything
  you typed. The full list: [SECURITY.md, *The anonymous usage count*](../SECURITY.md#the-anonymous-usage-count-count-me-in).
- **When:** once a day, on closing the app if something waits for the next count, and
  once when you uninstall it.
- **Where:** [GoatCounter](https://www.goatcounter.com/) (`onionalien.goatcounter.com`),
  over HTTPS. It's used only to fix errors and see which features need work.
- **Off:** untick *Count me in* in the installer, or in Settings → Privacy & security.
  Nothing is sent from then on, the uninstall one included.

**Everything else goes out only because you did something**, and only to the place
that thing needs:

| You | It talks to |
|---|---|
| search for sounds or paste a link | YouTube, SoundCloud, Myinstants or the link's own site |
| open the Store, vote or share a sound | this project's store server (with a random store ID; the server keeps only salted hashes) |
| open *Free sound packs* | GitHub (this project's pack list and downloads); for a links pack, Myinstants (its sounds, straight from there) |
| play the radio | the radio directory and the station you picked |
| get Tor, add-ons, AI voices, translation models, Onion Watch or Onion Pocket | their download sites (GitHub, the Tor Project, PyPI, the model's site) |
| connect Twitch | Twitch |
| press a help, feedback or report button | your own web browser opens the page; nothing is sent unless you send it there |

A few happen without a click, and each has its switch: the check for a new version of
the app (GitHub, about once an hour; Settings → Updates), the daily yt-dlp update (only
if you tick it there), and FFmpeg's download when it's missing at start (it shows on a
bar with *Stop*; Settings → Privacy & security → Setup downloads).

**Crash reports are never sent.** The crash window puts a report on your clipboard and
can open GitHub's new-issue page in your browser; nothing is posted unless you paste
it and submit it yourself.

## How to turn it off

- **Settings → Privacy & security** has a switch for each feature that goes online,
  and **Offline mode**, which switches them all off at once. Off means off: the app
  refuses the connection before anything is looked up.
- The installer's *Your privacy* page has the same *Offline mode* box (`/OFFLINE=1`
  for a silent install), so the app never goes online at all, from its first start.
- **Settings → Connection → *Network activity*** lists every connection the app makes
  or refuses while it runs, so you can check all of this yourself.

## What it changes on your PC

Each of these happens only when you choose it (FFmpeg: when you install), and Windows
asks for permission first where it needs admin:

| Change | When | Removed by the uninstaller |
|---|---|---|
| The program and its shortcuts (`%LOCALAPPDATA%\Programs\OnionBoard`) | install | yes |
| FFmpeg, through Windows' `winget` (for M4A, AAC and video files) | install, when it isn't on the PC yet and Offline mode is off (the installer says so first) | no: it's a normal app in Installed apps |
| The mic effect for *Straight into my mic* (an audio effect on the mic you pick, under `%ProgramFiles%\Onion Board Mic`) | you set it up; Windows asks | yes, and every mic's settings go back as they were |
| The mic helper (a scheduled task that runs only when Onion Board asks, so Windows asks once) | the first mic-effect set-up | yes |
| The virtual cable (VB-Cable, VB-Audio's own driver) | only if you tick it | it asks you |
| *Start with Windows* (a start-up entry) | only if you turn it on | yes |
| Discord's voice clean-up switched off, so sounds get through (and a copy of the voice settings it replaced, kept on your PC for up to 14 days) | you press Discord's set-up button | put back when the app closes, and on uninstall |
| A firewall rule for Onion Pocket (phones on your Wi-Fi) | you turn it on; Windows asks | yes (Windows asks once more) |
| A Windows text-to-speech voice | you press *Install the … voice*; Windows asks | no: it's part of Windows |

How the mic effect works, and what each step writes: [SECURITY.md, *What Straight into
my mic changes on your PC*](../SECURITY.md#what-straight-into-my-mic-changes-on-your-pc).

## Discord's settings

To see whether Discord's voice clean-up would wipe your sounds out, the app reads
Discord's settings files on your PC. It looks only at the voice settings in them, never
at your Discord login (which Discord keeps in the same folder), and sends nothing
anywhere. Before it changes them, the copy it keeps holds only those voice settings:
the app never reads, copies or keeps your Discord login token. Details: [SECURITY.md, *What the app reads and writes in Discord's
settings*](../SECURITY.md#what-the-app-reads-and-writes-in-discords-settings).

## What stays on your PC

- `%APPDATA%\OnionBoard`: your sounds, settings, logs, downloaded add-ons and Tor. The
  logs never leave your PC unless you send them yourself.
- `%ProgramData%\OnionBoard`: the mic effect's shared file and its logs.

Uninstalling asks *Also delete your sounds and settings?*: No (the default) keeps both,
so a reinstall still has your board; Yes puts the first in the Recycle Bin and deletes
the second. A silent uninstall keeps them. To remove anything an unfinished uninstall
left behind, run
[OnionBoardCleanup.exe](https://github.com/Onion-Alien/onion-board/releases/download/cleanup-tool/OnionBoardCleanup.exe):
it asks once, and deletes your sounds only if you say so.

## Questions

Ask on [GitHub](https://github.com/Onion-Alien/onion-board/issues). Security problems:
see [SECURITY.md](../SECURITY.md#reporting-a-vulnerability).
