"""Settings > Achievements: the counting (soundboard.core.achievements) and its page."""
from types import SimpleNamespace

import pytest
from conftest import process_events

from soundboard.core import achievements as ach, usage
from soundboard.ui.settings.achievements import TIER_SPLASH, texts
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


@pytest.fixture
def cfg():
    c = SimpleNamespace(achievements={}, sounds=[])
    ach.attach(c, now=0.0, today="2026-10-19", month=10)
    yield c
    ach.detach()


def test_every_achievement_has_words_a_known_rarity_and_a_reachable_goal():
    words = texts()
    assert set(words) == set(ach.BY_ID)
    for a in ach.ALL:
        assert a.tier in ach.TIERS
        assert a.tier == "common" or a.tier in TIER_SPLASH
        assert a.goal > 0
        assert a.stat not in ach.SETS or ach.SETS[a.stat] >= a.goal, a.id
    assert sum(a.hidden for a in ach.ALL) > len(ach.ALL) / 2   # most are secret


def test_a_count_earns_it_once_at_its_goal(cfg):
    heard = []
    ach.on_unlock.append(heard.append)
    try:
        ach.played(hour=12)
        assert ach.got("first_blood") and not ach.got("spammer")
        for _ in range(999):
            ach.played(hour=12)
        assert ach.got("spammer")
        ach.played(hour=12)
        assert heard == ["first_blood", "spammer"]   # each said once
        assert not ach.got("gremlin")
        ach.played(hour=3)
        assert ach.got("gremlin")
    finally:
        ach.on_unlock.remove(heard.append)


def test_used_features_count_without_the_usage_count(cfg, monkeypatch):
    monkeypatch.setattr(usage, "enabled", lambda: False)
    usage.used("egg-pong-won")
    usage.used("splash-rainbow")
    for g in ("pong", "draw", "rps", "ttt", "other"):
        usage.used(f"egg-game-{g}")
    assert ach.got("gamer_bun") and ach.got("rainbow_bun") and ach.got("arcade_rat")
    assert not ach.got("catch_em_all")   # Rainbow isn't one of the three


def test_one_station_played_again_and_again_counts_once(cfg):
    for _ in range(200):
        ach.station("abc-123", "nz")
    assert ach.value("stations") == 1 and ach.value("countries") == 1


def test_up_undo_up_on_one_sound_is_one_upvote(cfg):
    for mine in (1, 0, 1, -1, 1):
        ach.voted("s1", mine)
    assert ach.value("upvotes") == 1


def test_sounds_already_on_the_board_count_then_new_ones_add(cfg):
    c = SimpleNamespace(achievements={}, sounds=[object()] * 120)
    ach.attach(c, today="2026-10-19")
    assert ach.got("collector") and ach.value("sounds_added") == 120
    ach.sounds_now(100)   # some deleted: nothing taken off
    ach.sounds_now(260)
    assert ach.value("sounds_added") == 280 and ach.got("hoarder")


def test_live_time_adds_up_on_the_tick(cfg):
    ach.live("voice", True, now=10.0)
    ach.tick(now=10.0 + 1800)
    assert not ach.got("new_voice")
    ach.live("voice", False, now=10.0 + 3600)
    assert ach.got("new_voice")
    ach.tick(now=99_999.0)   # off: nothing more piles up
    assert ach.value("voice_s") == 3600


def test_the_radio_run_is_its_longest_stretch(cfg):
    ach.live("radio", True, now=0.0)
    ach.tick(now=2 * 3600)
    ach.live("radio", False, now=2.5 * 3600)
    ach.live("radio", True, now=3 * 3600)
    ach.live("radio", False, now=4 * 3600)
    assert ach.value("radio_run_s") == 2.5 * 3600 and not ach.got("night_owl")


def test_days_count_once_a_day(cfg):
    c = cfg
    ach.attach(c, today="2026-10-19", month=10)
    ach.attach(c, today="2026-10-20", month=11)
    assert ach.value("days") == 2 and ach.value("months") == 2


def test_the_page_shows_secrets_as_question_marks(window):  # noqa: F811
    from soundboard.ui.settings.settings import SettingsDialog
    ach.attach(window.cfg, today="2026-10-19")
    usage.used("egg-bun-woken")
    d = SettingsDialog(window, "achievements")
    d.show()
    tiles = {t.a.id: t for t in d.ach_tiles}
    assert len(tiles) == len(ach.ALL)
    assert tiles["rise_and_shine"].title.text() == texts()["rise_and_shine"][0]
    assert tiles["gremlin"].title.text() == "???"
    assert tiles["collector"].title.text() == texts()["collector"][0]
    d.close()
    ach.detach()


def test_tiles_take_one_column_in_a_narrow_window(window):  # noqa: F811
    """The page started at two columns, which set its minimum width: at the narrowest
    Settings the right column was cut off and never wrapped."""
    from PySide6.QtTest import QTest
    from soundboard.ui.settings.achievements import TILE_W
    from soundboard.ui.settings.settings import SettingsDialog
    window.resize(1275, 760)
    window.show()
    window.setctl.open_settings("achievements")
    d = window.findChild(SettingsDialog)
    QTest.qWait(300)
    grid = d.ach_tiles[0].parent()
    assert grid.cols == 3
    assert grid.minimumSizeHint().width() <= TILE_W   # one column's worth, never three
    window.resize(440, 760)   # a jump, as an un-maximise or a snap does
    QTest.qWait(400)
    assert grid.cols == 1
    ach.detach()


def test_the_rarity_line_never_has_a_number_beside_it(window):  # noqa: F811
    """"Common · 140 of 1,000" read as how many people had it: the numbers are the tooltip."""
    from soundboard.ui.settings.achievements import tier_name
    from soundboard.ui.settings.settings import SettingsDialog
    ach.attach(window.cfg, today="2026-10-19")
    for _ in range(140):
        ach.played(hour=12)
    d = SettingsDialog(window, "achievements")
    tiles = {t.a.id: t for t in d.ach_tiles}
    assert tiles["spammer"].status.text() == tier_name("uncommon")
    assert "140" in tiles["spammer"].toolTip() and "1" in tiles["spammer"].toolTip()
    assert tiles["first_blood"].status.text() == tier_name("common")
    ach.detach()


def test_a_badge_picture_in_the_art_folder_is_used(qapp, tmp_path, monkeypatch):
    """Badge pictures live in assets/art (achievement-<id>.png): the installed build
    carries that folder, not a new one of their own."""
    from PySide6.QtGui import QColor, QImage
    from soundboard.ui.settings import achievements as page
    from soundboard.ui.voice import art
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(QColor("#ff0000"))
    img.save(str(tmp_path / "achievement-first_blood.png"))
    monkeypatch.setattr(art, "ART_DIR", tmp_path)
    page._picture.cache_clear()
    try:
        b = page.Badge(ach.BY_ID["first_blood"])
        b.earned = True
        shot = b.grab().toImage()
        mid = shot.pixelColor(shot.width() // 2, shot.height() // 2)
        assert mid.red() > 200 and mid.green() < 60
        assert page._picture("menace", 44, False) is None   # none for it: drawn
    finally:
        page._picture.cache_clear()


def test_prepare_art_knows_every_badge():
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "scripts" / "pictures" / "prepare_art.py"
    spec = importlib.util.spec_from_file_location("prepare_art", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.key_for("achievement-gamer_bun (2).png") == "achievement-gamer_bun"
    assert {f"achievement-{a.id}" for a in ach.ALL} <= set(mod.KEYS)


def test_every_badge_has_a_scene_from_buns_own_kit(qapp):
    """Each badge is Bun drawn in a scene: only props, outfit pieces, rare looks and
    icons that exist (a typo would quietly draw plain Bun, or nothing)."""
    from soundboard.style import bunnyfit
    from soundboard.ui.bun import bunny, splashacts
    from soundboard.ui.kit import icons
    from soundboard.ui.settings import badges
    assert set(badges.SCENES) == set(ach.BY_ID)
    for aid, scene in badges.SCENES.items():
        assert scene.get("prop") in bunny.PROPS, aid
        assert all(piece in bunnyfit.PIECES for piece in scene.get("outfit", ())), aid
        assert scene.get("rare") in (None, *splashacts.RARES), aid
        assert scene.get("glyph") in (None, *icons.SHAPES), aid


def test_a_badge_is_drawn_and_locked_ones_are_grey(qapp):
    from soundboard.ui.settings import badges
    on = badges.badge("golden_bun", "uncommon", 56).toImage()
    off = badges.badge("golden_bun", "uncommon", 56, locked=True).toImage()
    mid = on.pixelColor(28, 30)
    assert mid.alpha() == 255 and mid.saturation() > 40   # gold, Bun on it
    grey = off.pixelColor(28, 30)
    assert grey.saturation() < 10 and grey.alpha() < 160  # grey and faded


def test_the_filters_pick_earned_not_yet_and_a_rarity(window):  # noqa: F811
    from soundboard.ui.settings.settings import SettingsDialog
    ach.attach(window.cfg, today="2026-10-19")
    usage.used("egg-bun-woken")   # Rise and Shine: an Uncommon secret
    ach.played(hour=12)           # First Blood: Common
    d = SettingsDialog(window, "achievements")
    d.show()
    shown = lambda: {t.a.id for t in d.ach_tiles if t.isVisibleTo(d)}  # noqa: E731
    assert len(shown()) == len(ach.ALL)
    d.ach_show["earned"].click()
    assert shown() == {"first_blood", "rise_and_shine"}
    d.ach_rarity.setCurrentIndex(d.ach_rarity.findData("uncommon"))
    assert shown() == {"rise_and_shine"}
    assert not d.ach_cards[0][0].isVisibleTo(d)   # no earned Uncommon milestone: it goes
    d.ach_show["todo"].click()
    assert "rise_and_shine" not in shown() and "spammer" in shown()
    d.ach_rarity.setCurrentIndex(d.ach_rarity.findData("super"))
    d.ach_show["earned"].click()
    assert not shown() and d.ach_none.isVisibleTo(d)   # nothing: the line says so
    d.close()
    ach.detach()


def test_the_page_turns_the_pop_up_sound_on_and_off(window):  # noqa: F811
    from soundboard.ui.settings.settings import SettingsDialog
    window.cfg.achievement_popups = True
    window.cfg.achievement_sound = False
    d = SettingsDialog(window, "achievements")
    d.show()
    assert not d.box_ach_sound.isChecked()
    d.box_ach_sound.click()
    assert window.cfg.achievement_sound is True
    d.box_ach_sound.click()
    assert window.cfg.achievement_sound is False
    d.close()


def test_pop_ups_off_greys_the_sound_box(window):  # noqa: F811
    from soundboard.ui.settings.settings import SettingsDialog
    window.cfg.achievement_popups = True
    d = SettingsDialog(window, "achievements")
    d.show()
    assert d.box_ach_popups.isChecked() and d.box_ach_sound.isEnabled()
    d.box_ach_popups.click()
    assert window.cfg.achievement_popups is False and not d.box_ach_sound.isEnabled()
    d.box_ach_popups.click()
    assert window.cfg.achievement_popups is True and d.box_ach_sound.isEnabled()
    d.close()


def test_silent_but_deadly_counts_with_sending_off_too(qapp, window, monkeypatch):  # noqa: F811
    """A sound played at 0% Sounds volume earns it whatever the route: with the route
    "off" it never counted, though the badge just says "with the sound volume at 0%"."""
    assert process_events(qapp, lambda: "s0" in window.audio)   # loaded
    ach.attach(window.cfg, today="2026-10-19")
    monkeypatch.setattr(window.engine, "play", lambda *a, **k: object())
    window.cfg.route = "off"
    window.cfg.sound_vol = 0.0
    window.playctl.play("s0")
    assert ach.got("silent_but_deadly")
