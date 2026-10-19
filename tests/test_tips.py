"""The old *Did you know?* tips' settings: still loaded from older versions, never in a
backup."""
from soundboard.sounds.library import Config


def test_tip_settings_survive_save_and_stay_out_of_backups(app_dir):
    from soundboard.core import backup
    Config(tips_on=False, tips_seen=["effects", "newer-tip"], tip_day="2026-10-07").save()
    c = Config.load()
    assert c.tips_on is False and c.tips_seen == ["effects", "newer-tip"]
    raw = backup.settings_of(c)
    assert "tips_seen" not in raw and "tip_day" not in raw and raw["tips_on"] is False
