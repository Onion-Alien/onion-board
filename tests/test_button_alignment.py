"""Buttons side by side line up: one height in a row, the icon's gap before the words,
and no row of its own for one button."""
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401

from soundboard import appaudio
from soundboard import engine as eng
from soundboard.appaudio import App
from soundboard.ui.tabcontrol import TAB_INDEX


def pump():
    for _ in range(6):
        QApplication.processEvents()


def has_gap(btn) -> bool:
    """The icon was given room before the words (icons.set_icon's TEXT_GAP)."""
    return btn.iconSize().width() > btn.iconSize().height()


class _Capture:
    error = None
    ready = running = True

    def __init__(self, *a, **k):
        pass

    def start(self, timeout=0, wait=True):
        return True

    def stop(self, wait=True):
        pass

    def join(self, timeout=3.0):
        pass


def test_setup_ways_share_one_height_and_check_again_stays_with_them(window, monkeypatch):  # noqa: F811
    w = window
    w.cfg.route = "cable"   # no cable: the mic first (filled), then the cable's ways
    monkeypatch.setattr(w.statusctl, "virtual_mic", None)
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    w.resize(1400, 900)
    w.show()
    w.tabs.setCurrentIndex(TAB_INDEX["setup"])
    w.statusctl._update_flow()
    pump()
    ways = (w.btn_attach, w.btn_install, w.btn_guide, w.btn_rescan)
    assert all(b.isVisible() for b in ways)
    assert w.btn_attach.objectName() == "primary"
    assert len({b.height() for b in ways}) == 1, [b.height() for b in ways]
    # check again is the last of the ways, in their row, not on a line of its own
    assert w._ways.indexOf(w.btn_rescan) > w._ways.indexOf(w.btn_guide) >= 0
    assert w.btn_rescan.y() == w.btn_guide.y()
    assert "(no cable)" not in w.btn_attach.text()   # the tip says it


def test_radio_bar_buttons_line_up_and_keep_their_size_when_narrow(window):  # noqa: F811
    w = window
    w.resize(1400, 900)
    w.show()
    w.tabs.setCurrentIndex(TAB_INDEX["radio"])
    pump()
    r = w.radio
    assert (r.btn_rec.sizeHint().height() == r.btn_live.sizeHint().height()
            == r.btn_play.sizeHint().height())
    assert has_gap(r.btn_live)
    w.resize(800, 600)
    pump()
    # Now playing hidden: its room isn't shared out into Play / shuffle / Send (Play and
    # Send keep the room of their other word, Stop / Others hear it, and no more)
    for b in (r.btn_play, r.btn_random, r.btn_live):
        assert b.width() <= max(b.sizeHint().width(), b.minimumWidth()), \
            b.accessibleName() or b.text()


def test_radio_bar_buttons_stay_put_on_play_stop_and_send(window, monkeypatch):  # noqa: F811
    w = window
    w.resize(2000, 900)          # wide enough that Play keeps its word with any font
    w.show()
    w.tabs.setCurrentIndex(TAB_INDEX["radio"])
    pump()
    r = w.radio
    spots = lambda: [(b.x(), b.width()) for b in (r.btn_play, r.btn_random, r.btn_live,  # noqa: E731
                                                  r.btn_rec)]
    before = spots()
    monkeypatch.setattr(r.player, "station", SimpleNamespace(name="Some radio", uuid="u"))
    r._update_buttons()          # Play -> Stop
    r.btn_live.blockSignals(True)
    r.btn_live.setChecked(True)  # Send to others -> Others hear it
    r._label_live()
    pump()
    assert r.btn_play.text() == "Stop" and r.btn_live.text() == "Others hear it"
    assert spots() == before
    r.btn_live.setChecked(False)
    r._label_live()
    r.btn_live.blockSignals(False)
    monkeypatch.setattr(r.player, "station", None)
    r._update_buttons()
    pump()
    assert spots() == before


def test_app_card_send_and_record_line_up(window, monkeypatch):  # noqa: F811
    w = window
    music = App(100, "music.exe", r"C:\P\music.exe", "Music Thing", True, 0.3, ["Speakers"])
    monkeypatch.setattr(appaudio, "AppCapture", _Capture)
    monkeypatch.setattr(appaudio, "list_apps", lambda strict=False, **_: [music])
    w.resize(1400, 900)
    w.show()
    w.tabs.setCurrentIndex(TAB_INDEX["apps"])
    w.apps._on_apps([music])
    pump()
    row = w.apps.rows["music.exe"]
    assert row.btn_rec.sizeHint().height() == row.btn_send.sizeHint().height()
    row._tight = 0            # wide: "Send", with the icon's gap
    row._label_send()
    assert row.btn_send.text() and has_gap(row.btn_send)
    row._tight = len(row._TIGHTEN)   # narrow: the icon alone, no gap beside it
    row._label_send()
    assert not row.btn_send.text() and not has_gap(row.btn_send)
    assert (row.btn_forget.width(), row.btn_forget.height()) == (28, 28)


def test_get_onion_watch_icon_has_its_gap(window):  # noqa: F811
    w = window
    w.tabs.setCurrentIndex(TAB_INDEX["triggers"])
    pump()
    btn = getattr(w.triggers, "btn_get", None)
    if btn is None:   # the add-on is installed here: its own page, no Get button
        return
    assert has_gap(btn)
