"""The quick setup's mic test, its last result: "pass" (the level bar heard them) or
"fail", and when (UTC), under HKCU\\Software\\OnionBoard. Only the uninstaller reads it,
for its feedback form's address (installer/OnionBoard.iss, FormDetails), which the
user's browser opens on their Yes; nothing is sent unless they submit the form."""
from __future__ import annotations

import time

try:
    import winreg
except ImportError:   # not Windows: nothing reads it there
    winreg = None

KEY = r"Software\OnionBoard"


def save(heard: bool) -> None:
    if winreg is None:
        return
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            winreg.SetValueEx(k, "MicTest", 0, winreg.REG_SZ, "pass" if heard else "fail")
            winreg.SetValueEx(k, "MicTestAt", 0, winreg.REG_SZ,
                              time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    except OSError:
        pass
