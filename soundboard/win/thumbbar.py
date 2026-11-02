"""Buttons in the taskbar's hover preview of the main window, like Discord's
mute / deafen: play the last sound again, pause, stop all, a random sound, and
Live / Muted.

Windows draws them (ITaskbarList3::ThumbBarAddButtons) under the window's
thumbnail. They can be added only after the taskbar button exists (the
"TaskbarButtonCreated" message, which comes again when Explorer restarts), at most
once per button, and are changed afterwards with ThumbBarUpdateButtons. A click
arrives as WM_COMMAND with THBN_CLICKED in the high word and the button's id in
the low one. Icons are the app's own, 16 px at the window's scale, in a colour that
reads on the flyout (which follows Windows' light / dark setting, not the app's
theme). Every step only logs when Windows says no.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, Structure, byref, c_uint, c_void_p, c_wchar, sizeof, wintypes

log = logging.getLogger(__name__)

WM_COMMAND = 0x0111
WM_SETTINGCHANGE, WM_DPICHANGED = 0x001A, 0x02E0   # light / dark mode, scale
THBN_CLICKED = 0x1800
THB_ICON, THB_TOOLTIP, THB_FLAGS = 0x2, 0x4, 0x8
THBF_ENABLED = 0x0
MSGFLT_ALLOW = 1

# button id -> (icon, colour key); ids are what WM_COMMAND brings back
LAST, PAUSE, STOP, RANDOM, LIVE = range(1, 6)
ORDER = (LAST, PAUSE, STOP, RANDOM, LIVE)
ICONS = {LAST: "reload", PAUSE: "pause", STOP: "stop", RANDOM: "shuffle", LIVE: "live"}

# on the flyout: (light Windows, dark Windows)
COLOURS = {"plain": ("#1f1f1f", "#e8e8e8"), "stop": ("#c42b1c", "#ff6b6b"),
           "live": ("#0f7b3f", "#5fd38a"), "muted": ("#c42b1c", "#ff6b6b")}

CLSID_TaskbarList = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
IID_ITaskbarList3 = "{ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf}"
SLOT_HRINIT, SLOT_ADD, SLOT_UPDATE = 3, 15, 16
# Windows sends WM_SETTINGCHANGE to every window for any setting (several in a row is
# common) while Explorer handles the same broadcast: the buttons are looked at this
# long after the last one, and only pushed when they'd look different. Pushing on each
# one, inside the message, held the window for seconds to minutes on a busy PC (freeze
# reports in ThumbBarUpdate and the icons drawn for it).
SETTLE_MS = 500


_MSG_ID = wintypes.MSG.message.offset


class THUMBBUTTON(Structure):
    _fields_ = [("dwMask", wintypes.DWORD), ("iId", c_uint), ("iBitmap", c_uint),
                ("hIcon", wintypes.HICON), ("szTip", c_wchar * 260),
                ("dwFlags", wintypes.DWORD)]


def tips() -> dict:
    """Tooltips, translated when they're asked for (the language can change)."""
    from soundboard.i18n import _
    return {LAST: _("Play the last sound again"), PAUSE: _("Pause"),
            # the hover flyout is small: the rail's Stop all tooltip has the long form
            STOP: _("Stop everything"),
            RANDOM: _("Play a random sound")}


def live_tip(on: bool) -> str:
    from soundboard.i18n import _
    return (_("Others hear you: click to mute") if on
            else _("Muted: click so others hear you"))


def light_windows() -> bool:
    """Whether Windows' own UI (the taskbar and its flyouts) is light."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows"
                            r"\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except OSError:
        return False


def _native() -> bool:
    if sys.platform != "win32":
        return False
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.platformName() == "windows"


class ThumbBar:
    """The buttons on one window. `actions` maps a button id to what it does."""

    def __init__(self, window, actions: dict):
        self.window = window
        self.actions = actions
        self.live = True
        self.paused = False    # everything playing is paused: the Pause button says Play
        self._tb = None        # the ITaskbarList3, once the taskbar button exists
        self._hwnd = 0
        self._added = False
        self._icons: list[int] = []
        self._shown: tuple | None = None   # the look last pushed (_look)
        self._settling = False             # a settings change waits for SETTLE_MS
        self._created = 0
        if _native():
            user = ctypes.windll.user32
            user.RegisterWindowMessageW.restype = c_uint
            self._created = user.RegisterWindowMessageW("TaskbarButtonCreated")
        self._wanted = {self._created, WM_COMMAND, WM_SETTINGCHANGE, WM_DPICHANGED}

    # ----------------------------------------------------------------- messages
    def native_event(self, message) -> bool:
        """From the window's nativeEvent: True when it was one of our clicks."""
        if not self._created:
            return False
        addr = int(message)
        kind = c_uint.from_address(addr + _MSG_ID).value   # only the id, until it's ours
        if kind not in self._wanted:
            return False
        msg = wintypes.MSG.from_address(addr)
        if kind == self._created:
            self._added = False   # a new taskbar button (Explorer restarted, too)
            self._setup(int(msg.hWnd or 0))
        elif kind == WM_COMMAND:
            if (msg.wParam >> 16) & 0xFFFF == THBN_CLICKED:
                self.click(msg.wParam & 0xFFFF)
                return True
        else:
            self._settle()
        return False

    def _settle(self):
        """A setting or the scale changed: refresh() once things settle (SETTLE_MS)."""
        if self._settling:
            return
        from PySide6.QtCore import QObject, QTimer
        self._settling = True
        if isinstance(self.window, QObject):   # (gone with the window)
            QTimer.singleShot(SETTLE_MS, self.window, self._settled)
        else:
            QTimer.singleShot(SETTLE_MS, self._settled)

    def _settled(self):
        self._settling = False
        self.refresh()

    def click(self, bid: int):
        act = self.actions.get(bid)
        if act is not None:
            act()

    # ----------------------------------------------------------------- Windows side
    def _setup(self, hwnd: int):
        try:
            # an app run as admin still gets the messages from the (non-admin) taskbar
            user = ctypes.windll.user32
            for m in (self._created, WM_COMMAND):
                user.ChangeWindowMessageFilterEx(wintypes.HWND(hwnd), m, MSGFLT_ALLOW, None)
            if self._tb is None:
                self._tb = _taskbar_list()
            self._hwnd = hwnd
            self._push(SLOT_ADD)
            self._added = True
        except Exception:  # noqa: BLE001 - only the buttons are missing
            log.warning("taskbar buttons not added", exc_info=True)

    def set_live(self, on: bool):
        """The Live / Muted button follows the app's master switch."""
        if on == self.live:
            return
        self.live = on
        self.refresh()

    def set_paused(self, on: bool):
        """Pause while a sound plays, Play (resume) while everything is paused."""
        if on == self.paused:
            return
        self.paused = on
        self.refresh()

    def refresh(self):
        """Repaint the buttons (the state changed, Windows' light / dark mode), when
        they'd look different from what Windows has."""
        if not self._added:
            return
        try:
            if self._look() != self._shown:
                self._push(SLOT_UPDATE)
        except Exception:  # noqa: BLE001
            log.warning("taskbar buttons not updated", exc_info=True)

    def _push(self, slot: int):
        from soundboard.audio.appaudio import Com
        look = self._look()
        btns, old = self.buttons(look), self._icons
        self._icons = [b.hIcon for b in btns]
        arr = (THUMBBUTTON * len(btns))(*btns)
        Com(self._tb).call(slot, (wintypes.HWND, c_uint, POINTER(THUMBBUTTON)),
                           wintypes.HWND(self._hwnd), len(btns), arr,
                           what="ThumbBarAddButtons" if slot == SLOT_ADD else "ThumbBarUpdate")
        for h in old:   # Windows keeps its own copy of each icon
            ctypes.windll.user32.DestroyIcon(wintypes.HICON(h))
        self._shown = look

    def _look(self) -> tuple:
        """Everything the buttons show: (light Windows, icon size, tips, live, paused)."""
        text = {**tips(), LIVE: live_tip(self.live)}
        if self.paused:
            from soundboard.i18n import _
            text[PAUSE] = _("Resume")
        size = max(16, round(16 * self.window.devicePixelRatioF()))
        return light_windows(), size, tuple(text.items()), self.live, self.paused

    def buttons(self, look: tuple | None = None) -> list[THUMBBUTTON]:
        from soundboard.ui.kit import icons
        light, size, items, _live, _paused = look or self._look()
        text = dict(items)
        out = []
        for bid in ORDER:
            kind = ("live" if self.live else "muted") if bid == LIVE else (
                "stop" if bid == STOP else "plain")
            colour = COLOURS[kind][0 if light else 1]
            name = "play" if bid == PAUSE and self.paused else ICONS[bid]
            img = icons.pixmap(name, size, colour).toImage()
            b = THUMBBUTTON()
            b.dwMask = THB_ICON | THB_TOOLTIP | THB_FLAGS
            b.iId = bid
            b.hIcon = int(img.toHICON())
            b.szTip = text[bid][:259]
            b.dwFlags = THBF_ENABLED
            out.append(b)
        return out

    def close(self):
        for h in self._icons:
            ctypes.windll.user32.DestroyIcon(wintypes.HICON(h))
        self._icons = []
        if self._tb is not None:
            from soundboard.audio.appaudio import Com
            Com(self._tb).release()
            self._tb = None
        self._added = False


def _taskbar_list() -> int:
    """A new ITaskbarList3, initialised. Qt's UI thread is already in an STA."""
    from soundboard.audio.appaudio import GUID
    ole = ctypes.windll.ole32
    clsid, iid = GUID.of(CLSID_TaskbarList), GUID.of(IID_ITaskbarList3)
    out = c_void_p()
    hr = ole.CoCreateInstance(byref(clsid), None, 1, byref(iid), byref(out))   # INPROC_SERVER
    if hr < 0 or not out.value:
        raise OSError(f"CoCreateInstance(TaskbarList) failed: {hr & 0xFFFFFFFF:#x}")
    from soundboard.audio.appaudio import Com
    Com(out.value).call(SLOT_HRINIT, (), what="HrInit")
    return out.value


assert sizeof(THUMBBUTTON) in (540, 552)   # 32-bit / 64-bit layout
