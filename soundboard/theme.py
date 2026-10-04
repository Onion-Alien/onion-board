"""Colour themes and the app logo.

A theme is a set of named colour tokens. The Qt stylesheet is built from them, and
the hand-painted widgets (pads, meters, EQ curve, logo) read the same tokens through
`T` when they paint, so switching theme recolours everything live.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QTransform)

# Status colours (inline ok / warn / error messages, danger buttons) most themes share:
# the bright ones read on dark backgrounds, the deep ones on light.
_DARK_STATUS = dict(
    danger_bg="#3a2230", danger_border="#5a2a3e", danger_text="#ff8fa3", danger_hover="#4a2a3c",
    warn_bg="#3a2e14", warn_text="#ffb020",
    ok_text="#13ce66", ok_border="#1c6b45", error_text="#ff4d4f",
)
_LIGHT_STATUS = dict(
    danger_bg="#ffe8ec", danger_border="#f3b3c0", danger_text="#c4213f", danger_hover="#ffd9e0",
    warn_bg="#fff1d6", warn_text="#855000",
    ok_text="#0a6634", ok_border="#7cc39a", error_text="#b01e36",
)

THEMES: dict[str, dict[str, str]] = {
    "Dark": dict(
        bg="#15171f", panel="#1c1f2a", card="#232633", card_hi="#2b2f3f",
        btn="#2a2e3d", btn_hover="#333849", btn_press="#3c4257",
        border="#363b4e", border_hi="#5a6080", groove="#343849", inset="#1b1d26",
        text="#e6e8f0", text_hi="#f1f3f9", muted="#8a90a6", faint="#6b7189", section="#8f96b3",
        accent="#7c5cff", accent_hi="#8d71ff", accent2="#ff4d8d", on_accent="#ffffff",
        off="#4a5068", badge="#343849", badge_text="#d6d9e6",
        danger_bg="#3a2230", danger_border="#5a2a3e", danger_text="#ff8fa3", danger_hover="#4a2a3c",
        warn_bg="#3a2e14", warn_text="#ffb020",
        ok_text="#13ce66", ok_border="#1c6b45", error_text="#ff4d4f",
    ),
    "Light": dict(
        bg="#eef0f6", panel="#ffffff", card="#ffffff", card_hi="#f4f5fa",
        btn="#e7eaf2", btn_hover="#dde1ec", btn_press="#d0d6e4",
        border="#cfd5e2", border_hi="#8f98b3", groove="#d5dae6", inset="#e3e7f0",
        text="#1d2130", text_hi="#11141f", muted="#5c637c", faint="#8a90a6", section="#6a7190",
        accent="#6a4cff", accent_hi="#7d62ff", accent2="#ff3d7f", on_accent="#ffffff",
        off="#b3b9cc", badge="#e3e7f0", badge_text="#2a2f40",
        danger_bg="#ffe8ec", danger_border="#f3b3c0", danger_text="#c4213f", danger_hover="#ffd9e0",
        warn_bg="#fff1d6", warn_text="#855000",
        ok_text="#0a6634", ok_border="#7cc39a", error_text="#b01e36",
    ),
    "Toxic": dict(   # green on near-black
        bg="#0b120e", panel="#111b15", card="#16241c", card_hi="#1c2e23",
        btn="#182a1f", btn_hover="#1f3627", btn_press="#274230",
        border="#27402f", border_hi="#3f6a50", groove="#223829", inset="#0e1711",
        text="#e0f5e8", text_hi="#f0fff5", muted="#7fa08c", faint="#5b7b67", section="#86b597",
        accent="#1ee07f", accent_hi="#45ef98", accent2="#c6ff3d", on_accent="#04140b",
        off="#3a5646", badge="#223829", badge_text="#cfeedd",
        danger_bg="#361d22", danger_border="#5a2a33", danger_text="#ff8f9e", danger_hover="#45242a",
        warn_bg="#33301a", warn_text="#ffc53d",
        ok_text="#13ce66", ok_border="#1c6b45", error_text="#ff4d4f",
    ),
    "Ocean": dict(   # cyan on deep navy
        bg="#0c131d", panel="#111a27", card="#162234", card_hi="#1c2b41",
        btn="#182638", btn_hover="#1f3048", btn_press="#273b57",
        border="#263a54", border_hi="#3d5f86", groove="#22354d", inset="#0e1622",
        text="#e1ecf8", text_hi="#f2f8ff", muted="#7f96b2", faint="#5c738f", section="#87a4c6",
        accent="#1fb6ff", accent_hi="#4cc6ff", accent2="#7c5cff", on_accent="#031320",
        off="#3a4f69", badge="#22354d", badge_text="#d3e3f5",
        danger_bg="#361f2b", danger_border="#5a2a40", danger_text="#ff8fb0", danger_hover="#45243a",
        warn_bg="#33301f", warn_text="#ffb020",
        ok_text="#13ce66", ok_border="#1c6b45", error_text="#ff4d4f",
    ),
    "Cherry Blossom": dict(   # sakura pink on petal white
        bg="#fbecf1", panel="#fff7f9", card="#ffffff", card_hi="#fdf0f4",
        btn="#f8e1e8", btn_hover="#f4d3de", btn_press="#eec3d1",
        border="#efc9d5", border_hi="#d98aa5", groove="#f0cdd8", inset="#f6e3e9",
        text="#3a1f2b", text_hi="#2a1520", muted="#8a5d6e", faint="#b48898", section="#a9607c",
        accent="#d23f6a", accent_hi="#e0527e", accent2="#ffb7c5", on_accent="#ffffff",
        off="#dcb0c0", badge="#f6dde5", badge_text="#5a2f40",
        danger_bg="#ffe3e3", danger_border="#f2a9a9", danger_text="#c0282d", danger_hover="#ffd3d3",
        warn_bg="#fff1d6", warn_text="#855000",
        ok_text="#0a6634", ok_border="#7cc39a", error_text="#b01e36",
    ),
    "Carbon": dict(   # graphite grey, carbon-fibre weave on the panels
        bg="#111113", panel="#1c1c1f", card="#242428", card_hi="#2c2c31",
        btn="#2a2a2f", btn_hover="#333339", btn_press="#3d3d44",
        border="#38383f", border_hi="#5e5e68", groove="#36363c", inset="#161618",
        text="#e4e4e7", text_hi="#f4f4f5", muted="#8e8e97", faint="#6a6a73", section="#9c9ca6",
        accent="#aeb3bf", accent_hi="#c9ccd5", accent2="#6e7380", on_accent="#111113",
        off="#4a4a52", badge="#34343a", badge_text="#d8d8dd",
        danger_bg="#3a2226", danger_border="#5a2a32", danger_text="#ff8f9a", danger_hover="#4a2a30",
        warn_bg="#33301a", warn_text="#ffb020",
        ok_text="#13ce66", ok_border="#1c6b45", error_text="#ff4d4f",
        texture="carbon",
    ),
    # ---- more classics
    "Midnight": dict(   # true black, for OLED screens
        bg="#000000", panel="#0c0c0f", card="#131318", card_hi="#1a1a21",
        btn="#16161c", btn_hover="#1f1f27", btn_press="#292932",
        border="#25252e", border_hi="#45455a", groove="#22222b", inset="#070709",
        text="#e8e8ee", text_hi="#ffffff", muted="#85859a", faint="#5e5e70", section="#9090a8",
        accent="#336bed", accent_hi="#5a8aff", accent2="#b36bff", on_accent="#ffffff",
        off="#3a3a48", badge="#1f1f27", badge_text="#d8d8e4", **_DARK_STATUS,
    ),
    "Slate": dict(   # blue-grey with teal and brass
        bg="#1a2129", panel="#212a34", card="#28323e", card_hi="#2f3b49",
        btn="#2c3744", btn_hover="#354251", btn_press="#3f4e5f",
        border="#3a4757", border_hi="#5b6e84", groove="#37434f", inset="#161c23",
        text="#e2e8ef", text_hi="#f3f6f9", muted="#8d9bab", faint="#687686", section="#9fb0c2",
        accent="#4fa3a5", accent_hi="#63b9bb", accent2="#e0a458", on_accent="#0e1a1b",
        off="#4a5868", badge="#354251", badge_text="#d6dee7",
        **_DARK_STATUS | dict(error_text="#ff7a7c"),
    ),
    "Arctic": dict(   # frosty blue-grey
        bg="#2e3440", panel="#353c4a", card="#3b4252", card_hi="#434c5e",
        btn="#3f4758", btn_hover="#4a5367", btn_press="#545e74",
        border="#4c566a", border_hi="#6b7891", groove="#4c566a", inset="#2a2f3a",
        text="#e5e9f0", text_hi="#eceff4", muted="#a3adc0", faint="#7b869c", section="#93b3d3",
        accent="#88c0d0", accent_hi="#9fd0de", accent2="#b48ead", on_accent="#1d232e",
        off="#5a6479", badge="#434c5e", badge_text="#e5e9f0",
        **_DARK_STATUS | dict(ok_text="#a3e635", error_text="#ff8a8a", warn_text="#ffc857"),
    ),
    "Paper": dict(   # warm sepia, like an old notebook
        bg="#f3ecdf", panel="#fbf7ef", card="#fffdf8", card_hi="#f6efe2",
        btn="#ece3d2", btn_hover="#e4d8c3", btn_press="#d9cab1",
        border="#d8cbb4", border_hi="#a8977a", groove="#dccfb9", inset="#ebe2d1",
        text="#3b3226", text_hi="#2a2319", muted="#6e604a", faint="#a08f74", section="#8a6f47",
        accent="#b5562c", accent_hi="#c9663a", accent2="#2f6f73", on_accent="#ffffff",
        off="#c9b99c", badge="#ece3d2", badge_text="#4a3f30", **_LIGHT_STATUS,
    ),
    "High Contrast": dict(   # black, white and yellow: easiest to read
        bg="#000000", panel="#000000", card="#0a0a0a", card_hi="#141414",
        btn="#000000", btn_hover="#1a1a1a", btn_press="#2a2a2a",
        border="#ffffff", border_hi="#ffff00", groove="#808080", inset="#000000",
        text="#ffffff", text_hi="#ffffff", muted="#e0e0e0", faint="#bdbdbd", section="#ffff00",
        accent="#ffff00", accent_hi="#ffff66", accent2="#00ffff", on_accent="#000000",
        off="#9e9e9e", badge="#1a1a1a", badge_text="#ffffff",
        danger_bg="#3a0000", danger_border="#ff6b6b", danger_text="#ff9e9e", danger_hover="#520000",
        warn_bg="#332b00", warn_text="#ffd000",
        ok_text="#3dff7a", ok_border="#3dff7a", error_text="#ff7070",
    ),
    # ---- colourful
    "Vampire": dict(   # purple and pink on dusk grey
        bg="#1e1f29", panel="#282a36", card="#2f3242", card_hi="#373a4d",
        btn="#343746", btn_hover="#3e4154", btn_press="#494d63",
        border="#44475a", border_hi="#6272a4", groove="#44475a", inset="#191a22",
        text="#f8f8f2", text_hi="#ffffff", muted="#a0a4c0", faint="#6f7494", section="#bd93f9",
        accent="#bd93f9", accent_hi="#caa8fb", accent2="#ff79c6", on_accent="#1e1f29",
        off="#565a70", badge="#3e4154", badge_text="#f0f0ea",
        **_DARK_STATUS | dict(ok_text="#50fa7b", error_text="#ff6e6e"),
    ),
    "Forest": dict(   # moss and bark
        bg="#141a14", panel="#1b231b", card="#222c21", card_hi="#2a3628",
        btn="#263025", btn_hover="#2f3b2d", btn_press="#394837",
        border="#354433", border_hi="#587055", groove="#324030", inset="#101510",
        text="#e6eedf", text_hi="#f4f9ef", muted="#93a58a", faint="#6c7d64", section="#b5c98f",
        accent="#8bbf4d", accent_hi="#9fd060", accent2="#d9a441", on_accent="#122008",
        off="#4a5a45", badge="#2f3b2d", badge_text="#dbe6d1", **_DARK_STATUS,
    ),
    "Mocha": dict(   # coffee browns and caramel
        bg="#1c1714", panel="#251e1a", card="#2d2520", card_hi="#362c26",
        btn="#312822", btn_hover="#3b302a", btn_press="#473a32",
        border="#45382f", border_hi="#6e5a4b", groove="#413429", inset="#171210",
        text="#efe4da", text_hi="#fbf3ec", muted="#a8927f", faint="#7d6a5b", section="#d0a77f",
        accent="#d4915a", accent_hi="#e0a36e", accent2="#a86a4a", on_accent="#1c120a",
        off="#5a4a3f", badge="#3b302a", badge_text="#e8dccf", **_DARK_STATUS,
    ),
    "Sunset": dict(   # orange and pink on plum
        bg="#1f1420", panel="#2a1a2b", card="#332034", card_hi="#3d273e",
        btn="#38233a", btn_hover="#442b46", btn_press="#523452",
        border="#4d2f4f", border_hi="#7a4d7a", groove="#4a2d4b", inset="#1a1019",
        text="#fbe9f0", text_hi="#fff5f8", muted="#c095a8", faint="#8e6a7c", section="#ff9e7a",
        accent="#ff7849", accent_hi="#ff8f66", accent2="#ff3d7f", on_accent="#1f0e0a",
        off="#614160", badge="#442b46", badge_text="#f5dbe5",
        **_DARK_STATUS | dict(error_text="#ff6b6b"),
    ),
    "Royal": dict(   # gold on deep violet
        bg="#140f24", panel="#1c1530", card="#241b3c", card_hi="#2c2248",
        btn="#271e40", btn_hover="#31264f", btn_press="#3c2f5f",
        border="#3a2d5c", border_hi="#5f4c91", groove="#372a58", inset="#100b1d",
        text="#ece6ff", text_hi="#f7f3ff", muted="#a497c7", faint="#766a99", section="#e0bf5c",
        accent="#e6b93d", accent_hi="#f0c95a", accent2="#9d6bff", on_accent="#1c1405",
        off="#4c406e", badge="#31264f", badge_text="#e2daf7", **_DARK_STATUS,
    ),
    "Onion": dict(   # red-onion purple with a green sprout, like the logo
        bg="#1d1224", panel="#27182f", card="#301d3a", card_hi="#3a2446",
        btn="#352040", btn_hover="#40274d", btn_press="#4c2f5b",
        border="#4a2f57", border_hi="#7a4f8e", groove="#472c54", inset="#170e1d",
        text="#f3e6f7", text_hi="#fbf5fd", muted="#b596c2", faint="#846a90", section="#9ad36a",
        accent="#ae45d7", accent_hi="#c064e4", accent2="#8fd14f", on_accent="#ffffff",
        off="#5e416b", badge="#40274d", badge_text="#ecdcf2",
        **_DARK_STATUS | dict(error_text="#ff6b6b"),
    ),
    "Mint": dict(   # fresh mint and white
        bg="#e8f5ef", panel="#f7fcfa", card="#ffffff", card_hi="#eef8f3",
        btn="#dcefe6", btn_hover="#cfe7db", btn_press="#bfdecf",
        border="#c3ddd1", border_hi="#7fb39b", groove="#c9e2d6", inset="#e0f0e8",
        text="#16322a", text_hi="#0c231c", muted="#4d6e62", faint="#85a498", section="#3f7f68",
        accent="#0e8669", accent_hi="#10a07c", accent2="#3f8cff", on_accent="#ffffff",
        off="#a9cbbd", badge="#dcefe6", badge_text="#1e3d33", **_LIGHT_STATUS,
    ),
    # ---- wild
    "Synthwave": dict(   # neon pink and cyan on an 80s grid
        bg="#1a0b2e", panel="#240f3d", card="#2d1450", card_hi="#37195f",
        btn="#2f1553", btn_hover="#3b1b66", btn_press="#472179",
        border="#4a2280", border_hi="#7a3bd1", groove="#45206f", inset="#140824",
        text="#fbe6ff", text_hi="#ffffff", muted="#c49be0", faint="#8a64a8", section="#36f9f6",
        accent="#e5155a", accent_hi="#ff3d7c", accent2="#36f9f6", on_accent="#ffffff",
        off="#5a3585", badge="#3b1b66", badge_text="#f5d7ff",
        **_DARK_STATUS | dict(ok_text="#36f9a0", error_text="#ff6b8b"),
        texture="grid",
    ),
    "Vaporwave": dict(   # A E S T H E T I C pastel pink and mint
        bg="#fce4f4", panel="#fff1fa", card="#ffffff", card_hi="#fdeaf6",
        btn="#f5d5ec", btn_hover="#efc4e4", btn_press="#e6b1d9",
        border="#e9bfdc", border_hi="#c47fb5", groove="#eac6e0", inset="#f6dcee",
        text="#3b1d4a", text_hi="#2a1236", muted="#74508a", faint="#a888b8", section="#1f8a83",
        accent="#9f3dff", accent_hi="#b060ff", accent2="#05e0a1", on_accent="#ffffff",
        off="#d9b3d6", badge="#f5d5ec", badge_text="#4a2860", **_LIGHT_STATUS,
    ),
    "Blood Moon": dict(   # crimson on black
        bg="#120a0b", panel="#1b0f11", card="#241417", card_hi="#2d191d",
        btn="#29161a", btn_hover="#341c21", btn_press="#40232a",
        border="#3e2228", border_hi="#6b3440", groove="#3a1f25", inset="#0d0708",
        text="#f3e3e5", text_hi="#fff4f5", muted="#b08a90", faint="#7f5f65", section="#e0606f",
        accent="#d91f35", accent_hi="#ec3448", accent2="#ff8a3d", on_accent="#ffffff",
        off="#56313a", badge="#341c21", badge_text="#f0d6da",
        **_DARK_STATUS | dict(error_text="#ff7a7c"),
    ),
    "Lava": dict(   # molten orange and yellow
        bg="#150805", panel="#1f0c07", card="#2a1109", card_hi="#35160b",
        btn="#2e130a", btn_hover="#3b180c", btn_press="#4a1e0f",
        border="#4d2010", border_hi="#8a3a14", groove="#45200e", inset="#100604",
        text="#ffe4d1", text_hi="#fff3ea", muted="#d08a63", faint="#9a6043", section="#ffae3d",
        accent="#ff5a1f", accent_hi="#ff7640", accent2="#ffd23d", on_accent="#1a0600",
        off="#5f2b16", badge="#3b180c", badge_text="#ffd9c2",
        **_DARK_STATUS | dict(error_text="#ff7a7c"),
    ),
    "Amber Terminal": dict(   # an old amber CRT, scanlines and all
        bg="#0d0a05", panel="#15100a", card="#1c160d", card_hi="#241c10",
        btn="#1f180e", btn_hover="#2a2012", btn_press="#352816",
        border="#3a2c15", border_hi="#6b5020", groove="#33270f", inset="#0a0804",
        text="#ffc766", text_hi="#ffd98f", muted="#c29445", faint="#7f612c", section="#ffb000",
        accent="#ffb000", accent_hi="#ffc233", accent2="#ff7a00", on_accent="#1a1000",
        off="#54401c", badge="#2a2012", badge_text="#ffd07a",
        **_DARK_STATUS | dict(warn_text="#ffd24d"),
        texture="scanlines", font="Consolas",
    ),
    "Hacker": dict(   # green phosphor. I'm in.
        bg="#020a04", panel="#051208", card="#08190c", card_hi="#0b2110",
        btn="#0a1c0e", btn_hover="#0e2814", btn_press="#13341a",
        border="#11361a", border_hi="#1f6b33", groove="#0f2e17", inset="#010702",
        text="#33ff66", text_hi="#99ffb3", muted="#22b04b", faint="#177a33", section="#33ff66",
        accent="#00ff41", accent_hi="#4dff7a", accent2="#00c8ff", on_accent="#001a07",
        off="#1a4a26", badge="#0e2814", badge_text="#66ff8c",
        **_DARK_STATUS | dict(ok_text="#00ff41"),
        texture="scanlines", font="Consolas",
    ),
    # ---- memes
    "Flashbang": dict(   # light mode, but worse. Your eyes will thank you (they won't)
        bg="#ffffff", panel="#ffffff", card="#ffffff", card_hi="#fafafa",
        btn="#ffffff", btn_hover="#fff9c4", btn_press="#fff176",
        border="#eeeeee", border_hi="#d4b000", groove="#e0e0e0", inset="#fafafa",
        text="#222222", text_hi="#000000", muted="#666666", faint="#9e9e9e", section="#8a6500",
        accent="#ffd600", accent_hi="#a38600", accent2="#ff9100", on_accent="#000000",
        off="#bdbdbd", badge="#fffde7", badge_text="#333333", **_LIGHT_STATUS,
    ),
    "Barbie": dict(   # everything is pink. Everything.
        bg="#ffb3d9", panel="#ffc9e4", card="#ffdcee", card_hi="#ffd0e8",
        btn="#ff9ccf", btn_hover="#ff85c4", btn_press="#ff6eb8",
        border="#ff5fb0", border_hi="#e0218a", groove="#ff8cc6", inset="#ffc0e0",
        text="#4a0027", text_hi="#330019", muted="#7a1650", faint="#a8407c", section="#a3005a",
        accent="#d6157f", accent_hi="#d91a84", accent2="#ff00a0", on_accent="#ffffff",
        off="#e889bd", badge="#ff9ccf", badge_text="#4a0027",
        **_LIGHT_STATUS | dict(ok_text="#044a22", warn_text="#5e3700", error_text="#7a0017",
                               danger_bg="#ffe0e8", danger_text="#9a0f25"),
    ),
    "Swamp": dict(   # what are you doing in my swamp
        bg="#2a3312", panel="#34401a", card="#3e4c1f", card_hi="#485824",
        btn="#425220", btn_hover="#4d5f26", btn_press="#596d2c",
        border="#56692a", border_hi="#86a03e", groove="#50622a", inset="#232b0f",
        text="#eef5d0", text_hi="#fbffe8", muted="#b9c78c", faint="#899960", section="#c9e05a",
        accent="#a4c639", accent_hi="#b6d64c", accent2="#8b5a2b", on_accent="#1a2205",
        off="#647535", badge="#4d5f26", badge_text="#e6efc4",
        **_DARK_STATUS | dict(ok_text="#7dffa8", error_text="#ffa0a0", warn_text="#ffd466"),
        texture="dots",
    ),
    "Deep Fried": dict(   # saturation turned up until the meme cooks
        bg="#3d0a00", panel="#5c1000", card="#7a1a00", card_hi="#8f2200",
        btn="#8a1f00", btn_hover="#a82a00", btn_press="#c43500",
        border="#ff4400", border_hi="#ffcc00", groove="#b32d00", inset="#2e0700",
        text="#ffff00", text_hi="#ffffff", muted="#ffc266", faint="#ff9c3d", section="#00ffff",
        accent="#00ff00", accent_hi="#66ff66", accent2="#ffff00", on_accent="#000000",
        off="#b35900", badge="#a82a00", badge_text="#ffff66",
        danger_bg="#000000", danger_border="#ffff00", danger_text="#ffff00", danger_hover="#222200",
        warn_bg="#000000", warn_text="#ffe066",
        ok_text="#7dff7d", ok_border="#7dff7d", error_text="#ffffff",
        texture="dots",
    ),
    "Retro 98": dict(   # it's 1998 and you just got a new PC
        bg="#c0c0c0", panel="#d4d0c8", card="#ffffff", card_hi="#eeeeee",
        btn="#d4d0c8", btn_hover="#e0ddd6", btn_press="#b8b4ac",
        border="#808080", border_hi="#404040", groove="#a0a0a0", inset="#ffffff",
        text="#000000", text_hi="#000000", muted="#3a3a3a", faint="#6d6d6d", section="#000080",
        accent="#000080", accent_hi="#0e6fae", accent2="#008080", on_accent="#ffffff",
        off="#a0a0a0", badge="#ffffff", badge_text="#000000",
        **_LIGHT_STATUS | dict(ok_text="#005a1e", warn_text="#6b3f00", error_text="#9a0000"),
        font="Tahoma",
    ),
    "Comic Sans": dict(   # the most serious theme
        bg="#fff8b8", panel="#fffbd6", card="#ffffff", card_hi="#fffce6",
        btn="#ffe97a", btn_hover="#ffe14d", btn_press="#ffd41a",
        border="#f2c200", border_hi="#d99a00", groove="#f5dc70", inset="#fff3a0",
        text="#2b1d00", text_hi="#1a1100", muted="#63500f", faint="#a08530", section="#c2006b",
        accent="#e01686", accent_hi="#f7349c", accent2="#1aa7ec", on_accent="#ffffff",
        off="#e0c860", badge="#ffe97a", badge_text="#3a2a00",
        **_LIGHT_STATUS | dict(ok_text="#085a2d", warn_text="#6b3f00", error_text="#a0142e"),
        font="Comic Sans MS",
    ),
    "Brainrot": dict(   # lime and magenta, fighting
        bg="#0d001a", panel="#1a0033", card="#240046", card_hi="#2e0059",
        btn="#29004f", btn_hover="#3a0070", btn_press="#4b0091",
        border="#7a00ff", border_hi="#c6ff00", groove="#3d0073", inset="#08000f",
        text="#c6ff00", text_hi="#eaff80", muted="#ff70ff", faint="#b347d9", section="#00ffea",
        accent="#ff00d4", accent_hi="#ff40df", accent2="#c6ff00", on_accent="#000000",
        off="#52307a", badge="#3a0070", badge_text="#eaff80",
        **_DARK_STATUS | dict(ok_text="#00ffea", error_text="#ff8080"),
        texture="grid",
    ),
}
DEFAULT = "Dark"
# How the Settings window groups the theme cards. Every theme is in exactly one group.
GROUPS: list[tuple[str, list[str]]] = [
    ("Classic", ["Dark", "Light", "Midnight", "Carbon", "Slate", "Arctic", "Paper",
                 "High Contrast"]),
    ("Colourful", ["Ocean", "Toxic", "Vampire", "Forest", "Mocha", "Sunset", "Royal", "Onion",
                   "Mint", "Cherry Blossom"]),
    ("Wild", ["Synthwave", "Vaporwave", "Blood Moon", "Lava", "Amber Terminal", "Hacker"]),
    ("Meme", ["Flashbang", "Barbie", "Swamp", "Deep Fried", "Retro 98", "Comic Sans",
              "Brainrot"]),
]
FONT = "Segoe UI"   # a theme can swap it with a `font` token

T: dict[str, str] = dict(THEMES[DEFAULT])   # current theme (read at paint time)
current_name = DEFAULT


def status(kind: str) -> str:
    """The current theme's colour for an inline "ok", "warn" or "error" message. The
    bright green / amber / red of the dark themes can't be read on the light ones."""
    return T[f"{kind}_text"]


def set_tone(label, kind: str = "") -> None:
    """Colour a label as an "ok", "warn" or "error" message ("" = normal) in a way that
    follows theme changes (the stylesheet's [tone] rules)."""
    if label.property("tone") != kind:
        label.setProperty("tone", kind)
        label.style().unpolish(label)
        label.style().polish(label)


def set_current(name: str) -> str:
    global current_name
    name = name if name in THEMES else DEFAULT
    T.clear()
    T.update(THEMES[name])
    current_name = name
    return name


STYLE = Template("""
QWidget { background:$bg; color:$text; font-family:'$font'; font-size:10pt; }
QDialog { background:$bg; }
QFrame#card { background:$panel; border-radius:12px; }
QFrame#card QWidget { background:transparent; }
QFrame#card[interactive="true"] { border:1px solid transparent; }
QFrame#card[interactive="true"][hovered="true"] { background:$card_hi; border-color:$border_hi; }
QFrame#card[interactive="true"]:focus { background:$card_hi; border-color:$accent; }
QLabel#section { color:$section; font-size:8pt; font-weight:700; letter-spacing:1px; padding-top:8px; }
QLabel#hint, QLabel#muted { color:$muted; }
QLabel#hint { font-size:8.5pt; }
QLabel[tone="ok"], QLabel#hint[tone="ok"] { color:$ok_text; }
QLabel[tone="warn"], QLabel#hint[tone="warn"] { color:$warn_text; }
QLabel[tone="error"], QLabel#hint[tone="error"] { color:$error_text; }
QLabel#eqlabel { color:$muted; font-size:8pt; }
QLabel#empty { color:$muted; font-size:15px; padding:8px 40px 40px 40px; }
QFrame#card QLabel#stepbox { background:$bg; border-radius:8px; padding:8px; margin-top:6px; }
QFrame#card QLabel#resultbox { background:$bg; border-radius:8px; padding:8px; }
QLabel#wordmark { font-size:13pt; font-weight:800; letter-spacing:2px; color:$text_hi; background:transparent; }
QLabel#tagline { color:$muted; font-size:8.5pt; background:transparent; }
QPushButton { background:$btn; border:1px solid $border; border-radius:8px; padding:7px 12px; }
QPushButton:hover { background:$btn_hover; }
QPushButton:focus { border-color:$accent; }
QPushButton#iconbutton { padding:7px 10px; min-width:18px; }
QPushButton:pressed { background:$btn_press; }
QPushButton:checked { background:$accent; border-color:$accent; color:$on_accent; }
QPushButton:disabled { color:$muted; }
QPushButton[busy="true"], QPushButton#primary[busy="true"] { color:$muted; }
QPushButton#primary { background:$accent; border:none; color:$on_accent; font-weight:600; }
QPushButton#primary:hover { background:$accent_hi; }
QPushButton#primary:focus { border:1px solid $text_hi; }
QPushButton#danger { background:$danger_bg; border:1px solid $danger_border; color:$danger_text; font-weight:600; }
QPushButton#danger:hover { background:$danger_hover; }
QPushButton#small { padding:2px 8px; font-size:8pt; }
QPushButton#settings { padding:6px 14px; font-weight:600; }
QFrame#transport, QFrame#deck { background:$panel; border-radius:12px; }
QFrame#mixer { background:transparent; }
QFrame#card QPushButton#primary { background:$accent; color:$on_accent; border:none; padding:9px; }
QFrame#card QPushButton#primary:hover { background:$accent_hi; }
QFrame#vsep { background:$border; border:none; }
QLabel#toast { background:$panel; border:1px solid $border_hi;
               border-radius:12px; padding:8px 14px; }
QFrame#chip { background:$panel; border:1px solid $border; border-radius:14px; }
QFrame#chip[sel="true"] { border-color:$accent; }
QFrame#chip QPushButton { background:transparent; border:none; padding:2px 6px; }
QFrame#chip QPushButton#chipname { font-weight:600; }
QFrame#chip QPushButton#chipstop { border-radius:12px; padding:0; }
QFrame#chip QPushButton#chipstop:hover { background:$danger_bg; }
QLabel#iconlabel { background:transparent; }
QPushButton#pill { border-radius:15px; padding:5px 14px; font-weight:600; }
QPushButton#pill[state="ok"] { color:$ok_text; border:1px solid $ok_border; }
QPushButton#onair { border-radius:15px; padding:5px 14px; font-weight:700;
    background:$danger_bg; border:1px solid $danger_border; color:$danger_text; }
QPushButton#onair:checked { background:#13a35a; border:1px solid #13ce66; color:white; }
QPushButton#onair:checked:hover { background:#16b865; }
QWidget#decktop { background:transparent; }
QLabel#decktitle { color:$section; font-size:8pt; font-weight:700; letter-spacing:1px; }
QPushButton#pill[state="warn"] { background:$warn_bg; color:$warn_text; border:1px solid $warn_text; }
QAbstractSpinBox { background:$bg; border:1px solid $border; border-radius:6px; padding:3px 6px; }
QAbstractSpinBox:hover { border-color:$border_hi; }
QAbstractSpinBox:focus { border-color:$accent; }
QSpinBox::up-button, QSpinBox::down-button { width:0; }
QSpinBox#pct, QFrame#card QSpinBox#pct { background:transparent; border-color:transparent;
    padding:3px 2px; }
QSpinBox#pct:hover, QFrame#card QSpinBox#pct:hover { background:$bg; border-color:$border_hi; }
QSpinBox#pct:focus, QFrame#card QSpinBox#pct:focus { background:$bg; border-color:$accent; }
QDoubleSpinBox, QSpinBox#stepper { padding-right:20px; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox#stepper::up-button, QSpinBox#stepper::down-button {
    subcontrol-origin:border; width:18px; border:none; background:transparent; }
QDoubleSpinBox::up-button, QSpinBox#stepper::up-button {
    subcontrol-position:top right; border-top-right-radius:6px; }
QDoubleSpinBox::down-button, QSpinBox#stepper::down-button {
    subcontrol-position:bottom right; border-bottom-right-radius:6px; }
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover,
QSpinBox#stepper::up-button:hover, QSpinBox#stepper::down-button:hover { background:$btn_hover; }
QDoubleSpinBox::up-arrow, QSpinBox#stepper::up-arrow { image:url("$up_small"); width:8px; height:8px; }
QDoubleSpinBox::down-arrow, QSpinBox#stepper::down-arrow { image:url("$down_small"); width:8px; height:8px; }
QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:off,
QSpinBox#stepper::up-arrow:disabled, QSpinBox#stepper::up-arrow:off { image:url("$up_small_off"); }
QDoubleSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:off,
QSpinBox#stepper::down-arrow:disabled, QSpinBox#stepper::down-arrow:off { image:url("$down_small_off"); }
QSlider::groove:vertical { width:4px; background:$groove; border-radius:2px; }
QSlider::add-page:vertical { background:$accent; border-radius:2px; }
QSlider::handle:vertical { background:white; border:1px solid $border; width:14px; height:14px; margin:0 -5px; border-radius:7px; }
QPushButton#micbanner { background:#e53935; color:white; font-weight:700; font-size:11pt;
    border:none; border-radius:10px; padding:10px; }
QPushButton#miccheck:checked { background:#e53935; border:1px solid #ff6b6b; color:white;
    font-weight:700; }
QFrame#transport QLabel, QFrame#transport QCheckBox, QFrame#transport QSlider,
QFrame#deck QLabel, QFrame#deck QCheckBox, QFrame#deck QSlider { background:transparent; }
QPushButton#round { padding:0; font-size:14pt; border-radius:10px; }
QSlider#seek::groove:horizontal { height:6px; border-radius:3px; }
QSlider#seek::sub-page:horizontal { border-radius:3px; }
QLineEdit, QComboBox { background:$card; border:1px solid $border; border-radius:8px; padding:6px 8px; }
QLineEdit:hover, QComboBox:hover { border-color:$border_hi; }
QLineEdit:focus, QComboBox:focus, QComboBox:on { border-color:$accent; }
QLineEdit { selection-background-color:$accent; selection-color:$on_accent; }
QComboBox { padding:6px 10px; padding-right:30px; combobox-popup:0; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:center right;
    width:26px; border:none; background:transparent; }
QComboBox::down-arrow { image:url("$down"); width:10px; height:10px; }
QComboBox::down-arrow:on { image:url("$up"); }
QComboBox::down-arrow:disabled { image:url("$down_off"); }
QComboBox:disabled, QLineEdit:disabled { color:$muted; background:$inset; }
QFrame#card QComboBox, QFrame#card QPushButton, QFrame#card QLineEdit { background:$card; }
QFrame#card QPushButton:hover:!checked { background:$btn_hover; border-color:$border_hi; }
QFrame#card QPushButton#primary:hover { background:$accent_hi; }
QFrame#card QPushButton:focus { border-color:$accent; }
QFrame#card QComboBox:disabled, QFrame#card QLineEdit:disabled { background:$inset; }
QFrame#card QAbstractSpinBox { background:$bg; }
QFrame#card QPushButton:checked { background:$accent; }
QFrame#card QPushButton#miccheck:checked { background:#e53935; }
QComboBox QAbstractItemView { background:$card; color:$text; border:1px solid $border_hi;
    padding:4px; outline:0; selection-background-color:$accent; selection-color:$on_accent; }
QComboBox QAbstractItemView::item { min-height:28px; padding:0 10px; border-radius:6px; }
QComboBox QAbstractItemView::item:hover { background:$btn_hover; color:$text_hi; }
QComboBox QAbstractItemView::item:selected { background:$accent; color:$on_accent; }
QComboBox QAbstractItemView::item:disabled { color:$faint; }
QPushButton::menu-indicator { image:url("$down"); width:9px; height:9px;
    subcontrol-origin:padding; subcontrol-position:center right; right:2px; }
QPushButton::menu-indicator:open { image:url("$up"); }
QSlider::groove:horizontal { height:4px; background:$groove; border-radius:2px; }
QSlider::sub-page:horizontal { background:$accent; border-radius:2px; }
QSlider::handle:horizontal { background:white; border:1px solid $border; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
QCheckBox::indicator { width:16px; height:16px; border-radius:4px; border:1px solid $off; background:$card; }
QCheckBox::indicator:checked { background:$accent; border-color:$accent; image:url("$check"); }
QCheckBox::indicator:hover { border-color:$border_hi; }
QCheckBox::indicator:checked:hover { background:$accent_hi; border-color:$accent_hi; }
QCheckBox::indicator:disabled { background:$inset; border-color:$border; }
QCheckBox::indicator:checked:disabled { image:url("$check_off"); }
/* radio circles are whole pictures: a stylesheet border-radius:8px on a 16px box
   clips the ring flat on its left edge */
QRadioButton::indicator { width:16px; height:16px; border:none; background:transparent; image:url("$radio"); }
QRadioButton::indicator:hover { image:url("$radio_hover"); }
QRadioButton::indicator:checked { image:url("$radio_on"); }
QRadioButton::indicator:checked:hover { image:url("$radio_on_hover"); }
QRadioButton::indicator:disabled { image:url("$radio_off"); }
QRadioButton::indicator:checked:disabled { image:url("$radio_on_off"); }
QListWidget#settingscategories { background:$panel; border:1px solid $border; outline:0; }
QListWidget#settingscategories::item { padding:4px; }
QListWidget#settingscategories::item:selected { background:$accent; color:$on_accent; }
QListWidget#settingscategories::item:hover:!selected { background:$inset; }
QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { background:transparent; width:10px; }
QScrollBar::handle:vertical { background:$groove; border-radius:5px; min-height:30px; }
QScrollBar::handle:vertical:hover { background:$border_hi; }
QScrollBar:horizontal { background:transparent; height:10px; }
QScrollBar::handle:horizontal { background:$groove; border-radius:5px; min-width:30px; }
QScrollBar::handle:horizontal:hover { background:$border_hi; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QMenu { background:$card; border:1px solid $border_hi; padding:5px; }
QMenu::item { padding:7px 22px 7px 12px; border-radius:6px; margin:1px 0; }
QMenu::item:selected { background:$accent; color:$on_accent; }
QMenu::item:disabled { color:$faint; }
QMenu::icon { padding-left:10px; }
QMenu::separator { height:1px; background:$border; margin:5px 8px; }
QToolTip { background:$card; color:$text; border:1px solid $border_hi; border-radius:6px; padding:5px 8px; }
QTabWidget::pane { border:none; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background:transparent; color:$muted; padding:8px 16px; margin-right:4px;
    border:none; border-bottom:2px solid transparent; font-weight:600; }
QTabBar::tab:selected { color:$text; border-bottom:2px solid $accent; }
QTabBar::tab:hover { color:$text; }
QTabBar::scroller { width:48px; }
QTabBar QToolButton { background:$btn; border:none; border-radius:8px; margin:5px 0 5px 2px; }
QTabBar QToolButton:hover { background:$btn_hover; }
QTabBar QToolButton:disabled { background:$bg; }
QTabBar QToolButton::left-arrow { image:url("$left"); width:10px; height:10px; }
QTabBar QToolButton::right-arrow { image:url("$right"); width:10px; height:10px; }
QTabBar QToolButton::left-arrow:disabled { image:url("$left_off"); }
QTabBar QToolButton::right-arrow:disabled { image:url("$right_off"); }
QTabBar::tear { width:0; border:none; }
QPushButton#live { font-weight:700; }
QPushButton#voicetile { text-align:left; padding:9px 10px; border-radius:10px; }
QPushButton#voicetile:checked { background:$accent; color:$on_accent; border:1px solid $accent_hi; font-weight:700; }
QPushButton#voicetile[art="true"] { padding:5px 10px 5px 6px; }
QPushButton#voicetile:hover:!checked { border-color:$border_hi; }
/* Spacious controls only in Voice and Setup cards. */
QFrame#card[roomy="true"] QPushButton { padding:9px 14px; min-height:18px; }
QFrame#card[roomy="true"] QPushButton#primary { padding:10px 16px; }
QFrame#card[roomy="true"] QPushButton#voicetile { padding:7px 12px; text-align:left; }
QFrame#card[roomy="true"] QPushButton#fold { padding:8px 10px; text-align:left; }
QFrame#card[roomy="true"] QComboBox { padding:9px 12px; }
QPlainTextEdit#speechlog { background:$bg; border:1px solid $border; border-radius:8px; padding:8px; }

QWidget#fxrow { border:1px solid transparent; border-radius:8px; }
QWidget#fxrow[fresh="true"] { background:$card_hi; border-color:$accent; }
QPushButton#fold { background:transparent; border:none; color:$muted; padding:3px 6px; font-size:8.5pt; font-weight:600; }
QPushButton#fold:hover, QPushButton#fold:checked { color:$text; background:transparent; }
QFrame#card QPushButton#fold, QFrame#card QPushButton#fold:checked { background:transparent; }
QPushButton#power { font-weight:700; }
QPushButton#power:checked, QFrame#card QPushButton#power:checked { background:#13a35a; border:1px solid #13ce66; color:white; }
QPushButton#live:checked { background:#e53935; border:1px solid #ff6b6b; color:white; }
QPushButton#rec:checked { background:#e53935; border:1px solid #ff6b6b; color:white; font-weight:700; }
QPushButton#lite:checked { background:#13a35a; border:1px solid #13ce66; color:white; font-weight:700; }
QFrame#setcard { background:$panel; border-radius:12px; }
QFrame#setcard QWidget { background:transparent; }
QFrame#setcard QPushButton { background:$btn; }
QFrame#setcard QPushButton:hover { background:$btn_hover; border-color:$border_hi; }
QFrame#setcard QPushButton:checked { background:$accent; color:$on_accent; }
QFrame#setcard QPushButton#primary { background:$accent; color:$on_accent; border:none; }
QFrame#setcard QPushButton#primary:hover { background:$accent_hi; }
QTableView, QFrame#setcard QTableView { background:$card; alternate-background-color:$card_hi;
    color:$text; border:1px solid $border; border-radius:6px;
    selection-background-color:$accent; selection-color:$on_accent; }
QTableView::item { padding:5px 8px; border:none; }
QTableView::item:hover { background:$btn_hover; }
QTableView::item:selected { background:$accent; color:$on_accent; }
QHeaderView, QFrame#setcard QHeaderView { background:$btn; color:$text; }
QHeaderView::section, QFrame#setcard QHeaderView::section { background:$btn; color:$text;
    padding:8px; border:none; border-bottom:1px solid $border; font-weight:600; }
QTableCornerButton::section { background:$btn; border:none; }
QFrame#setcard QPlainTextEdit { background:$card; color:$text;
    border:1px solid $border; border-radius:6px; padding:8px;
    selection-background-color:$accent; selection-color:$on_accent; }
QProgressBar#downloadprogress, QFrame#card QProgressBar#downloadprogress {
    background:$groove; border:none; border-radius:2px; }
QProgressBar#downloadprogress::chunk { background:$accent; border-radius:2px; }
QPushButton#hkbtn { min-width:150px; font-weight:600; }
QPushButton#themecard { background:$panel; border:2px solid $border; border-radius:12px; padding:0; }
QPushButton#themecard:hover { border-color:$border_hi; }
QPushButton#themecard:checked { background:$panel; border:2px solid $accent; }
QFrame#card QFrame#chip { background:$btn; border:1px solid $border; border-radius:11px; }
QFrame#card QFrame#chip:hover { border-color:$border_hi; }
QFrame#card QFrame#chip[sel="true"] { border-color:$accent; }
QFrame#card QFrame#chip QPushButton { background:transparent; border:none; }
QFrame#card QFrame#chip QPushButton#chipname:hover { color:$text_hi; }
QFrame#card QFrame#chip QPushButton#chipstop { border-radius:11px; color:$muted; }
QFrame#card QFrame#chip QPushButton#chipstop:hover { background:$danger_bg; color:$danger_text; }
/* popups (combo lists, menus) are children of the widget that opens them, so the
   "card QWidget { transparent }" rules above reach them and a see-through popup draws black.
   Last so it wins the tie with those rules. */
QFrame#card QComboBox QAbstractItemView, QFrame#setcard QComboBox QAbstractItemView,
QFrame#card QComboBoxPrivateContainer, QFrame#setcard QComboBoxPrivateContainer,
QFrame#card QMenu, QFrame#setcard QMenu { background:$card; }
""")


def _check_image(colour: str, size: int) -> QImage:
    """A rounded tick, drawn in code so it follows the theme's on-accent colour."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(colour), size * 0.16)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(size * 0.22, size * 0.52))
    path.lineTo(QPointF(size * 0.42, size * 0.72))
    path.lineTo(QPointF(size * 0.78, size * 0.30))
    p.drawPath(path)
    p.end()
    return img


def _check_url(colour: str) -> str:
    """Stylesheets need a file for `image:`, so write the tick (plus an @2x copy Qt picks
    on high-DPI screens) to the temp folder once per colour."""
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    base = folder / f"check-{colour.lstrip('#')}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, size in ((base, 14), (base.with_name(base.stem + "@2x.png"), 28)):
            if not path.exists():
                _check_image(colour, size).save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def _radio_image(ring: str, fill: str, dot: str, size: int) -> QImage:
    """A whole radio circle: a 1px ring (scaled with `size`) around `fill`, plus a centre
    dot when `dot` is set. Kept half a pixel inside the edge so no side gets clipped."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen_w = size / 16
    p.setPen(QPen(QColor(ring), pen_w))
    p.setBrush(QColor(fill))
    r = size / 2 - pen_w / 2 - size / 64
    p.drawEllipse(QPointF(size / 2, size / 2), r, r)
    if dot:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(dot))
        p.drawEllipse(QPointF(size / 2, size / 2), size * 0.22, size * 0.22)
    p.end()
    return img


def _radio_url(ring: str, fill: str, dot: str = "") -> str:
    """The radio circle as a file for `image:`, plus a sharp high-DPI copy."""
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    name = "-".join(c.lstrip("#") for c in (ring, fill, dot) if c)
    base = folder / f"radio2-{name}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, size in ((base, 16), (base.with_name(base.stem + "@2x.png"), 32)):
            if not path.exists():
                _radio_image(ring, fill, dot, size).save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def _chevron_image(colour: str, size: int, up: bool) -> QImage:
    """A rounded chevron (dropdown / stepper arrow), drawn in code like the tick."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(colour), size * 0.17)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    tip, ends = (0.34, 0.64) if up else (0.66, 0.36)
    path = QPainterPath(QPointF(size * 0.18, size * ends))
    path.lineTo(QPointF(size * 0.5, size * tip))
    path.lineTo(QPointF(size * 0.82, size * ends))
    p.drawPath(path)
    p.end()
    return img


def _chevron_url(colour: str, size: int, up: bool, side: str = "") -> str:
    """`side` "left" / "right" turns the down chevron on its side (tab-bar scroll arrows)."""
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    name = side or ("up" if up else "down")
    base = folder / f"chevron-{name}{size}-{colour.lstrip('#')}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, px in ((base, size), (base.with_name(base.stem + "@2x.png"), size * 2)):
            if not path.exists():
                img = _chevron_image(colour, px, up)
                if side:
                    img = img.transformed(QTransform().rotate(90 if side == "left" else -90))
                img.save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def _carbon_image(base: str, size: int) -> QImage:
    """One tile of 2x2 twill weave: each cell is a tow of fibres shaded across its
    width, the neighbouring cells turned 90 degrees, so it tiles into carbon fibre."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(QColor(base))
    p = QPainter(img)
    c = size / 2
    dark, light = QColor(base).darker(150), QColor(base).lighter(135)
    for i in range(2):
        for j in range(2):
            x, y = i * c, j * c
            if (i + j) % 2:
                g = QLinearGradient(QPointF(x, y), QPointF(x + c, y))
            else:
                g = QLinearGradient(QPointF(x, y), QPointF(x, y + c))
            g.setColorAt(0.0, dark)
            g.setColorAt(0.5, light)
            g.setColorAt(1.0, dark)
            p.fillRect(QRectF(x, y, c, c), g)
    p.end()
    return img


def _pattern_image(kind: str, base: str, size: int) -> QImage:
    """The simpler tiling patterns: CRT scanlines, a neon grid, polka dots. Each is the
    panel colour a shade lighter or darker, so text on it stays readable."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(QColor(base))
    p = QPainter(img)
    if kind == "scanlines":   # a darker row every third pixel
        for y in range(0, size, 3):
            p.fillRect(QRectF(0, y, size, 1), QColor(base).darker(135))
    elif kind == "grid":      # one lit line along the top and left of each tile
        line = QColor(base).lighter(150)
        p.fillRect(QRectF(0, 0, size, 1), line)
        p.fillRect(QRectF(0, 0, 1, size), line)
    elif kind == "dots":
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(base).lighter(125))
        r = size * 0.14
        for c in (0.25, 0.75):
            p.drawEllipse(QPointF(size * c, size * c), r, r)
    p.end()
    return img


TEXTURE_TILE = {"carbon": 14, "scanlines": 3, "grid": 24, "dots": 12}


def texture_image(kind: str, base: str, size: int | None = None) -> QImage:
    """One tile of theme texture `kind` ("carbon", "scanlines", "grid", "dots") on `base`."""
    size = size or TEXTURE_TILE.get(kind, 14)
    return _carbon_image(base, size) if kind == "carbon" else _pattern_image(kind, base, size)


def _texture_url(kind: str, base: str) -> str:
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    size = TEXTURE_TILE.get(kind, 14)
    path = folder / f"{kind}{size}-{base.lstrip('#')}.png"
    try:
        folder.mkdir(exist_ok=True)
        if not path.exists():
            texture_image(kind, base, size).save(str(path))
    except OSError:
        return ""
    return path.as_posix()


def is_light(name: str | None = None) -> bool:
    """Whether theme `name` (default: the current one) has a light background."""
    c = QColor(THEMES.get(name or current_name, THEMES[DEFAULT])["bg"])
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 140


def stylesheet(name: str | None = None) -> str:
    tokens = dict(THEMES.get(name or current_name, THEMES[DEFAULT]))
    tokens.setdefault("font", FONT)
    tokens["check"] = _check_url(tokens["on_accent"])
    tokens["check_off"] = _check_url(tokens["muted"])   # ticked but greyed out: on $inset
    tokens["radio"] = _radio_url(tokens["off"], tokens["card"])
    tokens["radio_hover"] = _radio_url(tokens["border_hi"], tokens["card"])
    tokens["radio_on"] = _radio_url(tokens["accent"], tokens["accent"], tokens["on_accent"])
    tokens["radio_on_hover"] = _radio_url(tokens["accent_hi"], tokens["accent_hi"], tokens["on_accent"])
    tokens["radio_off"] = _radio_url(tokens["border"], tokens["inset"])
    tokens["radio_on_off"] = _radio_url(tokens["border"], tokens["inset"], tokens["muted"])
    for key, colour in (("", tokens["muted"]), ("_off", tokens["off"])):
        tokens["down" + key] = _chevron_url(colour, 10, up=False)
        tokens["up" + key] = _chevron_url(colour, 10, up=True)
        tokens["down_small" + key] = _chevron_url(colour, 8, up=False)
        tokens["up_small" + key] = _chevron_url(colour, 8, up=True)
        tokens["left" + key] = _chevron_url(colour, 10, False, side="left")
        tokens["right" + key] = _chevron_url(colour, 10, False, side="right")
    css = STYLE.substitute(tokens)
    if tokens.get("texture") and (url := _texture_url(tokens["texture"], tokens["panel"])):
        css += ("QFrame#card, QFrame#transport, QFrame#deck, QFrame#setcard "
                f'{{ background-image:url("{url}"); }}\n')
    return css


# Text colours code writes straight into a label's rich text or a widget's own stylesheet
# (status(), T["faint"]...): a live theme switch swaps the old theme's for the new one's.
_INLINE_KEYS = ("ok_text", "warn_text", "error_text", "danger_text", "text", "text_hi",
                "muted", "faint", "section", "accent", "accent_hi")
_TEXT_COLOUR = re.compile(r"(?<![-\w])(color:\s*)(#[0-9a-fA-F]{6})(?![0-9a-fA-F])")


def _recolour_inline(widgets, old: dict[str, str]) -> None:
    """Only `color:` (text), never backgrounds or borders: those can be a sound's own
    colour that merely matches a token."""
    swap: dict[str, str] = {}
    for k in _INLINE_KEYS:
        if k in old and k in T:
            swap.setdefault(old[k].lower(), T[k])
    swap = {a: b for a, b in swap.items() if a != b.lower()}
    if not swap:
        return

    def sub(text: str) -> str:
        return _TEXT_COLOUR.sub(lambda m: m[1] + swap.get(m[2].lower(), m[2]), text)
    for w in widgets:
        try:
            css = w.styleSheet()
            if "color" in css and (new := sub(css)) != css:
                w.setStyleSheet(new)
            if not hasattr(w, "textFormat"):   # QLabel: its rich text
                continue
            text = w.text()
            if "color" in text and (new := sub(text)) != text:
                w.setText(new)
        except RuntimeError:   # being deleted
            pass


def apply(app, name: str) -> str:
    """Switch the whole app to theme `name` (live)."""
    old = dict(T)
    name = set_current(name)
    app.setStyleSheet(stylesheet(name))
    widgets = app.allWidgets()
    _recolour_inline(widgets, old)
    for w in widgets:   # hand-painted widgets read T in paintEvent
        w.update()
    return name


# --------------------------------------------------------------------------- logo

def paint_logo(p: QPainter, rect: QRectF, c1: str, c2: str):
    """The Onion Board mark: a gradient squircle holding an onion whose layers
    are drawn as sound-wave arcs — onion + soundboard in one shape."""
    s = rect.width()
    x0, y0 = rect.left(), rect.top()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    # body
    g = QLinearGradient(QPointF(x0, y0), QPointF(x0 + s, y0 + s))
    g.setColorAt(0.0, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    body = QPainterPath()
    body.addRoundedRect(QRectF(x0 + s * 0.04, y0 + s * 0.04, s * 0.92, s * 0.92), s * 0.26, s * 0.26)
    p.fillPath(body, g)
    # soft top highlight
    hi = QLinearGradient(QPointF(x0, y0), QPointF(x0, y0 + s * 0.6))
    hi.setColorAt(0.0, QColor(255, 255, 255, 60))
    hi.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(body, hi)
    # the onion is white, or near-black on light accents (e.g. Toxic's lime) so it stays legible
    a, b = QColor(c1), QColor(c2)
    lum = sum((0.299 * q.red() + 0.587 * q.green() + 0.114 * q.blue()) / 2 for q in (a, b))
    fg = QColor("#0b1a10") if lum > 165 else QColor("white")
    cx = x0 + s * 0.5

    def pt(dx, dy):   # offsets in units of s, from the top-centre of the icon
        return QPointF(cx + dx * s, y0 + dy * s)

    def bulb(w):   # onion outline, w = half-width at the widest point
        path = QPainterPath(pt(0, 0.27))
        path.cubicTo(pt(w * 0.25, 0.36), pt(w, 0.42), pt(w, 0.59))
        path.cubicTo(pt(w, 0.74), pt(w * 0.55, 0.81), pt(0, 0.81))
        path.cubicTo(pt(-w * 0.55, 0.81), pt(-w, 0.74), pt(-w, 0.59))
        path.cubicTo(pt(-w, 0.42), pt(-w * 0.25, 0.36), pt(0, 0.27))
        return path

    # sprout: two leaves curling out of the neck
    pen = QPen(fg, max(1.2, s * 0.05))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    leaf = QPainterPath(pt(0, 0.29))
    leaf.cubicTo(pt(0, 0.20), pt(-0.04, 0.15), pt(-0.12, 0.12))
    leaf.moveTo(pt(0, 0.27))
    leaf.cubicTo(pt(0.01, 0.19), pt(0.05, 0.14), pt(0.10, 0.10))
    p.drawPath(leaf)
    # bulb
    p.setPen(Qt.NoPen)
    p.fillPath(bulb(0.29), fg)
    # layers: inner outlines in the brand gradient, reading like sound waves
    if s >= 20:
        lp = QPen(g, max(1.0, s * 0.032))
        lp.setCapStyle(Qt.RoundCap)
        p.setPen(lp)
        for w in ((0.17, 0.07) if s >= 40 else (0.13,)):
            p.drawPath(bulb(w))
    # roots
    if s >= 32:
        rp = QPen(fg, max(1.0, s * 0.03))
        rp.setCapStyle(Qt.RoundCap)
        p.setPen(rp)
        for dx in (-0.06, 0.0, 0.06):
            p.drawLine(pt(dx * 0.6, 0.81), pt(dx, 0.87))
    p.restore()


BRAND = ("#7c5cff", "#ff4d8d")   # the app icon keeps its own colours in every theme


def logo_pixmap(size: int, c1: str | None = None, c2: str | None = None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint_logo(p, QRectF(0, 0, size, size), c1 or BRAND[0], c2 or BRAND[1])
    p.end()
    return pm


def app_icon(c1: str | None = None, c2: str | None = None) -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(sz, c1, c2))
    return icon


def logo_image(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint_logo(p, QRectF(0, 0, size, size), *BRAND)
    p.end()
    return img
