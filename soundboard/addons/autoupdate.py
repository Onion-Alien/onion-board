"""Add-ons kept up to date by themselves, alongside the app's own update.

With *Install updates by themselves* ticked in Settings > Updates (and the update check
on, an installed copy, add-ons allowed online), the check as the app starts also brings
the add-ons that came from GitHub up to date:

- Onion Watch and Onion Pocket: the newer zip is downloaded and installed; the copy
  already running keeps running, and the new one loads the next time it starts
  (Onion Watch's Triggers tab says so). A failure leaves the old one, and Onion
  Watch's tab offers its Update button instead.
- AI voices: its newer zip is fetched and its set-up runs (the panel's own Update),
  only while no AI voice is on.
- A downloaded language that has no voice of its own yet gets it (once AI voices can
  read it), as its *Download the voice* button would.

Copies shipped with the app (not removable) are left alone: the app's update brings
those. Everything that goes online runs off the UI thread; `check()` raises nothing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from soundboard.addons import aiaddon, pocketaddon
from soundboard.core import updates
from soundboard.online import net

log = logging.getLogger(__name__)

FEATURE = "addons"   # "Get and update add-ons" in Settings > Privacy & security


@dataclass
class Found:
    """What `check()` found newer than what's installed (None: nothing to do)."""
    pocket: pocketaddon.Offer | None = None
    ai: aiaddon.Offer | None = None


def wanted(cfg) -> bool:
    """Whether add-ons install their updates by themselves: the same switches as the
    app's own (UpdateControl._can_auto), and add-ons allowed to go online."""
    return bool(cfg.update_auto and cfg.update_check and updates.can_install()
                and net.allowed(FEATURE))


def _newer_ai() -> aiaddon.Offer | None:
    info = aiaddon.installed()
    if info is None or not info.installed or not aiaddon.removable(info):
        return None
    try:
        offer = aiaddon.latest()
    except Exception as e:  # noqa: BLE001 - offline, rate-limited, switched off…
        log.info("AI voices update check failed: %s", e)
        return None
    if offer is not None and updates.newer(offer.version, info.version):
        log.info("a newer AI voices add-on is out: %s", offer.version)
        return offer
    return None


def _newer_pocket() -> pocketaddon.Offer | None:
    info = pocketaddon.installed()
    if info is None or not pocketaddon.removable(info):
        return None
    return pocketaddon.check_update(info)


def check() -> Found:
    """The add-ons with a newer release than the one installed. Call off the UI
    thread; errors are logged, never raised."""
    found = Found()
    for name, ask in (("pocket", _newer_pocket), ("ai", _newer_ai)):
        try:
            setattr(found, name, ask())
        except Exception:  # noqa: BLE001 - one add-on can't stop the others
            log.exception("checking the %s add-on for an update failed", name)
    return found


def install_pocket(offer: pocketaddon.Offer) -> bool:
    """Download and install the newer Onion Pocket; it runs from the next start (the
    running copy is left alone, so a phone using it isn't cut off). Off the UI
    thread; True when it's in."""
    info = pocketaddon.get(offer=offer)
    if info is not None:
        log.info("Onion Pocket %s was installed by itself", info.version)
    return info is not None
