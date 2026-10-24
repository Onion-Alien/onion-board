"""The tab rail's sizes (ui/window/sidebar.py), shared by its parts: the tab buttons
(railtabs.py), the On Air card (onaircard.py) and the update card (updatecard.py)."""
from __future__ import annotations

ICON = 20          # a tab's icon on the rail
SHUT_W = 43        # the rail's width, shut: its 1 px edge, 4, a 34 px button, 4...
OPEN_W = 190       # room for the brand and expanded listening status
FULL_W = (SHUT_W + OPEN_W) // 2   # dragged at least halfway, open (let go there, it
                   # snaps open): the mid layout until everything fits (_full_fit), then
                   # the full one. Short of halfway, the shut one, its icon column centred
SNAP_W = SHUT_W + round(0.6 * (OPEN_W - SHUT_W))   # dragged this wide, it's open all
                   # the way: no squeezed in-between layout
LOGO = 24          # the onion: with its 5 px glow room, a tab button's width (BUTTON_W)
BUTTON_W = 34      # a button on the shut rail; open, its icon stays in this column
COMPACT_H = 28     # only genuinely short windows use smaller targets
SIDE_SHUT = 4      # the rail's own side margins, shut (a 34 px button)...
SIDE_OPEN = 10     # ...and open
LIVE_BAR_W = 3     # a live tab's bar on the rail's outer edge (Settings > Live tabs: tint)
ICON_PAD = " "   # Qt puts only ~4 px between a button's icon and its words, and with a
                      # style sheet on, no style or QSS rule can change that: an en space
                      # (~6 px) in front of the words does
TEXT_W = OPEN_W - 2 * SIDE_OPEN - ICON - 24   # a name's room on the open rail (icon,
                                              # padding, border, the gap after the icon)
