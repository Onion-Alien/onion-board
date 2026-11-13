"""*Enjoying Onion Board?*: a one-off thumbs up or down for people who really use the app.

Open time doesn't count: a day counts once they did DAY_ACTIONS or more things on it
(sounds played, plus features used: a voice, sounds added, a recording...).
usage.open_tick adds what's new since its last tick, so it only counts while the usage
count is on: with it off, the answer would go nowhere, so it's never asked. Once
DAYS_NEEDED earlier days count, it's asked at the next start on a later day, once,
ever: it's marked done the moment it shows, whether they answer, close it or quit. The
card itself is ui/window/enjoycontrol.py; the answers go out with usage.survey.
Config: enjoy_days {"YYYY-MM-DD": things done} and enjoy_state ("" / "done")."""
from __future__ import annotations

import time

DAY_ACTIONS = 10        # a day counts once they did this many things on it
DAYS_NEEDED = 2         # ...on this many days before today: asked on the next one
KEEP_DAYS = 30          # enjoy_days keeps this many dates, the newest

_seen: dict = {}        # the last totals add() was given, this run (never saved)


def today(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))


def _days(cfg) -> dict:
    return cfg.enjoy_days if isinstance(cfg.enjoy_days, dict) else {}


def add(cfg, plays: int, uses: int, now: float | None = None) -> None:
    """Today's things done += what's new in the running totals `plays` (sounds played,
    ever) and `uses` (features used, this run). The first call of a run only notes them."""
    last = dict(_seen)
    _seen.update(plays=plays, uses=uses)
    if cfg.enjoy_state == "done" or not last:
        return
    new = max(0, plays - last.get("plays", plays)) + max(0, uses - last.get("uses", uses))
    if not new:
        return
    days = _days(cfg)
    day = today(now)
    try:
        had = max(0, int(days.get(day, 0) or 0))
    except (TypeError, ValueError):
        had = 0
    days[day] = had + new
    cfg.enjoy_days = dict(sorted(days.items())[-KEEP_DAYS:])


def busy_days(cfg, now: float | None = None) -> int:
    """How many days before today they did DAY_ACTIONS or more things."""
    t = today(now)
    n = 0
    for day, v in _days(cfg).items():
        try:
            n += day < t and int(v) >= DAY_ACTIONS
        except (TypeError, ValueError):
            pass
    return n


def due(cfg, now: float | None = None) -> bool:
    """Time to ask (at a start)?"""
    return cfg.enjoy_state != "done" and busy_days(cfg, now) >= DAYS_NEEDED


def asked(cfg) -> None:
    """It showed: never again."""
    cfg.enjoy_state = "done"


def forget_run() -> None:
    """Tests: a fresh run."""
    _seen.clear()
