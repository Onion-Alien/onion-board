"""Whole-pixel painting at fractional display scales (125 %, 150 %, ...): lives in the
style kit (soundboard/style/appstate.py), which Hoot shares with Onion Watch."""
from soundboard.style.appstate import snap_to_pixels

__all__ = ["snap_to_pixels"]
