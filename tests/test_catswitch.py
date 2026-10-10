"""Switch category when a program is in front: the rules' logic with a stubbed
foreground window, and the board following it."""
import pytest

from soundboard import backup
from soundboard.catswitch import Switcher
from soundboard.library import Config, clean_programs

from test_mainwindow import window  # noqa: F401  (the real MainWindow)

GAME = "C:\\Games\\Some Game\\game.exe"
BROWSER = "C:\\Apps\\browser.exe"
CATS = ["Memes", "Game"]
RULES = {"game.exe": "Game"}


class Desk:
    """A stand-in for the window in front and the running programs."""
    def __init__(self):
        self.front = (0, "")
        self.running = set()

    def show(self, pid, path):
        self.front = (pid, path)
        self.running.add(pid)

    def close(self, pid):
        self.running.discard(pid)
        if self.front[0] == pid:
            self.front = (0, "")


def switcher(desk):
    return Switcher(foreground=lambda: desk.front, alive=lambda pid: pid in desk.running)


@pytest.mark.windows   # Windows paths (C:\...)
def test_switches_when_the_program_comes_to_the_front_and_back_when_it_closes():
    d = Desk()
    s = switcher(d)
    assert s.poll(RULES, "Memes", CATS) is None   # nothing in front
    d.show(10, GAME)
    sw = s.poll(RULES, "Memes", CATS)
    assert sw.category == "Game" and sw.exe == "game.exe" and not sw.back
    assert s.poll(RULES, "Game", CATS) is None    # still in front: once is enough
    d.close(10)
    sw = s.poll(RULES, "Game", CATS)
    assert sw.category == "Memes" and sw.back
    assert s.poll(RULES, "Memes", CATS) is None


def test_no_switch_for_a_program_without_a_rule_or_a_missing_category():
    d = Desk()
    s = switcher(d)
    d.show(11, BROWSER)
    assert s.poll(RULES, "Memes", CATS) is None
    d.show(12, GAME)
    assert s.poll({"game.exe": "Gone"}, "Memes", CATS) is None


@pytest.mark.windows   # Windows paths (C:\...)
def test_alt_tab_out_changes_nothing_and_coming_back_switches_again():
    d = Desk()
    s = switcher(d)
    d.show(10, GAME)
    s.poll(RULES, "", CATS)
    d.show(11, BROWSER)                       # alt-tab out: the game still runs
    assert s.poll(RULES, "Game", CATS) is None
    # picked by hand while away; back in the game shows its category again
    d.show(10, GAME)
    assert s.poll(RULES, "Memes", CATS).category == "Game"


def test_a_pick_by_hand_while_the_program_is_in_front_is_respected():
    d = Desk()
    s = switcher(d)
    d.show(10, GAME)
    s.poll(RULES, "", CATS)
    d.front = (0, "")   # the board's own window (or Windows' taskbar) doesn't count
    assert s.poll(RULES, "Memes", CATS) is None
    d.front = (10, GAME)   # back to the game without another program in between
    assert s.poll(RULES, "Memes", CATS) is None
    d.close(10)   # closed while their pick shows: it stays
    assert s.poll(RULES, "Memes", CATS) is None


@pytest.mark.windows   # Windows paths (C:\...)
def test_matches_the_exe_name_in_any_folder_and_case():
    d = Desk()
    s = switcher(d)
    d.show(13, "D:\\Other place\\GAME.EXE")
    assert s.poll(RULES, "", CATS).category == "Game"


@pytest.mark.windows   # Windows paths (C:\...)
def test_back_to_all_works():
    d = Desk()
    s = switcher(d)
    d.show(10, GAME)
    s.poll(RULES, "", CATS)
    d.close(10)
    sw = s.poll(RULES, "Game", CATS)
    assert sw.back and sw.category == ""


# ------------------------------------------------------------------ settings + backups

def test_rules_round_trip_through_save_and_load(app_dir):
    Config(categories=["Game"], category_programs={"game.exe": "Game"},
           category_programs_on=False).save()
    c = Config.load()
    assert c.category_programs == {"game.exe": "Game"} and c.category_programs_on is False


def test_old_settings_without_the_field_load(app_dir):
    import json

    from soundboard import library
    library.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    library.CONFIG_PATH.write_text(json.dumps({"version": 5, "categories": ["Game"]}),
                                   encoding="utf-8")
    c = Config.load()
    assert c.category_programs == {} and c.category_programs_on is True


def test_bad_rules_are_dropped():
    assert clean_programs({"Game.EXE": "Game", "..": "x", "c:\\x\\y.exe": "Game",
                           "a.exe": "", 3: "Game", "b.exe": 4}) == {"game.exe": "Game"}
    assert clean_programs([1, 2]) == {}


def test_rules_go_into_a_backup_and_back():
    cfg = Config(category_programs={"game.exe": "Game"})
    raw = backup.settings_of(cfg)
    assert raw["category_programs"] == {"game.exe": "Game"}
    other = Config()
    assert "category_programs" in backup.apply_settings(other, raw)
    assert other.category_programs == {"game.exe": "Game"}


# ------------------------------------------------------------------ the board

@pytest.mark.windows   # Windows paths (C:\...)
def test_the_board_follows_the_program_and_rename_delete_keep_rules_right(window):  # noqa: F811
    d = Desk()
    w = window
    w.cat_switch = switcher(d)
    w.new_category(name="Memes")
    w.new_category(name="Game")
    w.set_category("Memes")
    w.add_category_program("Game", GAME)
    assert w.cfg.category_programs == {"game.exe": "Game"} and w._cat_timer.isActive()
    d.show(10, GAME)
    w._cat_tick()
    assert w.cfg.category == "Game"
    w.rename_category("Game", "Shooter")
    assert w.cfg.category_programs == {"game.exe": "Shooter"}
    d.close(10)
    w._cat_tick()
    assert w.cfg.category == "Memes"   # back to what showed before
    tip = w.cat_tabs.tabToolTip(w.cfg.categories.index("Shooter") + 1)
    assert "game.exe" in tip
    w.delete_category("Shooter")
    assert w.cfg.category_programs == {} and not w._cat_timer.isActive()


def test_switch_off_stops_following(window):  # noqa: F811
    w = window
    w.new_category(name="Game")
    w.add_category_program("Game", "game.exe")
    w.set_category_programs_on(False)
    assert not w._cat_timer.isActive() and w.cfg.category_programs == {"game.exe": "Game"}
    w.set_category_programs_on(True)
    assert w._cat_timer.isActive()
    w.remove_category_program("game.exe")
    assert not w._cat_timer.isActive()


@pytest.mark.windows   # Windows paths (C:\...)
def test_program_picker_lists_and_browses(qapp):
    from soundboard.ui.programpick import ProgramPicker
    p = ProgramPicker("Game", {"other.exe": "Memes"},
                      lister=lambda: [("game.exe", GAME, "Some Game"),
                                      ("other.exe", "C:\\o\\other.exe", "")])
    p.fill([("game.exe", GAME, "Some Game"), ("other.exe", "C:\\o\\other.exe", "")])
    assert p.list.count() == 2 and "now shows “Memes”" in p.list.item(1).text()
    p.add_path("C:\\x\\New.exe")
    assert p.list.count() == 3 and p._chosen() == ["new.exe"]
    p._ok()
    assert p.picked == ["new.exe"]
    p.deleteLater()
