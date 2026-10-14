"""The themes' colours, shared by Onion Board and Onion Watch.

A theme is a set of named colour tokens. THEMES holds the hand-picked ones, each
finished at import (finish()) with the tokens worked out from them so text reads on
every surface. The app's theme module keeps the current theme (`T`) and builds its
stylesheet from these.

Part of the style kit (see __init__.py): imports nothing from either app.
"""
from __future__ import annotations

import re
from string import Template

from PySide6.QtGui import QColor

from . import hooks

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
    "Dark": dict(   # neutral charcoal: no blue cast, hairline borders
        bg="#0f0f11", panel="#17171a", card="#1d1d21", card_hi="#25252a",
        btn="#26262b", btn_hover="#2e2e34", btn_press="#37373e",
        border="#2a2a30", border_hi="#4d4d56", groove="#2c2c33", inset="#131316",
        text="#ececee", text_hi="#fafafa", muted="#8d8d95", faint="#6c6c74", section="#9c9ca5",
        accent="#7859f7", accent_hi="#8d71ff", accent2="#ff4d8d", on_accent="#ffffff",
        off="#4a4a54", badge="#2c2c33", badge_text="#d8d8de",
        danger_bg="#3f1d27", danger_border="#5f2a3a", danger_text="#ff8fa3", danger_hover="#4f2531",
        warn_bg="#3a2e14", warn_text="#ffb020",
        ok_text="#13ce66", ok_border="#1c6b45", error_text="#ff4d4f",
    ),
    "Light": dict(   # neutral off-white, pure white cards, hairline borders
        bg="#f4f4f6", panel="#ffffff", card="#ffffff", card_hi="#f7f7f9",
        btn="#ededf0", btn_hover="#e2e2e7", btn_press="#d6d6dd",
        border="#e4e4e9", border_hi="#a3a3ad", groove="#e1e1e7", inset="#f1f1f4",
        text="#1b1b20", text_hi="#0b0b0e", muted="#6c6c77", faint="#9a9aa4", section="#72727e",
        accent="#6a4cff", accent_hi="#7d62ff", accent2="#ff3d7f", on_accent="#ffffff",
        off="#b6b6c0", badge="#ececf0", badge_text="#2a2a33",
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
        texture="diagonal",
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
        texture="waves",
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
        texture="petals",
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
        texture="diagonal",
        off="#4a5868", badge="#354251", badge_text="#d6dee7",
        **_DARK_STATUS | dict(error_text="#ff7a7c"),
    ),
    "Arctic": dict(   # frosty blue-grey
        bg="#2e3440", panel="#353c4a", card="#3b4252", card_hi="#434c5e",
        btn="#3f4758", btn_hover="#4a5367", btn_press="#545e74",
        border="#4c566a", border_hi="#6b7891", groove="#4c566a", inset="#2a2f3a",
        text="#e5e9f0", text_hi="#eceff4", muted="#a3adc0", faint="#7b869c", section="#93b3d3",
        accent="#88c0d0", accent_hi="#9fd0de", accent2="#b48ead", on_accent="#1d232e",
        texture="frost",
        off="#5a6479", badge="#434c5e", badge_text="#e5e9f0",
        **_DARK_STATUS | dict(ok_text="#a3e635", error_text="#ff8a8a", warn_text="#ffc857"),
    ),
    "Paper": dict(   # warm sepia, like an old notebook
        bg="#f3ecdf", panel="#fbf7ef", card="#fffdf8", card_hi="#f6efe2",
        btn="#ece3d2", btn_hover="#e4d8c3", btn_press="#d9cab1",
        border="#d8cbb4", border_hi="#a8977a", groove="#dccfb9", inset="#ebe2d1",
        text="#3b3226", text_hi="#2a2319", muted="#6e604a", faint="#a08f74", section="#8a6f47",
        accent="#b5562c", accent_hi="#c9663a", accent2="#2f6f73", on_accent="#ffffff",
        texture="ruled",
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
        texture="crosshatch",
        off="#565a70", badge="#3e4154", badge_text="#f0f0ea",
        **_DARK_STATUS | dict(ok_text="#50fa7b", error_text="#ff6e6e"),
    ),
    "Forest": dict(   # moss and bark
        bg="#141a14", panel="#1b231b", card="#222c21", card_hi="#2a3628",
        btn="#263025", btn_hover="#2f3b2d", btn_press="#394837",
        border="#354433", border_hi="#587055", groove="#324030", inset="#101510",
        text="#e6eedf", text_hi="#f4f9ef", muted="#93a58a", faint="#6c7d64", section="#b5c98f",
        accent="#8bbf4d", accent_hi="#9fd060", accent2="#d9a441", on_accent="#122008",
        texture="crosshatch",
        off="#4a5a45", badge="#2f3b2d", badge_text="#dbe6d1", **_DARK_STATUS,
    ),
    "Mocha": dict(   # coffee browns and caramel
        bg="#1c1714", panel="#251e1a", card="#2d2520", card_hi="#362c26",
        btn="#312822", btn_hover="#3b302a", btn_press="#473a32",
        border="#45382f", border_hi="#6e5a4b", groove="#413429", inset="#171210",
        text="#efe4da", text_hi="#fbf3ec", muted="#a8927f", faint="#7d6a5b", section="#b9b0a8",
        accent="#d4915a", accent_hi="#e0a36e", accent2="#a86a4a", on_accent="#1c120a",
        texture="crosshatch",
        off="#5a4a3f", badge="#3b302a", badge_text="#e8dccf", **_DARK_STATUS,
    ),
    "Sunset": dict(   # orange and pink on plum
        bg="#1f1420", panel="#2a1a2b", card="#332034", card_hi="#3d273e",
        btn="#38233a", btn_hover="#442b46", btn_press="#523452",
        border="#4d2f4f", border_hi="#7a4d7a", groove="#4a2d4b", inset="#1a1019",
        text="#fbe9f0", text_hi="#fff5f8", muted="#c095a8", faint="#8e6a7c", section="#ff9e7a",
        accent="#ff7849", accent_hi="#ff8f66", accent2="#ff3d7f", on_accent="#1f0e0a",
        texture="diagonal",
        off="#614160", badge="#442b46", badge_text="#f5dbe5",
        **_DARK_STATUS | dict(error_text="#ff6b6b"),
    ),
    "Royal": dict(   # gold on deep violet
        bg="#140f24", panel="#1c1530", card="#241b3c", card_hi="#2c2248",
        btn="#271e40", btn_hover="#31264f", btn_press="#3c2f5f",
        border="#3a2d5c", border_hi="#5f4c91", groove="#372a58", inset="#100b1d",
        text="#ece6ff", text_hi="#f7f3ff", muted="#a497c7", faint="#766a99", section="#e0bf5c",
        accent="#e6b93d", accent_hi="#f0c95a", accent2="#9d6bff", on_accent="#1c1405",
        texture="diamond",
        off="#4c406e", badge="#31264f", badge_text="#e2daf7", **_DARK_STATUS,
    ),
    "Onion": dict(   # red-onion purple with a green sprout, like the logo
        bg="#1d1224", panel="#27182f", card="#301d3a", card_hi="#3a2446",
        btn="#352040", btn_hover="#40274d", btn_press="#4c2f5b",
        border="#4a2f57", border_hi="#7a4f8e", groove="#472c54", inset="#170e1d",
        text="#f3e6f7", text_hi="#fbf5fd", muted="#b596c2", faint="#846a90", section="#9ad36a",
        accent="#ae45d7", accent_hi="#c064e4", accent2="#8fd14f", on_accent="#ffffff",
        texture="scales",
        off="#5e416b", badge="#40274d", badge_text="#ecdcf2",
        **_DARK_STATUS | dict(error_text="#ff6b6b"),
    ),
    "Lilac": dict(   # Dark's calm greys with a touch of purple, logo pink as the second colour
        bg="#16121c", panel="#1d1826", card="#251e31", card_hi="#2e263c",
        btn="#2a2336", btn_hover="#342b43", btn_press="#3e3450",
        border="#3a3049", border_hi="#5e5079", groove="#352c44", inset="#19141f",
        text="#ebe5f4", text_hi="#f7f2ff", muted="#9b90b0", faint="#75698b", section="#a598c4",
        accent="#8f4cf5", accent_hi="#a066ff", accent2="#ff5fa2", on_accent="#ffffff",
        texture="frost",
        off="#4d4262", badge="#352c44", badge_text="#e2d9f0", **_DARK_STATUS,
    ),
    "Mint": dict(   # fresh mint and white
        bg="#e8f5ef", panel="#f7fcfa", card="#ffffff", card_hi="#eef8f3",
        btn="#dcefe6", btn_hover="#cfe7db", btn_press="#bfdecf",
        border="#c3ddd1", border_hi="#7fb39b", groove="#c9e2d6", inset="#e0f0e8",
        text="#16322a", text_hi="#0c231c", muted="#4d6e62", faint="#85a498", section="#3f7f68",
        accent="#0e8669", accent_hi="#10a07c", accent2="#3f8cff", on_accent="#ffffff",
        texture="diagonal",
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
        texture="grid",
        off="#d9b3d6", badge="#f5d5ec", badge_text="#4a2860", **_LIGHT_STATUS,
    ),
    "Blood Moon": dict(   # crimson on black
        bg="#120a0b", panel="#1b0f11", card="#241417", card_hi="#2d191d",
        btn="#29161a", btn_hover="#341c21", btn_press="#40232a",
        border="#3e2228", border_hi="#6b3440", groove="#3a1f25", inset="#0d0708",
        text="#f3e3e5", text_hi="#fff4f5", muted="#b08a90", faint="#7f5f65", section="#e0606f",
        accent="#d91f35", accent_hi="#ec3448", accent2="#ff8a3d", on_accent="#ffffff",
        texture="embers",
        off="#56313a", badge="#341c21", badge_text="#f0d6da",
        **_DARK_STATUS | dict(error_text="#ff7a7c"),
    ),
    "Lava": dict(   # molten orange and yellow
        bg="#150805", panel="#1f0c07", card="#2a1109", card_hi="#35160b",
        btn="#2e130a", btn_hover="#3b180c", btn_press="#4a1e0f",
        border="#4d2010", border_hi="#8a3a14", groove="#45200e", inset="#100604",
        text="#ffe4d1", text_hi="#fff3ea", muted="#d08a63", faint="#9a6043", section="#ffae3d",
        accent="#ff5a1f", accent_hi="#ff7640", accent2="#ffd23d", on_accent="#1a0600",
        texture="embers",
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
        # the window, panels and cards are all white: the language / theme tiles, the
        # Radio Favorites / Recent strip and the map's + / - get a grey of their own
        tile="#eeeeee", segbox="#eeeeee", map_btn="#eeeeee",
    ),
    "Barbie": dict(   # everything is pink. Everything.
        bg="#ffb3d9", panel="#ffc9e4", card="#ffdcee", card_hi="#ffd0e8",
        btn="#ff9ccf", btn_hover="#ff85c4", btn_press="#ff6eb8",
        border="#ff5fb0", border_hi="#e0218a", groove="#ff8cc6", inset="#ffc0e0",
        text="#4a0027", text_hi="#330019", muted="#7a1650", faint="#a8407c", section="#a3005a",
        accent="#d6157f", accent_hi="#d91a84", accent2="#ff00a0", on_accent="#ffffff",
        texture="dots",
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
        texture="dither",
        off="#a0a0a0", badge="#ffffff", badge_text="#000000",
        **_LIGHT_STATUS | dict(ok_text="#004a18", warn_text="#5c3600", error_text="#880000"),
        font="Tahoma",
    ),
    "Comic Sans": dict(   # the most serious theme
        bg="#fff8b8", panel="#fffbd6", card="#ffffff", card_hi="#fffce6",
        btn="#ffe97a", btn_hover="#ffe14d", btn_press="#ffd41a",
        border="#f2c200", border_hi="#d99a00", groove="#f5dc70", inset="#fff3a0",
        text="#2b1d00", text_hi="#1a1100", muted="#63500f", faint="#a08530", section="#c2006b",
        accent="#e01686", accent_hi="#f7349c", accent2="#1aa7ec", on_accent="#ffffff",
        texture="halftone",
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


def _contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two colours (1 = same, 21 = black on white)."""
    def lum(hex_: str) -> float:
        c = QColor(hex_)
        ch = [v / 255 for v in (c.red(), c.green(), c.blue())]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _mix(a: str, b: str, t: float) -> str:
    """`a` moved fraction `t` of the way to `b`."""
    ca, cb = QColor(a), QColor(b)
    return QColor(*(round(x + (y - x) * t) for x, y in (
        (ca.red(), cb.red()), (ca.green(), cb.green()), (ca.blue(), cb.blue())))).name()


mix = _mix   # for widgets that tint with the theme's colours


def _away(on: str) -> str:
    """Black or white, whichever is further from text colour `on`."""
    return "#000000" if _contrast(on, "#000000") > _contrast(on, "#ffffff") else "#ffffff"


def _readable_fill(fill: str, on: str, need: float = 4.5) -> str:
    """`fill` moved away from its text colour `on`, just far enough for `on` to read on
    it (`need`); unchanged when it already does."""
    away = _away(on)
    return next((c for c in (_mix(fill, away, i / 40) for i in range(41))
                 if _contrast(on, c) >= need), away)


# The surfaces text in the live or accent colour sits on (a pill on a card, a link in a
# dialog, a hovered card): it must read on each of them, not just the window.
TEXT_ON = ("bg", "panel", "card", "card_hi")


def _readable_text(colour: str, t: dict[str, str], need: float, on=TEXT_ON) -> str:
    """`colour` moved towards the theme's text colour until it reads (`need`) on every
    surface in `on`; the text colour itself when nothing short of it does."""
    return next(c for c in (_mix(colour, t["text_hi"], i / 20) for i in range(21))
                if min(_contrast(c, t[b]) for b in on if b in t) >= need or c == t["text_hi"])


def _add_live_tokens(t: dict[str, str], colour: str = "") -> None:
    """The "it's on" highlight (voice changer on, live on air, Send, the mic pill when
    it's connected, a live tab's tint): the theme's own accent, not one green for every
    theme. `live` / `live_hover` / `live_top` fill a switched-on button (its plain, hovered
    and lit-top shades), each dark or light enough for its `on_live` words and icon to
    read (4.5:1); `live_hi` is its border. `live_text` is the same colour where it's
    drawn on a surface (text, icons, a tab's wash), moved towards the theme's text colour
    until it reads on each of them (Flashbang's yellow on white, Onion's purple on
    purple). A theme can set live / live_hi / on_live / live_text itself.
    `colour`: one the user picked instead (Settings → Appearance), whatever the theme."""
    if colour:
        t["live"], t["live_hi"] = colour, _mix(colour, "#ffffff", 0.18)
        t["on_live"] = max(("#ffffff", "#111111"), key=lambda c: _contrast(c, colour))
        t.pop("live_text", None)
        t.pop("live_border", None)
    t.setdefault("live", t["accent"])
    t.setdefault("live_hi", t["accent_hi"])
    t.setdefault("on_live", t["on_accent"])
    on = t["on_live"]
    t["live"] = _readable_fill(t["live"], on)
    t["live_hover"] = _readable_fill(t["live_hi"], on)
    # the lit top of its gradient: as much lighter as still reads
    t["live_top"] = next((c for c in (_mix(t["live"], "#ffffff", 0.16 * (8 - i) / 8)
                                      for i in range(9)) if _contrast(on, c) >= 4.5), t["live"])
    if "live_text" not in t:
        t["live_text"] = _readable_text(t["live"], t, 4.5)
    t.setdefault("live_border", _mix(t["live_text"], t["bg"], 0.45))


def _add_hover_token(t: dict[str, str]) -> None:
    """accent_hover: a filled accent button's hover colour, its accent_hi made just dark
    (or light) enough for its on_accent text to read (4.5:1). White on a lightened
    accent was 3.2-4.2:1 in ten themes, the default Dark among them. accent_hi itself
    stays as it is: it's also text and borders on the panels."""
    if "accent_hover" in t:
        return
    # light text: darker; dark text: lighter
    on = t["on_accent"]
    t["accent_hover"] = next(
        (c for c in (_mix(t["accent_hi"], _away(on), i / 20) for i in range(13))
         if _contrast(c, t["on_accent"]) >= 4.5), t["accent_hi"])
    t["accent_hover"] = _distinct_hover(t["accent"], t["accent_hover"], on,
                                         "#000000" if is_light_colour(t["bg"]) else "#ffffff")


def _add_item_hover_token(t: dict[str, str]) -> None:
    """item_hover: a hovered menu or dropdown row. btn_hover was 1.07-1.5:1 against the
    menu (Flashbang, Blood Moon, Lava: no visible change). The menu's colour moved
    towards the accent (or the text, when the accent itself is too faint) until the row
    stands out (1.6:1) while its words still read (4.5:1)."""
    if "item_hover" in t:
        return
    card = t["card"]
    tries = [_mix(card, to, i / 50) for to in (t["accent"], t["text"]) for i in range(6, 26)]
    t["item_hover"] = next((c for c in tries if _contrast(c, card) >= 1.6
                            and _contrast(c, t["text_hi"]) >= 4.5), _mix(card, t["text"], 0.25))


def _add_accent_text_token(t: dict[str, str]) -> None:
    """The accent where it's drawn straight on a surface, not as a fill, in two
    strengths. accent_text: icons and edges (3:1); Flashbang's yellow was 1.4:1 on white.
    accent_link: words (links, an effect's value, a checked menu row, a small action
    label), which need 4.5:1 on every surface they sit on (TEXT_ON and a hovered menu
    row). Both are the accent moved towards the text colour only as far as needed; most
    themes' accent keeps its exact colour for icons."""
    if "accent_text" not in t:
        t["accent_text"] = _readable_text(t["accent"], t, 3.0, ("bg", "panel", "card"))
    if "accent_link" not in t:
        t["accent_link"] = _readable_text(t["accent"], t, 4.5, TEXT_ON + ("item_hover",))


SECONDARY_ON = ("bg", "panel", "card", "card_hi", "btn", "btn_hover", "inset")


def is_light_colour(colour: str) -> bool:
    """Whether `colour` is a light one (the window background of a light theme)."""
    c = QColor(colour)
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 140


def _lift_buttons(t: dict[str, str]) -> None:
    """A light theme's buttons a shade darker until they stand out (1.12:1) from both the
    window and the panels: Light's were 1.06:1 on the window, so a pop-up's Done or Copy
    read as plain words. Hover and press move with them. Dark themes are left alone (a
    small step shows on dark colours), and so are outlined ones (High Contrast)."""
    if not is_light_colour(t["bg"]):
        return
    for i in range(16):
        c = _mix(t["btn"], t["text"], i / 40)
        if min(_contrast(c, t["bg"]), _contrast(c, t["panel"])) >= 1.12:
            break
    if i:
        for key in ("btn", "btn_hover", "btn_press"):
            t[key] = _mix(t[key], t["text"], i / 40)


def _distinct_hover(base: str, hover: str, on: str, direction: str) -> str:
    """Keep a visible hover step (1.3:1) without losing readable button text.

    Continue the theme's lightening or darkening direction first; when that would
    wash out the words, move the fill away from them instead. This is a visual
    feedback floor, not a WCAG contrast requirement between interaction states.
    """
    for to in (direction, "#ffffff" if direction == "#000000" else "#000000"):
        for i in range(101):
            colour = _mix(hover, to, i / 100)
            if _contrast(colour, base) >= 1.3 and _contrast(on, colour) >= 4.5:
                return colour
    return hover


def finish(t: dict[str, str]) -> dict[str, str]:
    """Work out a theme's derived colours (readable secondary text, hovers, the live
    and accent-text tokens) from the ones it sets. Every theme in THEMES has been;
    an app's own extra theme goes through it too. Returns `t`."""
    _lift_buttons(t)   # first: the secondary text below has to read on the lifted buttons
    t["btn_hover"] = _distinct_hover(t["btn"], t["btn_hover"], t["text"],
                                      "#000000" if is_light_colour(t["bg"]) else "#ffffff")
    t["section"] = _readable_text(t["section"], t, 4.5)
    # Secondary text must read (4.5:1) on every surface it sits on: a quiet button's
    # hover and the inset boxes too (they were 3.6-4.5:1 in most themes).
    for key in ("muted", "faint"):
        t[key] = next(c for c in (_mix(t[key], t["text_hi"], i / 20)
                                  for i in range(21))
                       if min(_contrast(c, t[bg]) for bg in SECONDARY_ON if bg in t) >= 4.5
                       or c == t["text_hi"])
    # boxes and buttons on a panel or card: the card's colour, or where cards are (near
    # enough) the panel's (Light: white on white, the buttons read as plain text; Paper
    # and Cherry Blossom a hair off it) the button colour, or its hover one when that's
    # the panel's too (Flashbang). Light colours need a bigger step to show; a dark theme
    # whose buttons are no better keeps its card colour (High Contrast: outlined anyway)
    light = is_light_colour(t["bg"])
    need = 1.10 if light else 1.08
    t.setdefault("card_ctl", next(
        (c for c in ((t["card"], t["btn"], t["btn_hover"], t["groove"]) if light
                     else (t["card"], t["btn"]))
         if _contrast(c, t["panel"]) >= need), t["groove"] if light else t["card"]))
    # boxes drawn in the window colour on a panel (Settings' boxes, number boxes, the
    # sounds search): the card one where the window is the panel's (Flashbang, Comic Sans)
    t.setdefault("field", t["bg"] if _contrast(t["bg"], t["panel"]) >= need
                  else t["card_ctl"])
    # language / theme tiles, the Radio list's segment strip, the map's zoom buttons
    # (their own colours only where they'd vanish: Flashbang)
    t.setdefault("tile", t["panel"])
    t.setdefault("segbox", t["inset"])
    t.setdefault("map_btn", t["card"])
    _add_live_tokens(t)
    _add_hover_token(t)
    _add_item_hover_token(t)
    _add_accent_text_token(t)
    return t


for _t in THEMES.values():
    finish(_t)

DEFAULT = "Dark"
# How the Settings window groups the theme cards. Every theme is in exactly one group.
GROUPS: list[tuple[str, list[str]]] = [
    ("Classic", ["Dark", "Light", "Midnight", "Carbon", "Slate", "Arctic", "Paper",
                 "High Contrast"]),
    ("Colourful", ["Ocean", "Toxic", "Vampire", "Forest", "Mocha", "Sunset", "Royal", "Onion",
                   "Lilac", "Mint", "Cherry Blossom"]),
    ("Wild", ["Synthwave", "Vaporwave", "Blood Moon", "Lava", "Amber Terminal", "Hacker"]),
    ("Meme", ["Flashbang", "Barbie", "Swamp", "Deep Fried", "Retro 98", "Comic Sans",
              "Brainrot"]),
]


FONT = "Bahnschrift"   # ships with Windows 10+; a theme can swap it with a `font` token


def font_families() -> list[str]:
    """Every font a theme uses."""
    return sorted({FONT, *(t["font"] for t in THEMES.values() if t.get("font"))})


def valid_colour(colour: str) -> str:
    """`colour` as "#rrggbb", or "" when it isn't one (a hand-edited or damaged setting)."""
    if not isinstance(colour, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", colour.strip()):
        return ""
    return colour.strip().lower()


# The widgets drawn in the live colour (by objectName): a colour change restyles just
# these (apply_live), not the whole app, which takes seconds on a full board.
LIVE_NAMES = ("power", "onair", "pill", "live")
LIVE_STYLE = Template("""
QPushButton#power:checked, QPushButton#onair:checked, QPushButton#live:checked {
    background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $live_top, stop:1 $live);
    border:1px solid $live_hi; color:$on_live; }
QPushButton#onair:checked { border-color:transparent; }
QPushButton#power:checked:hover, QPushButton#onair:checked:hover,
QPushButton#live:checked:hover { background:$live_hover; }
QPushButton#pill[state="ok"] { color:$live_text; background:transparent; }
""")


def live_sheet(tk: dict[str, str] | None = None) -> str:
    """The live rules in theme `tk`'s colours (default: the current one), as a widget's
    own stylesheet (it wins over the app's, so it also beats the cards' generic
    `:checked` rules)."""
    return LIVE_STYLE.substitute(hooks.palette() if tk is None else tk)
