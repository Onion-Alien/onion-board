"""Discord's card on the Setup tab: what it shows, and what its switches do."""
from __future__ import annotations

import threading

import pytest
from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401  (fixture)

from soundboard.mic import discordcfg, discordtalk
from soundboard.ui.setup import chatguide, discordcard

FILTERS_ON = discordcfg.Settings("Discord", "CUSTOM", True, False, True, True, False, False,
                                 "default", 1.0)
FILTERS_OFF = discordcfg.Settings("Discord", "CUSTOM", False, False, False, False, False, False,
                                  "default", 1.0)


class Clean:
    """The Voice tab's Clean mic, as far as the card cares."""
    ok = True

    def __init__(self):
        self.on = False
        self.live_changed = _Signal()

    def is_on(self):
        return self.on

    def set_on(self, on):
        self.on = on


class _Signal:
    def connect(self, _fn):
        pass


def pump(until=lambda: True):
    for _ in range(400):
        QApplication.processEvents()
        if until():
            return
        threading.Event().wait(0.005)
    raise AssertionError("never happened")


@pytest.fixture
def card(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(discordcfg, "read", lambda *a: [])
    monkeypatch.setattr(chatguide, "on_headphones", lambda mw: True)
    monkeypatch.setattr(chatguide, "raw_skips", lambda mw: True)
    monkeypatch.setattr(chatguide, "clean_mic", lambda mw: None)
    c = window.discord_card
    c.set_wanted(True)
    return c


def show(window, settings):  # noqa: F811
    window.alertctl.set_discord_found([settings] if settings else [])


def test_no_discord_no_card_and_your_mic_takes_the_whole_width(window, card):  # noqa: F811
    show(window, None)
    assert not card.shown and card.frame.isHidden()
    assert window._setup_rows[0] == (window._setup_cards[0],)
    show(window, FILTERS_OFF)
    assert card.shown and not card.frame.isHidden()
    assert window._setup_rows[0] == (window._setup_cards[0], card.frame)
    card.set_wanted(False)   # no way out for your sounds yet: nothing to set in Discord
    assert not card.shown and card.frame.isHidden()


def test_the_switch_says_how_discord_is_set(window, card):  # noqa: F811
    show(window, FILTERS_OFF)
    assert card.mode.isChecked() and card.pill.text() == "Sounds get through"
    show(window, FILTERS_ON)   # changed in Discord itself
    assert not card.mode.isChecked() and card.pill.text() == "Sounds may cut out"


def test_setup_stacks_before_the_card_gets_cut(window, card):  # noqa: F811
    show(window, FILTERS_OFF)
    assert window.fitctl._setup_need() >= 2 * card.MIN_W + window._setup_cols.spacing()


def test_mode_on_runs_the_set_up_with_no_box(window, card, monkeypatch):  # noqa: F811
    show(window, FILTERS_ON)
    calls = []

    def fake(mw, parent=None, then=None, quiet=False, after=None):
        calls.append(quiet)
        assert card.switching and card.pill.text() == "Switching…"
        assert card.mode.isChecked()   # shows where it's heading, not the old state
        show(window, FILTERS_OFF)
        after()
    monkeypatch.setattr(chatguide, "set_up_discord", fake)
    card.mode.click()
    assert calls == [True] and not card.switching and card.mode.isChecked()


def test_a_click_while_switching_does_nothing(window, card, monkeypatch):  # noqa: F811
    show(window, FILTERS_ON)
    card.switching = True
    monkeypatch.setattr(chatguide, "set_up_discord",
                        lambda *a, **k: pytest.fail("started a second one"))
    card.mode.click()
    assert not card.mode.isChecked()   # it stays what Discord is set to
    card.switching = False


def test_mode_off_with_discord_closed_turns_the_filters_back_on(window, card, monkeypatch):  # noqa: F811
    show(window, FILTERS_OFF)
    restored = []
    monkeypatch.setattr(discordtalk, "to_restore", lambda saved: ["discord"])
    monkeypatch.setattr(discordtalk, "running_clients", set)
    monkeypatch.setattr(discordtalk, "restore", lambda *a, **k: restored.append(k) or [])
    card.mode.click()
    pump(lambda: restored and not card.switching)
    assert restored[0]["only"] == {"discord"} and restored[0]["always"]
    assert window.cfg.discord_off   # on purpose: no Fix Discord bar about it


def test_mode_off_with_discord_open_asks_first(window, card, monkeypatch):  # noqa: F811
    show(window, FILTERS_OFF)
    asked = []
    monkeypatch.setattr(discordtalk, "to_restore", lambda saved: ["discord"])
    monkeypatch.setattr(discordtalk, "running_clients", lambda: {"discord"})
    monkeypatch.setattr(discordtalk, "restore", lambda *a, **k: pytest.fail("Discord is open"))
    monkeypatch.setattr(discordcard.DiscordCard, "_on_asked",
                        lambda self, names: (asked.append(names), self._switched()))
    card._asked.disconnect()
    card._asked.connect(lambda names: discordcard.DiscordCard._on_asked(card, names))
    card.mode.click()
    pump(lambda: asked and not card.switching)
    assert asked == [["discord"]] and not window.cfg.discord_off


def test_no_fix_discord_bar_once_switched_off_on_purpose(window, card):  # noqa: F811
    show(window, FILTERS_ON)
    assert (window.alertctl._urgent_now() or ("", "", ""))[0].startswith("discord ")
    window.cfg.discord_off = True
    assert not (window.alertctl._urgent_now() or ("", "", ""))[0].startswith("discord ")
    show(window, FILTERS_OFF)   # on again: the bar may speak up next time
    assert not window.cfg.discord_off


def test_clean_mic_row(window, card, monkeypatch):  # noqa: F811
    show(window, FILTERS_OFF)
    assert card.clean_row.isHidden()   # no Voice tab or no cleaner: no row
    clean = Clean()
    monkeypatch.setattr(chatguide, "clean_mic", lambda mw: clean)
    card.refresh()
    assert not card.clean_row.isHidden() and "Recommended" in card.clean_why.text()
    card.clean.click()
    assert clean.on and "Recommended" not in card.clean_why.text()
    clean.on = False
    show(window, FILTERS_ON)   # Discord's filter is doing the job
    assert "Recommended" not in card.clean_why.text()


def test_the_tick_is_the_close_setting(window, card):  # noqa: F811
    show(window, FILTERS_OFF)
    was = window.cfg.discord_restore
    card.chk_off.click()
    assert window.cfg.discord_restore is (not was)


def test_an_answer_before_the_card_is_built_waits_for_it(window, card):  # noqa: F811
    """A slow start: Discord's first check answers before the Setup page (and this card)
    is made. It must not throw, and the card shows it once it's there."""
    del window.discord_card
    try:
        window.alertctl._on_discord(([FILTERS_OFF], ("a",)))
        assert window.alertctl.discord_found == [FILTERS_OFF]
    finally:
        window.discord_card = card
    card.refresh()
    assert card.shown and not card.frame.isHidden()
