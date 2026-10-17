# Bun the mascot: where he lives and how he animates

Read this before changing Bun's drawing, an outfit, or any animation he's in. He's
drawn in code with QPainter (no image files), so every pose, prop and outfit is a few
lines in the files below.

## The files

| File | What it does |
| --- | --- |
| `soundboard/bunny.py` | `draw_bunny(p, rect, prop, **pose)`: one still picture of Bun on a 100 x 120 canvas. Everything else calls this. Also `bunny_image` / `bunny_pixmap` for static pictures. |
| `soundboard/style/bunnyfit.py` | His outfit per theme (`OUTFITS`) and the pieces' drawing (`PIECES`), in layers `draw_bunny` calls between its own; his look per theme (`LOOKS`: fur, floppy ears, extras). |
| `soundboard/ui/bunnywidget.py` | `BunnyWidget`: Bun alive. Bobs, blinks, flicks ears, idle fidgets (yawn, look round, foot tap), talks with the mic level, music notes, begging bubbles, naps, the click cheer, the build act (dives into a dust cloud, rummages, hammers a speaker together; the snap when it fails), Robo-Bun's version (gadget screen, sparks, LED pulse), the Pong dare (cross face, bat). Its `pose(now)` turns the clock into `draw_bunny`'s keywords plus his squash (`sx`, `sy`), lean (`angle`) and fade (`alpha`). |
| `soundboard/ui/setupshow.py` | `SetupShow(BunnyWidget)`: the mic set-up show (toolbox, speaker parts popping on, progress dots). |
| `soundboard/ui/scribebun.py` | `ScribeBunny`: the download bar's picture, Bun writing the tune on a scroll in a 56 x 59 slot. Caches pictures of him in `_layer`. |
| `soundboard/ui/bunpong.py` | The Pong Easter egg; draws Bun with his bat (or the star when he wins). |
| `soundboard/ui/splash.py` | The start-up splash (drawn before a theme is applied: plain Bun). |
| `scripts/pictures/make_bunny.py`, `scripts/pictures/make_favicon.py` | Installer art and icons: always plain Bun (`outfit=()`, `kit=VANILLA`). |
| `scripts/pictures/bun_sheet.py` | Picture sheets for checking a change by eye (below). |

## Every place he shows up

`BunnyWidget` in the setup guide (`ui/setupwizard.py`, a prop per page), the chat guides
(`ui/chatguide.py`, `ui/streamguide.py`), Bun mode (`ui/bunmode.py`, the window as a
floating Bun: `in_background=True` keeps him moving behind a game), the empty board (`ui/widgets.py`), the Apps tab
(`ui/appspanel.py`, sad and begging), the Radio map (`ui/flatmap.py`), the YouTube search
(`ui/ytsearch.py`), the mic part update (`ui/micupdate.py`) and Robo-Bun on the AI voice
card (`ui/aivoicepanel.py`). `SetupShow` in the setup guide; `ScribeBunny` in the
download bar (`ui/downloadbar.py`); static pictures in `ui/dialogs.py` and the smug box in
`ui/mainwindow.py`; each theme's card in Settings > Appearance
(`ui/settingspages/appearance.py`: Bun as he looks in that theme, drawn once per theme with
room above him for an upright ear or a tall hat; when the mouse comes onto a card he hops
and waves, `wave_pose`, unless Windows animations are off). To find new ones: grep for `draw_bunny`, `BunnyWidget`, `bunny_pixmap`.

## Poses

His look is the Storybook one: a round head a little wider at the cheeks
(`bunnyfit.head_path`), a small sitting body under it (`bunnyfit.body_path`) with a
tail and a soft tummy patch, two short stubby arms from his shoulders at the sides of his
body (tucked under his head) to round paws, two plain oval feet, sparkle eyes (a dark eye,
a coloured iris glowing up from the bottom, one big shine and two little ones), little
resting brows, a pink nose over a soft double smile, and his ears as his theme's look
says (plain Bun: one up, the other flopped over a little below the middle, its pink
running on to the tip; `bunny.REST_FOLD`, `REST_HINGE`). No fur lines inside him (no toe
or finger lines, no leg creases). Lines are round-capped ink; shading is a couple of soft
fades (`_shade`), never texture.

`draw_bunny` keywords, all 0 when he's at rest: `blink` (0..1, shut above 0.6: happy
arcs, sleepy ones under the nightcap), `mouth` (talking), `ears` (degrees outward),
`swing` (hammer or bat), `sad` (worried face, the ears fold down from the middle, and
with no prop his paws come up in front of his chest, hoping), `angry` (cross brows and the
vein mark; with no prop his arms fold under his chin), `nightcap` (asleep), `robot` (Robo-Bun), `smug`,
`led` (Robo-Bun's LEDs brighter, 0..1), `nod` (his head tilted on his neck, degrees),
`dip` (his head dropped, canvas units), `look` (his eyes, -1..1 left to right) and
`wave` (None, or -1..1: his right paw up by his cheek on a short arm, swung side to side
as he says hello; no prop): the
body, and what's round his neck (`bunny.BODY_PIECES`), stay put. His arms move between
`bunny.ARMS_REST`, `ARMS_HOPE` and `ARMS_CROSS` (bend and paw per arm, from `SHOULDERS`),
eased by `sad` and `angry`, so he never snaps between poses. A prop that needs a paw takes
that arm (`bunny.ONE_PAW`, `bunny.BOTH_PAWS`, the paw's spot in `bunny.PROP_PAWS`): it
reaches out from behind his body to the prop, which draws the paw holding it. `BunnyWidget` gives him his
head tilts on top (its pose's `tilt`, added to `nod`): a slow curious lean, further over
when he's hoping, into the cup he's listening with, side to side as he hops, lolled
over asleep. Bun mode's dances
(`BunnyWidget.set_groove`, `_moves`) use them to headbang and nod on the beat. Props:
`bunny.PROPS` (`hammer_broken`: the failed build's snapped plank and headless hammer).
Everything an act shows stays inside the widget's own box: a widget is only a little wider
than Bun, so moving him sideways out of view slices him at its edge. Squash, shrink or fade
him instead (the build act dives into its cloud, the setup show fades out before the edge).
What gets built is drawn on the canvas at `bunny.PLANK_SPOT` / `bunny.GADGET_SCREEN`.
Animations never draw Bun themselves: they work out these numbers per frame and call
`draw_bunny`, so a new piece of drawing in `bunny.py` or `bunnyfit.py` shows up in every
animation at once.

## Skits

Now and then an idle `BunnyWidget` plays his theme's skit (`ui/bunskits.py`) instead of a
fidget: everywhere he idles (the empty board, Bun mode, the YouTube search). A skit is a
function of its time alone: it adds to his pose, hides the outfit pieces it moves and
queues drawings behind him, with him (held things) or in front, on the canvas. No words
(only "!" and "?"), so nothing to translate. Dark, the default, has his DJ act. A new theme with an outfit gets a skit in
`bunskits.SKITS`; one without juggles. `tests/test_bunnywidget.py`
plays every theme's skit through.

## Looks

Besides an outfit, every theme gives him a look (`bunnyfit.LOOKS`, read with
`bunnyfit.look()`): his fur colour, which ear flops (`"up"`: neither, `"left"` /
`"right"`: the viewer's, `"both"`) and extras (`"chomp"`: a bite out of the edge of an
upright ear, `"earring"`: a gold hoop through one, `"shiner"`: a black eye, `"bandaid"`: a
plaster on his cheek, `"freckles"`), his tail (`bunnyfit.TAILS`: `"round"`, `"fluffy"`
with soft tufts, `"long"`, a pointy `"tuft"`, a `"heart"`), the colour low in his eyes
(`"iris"`), inside his ears (`"inner"`) and his nose (`"nose"`), fur markings
(`"pattern"` from `bunnyfit.PATTERNS`: a `"patch"` over his left eye, `"spots"`, a
`"mask"` round both eyes with a stripe of fur down the middle, all in `"marks"`), his
tummy patch colour (`"belly"`) and pad prints under his feet (`"pads"`: a big pad and three
toe beans, plain shapes with no lines). Markings are clipped to his head and body; an eye
on dark markings gets the light rim and face lines dark fur gets, and his smug lids take
the markings' colour. A theme that isn't listed is plain Bun,
`bunnyfit.VANILLA`: Dark, the default, stays plain. `draw_bunny(..., kit=None)` uses the
current theme's look; pass `kit=bunnyfit.VANILLA` for plain Bun (installer art). On dark fur
(lightness under 0.45) his face is drawn in light lines (`bunny.FACE_LIGHT`), his eyes get a
light rim and his tummy patch is lighter than his fur, so his face still reads. Robo-Bun
keeps his own metal look. A sweater gives his arms sleeves in its colour
(`bunnyfit.sleeve`). `tests/test_bunnyfit.py` checks every look names a real theme and
every change shows.

## Outfits

`draw_bunny(..., outfit=None)` wears the current theme's outfit (`bunnyfit.outfit()`);
`outfit=()` is plain Bun. The layers, in the order they're painted:

| Layer | Painted | Pieces |
| --- | --- | --- |
| `behind` | first, behind even his ears | moon |
| `back` | after his body, before his head | hood, hazmat hood, cape collar |
| `under` | on his head, under the headphones | beanie, frog hat, snapback, bandana, eye shade |
| `over` | after the headphones (and nightcap) | crown, hats, horns, flowers, mint sprig, pencil, dizzy stars |
| `face` | after his face, before the prop in his paw | glasses, spiral eyes, laser eyes, fangs, clown nose, sweater, turtleneck, badge, bow tie, scarf, lei, hood strings |

Rules the drawing keeps:

- Robo-Bun wears no outfit.
- The nightcap replaces anything in `bunnyfit.HATS` and takes off his glasses
  (`bunnyfit.EYEWEAR`); neck pieces stay on.
- Glasses you can't see through (`bunnyfit.HIDE_EYES`) hide his smug lids and tears, and
  his smug brows lift clear of the lenses.
- Laser eyes switch off while his eyes are shut (`blink > 0.6`).
- A piece clipped to his head redraws only the part of his outline it covered, never the
  whole ellipse (on Hoot that line would cross his face).
- His headphones are the theme's `accent`; hats and neck pieces that follow the theme use
  `accent2`, so the two don't blend.
- Dark (the default, and the installer art) and High Contrast wear no outfit; Dark has no
  look either (plain Bun).

To add an outfit: draw the piece as a function in `bunnyfit.py` on the 100 x 120 canvas
(head: `head_path()`, about the 68 x 56 oval centred at 50, 64; eyes at `EYES` (x 35.5 and
64.5) on `EYE_Y` (63); ear bases at 37, 48 and 63, 48; neck about y 90), add it to `PIECES` with its layer (and to `HATS` if
it sits on his head), list it under the theme in `OUTFITS`, then check the sheets.
`tests/test_bunnyfit.py` checks every listed piece exists and draws.

### Hoot wears them too

Hoot has the same Storybook look: a round teal egg with two soft feather points on
each cheek, curved tufts, a joined cream mask round big glossy eyes (shines placed as
Bun's), an amber beak (`beak` 0..1 opens it: he cheers, he hoots while he begs), a
scalloped belly, wings with feather tips as his only forelimbs, and three-toed feet.

Hoot the owl (`soundboard/style/owl.py`, the Triggers tab before Onion Watch is installed)
wears the same theme outfit. He has no pieces of his own: `owl._fit` moves Bun's pieces
onto his shape (head 12 higher, eyes 32 apart and scaled to match, neck pieces just under his
beak; `OWN_PLACE` for the ones that need their own spot (tall hats stay full size: an
oversized hat is the look); `NOT_ON_OWL` for the ones that don't suit him) and `draw_owl` calls it at
the same five layers. `owl_image` (dialog artwork, his own
teal) stays plain. A new piece drawn for Bun shows up on Hoot too: check it with
`bun_sheet.py owls` and `bun_sheet.py owl`. Both files are in the style kit
(`soundboard/style/`), which Onion Watch copies whole, so Hoot wears the same outfits
there; inside the board's Triggers tab the add-on draws him with the board's kit.

**Anything that caches a picture of Bun must key it on `theme.current_name`** (his
outfit and look), not only the accent colour: see `ScribeBunny._layer`.

## Checking a change

```
.venv\Scripts\python scripts\pictures\bun_sheet.py outfits   # every theme's outfit
.venv\Scripts\python scripts\pictures\bun_sheet.py poses     # outfits x every pose
.venv\Scripts\python scripts\pictures\bun_sheet.py live      # the real widgets, frame by frame
.venv\Scripts\python scripts\pictures\bun_sheet.py owls      # Hoot in every theme's outfit
.venv\Scripts\python scripts\pictures\bun_sheet.py owl       # Hoot's poses in a few outfits
```

`live` swaps `time.monotonic` for a fake clock and steps each widget's own timer
(`_step` / `_tick`) so every act (talking, notes, the build act, begging, napping, the
cross face and bat, Robo-Bun, the setup show, the download scribe) is caught at a known
moment. Sheets go to `%TEMP%\bun-sheets`. Look at every sheet the change touches before sending pictures.
