"""The random-sound hotkeys: the shuffle bag, and the window's global / per-category keys."""
import pytest
import random

import numpy as np

from soundboard.library import SoundMeta
from soundboard.shuffle import ShuffleBag
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_bag_plays_everything_before_repeating_and_never_twice_in_a_row():
    bag = ShuffleBag(random.Random(1))
    pool = list("abcde")
    seen = [bag.next("", pool) for _ in range(50)]
    for i in range(0, 50, 5):
        assert sorted(seen[i:i + 5]) == pool
    assert all(x != y for x, y in zip(seen, seen[1:]))


def test_bag_follows_the_pool_and_handles_tiny_ones():
    bag = ShuffleBag(random.Random(2))
    assert bag.next("", []) is None
    assert [bag.next("", ["a"]) for _ in range(3)] == ["a", "a", "a"]
    bag.next("k", list("abc"))
    assert all(bag.next("k", ["c"]) == "c" for _ in range(3))   # removed ones never come


def test_random_hotkeys_pick_from_the_right_category(window):
    w = window
    for i, n in enumerate(("Meme1", "Meme2")):
        m = SoundMeta(id=f"m{i}", name=n, file=f"{n}.wav", tags=["Memes"])
        w.cfg.sounds.append(m)
        w.audio[m.id] = np.zeros((480, 2), np.float32)
    w.cfg.categories.append("Memes")
    for sid in ("s0", "s1"):
        w.audio[sid] = np.zeros((480, 2), np.float32)
    w._rebuild_pads()
    played = []
    w.play = played.append
    for _ in range(6):
        w.on_hotkey("__random__:Memes")
    assert set(played) == {"m0", "m1"}
    played.clear()
    w.set_category("Memes")
    w.on_hotkey("__random__")                     # the global one follows the view
    assert played[0] in ("m0", "m1")
    w.set_category("")
    assert {w.play_random() for _ in range(8)} >= {"s0", "s1"}


def test_category_hotkey_is_unique_and_follows_renames(window, monkeypatch):
    w = window
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    w.new_category(name="Memes")
    w.meta("s0").hotkey = "ctrl+1"
    w.set_category_hotkey("Memes", "ctrl+1")
    assert w.meta("s0").hotkey == "" and w.cfg.category_hotkeys == {"Memes": "ctrl+1"}
    assert registered[-1]["ctrl+1"] == "__random__:Memes"
    w.rename_category("Memes", "Funny")
    assert w.cfg.category_hotkeys == {"Funny": "ctrl+1"}
    w.set_global_hotkey("stop_hotkey", "ctrl+1")   # taken for something else
    assert w.cfg.category_hotkeys == {}
    w.set_category_hotkey("Funny", "ctrl+2")
    w.delete_category("Funny")
    assert w.cfg.category_hotkeys == {}
