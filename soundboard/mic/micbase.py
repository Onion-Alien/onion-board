"""The mic effect's names and places: its COM class, the registry keys and effect
slots it uses on a mic, where its files go. Shared by every part of it (directmic.py
has the whole design)."""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

log = logging.getLogger("soundboard.mic.directmic")   # one log for the whole mic effect

FLAG = "--direct-mic"
CLSID = "{C55E76FE-6667-4828-81FD-05B393FD649E}"   # obmic.cpp CLSID_OnionMic
DEVICE = "Your mic (no cable)"         # the send "device" for the engine
DLL_NAME = "obmic.dll"
EFFECT_VERSION = 5                                  # obmic.cpp EFFECT_VERSION

STATE_KEY = r"SOFTWARE\OnionBoard\MicPlugin"
ENDPOINTS_KEY = STATE_KEY + r"\Endpoints"
CAPTURE_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
RENDER_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
FX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},%d"   # PKEY_FX_* / PKEY_CompositeFX_*
# On a recording device Windows runs the effects in front of each app's stream: SFX (or
# LFX on drivers that only know the old kind), after the device's own EFX if it has one.
# An app asking for a raw stream (Chrome and Edge whenever the mic offers raw, Discord's
# Studio profile) skips SFX/MFX but not EFX, the endpoint's always-on effect: one copy
# for every app recording the mic. So the effect goes in EFX.
LFX, GFX, SFX, MFX, EFX = 1, 2, 5, 6, 7
SLOTS_FX = {"sfx": SFX, "lfx": LFX, "efx": EFX}     # where the effect goes on a mic
MODERN = (SFX, MFX, EFX)
LEGACY = (LFX, GFX)
COMPOSITE_SFX = 13                                  # PKEY_CompositeFX_StreamEffectClsid
COMPOSITE_EFX = 15                                  # PKEY_CompositeFX_EndpointEffectClsid
ENDPOINT_SLOTS = (EFX, COMPOSITE_EFX)               # raw streams get these too
OUR_SLOTS = (SFX, LFX, COMPOSITE_SFX, EFX, COMPOSITE_EFX)
# Equalizer APO works like this effect: it takes a slot and runs the effect it replaced,
# noted per mic under EAPO_KEY\<endpoint> as "<FX % pid>" (or "!VALUE": none) plus
# PreMixChild / PostMixChild. Put on the mic after this effect, it runs this one: that
# counts as on the mic, and this effect never wraps it back (obmic.cpp EAPO_*).
EAPO_KEY = r"SOFTWARE\EqualizerAPO\Child APOs"
EAPO_CLSIDS = ("{EACD2258-FCAC-4FF4-B36D-419E924A6D79}",   # its pre-mix effect
               "{EC1CC9CE-FAED-4822-828A-82A81A6F018F}")   # its post-mix effect
EAPO_NONE = "!VALUE"
DISABLE_SYSFX = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"   # "Audio enhancements: off"
MODES_KEY = "{d3993a3f-99c2-4402-b5ec-a92a0367664b},%d"     # PKEY_*_ProcessingModes_...
MODE_DEFAULT = "{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}"     # AUDIO_SIGNALPROCESSINGMODE_DEFAULT
NAME_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"       # "Microphone"
NAME_IFACE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"      # "Realtek Audio"
NAME_ENUM = "{a45c254e-df1c-4efd-8020-67d146a850e0},24"      # "USB", "BTHHFENUM" (Bluetooth)
UNPLUGGED_STATES = (4, 8)   # DEVICE_STATE_NOTPRESENT, _UNPLUGGED (2 is switched off by hand)
_GUID = re.compile(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{12}\}")
_CREATE_NO_WINDOW = 0x08000000


def data_dir() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OnionBoard" / "MicPlugin"


def ring_path() -> Path:
    return data_dir() / "ring2.bin"   # (ring.bin: the first test build's layout)


def install_dir() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Onion Board Mic"


def _old_install_dirs() -> list[Path]:
    """Where the first test builds put the effect (removed on install / uninstall)."""
    return [install_dir().parent / "Onion Board Mic Plugin"]


def bundled_dll() -> Path:
    """This app's own copy of the effect: next to the frozen app, or the one
    scripts/directmic/build_directmic.py built when run from source."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "directmic" / DLL_NAME
    return Path(__file__).resolve().parents[2] / "build" / "directmic" / DLL_NAME
