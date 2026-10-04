# Artwork

Small pictures the app shows when they're here (`soundboard/ui/art.py`). Every one
is optional: without it the voice tile keeps its emoji and the Voice tab its
painted icon.

They're square PNGs, 256 px, shown with rounded corners at 16–40 px, so a bold
silhouette on a plain background reads best. `scripts/prepare_art.py <folder>`
crops, shrinks and names a folder of generated pictures into here.

Only artwork made for this project goes here (no third-party images).

| File | Shown |
|---|---|
| `voice-chipmunk.png` … `voice-podcast-voice.png` | the voice changer's tiles, and the Voice tab while that voice is on. The name is the voice's name in lowercase with dashes: `voice-deep-voice`, `voice-walkie-talkie`, `voice-old-telephone`, `voice-stadium-announcer` |
| `voice-custom.png` | the "My own mix" tile, and your saved voices' tiles |
| `voice-random.png` | the "Random voice" tile (without it, a die painted in code) |
| `voice-computer.png` | "Start talking as the voice", and the Voice tab while the computer voice talks in English |
| `lang-en.png`, `lang-de.png`, `lang-es.png`, `lang-fr.png`, `lang-ru.png`, `lang-zh.png` | the "Speak in" list, and the Voice tab while the computer voice talks in that language |
