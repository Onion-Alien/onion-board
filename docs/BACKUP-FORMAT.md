# Backup and sound pack format

What *Backup → Export* writes and *Import* reads (`soundboard/backup.py`). It's a
plain `.zip` of JSON files and the original audio, so it can be opened, edited,
made or taken apart with any zip tool or script — no Onion Board needed.

## Layout

```
Onion Board backup 2026-09-27.zip
├── onionboard.json               what's inside (a full export, a category or a sound pack)
├── settings.json                 the app's settings (only in a full export)
└── sounds/
    ├── 001 Air horn/
    │   ├── sound.json            this sound's settings
    │   ├── Air horn.mp3          its audio, byte for byte as it was imported
    │   └── picture.jpg           its pad picture (optional)
    └── 002 Bruh/
        ├── sound.json
        └── bruh.wav
```

Each sound folder is self-contained. That makes three shapes importable:

| shape | what it is | what importing does |
|---|---|---|
| **backup** | `onionboard.json` + `sounds/…` + usually `settings.json` | adds the sounds in the listed order; asks before using the settings |
| **sound pack** | any number of sound folders, with or without `onionboard.json`, no `settings.json` | adds the sounds |
| **single sound** | `sound.json` and its audio at the root of the zip | adds that sound |

An unzipped folder of any of these imports too (drop it on the pads). Sounds whose
fingerprint is already in the library are skipped, so importing the same thing
twice adds nothing.

A zip with none of these, just audio files (in any folders inside it), is a
**zip of sounds**: each audio file is added as if it had been dropped on the pads.

## `onionboard.json`

```json
{
  "format": "onionboard-board",
  "format_version": 1,
  "app_version": "1.0.0",
  "created": "2026-09-27T12:00:00Z",
  "categories": ["Memes", "Game"],
  "sounds": ["sounds/001 Air horn", "sounds/002 Bruh"],
  "settings": "settings.json"
}
```

- `format` must be `onionboard-board`. A `format_version` newer than the app knows
  is refused with "made by a newer Onion Board".
- `categories`: the category tabs, in order (a full export includes empty ones).
- `sounds`: the pad order. Sound folders not listed are imported after these.
- `settings`: the settings file's name, or `null`.

## `sound.json`

```json
{
  "name": "Air horn",
  "audio": "Air horn.mp3",
  "picture": "picture.jpg",
  "volume": 1.0,
  "hotkey": "ctrl+1",
  "mode": "restart",
  "loop": false,
  "color": "#7c5cff",
  "fx": {"start": 1.2, "end": 3.5, "speed": 1.25, "tape": true},
  "tags": ["Memes"],
  "level_gain": 1.8,
  "duration": 2.3,
  "fingerprint": "3f0c…"
}
```

Only `name` and `audio` are needed; everything else falls back to the defaults.

| key | meaning |
|---|---|
| `audio` | file name of the audio, in the same folder. Any format the app plays (mp3, wav, ogg, flac, opus, m4a, aac, wma, aiff, aif, webm, mp4, mkv, mov) |
| `picture` | file name of the pad picture in the same folder (png, jpg, jpeg, jfif, webp, gif, bmp), or `""` |
| `volume` | 0–2 (1 = 100 %) |
| `hotkey` | e.g. `ctrl+alt+1`, `f5`, `num 7`, or a MIDI pad: `midi:note 36:LPD8` (`note`, `cc` or `pc`, its number, the device name); dropped on import if something already uses it |
| `mode` | `restart`, `overlap`, `toggle`, `solo` (stops the other sounds first) or `queue` (waits for the sounds playing to finish) |
| `loop` | `true` / `false` |
| `hold` | `true`: plays only while its hotkey / MIDI pad is held down |
| `fade_in`, `fade_out` | seconds (0–10) |
| `only_them` | `true`: goes out to others but isn't played in your own headphones |
| `delay` | seconds between the press and the sound (0–10) |
| `cooldown` | seconds after it starts during which presses are ignored (0–60) |
| `color` | `#rrggbb` |
| `fx` | the sound's effects, as in `soundboard/soundfx.py`: `start` / `end` (trim, seconds into the audio; `end` 0 = to the end), `speed`, `pitch` (semitones), `tape`, `eq` (7 dB values), `gain_db`, `reverse`, `effects` (voice effects by type) |
| `tags` | the categories the sound is in |
| `level_gain` | the loudness-levelling gain (recomputed if missing) |
| `duration`, `fingerprint` | informational; the fingerprint is how duplicates are spotted |

## `settings.json`

The app's settings (`Config` in `soundboard/library.py`) minus anything that
belongs to one PC or that must only be switched on by hand (`LOCAL_SETTINGS` in
`soundboard/backup.py`): audio devices, where sounds are sent (straight into the mic,
the cable, another device or nowhere), the setup-guide state, per-program Apps
settings, the Triggers tab's screen settings, category hotkeys, the remote-control
switch, port and key, remote add-ons' settings (Onion Pocket), the network settings
(connection mode, proxy, per-feature switches, Offline mode, Tor bridges), the data
& quality settings, the usage count's ID and state, and the downloaded-code settings
(yt-dlp auto-update, the update check and its state). On
import only known settings of the right type are used, and only if the user says
yes.

It also holds `saved_voices`, the voice changer's saved voices (kept in a file of
their own in the app, so not a `Config` field), when there are any:

```json
"saved_voices": [{"name": "Squeaky robot", "effects": {"pitch": {"on": true, "semitones": 6.0}}}]
```

On import, voices whose name isn't taken yet are added; ones already there are left
as they are.

## Safety

Import never uses a name from the archive as a path. Files are looked up by the
plain file names `sound.json` gives (no `/`, `\` or `..`) and written into the
library under new names. Any one file is limited to 1 GiB (64 MiB for a picture,
4 MiB for JSON), checked while unpacking, and a whole import to 8 GiB; before
anything is written the declared sizes are checked against that and against the
free disk space (leaving 256 MiB spare; a zip is unpacked first and then copied in,
so it needs room twice over). Numbers must be finite (`NaN` /
`Infinity` fall back to the default), and imported speech settings only accept the
app's own model names. Pictures are re-encoded before use.
