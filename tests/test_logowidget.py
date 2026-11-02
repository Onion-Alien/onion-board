from soundboard.ui.bun.logowidget import LogoWidget


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


def test_at_rest_it_only_runs_for_the_sheen(qapp):
    """Nothing playing: between two sheens nothing moves, so the timer stops until the
    next one (never a slower pace: that juddered). A sound wakes it at once."""
    from soundboard.ui.bun import logowidget
    w = LogoWidget()
    w._timer.start(logowidget.FAST_MS)
    w._t0 = logowidget.time.monotonic() - logowidget.SHEEN_TIME / 2   # mid-sheen
    w._step()
    assert w._timer.isActive() and w._timer.interval() == logowidget.FAST_MS
    w._t0 = logowidget.time.monotonic() - logowidget.SHEEN_TIME - 0.5   # between sheens
    w._step()
    assert not w._timer.isActive() and w._wake.isActive()
    assert w._wake.remainingTime() <= (logowidget.SHEEN_PERIOD - logowidget.SHEEN_TIME) * 1000
    w.set_level(0.0005)   # a fading tail below the meters' floor: still resting
    assert w._wake.isActive()
    w.set_level(0.4)      # a sound
    assert w._timer.isActive() and not w._wake.isActive()
    for _ in range(10):
        w._step()
    assert w._timer.isActive() and w.life > 0   # breathing with it
    w._pause()


def test_glow_icon_is_the_plain_icon_at_rest_and_glows_warm_with_sound(qapp):
    from soundboard.ui.kit import theme
    from soundboard.ui.bun.logowidget import glow_icon
    rest = glow_icon(*theme.BRAND, 0.0).pixmap(32).toImage()
    loud = glow_icon(*theme.BRAND, 1.0).pixmap(32).toImage()
    assert glow_icon(*theme.BRAND, 1.0) is glow_icon(*theme.BRAND, 1.0)   # cached
    edge_rest, edge_loud = rest.pixelColor(2, 16), loud.pixelColor(2, 16)
    assert edge_rest.blue() > edge_rest.red()     # at rest: the purple tile reaches the edge
    assert edge_loud.alpha() > 0 and edge_loud.red() > edge_loud.blue()   # loud: a warm halo


from test_mainwindow import window  # noqa: E402,F401  (the real MainWindow fixture)


def test_taskbar_and_tray_icons_stay_still_while_sound_plays(window, monkeypatch):  # noqa: F811
    """Only the header logo glows: swapping the window / tray icon made Windows redraw
    the taskbar button, which kept dropping and redrawing the onion's layers."""
    window.show()
    swaps = []
    monkeypatch.setattr(window, "setWindowIcon", lambda ic: swaps.append(ic))
    for _ in range(5):
        window.engine.level_play = 0.9
        window.tickctl.tick()
    assert not swaps
