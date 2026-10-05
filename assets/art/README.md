# Artwork

Small pictures the app shows when they're here (`soundboard/ui/art.py`). Every one
is optional: without it a voice tile shows a painted "?" and the Voice tab its
painted icon. Still to make: `voice-female-voice`, `voice-male-voice`,
`voice-talkbox`, `voice-autotune`, `voice-masked-caller`, `voice-anonymous`,
`voice-dark-lord`, `voice-hothead`.

They're square PNGs, 128 px, shown with rounded corners at 16–30 px, so a bold
silhouette on a plain background reads best. `scripts/prepare_art.py <folder>`
crops, shrinks and names a folder of generated pictures into here.

Only artwork made for this project goes here (no third-party images).

| File | Shown |
|---|---|
| `voice-chipmunk.png` … `voice-podcast-voice.png` | the voice changer's tiles, and the Voice tab while that voice is on. The name is the voice's name in lowercase with dashes: `voice-deep-voice`, `voice-walkie-talkie`, `voice-old-telephone`, `voice-stadium-announcer` |
| `voice-custom.png` | the "My own mix" tile, and your saved voices' tiles |
| `voice-random.png` | the "Random voice" tile (without it, a die painted in code) |
