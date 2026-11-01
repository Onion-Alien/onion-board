"""Edit sound's player (ui/sounds/editplayer.py): the board's player bar in the window,
kept in step with it both ways, so a song can be paused or moved in a window that
covers the board."""
from soundboard.ui.kit.widgets import fmt_pos
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def _open(w, sid="s0"):
    d = w.editctl.edit(sid)
    return d, d.player


def test_the_player_is_over_the_save_row_in_advanced_only(window):  # noqa: F811
    d, p = _open(window)
    d.set_advanced(False)
    assert p is not None and not p.isVisibleTo(d)   # Simple: no player
    lay = d._lay
    assert lay.indexOf(p) == lay.indexOf(d._brow) - 1
    assert window.editctl.players() == [p]
    d.switch.advanced.click()
    assert p.isVisibleTo(d)
    d.adv.switch.simple.click()
    assert not p.isVisibleTo(d)
    d.reject()
    assert window.editctl.players() == []   # a closed one isn't set any more


def test_it_follows_the_boards_player(window):  # noqa: F811
    w = window
    d, p = _open(w)
    w.playctl.select("s1")
    m = w.meta("s1")
    assert p.name.text() == m.name or p.name.text().endswith("…")
    playing = {"s1": (0.5, False)}
    w.transctl._update_transport(playing)
    assert p.seek.value() == 500 and p.btn_pp.isEnabled()
    assert p.time.text() == fmt_pos(0.5 * m.duration, m.duration)
    w.playctl._update_chips(playing)
    assert list(p._chips) == ["s1"] and not p.chips_row.isHidden()
    assert p._chips["s1"].property("sel") == "true"
    w.playctl._update_chips({})
    assert p.chips_row.isHidden()
    d.reject()


def test_volume_and_hear_it_myself_go_both_ways(window):  # noqa: F811
    w = window
    d, p = _open(w)
    p.vol.spin.setValue(40)                 # in the window: the board's, and saved
    assert w.vol_sound.spin.value() == 40 and abs(w.cfg.sound_vol - 0.4) < 1e-6
    w.vol_sound.spin.setValue(150)          # on the board: the window's too
    assert p.vol.spin.value() == 150 and p.vol.slider.value() == 150
    before = w.chk_monitor.isChecked()
    p.chk_monitor.setChecked(not before)
    assert w.chk_monitor.isChecked() is (not before) and w.cfg.monitor_sounds is (not before)
    w.chk_monitor.setChecked(before)
    assert p.chk_monitor.isChecked() is before
    d.reject()


def test_a_reopened_window_shows_the_player_as_it_is_now(window):  # noqa: F811
    w = window
    d, p = _open(w)
    d.reject()
    w.vol_sound.spin.setValue(70)
    w.playctl.select("s0")
    d2, p2 = _open(w, "s1")                 # the closed window, reused
    assert p2.vol.spin.value() == 70
    assert w.meta("s0").name.startswith(p2.name.text().rstrip("…"))
    d2.reject()
