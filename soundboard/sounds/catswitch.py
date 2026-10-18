"""Switch category when a program is in front: the user ties programs (by their
.exe name, `Config.category_programs`) to a category, and the board shows that
category whenever one of them comes to the front; when it closes, the board goes back
to the category it was on before. Nothing is built in: every rule is the user's.

`Switcher.poll()` runs on the main window's timer (about once a second, only while a
rule exists): one foreground-window lookup and, while a program it switched for is
running, one "is it still running?" check. Nothing is scanned."""
from __future__ import annotations

import os
from dataclasses import dataclass

from soundboard.mic import voicesdk

POLL_MS = 1000


def exe_name(path: str) -> str:
    """'game.exe' from a full path: what rules match on, so they survive a reinstall
    to another folder and go into backups."""
    return os.path.basename(path or "").strip().lower()


def programs_for(rules: dict[str, str], category: str) -> list[str]:
    return sorted(exe for exe, cat in rules.items() if cat == category)


@dataclass
class Switch:
    """What poll() wants shown: `category`, because `exe` came to the front (`back`
    False) or closed (`back` True)."""
    category: str
    exe: str
    back: bool = False


class Switcher:
    """Follows the program in front. `foreground()` -> (pid, exe path), as
    voicesdk.foreground_process (this app's own windows are (0, '')); `alive(pid)` as
    appaudio.is_running."""

    def __init__(self, foreground=None, alive=None):
        self._fg = foreground or (lambda: voicesdk.foreground_process())
        if alive is None:
            from soundboard.appaudio import is_running
            alive = is_running
        self._alive = alive
        self.front_pid = 0          # the last real program in front (not us, not Windows')
        self.pid = 0                # the program a switch was made for, while it runs
        self.exe = ""
        self.shown = ""             # the category that switch showed
        self.before: str | None = None   # what was showing before the first switch

    def reset(self):
        """Rules changed or the feature went off: forget the program followed (the
        category showing stays as it is)."""
        self.pid, self.exe, self.shown, self.before = 0, "", "", None

    def poll(self, rules: dict[str, str], current: str, categories) -> Switch | None:
        cats = set(categories)
        pid, path = self._fg()
        if pid and path and not voicesdk._is_system(path) and pid != self.front_pid:
            # a program came to the front. Alt-tabbing out to another one changes
            # nothing; back in front (or a new one with a rule) shows its category
            self.front_pid = pid
            exe = exe_name(path)
            cat = rules.get(exe)
            if cat is not None and cat in cats:
                if self.before is None:
                    self.before = current
                self.pid, self.exe, self.shown = pid, exe, cat
                if current != cat:
                    return Switch(cat, exe)
                return None
        if self.pid and not self._alive(self.pid):
            # it closed: back to what was showing, unless the user has picked another
            # category by hand meanwhile (theirs to keep)
            exe, shown, before = self.exe, self.shown, self.before
            self.reset()
            if current == shown and before is not None and before != current and \
                    (before == "" or before in cats):
                return Switch(before, exe, back=True)
        return None

