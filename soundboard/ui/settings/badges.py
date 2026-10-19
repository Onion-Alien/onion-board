"""Settings > Achievements' badges, drawn: Bun (ui/bun/bunny.py draw_bunny) in a pose,
outfit or rare look that fits each achievement, inside a rim in the achievement's
rarity colour, sometimes with an icon beside him for what it's about. No picture files:
a badge is drawn once per size and kept (badge()).

SCENES says each badge's scene: draw_bunny's keywords ("prop", poses, "outfit", "kit"
or a rare look's name in "rare"), an icons.SHAPES name as "glyph" (on a chip at the
bottom right) and "bg" for a backdrop of its own (night, stars, rainbow, seasons)."""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QConicalGradient, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)

from soundboard.ui.kit import icons

# rarity -> its rare loading screen (splashacts.RARES): its colour and its look
TIER_SPLASH = {"uncommon": "gold", "rare": "ice", "legendary": "galaxy", "super": "rainbow"}
COMMON = "#a3a9b6"   # Common's silver
INK = "#2b2340"      # Bun's ink, for a glyph chip's ring

# Each achievement's scene (see the module docstring).
SCENES: dict[str, dict] = {
    "first_blood": {"outfit": ("party",), "wave": 0.6, "mouth": 0.4, "glyph": "play"},
    "spammer": {"outfit": ("laser",), "mouth": 0.9, "ears": 18, "glyph": "flame"},
    "menace": {"outfit": ("horns", "fangs"), "smug": True, "glyph": "flame"},
    "collector": {"outfit": ("collar",), "wave": 0.3, "mouth": 0.3, "glyph": "sounds"},
    "hoarder": {"smug": True, "outfit": ("crown",), "glyph": "sounds"},
    "dragon_hoard": {"outfit": ("horns", "crown"), "smug": True, "glyph": "sounds", "bg": "gold"},
    "new_voice": {"outfit": ("clown_nose",), "mouth": 0.7, "glyph": "voice"},
    "voice_actor": {"prop": "mic", "mouth": 0.7, "glyph": "mic"},
    "method_actor": {"prop": "star", "outfit": ("bowtie",), "mouth": 1.0, "nod": 8},
    "station_hopper": {"outfit": ("eyeshade",), "kick": 1.0, "wave": -0.4, "glyph": "radio"},
    "radio_head": {"outfit": ("propeller",), "prop": "headphones", "glyph": "radio"},
    "critic": {"outfit": ("beret",), "smug": True, "glyph": "like"},
    "tastemaker": {"outfit": ("beret", "bowtie"), "prop": "star"},
    "regular": {"outfit": ("sweater",), "wave": 0.5, "mouth": 0.3, "glyph": "history"},
    "veteran": {"outfit": ("readers", "bowtie"), "smug": True, "glyph": "history"},
    "golden_bun": {"rare": "gold", "bg": "sparkle"},
    "ice_bun": {"rare": "ice", "bg": "sparkle"},
    "galaxy_bun": {"rare": "galaxy", "bg": "starslight"},
    "rainbow_bun": {"rare": "rainbow", "bg": "rainbow"},
    "catch_em_all": {"trio": True, "bg": "stars"},
    "gamer_bun": {"prop": "bat", "smug": True, "outfit": ("snapback",)},
    "sore_loser": {"prop": "bat", "sad": 1.0},
    "arcade_rat": {"outfit": ("pixel_shades",), "smug": True, "glyph": "gamepad"},
    "rise_and_shine": {"nightcap": True, "blink": 0.75, "mouth": 0.8},
    "chatterbox": {"mouth": 1.0, "look": 0.6, "glyph": "chat"},
    "who_hoots": {"hoot": True, "look": 1.0, "mouth": 0.5},
    "bun_mode": {"wave": 0.0, "mouth": 0.3, "glyph": "bun"},
    "panic_button": {"sad": 0.7, "ears": 25, "glyph": "stop_all"},
    "silent_but_deadly": {"smug": True, "look": -0.8, "glyph": "volume_off"},
    "gremlin": {"outfit": ("fangs",), "smug": True, "bg": "night", "glyph": "ghost"},
    "pack_rat": {"outfit": ("bandana",), "mouth": 0.3, "glyph": "archive"},
    "defector": {"outfit": ("shades",), "smug": True, "look": -1.0, "glyph": "download"},
    "clip_it": {"outfit": ("pencil",), "mouth": 0.4, "look": 0.6, "glyph": "scissors"},
    "producer": {"prop": "headphones", "smug": True, "glyph": "sliders"},
    "link_grabber": {"outfit": ("captain",), "smug": True, "look": 0.7, "glyph": "link"},
    "hotkey_hero": {"outfit": ("visor",), "mouth": 0.4, "glyph": "keyboard"},
    "second_chances": {"outfit": ("bow",), "wave": 0.5, "mouth": 0.5, "glyph": "trash"},
    "mic_check": {"prop": "mic", "look": 0.4, "mouth": 0.3, "glyph": "volume"},
    "puppet_master": {"outfit": ("strings",), "smug": True, "glyph": "apps"},
    "shapeshifter": {"outfit": ("frog",), "mouth": 0.5, "glyph": "shuffle"},
    "mad_scientist": {"outfit": ("hazmat", "round_glasses"), "smug": True, "glyph": "sliders"},
    "polyglot": {"outfit": ("scarf",), "mouth": 0.7, "glyph": "speech"},
    "robot_mouth": {"robot": True, "led": 1.0, "mouth": 0.6},
    "dice_roll": {"outfit": ("wizard",), "wave": 0.8, "mouth": 0.5, "glyph": "shuffle"},
    "world_tour": {"outfit": ("lei", "shades"), "mouth": 0.4, "glyph": "radio"},
    "night_owl": {"prop": "headphones", "blink": 0.35, "bg": "night", "glyph": "radio"},
    "contributor": {"outfit": ("santa",), "wave": 0.7, "mouth": 0.5, "glyph": "upload"},
    "fashionista": {"outfit": ("heart_glasses", "scarf"), "smug": True},
    "rainbow_road": {"outfit": ("shades",), "mouth": 0.4, "bg": "rainbow"},
    "seasons": {"outfit": ("flower_crown",), "mouth": 0.3, "bg": "seasons"},
    "onion_onion": {"outfit": ("onion",), "smug": True, "glyph": "tor"},
    "off_the_grid": {"outfit": ("pom_beanie",), "blink": 0.5, "mouth": 0.2, "glyph": "offline"},
    "remote_control": {"outfit": ("turtleneck",), "wave": 0.4, "mouth": 0.3, "glyph": "phone"},
    "streamer": {"prop": "mic", "outfit": ("snapback",), "glyph": "twitch"},
    "watcher": {"outfit": ("readers",), "look": 1.0, "glyph": "eye"},
    "no_life": {"outfit": ("dizzy",), "blink": 0.3, "glyph": "trophy"},
}


def tier_colour(tier: str) -> QColor:
    """A rarity's colour: its rare loading screen's glow; Common, silver."""
    if tier in TIER_SPLASH:
        from soundboard.ui.bun import splashacts
        return QColor(splashacts.RARES[TIER_SPLASH[tier]][2])
    return QColor(COMMON)


def _rare_kit(name: str) -> dict:
    from soundboard.style import bunnyfit
    from soundboard.ui.bun import splashacts
    kit = {**bunnyfit.VANILLA, **splashacts.RARES[name][1]}
    if name == "rainbow":   # (the loading screen cycles it; a badge keeps one hue)
        kit["fur"], kit["inner"] = "#ffd6e8", "#9fd8ff"
    return kit


def _bun(p: QPainter, rect: QRectF, scene: dict, rare: str | None = None) -> None:
    from soundboard.style import bunnyfit
    from soundboard.ui.bun import bunny
    pose = {k: v for k, v in scene.items()
            if k not in ("glyph", "bg", "rare", "trio", "hoot", "prop")}
    pose.setdefault("outfit", ())
    pose["kit"] = _rare_kit(rare) if rare else dict(bunnyfit.VANILLA)
    bunny.draw_bunny(p, rect, scene.get("prop"), **pose)


def _backdrop(p: QPainter, r: QRectF, colour: QColor, kind: str | None) -> None:
    c = r.center()
    if kind == "night":
        g = QRadialGradient(c, r.width() / 2)
        g.setColorAt(0, QColor("#2c2a5a"))
        g.setColorAt(1, QColor("#121029"))
        p.fillRect(r, g)
        p.setBrush(QColor("#fff3b0"))
        p.setPen(Qt.PenStyle.NoPen)
        moon = QPainterPath()
        moon.addEllipse(QPointF(r.left() + r.width() * 0.25, r.top() + r.height() * 0.25),
                        r.width() * 0.09, r.width() * 0.09)
        cut = QPainterPath()
        cut.addEllipse(QPointF(r.left() + r.width() * 0.29, r.top() + r.height() * 0.22),
                       r.width() * 0.08, r.width() * 0.08)
        p.drawPath(moon.subtracted(cut))
        _dots(p, r, QColor("#ffffff"), 9, 1)
        return
    if kind == "rainbow":
        g = QConicalGradient(c, 90)
        for i, hue in enumerate((0, 0.13, 0.3, 0.5, 0.65, 0.8, 1.0)):
            g.setColorAt(i / 6, QColor.fromHsvF(hue % 1.0, 0.45, 0.95))
        p.fillRect(r, g)
        return
    if kind == "seasons":
        half_w, half_h = r.width() / 2, r.height() / 2
        for (dx, dy), col in zip(((0, 0), (1, 0), (0, 1), (1, 1)),
                                 ("#cfe8ff", "#ffd6ea", "#fff1a8", "#ffc79a")):
            p.fillRect(QRectF(r.left() + dx * half_w, r.top() + dy * half_h, half_w, half_h),
                       QColor(col))
        return
    # the rarity's own: a darker shade of it, lighter in the middle
    g = QRadialGradient(QPointF(c.x(), c.y() - r.height() * 0.1), r.width() * 0.62)
    light = kind in ("gold", "starslight")   # (Galaxy Bun's dark fur needs a lighter sky)
    g.setColorAt(0, colour.lighter(125) if light else colour.darker(150))
    g.setColorAt(1, colour.darker(170) if light else colour.darker(260))
    p.fillRect(r, g)
    if kind in ("sparkle", "gold"):
        _dots(p, r, colour.lighter(160), 7, 2)
    elif kind in ("stars", "starslight"):
        _dots(p, r, QColor("#f4f0ff"), 14, 3)


def _dots(p: QPainter, r: QRectF, colour: QColor, n: int, seed: int) -> None:
    """Little sparkles round the edge (the same each time: the badge is a still)."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    for i in range(n):
        a = (i * 2.399 + seed) % (2 * math.pi)            # the golden angle: spread out
        d = 0.33 + 0.12 * ((i * 7 + seed) % 5) / 4
        x = r.center().x() + math.cos(a) * r.width() * d
        y = r.center().y() + math.sin(a) * r.height() * d * 0.9
        s = r.width() * (0.012 + 0.008 * ((i + seed) % 3))
        p.drawEllipse(QPointF(x, y), s, s)


def paint(p: QPainter, r: QRectF, ach_id: str, tier: str) -> None:
    """The badge for `ach_id` (rarity `tier`) filling the square `r`."""
    scene = SCENES.get(ach_id, {})
    colour = tier_colour(tier)
    rim = max(2.0, r.width() * 0.06)
    inner = r.adjusted(rim, rim, -rim, -rim)
    circle = QPainterPath()
    circle.addEllipse(inner)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setClipPath(circle)
    _backdrop(p, inner, colour, scene.get("bg"))
    w = inner.width()
    if scene.get("trio"):   # the three rare Buns side by side, the middle one in front
        for rare, dx, dy, k in (("gold", -0.27, 0.12, 0.62), ("galaxy", 0.27, 0.12, 0.62),
                                ("ice", 0.0, 0.06, 0.74)):
            bw = w * k
            box = QRectF(inner.center().x() + dx * w - bw / 2, inner.top() + w * (0.14 + dy),
                         bw, bw * 1.2)
            _bun(p, box, {"mouth": 0.3}, rare)
    elif scene.get("hoot"):   # Bun and Hoot side by side
        from soundboard.style import owl
        bw = w * 0.72
        _bun(p, QRectF(inner.left() + w * 0.02, inner.top() + w * 0.2, bw, bw * 1.2), scene)
        owl.draw_owl(p, QRectF(inner.left() + w * 0.48, inner.top() + w * 0.34, w * 0.56,
                               w * 0.67), look=-1.0, beak=0.8, wave=0.5)
    else:   # Bun big, his ears near the top and his paws (and what he holds) in sight
        bw = w * 0.78
        box = QRectF(inner.center().x() - bw / 2, inner.top() + w * 0.09, bw, bw * 1.2)
        _bun(p, box, scene, scene.get("rare"))
    p.restore()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ring = QColor(colour)
    p.setPen(QPen(ring, rim))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(r.adjusted(rim / 2, rim / 2, -rim / 2, -rim / 2))
    p.setPen(QPen(ring.lighter(150), max(1.0, rim * 0.22)))   # a highlight on the rim
    p.drawArc(r.adjusted(rim * 0.4, rim * 0.4, -rim * 0.4, -rim * 0.4), 40 * 16, 100 * 16)
    glyph = scene.get("glyph")
    if glyph:   # what it's about, on a chip over the rim at the bottom right
        d = r.width() * 0.36
        chip = QRectF(r.right() - d * 0.98, r.bottom() - d * 0.98, d, d)
        p.setPen(QPen(QColor(INK), max(1.0, r.width() * 0.025)))
        p.setBrush(colour)
        p.drawEllipse(chip)
        g = int(d * 0.6)
        ink = "#1b1b1f" if colour.lightnessF() > 0.6 else "#ffffff"
        p.drawPixmap(QRectF(chip.center().x() - g / 2, chip.center().y() - g / 2, g, g),
                     icons.pixmap(glyph, g * 2, ink), QRectF(0, 0, g * 2, g * 2))
    p.restore()


def badge(ach_id: str, tier: str, size: int, locked: bool = False,
          dpr: float = 1.0) -> QPixmap:
    """The badge as a `size` px pixmap (at `dpr`); `locked`: grey and faded. Kept per
    theme: Bun's headphones are its accent."""
    from soundboard.ui.kit import theme
    return _badge(ach_id, tier, size, locked, dpr, theme.tokens()["accent"])


@lru_cache(maxsize=256)
def _badge(ach_id: str, tier: str, size: int, locked: bool, dpr: float,
           _accent: str) -> QPixmap:
    px = max(1, round(size * dpr))
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint(p, QRectF(0, 0, px, px), ach_id, tier)
    p.end()
    if locked:
        grey = img.convertToFormat(QImage.Format.Format_Grayscale8)
        alpha = img.convertToFormat(QImage.Format.Format_Alpha8)
        img = grey.convertToFormat(QImage.Format.Format_ARGB32)
        img.setAlphaChannel(alpha)
        faded = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
        faded.fill(Qt.GlobalColor.transparent)
        q = QPainter(faded)
        q.setOpacity(0.45)
        q.drawImage(0, 0, img)
        q.end()
        img = faded
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm
