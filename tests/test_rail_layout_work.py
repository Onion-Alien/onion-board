"""The rail's layout work stays small: the window's fit flips its compact step back and forth
on a switch into Setup and when it tries again what gave way, so each flip has to be cheap.
These count calls, never time."""
import pytest
from PySide6.QtWidgets import QWidget

from test_mainwindow import window  # noqa: F401

from soundboard.ui.kit import wheelguard
from soundboard.ui.window import sidebar as sb
from soundboard.ui.window.onaircard import Line, OutputBlock
from soundboard.ui.window.sidebar import SideRail

LINES = [Line("leaf", "Voice changer on", "ok", "", "voice", "voice"),
         Line("tor", "Through Tor", "ok", "", "privacy", "connection")]


def count(monkeypatch, cls, name) -> list:
    calls = []
    real = getattr(cls, name)

    def counted(self, *a, **k):
        calls.append(name)
        return real(self, *a, **k)
    monkeypatch.setattr(cls, name, counted)
    return calls


def shown(window, qapp, size=(1100, 620)):  # noqa: F811
    window.resize(*size)
    window.show()
    window.rail.set_open(True)
    window.rail.output.set_lines(LINES)
    window.tabs.setCurrentWidget(window.sounds_page)   # (it opens on Setup)
    qapp.processEvents()
    window.fitctl._refit()
    qapp.processEvents()


def geometry(rail) -> list:
    return [(c.objectName(), c.geometry().getRect(), c.isVisibleTo(rail))
            for c in rail.findChildren(QWidget)]


def test_a_cold_switch_into_setup_never_runs_the_whole_rail(window, qapp, monkeypatch):  # noqa: F811
    """A short window: every step undone and fitted again, which flips the compact step
    four times each way. A whole _apply each time took over a second on a slower PC."""
    shown(window, qapp)
    assert window.rail._compact
    apply, card = (count(monkeypatch, SideRail, "_apply"),
                   count(monkeypatch, SideRail, "refresh_output"))
    flips = count(monkeypatch, SideRail, "_apply_compact")
    for page in (window.setup_page, window.sounds_page):
        window.fitctl._fit.changes += 1   # (what's kept for each side no longer holds)
        window.tabs.setCurrentWidget(page)
        qapp.processEvents()
    assert flips, "the compact step wasn't flipped: this test no longer tests it"
    assert not apply and not card


def test_a_whole_rail_pass_follows_the_status_words_once(window, qapp, monkeypatch):  # noqa: F811
    """Each status button used to refresh the card by itself, on top of the pass's own."""
    shown(window, qapp)
    card = count(monkeypatch, SideRail, "refresh_output")
    window.rail._apply()
    assert len(card) == 2   # before the heights are judged, and after them


def test_a_whole_rail_pass_restyles_only_what_changed(window, qapp, monkeypatch):  # noqa: F811
    shown(window, qapp)
    rail = window.rail
    polished = []
    monkeypatch.setattr(wheelguard.AppStyle, "hooks", [polished.append])
    rail.compact(not rail._compact)   # (the padding: all of them, so hooks do reach them)
    assert rail.toggle in polished
    polished.clear()
    rail._apply()
    ours = [*rail.buttons, *rail.status, *rail.extras, rail.toggle]
    assert not [w for w in polished if any(w is o for o in ours)]


@pytest.mark.parametrize("state", ["open", "shut", "dragged"])
def test_a_flip_lays_out_as_a_whole_pass_would(window, qapp, state):  # noqa: F811
    """The cheap flip does only what the step changes: it ends where a whole pass does."""
    shown(window, qapp, (1200, 900))
    rail = window.rail
    if state == "shut":
        rail.set_open(False)
    elif state == "dragged":
        rail.drag_width(150)
    for tight in (True, False, True, False):   # (a first whole pass settles the card)
        rail.compact(tight)
        rail._apply()
        qapp.processEvents()
    for tight in (True, False, True):
        rail.compact(tight)
        qapp.processEvents()
        flipped = geometry(rail)
        rail._apply()
        qapp.processEvents()
        assert geometry(rail) == flipped, f"compact {tight}"


def test_the_card_measures_once_until_its_words_change(window, qapp, monkeypatch):  # noqa: F811
    shown(window, qapp)
    card = window.rail.output
    measured = count(monkeypatch, OutputBlock, "_measure")
    before = card.need(card.MIN_SCALE)
    for _ in range(5):
        assert card.need(card.MIN_SCALE) == before
    assert len(measured) <= 1
    measured.clear()
    # longer words: measured again, and they need more room
    sb.put(card.connection, "A much longer status line than it had before all this",
           "words", "tip")
    assert card.need(card.MIN_SCALE) > before
    assert measured
    measured.clear()
    wide = card.need(card.MIN_SCALE)
    card.set_lines([*LINES, Line("leaf", "Another line that is really very long indeed, yes",
                                 "", "", "", "")])
    assert card.need(card.MIN_SCALE) >= wide
    assert measured
