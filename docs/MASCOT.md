# Bun the mascot: where he lives and how he animates

Read this before changing Bun's drawing, an outfit, or any animation he's in. He's
drawn in code with QPainter (no image files), so every pose, prop and outfit is a few
lines in the files below.

## The files

| File | What it does |
| --- | --- |
| `soundboard/ui/bun/bunny.py` | `draw_bunny(p, rect, prop, **pose)`: one still picture of Bun on a 100 x 120 canvas. Everything else calls this. Also `bunny_image` / `bunny_pixmap` for static pictures (with `ROOM_TOP` above him and `ROOM_SIDE` either side: an upright ear and a wide collar reach past his canvas). |
| `soundboard/style/bunnyfit.py` | His outfit per theme (`OUTFITS`) and the pieces' drawing (`PIECES`), in layers `draw_bunny` calls between its own; his look per theme (`LOOKS`: fur, floppy ears, extras). |
| `soundboard/ui/bun/bunnywidget.py` | `BunnyWidget`: Bun alive. Bobs, blinks, flicks ears, idle fidgets (yawn, look round, foot tap), talks with the mic level, music notes, begging bubbles, naps, the click cheer, the build act (dives into a dust cloud, rummages, hammers a speaker together; the snap when it fails), Robo-Bun's version (gadget screen, sparks, LED pulse), the Pong dare (cross face, bat). Its `pose(now)` turns the clock into `draw_bunny`'s keywords plus his squash (`sx`, `sy`), lean (`angle`) and fade (`alpha`). |
| `soundboard/ui/setup/setupshow.py` | `SetupShow(BunnyWidget)`: the mic set-up show (toolbox, speaker parts popping on, progress dots). |
| `soundboard/ui/bun/scribebun.py` | `ScribeBunny`: the download bar's picture, Bun writing the tune on a scroll in a 56 x 59 slot. Caches pictures of him per pose in `_bun` and the last frame drawn. |
| `soundboard/ui/bun/pilotbun.py` | `PilotBunny`: the Languages card's install picture, Bun in a little red 3D plane flying low over a lit, turning 3D Earth (real coasts, simplified, with clouds, a night side and glowing air) in a 132 x 104 slot. Flies for `REST_S` after he's shown, hovered or clicked, and all through the install (`set_flying`); still in lite mode. Caches pictures of him per pose in `_bun` and the last frame drawn. |
| `soundboard/ui/bun/bunacts.py` | `ActBunny(BunnyWidget)`: Bun beside a window's title playing one act on a loop (skit-style functions of time), `play(act)` for a one-off, `tune(speed, semitones)` to hurry him and stretch or squash him; still in lite mode. The acts: `snipping` (Edit sound), `mic_check` / `rec_light` (Record a sound), `in_bin` / `bring_back` / `bye` (Recently deleted), `box_pat` / `box_run` / `box_open` (Free sound packs), `present` (What's new). |
| `soundboard/ui/bun/bunpong.py` | The Pong Easter egg; draws Bun with his bat (or the star when he wins). |
| `soundboard/ui/bun/splash.py` | The start-up splash: the panel, the name and the dots; Bun's part is `splashacts.py`. |
| `soundboard/ui/bun/splashacts.py` | Bun's start-up acts, one picked at random each launch (`pick`): headbang, karaoke, build, batting, party, sleepy (the favourite at night), Robo-Bun booting, plugging in his headphones, hop, drums, ear wiggle, peekaboo, spin. rare launches (`RARES`, rarest first): Golden Bun 1 in 50, Ice Bun 1 in 500, Galaxy Bun 1 in 5000 (planets orbit him), Rainbow Bun 1 in 50000 (his fur cycles the hues), each with a glowing border in its colour and its tier and drop rate (`Rare · 1/500`, tier names from `splash.tier_name`: Uncommon, Rare, Legendary, Super Rare) on a taller card under the dots; the season's pieces by month (`SEASONS`: October the Halloween hat and fangs, December the Santa hat); his goodbye wave as the window comes up. Every act reads in its first half second and loops; `still` is Bun at rest for Windows' Animation effects off. An act that hides part of him (peekaboo's hole) draws him on a picture first (`_bun_above`): `draw_bunny` sets clips of its own. |
| `scripts/pictures/make_bunny.py`, `scripts/pictures/make_favicon.py` | Installer art and icons: always plain Bun (`outfit=()`, `kit=VANILLA`). |
| `scripts/pictures/bun_sheet.py` | Picture sheets for checking a change by eye (below). |
| `scripts/pictures/site_mascots.py` | The website's Bun and Hoot: runs `draw_bunny` / `draw_owl` in each theme of the site's look switcher through a painter that writes SVG, into `site/index.html` (the parts the page moves in their own groups) and `site/home.css` (each look's colours). Rerun it after changing either drawing. |

## Every place he shows up

`BunnyWidget` in the setup guide (`ui/setup/setupwizard.py`, a prop per page), the chat guides
(`ui/setup/chatguide.py`, `ui/setup/streamguide.py`), Bun mode (`ui/bun/bunmode.py`, the window as a
floating Bun: `in_background=True` keeps him moving behind a game), the empty board (`ui/kit/padgrid.py`), the Apps tab
(`ui/apps/appspanel.py`, sad and begging; `rest_after_s=30`: still after 30 s with nothing playing, until a sound or a click), the Radio map (`ui/radio/mapparts.py`), the YouTube search
(`ui/sounds/ytwaiting.py`), beside the titles of Edit sound, Record a sound, Recently deleted, Free sound packs and What's new (`bunacts.ActBunny`), left of the Live controls title (`ui/sounds/speedpitch.py` `DjBunny`: his
`bunskits.mixing` act on a loop, tapping sound pads and scratching a record), the mic part update (`ui/setup/micupdate.py`), the *Enjoying Onion Board?* bar (`ui/window/enjoycontrol.py`, holding up the `survey` clipboard) Robo-Bun on the AI voice
card (`ui/voice/aivoicepanel.py`) and Pilot Bun on the Languages card's install (`ui/voice/speechinstall.py`). `SetupShow` in the setup guide; `ScribeBunny` in the
download bar (`ui/window/downloadbar.py`); static pictures in `ui/sounds/dialogs.py` and the smug box in
`ui/window/mainwindow.py`; each theme's card in Settings > Appearance
(`ui/settings/appearance.py`: Bun as he looks in that theme, drawn once per theme with
room above him for an upright ear or a tall hat; when the mouse comes onto a card he hops
and waves, `wave_pose`, unless Windows animations are off). To find new ones: grep for `draw_bunny`, `BunnyWidget`, `bunny_pixmap`.

## Poses

His look is the Storybook one: a round head a little wider at the cheeks
(`bunnyfit.head_path`), a small sitting body under it (`bunnyfit.body_path`) with a
tail, a soft tummy patch with a little belly button and a fluffy poof of lighter fur on his
chest under his chin (`bunny._poof`: pointed tufts, no ink outline), two short stubby arms from his shoulders at the sides of his
body (tucked under his head) to round paws, two long oval feet, sparkle eyes (a dark eye,
a coloured iris glowing up from the bottom, one big shine and two little ones), little
resting brows, a pink nose over a soft double smile, and his ears as his theme's look
says (plain Bun: both up, their top halves curving softly out and down, `bunny.DROOP`;
a floppy ear, in the looks that have one, flops right over a little below the middle, its
pink running on to the tip and round the bend; `bunny.REST_FOLD`, `REST_HINGE`). An ear is three colours at most: the
ink outline, his fur and the inner colour, no shading. No fur lines inside him (no toe
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
`bunny.PROPS` (`hammer_broken`: the failed build's snapped plank and headless hammer;
`survey`: a clipboard held up in both paws, facing you).
Everything an act shows stays inside the widget's own box: a widget is only a little wider
than Bun, so moving him sideways out of view slices him at its edge. Squash, shrink or fade
him instead (the build act dives into its cloud, the setup show fades out before the edge).
What gets built is drawn on the canvas at `bunny.PLANK_SPOT` / `bunny.GADGET_SCREEN`.
Animations never draw Bun themselves: they work out these numbers per frame and call
`draw_bunny`, so a new piece of drawing in `bunny.py` or `bunnyfit.py` shows up in every
animation at once.

## Skits

Now and then an idle `BunnyWidget` plays his theme's skit (`ui/bun/bunskits.py`) instead of a
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
tummy patch colour (`"belly"`) and pad prints under his feet (`"pads"`: a heart-shaped pad
and four toe beans with a little shine, plain shapes with no lines, well inside the foot;
smaller on his waving paw, toes up). Markings are clipped to his head and body; an eye
on dark markings gets the light rim and face lines dark fur gets, and his smug lids take
the markings' colour. A theme that isn't listed is plain Bun,
`bunnyfit.VANILLA`: Dark, the default, stays plain. `draw_bunny(..., kit=None)` uses the
current theme's look; pass `kit=bunnyfit.VANILLA` for plain Bun (installer art). On dark fur
(lightness under 0.45) his face is drawn in light lines (`bunny.FACE_LIGHT`), his eyes get a
light rim and his tummy patch is lighter than his fur, so his face still reads. Robo-Bun
keeps his own metal look. A sweater gives his arms sleeves in its colour
(`bunnyfit.sleeve`). `tests/test_bunnyfit.py` checks every look names a real theme and
every change shows. A bit of him drawn outside `draw_bunny` (a skit's paw, the scribe's
paw on the quill, his ears out of the build cloud) takes its colours from
`bunny.look_colour("fur")` / `look_colour("inner")`, never `FUR` or `PINK` (plain
Bun's), or a white paw shows on a brown Bun. A `BunnyWidget` whose `pad` is too small
for an upright ear at the top of his bob gets the difference above him (`_head`).

## Outfits

`draw_bunny(..., outfit=None)` wears the current theme's outfit (`bunnyfit.outfit()`);
`outfit=()` is plain Bun. The layers, in the order they're painted:

| Layer | Painted | Pieces |
| --- | --- | --- |
| `behind` | first, behind even his ears | moon, firework burst |
| `back` | after his body, before his head | hood, hazmat hood, cape collar |
| `under` | on his head, under the headphones | beanie, frog hat, snapback, bandana, eye shade |
| `over` | after the headphones (and nightcap) | crown, hats, horns, flowers, mint sprig, pencil, sparkler, dizzy stars |
| `face` | after his face, before the prop in his paw | glasses, spiral eyes, laser eyes, fangs, clown nose, sweater, turtleneck, badge, bow tie, scarf, lei, glow stick, hood strings |

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
teal) stays plain.

Each theme also has its own Hoot, like Bun's looks: `owl.LOOKS` sets his feathers and
wings, the colour low in his eyes, his face mask and belly, the marks on his belly
(`MARKS`: plain Hoot's thin scallops, or bold spots, chevrons, hearts, none), his ear
tufts (`TUFTS`: point, round, tall, swept, tiny), his beak and his toes. Keep them
simple bold shapes, no feather lines. Dark and High Contrast are plain teal Hoot
(`VANILLA`); `owl.look(name)` gives a theme's, `draw_owl(kit=...)` draws one.
`tests/test_owl.py` checks every look names a real theme and every key shows.

A new piece drawn for Bun shows up on Hoot too: check it with
`bun_sheet.py owls` and `bun_sheet.py owl`. Both files are in the style kit
(`soundboard/style/`), which Onion Watch copies whole, so Hoot wears the same outfits
there; inside the board's Triggers tab the add-on draws him with the board's kit.

### What they say when clicked

Each outfit comes with a character, and a click gets a line in it
(`soundboard/style/mascotlines.py`: `bun()` / `hoot()` for the current theme): a sea
captain in Ocean, a wizard in Midnight, Dracula in Vampire, a hacker in Hacker. They're
mixed with the lines the place he sits in gives him (the empty board's "↑ Add sounds!",
Hoot's "↓ that button!"), never the same line twice in a row, and stay up long enough to
read (`read_secs`). A theme with no lines of its own says Dark's. A new theme gets four
lines for Bun and three for Hoot, short enough for one bubble (a longer translation goes
on two lines). `tests/test_mascotlines.py` checks every theme has them.

**Anything that caches a picture of Bun must key it on `theme.current_name`** (his
outfit and look), not only the accent colour: see `ScribeBunny._layer`.
`BunnyWidget` and `OwlWidget` keep their last picture of him (`HOLD`, `_held`): it's
reused until some part of him has moved `HOLD_PX` screen pixels (`SWAY` says how far
each pose key moves him), and a frame where nothing moved isn't painted. A new pose key
that moves him needs its entry in `SWAY` (or `_key`, for one that changes him outright),
or he'll lag behind it; `tests/test_bunny_hold.py` checks the kept picture draws the same.

## Checking a change

```
.venv\Scripts\python scripts\pictures\bun_sheet.py outfits   # every theme's outfit
.venv\Scripts\python scripts\pictures\bun_sheet.py poses     # outfits x every pose
.venv\Scripts\python scripts\pictures\bun_sheet.py live      # the real widgets, frame by frame
.venv\Scripts\python scripts\pictures\bun_sheet.py owls      # Hoot in every theme's look + outfit
.venv\Scripts\python scripts\pictures\bun_sheet.py owl       # Hoot's poses in a few outfits
```

`live` swaps `time.monotonic` for a fake clock and steps each widget's own timer
(`_step` / `_tick`) so every act (talking, notes, the build act, begging, napping, the
cross face and bat, Robo-Bun, the setup show, the download scribe) is caught at a known
moment. Sheets go to `%TEMP%\bun-sheets`. Look at every sheet the change touches before sending pictures.
