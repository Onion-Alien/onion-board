"""The start-up splash (ui/bun/splash.py): up while starting, pumped by imports, gone after."""
import sys

from soundboard.ui.bun import splash


def test_pump_without_splash_does_nothing(qapp):
    assert splash._splash is None
    splash.pump()   # must not raise or show anything


def test_show_pump_close(qapp):
    s = splash.show()
    try:
        assert s.isVisible()
        assert splash._PumpOnImport in sys.meta_path
        splash._last = 0.0
        splash.pump()
        assert splash._PumpOnImport.find_spec("no_such_module_xyz") is None
        img = s.grab().toImage()
        assert not img.isNull() and img.width() == splash.CARD_W
    finally:
        splash.close()
    assert splash._splash is None
    assert splash._PumpOnImport not in sys.meta_path
    splash.close()   # twice is fine (start-up failure path, then the normal one)


def test_splash_follows_the_saved_theme(qapp, tmp_path, monkeypatch):
    from soundboard.ui.kit import theme
    cfg = tmp_path / "config.json"
    cfg.write_text('{"theme": "Toxic"}', encoding="utf-8")
    monkeypatch.setattr(splash, "CONFIG", cfg)
    try:
        s = splash.show()
        assert theme.current_name == "Toxic"
        img = s.grab().toImage()
        assert img.pixelColor(0, 0).alpha() == 0   # transparent outside the rounded panel
        # bottom left: past both of the theme glow's blobs, the plain panel colour
        assert img.pixelColor(20, splash.CARD_H - 20).name() == theme.T["panel"]
    finally:
        splash.close()
        theme.set_current(theme.DEFAULT)


def test_frames_draw_at_any_scale(qapp):
    """The native splash paints paint_frame() at the monitor's own scale."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    for k in (1.0, 1.25, 2.0):
        img = QImage(round(splash.CARD_W * k), round(splash.CARD_H * k),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.scale(k, k)
        splash.paint_frame(p, 0.3, splash.CARD_W, splash.CARD_H, k)
        p.end()
        assert img.pixelColor(0, 0).alpha() == 0
        assert any(img.pixelColor(x, img.height() // 2).alpha() == 255
                   for x in range(img.width()))   # the panel is solid


def _panel(x, y):
    """The bare panel's colour at (x, y): its theme glow, with nothing drawn over it."""
    return splash._surface(splash.CARD_W, splash.card_h(), 1.0).pixelColor(x, y).name()


def _frame(t):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    img = QImage(splash.CARD_W, splash.card_h(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    splash.paint_frame(p, t, splash.CARD_W, splash.card_h())
    p.end()
    return img


def test_bun_acts_while_the_text_stays_put(qapp, monkeypatch):
    """Bun moves (his act), the name and status don't, and nothing he does reaches
    the text below him."""
    from soundboard.ui.bun import splashacts
    monkeypatch.setattr(splash, "_animate", True)
    for act in splashacts.ACTS:
        monkeypatch.setattr(splash, "_show", splashacts.Show(act=act))
        frames = [_frame(t) for t in (0.0, 0.31, 0.77, 1.4)]
        assert any(a.copy(0, 0, a.width(), 140) != b.copy(0, 0, b.width(), 140)
                   for a, b in zip(frames, frames[1:])), act   # he moves
        for img in frames[1:]:
            assert img.copy(0, 141, img.width(), 50) == frames[0].copy(0, 141, img.width(), 50), act
    assert splash.CARD_W <= 240 and splash.CARD_H <= 248


def test_pick_rare_and_seasonal():
    import datetime
    import random

    from soundboard.style import bunnyfit
    from soundboard.ui.bun import splashacts
    day = datetime.datetime(2026, 6, 1, 14)
    seen = {splashacts.pick(day, random.Random(i)).act for i in range(400)}
    assert seen == set(splashacts.ACTS)   # every act turns up
    rares = [splashacts.pick(day, random.Random(i)) for i in range(4000)]
    golds = sum(r.rare == "gold" for r in rares)
    assert 40 < golds < 130   # about 1 in 50
    assert all(r.act != "robo" for r in rares if r.rare)   # (Robo-Bun keeps his metal)
    assert [odds for odds, *_ in splashacts.RARES.values()] == [50000, 5000, 500, 50]
    assert all(splashacts.pick(day, random.Random(i)).outfit is None for i in range(20))
    xmas = splashacts.pick(datetime.datetime(2026, 12, 20, 14), random.Random(1))
    assert xmas.outfit is not None and "santa" in xmas.outfit
    assert not (set(xmas.outfit) - {"santa"}) & bunnyfit.HATS   # his own hat off
    october = splashacts.pick(datetime.datetime(2026, 10, 31, 14), random.Random(1))
    assert october.outfit is not None and "fangs" in october.outfit
    if "witch_hat" in bunnyfit.PIECES:   # (the Halloween theme's hat)
        assert "witch_hat" in october.outfit
    night = [splashacts.pick(datetime.datetime(2026, 6, 1, 23), random.Random(i)).act
             for i in range(300)]
    assert night.count("sleepy") > 100   # sleepy is the favourite at night


def test_goodbye_fades_out(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    monkeypatch.setattr(splash, "_animate", True)

    def leaving(u):
        img = QImage(splash.CARD_W, splash.CARD_H, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        splash.paint_frame(p, 0, splash.CARD_W, splash.CARD_H, 1.0, u)
        p.end()
        return img
    start, mid = leaving(0.0), leaving(0.4)
    assert start.pixelColor(20, 20).alpha() == 255
    assert start.copy(0, 0, start.width(), 140) != mid.copy(0, 0, mid.width(), 140)  # waving
    assert splash.fade(None) == splash.fade(0.5) == 1.0
    assert 0 < splash.fade(0.8) < 1 and splash.fade(1.0) == 0.0   # the window fades out


def test_reduced_motion_keeps_bun_still(qapp, monkeypatch):
    monkeypatch.setattr(splash, "_animate", False)
    a, b = _frame(0), _frame(0.77)
    assert a.copy(0, 0, a.width(), 140) == b.copy(0, 0, b.width(), 140)


def test_highlight_and_hop_travel_left_to_right(qapp, monkeypatch):
    from PySide6.QtGui import QColor

    from soundboard.ui.kit import theme

    monkeypatch.setattr(splash, "_animate", True)
    accent = QColor(theme.T["accent"])
    resting = QColor(theme.T["muted"])
    for active in range(3):
        img = _frame(active * splash.PULSE_S / 3)
        for dot in range(3):
            x = splash.CARD_W // 2 + (dot - 1) * 16
            if dot == active:
                assert img.pixelColor(x, 208) == accent
                assert img.pixelColor(x + 4, 208) == accent   # visibly larger
            else:
                assert img.pixelColor(x, 213) == resting
                assert img.pixelColor(x, 205).name() == _panel(x, 205)
    a, b = _frame(0), _frame(splash.PULSE_S)
    assert a.copy(0, 200, a.width(), 48) == b.copy(0, 200, b.width(), 48)   # seamless repeat


def test_reduced_motion_moves_only_the_colour(qapp, monkeypatch):
    """Animation effects off: the highlight still walks, but no dot grows or hops."""
    from PySide6.QtGui import QColor

    from soundboard.ui.kit import theme

    monkeypatch.setattr(splash, "_animate", False)
    accent = QColor(theme.T["accent"])
    resting = QColor(theme.T["muted"])
    for active in range(3):
        img = _frame(active * splash.PULSE_S / 3)
        for dot in range(3):
            x = splash.CARD_W // 2 + (dot - 1) * 16
            assert img.pixelColor(x, 213) == (accent if dot == active else resting)
            assert img.pixelColor(x + 4, 213).name() == _panel(x + 4, 213)   # same size
            assert img.pixelColor(x, 208).name() == _panel(x, 208)   # no hop
    assert _frame(0) != _frame(splash.PULSE_S / 3)


def test_windows_animation_preference(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    monkeypatch.setattr(splash.sys, "platform", "win32")

    def preference(action, param, result, flags):
        assert action == 0x1042
        result._obj.value = 0
        return 1

    user = SimpleNamespace(SystemParametersInfoW=preference)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user), raising=False)
    assert not splash._animations_enabled()
    user.SystemParametersInfoW = lambda *args: 0   # unavailable: retain the default
    assert splash._animations_enabled()


def test_rare_launch_glows_and_shows_its_drop_rate(qapp, monkeypatch):
    """A rare launch: a glow round the panel (in the margin a plain one leaves clear)
    and its tier and drop rate under the dots, on a taller card; each tier its own look."""
    from soundboard.ui.bun import splashacts
    monkeypatch.setattr(splash, "_animate", True)
    plain = _frame(0.3)
    assert plain.pixelColor(4, splash.CARD_H // 2).alpha() == 0
    looks = set()
    for rare in splashacts.RARES:
        monkeypatch.setattr(splash, "_show", splashacts.Show(act="hop", rare=rare))
        splash._surfaces.clear()
        img = _frame(0.3)
        assert img.pixelColor(5, splash.CARD_H // 2).alpha() > 0, rare   # the glow
        assert img.height() == splash.CARD_H + splash.RARE_H, rare   # room for its line
        assert img.copy(0, 228, img.width(), 22) != plain.copy(0, 228, img.width(), 22), rare
        looks.add(img.copy(80, 30, 80, 96).bits().tobytes())
    assert len(looks) == len(splashacts.RARES)
    assert len({splash.tier_name(r) for r in splashacts.RARES}) == len(splashacts.RARES)
    splash._surfaces.clear()


def test_rare_tiers_sit_end_to_end():
    """Each tier is exactly 1/odds of the roll: its edges, and nothing past the last."""
    from soundboard.ui.bun import splashacts
    edge = 0.0
    for name, (odds, *_) in splashacts.RARES.items():
        start, edge = edge, edge + 1 / odds
        assert splashacts.rare_for(start) == name
        assert splashacts.rare_for(edge - 1e-12) == name
    assert splashacts.rare_for(edge) is None
    assert splashacts.rare_for(0.5) is None and splashacts.rare_for(0.999999) is None
    assert abs(edge - (1 / 50 + 1 / 500 + 1 / 5000 + 1 / 50000)) < 1e-15   # ~2.2 % in all


def test_rare_odds_hold_over_millions_of_launches():
    """Rolled the way pick() rolls: each tier within 6 standard deviations of 1/odds
    (2 million launches: gold 40000 +- 1200, ice 4000 +- 380, galaxy 400 +- 120,
    rainbow 40 +- 38), so a 1/500 can't really be a 1/10."""
    import math
    import random

    from soundboard.ui.bun import splashacts
    n = 2_000_000
    rng = random.Random(20261018)
    counts = dict.fromkeys(splashacts.RARES, 0)
    for _ in range(n):
        rare = splashacts.rare_for(rng.random())
        if rare:
            counts[rare] += 1
    for name, (odds, *_) in splashacts.RARES.items():
        expected = n / odds
        assert abs(counts[name] - expected) <= 6 * math.sqrt(expected), (name, counts[name])


def test_panel_has_the_themes_soft_glow(qapp, monkeypatch):
    """The panel isn't one flat colour: the theme's accent glows behind Bun and fades
    out lower down. High Contrast keeps its flat panel."""
    from soundboard.ui.kit import theme
    from soundboard.ui.bun import splashacts
    monkeypatch.setattr(splash, "_show", splashacts.Show(act="hop"))
    try:
        for name, glows in (("Dark", True), ("High Contrast", False)):
            theme.set_current(name)
            splash._surfaces.clear()
            img = splash._surface(splash.CARD_W, splash.CARD_H, 1.0)
            top, bottom = img.pixelColor(30, 20), img.pixelColor(30, splash.CARD_H - 20)
            assert (top != bottom) == glows, name
    finally:
        theme.set_current("")
        splash._surfaces.clear()


class _SlowNative:
    """A NativeSplash whose thread is still on its first frame after the 1 s wait."""
    def __init__(self, alive=True):
        self.ok, self._alive, self.closed = False, alive, False

    def starting(self):
        return self._alive

    def close(self, goodbye=False):
        self.closed = True


def test_a_slow_first_frame_keeps_the_native_splash(qapp, monkeypatch):
    # a first launch right after installing drew its first frame late: the native one
    # stays (it shows when drawn) instead of the Qt one, which only drew while the UI
    # thread had time -- a start that slow showed nothing at all
    monkeypatch.setattr(splash.QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(splash, "NativeSplash", _SlowNative)
    try:
        s = splash.show()
        assert isinstance(s, _SlowNative) and not s.closed
    finally:
        monkeypatch.setattr(splash, "_splash", None)


def test_a_native_splash_that_failed_falls_back_to_qt(qapp, monkeypatch):
    monkeypatch.setattr(splash.QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    class _Failed(_SlowNative):
        def __init__(self):
            super().__init__(alive=False)
    monkeypatch.setattr(splash, "NativeSplash", _Failed)
    try:
        s = splash.show()
        assert isinstance(s, splash.Splash)
    finally:
        splash.close()
