from soundboard.ui.logowidget import LogoWidget


def test_idle_paints_without_embers(qapp):
    w = LogoWidget()
    for _ in range(30):
        w.advance(0.033)
    assert not w.embers
    assert not w.grab().isNull()


def test_sound_flares_and_throws_embers_then_settles(qapp):
    w = LogoWidget()
    w.set_level(1.0)
    for _ in range(60):
        w.advance(0.033)
    assert w.level > 0.9
    assert w.embers and len(w.embers) <= 16
    w.grab()
    w.set_level(0.0)
    for _ in range(200):
        w.advance(0.033)
    assert w.level < 0.05
    assert not w.embers


def test_idle_slows_the_timer_and_a_sound_speeds_it_up(qapp, monkeypatch):
    from soundboard.ui import logowidget
    w = LogoWidget()
    w._timer.start(logowidget.FAST_MS)
    w._t0 = logowidget.time.monotonic() - logowidget.SHEEN_TIME - 0.5   # between sheens
    w._step()
    assert w._timer.interval() == logowidget.IDLE_MS
    w.set_level(0.8)
    assert w._timer.interval() == logowidget.FAST_MS
    w._timer.stop()
