"""Hoot's looks: his canvas, his own colours and each theme's Hoot (LOOKS, look()).
Split out of owl.py, which re-exports every name here; part of the style kit (see
__init__.py)."""
from __future__ import annotations

from PySide6.QtGui import QColor

from . import hooks

# drawn on a 100 x 120 canvas, scaled to the requested height
W, H = 100.0, 120.0
INK = QColor("#2b2340")
FEATHER = QColor("#2fbfae")
FEATHER_DARK = QColor("#1f9a8c")
BELLY = QColor("#fbf3e3")
BELLY_MARK = QColor("#e2cfae")
FACE = QColor("#fdf8ee")
EYE = QColor("#251c33")
EYE_LOW = QColor("#5d4560")
BEAK = QColor("#ffb43c")
BEAK_DARK = QColor("#e8892a")
MOUTH = QColor("#c2413b")
EYE_RING = FACE   # (older name for the colour round his eyes)
CHEEK = QColor(255, 128, 160, 120)
TEAR = QColor("#8fd3ff")
BUBBLE = QColor("#fffaf0")
SPARKLE_COLORS = ("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")
EYES = (34, 66)
EYE_Y = 53.0

# each theme's own Hoot, like Bun's (bunnyfit.LOOKS): his feathers ("feather"; "wing":
# the darker wings and shading, None: a shade of the feathers), the colour low in his eyes
# ("iris"), his face mask ("face") and belly ("belly"), the marks on his belly ("marks":
# MARKS, in the "mark" colour), his ear tufts ("tufts": TUFTS), his beak and his toes
# ("feet", None: the beak's colour). All bold shapes, no feather lines. A theme that isn't
# listed is plain Hoot: VANILLA, his own teal.
MARKS = ("scallops", "spots", "chevrons", "hearts", "plain")
TUFTS = ("point", "round", "tall", "swept", "tiny")
VANILLA = {"feather": FEATHER.name(), "wing": FEATHER_DARK.name(), "iris": EYE_LOW.name(),
           "face": FACE.name(), "belly": BELLY.name(), "marks": "scallops",
           "mark": BELLY_MARK.name(), "tufts": "point", "beak": BEAK.name(), "feet": None}
LOOKS: dict[str, dict] = {
    "Light": {"feather": "#8f7bff", "wing": "#6a4cff", "iris": "#3d8fe0", "marks": "chevrons",
              "mark": "#b8a8ff", "feet": "#ffb3c7"},
    "Lilac": {"feather": "#b48cf0", "wing": "#8a60d0", "iris": "#a46be8", "belly": "#f8f3fe",
              "marks": "hearts", "mark": "#d6b4f2", "tufts": "round"},
    "Toxic": {"feather": "#6fd84a", "wing": "#3f9a2a", "iris": "#c6ff3d", "belly": "#eaf7d4",
              "marks": "spots", "mark": "#9fd46a", "tufts": "swept", "beak": "#ffcf40"},
    "Ocean": {"feather": "#2fa8e8", "wing": "#1a78b8", "iris": "#1aa0c8", "belly": "#eef8ff",
              "marks": "chevrons", "mark": "#a8d4ee", "tufts": "swept", "feet": "#ff8a73"},
    "Cherry Blossom": {"feather": "#f48fb1", "wing": "#d9658c", "iris": "#e0608f",
                       "face": "#fff7fa", "belly": "#fff4f8", "marks": "hearts",
                       "mark": "#ffb7c5", "tufts": "round", "beak": "#ffc36b"},
    "Carbon": {"feather": "#6e7380", "wing": "#4a4e58", "iris": "#ff9a3c", "belly": "#e6e2ea",
               "marks": "chevrons", "mark": "#aeb3bf", "tufts": "tall"},
    "Midnight": {"feather": "#3e4f9e", "wing": "#2a3570", "iris": "#ffd66b", "face": "#e8ebfa",
                 "belly": "#c9d0f0", "marks": "spots", "mark": "#8e9ad6", "tufts": "tall",
                 "beak": "#ffd66b"},
    "Slate": {"feather": "#6b7f99", "wing": "#4a5a70", "iris": "#4fa3a5", "belly": "#eef1f4",
              "marks": "plain", "beak": "#e0a458"},
    "Arctic": {"feather": "#e3ecf4", "wing": "#a9bccd", "iris": "#f5c400", "face": "#f7fbff",
               "belly": "#ffffff", "marks": "spots", "mark": "#4c566a", "tufts": "tiny",
               "beak": "#4c566a", "feet": "#eef3f8"},   # a snowy owl
    "Paper": {"feather": "#c98a5a", "wing": "#8f5a36", "iris": "#7a5a34", "face": "#fbf5e8",
              "belly": "#f6edda", "marks": "chevrons", "mark": "#b5562c", "beak": "#f0b050"},
    "Vampire": {"feather": "#6b4a8f", "wing": "#45305e", "iris": "#d4213d", "face": "#ece7f1",
                "belly": "#d9cfe3", "marks": "plain", "tufts": "tall", "beak": "#e8c86a"},
    "Forest": {"feather": "#8a6040", "wing": "#5e3f28", "iris": "#5fae3c", "belly": "#e9d6ba",
               "marks": "chevrons", "mark": "#a57a52", "tufts": "swept", "beak": "#d9a441"},
    "Mocha": {"feather": "#8a5a3c", "wing": "#5e3a24", "iris": "#e3a24e", "face": "#f3e3cc",
              "belly": "#f3e3cc", "marks": "spots", "mark": "#c49a74", "tufts": "round",
              "beak": "#d4915a"},
    "Sunset": {"feather": "#ff8f5a", "wing": "#e0603a", "iris": "#ff3d7f", "belly": "#fff1e4",
               "marks": "chevrons", "mark": "#ffc4a0", "tufts": "swept", "beak": "#ffd23d"},
    "Royal": {"feather": "#7c52d9", "wing": "#563a9e", "iris": "#d9a521", "belly": "#f5efff",
              "marks": "spots", "mark": "#e6b93d", "tufts": "tall", "beak": "#e6b93d"},
    "Onion": {"feather": "#ae45d7", "wing": "#7d2fa0", "iris": "#8fd14f", "belly": "#f6ecfa",
              "marks": "chevrons", "mark": "#e2b6f0", "tufts": "round", "feet": "#8fd14f"},
    "Mint": {"feather": "#6fd6aa", "wing": "#3fae84", "iris": "#22b585", "belly": "#f0fbf6",
             "marks": "spots", "mark": "#5a3a28", "tufts": "tiny", "beak": "#ff9fb3"},
    "Synthwave": {"feather": "#ff3f8e", "wing": "#9b5de5", "iris": "#36f9f6", "belly": "#ffe6f4",
                  "marks": "chevrons", "mark": "#ff7ad9", "tufts": "swept", "beak": "#ffcf40",
                  "feet": "#36f9f6"},
    "Vaporwave": {"feather": "#c9a8ff", "wing": "#9f7dff", "iris": "#3fcbdc", "belly": "#c9f2f7",
                  "marks": "hearts", "mark": "#ff9fe0", "tufts": "round", "beak": "#ff9fe0"},
    "Blood Moon": {"feather": "#4a3b4c", "wing": "#2e2430", "iris": "#ff3b2f", "face": "#e6d6d8",
                   "belly": "#c4a0a6", "marks": "chevrons", "mark": "#7a4652", "tufts": "tall",
                   "beak": "#ff8a3d"},
    "Halloween": {"feather": "#4a3a56", "wing": "#2c2233", "iris": "#ff8a1f",
                  "face": "#efe0ef", "belly": "#ffb066", "marks": "chevrons",
                  "mark": "#ff7518", "tufts": "tall", "beak": "#ffcf40", "feet": "#ff8a1f"},
    "Fireworks": {"feather": "#2f3778", "wing": "#1f2556", "iris": "#ffb627",
                  "face": "#fff3dc", "belly": "#ffe2a0", "marks": "spots", "mark": "#ff7fbe",
                  "tufts": "swept", "beak": "#ffb627", "feet": "#ffb627"},
    "Lava": {"feather": "#e0482a", "wing": "#a02a14", "iris": "#ffd23d", "belly": "#ffe0b8",
             "marks": "spots", "mark": "#3d2c2c", "tufts": "swept", "beak": "#ffd23d"},
    "Amber Terminal": {"feather": "#c98a2a", "wing": "#8a5a14", "iris": "#ffb000",
                       "face": "#f3e7c8", "belly": "#f3e7c8", "marks": "chevrons",
                       "mark": "#c99a52", "beak": "#ffb000"},
    "Hacker": {"feather": "#2e3a32", "wing": "#1e2620", "iris": "#39ff7a", "face": "#cfe8d6",
               "belly": "#d4ecd9", "marks": "plain", "tufts": "tall", "beak": "#39ff7a"},
    "Flashbang": {"feather": "#ffd600", "wing": "#ff9100", "iris": "#ff9100", "belly": "#fffbe0",
                  "marks": "spots", "mark": "#ffe680", "tufts": "round", "beak": "#ff9100"},
    "Barbie": {"feather": "#ff6fb5", "wing": "#d6157f", "iris": "#ff4fa3", "face": "#fff0f7",
               "belly": "#fff0f7", "marks": "hearts", "mark": "#ff9fd0", "tufts": "round",
               "beak": "#ffcf40", "feet": "#ff8cc6"},
    "Swamp": {"feather": "#7d8a3c", "wing": "#56602a", "iris": "#e8d84a", "belly": "#c9cf8f",
              "marks": "spots", "mark": "#97a35a", "tufts": "swept", "beak": "#e8b84a"},
    "Deep Fried": {"feather": "#ff7a00", "wing": "#c83a14", "iris": "#ff2a00", "belly": "#f1d394",
                   "marks": "spots", "mark": "#c8862a", "tufts": "tall", "beak": "#ffff00",
                   "feet": "#00ff00"},
    "Retro 98": {"feather": "#008080", "wing": "#005a5a", "iris": "#1a2ab0", "face": "#ffffff",
                 "belly": "#d8d4cc", "marks": "chevrons", "mark": "#8a8a8a", "beak": "#ffcf40"},
    "Comic Sans": {"feather": "#1aa7ec", "wing": "#0f7fbc", "iris": "#e01686", "belly": "#fff8b8",
                   "marks": "spots", "mark": "#86b8ff", "tufts": "round", "beak": "#ff9f1c"},
    "Brainrot": {"feather": "#ff5ce0", "wing": "#7a5cff", "iris": "#8fe000", "belly": "#e8ffb0",
                 "marks": "chevrons", "mark": "#c6ff00", "tufts": "tall", "beak": "#c6ff00"},
}


def look(name: str | None = None) -> dict:
    """Theme `name`'s Hoot (default: the current theme's): VANILLA with its changes."""
    return {**VANILLA, **LOOKS.get(name or hooks.theme_name(), {})}
