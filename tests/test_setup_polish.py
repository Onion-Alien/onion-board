"""Setup tab polish: the review's layout and wording defects stay fixed."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401

from soundboard import directmic as dm
from soundboard import engine as eng


def pump():
    for _ in range(4):
        QApplication.processEvents()


class _Stream:
    def stop(self):
        pass
    close = stop


def _mic_works(w, monkeypatch):
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    monkeypatch.setattr(w, "_direct_not_running", lambda: False)
    monkeypatch.setattr(w.engine, "main_stream", _Stream())
    w.cfg.route = "mic"
    w.cfg.main_device = None
    w.cfg.mic_device = "Microphone (Example Gaming Headset)"


def test_cable_not_installed_says_it_once(window, monkeypatch):  # noqa: F811
    """The cable is picked but not installed: Devices says "setup needed" once, never
    "Nothing picked" (the cable is picked) under it."""
    w = window
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    w.cfg.route = "cable"
    w.cfg.main_device = None
    w.routectl._show_route()
    w._update_status()
    assert w.routectl._main_name() is None
    assert "Nothing picked" not in w.setup_hint.text()
    assert w.setup_hint.isHidden()   # no empty line's gap either
    assert w.setup_state == "missing"
    # nothing picked at all (another device, gone): still said
    w.cfg.route = "device"
    w._update_status()
    assert not w.setup_hint.isHidden()


def test_working_mic_card_is_one_line_with_tips_behind_info(window, monkeypatch):  # noqa: F811
    """Straight into the mic works: one status line and no step; the
    noise-suppression how-to is behind the card's ⓘ, not a paragraph."""
    w = window
    _mic_works(w, monkeypatch)
    w.routectl._show_route()
    w._update_status()
    assert w.mic_line.text() == "Your sounds go into your mic"
    assert w.step_lbl.isHidden() and w.mic_reason.isHidden()
    b = w.btn_mictips
    assert not b.isHidden()
    assert b.toolTip() and b.accessibleName()
    shown = []
    monkeypatch.setattr(w, "_show_help", lambda box, beside: shown.append((box, beside)))
    b.click()
    box, beside = shown[0]
    assert "Noise Suppression" in box.body.text() and beside is b
    assert box.body.textFormat() == Qt.TextFormat.RichText   # bold, not "<b>" shown
    w.cfg.route = "off"   # not on the mic: no mic tips
    w._update_status()
    assert b.isHidden()


def test_device_boxes_line_up(window, monkeypatch):  # noqa: F811
    """My headphones, My mic and Send my sounds to end at the same right edge."""
    w = window
    _mic_works(w, monkeypatch)
    w.show()
    w.tabs.setCurrentWidget(w.setup_page)
    for size in ((1180, 720), (800, 600)):
        w.resize(*size)
        pump()
        rights = {cb.geometry().right() for cb in (w.cb_mon, w.cb_mic, w.cb_route)}
        assert len(rights) == 1, (size, rights)


def test_mode_hint_has_the_cards_gap(window):  # noqa: F811
    """Who's listening: the picked mode's line isn't flush under the mode buttons."""
    w = window
    w.show()
    w.tabs.setCurrentWidget(w.setup_page)
    w.resize(1180, 720)
    pump()
    p = w.dest_panel
    bottom = max(b.geometry().bottom() for b in p.buttons.values())
    assert p.now.geometry().top() - bottom - 1 >= 12


def test_working_mic_card_offers_reinstall_and_remove(window, monkeypatch):  # noqa: F811
    """Working: the status box has the mic effect's Reinstall and Remove (Settings'
    recovery, same are-you-sure box); not on the mic, they go."""
    from PySide6.QtWidgets import QDialog, QPushButton

    from soundboard.ui import audiorecovery
    w = window
    _mic_works(w, monkeypatch)
    w.routectl._show_route()
    w._update_status()
    assert not w.btn_micredo.isHidden() and not w.btn_micoff.isHidden()
    ran = []
    rec = audiorecovery.recovery_of(w)
    monkeypatch.setattr(rec, "start", lambda a, t=None, say_done=False:
                        ran.append((a, t, say_done)) or True)
    w.btn_micoff.click()
    pump()
    box = next(d for d in w.findChildren(QDialog) if d.isVisible())
    go = next(b for b in box.findChildren(QPushButton) if b.text() == "Remove mic effect")
    go.click()
    pump()
    assert ran == [("remove", None, True)] and not box.isVisible()
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    w._update_status()
    assert w.btn_micredo.isHidden() and w.btn_micoff.isHidden()
