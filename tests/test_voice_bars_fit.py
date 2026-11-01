"""Several voices on (Clean mic, the voice changer, a computer voice): their bars pinned
under the voices must not take all the room on a smaller window. The bars go into their
cards instead (scrolling with the voices), and come back when the window grows."""
from PySide6.QtWidgets import QApplication

from soundboard.ui.window.tabcontrol import TAB_KEYS
from test_mainwindow import window  # noqa: F401  (the real MainWindow)


def _settle():
    for _ in range(10):
        QApplication.processEvents()


def test_three_voices_on_leave_the_voices_room(window, monkeypatch):  # noqa: F811
    w = window
    w.resize(1700, 1000)
    w.show()
    w.tabs.setCurrentIndex(TAB_KEYS.index("voice"))
    v = w.voice
    v.show_tab("fx")
    monkeypatch.setattr(v.clean, "ok", True)   # as if RNNoise were there
    monkeypatch.setattr(v.clean, "_apply", lambda: None)
    monkeypatch.setattr(v, "_show_problem", lambda why: None)   # no mic on a test PC
    v.fx._tile["Robot"].click()
    v.clean.set_on(True)
    b = v.speech.livevoice.b_live
    b.blockSignals(True)
    b.setChecked(True)
    b.blockSignals(False)
    v._update_bar()
    _settle()
    bars = [p.picked for k, p in v._barred() if k in ("clean", "fx", "speak")]
    assert all(p.isVisible() and p.property("pinned") for p in bars)   # room: pinned
    for size in ((1100, 800), (560, 900), (560, 700)):
        w.resize(*size)
        _settle()
        assert not w.fitctl.is_mini()
        assert v._scroll.viewport().height() >= 440, size   # two rows of voices and more
        assert not any(p.property("pinned") for p in bars), size   # in their cards
        assert w.mixer.isVisible(), size   # the bars give way before the mixer does
    w.resize(1700, 1000)
    _settle()
    assert all(p.isVisible() and p.property("pinned") for p in bars)
    # all off with their ✕: no room kept for bars that aren't there
    for key in ("clean", "fx", "speak"):
        v._bar_ctl[key][1].click()
    _settle()
    assert not any(p.isVisible() for p in bars)
    assert v._scroll.minimumHeight() == 0
