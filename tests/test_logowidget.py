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


def test_glow_icon_is_the_plain_icon_at_rest_and_glows_warm_with_sound(qapp):
    from soundboard import theme
    from soundboard.ui.logowidget import glow_icon
    rest = glow_icon(*theme.BRAND, 0.0).pixmap(32).toImage()
    loud = glow_icon(*theme.BRAND, 1.0).pixmap(32).toImage()
    assert glow_icon(*theme.BRAND, 1.0) is glow_icon(*theme.BRAND, 1.0)   # cached
    edge_rest, edge_loud = rest.pixelColor(2, 16), loud.pixelColor(2, 16)
    assert edge_rest.blue() > edge_rest.red()     # at rest: the purple tile reaches the edge
    assert edge_loud.alpha() > 0 and edge_loud.red() > edge_loud.blue()   # loud: a warm halo


from test_mainwindow import window  # noqa: E402,F401  (the real MainWindow fixture)


def test_main_window_icon_glows_while_the_radio_plays(window):  # noqa: F811
    from PySide6.QtWidgets import QApplication
    plain = QApplication.windowIcon().cacheKey()
    window.engine.level_play = 0.9
    window._glow_icons(window.engine.level_play, 1e9)
    assert window._icon_step == 4 and QApplication.windowIcon().cacheKey() != plain
    window._glow_icons(0.0, 2e9)
    assert window._icon_step == 0
