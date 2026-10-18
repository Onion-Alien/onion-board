"""*Enjoying Onion Board?*: a one-off thumbs up or down for people who use the app a lot.

It's due once the app has been open DAY_S or more on DAYS_NEEDED different days (not
in a row). usage.open_tick adds the open time, so it only counts while the usage count
is on: with it off, the answer would go nowhere, so it's never asked. Asked once, ever:
it's marked done the moment it shows, whether they answer, close it or quit. The bar
itself is ui/window/enjoycontrol.py; the answers go out with usage.survey.
Config: enjoy_days {"YYYY-MM-DD": seconds open} and enjoy_state ("" / "done")."""
from __future__ import annotations

import time

DAY_S = 2 * 3600        # a day counts once the app was open this long on it
DAYS_NEEDED = 3         # ...on this many different days
KEEP_DAYS = 30          # enjoy_days keeps this many dates, the newest


def today(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))


def add(cfg, seconds: float, now: float | None = None) -> None:
    """Add `seconds` open to today's total (usage.open_tick)."""
    days = cfg.enjoy_days if isinstance(cfg.enjoy_days, dict) else {}
    if cfg.enjoy_state == "done" or seconds <= 0:
        return
    day = today(now)
    try:
        had = max(0.0, float(days.get(day, 0) or 0))
    except (TypeError, ValueError):
        had = 0.0
    days[day] = had + seconds
    cfg.enjoy_days = dict(sorted(days.items())[-KEEP_DAYS:])


def busy_days(cfg) -> int:
    """How many days the app was open DAY_S or more."""
    days = cfg.enjoy_days if isinstance(cfg.enjoy_days, dict) else {}
    n = 0
    for v in days.values():
        try:
            n += float(v) >= DAY_S
        except (TypeError, ValueError):
            pass
    return n


def due(cfg) -> bool:
    """Time to ask?"""
    return cfg.enjoy_state != "done" and busy_days(cfg) >= DAYS_NEEDED


def asked(cfg) -> None:
    """It showed: never again."""
    cfg.enjoy_state = "done"
