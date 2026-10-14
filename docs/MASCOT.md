# Bun the mascot: where he lives and how he animates

Read this before changing Bun's drawing, an outfit, or any animation he's in. He's
drawn in code with QPainter (no image files), so every pose, prop and outfit is a few
lines in the files below.

## The files

| File | What it does |
| --- | --- |
| `soundboard/bunny.py` | `draw_bunny(p, rect, prop, **pose)`: one still picture of Bun on a 100 x 120 canvas. Everything else calls this. Also `bunny_image` / `bunny_pixmap` for static pictures. |
| `soundboard/bunnyfit.py` | His outfit per theme (`OUTFITS`) and the pieces' drawing (`PIECES`), in layers `draw_bunny` calls between its own. |
| `soundboard/ui/bunnywidget.py` | `BunnyWidget`: Bun alive. Bobs, blinks, flicks ears, idle fidgets (yawn, look round, foot tap), talks with the mic level, music notes, begging bubbles, naps, the click cheer, the build act (dives into a dust cloud, rummages, hammers a speaker together; the snap when it fails), Robo-Bun's version (gadget screen, sparks, LED pulse), the Pong dare (cross face, bat). Its `pose(now)` turns the clock into `draw_bunny`'s keywords plus his squash (`sx`, `sy`), lean (`angle`) and fade (`alpha`). |
| `soundboard/ui/setupshow.py` | `SetupShow(BunnyWidget)`: the mic set-up show (toolbox, speaker parts popping on, progress dots). |
| `soundboard/ui/scribebun.py` | `ScribeBunny`: the download bar's picture, Bun writing the tune on a scroll in a 56 x 59 slot. Caches pictures of him in `_layer`. |
| `soundboard/ui/bunpong.py` | The Pong Easter egg; draws Bun with his bat (or the star when he wins). |
| `soundboard/splash.py` | The start-up splash (drawn before a theme is applied: plain Bun). |
| `scripts/make_bunny.py`, `scripts/make_favicon.py` | Installer art and icons: always plain Bun (`outfit=()`). |
| `scripts/bun_sheet.py` | Picture sheets for checking a change by eye (below). |

## Every place he shows up

`BunnyWidget` in the setup guide (`ui/setupwizard.py`, a prop per page), the chat guides
(`ui/chatguide.py`, `ui/streamguide.py`), the empty board (`ui/widgets.py`), the Apps tab
(`ui/appspanel.py`, sad and begging), the Radio map (`ui/flatmap.py`), the YouTube search
(`ui/ytsearch.py`), the mic part update (`ui/micupdate.py`) and Robo-Bun on the AI voice
card (`ui/aivoicepanel.py`). `SetupShow` in the setup guide; `ScribeBunny` in the
download bar (`ui/downloadbar.py`); static pictures in `ui/dialogs.py` and the smug box in
`ui/mainwindow.py`. To find new ones: grep for `draw_bunny`, `BunnyWidget`, `bunny_pixmap`.

## Poses

`draw_bunny` keywords, all 0 when he's at rest: `blink` (0..1, shut above 0.6), `mouth`
(talking), `ears` (degrees outward), `swing` (hammer or bat), `sad` (worried face, and the
ears fold down from the middle), `angry` (cross brows and the vein mark), `nightcap`
(asleep), `robot` (Robo-Bun), `smug`, `led` (Robo-Bun's LEDs brighter, 0..1). Props:
`bunny.PROPS` (`hammer_broken`: the failed build's snapped plank and headless hammer).
Everything an act shows stays inside the widget's own box: a widget is only a little wider
than Bun, so moving him sideways out of view slices him at its edge. Squash, shrink or fade
him instead (the build act dives into its cloud, the setup show fades out before the edge).
What gets built is drawn on the canvas at `bunny.PLANK_SPOT` / `bunny.GADGET_SCREEN`.
Animations never draw Bun themselves: they work out these numbers per frame and call
`draw_bunny`, so a new piece of drawing in `bunny.py` or `bunnyfit.py` shows up in every
animation at once.

## Outfits

`draw_bunny(..., outfit=None)` wears the current theme's outfit (`bunnyfit.outfit()`);
`outfit=()` is plain Bun. The layers, in the order they're painted:

| Layer | Painted | Pieces |
| --- | --- | --- |
| `back` | after his body, before his head | hood, cape collar |
| `under` | on his head, under the headphones | beanie, headband, bandana, eye shade |
| `over` | after the headphones (and nightcap) | crown, hats, horns, flowers, onion |
| `face` | after his face, before the prop in his paw | glasses, laser eyes, fangs, clown nose, bow tie, scarf, lei, hood strings |

Rules the drawing keeps:

- Robo-Bun wears no outfit.
- The nightcap replaces anything in `bunnyfit.HATS`; glasses and neck pieces stay on.
- Laser eyes switch off while his eyes are shut (`blink > 0.6`).
- His headphones are the theme's `accent`; hats and neck pieces that follow the theme use
  `accent2`, so the two don't blend.
- Dark (the default, and the installer art) and High Contrast stay plain.

To add an outfit: draw the piece as a function in `bunnyfit.py` on the 100 x 120 canvas
(head: the ellipse centred at 50, 64, 68 x 56; eyes at x 39 and 61, y 62; ear bases at
36, 48 and 64, 48; neck about y 90), add it to `PIECES` with its layer (and to `HATS` if
it sits on his head), list it under the theme in `OUTFITS`, then check the sheets.
`tests/test_bunnyfit.py` checks every listed piece exists and draws.

### Hoot wears them too

Hoot the owl (`soundboard/ui/owl.py`, the Triggers tab before Onion Watch is installed)
wears the same theme outfit. He has no pieces of his own: `owl._fit` moves Bun's pieces
onto his shape (head 12 higher, eyes 28 apart and scaled 1.3, neck pieces just under his
beak) and `draw_owl` calls it at the same four layers. `owl_image` (dialog artwork, his own
teal) stays plain. A new piece drawn for Bun shows up on Hoot too: check it with
`bun_sheet.py owls` and `bun_sheet.py owl`. Onion Watch's own copy of the owl
(`onionwatch/owl.py` in that project) has no outfits.

**Anything that caches a picture of Bun must key it on `theme.current_name`** (his
outfit), not only the accent colour: see `ScribeBunny._layer`.

## Checking a change

```
.venv\Scripts\python scripts\bun_sheet.py outfits   # every theme's outfit
.venv\Scripts\python scripts\bun_sheet.py poses     # outfits x every pose
.venv\Scripts\python scripts\bun_sheet.py live      # the real widgets, frame by frame
.venv\Scripts\python scripts\bun_sheet.py owls      # Hoot in every theme's outfit
.venv\Scripts\python scripts\bun_sheet.py owl       # Hoot's poses in a few outfits
```

`live` swaps `time.monotonic` for a fake clock and steps each widget's own timer
(`_step` / `_tick`) so every act (talking, notes, the build act, begging, napping, the
cross face and bat, Robo-Bun, the setup show, the download scribe) is caught at a known
moment. Sheets go to `%TEMP%\bun-sheets`. Look at all three before sending pictures.
