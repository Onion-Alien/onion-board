"""The style kit: the themes' colours and textures, Bun's outfits and Hoot the owl,
shared by Onion Board and Onion Watch so both look the same in every theme.

This folder is the only real copy. Onion Watch carries an exact copy of it
(`onionwatch/style/`, made by its `scripts/sync_style.py`, which stamps the commit it
came from), and inside Onion Board's Triggers tab it draws with this one instead
(`BoardHost.kit()`), so an older add-on still matches the board.

Rules, so the copy keeps working in both apps:
- Import nothing from either app: only the standard library, PySide6 and this folder
  (relative imports). What the kit needs from the app (the current theme, translation,
  whether the app is in front) comes through `hooks`, which the app's theme module
  connects.
- Text the user sees goes through `hooks.tr` as `_("...")`, so both apps' extractors
  find it, and is translated when it's shown, not at import.
- Bump KIT_VERSION with any change a host or the add-on must know about (a new hook,
  a new module, a renamed name).

    palettes   THEMES, GROUPS, finish(), the colour maths, LIVE_STYLE / live_sheet()
    textures   Textured: TEXTURES, texture_image(), texture_style(), paint_glow()
    bunnyfit   Bun's outfit per theme and the pieces' drawing
    owl        Hoot: draw_owl(), owl_image(), OwlWidget
    appstate   active(), pause_in_background(), snap_to_pixels()
    cover      Cover, covered(): a theme switch fades in and out instead of flashing
    hooks      what the app plugs in
"""

KIT_VERSION = 3   # 2: texture_style / paint_glow / live_sheet in the kit; 3: cover
