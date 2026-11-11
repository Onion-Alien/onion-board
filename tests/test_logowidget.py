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


def test_a_sheen_frame_repaints_the_logo_alone_and_looks_the_same(window, qapp, monkeypatch):  # noqa: F811
    """See-through, each frame repainted the window, its page and the rail under the
    tile too. While it moves it paints a copy of what's under it, opaque: the same
    picture, and the copy goes when anything round it moves or the theme changes."""
    from PySide6.QtCore import QPoint, QRect, Qt
    from soundboard.ui.bun import logowidget
    window.show()
    logo = window.logo
    logo._pause()
    fixed = logowidget.time.monotonic()
    logo._t0 = fixed - logowidget.SHEEN_TIME * 0.45   # mid-sheen
    r = QRect(logo.mapTo(window, QPoint(0, 0)), logo.size())
    scr = window.screen()
    import types
    monkeypatch.setattr(logowidget, "time", types.SimpleNamespace(monotonic=lambda: fixed))
    window.repaint()
    before = scr.grabWindow(window.winId()).copy(r).toImage()
    logo._keep_backdrop()
    assert logo.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    logo.repaint()
    after = scr.grabWindow(window.winId()).copy(r).toImage()
    worst = max(abs(getattr(before.pixelColor(x, y), c)() - getattr(after.pixelColor(x, y), c)())
                for x in range(r.width()) for y in range(r.height())
                for c in ("red", "green", "blue"))
    assert worst <= 2
    window.resize(window.width() - 40, window.height())   # something round it changed
    assert logo._backdrop is None
    assert not logo.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)


def test_the_loading_bar_and_glow_hold_still_behind_a_game(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton
    from soundboard.style import appstate as style_state
    from soundboard.ui.kit import appstate, toast
    from soundboard.ui.kit.glow import Glow
    from soundboard.ui.kit.meters import LoadingBar
    monkeypatch.setattr(toast, "animations_on", lambda: True)
    for mod in (appstate, style_state):           # in front
        monkeypatch.setattr(mod, "active", lambda: True)
    bar, btn = LoadingBar(), QPushButton("go")
    bar.show()
    btn.show()
    glow = Glow(btn)
    glow._apply()
    bar.start()
    assert bar.ticking() and glow._timer.isActive()
    for mod in (appstate, style_state):
        monkeypatch.setattr(mod, "active", lambda: False)
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    assert not bar.ticking() and not glow._timer.isActive()
    bar.hide()
    bar.show()                                    # shown again behind the game: still
    assert not bar.ticking()
    for mod in (appstate, style_state):
        monkeypatch.setattr(mod, "active", lambda: True)
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert bar.ticking() and glow._timer.isActive() and bar.running()
    bar.stop()
    glow.set_on(False)
