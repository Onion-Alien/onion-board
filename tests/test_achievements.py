"""Settings > Achievements: the counting (soundboard.core.achievements) and its page."""
import time
from types import SimpleNamespace

import pytest
from conftest import process_events

from soundboard.core import achievements as ach, usage
from soundboard.ui.settings.achievements import TIER_SPLASH, texts
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


NOON = time.strptime("2026-06-10 12:00:00", "%Y-%m-%d %H:%M:%S")   # no day of note


def at(when: str) -> time.struct_time:
    return time.strptime(when, "%Y-%m-%d %H:%M:%S")


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
        ach.played(hour=12, when=NOON, now=0.0)
        assert ach.got("first_blood") and not ach.got("spammer")
        for i in range(999):   # (2 s apart: never a Speed Run)
            ach.played(hour=12, when=NOON, now=2.0 * (i + 1))
        assert ach.got("spammer")
        ach.played(hour=12, when=NOON, now=5000.0)
        assert heard == ["first_blood", "spammer"]   # each said once
        assert not ach.got("gremlin")
        ach.played(hour=3, when=NOON)
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


def test_the_rarity_line_has_its_points_never_how_far_along(window):  # noqa: F811
    """"Common · 140 of 1,000" read as how many people had it: the numbers are the tooltip;
    the line has only the rarity and what it's worth."""
    from soundboard.ui.settings.achievements import tier_name
    from soundboard.ui.settings.settings import SettingsDialog
    ach.attach(window.cfg, today="2026-10-19")
    for _ in range(140):
        ach.played(hour=12, when=NOON)
    d = SettingsDialog(window, "achievements")
    tiles = {t.a.id: t for t in d.ach_tiles}
    assert tiles["spammer"].status.text() == f"{tier_name('uncommon')} · 25 points"
    assert "140" in tiles["spammer"].toolTip() and "1" in tiles["spammer"].toolTip()
    assert tiles["first_blood"].status.text() == f"{tier_name('common')} · 10 points"
    ach.detach()


def test_each_is_worth_its_rarity_and_the_score_adds_up(cfg):
    assert [ach.POINTS[t] for t in ach.TIERS] == sorted(ach.POINTS.values())   # rarer, more
    assert set(ach.POINTS) == set(ach.TIERS)
    assert ach.score() == 0
    assert ach.max_score() == sum(ach.POINTS[a.tier] for a in ach.ALL)
    ach.played(hour=3, when=NOON)   # First Blood (common) and 3 AM Gremlin (rare)
    assert ach.score() == ach.POINTS["common"] + ach.POINTS["rare"]


def test_the_page_shows_the_score_at_the_top(window):  # noqa: F811
    from PySide6.QtCore import QLocale
    from soundboard.ui.settings.settings import SettingsDialog
    ach.attach(window.cfg, today="2026-10-19")
    window.cfg.achievements["got"].clear()
    d = SettingsDialog(window, "achievements")
    total = QLocale().toString(ach.max_score())
    assert d.ach_score.text() == f"Score 0 / {total}"
    ach.played(hour=12, when=NOON)   # First Blood: 10
    d.achievements.refresh()   # (as each time the page is shown)
    assert d.ach_score.text() == f"Score 10 / {total}"
    d.close()
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
    ach.played(hour=12, when=NOON)           # First Blood: Common
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


def test_a_filter_closes_the_page_up_before_it_paints(window, qapp, monkeypatch):  # noqa: F811
    """Picking Earned painted a frame of the old, tall card with a few tiles at its
    bottom: the tiles change with painting held until the page is laid out again."""
    from soundboard.ui.settings import achievements as page
    from soundboard.ui.settings.settings import SettingsDialog
    ach.attach(window.cfg, today="2026-10-19")
    d = SettingsDialog(window, "achievements")
    d.show()
    held = []
    real = page.TileGrid.show_only
    monkeypatch.setattr(page.TileGrid, "show_only",
                        lambda grid, tiles: (held.append(d.updatesEnabled()), real(grid, tiles))[1])
    d.ach_show["earned"].click()
    assert held and not any(held) and d.updatesEnabled()
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


def test_the_onion_alien_egg_earns_its_four(cfg, monkeypatch):
    monkeypatch.setattr(usage, "enabled", lambda: False)
    usage.used("egg-onion-poked")
    assert ach.got("onion_poke") and not ach.got("onion_tears")
    ach.bump("onion_tears")
    usage.used("egg-onion-eaten")
    usage.used("egg-onion-please")
    assert all(ach.got(a) for a in ("onion_tears", "swallowed_whole", "pretty_please"))


def test_the_onion_alien_crying_counts(qapp, cfg):
    from soundboard.ui.bun import onionalien
    note = onionalien.AlienNote("hi")
    for _ in range(note.TEAR_1):
        note.poke()
    assert ach.got("onion_tears")
    note.deleteLater()


def test_an_hour_long_sound_on_the_board_is_the_long_haul(cfg):
    ach.tick(now=1.0, longest=3599.0)
    assert not ach.got("long_haul")
    ach.tick(now=2.0, longest=3600.0)
    assert ach.got("long_haul")


def test_a_long_sound_heard_to_its_end_is_a_full_album(cfg):
    ach.heard({"a": 0.2, "b": 0.4})
    ach.heard({"a": 0.6})            # b stopped half-way: no
    ach.heard({"a": 0.995})
    assert not ach.got("full_album")
    ach.heard({})                    # a ended at its end
    assert ach.got("full_album")


def test_ten_sounds_at_once_is_a_wall_of_noise(cfg):
    ach.at_once(9)
    assert not ach.got("wall_of_noise")
    ach.at_once(10)
    assert ach.got("wall_of_noise")


def test_the_pitch_all_the_way_up_or_down(cfg):
    ach.pitched(11)
    assert not ach.got("chipmunk") and not ach.got("demon_mode")
    ach.pitched(12)
    ach.pitched(-36)
    assert ach.got("chipmunk") and ach.got("demon_mode")


@pytest.mark.parametrize("when, earned", [
    ("2026-10-31 18:00:00", "spooky_season"), ("2026-12-25 09:30:00", "ho_ho_honk"),
    ("2027-01-01 00:00:42", "happy_new_noise"), ("2027-01-01 00:01:00", None),
    ("2026-12-31 23:59:59", None)])
def test_a_sound_on_the_day(cfg, when, earned):
    ach.played(when=at(when))
    days = {"spooky_season", "ho_ho_honk", "happy_new_noise"}
    assert {a for a in days if ach.got(a)} == ({earned} if earned else set())


def test_ten_theme_switches_in_thirty_seconds_is_disco_mode(cfg):
    for i in range(10):                   # one every 4 s: 36 s for the ten
        ach.theme_switched(now=i * 4.0)
    assert not ach.got("disco_mode")
    for i in range(10):
        ach.theme_switched(now=100 + i * 3.0)   # 27 s
    assert ach.got("disco_mode")


def test_tor_and_offline_together_is_the_hermit(cfg):
    ach.tick(now=1.0, tor=True)
    ach.tick(now=2.0, offline=True)
    assert not ach.got("hermit")
    ach.tick(now=3.0, tor=True, offline=True)
    assert ach.got("hermit")


def test_a_mic_unplugged_counts(cfg):
    usage.used("mic-unplugged")
    assert ach.got("pulled_plug")


def test_the_hunt_counts_what_was_earned(cfg):
    hidden = [a.id for a in ach.ALL if a.hidden and a.id not in
              ("achievement_hunter", "completionist", "onion_poke")]
    for aid in hidden[:9]:
        cfg.achievements["got"][aid] = 1
    usage.used("egg-onion-poked")             # the 10th secret one
    assert ach.got("achievement_hunter") and not ach.got("completionist")
    for a in ach.ALL:
        if a.id not in ("completionist", "pulled_plug"):
            cfg.achievements["got"].setdefault(a.id, 1)
    usage.used("mic-unplugged")               # the last one
    assert ach.got("completionist")


def test_earned_before_the_hunt_was_added_counts_at_start():
    secrets = [a.id for a in ach.ALL if a.hidden and a.id != "achievement_hunter"][:10]
    c = SimpleNamespace(achievements={"got": dict.fromkeys(secrets, 1)}, sounds=[])
    ach.attach(c, now=0.0, today="2026-10-19", month=10)
    try:
        assert ach.got("achievement_hunter")
    finally:
        ach.detach()


def test_the_konami_code(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    from soundboard.ui.window import konami
    w = QWidget()
    hits = []
    code = konami.KonamiCode(w, lambda: hits.append(1))
    K = Qt.Key
    for key in (K.Key_Up, K.Key_Down, *konami.CODE[:-1], K.Key_X):   # wrong: no
        code.press(key)
    assert not hits
    for key in (K.Key_Up, *konami.CODE):     # an extra ↑ first still works
        code.press(key)
    assert hits == [1]
    w.deleteLater()


def test_the_konami_code_cheers_and_earns_old_school(qapp, window):  # noqa: F811
    from soundboard.ui.window import konami
    ach.attach(window.cfg, today="2026-10-19")
    konami.react(window)
    assert ach.got("old_school")


# ------------------------------------------------------------------ the newer ones
def test_ten_plays_in_ten_seconds_is_a_speed_run(cfg):
    for i in range(10):
        ach.played(when=NOON, now=i * 1.5)   # 13.5 s for the ten
    assert not ach.got("speed_run")
    for i in range(10):
        ach.played(when=NOON, now=100 + i * 1.0)
    assert ach.got("speed_run")


def test_one_sound_all_day_long_and_after_a_month_away(cfg):
    for i in range(49):
        ach.played(when=NOON, sid="a", plays=i + 1, now=i * 5.0)
    assert not ach.got("broken_record")
    ach.played(when=at("2026-06-11 12:00:00"), sid="a", plays=50, now=500.0)
    assert not ach.got("broken_record")   # a new day starts again
    assert not ach.got("deep_cut")
    ach.played(when=at("2026-07-11 12:00:00"), sid="a", plays=51, now=600.0)
    assert ach.got("deep_cut")            # 30 days since it last played
    ach.played(when=NOON, sid="b", plays=500, now=700.0)
    assert ach.got("one_hit_wonder")


def test_quiet_plays_whisper(cfg):
    for i in range(20):
        ach.played(when=NOON, sid="a", gain=0.04, now=i * 5.0)
    ach.played(when=NOON, sid="a", gain=0.0, now=500.0)   # (muted: not a whisper)
    assert ach.got("whisper")


@pytest.mark.parametrize("when, earned", [
    ("2026-04-01 10:00:00", "april_fool"), ("2028-02-29 10:00:00", "leap_of_faith"),
    ("2026-06-10 13:37:00", "leet"), ("2026-11-13 10:00:00", "friday_13th"),
    ("2026-06-10 05:20:00", "early_bird"), ("2026-06-10 13:38:00", None)])
def test_more_sounds_on_the_day(cfg, when, earned):
    ach.played(when=at(when))
    days = {"april_fool", "leap_of_faith", "leet", "friday_13th", "early_bird"}
    assert {a for a in days if ach.got(a)} == ({earned} if earned else set())


def test_how_a_sound_was_played_counts(cfg):
    for _ in range(100):
        ach.played_by("hotkey", hidden=True)
        ach.played_by("phone")
    assert ach.got("tray_ninja") and ach.got("phone_home")
    assert not ach.got("keyboard_warrior") and not ach.got("clicker")


def test_days_in_a_row_weekends_and_coming_back():
    c = SimpleNamespace(achievements={}, sounds=[])
    try:
        for day in range(1, 8):   # 1 to 7 November 2026: a Sunday, then Monday to Saturday
            ach.attach(c, now=0.0, today=f"2026-11-{day:02d}", month=11)
        assert ach.got("on_a_roll") and not ach.got("unbreakable")
        assert ach.value("weekends") == 2
        ach.attach(c, now=0.0, today="2026-11-09", month=11)   # a day missed
        assert c.achievements["seen"]["run"] == 1 and not ach.got("comeback_kid")
        ach.attach(c, now=0.0, today="2026-12-20", month=12)
        assert ach.got("comeback_kid")
    finally:
        ach.detach()


def test_the_tick_counts_the_quiet_the_night_loops_and_the_board(cfg):
    ach.tick(now=1800.0, hour=2)
    assert not ach.got("night_shift") and not ach.got("silence")
    ach.tick(now=3700.0, hour=3, looping=["x"])
    assert ach.got("night_shift") and ach.got("silence")
    assert not ach.got("loop_de_loop")
    ach.tick(now=4400.0, hour=12, looping=["x"], shortest=0.4, tabs=5)
    assert ach.got("loop_de_loop") and ach.got("blink") and ach.got("tidy_desk")


def test_exactly_69_sounds_is_nice(cfg):
    ach.sounds_now(68)
    assert not ach.got("nice")
    ach.sounds_now(69)
    assert ach.got("nice")


def test_radio_from_six_continents_and_a_long_listen_to_one(cfg):
    for i, cc in enumerate(("DE", "US", "BR", "JP", "ZA")):
        ach.station(f"s{i}", "x", cc)
    assert not ach.got("seven_seas")
    ach.station("s9", "x", "NZ")
    assert ach.got("seven_seas")
    ach.live("radio", True, now=0.0)
    ach.station("s1", "x", "US", now=0.0)
    ach.tick(now=9 * 3600.0, hour=12)
    assert not ach.got("station_loyalist")
    ach.tick(now=10 * 3600.0 + 5, hour=12)
    assert ach.got("station_loyalist")


def test_rock_paper_scissors_in_a_row_and_tic_tac_toe_wins(cfg):
    for who in ("you", "you", "you", "you", "bun", "you", "you", "you", "you"):
        ach.game_point("rps", who)
    assert not ach.got("rock_solid")
    ach.game_point("rps", "you")
    assert ach.got("rock_solid")
    for _ in range(10):
        ach.game_won("ttt")
        ach.game_won("pong")
    assert ach.got("grid_master") and ach.value("ttt_won") == 10


def test_a_voice_changer_run_and_the_voices_in_it(cfg):
    for i in range(10):
        ach.voice_picked(f"v{i}")
    assert ach.got("quick_change")
    ach.live("voice", True, now=0.0)
    ach.tick(now=3 * 3600.0 + 1, hour=12)
    assert ach.got("talk_show")


def test_downloads_count_sites_and_failures(cfg):
    for site in ("youtube", "tiktok", "soundcloud", "reddit"):
        ach.downloaded(site, True, "add")
    ach.downloaded("other", True, "play")   # (a Play isn't added)
    assert not ach.got("site_seer")
    ach.downloaded("other", True, "add")
    assert ach.got("site_seer")
    for _ in range(5):
        ach.downloaded("youtube", False, "add")
    assert ach.got("not_found")


def test_the_score_and_fifty_earned(cfg):
    for a in ach.ALL[1:50]:   # (not First Blood, ALL[0])
        cfg.achievements["got"][a.id] = 1
    ach.played(when=NOON)   # First Blood earned: the hunt looks again
    assert ach.got("overachiever")
    assert ach.value("score") == ach.score()
    assert ach.max_score() >= ach.BY_ID["high_score"].goal


def test_a_settings_reset_keeps_what_was_earned_and_earns_fresh_start(tmp_path, monkeypatch):
    from soundboard.core import reset
    assert "achievements" in reset.KEEP
    c = SimpleNamespace(achievements={"n": {"fresh_start": 1}, "got": {"first_blood": 5}},
                        sounds=[])
    try:
        ach.attach(c, now=0.0, today="2026-10-19", month=10)
        assert ach.got("fresh_start") and ach.got("first_blood") == 5
    finally:
        ach.detach()
