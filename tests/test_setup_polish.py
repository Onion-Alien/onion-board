"""Setup tab polish: the review's layout and wording defects stay fixed."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401
from conftest import said

from soundboard.mic import directmic as dm
from soundboard.audio import engine as eng
from soundboard.voicefx import cleanmic


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
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    monkeypatch.setattr(w.engine, "main_stream", _Stream())
    w.cfg.route = "mic"
    w.cfg.main_device = None
    w.cfg.mic_device = "Microphone (Example Gaming Headset)"


def test_voice_only_appearing_fits_the_strip_again(window, monkeypatch, qapp):  # noqa: F811
    """The effect goes while the app is open: no resize, but the strip got wider."""
    w = window
    _mic_works(w, monkeypatch)
    monkeypatch.setattr(w.engine, "mic_stream", _Stream())
    w.resize(1180, 650)
    w.show()
    w.setctl.open_settings("audio")
    w.routectl._show_route()
    w.statusctl._update_status()
    pump()
    w.fitctl._refit()
    pump()
    assert w.voice_only.isHidden()
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    w.routectl._show_route()
    w.statusctl._update_status()
    pump()
    assert not w.voice_only.isHidden()
    assert w.voice_only.width() >= w.voice_only.sizeHint().width()
    assert w.btn_check.width() >= w.btn_check.sizeHint().width()


def test_voice_only_keeps_the_strip_whole_and_gives_it_back(window, monkeypatch):  # noqa: F811
    """The chip is only a little too wide at a normal window size: the % boxes make room, not
    two of the three groups, and all of it is back when the chip goes, with no resize."""
    w = window
    _mic_works(w, monkeypatch)
    monkeypatch.setattr(w.engine, "mic_stream", _Stream())
    w.resize(1900, 760)
    w.show()
    w.routectl._show_route()
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    w.statusctl._update_status()
    pump()
    assert not w.voice_only.isHidden()
    for width in range(1900, 700, -20):   # (this font's widths: find where the boxes go)
        w.resize(width, 760)
        pump()
        if not w.vol_mic.spin.isVisibleTo(w):
            break
    else:
        raise AssertionError("the % boxes never made room")
    assert not w._mixer_one and all(g[-1].isVisibleTo(w) for g in w._decks)

    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    w.statusctl._update_status()
    pump()
    assert w.voice_only.isHidden()
    assert not w._mixer_one and w.vol_mic.spin.isVisibleTo(w) and w.vol_mon.spin.isVisibleTo(w)

    # narrower, with the chip: past what the boxes can give, the groups go as ever
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    w.statusctl._update_status()
    pump()
    whole_at = w.width()
    for width in range(whole_at, 700, -20):
        w.resize(width, 760)
        pump()
        assert w.mixer.width() >= w.mixer.minimumSizeHint().width()
        assert not w.fitctl.is_mini()
        if not w._mixer_one:
            whole_at = width
    assert w._mixer_one

    # and wider again: back as soon as they fit, not only at the width that took the boxes
    for width in range(w.width(), whole_at + 20, 20):
        w.resize(width, 760)
        pump()
    assert w.width() >= whole_at and not w._mixer_one


def test_mic_box_with_no_mics_is_as_wide_as_its_words(window):  # noqa: F811
    """With no items only the placeholder is left to size the box: "Pick your m" on a fresh
    window, and a saved mic that isn't plugged in cut off the same way."""
    w = window
    box = w.cb_mic
    w.routectl._fill_combo(box, [], "Mic")
    box.sizeHint()   # (Qt keeps this: the next text has to make it measure again)
    long_name = "Microphone (Example Gaming Headset With A Long Name)"
    for current, text in ((None, "Pick your mic"), (long_name, long_name)):
        w.routectl._fill_combo(box, [], current)
        assert box.placeholderText() == text
        assert box.sizeHint().width() > box.fontMetrics().horizontalAdvance(text)


def test_cable_not_installed_says_it_once(window, monkeypatch):  # noqa: F811
    """The cable is picked but not installed: Devices says "setup needed" once, never
    "Nothing picked" (the cable is picked) under it."""
    w = window
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    w.cfg.route = "cable"
    w.cfg.main_device = None
    w.routectl._show_route()
    w.statusctl._update_status()
    assert w.routectl._main_name() is None
    assert "Nothing picked" not in w.setup_hint.text()
    assert w.setup_hint.isHidden()   # no empty line's gap either
    assert w.statusctl.setup_state == "missing"
    # nothing picked at all (another device, gone): still said
    w.cfg.route = "device"
    w.statusctl._update_status()
    assert not w.setup_hint.isHidden()


def test_working_mic_card_is_one_line_with_tips_behind_info(window, monkeypatch):  # noqa: F811
    """Straight into the mic works: one status line and no step; the
    noise-suppression how-to is behind the card's ⓘ, not a paragraph."""
    w = window
    _mic_works(w, monkeypatch)
    w.routectl._show_route()
    w.statusctl._update_status()
    assert w.mic_line.text() == "Your sounds go into your mic"
    assert w.mic_reason.isHidden()
    b = w.btn_mictips
    assert not b.isHidden()
    assert b.toolTip() and b.accessibleName()
    shown = []
    monkeypatch.setattr(w.tipctl, "_show_help", lambda box, beside: shown.append((box, beside)))
    b.click()
    box, beside = shown[0]
    assert "Noise Suppression" in box.body.text() and beside is b
    assert box.body.textFormat() == Qt.TextFormat.RichText   # bold, not "<b>" shown
    assert ("Clean mic" in box.body.text()) == cleanmic.available()   # does it instead
    w.cfg.route = "off"   # not on the mic: no mic tips
    w.statusctl._update_status()
    assert b.isHidden()




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

    from soundboard.ui.setup import audiorecovery
    w = window
    _mic_works(w, monkeypatch)
    w.routectl._show_route()
    w.statusctl._update_status()
    assert not w.btn_micredo.isHidden() and not w.btn_micoff.isHidden()
    assert w.btn_michange.isHidden()   # (the mic's box is right above)
    ran = []
    rec = audiorecovery.recovery_of(w)
    monkeypatch.setattr(rec, "start", lambda a, t=None, say_done=False:
                        ran.append((a, t, say_done)) or True)
    w.btn_micoff.click()
    pump()
    box = next(d for d in w.findChildren(QDialog) if d.isVisible())
    go = next(b for b in box.findChildren(QPushButton) if b.text() == "Remove driver")
    go.click()
    pump()
    assert ran == [("remove", None, True)] and not box.isVisible()
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    w.statusctl._update_status()
    assert w.btn_micredo.isHidden() and w.btn_micoff.isHidden()
    assert w.btn_michange.isHidden()




def test_unplugged_headphones_and_mic_stay_said_in_their_cards(window, monkeypatch):  # noqa: F811
    """The headphones or mic picked won't open (unplugged): the toast about it fades, so
    the card each is picked in says so until it's back, and stops once it is."""
    w = window
    e = w.engine
    w._attaching, w._settle_until = False, 0.0
    monkeypatch.setitem(e.names, "mon", "Headphones (Example Headset)")
    monkeypatch.setitem(e.names, "mic", "Headset Microphone (Example Headset)")
    monkeypatch.setattr(e, "mon_stream", None)
    monkeypatch.setattr(e, "mic_stream", None)
    monkeypatch.setitem(e.errors, "mon", "Device unavailable")
    monkeypatch.setitem(e.errors, "mic", "Device unavailable")
    w.statusctl._update_status()
    assert "Can't open <b>Headphones (Example Headset)</b> (My headphones)" in w.dev_hint.text()
    assert "Can't open <b>Headset Microphone (Example Headset)</b> (My mic)" in w.setup_hint.text()
    assert not w.setup_hint.isHidden() and not w.dev_hint.isHidden()
    # the toast says it in the same words, not PortAudio's error
    toast = said(w)
    assert "(My headphones). Plugged in?" in toast and "(My mic)" in toast
    assert "Device unavailable" not in toast and "span" not in toast
    # back: the lines go
    monkeypatch.setattr(e, "mon_stream", _Stream())
    e.errors.pop("mon")
    w.statusctl._update_status()
    assert w.dev_hint.isHidden() and "(My mic)" in w.setup_hint.text()


def test_a_working_mic_without_the_sounds_in_it_says_both(window, monkeypatch):  # noqa: F811
    """The mic works (open, its level moving beside its box) but the sounds aren't in it
    yet: what's missing is named as the sounds, never "Your mic: Not set up" (which read
    as a broken mic while the meter moved)."""
    w = window
    _mic_works(w, monkeypatch)
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    monkeypatch.setattr(w.engine, "mic_stream", _Stream())
    w.routectl._show_route()
    w.statusctl._update_status()
    assert not w.card_meter.isHidden()
    assert w.mic_line.text() == "Your sounds aren't in your mic yet"
    assert "your voice, but not your sounds" in w.mic_reason.text()
    assert w.mic_pill.text() == "1 step left"
    assert not w.voice_only.isHidden()   # by "What others hear": your voice alone
    assert "Not set up" not in (w.mic_pill.text(), w.mic_line.text())
    # no mic open: no level, and nothing others hear
    monkeypatch.setattr(w.engine, "mic_stream", None)
    w.statusctl._update_status()
    assert w.card_meter.isHidden() and w.voice_only.isHidden()
    # working: the one green status says it all
    monkeypatch.setattr(w.engine, "mic_stream", _Stream())
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    w.statusctl._update_status()
    assert w.voice_only.isHidden()
    # not on the mic at all
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    w.cfg.route = "off"
    w.statusctl._update_status()
    assert w.voice_only.isHidden()


def test_no_mic_picked_is_never_green(window, monkeypatch):  # noqa: F811
    """No mic picked: the card says so and offers only to pick one, never "Your sounds go
    into your mic" with Reinstall and Remove, and never a "(none)" to get stuck on."""
    w = window
    _mic_works(w, monkeypatch)
    w.routectl._fill_combo(w.cb_mic, ["Microphone (Example Gaming Headset)"], None)
    w.cfg.mic_device = None
    w.routectl._show_route()
    w.statusctl._update_status()
    assert w.mic_line.text() == "No mic picked"
    assert w.mic_pill.text() == "No mic"
    assert "(none)" not in w.mic_reason.text() and "Pick your mic" in w.mic_reason.text()
    assert w.btn_michange.text() == "Pick my mic" and not w.btn_michange.isHidden()
    opened = []
    monkeypatch.setattr(w.cb_mic, "showPopup", lambda: opened.append(True))
    w.btn_michange.click()   # the card's own mic box, opened
    assert opened
    assert w.btn_micredo.isHidden() and w.btn_micoff.isHidden()
    # a mic picked again: back to working, with its buttons
    w.cfg.mic_device = "Microphone (Example Gaming Headset)"
    w.statusctl._update_status()
    assert w.mic_line.text() == "Your sounds go into your mic"
    assert w.btn_michange.isHidden() and not w.btn_micredo.isHidden()
