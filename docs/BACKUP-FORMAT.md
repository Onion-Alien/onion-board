# Backup and sound pack format

What *Backup → Export* writes and *Import* reads (`soundboard/backup.py`). It's a
plain `.zip` of JSON files and the original audio, so it can be opened, edited,
made or taken apart with any zip tool or script — no Onion Board needed.

## Layout

```
Onion Board backup 2026-09-27.zip
├── onionboard.json               what's inside (only in a full export)
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
| `audio` | file name of the audio, in the same folder. Any format the app plays (mp3, wav, ogg, flac, opus, m4a, aac, wma, aiff, webm, mp4, mkv, mov) |
| `picture` | file name of the pad picture in the same folder (png, jpg, webp, gif, bmp), or `""` |
| `volume` | 0–2 (1 = 100 %) |
| `hotkey` | e.g. `ctrl+alt+1`, `f5`, `num 7`; dropped on import if something already uses it |
| `mode` | `restart`, `overlap` or `toggle` |
| `loop` | `true` / `false` |
| `color` | `#rrggbb` |
| `fx` | the sound's effects, as in `soundboard/soundfx.py`: `start` / `end` (trim, seconds into the audio; `end` 0 = to the end), `speed`, `pitch` (semitones), `tape`, `eq` (7 dB values), `gain_db`, `reverse`, `effects` (voice effects by type) |
| `tags` | the categories the sound is in |
| `level_gain` | the loudness-levelling gain (recomputed if missing) |
| `duration`, `fingerprint` | informational; the fingerprint is how duplicates are spotted |

## `settings.json`

The app's settings (`Config` in `soundboard/library.py`) minus anything that
belongs to one PC or that must only be switched on by hand: audio devices, the
setup-guide state, per-program Apps settings, and the network / downloaded-code
opt-ins (yt-dlp auto-update, update check). On import only known settings of the
right type are used, and only if the user says yes.

## Safety

Import never uses a name from the archive as a path. Files are looked up by the
plain file names `sound.json` gives (no `/`, `\` or `..`) and written into the
library under new names. Any one file is limited to 1 GiB (64 MiB for a picture,
4 MiB for JSON), checked while unpacking, and a whole import to 8 GiB; before
anything is written the declared sizes are checked against that and against the
free disk space (leaving 256 MiB spare). Numbers must be finite (`NaN` /
`Infinity` fall back to the default), and imported speech settings only accept the
app's own model names. Pictures are re-encoded before use.
