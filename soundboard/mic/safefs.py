"""Folder work for the mic effect's admin step and the mic helper (admin / SYSTEM) in
folders other accounts can write to (MicPlugin, the helper's requests, anything someone
put in %ProgramData%\\OnionBoard before it was made safe).

A path is looked up again on every use, so a folder on it that someone turns into a link
(a junction to another folder, or to \\RPC Control and its symlinks) between two steps
sends the next one somewhere else. Here a folder is opened once, checked on that handle
to be a real folder, and everything in it is opened, read, renamed and deleted relative
to that handle, each entry without following it: a link is removed, never what it points
at, and nothing is ever looked up by its full path again."""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_REPARSE = 0x400      # FILE_ATTRIBUTE_REPARSE_POINT
_DIRECTORY = 0x10     # FILE_ATTRIBUTE_DIRECTORY

# access
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_LIST = 0x0001                 # FILE_LIST_DIRECTORY (FILE_READ_DATA on a file)
_READ_ATTRIBUTES = 0x0080
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
# NtCreateFile
_FILE_OPEN, _FILE_CREATE = 1, 2
_SYNC_IO = 0x20                # FILE_SYNCHRONOUS_IO_NONALERT
_NON_DIRECTORY = 0x40
_BACKUP_INTENT = 0x4000        # honoured only with SeBackup/SeRestore (the admin step)
_OPEN_LINK = 0x200000          # FILE_OPEN_REPARSE_POINT: the entry itself, never its target
_NOT_FOUND = (0xC0000034, 0xC000003A)   # OBJECT_NAME_NOT_FOUND, OBJECT_PATH_NOT_FOUND


class NotPlain(PermissionError):
    """The folder is a link (or not a folder): nothing is done through it."""


def guard():
    """Turn on Windows' redirection guard for this process where it has one (Windows 11):
    a junction a non-admin made is then never followed, whatever opens a path. Best
    effort, on top of the handle work below: older Windows just don't have it."""
    if os.name != "nt":
        return
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        flags = ctypes.c_ulong(1)   # EnforceRedirectionTrust
        # ProcessRedirectionTrustPolicy
        if not kernel.SetProcessMitigationPolicy(16, ctypes.byref(flags), 4):
            log.info("no redirection guard here (%d)", ctypes.get_last_error())
    except (AttributeError, OSError):
        log.info("no redirection guard here", exc_info=True)


# ---------------------------------------------------------------------- Windows

if os.name == "nt":
    from ctypes import wintypes

    class _UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", wintypes.LPWSTR)]

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(_UnicodeString)),
                    ("Attributes", wintypes.ULONG), ("SecurityDescriptor", ctypes.c_void_p),
                    ("SecurityQualityOfService", ctypes.c_void_p)]

    class _IoStatus(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_void_p)]

    class _Info(ctypes.Structure):   # BY_HANDLE_FILE_INFORMATION
        _fields_ = [("attributes", wintypes.DWORD), ("times", wintypes.DWORD * 6),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index", wintypes.DWORD * 2)]

    _ntdll = ctypes.WinDLL("ntdll")
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll.NtCreateFile.restype = ctypes.c_long
    _ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG, ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatus), ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
        wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
    _ntdll.NtSetInformationFile.restype = ctypes.c_long
    _ntdll.NtSetInformationFile.argtypes = [wintypes.HANDLE, ctypes.POINTER(_IoStatus),
                                            ctypes.c_void_p, wintypes.ULONG, ctypes.c_int]
    _ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
    _ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.HANDLE]
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Info)]
    _kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                     ctypes.c_void_p, wintypes.DWORD]
    _kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _kernel.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _INVALID = wintypes.HANDLE(-1).value

    def _status_error(status: int, name: str) -> OSError:
        code = _ntdll.RtlNtStatusToDosError(status)
        e = ctypes.WinError(code)
        e.filename = name
        return e

    def _open_at(root, name: str, access: int, share: int = 7,
                 disposition: int = _FILE_OPEN, options: int = 0):
        """`name` in the folder `root` (a handle), the entry itself (a link isn't
        followed). None if it isn't there."""
        text = ctypes.create_unicode_buffer(name)
        us = _UnicodeString(len(name) * 2, len(name) * 2 + 2,
                            ctypes.cast(text, wintypes.LPWSTR))
        oa = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), root,
                               ctypes.pointer(us), 0x40, None, None)   # OBJ_CASE_INSENSITIVE
        h, io = wintypes.HANDLE(), _IoStatus()
        status = _ntdll.NtCreateFile(
            ctypes.byref(h), access | _SYNCHRONIZE | _READ_ATTRIBUTES, ctypes.byref(oa),
            ctypes.byref(io), None, 0x80, share, disposition,
            options | _SYNC_IO | _OPEN_LINK | _BACKUP_INTENT, None, 0)
        if status & 0xFFFFFFFF in _NOT_FOUND:
            return None
        if status < 0:
            raise _status_error(status, name)
        return h.value

    def _info(h) -> _Info:
        info = _Info()
        if not _kernel.GetFileInformationByHandle(h, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return info

    def _set_info(h, buf, klass: int) -> int:
        io = _IoStatus()
        return _ntdll.NtSetInformationFile(h, ctypes.byref(io), buf, ctypes.sizeof(buf), klass)

    def _dispose(h) -> bool:
        """Delete the entry `h` is open on (with DELETE): its name goes at once."""
        # FileDispositionInformationEx: DELETE | POSIX_SEMANTICS | IGNORE_READONLY
        if _set_info(h, (ctypes.c_ulong * 1)(0x13), 64) >= 0:
            return True
        return _set_info(h, (ctypes.c_ubyte * 1)(1), 13) >= 0   # FileDispositionInformation

    def _names(h) -> list[tuple[str, int]]:
        """(name, attributes) of what's in the folder `h` (opened with FILE_LIST)."""
        out, klass = [], 15   # FileFullDirectoryRestartInfo, then FileFullDirectoryInfo
        buf = ctypes.create_string_buffer(64 << 10)
        while True:
            if not _kernel.GetFileInformationByHandleEx(h, klass, buf, len(buf)):
                err = ctypes.get_last_error()
                if err in (18, 2):   # ERROR_NO_MORE_FILES, ERROR_FILE_NOT_FOUND
                    return out
                raise ctypes.WinError(err)
            klass, at = 14, 0
            while True:
                nxt = int.from_bytes(buf.raw[at:at + 4], "little")
                attrs = int.from_bytes(buf.raw[at + 56:at + 60], "little")
                size = int.from_bytes(buf.raw[at + 60:at + 64], "little")
                name = buf.raw[at + 68:at + 68 + size].decode("utf-16-le")
                if name not in (".", ".."):
                    out.append((name, attrs))
                if not nxt:
                    break
                at += nxt

    def _delete_at(root, name: str, where: Path, left: list[Path]):
        h = _open_at(root, name, _DELETE | _LIST)
        if h is None:
            return
        try:
            attrs = _info(h).attributes
            if attrs & _DIRECTORY and not attrs & _REPARSE:
                for child, _a in _names(h):
                    try:
                        _delete_at(h, child, where / name, left)
                    except OSError:
                        left.append(where / name / child)
            if not _dispose(h):
                left.append(where / name)
        finally:
            _kernel.CloseHandle(h)

    def _open_dir(path: Path, access: int = _LIST):
        h = _kernel.CreateFileW(str(path), access | _READ_ATTRIBUTES | _SYNCHRONIZE, 7,
                                None, 3, 0x02200000, None)   # BACKUP_SEMANTICS | OPEN_REPARSE
        if h in (None, _INVALID):
            err = ctypes.get_last_error()
            if err in (2, 3):
                raise FileNotFoundError(2, "not there", str(path))
            raise ctypes.WinError(err)
        try:
            attrs = _info(h).attributes
        except OSError:
            _kernel.CloseHandle(h)
            raise
        if attrs & _REPARSE or not attrs & _DIRECTORY:
            _kernel.CloseHandle(h)
            raise NotPlain(f"{path} isn't a plain folder")
        return h


class Folder:
    """A real folder (never a link), opened once: everything in it goes through here.
    Raises NotPlain if `path` is a link or a file, FileNotFoundError if it isn't there."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if os.name == "nt":
            self._h = _open_dir(self.path)
        else:
            st = os.lstat(self.path)
            if not os.path.isdir(self.path) or os.path.islink(self.path):
                raise NotPlain(f"{path} isn't a plain folder")
            self._h = st

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if os.name == "nt" and self._h is not None:
            _kernel.CloseHandle(self._h)
        self._h = None

    def names(self) -> list[str]:
        if os.name == "nt":
            return [n for n, _a in _names(self._h)]
        return os.listdir(self.path)

    def delete(self, name: str) -> list[Path]:
        """Remove `name` in here: a file, a link (only the link) or a whole folder,
        each entry relative to its checked folder. What couldn't go (in use)."""
        left: list[Path] = []
        if os.name == "nt":
            try:
                _delete_at(self._h, name, self.path, left)
            except OSError:
                left.append(self.path / name)   # (in use)
            return left
        p = self.path / name
        try:
            if os.path.islink(p) or not os.path.isdir(p):
                os.unlink(p)
            else:
                shutil.rmtree(p)
        except FileNotFoundError:
            pass
        except OSError:
            left.append(p)
        return left

    def take(self, name: str, limit: int) -> bytes | None:
        """Read `name` and delete it. Its bytes only if it is a plain file of its own
        (no link, no second name, not a folder) of up to `limit` bytes, checked on the
        handle it's read from (nobody else may open it meanwhile); it goes either way,
        once checked (a link: only the link)."""
        if os.name != "nt":
            p = self.path / name
            try:
                st = os.lstat(p)
                ok = os.path.isfile(p) and not os.path.islink(p) and st.st_nlink == 1 \
                    and st.st_size <= limit
                return p.read_bytes() if ok else None
            finally:
                self.delete(name)
        h = _open_at(self._h, name, _GENERIC_READ | _DELETE, share=0)
        if h is None:
            return None
        gone = False
        try:
            info = _info(h)
            size = (info.size_high << 32) | info.size_low
            if info.attributes & (_REPARSE | _DIRECTORY) or info.links != 1 or size > limit:
                gone = not info.attributes & _DIRECTORY and _dispose(h)
                return None
            buf = ctypes.create_string_buffer(limit + 1)
            got = wintypes.DWORD()
            if not _kernel.ReadFile(h, buf, limit + 1, ctypes.byref(got), None):
                raise ctypes.WinError(ctypes.get_last_error())
            gone = _dispose(h)
            return buf.raw[:got.value]
        finally:
            _kernel.CloseHandle(h)
            if not gone:
                self.delete(name)   # a folder: the whole of it, through its own handles

    def write_new(self, name: str, data: bytes):
        """A new file `name` in here with `data` (fails if there's one of that name)."""
        if os.name != "nt":
            fd = os.open(self.path / name,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return
        h = _open_at(self._h, name, _GENERIC_WRITE, share=0, disposition=_FILE_CREATE,
                     options=_NON_DIRECTORY)
        if h is None:
            raise FileNotFoundError(2, "not there", name)
        try:
            done = wintypes.DWORD()
            if not _kernel.WriteFile(h, data, len(data), ctypes.byref(done), None) \
                    or done.value != len(data):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _kernel.CloseHandle(h)

    def replace(self, src: str, dst: str):
        """Rename `src` to `dst` in here, replacing the entry `dst` itself (never what a
        link of that name points at)."""
        if os.name != "nt":
            os.replace(self.path / src, self.path / dst)
            return
        h = _open_at(self._h, src, _DELETE, options=_NON_DIRECTORY)
        if h is None:
            raise FileNotFoundError(2, "not there", src)
        try:
            raw = dst.encode("utf-16-le")
            buf = ctypes.create_string_buffer(20 + len(raw) + 2)
            ctypes.c_void_p.from_buffer(buf, 8).value = self._h          # RootDirectory
            ctypes.c_ulong.from_buffer(buf, 16).value = len(raw)         # FileNameLength
            ctypes.memmove(ctypes.addressof(buf) + 20, raw, len(raw))
            ctypes.c_ulong.from_buffer(buf, 0).value = 0x3   # REPLACE_IF_EXISTS | POSIX
            status = _set_info(h, buf, 65)                   # FileRenameInformationEx
            if status < 0:
                ctypes.c_ulong.from_buffer(buf, 0).value = 1   # ReplaceIfExists
                status = _set_info(h, buf, 10)                 # FileRenameInformation
            if status < 0:
                raise _status_error(status, dst)
        finally:
            _kernel.CloseHandle(h)


def remove_tree(path: Path) -> list[Path]:
    """Remove `path`, a file, a link (only the link itself) or a folder with all that's
    in it, never following a link anywhere in it. Only `path`'s last part is looked up
    by name (the folders above it are the caller's, and must be safe). What couldn't go
    (in use), as paths found through checked folders."""
    path = Path(path)
    if os.name != "nt":
        with Folder(path.parent) as parent:
            return parent.delete(path.name)
    h = _kernel.CreateFileW(str(path), _DELETE | _LIST | _READ_ATTRIBUTES | _SYNCHRONIZE, 7,
                            None, 3, 0x02200000, None)   # BACKUP_SEMANTICS | OPEN_REPARSE
    if h in (None, _INVALID):
        err = ctypes.get_last_error()
        if err in (2, 3):
            return []
        if err == 32:   # in use
            return [path]
        raise ctypes.WinError(err)
    left: list[Path] = []
    try:
        attrs = _info(h).attributes
        if attrs & _DIRECTORY and not attrs & _REPARSE:
            for child, _a in _names(h):
                try:
                    _delete_at(h, child, path, left)
                except OSError:
                    left.append(path / child)
        if not _dispose(h):
            left.append(path)
    finally:
        _kernel.CloseHandle(h)
    return left
