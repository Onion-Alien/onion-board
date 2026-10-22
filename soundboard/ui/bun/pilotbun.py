"""Pilot Bun: the Languages card's install picture, Bun flying a little plane round the
world (Robo-Bun's counterpart on the AI voice card).

Both are drawn in 3D. The Earth is a lit ball worked out pixel by pixel with numpy: the
real coasts (much simplified) painted onto a map once, then wrapped round the ball as
it turns, with the sun on it from the top left (a night side, a glint on the sea, a
blue glow of air round the rim) and clouds drifting a little faster than the land.
Bun flies a small red propeller plane, a real 3D model, low over the world with its
belly to the ground: across the front, over the curve and round the back, a contrail
behind him and his shadow on the land below. The plane is drawn into its own depth
buffer (each pixel keeps whatever is nearest), so its parts never swap places, and
the Earth hides exactly the parts of it that are behind the world.

He flies for REST_S after he's shown (or clicked, or the mouse comes onto him), then
holds still where he is, so a card left open costs nothing; while the install runs
(`set_flying(True)`) he keeps going. The timer only runs while he's on screen and the
app is in front. In lite mode (ui/settings/lite.py) he still flies, at LITE_FPS: a
still plane read as a broken picture.

Everything is drawn at the screen's own pixels in a SLOT_W x SLOT_H slot; Bun himself
is soundboard/ui/bun/bunny.py's draw_bunny, kept as a picture per pose.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from soundboard.ui.kit import appstate, theme
from soundboard.ui.bun.bunny import H, W, draw_bunny
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.settings import lite

SLOT_W, SLOT_H = 132, 104        # about Robo-Bun's size beside the AI voices install
FPS = 30
LITE_FPS = 15                    # lite mode: half the frames
REST_S = 20.0                    # how long he flies after a stir, then holds still

GLOBE_C, GLOBE_R = QPointF(66, 53), 36.0
VIEW_LAT = 18.0                  # the Earth seen this many degrees above the equator
SPIN = 14.0                      # degrees a second it turns
CLOUD_SPIN = 18.0                # the clouds, a little faster
ORBIT_R = 1.24                   # his height: the path's radius, in Earth radii
ORBIT_TILT, ORBIT_ROLL = 22.0, -18.0   # the path leans toward us, then tips sideways
ORBIT_SPEED = 0.7                # radians a second
PLANE_SIZE = 32.0                # px per plane unit (the fuselage is about 1 long)
SS = 2                         # the plane is drawn this many times finer, then shrunk
SUN = np.array([-0.55, 0.55, 0.63])
SUN = SUN / np.linalg.norm(SUN)  # from the top left, a little in front
TEX_W, TEX_H = 512, 256          # the world map wrapped round the ball

RED, RED_DARK = QColor("#e8574a"), QColor("#b53a32")
CREAM = QColor("#f6ecd6")
DESERT, ICE = QColor("#c7a35c"), QColor("#eef4f7")   # (which map shapes are what)
LAND = QColor("#5e9f45")
AIR = np.array((110, 175, 255.0))      # the air's glow
CLOUD = np.array((250, 252, 255.0))
GLINT = np.array((255, 245, 220.0))     # the sun on the sea

# the world's coasts, much simplified: "longitude latitude" points round each land, in
# the order they're drawn (a desert over the land it's in)
_LANDS = (
    (LAND, "-168 66 -162 70 -156 71 -140 70 -128 70 -115 68 -95 72 -85 70 -80 63 -90 57 "
           "-82 52 -78 58 -70 60 -64 58 -56 52 -60 47 -66 44 -70 42 -74 40 -76 35 -81 31 "
           "-80 26 -82 27 -84 30 -90 29 -97 27 -97 22 -94 18 -88 21 -87 16 -83 15 -80 9 "
           "-78 8 -84 10 -86 12 -92 14 -96 16 -105 20 -110 24 -112 29 -115 31 -117 32 "
           "-121 35 -124 40 -124 46 -125 50 -131 54 -137 58 -145 60 -152 59 -158 57 "
           "-165 54 -160 58 -165 61 -166 64"),                          # North America
    (ICE, "-73 78 -60 82 -35 83 -20 81 -18 76 -22 70 -32 68 -42 60 -48 61 -52 65 -55 70 "
          "-60 75 -70 77"),                                             # Greenland
    (LAND, "-80 9 -75 11 -72 12 -62 11 -60 8 -52 5 -50 0 -44 -2 -35 -5 -35 -9 -39 -14 "
           "-40 -20 -44 -23 -48 -26 -53 -34 -58 -38 -62 -39 -65 -45 -68 -50 -69 -55 "
           "-74 -52 -75 -46 -73 -38 -71 -30 -70 -18 -76 -14 -81 -6 -80 -1 -78 2 "
           "-78 7"),                                                    # South America
    (LAND, "-10 36 -9 43 -2 44 -5 48 2 51 8 54 9 57 12 56 18 60 22 65 18 70 26 71 33 70 "
           "42 67 44 68 54 69 60 70 70 73 80 73 87 75 100 77 112 74 130 72 140 72 160 70 "
           "170 70 180 68 178 64 170 60 163 58 160 54 156 51 156 58 150 59 140 54 136 54 "
           "140 48 135 43 130 42 129 36 126 37 126 40 122 40 119 35 122 30 120 24 110 21 "
           "108 16 109 12 105 9 100 13 99 8 103 2 100 4 98 10 98 16 94 17 92 22 88 22 "
           "80 16 77 8 73 17 72 22 67 25 62 25 57 26 56 24 59 22 52 17 44 13 43 17 39 22 "
           "35 28 34 31 36 35 30 36 27 37 26 40 29 41 28 43 23 40 22 37 20 40 19 42 13 45 "
           "12 44 16 40 16 38 15 40 10 44 3 43 -1 37 -6 36"),          # Europe and Asia
    (DESERT, "35 28 39 22 43 17 44 13 52 17 59 22 56 24 51 25 48 30 44 30 "
             "38 32"),                                                  # Arabia
    (LAND, "-17 21 -13 27 -10 30 -6 35 10 37 11 33 20 31 32 31 34 28 38 22 43 12 51 12 "
           "44 2 40 -3 40 -10 40 -16 35 -24 32 -29 27 -34 20 -35 18 -32 14 -23 12 -17 "
           "13 -10 9 -1 9 4 4 6 -4 5 -8 4 -13 8 -17 13 -17 15"),        # Africa
    (DESERT, "-16 20 -13 27 -10 30 -6 35 10 37 11 33 20 31 32 31 34 28 37 22 33 17 22 15 "
             "10 16 0 16 -10 17"),                                      # the Sahara
    (LAND, "44 -25 47 -25 50 -15 49 -12 44 -17"),                       # Madagascar
    (DESERT, "114 -22 114 -26 115 -34 118 -35 124 -34 131 -31 135 -35 138 -35 140 -38 "
             "146 -39 150 -37 153 -31 153 -25 146 -19 145 -15 142 -11 141 -17 136 -12 "
             "130 -12 126 -14 122 -18"),                                # Australia
    (LAND, "109 1 117 7 119 1 116 -4 110 -3"),                          # Borneo
    (LAND, "95 5 98 4 106 -6 102 -4"),                                  # Sumatra
    (LAND, "131 -1 141 -3 150 -10 141 -9 137 -5"),                      # New Guinea
    (LAND, "130 31 135 34 140 36 142 40 141 45 140 41 136 36 131 34"),  # Japan
    (LAND, "-5 50 1 51 0 53 -2 56 -5 58 -6 56 -4 54 -3 53 -5 52"),      # Britain
    (ICE, " ".join(f"{lon} -70" for lon in range(-180, 181, 20))
     + " 180 -90 -180 -90"),                                            # Antarctica
)


def _points(text: str) -> list[tuple[float, float]]:
    n = [math.radians(float(v)) for v in text.split()]
    return list(zip(n[::2], n[1::2]))


LANDS = tuple((colour, _points(text)) for colour, text in _LANDS)


# ------------------------------------------------------------------ the world map
def _smooth(e0: float, e1: float, x):
    k = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return k * k * (3 - 2 * k)


def _noise(cells: int, seed: int) -> np.ndarray:
    """Smooth random hills over the map, joined up where east meets west."""
    g = np.random.default_rng(seed).random((cells + 1, cells * 2))
    ys = np.linspace(0, cells, TEX_H, endpoint=False)
    xs = np.linspace(0, cells * 2, TEX_W, endpoint=False)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = _smooth(0, 1, ys - y0)[:, None], _smooth(0, 1, xs - x0)
    x1 = (x0 + 1) % (cells * 2)
    top = g[y0][:, x0] + (g[y0][:, x1] - g[y0][:, x0]) * fx
    bot = g[y0 + 1][:, x0] + (g[y0 + 1][:, x1] - g[y0 + 1][:, x0]) * fx
    return top + (bot - top) * fy


def _fbm(cells: int, octaves: int, seed: int) -> np.ndarray:
    out, amp, total = np.zeros((TEX_H, TEX_W)), 1.0, 0.0
    for i in range(octaves):
        out += amp * _noise(cells * 2 ** i, seed + i)
        total += amp
        amp *= 0.5
    return out / total


def _blur(a: np.ndarray, r: int) -> np.ndarray:
    for _ in range(3):
        a = np.sum([np.roll(a, k, 1) for k in range(-r, r + 1)], 0) / (2 * r + 1)
        pad = np.pad(a, ((r, r), (0, 0)), mode="edge")
        a = np.sum([pad[r + k:r + k + TEX_H] for k in range(-r, r + 1)], 0) / (2 * r + 1)
    return a


def _mask(which) -> np.ndarray:
    """1 where the map shapes `which(colour)` picks are, 0 elsewhere."""
    img = QImage(TEX_W, TEX_H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    q = QPainter(img)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(QColor(255, 255, 255))
    for colour, pts in LANDS:
        if which(colour):
            q.drawPolygon(QPolygonF([QPointF((lon + math.pi) / (2 * math.pi) * TEX_W,
                                             (math.pi / 2 - lat) / math.pi * TEX_H)
                                     for lon, lat in pts]))
    q.end()
    return np.frombuffer(img.constBits(), np.uint8).reshape(TEX_H, TEX_W, 4)[..., 3] / 255.0


_MAP: dict = {}


def world_map() -> tuple[np.ndarray, np.ndarray]:
    """(colours with the sea in a 4th channel, clouds): painted once, on first use."""
    if not _MAP:
        lat = np.abs(np.linspace(90, -90, TEX_H))[:, None] * np.ones((1, TEX_W))
        n1, n2 = _fbm(4, 5, 1), _fbm(8, 4, 7)
        land = _mask(lambda c: True)
        land = _smooth(0.35, 0.65, land + (n2 - 0.5) * (1 - np.abs(land - 0.5) * 2) * 0.5)
        desert = _smooth(0.3, 0.7, _mask(lambda c: c == DESERT) + (n1 - 0.5) * 0.6)
        ice = np.clip(_mask(lambda c: c == ICE) + _smooth(73, 80, lat) * land, 0, 1)
        # the sea: deep, lighter over the shallows by the coasts
        deep, mid, shallow = (np.array(c, float) for c in ((12, 38, 92), (22, 74, 150),
                                                           (45, 140, 190)))
        sea = deep + (mid - deep) * (n1 * 0.6)[..., None]
        sea += (shallow - sea) * (_smooth(0, 0.5, _blur(land, 3)) * 0.8)[..., None]
        # the land: greens, darker forest up north, then tundra; deserts; ice
        green = np.array((58, 120, 48.0)) + np.array((34, 20, 12.0)) * n2[..., None]
        green += (np.array((52, 86, 50.0)) - green) * _smooth(42, 58, lat)[..., None]
        green += (np.array((128, 124, 100.0)) - green) * _smooth(60, 70, lat)[..., None]
        sand = np.array((180, 130, 80.0)) + np.array((34, 52, 40.0)) * n2[..., None]
        ground = green + (sand - green) * desert[..., None]
        ground += (np.array((236, 242, 248.0)) - ground) * ice[..., None]
        colour = sea + (ground - sea) * land[..., None]
        floe = _smooth(76, 84, lat) * (1 - land)   # sea ice round the poles
        colour += (np.array((225, 235, 245.0)) - colour) * floe[..., None]
        wet = (1 - land) * (1 - floe)
        clouds = _smooth(0.52, 0.72, _fbm(5, 6, 21) * 0.75
                         + (0.55 + 0.25 * np.cos(np.radians(lat) * 6)) * 0.25 + 0.03)
        _MAP["map"] = np.dstack([colour, wet]).astype(np.float32)
        _MAP["clouds"] = (clouds * 0.95).astype(np.float32)
    return _MAP["map"], _MAP["clouds"]


def _sample(img: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """`img` looked up (smoothly) at u (0..1, round the world) and v (0..1, top down)."""
    th, tw = img.shape[:2]
    x, y = u * tw - 0.5, np.clip(v * th - 0.5, 0, th - 1.001)
    x0, y0 = np.floor(x).astype(int), y.astype(int)
    fx, fy = x - x0, y - y0
    x0 %= tw
    x1, y1 = (x0 + 1) % tw, y0 + 1
    if img.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    a, b, c, d = img[y0, x0], img[y0, x1], img[y1, x0], img[y1, x1]
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy


class _Ball:
    """What doesn't change while the world turns, for a ball `rpx` screen pixels round:
    where each of its pixels lands on the map, how the sun and the air light it, and
    the glow round it (drawn once)."""

    def __init__(self, rpx: float):
        self.rpx = rpx
        self.half = half = int(math.ceil(rpx * 1.22)) + 1   # room for the glow
        ys, xs = np.mgrid[0:2 * half, 0:2 * half]
        x, y = (xs + 0.5 - half) / rpx, -(ys + 0.5 - half) / rpx
        d = np.hypot(x, y)
        cover = np.clip((1 - d) * rpx + 0.5, 0, 1)   # smooth rim
        side = (x * SUN[0] + y * SUN[1]) / np.maximum(d, 1e-6)
        glow = np.exp(-np.clip(d - 1, 0, None) / 0.07) * (d >= 1)
        glow *= (0.25 + 0.6 * _smooth(-0.6, 0.8, side)) * 0.85 * (1 - cover)
        self.base = np.zeros((2 * half, 2 * half, 4), np.uint8)
        self.base[..., :3] = np.clip(AIR * glow[..., None], 0, 255)
        self.base[..., 3] = np.clip(glow * 255, 0, 255)
        self.on = cover > 0   # the ball itself: only these pixels change
        x, y, d = x[self.on], y[self.on], d[self.on]
        self.cover, self.glow = cover[self.on][:, None], glow[self.on][:, None]
        z = np.sqrt(np.clip(1 - d * d, 0, 1))
        v = math.radians(VIEW_LAT)
        lat = np.arcsin(np.clip(y * math.cos(v) + z * math.sin(v), -1, 1))
        self.lon = np.arctan2(x, -y * math.sin(v) + z * math.cos(v))
        self.v = (math.pi / 2 - lat) / math.pi
        sun = x * SUN[0] + y * SUN[1] + z * SUN[2]
        self.day = (0.25 * _smooth(-0.12, 0.3, sun) + 0.75 * np.clip(sun, 0, 1) ** 0.85)[:, None]
        hv = SUN + (0, 0, 1)
        hv /= np.linalg.norm(hv)
        glint = np.clip(x * hv[0] + y * hv[1] + z * hv[2], 0, 1)
        self.glint = glint ** 90 * 0.38 + glint ** 14 * 0.07
        self.air = ((1 - z) ** 2.2 * (0.15 + 0.75 * _smooth(-0.3, 0.5, sun)))[:, None]

    def paint(self, lon0: float, cloud_lon: float) -> QImage:
        world, clouds = world_map()
        u = ((self.lon + lon0 + math.pi) / (2 * math.pi)) % 1.0
        uc = ((self.lon + cloud_lon + math.pi) / (2 * math.pi)) % 1.0
        here = _sample(world, u, self.v)
        col, sea = here[:, :3], here[:, 3]
        cl = _sample(clouds, uc, self.v)
        col = col * (1 - 0.3 * cl)[:, None] * (0.06 + 1.05 * self.day)   # their shade
        col += (CLOUD * (0.08 + 1.0 * self.day) - col) * cl[:, None]
        col += GLINT * (self.glint * sea * (1 - cl))[:, None]
        col += (AIR - col) * self.air
        out = self.base.copy()
        out[self.on, :3] = np.clip(col * self.cover + AIR * self.glow, 0, 255)
        out[self.on, 3] = np.clip((self.cover + self.glow)[:, 0] * 255, 0, 255)
        n = 2 * self.half
        return QImage(out.tobytes(), n, n, n * 4,
                      QImage.Format.Format_RGBA8888_Premultiplied).copy()


# ------------------------------------------------------------------ the plane
def _box(x0, x1, y0, y1, z0, z1, colour, lift=0.0):
    """A slab's six sides, its y ends raised by `lift` per unit (a wing's dihedral)."""
    def at(x, y, z):
        return np.array((x, y, z + lift * abs(y)))
    v = [at(x0, y0, z0), at(x1, y0, z0), at(x1, y1, z0), at(x0, y1, z0),
         at(x0, y0, z1), at(x1, y0, z1), at(x1, y1, z1), at(x0, y1, z1)]
    sides = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    return [([v[i] for i in s], colour) for s in sides]


def _plane_model() -> list[tuple[list, QColor]]:
    """The plane as faces (corner points, colour), its cockpit near (0, 0, 0): x to the
    nose, y to the left wing, z up. All its faces point outward."""
    faces = []
    rings = []
    for x, r, dz in ((-0.52, 0.025, 0.06), (-0.32, 0.07, 0.06), (-0.05, 0.11, 0.0),
                     (0.22, 0.115, 0.0), (0.40, 0.095, 0.0), (0.48, 0.06, 0.0)):
        rings.append([np.array((x, r * math.cos(a), dz + r * 1.05 * math.sin(a)))
                      for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)])
    for a, b in zip(rings, rings[1:]):
        for i in range(8):
            j = (i + 1) % 8
            stripe = abs(a[i][2] + a[j][2]) / 2 < 0.03 and a[i][0] > -0.3   # along its sides
            faces.append(([a[i], a[j], b[j], b[i]], CREAM if stripe else RED))
    faces.append((list(reversed(rings[0])), RED_DARK))
    faces.append((rings[-1], CREAM))
    for y0, y1, colour in ((0.06, 0.43, CREAM), (0.43, 0.5, RED), (-0.43, -0.06, CREAM),
                           (-0.5, -0.43, RED)):   # the wings, red tips beside (not over) them
        faces += _box(-0.08, 0.12, y0, y1, -0.075, -0.045, colour, 0.09)
    faces += _box(-0.5, -0.38, -0.2, 0.2, 0.05, 0.068, CREAM)   # the tailplane
    fin = [np.array(p) for p in ((-0.52, 0, 0.06), (-0.36, 0, 0.08), (-0.5, 0, 0.27),
                                 (-0.56, 0, 0.26))]
    faces.append(([p + (0, 0.012, 0) for p in fin], RED))
    faces.append(([p - (0, 0.012, 0) for p in reversed(fin)], RED))
    return faces


def _faces():
    """The model as arrays: every corner (n x xyz), where each face's corners start in
    it, and the faces' colours (rgb, 0..1)."""
    model = _plane_model()
    corners = np.array([c for face, _ in model for c in face])
    starts = np.cumsum([0] + [len(face) for face, _ in model])
    colours = np.array([(c.redF(), c.greenF(), c.blueF()) for _, c in model])
    return corners, starts, colours


PLANE, PLANE_STARTS, PLANE_COLOURS = _faces()
_HALF = SUN + (0, 0, 1)
_HALF = _HALF / np.linalg.norm(_HALF)   # halfway between the sun and us: the gloss
PROP = np.array((0.5, 0.0, 0.0))    # the propeller's hub
SEAT = np.array((0.06, 0.0, 0.09))  # where Bun's chest is


class _Pose:
    """Where the plane is (px, the Earth's centre at 0, y up, z toward us) and which way
    it points."""

    def __init__(self, pos, fwd, up):
        self.pos = pos
        self.fwd = fwd / np.linalg.norm(fwd)
        up = up - self.fwd * np.dot(up, self.fwd)
        self.up = up / np.linalg.norm(up)
        self.left = np.cross(self.up, self.fwd)
        self.axes = np.stack([self.fwd, self.left, self.up])


_TILT, _ROLL = math.radians(ORBIT_TILT), math.radians(ORBIT_ROLL)
_E1 = np.array((math.cos(_ROLL), math.sin(_ROLL), 0))
_E2 = np.array((-math.sin(_ROLL) * math.sin(_TILT), math.cos(_ROLL) * math.sin(_TILT),
                math.cos(_TILT)))


def _path(a):
    """Points of his flight path (one per angle in `a`): a circle round the world,
    leaning toward us."""
    a = np.asarray(a, float)[..., None]
    return GLOBE_R * ORBIT_R * (np.cos(a) * _E1 + np.sin(a) * _E2)


def _angle(t: float) -> float:
    return 2.6 - t * ORBIT_SPEED


def _pose(t: float) -> _Pose:
    a = _angle(t)
    pos = _path(a)
    return _Pose(pos, _path(a - 0.01) - pos, pos)   # belly to the ground


class _Raster:
    """A small depth-buffered canvas for the plane, SS times finer than the screen.
    Each pixel keeps the nearest thing drawn there (bigger z is nearer)."""

    def __init__(self, x0: float, y0: float, w: int, h: int):
        self.x0, self.y0, self.w, self.h = x0, y0, w, h
        self.rgb = np.zeros((h, w, 3))      # premultiplied colour
        self.a = np.zeros((h, w))
        self.z = np.full((h, w), -np.inf)   # nearest solid thing
        self.zs = np.full((h, w), -np.inf)  # nearest anything (for the Earth's cover)

    def poly(self, pts, colour, alpha: float = 1.0):
        """A flat face with straight sides bulging nowhere inward: pts are its corners,
        (x, y, z) in canvas pixels, in order round it."""
        pts = np.asarray(pts, float)
        (xa, ya, za), (xb, yb, zb), (xc, yc, zc) = pts[:3]
        area = (xb - xa) * (yc - ya) - (xc - xa) * (yb - ya)
        if abs(area) < 1e-9:
            return
        lx, hx = max(int(pts[:, 0].min()), 0), min(int(pts[:, 0].max()) + 1, self.w)
        ly, hy = max(int(pts[:, 1].min()), 0), min(int(pts[:, 1].max()) + 1, self.h)
        if lx >= hx or ly >= hy:
            return
        X, Y = np.arange(lx, hx) + 0.5, (np.arange(ly, hy) + 0.5)[:, None]
        px, py = pts[:, 0, None, None], pts[:, 1, None, None]
        qx, qy = np.roll(px, -1, 0), np.roll(py, -1, 0)
        inside = ((qx - px) * (Y - py) - (qy - py) * (X - px)) * area >= 0   # every side
        # its depth across it, from the plane through its first three corners
        gx = ((zb - za) * (yc - ya) - (yb - ya) * (zc - za)) / area
        gy = ((xb - xa) * (zc - za) - (zb - za) * (xc - xa)) / area
        z = za + gx * (X - xa) + gy * (Y - ya)
        zbuf = self.z[ly:hy, lx:hx]
        m = inside.all(0) & (z > zbuf)
        if not m.any():
            return
        rgb, a, zs = self.rgb[ly:hy, lx:hx], self.a[ly:hy, lx:hx], self.zs[ly:hy, lx:hx]
        if alpha >= 1.0:
            rgb[m] = colour
            a[m] = 1.0
            zbuf[m] = z[m]
        else:   # see-through: over what's there, hides nothing
            rgb[m] = np.asarray(colour) * alpha + rgb[m] * (1 - alpha)
            a[m] = alpha + a[m] * (1 - alpha)
        zs[m] = np.maximum(zs[m], z[m])

    def sprite(self, img: QImage, z: float):
        """A flat picture (premultiplied, the canvas's size) standing at depth z."""
        px = np.frombuffer(img.constBits(), np.uint8).reshape(self.h, self.w, 4) / 255.0
        pa = px[..., 3]
        m = (pa > 0.004) & (z > self.z)
        rgb = px[..., [2, 1, 0]]   # (the picture is BGRA in memory)
        self.rgb[m] = rgb[m] + self.rgb[m] * (1 - pa[m, None])
        self.a[m] = pa[m] + self.a[m] * (1 - pa[m])
        self.z[m & (pa > 0.5)] = z
        self.zs[m] = np.maximum(self.zs[m], z)

    def image(self, scale: float, centre: tuple[float, float], radius: float) -> QImage:
        """Shrunk to screen pixels, with what's behind the Earth taken out (`centre`:
        the Earth's, from the canvas's top left, px)."""
        # behind the world: inside its disc and further back than its near surface
        X, Y = np.meshgrid((np.arange(self.w) + 0.5) / (SS * scale) - centre[0],
                           (np.arange(self.h) + 0.5) / (SS * scale) - centre[1])
        d2 = X * X + Y * Y
        hidden = (d2 < radius * radius) & (self.zs < np.sqrt(np.clip(radius * radius - d2,
                                                                     0, None)))
        a = np.where(hidden, 0.0, self.a)
        rgb = self.rgb * (a / np.maximum(self.a, 1e-6))[..., None]
        h, w = self.h // SS, self.w // SS
        a = a[:h * SS, :w * SS].reshape(h, SS, w, SS).mean((1, 3))
        rgb = rgb[:h * SS, :w * SS].reshape(h, SS, w, SS, 3).mean((1, 3))
        out = np.empty((h, w, 4), np.uint8)
        out[..., :3] = np.clip(rgb * 255, 0, 255)
        out[..., 3] = np.clip(a * 255, 0, 255)
        img = QImage(out.tobytes(), w, h, w * 4,
                     QImage.Format.Format_RGBA8888_Premultiplied).copy()
        img.setDevicePixelRatio(scale)
        return img


class PilotBunny(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(SLOT_W, SLOT_H)
        self.flying = False          # the install is running: no rest
        self._t0 = time.monotonic()  # the clock his flight runs on
        self._rest_at = 0.0          # when he holds still
        self._held = 0.0             # the moment he holds once resting
        self._buns: dict[tuple, QImage] = {}
        self._ball: _Ball | None = None
        self._frame: tuple[tuple, QImage, QImage] | None = None   # the last one drawn
        self._spun: tuple = ()       # when (and how) its world was drawn
        self._scale = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)
        world_map()   # (~0.1 s, once: now, while the app is still loading)

    def sizeHint(self) -> QSize:
        return QSize(SLOT_W, SLOT_H)

    # ------------------------------------------------------------------ state
    def set_flying(self, on: bool):
        """The install started (he keeps flying) or ended (he rests after REST_S)."""
        self.flying = bool(on)
        self.stir()

    def stir(self):
        """Fly again for REST_S."""
        self._rest_at = time.monotonic() + REST_S
        self._run()

    def resting(self) -> bool:
        return not self.flying and time.monotonic() >= self._rest_at

    def _run(self):
        if self.isVisible() and not self.resting():
            self._timer.setInterval(1000 // (LITE_FPS if lite.on() else FPS))
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.stir()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def enterEvent(self, ev):
        self.stir()
        super().enterEvent(ev)

    def mousePressEvent(self, ev):
        self.stir()
        super().mousePressEvent(ev)

    def _tick(self):
        if self.resting():
            self._timer.stop()
        if appstate.active() and not self.window().isMinimized():
            self.update()

    def _now(self) -> float:
        """His clock: running while he flies, held where he stopped once he rests."""
        if not self.resting():
            self._held = time.monotonic() - self._t0
        return self._held

    def _bun(self, blink: float, ears: int) -> QImage:
        """Bun, upright, drawn big once per pose (and outfit) to shrink onto the plane."""
        key = (blink, ears, theme.T["accent"], theme.current_name)
        img = self._buns.get(key)
        if img is None:
            if len(self._buns) > 16:
                self._buns.clear()
            img = QImage(int(W * 2), int(H * 2 + 40), QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            q = QPainter(img)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_bunny(q, QRectF(0, 40, W * 2, H * 2), None, blink=blink, ears=ears)
            q.end()
            self._buns[key] = img
        return img

    # --------------------------------------------------------------- painting
    def paintEvent(self, _e):
        t = self._now()
        p = QPainter(self)
        snap_to_pixels(p)
        self._scale = round(max(p.device().devicePixelRatioF(), p.deviceTransform().m11()), 2)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setClipRect(self.rect())
        key = (t, self._scale, theme.T["accent"], theme.current_name, self.resting())
        if self._frame is None or self._frame[0] != key:   # (resting: the same picture)
            # the world turns less than half a pixel a frame: a new one every other frame
            spun = round(t * FPS / 2) * 2 / FPS
            last = self._frame
            same = last is not None and self._spun == (spun, key[1:])
            world = last[1] if last is not None and same else self._world(spun)
            self._spun = (spun, key[1:])
            self._frame = (key, world, self._plane(t))
        _, world, plane = self._frame
        pose = _pose(t)
        self._trail(p, t, front=False)
        p.drawImage(QPointF(GLOBE_C.x() - world.width() / 2 / self._scale,
                            GLOBE_C.y() - world.height() / 2 / self._scale), world)
        self._shadow(p, pose)
        self._trail(p, t, front=True)
        p.drawImage(QPointF(*self._plane_at), plane)
        p.end()

    def _world(self, t: float) -> QImage:
        rpx = GLOBE_R * self._scale
        if self._ball is None or self._ball.rpx != rpx:
            self._ball = _Ball(rpx)
        img = self._ball.paint(math.radians(t * SPIN - 20), math.radians(t * CLOUD_SPIN - 20))
        img.setDevicePixelRatio(self._scale)
        return img

    def _trail(self, p: QPainter, t: float, front: bool):
        """His contrail, fading back along where he's been; the part behind the world
        hidden by it."""
        n = 26
        pts = _path(_angle(t) + np.arange(n + 1) * 0.05)
        for i in range(n):
            p0, p1 = pts[i], pts[i + 1]
            if (p0[2] >= 0) != front:
                continue
            if not front and p0[0] ** 2 + p0[1] ** 2 < GLOBE_R ** 2:
                continue
            alpha = round(150 * (i / 3 if i <= 2 else (1 - i / n) ** 1.5))
            p.setPen(QPen(QColor(255, 255, 255, alpha), 1.1 * (1 - i / n * 0.5),
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(GLOBE_C.x() + p0[0], GLOBE_C.y() - p0[1]),
                       QPointF(GLOBE_C.x() + p1[0], GLOBE_C.y() - p1[1]))

    def _shadow(self, p: QPainter, pose: _Pose):
        """His shadow on the ground below, a little away from the sun."""
        g = pose.pos - SUN * GLOBE_R * 0.35
        g = g / np.linalg.norm(g) * GLOBE_R
        if g[2] <= 0:
            return
        c = QPointF(GLOBE_C.x() + g[0], GLOBE_C.y() - g[1])
        soft = QRadialGradient(c, 5)
        soft.setColorAt(0, QColor(0, 0, 20, 90))
        soft.setColorAt(1, QColor(0, 0, 20, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(soft)
        p.drawEllipse(c, 5, 3.5)

    def _plane(self, t: float) -> QImage:
        """The plane and Bun, depth-buffered, for this moment (sets `_plane_at`)."""
        pose = _pose(t)
        k = 1.0 / (1 - pose.pos[2] / (GLOBE_R * 7))   # nearer is bigger
        unit = PLANE_SIZE * k
        box = 0.72 * unit                              # room round him, px (wing tips, ears)
        cx, cy = GLOBE_C.x() + pose.pos[0], GLOBE_C.y() - pose.pos[1]
        x0, y0 = cx - box, cy - box
        f = self._scale * SS                           # canvas pixels per px
        side = int(math.ceil(2 * box * self._scale)) * SS
        r = _Raster(x0, y0, side, side)
        self._plane_at = (x0, y0)

        def at(v):   # a plane point -> canvas (x, y, depth in px)
            w = v @ pose.axes * unit
            return ((cx + w[0] - x0) * f, (cy - w[1] - y0) * f, pose.pos[2] + w[2])

        ws = PLANE @ pose.axes   # every corner turned the plane's way
        first = PLANE_STARTS[:-1]
        normal = np.cross(ws[first + 1] - ws[first], ws[first + 2] - ws[first])
        normal /= np.maximum(np.linalg.norm(normal, axis=1), 1e-12)[:, None]
        sun = np.clip(normal @ SUN, 0, None)[:, None]
        gloss = np.clip(normal @ _HALF, 0, None)[:, None] ** 24 * 0.25
        lit = np.clip(PLANE_COLOURS * (0.42 + 0.72 * sun) + gloss, 0, 1)
        canvas = np.column_stack([(cx + ws[:, 0] * unit - x0) * f,
                                  (cy - ws[:, 1] * unit - y0) * f,
                                  pose.pos[2] + ws[:, 2] * unit])
        # the faces toward us, all but ones too small to see
        span = canvas[PLANE_STARTS[:-1] + 2, :2] - canvas[PLANE_STARTS[:-1], :2]
        for i in np.flatnonzero((normal[:, 2] > 1e-6) & (np.abs(span).sum(1) > 1.0)):
            r.poly(canvas[PLANE_STARTS[i]:PLANE_STARTS[i + 1]], lit[i])
        # Bun, standing in the cockpit, turned with the plane's up as we see it
        blink = 1.0 if (t % 3.4) < 0.13 else 0.0
        ears = round(10 + 4 * math.sin(t * 7))
        seat, head = at(SEAT), at(SEAT + (0, 0, 0.21))
        dx, dy = head[0] - seat[0], head[1] - seat[1]
        ang = math.degrees(math.atan2(dx, -dy)) * min(1.0, math.hypot(dx, dy) / (0.21 * unit * f))
        bun = self._bun(blink, ears)
        sprite = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
        sprite.fill(Qt.GlobalColor.transparent)
        q = QPainter(sprite)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        q.translate(seat[0], seat[1])
        q.rotate(ang)
        s = 0.4 * unit * f / (H * 2)
        q.scale(s, s)
        q.drawImage(QPointF(-W, -(H * 2 + 40) * 0.6), bun)
        q.end()
        # in front of the cockpit floor, behind the fuselage's near side
        r.sprite(sprite, pose.pos[2] + float(((SEAT + (0, 0, 0.06)) @ pose.axes)[2]) * unit)
        # the windscreen and the propeller: see-through, so after everything solid
        r.poly([at(np.array(v)) for v in ((0.17, 0.06, 0.1), (0.17, -0.06, 0.1),
                                          (0.12, -0.05, 0.2), (0.12, 0.05, 0.2))],
               (200 / 255, 236 / 255, 1.0), 0.55)
        ring = np.linspace(0, 2 * math.pi, 24, endpoint=False)
        if not self.resting():   # a blur where the blades turn
            r.poly([at(PROP + (0, 0.2 * math.cos(a), 0.2 * math.sin(a))) for a in ring],
                   (1.0, 1.0, 1.0), 0.2)
        spin = t * 38
        for blade in (0.0, math.pi):
            a = spin + blade
            out, across = np.array((0, math.cos(a), math.sin(a))), np.array((0, -math.sin(a),
                                                                               math.cos(a)))
            r.poly([at(PROP + out * 0.02 + across * 0.018), at(PROP + out * 0.19 + across * 0.01),
                    at(PROP + out * 0.19 - across * 0.01), at(PROP + out * 0.02 - across * 0.018)],
                   (0.35, 0.24, 0.15))
        r.poly([at(PROP + (0.01, 0.03 * math.cos(a), 0.03 * math.sin(a))) for a in ring[::2]],
               (0.85, 0.78, 0.64))
        return r.image(self._scale, ((GLOBE_C.x() - x0), (GLOBE_C.y() - y0)), GLOBE_R)
