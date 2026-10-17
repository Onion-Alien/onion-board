"""What Bun and Hoot say when they're clicked, in each theme's character.

Each theme dresses them up (bunnyfit.OUTFITS, owl.LOOKS), and the outfit comes with a
personality: a sea captain in Ocean, a wizard in Midnight, Dracula in Vampire, a little
witch in Halloween. `bun()` / `hoot()` give the current theme's lines (functions: the
kit can be imported before the language is picked); the widgets mix them with their own
(`BunnyWidget.cheer`, `OwlWidget.cheer`). A theme that isn't listed says Dark's.
"""
from __future__ import annotations

from . import hooks
from .hooks import _


def _bun() -> dict[str, tuple[str, ...]]:
    return {
        "Dark": (_("boing!"), _("again! again!"), _("that tickles!"), _("ready to make noise!")),
        "Light": (_("at your service!"), _("splendid click!"), _("how do you do?"),
                  _("a sound, perhaps?")),
        "Lilac": (_("peace and sounds"), _("such good vibes…"), _("you smell like flowers"),
                  _("float with me~")),
        "Toxic": (_("don't touch me, I'm toxic!"), _("safety first!"), _("I glow a little"),
                  _("is that normal?!")),
        "Ocean": (_("ahoy, matey!"), _("all hands on deck!"), _("land ho!"),
                  _("full steam ahead!")),
        "Cherry Blossom": (_("one petal falls…"), _("breathe in, breathe out"),
                           _("spring is here!"), _("so peaceful…")),
        "Carbon": (_("yo, what's good?"), _("fresh fit, right?"), _("big moves only"),
                   _("let's get it!")),
        "Midnight": (_("abracadabra!"), _("you shall not pass!"), _("poof! magic!"),
                     _("my spell is ready…")),
        "Slate": (_("back in my day…"), _("where are my glasses?"), _("let me think…"),
                  _("ah, a fine choice")),
        "Arctic": (_("brrr! so cold!"), _("warm hands, please?"), _("my ears are frozen!"),
                   _("snow day!")),
        "Paper": (_("shh! library!"), _("chapter one…"), _("I read about clicks"),
                  _("quite interesting!")),
        "High Contrast": (_("HELLO!"), _("I SEE YOU!"), _("CLEAR AND LOUD!"),
                          _("BIG CLICK!")),
        "Vampire": (_("I vant to play sounds!"), _("bleh! bleh!"), _("no garlic, please"),
                    _("the night is young…")),
        "Forest": (_("hug a tree!"), _("the forest says hi"), _("I'm one with the moss"),
                   _("listen… birds!")),
        "Mocha": (_("one more coffee?"), _("I'm an artist"), _("extra foam, please"),
                  _("ooh, bitter!")),
        "Sunset": (_("surf's up!"), _("aloha!"), _("chill, dude"), _("beach day!")),
        "Royal": (_("bow before me!"), _("we are pleased"), _("a royal click!"),
                  _("fetch my crown!")),
        "Onion": (_("I have layers!"), _("don't cry!"), _("peel me gently"),
                  _("onion power!")),
        "Mint": (_("so fresh!"), _("minty!"), _("brush your teeth!"), _("cool breeze~")),
        "Synthwave": (_("totally rad!"), _("to the year 1985!"), _("neon forever!"),
                      _("crank it up!")),
        "Vaporwave": (_("a e s t h e t i c"), _("so smooth…"), _("welcome to the mall"),
                      _("vibes only")),
        "Blood Moon": (_("mwahaha!"), _("the moon is red…"), _("I'm a little devil"),
                       _("fear me! (please)")),
        "Lava": (_("hot hot hot!"), _("don't stand in lava!"), _("let's do this!"),
                 _("I'm on fire!")),
        "Amber Terminal": (_("stop the press!"), _("checking the numbers…"), _("noted."),
                           _("back to work!")),
        "Hacker": (_("I'm in."), _("access granted"), _("hacking your sounds…"),
                   _("nobody saw that")),
        "Flashbang": (_("my eyes!"), _("too bright!"), _("where am I?"), _("everything is white…")),
        "Barbie": (_("so fabulous!"), _("pink is a lifestyle"), _("hi, gorgeous!"),
                   _("let's go party!")),
        "Swamp": (_("ribbit!"), _("get out of my swamp!"), _("mud bath time"),
                  _("smells like home")),
        "Deep Fried": (_("BRUH"), _("laser eyes on!"), _("too much salt"),
                       _("I'm extra crispy")),
        "Retro 98": (_("loading… 3%"), _("please wait…"), _("it's 1998!"),
                     _("insert disk 2")),
        "Comic Sans": (_("honk honk!"), _("knock knock!"), _("got your nose!"),
                       _("very serious bunny")),
        "Halloween": (_("trick or treat!"), _("boo! scared you?"), _("got any candy?"),
                      _("my broom's parked outside")),
        "Brainrot": (_("no cap!"), _("this is so real"), _("bro is clicking me"),
                     _("rent free!")),
    }


def _hoot() -> dict[str, tuple[str, ...]]:
    return {
        "Dark": (_("hoo-ray!"), _("I see everything!"), _("got my eyes on you")),
        "Light": (_("good day to you!"), _("how kind of you"), _("most delightful!")),
        "Lilac": (_("I see good vibes"), _("float, little feathers…"), _("so dreamy~")),
        "Toxic": (_("hazard spotted!"), _("all clear… I think"), _("stay back, it glows!")),
        "Ocean": (_("ahoy from the crow's nest!"), _("ship on the horizon!"),
                  _("I'm on lookout!")),
        "Cherry Blossom": (_("watch the petals fall"), _("a quiet moment…"),
                           _("so pretty, hoo~")),
        "Carbon": (_("eyes on the prize"), _("I see a win"), _("let's run it!")),
        "Midnight": (_("I foresee… a click!"), _("my crystal ball says yes"),
                     _("whooo summoned me?")),
        "Slate": (_("let me check my notes"), _("hmm, fascinating"), _("in my experience…")),
        "Arctic": (_("frozen feathers!"), _("brr, hoo hoo hoo!"), _("I see snow!")),
        "Paper": (_("hoo said that?"), _("I read the whole thing"), _("footnote spotted!")),
        "High Contrast": (_("I SEE IT!"), _("HOO HOO!"), _("WATCHING!")),
        "Vampire": (_("we creatures of the night…"), _("I see in the dark!"),
                    _("bats are my friends")),
        "Forest": (_("hoo hoo, the woods!"), _("a mouse? where?!"), _("I live in a tree")),
        "Mocha": (_("I need coffee to watch"), _("night owl life"), _("one more episode…")),
        "Sunset": (_("what a view!"), _("sunset spotted!"), _("so chill, hoo")),
        "Royal": (_("the royal watcher"), _("we see all"), _("make way!")),
        "Onion": (_("I see layers!"), _("my eyes are watering"), _("onion vision!")),
        "Mint": (_("fresh eyes!"), _("cool, cool, cool"), _("a mint view")),
        "Synthwave": (_("neon eyes!"), _("watch the grid!"), _("radical!")),
        "Vaporwave": (_("v i e w i n g"), _("watching… slowly"), _("so retro")),
        "Blood Moon": (_("the moon is watching"), _("hoo dares wake me?"), _("spooky!")),
        "Lava": (_("watch out, it's hot!"), _("eyes on the fire"), _("intense!")),
        "Amber Terminal": (_("noted in the log"), _("watching the numbers"), _("all on file")),
        "Hacker": (_("tracking you…"), _("signal found"), _("I see your packets")),
        "Flashbang": (_("I can't see!"), _("everything is white!"), _("blinded!")),
        "Barbie": (_("I see fabulous!"), _("pink alert!"), _("love that!")),
        "Swamp": (_("I see a frog!"), _("swamp watch!"), _("bog life")),
        "Deep Fried": (_("HOOOO"), _("eyes are frying"), _("so crispy")),
        "Retro 98": (_("buffering…"), _("now loading"), _("please be kind, rewind")),
        "Comic Sans": (_("hoo's there?"), _("owl be watching!"), _("whooo's laughing?")),
        "Halloween": (_("hoo goes there?!"), _("I saw a ghost!"), _("spooky season, hoo!")),
        "Brainrot": (_("watching brainrot"), _("ok that's crazy"), _("no thoughts, just eyes")),
    }


def bun(name: str | None = None) -> tuple[str, ...]:
    """What Bun says when clicked in theme `name` (default: the current theme)."""
    lines = _bun()
    return lines.get(name or hooks.theme_name(), lines["Dark"])


def hoot(name: str | None = None) -> tuple[str, ...]:
    """What Hoot says when clicked in theme `name` (default: the current theme)."""
    lines = _hoot()
    return lines.get(name or hooks.theme_name(), lines["Dark"])


def read_secs(text: str, least: float = 1.6) -> float:
    """How long a line stays up: enough to read it, and never less than `least`."""
    return max(least, 0.8 + 0.06 * len(text))


def pick(rng, lines, last: str = "") -> str:
    """A line from `lines`, not the one said `last` (when there's another)."""
    pool = [t for t in lines if t != last] or list(lines)
    return rng.choice(pool) if pool else ""
