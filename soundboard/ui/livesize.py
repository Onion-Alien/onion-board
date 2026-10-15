"""The window's edge being dragged (Windows' size/move loop), for work that can wait
until it's let go.

Windows sends WM_ENTERSIZEMOVE when the user starts dragging an edge (or the title
bar) and WM_EXITSIZEMOVE when they let go. In between, each mouse move is a resize
step that has to be laid out and painted before the next one comes: work skipped
there (measuring the whole window afresh, see FitControl) is done once on release."""
from __future__ import annotations

import sys
from ctypes import c_uint, wintypes

WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
_MSG_ID = wintypes.MSG.message.offset if sys.platform == "win32" else 0


def drag_edge(message) -> int:
    """From a window's nativeEvent: 1 as a size/move drag starts, -1 as it ends, else 0.
    Every Windows message passes here: one read of the message's id."""
    if sys.platform != "win32":
        return 0
    kind = c_uint.from_address(int(message) + _MSG_ID).value
    if kind == WM_ENTERSIZEMOVE:
        return 1
    if kind == WM_EXITSIZEMOVE:
        return -1
    return 0
