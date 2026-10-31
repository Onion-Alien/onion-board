"""Sets Discord up for sounds, and puts it back the way you talk once Onion Board is
closed.

To let sounds through, Discord's voice clean-up has to be off (discordcfg: noise
suppression, echo cancellation, automatic gain, automatic input sensitivity). `set_up`
switches it off (SOUND), after remembering how Discord was set while you only talked
(`snapshot`, saved in the config). Left that way after Onion Board closes, a plain
voice comes through noisy and up and down, so on quit those settings go back
(`restore`; Settings → Audio → Mic effect's Put Discord back does it by hand).

Discord keeps its settings in memory while it runs and writes over its files, so they
can only be changed while it's closed. On quit: Discord closed, they're put back at
once; Discord open, a small helper (`OnionBoard.exe --discord-restore`, no window)
says so in a notification and puts them back the moment Discord closes. It gives up
when Onion Board starts again or after HELPER_MAX_S.

How they're written: Discord's settings are a LevelDB database (Chromium's local
storage). A put is one more record appended to the database's log file, in LevelDB's
own format (32 kB blocks, CRC-32C per fragment, a write batch with a sequence number
above everything already stored), which LevelDB replays the next time Discord opens
it. Only while Discord's LOCK file can be locked (no Discord has it open), only if the
log reads cleanly to its end, after the voice settings it replaces are kept (BACKUPS
of them, the MediaEngineStore JSON alone), and checked by reading it back. Anything
off: nothing is written. Nothing else in Discord's files is kept, copied or logged:
the same folder holds its login.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import struct
import sys
import time
from pathlib import Path

from soundboard.mic import discordcfg
_varint = discordcfg._varint

log = logging.getLogger(__name__)

ARG = "--discord-restore"
NOW = "--now"        # the uninstaller: put back what it can and end (cli)
QUIET = "--quiet"    # the installer, starting it again: no notification
STILL_OPEN = 2       # NOW's exit code: a Discord is still open, not put back
KEY = b"_https://discord.com\x00\x01MediaEngineStore"   # Chromium: "_" origin \0 \1 name
BLOCK = 32768        # LevelDB log block
HEADER = 7           # crc32c (4), length (2), type (1)
FULL, FIRST, MIDDLE, LAST = 1, 2, 3, 4
BACKUPS = 3          # each client's voice settings kept from before a write
BACKUP_DAYS = 14     # ...and for this long at most
# what older versions kept there: a copy of Discord's files (its login among them), in
# a folder per write named by its time. Removed on sight (drop_old_copies).
OLD_COPY = re.compile(r"\d{8}-\d{6}")
HELPER_MAX_S = 12 * 3600
HELPER_POLL_S = 3.0
CLOSE_WAIT_S = 10.0   # set_up's Discord closing: how long it may take to go
VOICE_URL = "discord://-/settings/voice"   # opens Discord's Voice settings
EXES = dict(zip((c for c, _n in discordcfg.CLIENTS),
                ("discord.exe", "discordptb.exe", "discordcanary.exe",
                 "discorddevelopment.exe")))

# the voice settings that make up "how you talk", as paths into the store's "default"
TALK_KEYS = ("activeInputProfile", "noiseCancellation", "noiseSuppression",
             "echoCancellation", "automaticGainControl", "bypassSystemInputProcessing",
             "modeOptions.autoThreshold", "modeOptions.vadUseKrisp", "modeOptions.threshold")
# Discord's own defaults: put back when the board never saw you talking without it
DEFAULT_TALK = {"noiseCancellation": True, "echoCancellation": True,
                "automaticGainControl": True, "bypassSystemInputProcessing": False,
                "modeOptions.autoThreshold": True, "modeOptions.vadUseKrisp": True}
# what sounds need (discordcfg's measurements): the Custom profile with every clean-up
# off, and Voice Activity's sensitivity set by hand (Push to Talk is left as it is).
# Clean both straight into the mic and on the cable. The slider at THRESHOLD_DB: low
# enough that sounds open it, high enough that keyboard clicks and room noise don't.
THRESHOLD_DB = -65
SOUND = {"activeInputProfile": "CUSTOM", "noiseCancellation": False,
         "noiseSuppression": False, "echoCancellation": False,
         "automaticGainControl": False, "bypassSystemInputProcessing": False,
         "modeOptions.autoThreshold": False, "modeOptions.vadUseKrisp": False,
         "modeOptions.threshold": THRESHOLD_DB}


# ---------------------------------------------------------------- what "talking" is

def talking(s: discordcfg.Settings) -> bool:
    """Discord set for a plain voice: some of its clean-up on."""
    return (s.krisp or s.suppression or s.echo or s.agc
            or s.profile == "VOICE_ISOLATION")


def snapshot(store: dict) -> dict:
    """The TALK_KEYS the store has, flat ({"modeOptions.autoThreshold": True, ...})."""
    d = store.get("default") if isinstance(store, dict) else None
    out = {}
    if not isinstance(d, dict):
        return out
    for k in TALK_KEYS:
        head, _, tail = k.partition(".")
        v = d.get(head)
        if tail:
            v = v.get(tail) if isinstance(v, dict) else None
        if isinstance(v, (bool, str, int, float)):
            out[k] = v
    return out


def target(saved: dict | None, store: dict) -> dict:
    """What to put back: the saved talking settings, else Discord's defaults (and off
    Studio, where Discord ignores them all)."""
    if saved:
        return dict(saved)
    t: dict[str, bool | str] = dict(DEFAULT_TALK)
    if snapshot(store).get("activeInputProfile") == "STUDIO":
        t["activeInputProfile"] = "CUSTOM"
    return t


def apply(store: dict, talk: dict) -> dict:
    """A copy of the store with `talk` put in; everything else as it was."""
    out = copy.deepcopy(store)
    d = out.setdefault("default", {})
    for k, v in talk.items():
        if k not in TALK_KEYS:
            continue
        head, _, tail = k.partition(".")
        if tail:
            sub = d.get(head)
            if not isinstance(sub, dict):
                sub = d[head] = {}
            sub[tail] = v
        else:
            d[head] = v
    return out


def needs_restore(s: discordcfg.Settings, store: dict, talk: dict) -> bool:
    """Discord still set for sounds, and putting `talk` back would change something."""
    return not talking(s) and apply(store, talk) != store


# ---------------------------------------------------------------- LevelDB's log

def _crc_table() -> list[int]:
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
        t.append(c)
    return t


_CRC = _crc_table()


def crc32c(data: bytes, crc: int = 0) -> int:
    crc ^= 0xFFFFFFFF
    for b in data:
        crc = _CRC[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def _mask(crc: int) -> int:
    return (((crc >> 15) | (crc << 17)) + 0xA282EAD8) & 0xFFFFFFFF


def read_records(data: bytes) -> list[bytes] | None:
    """Every whole record in a LevelDB log, or None if any part is damaged (a bad
    CRC, a fragment out of order, a record cut off before the end)."""
    out: list[bytes] = []
    part: bytearray | None = None
    pos = 0
    while pos < len(data):
        left = BLOCK - pos % BLOCK
        if left < HEADER:   # the block's tail: zero padding
            if any(data[pos:pos + left]):
                return None
            pos += left
            continue
        if pos + HEADER > len(data):
            return None
        crc, length, kind = struct.unpack_from("<IHB", data, pos)
        if kind == 0 and length == 0 and crc == 0:   # zeros to the block's end
            if any(data[pos:pos + left]):
                return None
            pos += left
            continue
        body = data[pos + HEADER:pos + HEADER + length]
        if len(body) != length or HEADER + length > left:
            return None
        if _mask(crc32c(bytes([kind]) + body)) != crc:
            return None
        pos += HEADER + length
        if kind == FULL and part is None:
            out.append(bytes(body))
        elif kind == FIRST and part is None:
            part = bytearray(body)
        elif kind == MIDDLE and part is not None:
            part += body
        elif kind == LAST and part is not None:
            out.append(bytes(part + body))
            part = None
        else:
            return None
    return None if part is not None else out


def frame(record: bytes, offset: int) -> bytes:
    """`record` as log fragments, for a log `offset` bytes long."""
    out = bytearray()
    first = True
    rest = record
    while True:
        left = BLOCK - (offset + len(out)) % BLOCK
        if left < HEADER:
            out += b"\0" * left
            continue
        n = min(len(rest), left - HEADER)
        last = n == len(rest)
        kind = FULL if first and last else FIRST if first else LAST if last else MIDDLE
        body = rest[:n]
        out += struct.pack("<IHB", _mask(crc32c(bytes([kind]) + body)), n, kind) + body
        rest = rest[n:]
        first = False
        if last:
            return bytes(out)


def _put_varint(v: int) -> bytes:
    out = bytearray()
    while v >= 0x80:
        out.append(v & 0x7F | 0x80)
        v >>= 7
    out.append(v)
    return bytes(out)


def _skip_str(b: bytes, i: int) -> int:
    n, i = _varint(b, i)
    return i + n


def manifest_sequence(edits: list[bytes]) -> int:
    """The highest last-sequence the MANIFEST's version edits record."""
    best = 0
    for e in edits:
        i = 0
        while i < len(e):
            tag, i = _varint(e, i)
            if tag == 1:                  # comparator
                i = _skip_str(e, i)
            elif tag in (2, 3, 9):        # log number, next file, previous log
                _, i = _varint(e, i)
            elif tag == 4:                # last sequence
                v, i = _varint(e, i)
                best = max(best, v)
            elif tag == 5:                # compact pointer: level, key
                _, i = _varint(e, i)
                i = _skip_str(e, i)
            elif tag == 6:                # deleted file: level, number
                _, i = _varint(e, i)
                _, i = _varint(e, i)
            elif tag == 7:                # new file: level, number, size, smallest, largest
                for _k in range(3):
                    _, i = _varint(e, i)
                i = _skip_str(e, i)
                i = _skip_str(e, i)
            else:
                raise ValueError(f"unknown manifest tag {tag}")
    return best


def log_sequence(records: list[bytes]) -> int:
    """The highest sequence number a log's write batches use."""
    best = 0
    for r in records:
        if len(r) >= 12:
            seq, count = struct.unpack_from("<QI", r, 0)
            best = max(best, seq + max(count, 1) - 1)
    return best


def batch_put(seq: int, key: bytes, value: bytes) -> bytes:
    return (struct.pack("<QI", seq, 1) + b"\x01" + _put_varint(len(key)) + key
            + _put_varint(len(value)) + value)


def batch_value(record: bytes) -> bytes | None:
    """The value of a one-put write batch (batch_put's), else None."""
    try:
        seq, count = struct.unpack_from("<QI", record, 0)
        if count != 1 or record[12] != 1:
            return None
        n, i = _varint(record, 13)
        i += n
        n, i = _varint(record, i)
        return record[i:i + n]
    except (struct.error, IndexError):
        return None


def decode_value(value: bytes) -> str:
    return (value[1:].decode("latin-1") if value[:1] == b""
            else value[1:].decode("utf-16-le"))


def encode_value(text: str) -> bytes:
    """Chromium's local storage value: 1 + Latin-1, or 0 + UTF-16 (anything else)."""
    try:
        return b"\x01" + text.encode("latin-1")
    except UnicodeEncodeError:
        return b"\x00" + text.encode("utf-16-le")


# ---------------------------------------------------------------- writing

class Locked(Exception):
    """Discord has its settings open (it's running): nothing can be written now."""


def _lock(folder: Path):
    """Hold LevelDB's LOCK file the way Discord does, so it can't open the folder
    while we write. Raises Locked while it's open."""
    if sys.platform != "win32":
        raise Locked("not on Windows")
    import msvcrt
    try:
        f = open(folder / "LOCK", "a+b")   # noqa: SIM115 - held until unlock
    except OSError as e:
        raise Locked(str(e)) from e
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as e:
        f.close()
        raise Locked(str(e)) from e
    return f


def _unlock(f):
    import msvcrt
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    f.close()


def _backup(store: dict | None, client_dir: str, backup_root: Path) -> Path | None:
    """The voice settings a write replaces (the MediaEngineStore JSON, nothing else),
    for going back by hand: `<client>/<time>.json`. Never Discord's files themselves:
    they hold its login too. The client's folder is made even with nothing to keep: it
    marks a Discord this app has written to (alertcontrol's quit)."""
    folder = backup_root / client_dir
    folder.mkdir(parents=True, exist_ok=True)
    drop_old_copies(backup_root)
    if store is None:
        return None
    dest = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10**9:09d}.json"
    dest.write_text(json.dumps(store, separators=(",", ":"), ensure_ascii=False), "utf-8")
    old = sorted(folder.glob("*.json"), key=lambda p: (_mtime(p), p.name))
    stale = time.time() - BACKUP_DAYS * 86400
    for p in old[:-BACKUPS] + [p for p in old[-BACKUPS:] if p != dest and _mtime(p) < stale]:
        p.unlink(missing_ok=True)
    return dest


def drop_old_copies(backup_root: Path) -> int:
    """Remove the copies of Discord's files older versions kept here (OLD_COPY folders,
    its login possibly among them). Only those: nothing else is looked at. Returns how
    many went."""
    gone = 0
    try:
        clients = [p for p in backup_root.iterdir() if p.is_dir()]
    except OSError:
        return 0
    for c in clients:
        try:
            old = [p for p in c.iterdir() if p.is_dir() and OLD_COPY.fullmatch(p.name)]
        except OSError:
            continue
        for p in old:
            shutil.rmtree(p, ignore_errors=True)
            gone += not p.exists()
    if gone:
        log.info("removed %d old copies of Discord's files", gone)
    return gone


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def write_store(client_dir: str, store: dict, backup_root: Path,
                appdata: Path | None = None, what: str = "talking settings put back") -> bool:
    """Put `store` in as Discord's MediaEngineStore. True once it's in and reads back;
    raises Locked while Discord has the folder open; False (nothing written, or put
    back from the backup) on anything unexpected."""
    folder = discordcfg._folder(client_dir, appdata)
    if folder is None or not folder.is_dir():
        return False
    lock = _lock(folder)
    try:
        logs = sorted(folder.glob("*.log"), key=lambda p: int("".join(filter(
            str.isdigit, p.stem)) or 0))
        current = (folder / "CURRENT").read_text("ascii", "replace").strip()
        manifest = folder / current
        if not logs or not current.startswith("MANIFEST-") or not manifest.is_file():
            log.info("%s: no log or manifest to write to", client_dir)
            return False
        log_path = logs[-1]
        data = log_path.read_bytes()
        records = read_records(data)
        edits = read_records(manifest.read_bytes())
        if records is None or edits is None:
            log.info("%s: its database doesn't read cleanly; not touching it", client_dir)
            return False
        seq = max(manifest_sequence(edits), log_sequence(records)) + 1
        value = encode_value(json.dumps(store, separators=(",", ":"), ensure_ascii=False))
        _backup(read_store(client_dir, appdata), client_dir, backup_root)
        with open(log_path, "ab") as f:
            f.write(frame(batch_put(seq, KEY, value), len(data)))
            f.flush()
            os.fsync(f.fileno())
        after = read_records(log_path.read_bytes())
        got = batch_value(after[-1]) if after else None
        ok = (after is not None and len(after) == len(records) + 1 and got is not None
              and json.loads(decode_value(got)) == store)
        if not ok:   # never leave it half done
            with open(log_path, "r+b") as f:
                f.truncate(len(data))
            log.warning("%s: the written settings didn't read back; undone", client_dir)
            return False
        log.info("%s: %s (sequence %d)", client_dir, what, seq)
        return True
    except (OSError, ValueError, IndexError):
        log.warning("%s: couldn't put its settings back", client_dir, exc_info=True)
        return False
    finally:
        _unlock(lock)


def read_store(client_dir: str, appdata: Path | None = None) -> dict | None:
    """The client's MediaEngineStore as it stands in its files (discordcfg's reader)."""
    folder = discordcfg._folder(client_dir, appdata)
    if folder is None or not folder.is_dir():
        return None
    for f in discordcfg._files(folder):
        try:
            data = f.read_bytes()
            st = f.stat()
        except OSError:
            continue
        store = (discordcfg._latest_store(data) if f.suffix == ".log"
                 else discordcfg._table_store(f, data, st))
        if store is not None:
            return store
    return None


# ---------------------------------------------------------------- on quit

def running_clients() -> set[str]:
    from soundboard.audio import appaudio
    names = {n for _p, n in appaudio._process_table().values()}
    return {c for c, exe in EXES.items() if exe in names}


def installed(appdata: Path | None = None) -> bool:
    """A Discord has a settings folder on this PC (any client)."""
    for client_dir, _n in discordcfg.CLIENTS:
        f = discordcfg._folder(client_dir, appdata)
        if f is not None and f.is_dir():
            return True
    return False


def to_restore(saved: dict, appdata: Path | None = None) -> list[str]:
    """The Discord folders where putting how you talk back (`saved`, else Discord's
    defaults) would change something: the Mic effect card's Put Discord back."""
    out = []
    for client_dir, name in discordcfg.CLIENTS:
        try:
            s = discordcfg.read_client(client_dir, name, appdata)
            store = read_store(client_dir, appdata)
            if (s is not None and store is not None
                    and apply(store, target(saved.get(client_dir), store)) != store):
                out.append(client_dir)
        except Exception:  # noqa: BLE001 - one unreadable client doesn't stop the rest
            log.warning("reading %s failed", client_dir, exc_info=True)
    return out


def restore(saved: dict, backup_root: Path, appdata: Path | None = None,
            running: set[str] | None = None, only=None, always: bool = False) -> list[str]:
    """Put back each Discord left set for sounds (or just the folder names in `only`).
    `always`: also one that's partly set for talking (asked for, not on quit).
    Returns the ones still to do because they're running."""
    if running is None:
        running = running_clients()
    pending = []
    for client_dir, name in discordcfg.CLIENTS:
        if only is not None and client_dir not in only:
            continue
        try:
            s = discordcfg.read_client(client_dir, name, appdata)
            store = read_store(client_dir, appdata)
            if s is None or store is None:
                continue
            talk = target(saved.get(client_dir), store)
            if (apply(store, talk) == store if always
                    else not needs_restore(s, store, talk)):
                continue
            if client_dir in running:
                pending.append(client_dir)
                continue
            try:
                write_store(client_dir, apply(store, talk), backup_root, appdata)
            except Locked:
                pending.append(client_dir)
        except Exception:  # noqa: BLE001 - never let one client stop the rest
            log.warning("putting %s back failed", client_dir, exc_info=True)
    return pending


def set_up(saved: dict, backup_root: Path, on_mic: bool, appdata: Path | None = None,
           running: set[str] | None = None) -> dict:
    """Set every installed Discord that needs it for sounds (SOUND). First, how each one
    is set while you talk is remembered (unless `saved` already has it), so it can go
    back on quit. Returns {"done": [(name, before, after)], "running": [folders still
    open, nothing written], "talk": {folder: snapshot to save}, "failed": [names]}."""
    if running is None:
        running = running_clients()
    out: dict = {"done": [], "running": [], "talk": {}, "failed": []}
    for client_dir, name in discordcfg.CLIENTS:
        try:
            s = discordcfg.read_client(client_dir, name, appdata)
            store = read_store(client_dir, appdata)
            if s is None or store is None or not s.problems(on_mic):
                continue   # not installed, unreadable, or already right for sounds
            if client_dir in running:
                out["running"].append(client_dir)
                continue
            if talking(s) and not saved.get(client_dir):
                out["talk"][client_dir] = snapshot(store)
            new = apply(store, SOUND)
            try:
                ok = write_store(client_dir, new, backup_root, appdata,
                                 what="set up for sounds")
            except Locked:
                out["running"].append(client_dir)
                continue
            if ok:
                out["done"].append((name, s, discordcfg.parse(new, name)))
            else:
                out["failed"].append(name)
        except Exception:  # noqa: BLE001 - never let one client stop the rest
            log.warning("setting up %s failed", client_dir, exc_info=True)
            out["failed"].append(name)
    return out


def close_clients(client_dirs, wait_s: float = CLOSE_WAIT_S) -> bool:
    """Close these Discords (every process of theirs, by its id: Discord only hides in
    the tray when its window's closed) and wait until they're gone. Asked first by
    the caller: it ends any call. True once none of them runs."""
    import subprocess

    from soundboard.audio import appaudio
    exes = {EXES[c] for c in client_dirs if c in EXES}
    for pid, (_parent, exe) in appaudio._process_table().items():
        if exe in exes:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True,
                               timeout=5, creationflags=getattr(subprocess,
                                                                "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.SubprocessError):
                log.warning("closing %s (%d) failed", exe, pid, exc_info=True)
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        if not running_clients() & set(client_dirs):
            time.sleep(0.5)   # its files let go a moment after the process ends
            return True
        time.sleep(0.25)
    return False


def board_running() -> bool:
    """Onion Board is open again (its single-instance mutex exists)."""
    if sys.platform != "win32":
        return False
    import ctypes
    from soundboard.core.singleinstance import INSTANCE_NAME
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.restype = ctypes.c_void_p
    h = k32.OpenMutexW(0x00100000, False, f"Local\\{INSTANCE_NAME}")   # SYNCHRONIZE
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


def job_path(app_dir: Path) -> Path:
    return app_dir / "discord-restore.json"


def start_helper(app_dir: Path, saved: dict, pending: list[str]) -> bool:
    """Hand the clients still running to the helper (a process of its own, no window)."""
    import subprocess
    try:
        job_path(app_dir).write_text(json.dumps({"saved": saved, "pending": pending}),
                                     "utf-8")
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, ARG]
        else:
            main = Path(__file__).resolve().parents[2] / "main.py"
            exe = Path(sys.executable)
            pyw = exe.with_name("pythonw.exe")
            cmd = [str(pyw if pyw.is_file() else exe), str(main), ARG]
        flags = 0
        if sys.platform == "win32":
            flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                     | subprocess.CREATE_NEW_PROCESS_GROUP)
        subprocess.Popen(cmd, creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except OSError:
        log.warning("couldn't start the Discord helper", exc_info=True)
        return False


# ---------------------------------------------------------------- the helper

def _notify(qapp):
    """The tray notification that Discord is still set for sounds; None if it can't."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QSystemTrayIcon

    from soundboard.i18n import _
    try:
        from soundboard.ui.kit.theme import app_icon
        tray = QSystemTrayIcon(app_icon(), parent=qapp)   # not a widget: no window
        tray.setToolTip("Onion Board")
        tray.messageClicked.connect(lambda: os.startfile(VOICE_URL))  # noqa: S606
        tray.show()
        tray.showMessage(
            _("Discord is still set up for sounds"),
            _("Onion Board turns its voice clean-up back on as soon as you close Discord. "
              "To talk clearly right now, click here and turn on Noise Suppression, Echo "
              "Cancellation and Automatic Gain Control."),
            QSystemTrayIcon.MessageIcon.Information, 15000)
        QTimer.singleShot(20000, tray.hide)
        return tray
    except Exception:  # noqa: BLE001 - no notification: still put it back
        log.warning("no notification", exc_info=True)
        return None


def cli(rest: list[str]) -> int:
    """`--discord-restore`: says Discord is still set for sounds (a notification), then
    puts it back as soon as it closes. Ends when that's done, when Onion Board opens
    again (it takes over), or after HELPER_MAX_S.

    The installer stops a waiting helper before it replaces the files, then starts it
    again with QUIET (no second notification). The uninstaller runs it with NOW: put
    back whatever's closed and end at once, exit code STILL_OPEN when a Discord is
    still open (the uninstaller then says how to put it back by hand)."""
    from soundboard.core.bootmark import app_dir
    app = app_dir()
    logging.basicConfig(filename=str(app / "discord-restore.log"), filemode="w",
                        level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        job = json.loads(job_path(app).read_text("utf-8"))
        saved, pending = dict(job.get("saved") or {}), list(job.get("pending") or [])
    except (OSError, ValueError):
        log.info("no job")
        return 0
    if NOW in rest:
        left = []
        try:
            left = restore(saved, app / "discord-backup", only=set(pending))
        except Exception:  # noqa: BLE001 - the uninstall goes on regardless
            log.exception("putting it back failed")
        log.info("put back at once; still open: %s", ", ".join(left) or "none")
        job_path(app).unlink(missing_ok=True)   # the app is going: nothing will wait
        return STILL_OPEN if left else 0
    from soundboard import i18n
    i18n.startup(app)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    qapp = QApplication(sys.argv[:1])
    qapp.setQuitOnLastWindowClosed(False)
    tray = None if QUIET in rest else _notify(qapp)   # QUIET: told once already
    start = time.monotonic()

    def tick():
        nonlocal pending
        try:
            if board_running():
                log.info("Onion Board is open again: it takes over")
            elif time.monotonic() - start > HELPER_MAX_S:
                log.info("gave up waiting for Discord to close")
            elif set(pending) <= running_clients():   # all still open: wait
                return
            else:
                pending = restore(saved, app / "discord-backup", only=set(pending))
                if pending:
                    return
                log.info("done")
            job_path(app).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            log.exception("helper failed")
        qapp.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(int(HELPER_POLL_S * 1000))
    qapp.exec()
    if tray is not None:
        tray.hide()
    return 0
