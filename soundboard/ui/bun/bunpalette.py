"""Bun's colours and the spots on his 100 x 120 canvas (ui/bun/bunny.py draws him):
fur, ink, eyes, nose, his props' wood and steel, Robo-Bun's, the room round him in a
picture. `bunny` imports them all, so `bunny.FUR` still works."""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from soundboard.style import bunnyfit

# drawn on a 100 x 120 canvas, scaled to the requested height
W, H = 100.0, 120.0

FUR = QColor("#fdf8f1")
FUR_SHADE = QColor("#efe3d6")
FUR_LINE = QColor(200, 176, 160, 150)   # soft fluff lines (the nightcap bobble)
INK = QColor("#2b2340")
EYE = QColor("#251c33")
IRIS = QColor(bunnyfit.VANILLA["iris"])   # the coloured glow low in his eyes (plain Bun's:
                                          # each theme's look can change it, and the pinks)
FACE_LIGHT = QColor("#f4ecf6")          # his face lines and eye rims on dark fur
BROW = QColor(196, 140, 140, 150)       # his little resting brows
PINK = QColor(bunnyfit.VANILLA["inner"])
NOSE = QColor(bunnyfit.VANILLA["nose"])   # (his tongue stays this pink whatever his nose)
NOSE_EDGE = QColor("#e0708f")
MOUTH = QColor("#7a2a45")
CHEEK = QColor(255, 122, 150, 165)
# his headphones are the current theme's accent (theme.T, read at paint time)

PROPS = (None, "mic", "headphones", "plug", "star", "hammer", "bat", "wrench",
         "hammer_broken", "survey")
# the props that take a paw (the one on the right, both): those paws leave his lap
ONE_PAW = {"mic", "headphones", "plug", "bat", "hammer", "hammer_broken", "wrench"}
BOTH_PAWS = {"star", "survey"}
WOOD = QColor("#c98a4b")
WOOD_DARK = QColor("#9a6532")
STEEL = QColor("#9aa0b4")
BAT = QColor("#e3b877")
GRIP = QColor("#3a3452")
CROSS = QColor("#ff4d6d")   # the cartoon anger mark

ROBOT_FUR = QColor("#dbe0ea")
ROBOT_FUR_SHADE = QColor("#bec7d8")
ROBOT_INK = QColor("#242735")
ROBOT_CYAN = QColor("#00d4ff")
ROBOT_CYAN_HI = QColor("#b0f4ff")
ROBOT_CYAN_GLOW = QColor(0, 212, 255, 130)
ROBOT_BOLT = QColor("#8e98ad")
GADGET = QColor("#b9c2d4")
# where things get built, on the 100 x 120 canvas (ui/bun/bunnywidget.py draws the progress):
# the wrench prop's gadget screen, and the spot on the hammer's plank
GADGET_SCREEN = QRectF(70, 109, 24, 6.5)
PLANK_SPOT = QRectF(84, 91, 17, 18)
# outfit pieces on his body, not his head: they stay put when he nods (draw_bunny `nod`)
BODY_PIECES = bunnyfit.NECK | {"sweater", "collar"}
EYES = bunnyfit.EYES
EYE_Y = bunnyfit.EYE_Y

# room round his canvas in a picture of him, canvas units: an upright ear reaches 8
# above it and a collar (Vampire's) 5 past each side
ROOM_TOP, ROOM_SIDE = 9.0, 7.0


