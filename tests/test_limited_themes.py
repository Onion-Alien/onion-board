"""Limited-edition themes (Halloween, Fireworks): on offer until their last day, kept for good by
whoever used one in time, gone for everyone else after; their tag and lantern logo."""
import datetime

from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard.ui.kit import theme

DAY = datetime.timedelta(days=1)


def _last():
    return theme.LIMITED["Halloween"]


def test_the_limited_ones_are_the_first_cards():
    assert theme.GROUPS[0][1][:2] == ["Fireworks", "Halloween"]
    assert {"Fireworks", "Halloween"} <= set(theme.LIMITED)


def test_fireworks_is_on_all_november_then_gone(monkeypatch):
    monkeypatch.setattr(theme, "kept", set())
    nov1, nov30 = datetime.date(2026, 11, 1), datetime.date(2026, 11, 30)
    assert theme.LIMITED["Fireworks"] == nov30
    assert theme.offered("Fireworks", nov1) and theme.offered("Fireworks", nov30)
    assert not theme.offered("Fireworks", nov30 + DAY)
    assert not theme.offered("Halloween", nov1)   # one season gives way to the next
    assert theme.keep("Fireworks", nov30) and theme.offered("Fireworks", nov30 + 365 * DAY)


def test_on_offer_until_its_last_day_then_gone(monkeypatch):
    monkeypatch.setattr(theme, "kept", set())
    assert theme.on_offer("Halloween", _last())
    assert theme.offered("Halloween", _last())
    assert not theme.on_offer("Halloween", _last() + DAY)
    assert not theme.offered("Halloween", _last() + DAY)
    names = [n for __, ns in theme.groups(_last() + DAY) for n in ns]
    assert "Halloween" not in names and "Dark" in names
    assert not theme.on_offer("Dark") and theme.offered("Dark", _last() + DAY)


def test_used_in_time_its_kept_for_good(monkeypatch):
    monkeypatch.setattr(theme, "kept", set())
    assert not theme.keep("Halloween", _last() + DAY)   # too late: nothing to keep
    assert theme.keep("Halloween", _last())
    assert not theme.keep("Halloween", _last())          # (once)
    later = _last() + 365 * DAY
    assert theme.offered("Halloween", later)
    assert "Halloween" in [n for __, ns in theme.groups(later) for n in ns]
    assert not theme.keep("Dark")


def test_a_missed_limited_theme_falls_back_to_the_default(monkeypatch):
    monkeypatch.setattr(theme, "kept", set())
    monkeypatch.setattr(theme, "_today", lambda: _last() + DAY)
    assert theme.set_current("Halloween") == theme.DEFAULT
    theme.kept.add("Halloween")
    assert theme.set_current("Halloween") == "Halloween"


def test_using_it_in_the_app_keeps_and_saves_it(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(theme, "kept", set())
    window.themectl.apply_theme("Halloween")
    assert window.cfg.kept_themes == ["Halloween"]
    window.themectl.apply_theme("Dark")
    assert window.cfg.kept_themes == ["Halloween"]   # switching away keeps it


def test_the_card_has_the_tag_and_says_until_when(qapp, monkeypatch):
    from soundboard.ui.settings.appearance import ThemeCard, limited_tip
    monkeypatch.setattr(theme, "kept", set())
    card, plain = ThemeCard("Halloween"), ThemeCard("Dark")
    assert card.toolTip() == limited_tip("Halloween") and "31" in card.toolTip()
    assert card.accessibleDescription() == card.toolTip()   # a screen reader hears the date too
    assert plain.toolTip() == ""
    theme.kept.add("Halloween")
    assert limited_tip("Halloween") != card.toolTip()   # now: yours to keep


def test_halloween_carves_the_logo_into_a_lantern(qapp):
    t = theme.THEMES["Halloween"]
    lantern = theme.logo_pixmap(64, t["accent"], t["accent2"]).toImage()
    onion = theme.logo_pixmap(64, "#ff7517", t["accent2"]).toImage()   # any other pair
    assert lantern != onion
    centre = lantern.pixelColor(32, 40)   # pumpkin orange / candlelight, not white
    assert centre.red() > 200 and centre.blue() < 120
