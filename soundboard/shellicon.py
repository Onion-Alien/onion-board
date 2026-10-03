"""The app's icon outside its own windows, in the theme's colours.

Qt's window icon only reaches the title bar and the running taskbar button. The
rest of Windows reads an icon *file*:

- the taskbar's right-click (Jump List) entry for the app and a pin made from the
  running window use the window's relaunch properties
  (System.AppUserModel.RelaunchIconResource, set with SHGetPropertyStoreForWindow);
- Start menu search, the Start menu and the Desktop show the "Onion Board"
  shortcut's icon.

So the theme's logo is written to `%APPDATA%\\OnionBoard\\icons\\onionboard-<hash>.ico`
(the name changes with the picture, so Explorer's icon cache never shows an old
one), the main window's relaunch properties point at it, and the app's own
"Onion Board.lnk" shortcuts (Desktop, Start menu, a taskbar pin; only those whose
target is this copy of the app) get it as their icon. Nothing else is touched, and
every step only logs when Windows says no. A reinstall puts the shortcuts back to
the .exe's icon; the next start re-themes them.
"""
from __future__ import annotations

import hashlib
import logging
import os
import struct
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

AUMID = "OnionBoard.App"   # same as app.py's SetCurrentProcessExplicitAppUserModelID
NAME = "Onion Board"
LINK_NAME = NAME + ".lnk"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)   # 100-250 % scaling, plus the big views

# what the theme last asked for, and the window it was put on
_state: dict = {"icon": None, "hwnd": None, "shortcuts_for": None}
_links_lock = threading.Lock()


# --------------------------------------------------------------------------- .ico

def ico_bytes(c1: str, c2: str, sizes=ICO_SIZES) -> bytes:
    """A multi-size .ico of the logo in these colours. Each entry is a PNG, which
    Windows reads at every size since Vista."""
    from PySide6.QtCore import QBuffer, QIODevice

    from soundboard import theme
    pngs = []
    for sz in sizes:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        theme.logo_pixmap(sz, c1, c2).toImage().save(buf, "PNG")
        pngs.append(bytes(buf.data()))
        buf.close()
    head = struct.pack("<HHH", 0, 1, len(pngs))   # reserved, type 1 = icon, count
    offset = len(head) + 16 * len(pngs)
    entries = b""
    for sz, png in zip(sizes, pngs):
        # width / height 0 means 256; no palette; 1 plane; 32 bits per pixel
        entries += struct.pack("<BBBBHHII", sz % 256, sz % 256, 0, 0, 1, 32,
                               len(png), offset)
        offset += len(png)
    return head + entries + b"".join(pngs)


def icon_dir() -> Path:
    from soundboard import library
    return library.APP_DIR / "icons"


def write_icon(c1: str, c2: str, folder: Path | None = None) -> Path:
    """The theme's .ico on disk (written once per look; an existing one is kept)."""
    data = ico_bytes(c1, c2)
    folder = folder or icon_dir()
    path = folder / f"onionboard-{hashlib.sha1(data).hexdigest()[:10]}.ico"
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    return path


# --------------------------------------------------------------------------- COM

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):   # only VT_EMPTY and VT_LPWSTR are used
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                    ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                    ("ptr", ctypes.c_void_p), ("ptr2", ctypes.c_void_p)]

    def _guid(text: str) -> GUID:
        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    def _call(obj, index: int, argtypes, *args, restype=ctypes.HRESULT):
        """Method `index` of a COM interface pointer (HRESULT failures raise OSError)."""
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
        return fn(obj, *args)

    def _release(obj):
        if obj:
            _call(obj, 2, (), restype=ctypes.c_ulong)

    _shell32 = ctypes.windll.shell32
    _ole32 = ctypes.windll.ole32
    _shell32.SHGetPropertyStoreForWindow.restype = ctypes.HRESULT
    _shell32.SHGetPropertyStoreForWindow.argtypes = (wintypes.HWND, ctypes.c_void_p,
                                                     ctypes.c_void_p)
    _shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT
    _shell32.SHGetKnownFolderPath.argtypes = (ctypes.c_void_p, wintypes.DWORD,
                                              wintypes.HANDLE, ctypes.c_void_p)
    _shell32.SHChangeNotify.restype = None
    _shell32.SHChangeNotify.argtypes = (wintypes.LONG, wintypes.UINT, ctypes.c_void_p,
                                        ctypes.c_void_p)
    _ole32.CoCreateInstance.restype = ctypes.HRESULT
    _ole32.CoCreateInstance.argtypes = (ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.c_void_p, ctypes.c_void_p)
    _ole32.CoInitializeEx.restype = ctypes.c_long   # S_FALSE / RPC_E_CHANGED_MODE are fine
    _ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    _ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)

    IID_IPropertyStore = _guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    CLSID_ShellLink = _guid("{00021401-0000-0000-C000-000000000046}")
    IID_IShellLinkW = _guid("{000214F9-0000-0000-C000-000000000046}")
    IID_IPersistFile = _guid("{0000010B-0000-0000-C000-000000000046}")
    FMTID_AppUserModel = _guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
    FOLDERS = {   # known folders that can hold the app's shortcuts
        "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
        "programs": "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}",
        "public desktop": "{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}",
        "common programs": "{0139D44E-6AFE-49F2-8690-3DAFCAE6FFB8}",
    }
    PID_ID, PID_COMMAND, PID_ICON, PID_DISPLAY_NAME = 5, 2, 3, 4
    VT_EMPTY, VT_LPWSTR = 0, 31
    STGM_READ = 0
    SHCNE_UPDATEITEM, SHCNE_ASSOCCHANGED = 0x00002000, 0x08000000
    SHCNF_IDLIST, SHCNF_PATHW = 0x0000, 0x0005

    def _known_folder(guid_text: str) -> Path | None:
        out = ctypes.c_wchar_p()
        try:
            _shell32.SHGetKnownFolderPath(ctypes.byref(_guid(guid_text)), 0, None,
                                          ctypes.byref(out))
        except OSError:
            return None
        try:
            return Path(out.value) if out.value else None
        finally:
            _ole32.CoTaskMemFree(out)

    def _set_props(hwnd: int, values) -> None:
        """Put (pid, text|None) on the window's property store; None removes it."""
        store = ctypes.c_void_p()
        _shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(IID_IPropertyStore),
                                             ctypes.byref(store))
        try:
            for pid, text in values:
                key = PROPERTYKEY(FMTID_AppUserModel, pid)
                pv = PROPVARIANT()
                buf = None
                if text is not None:
                    buf = ctypes.create_unicode_buffer(text)
                    pv.vt, pv.ptr = VT_LPWSTR, ctypes.cast(buf, ctypes.c_void_p).value
                _call(store, 6, (ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)),
                      ctypes.byref(key), ctypes.byref(pv))   # IPropertyStore::SetValue
                del buf   # SetValue keeps its own copy
        finally:
            _release(store)

    class ShellLink:
        """One .lnk through IShellLinkW / IPersistFile."""

        def __init__(self, path: Path):
            self.path = path
            self.link = ctypes.c_void_p()
            self.file = ctypes.c_void_p()
            _ole32.CoCreateInstance(ctypes.byref(CLSID_ShellLink), None, 1,   # inproc
                                    ctypes.byref(IID_IShellLinkW), ctypes.byref(self.link))
            try:
                _call(self.link, 0, (ctypes.c_void_p, ctypes.c_void_p),   # QueryInterface
                      ctypes.byref(IID_IPersistFile), ctypes.byref(self.file))
                _call(self.file, 5, (wintypes.LPCWSTR, wintypes.DWORD),   # Load
                      str(path), STGM_READ)
            except OSError:
                self.close()
                raise

        def _text(self, index: int, extra=()) -> str:
            buf = ctypes.create_unicode_buffer(1024)
            _call(self.link, index, (wintypes.LPWSTR, ctypes.c_int) + tuple(t for t, _ in extra),
                  buf, len(buf), *(v for _, v in extra))
            return buf.value

        def target(self) -> str:
            return self._text(3, ((ctypes.c_void_p, None), (wintypes.DWORD, 0)))   # GetPath

        def arguments(self) -> str:
            return self._text(10)   # GetArguments

        def icon(self) -> tuple[str, int]:
            idx = ctypes.c_int()
            path = self._text(16, ((ctypes.POINTER(ctypes.c_int), ctypes.byref(idx)),))
            return path, idx.value   # GetIconLocation

        def set_icon(self, path: str, index: int) -> None:
            _call(self.link, 17, (wintypes.LPCWSTR, ctypes.c_int), path, index)
            _call(self.file, 6, (wintypes.LPCWSTR, wintypes.BOOL), None, True)   # Save

        def close(self) -> None:
            _release(self.file)
            _release(self.link)
            self.file = self.link = ctypes.c_void_p()


# --------------------------------------------------------------------------- window

def relaunch_command() -> str:
    from soundboard import autostart
    return autostart.command(hidden=False)


def set_window(hwnd: int, icon: Path) -> bool:
    """Point the window's Jump List entry and taskbar pin at `icon`. The command and
    display name have to come with it (Windows ignores a lone icon), and the window
    needs its own explicit AppUserModelID for any of them to count."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        _set_props(hwnd, ((PID_COMMAND, relaunch_command()),
                          (PID_DISPLAY_NAME, NAME),
                          (PID_ICON, f"{icon},0"),
                          (PID_ID, AUMID)))
        return True
    except OSError:
        log.debug("couldn't set the window's relaunch icon", exc_info=True)
        return False


def clear_window(hwnd: int) -> None:
    """Windows wants these off the window before it's destroyed."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        _set_props(hwnd, ((PID_ID, None), (PID_ICON, None), (PID_DISPLAY_NAME, None),
                          (PID_COMMAND, None)))
    except OSError:
        log.debug("couldn't clear the window's relaunch properties", exc_info=True)


# --------------------------------------------------------------------------- shortcuts

def _norm(p: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(os.path.expandvars(str(p))))


def _first_arg(args: str) -> str:
    args = args.strip()
    if args.startswith('"'):
        return args[1:].split('"', 1)[0]
    return args.split(" ", 1)[0]


def is_ours(target: str, args: str, *, frozen: bool | None = None,
            exe: str | None = None, main: str | None = None) -> bool:
    """Does a shortcut start this copy of the app: the installed .exe, or (from
    source) python / pythonw with this checkout's main.py?"""
    if not target:
        return False
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return _norm(target) == _norm(exe or sys.executable)
    if Path(target).name.lower() not in ("python.exe", "pythonw.exe"):
        return False
    main = main or str(Path(__file__).resolve().parent.parent / "main.py")
    first = _first_arg(args)
    return bool(first) and _norm(first) == _norm(main)


def shortcut_folders() -> list[Path]:
    """Where the installer, scripts/install.ps1 and a taskbar pin put "Onion Board.lnk"."""
    if sys.platform != "win32":
        return []
    out = [p for p in (_known_folder(g) for g in FOLDERS.values()) if p]
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch"
                   / "User Pinned" / "TaskBar")
    return out


def _notify(paths: list[Path]) -> None:
    if sys.platform != "win32" or not paths:
        return
    try:
        for p in paths:
            _shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW,
                                    ctypes.c_wchar_p(str(p)), None)
        _shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)  # icon caches
    except OSError:
        log.debug("SHChangeNotify failed", exc_info=True)


def update_shortcuts(icon: Path, folders: list[Path] | None = None,
                     open_link=None, notify=None) -> list[Path]:
    """Give this app's own "Onion Board.lnk" shortcuts `icon`; returns the ones
    changed. Any other shortcut, one already right, or one Windows won't let us
    save (the all-users ones without admin) is left as it is."""
    if open_link is None:
        if sys.platform != "win32":
            return []
        open_link = ShellLink
    want = _norm(icon)
    changed = []
    for folder in (shortcut_folders() if folders is None else folders):
        path = Path(folder) / LINK_NAME
        if not path.is_file():
            continue
        try:
            link = open_link(path)
        except OSError:
            log.debug("couldn't read %s", path, exc_info=True)
            continue
        try:
            if not is_ours(link.target(), link.arguments()):
                continue
            cur, idx = link.icon()
            if cur and idx == 0 and _norm(cur) == want:
                continue
            link.set_icon(str(icon), 0)
            changed.append(path)
        except OSError:
            log.debug("couldn't re-icon %s", path, exc_info=True)
        finally:
            link.close()
    if changed:
        log.info("shortcut icons now follow the theme: %d updated", len(changed))
        (notify or _notify)(changed)
    return changed


def _shortcuts_worker():
    with _links_lock:   # theme flips while one runs: the next one picks up the latest
        icon = _state["icon"]
        if icon is None or icon == _state["shortcuts_for"]:
            return
        com = _ole32.CoInitializeEx(None, 0x2)   # apartment-threaded, for the shell
        try:
            update_shortcuts(icon)
            _state["shortcuts_for"] = icon
        except Exception:  # noqa: BLE001 - only cosmetic: never take the app down
            log.debug("updating shortcut icons failed", exc_info=True)
        finally:
            if com >= 0:
                _ole32.CoUninitialize()


# --------------------------------------------------------------------------- glue

def _native() -> bool:
    """Only on a real Windows desktop (not Qt's offscreen platform the tests use)."""
    if sys.platform != "win32":
        return False
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.platformName() == "windows"


def follow_theme(window, c1: str, c2: str) -> None:
    """The theme's colours changed (or the app started): write its icon, put it on
    the window if that exists yet, and re-icon the shortcuts in the background."""
    if not _native():
        return
    try:
        icon = write_icon(c1, c2)
    except Exception:  # noqa: BLE001 - only cosmetic
        log.debug("couldn't write the theme's icon", exc_info=True)
        return
    if icon == _state["icon"]:
        return
    _state["icon"] = icon
    if window is not None and window.windowHandle() is not None:
        attach(window)
    threading.Thread(target=_shortcuts_worker, name="shortcut-icons", daemon=True).start()


def attach(window) -> None:
    """Put the current theme icon on the window's relaunch properties."""
    if _state["icon"] is None or not _native():
        return
    hwnd = int(window.winId())
    if set_window(hwnd, _state["icon"]):
        _state["hwnd"] = hwnd


def on_show(window) -> None:
    """showEvent: the window's handle exists but it isn't on screen yet, so the
    relaunch icon is on before its taskbar button appears. Once per handle."""
    if _native() and _state["hwnd"] != int(window.winId()):
        attach(window)


def detach() -> None:
    hwnd, _state["hwnd"] = _state["hwnd"], None
    clear_window(hwnd)


def paint_background(window, color: str) -> None:
    """While the window is dragged bigger fast, Windows fills the new strip with the
    window class's background brush (white) before Qt gets to paint it: make that
    brush the theme's background so a fast resize shows the theme, not a white edge.
    The brush is per window class, so Qt's dialogs get it too."""
    if not _native() or window.windowHandle() is None:
        return
    import ctypes
    from ctypes import wintypes
    from PySide6.QtGui import QColor
    c = QColor(color)
    gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
    gdi.CreateSolidBrush.restype = wintypes.HANDLE
    gdi.CreateSolidBrush.argtypes = [wintypes.DWORD]
    brush = gdi.CreateSolidBrush(c.red() | c.green() << 8 | c.blue() << 16)
    if not brush:
        return
    user.SetClassLongPtrW.restype = ctypes.c_void_p
    user.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    old = user.SetClassLongPtrW(int(window.winId()), -10, brush)   # GCLP_HBRBACKGROUND
    if old and old == _state.get("brush"):
        gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi.DeleteObject(old)   # our previous theme's brush; never the system's own
    _state["brush"] = brush
