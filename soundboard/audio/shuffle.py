"""The "play a random sound" hotkey: a shuffle bag per category, so every sound comes
up once before any repeats, and never the same one twice in a row."""
from __future__ import annotations

import random


class ShuffleBag:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.bags: dict[str, list[str]] = {}   # category ("" = all) -> ids still to come
        self.last: dict[str, str] = {}

    def next(self, key: str, pool: list[str]) -> str | None:
        """The next id for `key` out of `pool` (the ids that can play right now)."""
        if not pool:
            return None
        live = set(pool)
        bag = [s for s in self.bags.get(key, []) if s in live]
        if not bag:
            bag = list(pool)
            self.rng.shuffle(bag)
            if len(bag) > 1 and bag[-1] == self.last.get(key):
                bag[0], bag[-1] = bag[-1], bag[0]   # the bag pops from the end
        sid = bag.pop()
        self.bags[key] = bag
        self.last[key] = sid
        return sid

    def forget(self, key: str):
        self.bags.pop(key, None)
        self.last.pop(key, None)
