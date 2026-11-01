"""The mic effect on this PC's mics, read without admin: which recording devices
there are, which of them carry the effect, its state on each (status, repair
checks) and whether any of it is installed."""
from __future__ import annotations

import hashlib
import re
import threading
import time
import winreg
from collections.abc import Sequence
from pathlib import Path

from soundboard.core.pollthread import PollThread
from soundboard.mic.micbase import (CAPTURE_KEY, CLSID, COMPOSITE_SFX, EAPO_CLSIDS, EAPO_KEY,
                                    EAPO_NONE, ENDPOINTS_KEY, ENDPOINT_SLOTS, FX, NAME_DESC,
                                    NAME_ENUM, NAME_IFACE, OUR_SLOTS, RENDER_KEY, SFX,
                                    UNPLUGGED_STATES, _old_install_dirs, bundled_dll, install_dir,
                                    log)
from soundboard.mic.micring import make_ring


# ---------------------------------------------------------------------- the mics

def capture_endpoints() -> list[dict]:
    """Every recording device Windows knows: {"guid", "name", "active", "out": unplugged
    (or its USB or Bluetooth headset switched off), "device": the part of the name in
    brackets ("AirPods Pro Hands-Free"), "bt": a Bluetooth headset's}."""
    return _endpoints(CAPTURE_KEY)


def render_endpoints() -> list[dict]:
    """Every playback device Windows knows, as capture_endpoints()."""
    return _endpoints(RENDER_KEY)


def _endpoints(key: str) -> list[dict]:
    found = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key)
    except OSError:
        return found
    with root:
        i = 0
        while True:
            try:
                guid = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, guid) as k:
                    state = winreg.QueryValueEx(k, "DeviceState")[0]
                with winreg.OpenKey(root, guid + r"\Properties") as p:
                    desc = _value(p, NAME_DESC) or "Microphone"
                    iface = _value(p, NAME_IFACE)
                    enum = _value(p, NAME_ENUM)
            except OSError:
                continue
            name = f"{desc} ({iface})" if iface else desc
            found.append({"guid": guid.lower(), "name": name, "active": state == 1,
                          "out": state in UNPLUGGED_STATES, "device": iface or "",
                          "bt": str(enum or "").upper().startswith("BTH")})
    return found


_HANDS_FREE = re.compile(r"\s*hands[- ]?free(\s+ag\s+audio)?\s*$", re.I)


def _sound_only(mic_name: str) -> str | None:
    """The name of the Bluetooth headset `mic_name` is the mic of, when Windows has the
    headset on for sound but its mic off: a Bluetooth headset (AirPods most of all)
    connects its sound and its phone-call mic separately, and the mic half drops out
    while the sound keeps playing (a phone took it, or Windows never connected it).
    None for anything else. Reads the registry: not on the UI thread."""
    off = [e for e in _near(mic_name, [e for e in capture_endpoints() if not e["active"]])
           if e.get("bt")]
    if not off:
        return None
    halves = {_squash(_HANDS_FREE.sub("", e.get("device", ""))) for e in off} - {""}
    for e in render_endpoints():
        headset = _HANDS_FREE.sub("", e.get("device", ""))
        if e["active"] and e.get("bt") and _squash(headset) in halves:
            return headset
    return None


def endpoint_for(name: str | None) -> str | None:
    """The endpoint GUID of the active recording device called `name` (as PortAudio
    lists it: its name may be cut short, so a prefix match counts)."""
    return mic_lookup(name)[0]


def mic_lookup(name: str | None) -> tuple[str | None, str]:
    """(endpoint GUID, "") of the active mic called `name`, else (None, why): "off"
    Windows knows it but it's unplugged or switched off, "unsure" two active mics start
    like that name (a cut-short one) and either could be it, "gone" Windows doesn't
    know it at all (an old mic, or renamed: "Microphone (2- USB Audio)" in another port).
    The why is counted (FAIL_KINDS no-mic-<why>), never the name."""
    if not name:
        return None, "gone"
    endpoints = capture_endpoints()
    active = [e for e in endpoints if e["active"]]
    guid = _match(name, active)
    if guid is not None:
        return guid, ""
    # the engine finds a saved name more loosely (engine.find_device): the mic it opened
    # (and the meter shows working) is the one meant. Uninstall feedback: "it said it
    # couldn't find my mic, but it was showing it picked up my mic sound just fine"
    opened = _engine_name(name)
    if opened and opened != name:
        exact = [e for e in active if _squash(e["name"]) == _squash(opened)]
        if len(exact) == 1:
            return exact[0]["guid"], ""
    # the same mic in another USB port: Windows numbers it ("Microphone (2- USB Audio)"
    # for the saved "Microphone (USB Audio)", or the other way round). Only when one fits
    same = [e for e in active if _unnumbered(e["name"]) == _unnumbered(name)]
    if len(same) == 1:
        return same[0]["guid"], ""
    # Windows itself, asked now: the registry's copy of a mic's name or state can
    # disagree with what Windows (and so the app's mic list) says. New users' first
    # set-up said it didn't know the mic they had just picked (no-mic-gone)
    live = [{"guid": g, "name": n} for g, n in _windows_mics()]
    for want in dict.fromkeys(n for n in (name, opened) if n):
        exact = [e for e in live if _squash(e["name"]) == _squash(want)]
        if len(exact) == 1:
            log.info("mic found by asking Windows (not in the registry's list)")
            return exact[0]["guid"], ""
    if len(_near(name, active)) > 1:
        return None, "unsure"
    others = [e for e in endpoints if not e["active"]]
    if _near(name, others):
        return None, "off"
    return None, "gone"


def fallback_mic(name: str | None) -> str | None:
    """The mic to set up instead when the picked `name` isn't one Windows knows (none
    picked, an old mic, renamed): Windows' default recording device, the one the board
    records then too. Never a virtual cable (our own sounds fed back in), never `name`
    itself, and None unless Windows has it on now. An unplugged or switched-off mic
    isn't swapped: it's the one meant, and it's back when it's plugged in."""
    try:
        from soundboard.audio import engine
        other = engine.default_device_name("input")
    except Exception:  # noqa: BLE001 - no audio devices to ask: nothing to fall back on
        log.debug("default mic lookup failed", exc_info=True)
        return None
    if not other or other == name or engine.is_virtual(other):
        return None
    return other if endpoint_for(other) is not None else None


def _windows_mics() -> list[tuple[str, str]]:
    """appaudio.capture_mics(): [(endpoint GUID, name)] of the mics Windows has on now
    ([] if it can't be asked)."""
    try:
        from soundboard.audio import appaudio
        return appaudio.capture_mics() or []
    except Exception:  # noqa: BLE001 - only a last try: the registry's answer stands
        log.debug("asking Windows for its mics failed", exc_info=True)
        return []


def _engine_name(name: str) -> str | None:
    """The name of the recording device the engine opens for the saved `name`."""
    try:
        from soundboard.audio import engine
        idx = engine.find_device("input", name)
        return None if idx is None else engine.list_name(idx)
    except Exception:  # noqa: BLE001 - no audio devices to ask: the registry's answer stands
        log.debug("engine name lookup failed", exc_info=True)
        return None


def _squash(name: str) -> str:
    """A name with Windows' odd spacing and case ironed out (as engine.find_device)."""
    return " ".join(name.split()).lower()


def _unnumbered(name: str) -> str:
    """_squash(name) without the port number Windows puts in front of a second copy's
    name: "Microphone (2- USB Audio)" -> "microphone (usb audio)"."""
    return re.sub(r"\(\d+-\s*", "(", _squash(name))


def _near(name: str, mics: list[dict]) -> list[dict]:
    n = _squash(name)
    return [e for e in mics if _squash(e["name"]).startswith(n)
            or n.startswith(_squash(e["name"]))]


def _match(name: str, active: list[dict]) -> str | None:
    for e in active:
        if e["name"] == name:
            return e["guid"]
    for e in active:
        if _squash(e["name"]) == _squash(name):
            return e["guid"]
    near = _near(name, active)
    # one mic only: two that start the same (a cut-short name) could be the wrong one
    return near[0]["guid"] if len(near) == 1 else None


def _value(key, name):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


# Windows' Privacy & security > Microphone switches: for the whole PC (HKLM), "Let apps
# access your microphone" and "Let desktop apps access your microphone" (HKCU)
_CONSENT_KEY = (r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
                r"\ConsentStore\microphone")
_CONSENT = ((winreg.HKEY_LOCAL_MACHINE, _CONSENT_KEY), (winreg.HKEY_CURRENT_USER, _CONSENT_KEY),
            (winreg.HKEY_CURRENT_USER, _CONSENT_KEY + r"\NonPackaged"))


def windows_blocks_mic() -> bool:
    """One of Windows' microphone privacy switches is off, so this app gets silence
    from every mic (it still opens). False when it can't tell."""
    for root, path in _CONSENT:
        try:
            with winreg.OpenKey(root, path) as k:
                if str(_value(k, "Value") or "").lower() == "deny":
                    return True
        except OSError:
            continue
    return False


def installed_on() -> list[str]:
    """Endpoint GUIDs the effect is installed on."""
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ENDPOINTS_KEY)
    except OSError:
        return []
    out = []
    with root:
        i = 0
        while True:
            try:
                out.append(winreg.EnumKey(root, i).lower())
            except OSError:
                break
            i += 1
    return out


_status_cache: dict = {}
_status_gen = [0]          # forget_status() bumps it: a refresh started before is dropped
_status_busy: set = set()  # mic names being re-checked on a thread
# One thread kept for the re-checks: starting a new one each time made the window wait
# in Thread.start until Windows had it running (a 2.2.1 freeze)
_status_poll = PollThread("mic-effect-status")
_status_lock = threading.Lock()
_unplugged: dict = {}   # mic name -> unplugged at the last status() check
_sound_only_on: dict = {}   # mic name -> its Bluetooth headset, on for sound only (or None)
STATUS_S = 2.0


def forget_status():
    with _status_lock:
        _status_cache.clear()
        _unplugged.clear()
        _sound_only_on.clear()
        _status_gen[0] += 1


def status(mic_name: str | None = None) -> str:
    """Where Onion Board stands on the mic called `mic_name` (any mic it's on if None):
      'missing'   not attached to any mic
      'other'     attached, but to another mic
      'wiped'     attached, but Windows (a driver or Windows update) took the effect off,
                  or its DLL file (or that file's registration) is gone
      'outdated'  attached, but with another version of the effect than this app's
      'ready'     attached and working
    'wiped' and 'outdated' need the one-click repair (attaching again).

    The first answer is worked out at once; after that it's re-checked every STATUS_S
    on a thread, and the last answer comes back meanwhile. The check reads the
    registry and the ring file, and the window asks every second: on a busy disk the
    stat alone froze it for 6 s (1.9.7)."""
    with _status_lock:
        hit = _status_cache.get(mic_name)
        now = time.monotonic()
        if hit and now - hit[0] < STATUS_S:
            return hit[1]
        if hit:
            if mic_name not in _status_busy:
                _status_busy.add(mic_name)
                gen = _status_gen[0]
                _status_poll.run(lambda: _refresh_status(mic_name, gen))
            return hit[1]
        gen = _status_gen[0]
    result = _status(mic_name)
    with _status_lock:
        if gen == _status_gen[0]:
            _status_cache[mic_name] = (time.monotonic(), result)
    return result


def _refresh_status(mic_name: str | None, gen: int):
    try:
        result = _status(mic_name)
    except Exception:  # noqa: BLE001 - keep the last answer; tried again later
        log.warning("couldn't check the mic effect", exc_info=True)
        result = None
    with _status_lock:
        _status_busy.discard(mic_name)
        if gen != _status_gen[0]:
            return
        hit = _status_cache.get(mic_name)
        _status_cache[mic_name] = (time.monotonic(),
                                   result if result is not None else hit[1] if hit else "missing")


def needs_repair(state: str) -> bool:
    """Windows took it off the mic: it has to be put back (one prompt)."""
    return state == "wiped"


def works(state: str) -> bool:
    """On the mic and working. An older copy of the effect ('outdated') still works:
    the update is offered, not forced."""
    return state in ("ready", "outdated")


def unplugged(mic_name: str | None) -> bool:
    """The mic called `mic_name` isn't there right now: unplugged, its headset or Windows
    switched it off, or Windows forgot it (as the last status() for it found: no I/O)."""
    return bool(mic_name) and _unplugged.get(mic_name, False)


def sound_only(mic_name: str | None) -> str | None:
    """The headset's name when the mic called `mic_name` isn't there because it's a
    Bluetooth headset's that Windows has on for sound only, its mic off (as the last
    status() for it found). "Is it plugged in?" is wrong then: it is, and it plays."""
    return _sound_only_on.get(mic_name) if mic_name else None


def _status(mic_name: str | None) -> str:
    on = installed_on()
    if mic_name is None:
        return _state(on[0], on) if on else "missing"
    guid = endpoint_for(mic_name)
    gone = _unplugged[mic_name] = guid is None and _not_here(mic_name)
    _sound_only_on[mic_name] = _sound_only(mic_name) if gone else None
    if not on:
        return "missing"
    return _state(guid, on)


def _not_here(mic_name: str) -> bool:
    """The mic isn't there: unplugged, switched off, or forgotten by Windows once it was
    pulled out (and nothing the engine can open goes by that name either). Nothing to
    set up or repair until it's back: the card asks whether it's plugged in, no louder."""
    why = mic_lookup(mic_name)[1]
    return why == "off" or why == "gone" and _engine_name(mic_name) is None


def _state(guid: str | None, on: list[str]) -> str:
    """status() for one mic by its endpoint GUID, given installed_on()."""
    if not on:
        return "missing"
    if guid not in on:
        return "other"
    dll = registered_dll()
    # the DLL deleted (a cleaner, an antivirus) or its registration gone: Windows has
    # nothing to load, so sounds stop reaching the mic. Not 'outdated' (which counts as
    # working, so nothing happened): the repair copies it back.
    if not effect_in_place(guid) or dll is None or not dll.is_file() or not make_ring():
        return "wiped"
    if not same_dll(dll, bundled_dll()) \
            or installed_slot(guid) in (SFX, COMPOSITE_SFX):   # raw streams skip it
        return "outdated"
    return "ready"


def status_on(guid: str) -> str:
    """status() for the mic with endpoint GUID `guid`, worked out now (no cache)."""
    return _state(guid.lower(), installed_on())


def mics(names: Sequence[str] = ()) -> list[dict]:
    """The mics the recovery card offers, each by its endpoint GUID (two mics can share
    a name): every plugged-in one, plus an unplugged one the effect is still on. Never a
    virtual cable's end (CABLE Output): it records our own sounds, so the effect has no
    place on it, unless it's already on one (then it's listed, to take it off).
    {"guid", "name", "active", "state" (as status()), "pa": the name in `names` (the
    app's device list) that is this mic, or None}. Reads the registry: not on the UI
    thread."""
    from soundboard.audio.devicelist import is_virtual
    on = installed_on()
    found = [e for e in capture_endpoints() if e["guid"] in on or not is_virtual(e["name"])]
    active = [e for e in found if e["active"]]
    pa = {}
    for n in names:
        # a name two plugged-in mics share can't say which it is: neither gets it
        twins = sum(e["name"] == n for e in active) > 1
        guid = None if twins else _match(n, active)
        if guid and guid not in pa:
            pa[guid] = n
    out = []
    for e in found:
        if not e["active"] and e["guid"] not in on:
            continue
        try:
            state = _state(e["guid"], on)
        except OSError:
            state = "unknown"
        out.append({**e, "state": state, "pa": pa.get(e["guid"])})
    out.sort(key=lambda m: (not m["active"], m["name"].lower()))
    return out


def installed_slot(guid: str) -> int | None:
    """The effect slot the effect was put in on this mic (None: not on it)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{ENDPOINTS_KEY}\{guid}") as k:
            return int(winreg.QueryValueEx(k, "Slot")[0])
    except (OSError, ValueError):
        return None


def endpoint_wide() -> bool:
    """The effect sits in the mic's endpoint effect: every app recording the mic gets it,
    raw streams too, through one shared copy (so its stream count isn't per app)."""
    return any(installed_slot(g) in ENDPOINT_SLOTS for g in installed_on())


def effect_in_place(guid: str) -> bool:
    """Our effect is still in one of the mic's effect slots (a driver update rewrites
    them, Windows' "Reset sound settings" too)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"{CAPTURE_KEY}\{guid}\FxProperties") as k:
            slots = [_value(k, FX % pid) for pid in OUR_SLOTS]
    except OSError:
        return False
    return any(_is_ours(v) for v in slots) \
        or any(_is_eapo(v) for v in slots) and bool(eapo_runs_us(guid))


def _is_eapo(value) -> bool:
    """An effect slot's value is Equalizer APO's effect."""
    return isinstance(value, str) and value.upper() in EAPO_CLSIDS


def eapo_runs_us(guid: str) -> list[str]:
    """The names of Equalizer APO's notes for this mic that hold this effect (it was put
    on the mic after this one, and runs it): [] if none, or no Equalizer APO."""
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{EAPO_KEY}\{guid}") as k:
            i = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if _is_ours(value):
                    out.append(name)
    except OSError:
        pass
    return out


def _eapo_hand_back(guid: str, original: str) -> bool:
    """Equalizer APO runs this effect on this mic: point its notes at the effect this one
    ran (`original`, "" for none) instead, so it runs that. False if it doesn't run us."""
    names = eapo_runs_us(guid)
    if not names:
        return False
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{EAPO_KEY}\{guid}", 0,
                        winreg.KEY_SET_VALUE) as k:
        for name in names:
            # its slot notes say "none" with a word, its *Child notes with ""
            gone = EAPO_NONE if name.startswith("{") else ""
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, original or gone)
    log.info("%s: Equalizer APO runs the mic's own effect again", guid)
    return True


def without_ours(value):
    """An effect slot's value with this effect taken out: (changed, new value or None
    to delete it). Only our own CLSID goes; every other effect in a list stays."""
    if isinstance(value, list):
        rest = [x for x in value if not (isinstance(x, str) and x.upper() == CLSID)]
        return len(rest) != len(value), (rest or None)
    return (True, None) if _is_ours(value) else (False, value)


def _fx_values(guid: str) -> dict:
    """Every effect-slot value on a mic ({name: value}); {} if it has none."""
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"{CAPTURE_KEY}\{guid}\FxProperties") as k:
            i = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if name.lower().startswith(FX.split(",")[0].lower() + ","):
                    out[name] = value
    except OSError:
        pass
    return out


def leftovers(guid: str) -> bool:
    """Something of Onion Board's is still on this mic although the notes say it isn't
    (a set-up cut off, notes lost): our CLSID in one of its effect slots, or, with the
    effect on no mic at all, its registration or files. Reads only: no admin."""
    if guid.lower() in installed_on():
        return True   # on it properly: Remove takes it off
    if any(without_ours(v)[0] for v in _fx_values(guid).values()):
        return True
    return not installed_on() and anything_installed()


def _is_ours(value) -> bool:
    """An effect slot's value (one CLSID, or a list of them) holds this effect."""
    vals = value if isinstance(value, list) else [value]
    return any(isinstance(x, str) and x.upper() == CLSID for x in vals)


def registered_dll() -> Path | None:
    """The effect DLL Windows loads (the one registered for our CLSID)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"SOFTWARE\Classes\CLSID\{CLSID}\InprocServer32") as k:
            v = _value(k, "")
    except OSError:
        return None
    return Path(v) if isinstance(v, str) and v else None


_hashes: dict = {}


def _digest(path: Path) -> str | None:
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _hashes:
        try:
            _hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None
    return _hashes[key]


def same_dll(installed: Path | None, ours: Path) -> bool:
    """The installed effect is this app's own. An app without one of its own (a build
    from source that never built it) can't tell, and takes what's there."""
    if not ours.is_file():
        return installed is not None and installed.is_file()
    if installed is None:
        return False
    a = _digest(installed)
    return a is not None and a == _digest(ours)



def anything_installed() -> bool:
    return bool(installed_on()) or registered_dll() is not None \
        or any(d.exists() for d in (install_dir(), *_old_install_dirs()))
