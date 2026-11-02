"""Give memory back to Windows while the window sits in the tray or minimised.

Every page the app has touched stays in its working set, what Task Manager's Memory
column shows: ~350 MB with 100 sounds after an Edit dialog, an effects preview and
Settings, most of it not needed again until the window is back. Nothing is drawn out
of sight, so once the window has been in the tray or minimised a while (AFTER_S) and
nothing is playing, release() collects Python's garbage and empties the working set
(EmptyWorkingSet): ~350 -> ~35 MB. The pages stay the app's; Windows only takes them
out of RAM until they're used again, and showing the window or playing a sound reads
back what it needs, from RAM's standby list as a rule (microseconds).

Never while a sound, the radio or a program's sound (the Apps tab) plays: the audio
thread would take those page faults. The mic's voice changer runs all the time, so it doesn't count:
its few pages come back on the next block.

The garbage collection is skipped on a PC short of memory (uigc.COLD_MEMORY): it goes
through every object made since start-up, and after the wait in the tray Windows had
moved most of them out to the page file, so it read them all back from disk with
Python's lock held, and every thread stopped for 10 s to over 2 minutes (freeze
reports at the collection: `all-held`, `paging`, `mem-80`). The working set is still
emptied: that touches nothing.
"""
from __future__ import annotations

import ctypes
import gc
import logging
import sys

log = logging.getLogger(__name__)

AFTER_S = 30.0   # out of sight this long before memory is given back

_win = sys.platform == "win32"
if _win:
    from ctypes import wintypes
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _psapi.EmptyWorkingSet.argtypes = (wintypes.HANDLE,)
    _psapi.EmptyWorkingSet.restype = wintypes.BOOL


def release() -> bool:
    """Garbage collected, working set emptied (see the module).
    UI thread. False where there's nothing to do (not Windows) or it failed."""
    from soundboard.core import hangwatch, uigc
    load = hangwatch.memory_load()
    if load is None or load < uigc.COLD_MEMORY:
        gc.collect()
    if not _win:
        return False
    try:
        return bool(_psapi.EmptyWorkingSet(_k32.GetCurrentProcess()))
    except (OSError, AttributeError):   # an old or odd Windows: keep what we have
        log.debug("couldn't give memory back", exc_info=True)
        return False
