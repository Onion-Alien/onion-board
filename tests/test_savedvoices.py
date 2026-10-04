"""Saved voices (soundboard.savedvoices): their own file, a bin, damaged files."""
import json
import time

from soundboard import backup, library, savedvoices
from soundboard.savedvoices import Store

ROBOT = {"pitch": {"on": True, "semitones": 4.0}, "echo": {"on": False}}


def test_voices_round_trip_in_order(app_dir):
    s = Store()
    s.put("Zed", ROBOT)
    s.put("Alpha", {"pitch": {"on": True, "semitones": -3.0}})
    again = Store()
    assert list(again.voices) == ["Zed", "Alpha"]
    assert again.voices["Zed"] == ROBOT
    assert savedvoices.path() == app_dir / "voices.json"


def test_put_replaces_whatever_the_capitals_and_keeps_its_place(app_dir):
    s = Store()
    s.put("One", ROBOT)
    s.put("Two", ROBOT)
    assert s.put("one", {"pitch": {"on": True, "semitones": 1.0}}) == "One"
    assert list(s.voices) == ["One", "Two"]
    assert s.voices["One"]["pitch"]["semitones"] == 1.0


def test_names_are_one_short_line():
    assert savedvoices.clean_name("  my \n  voice ") == "my voice"
    assert len(savedvoices.clean_name("x" * 100)) == savedvoices.MAX_NAME
    assert savedvoices.clean_name(None) == ""


def test_free_name(app_dir):
    s = Store()
    s.put("My voice", ROBOT)
    assert s.free_name("My voice") == "My voice (2)"
    s.put("My voice (2)", ROBOT)
    assert s.free_name("my voice") == "my voice (3)"
    assert s.free_name("Other") == "Other"


def test_remove_goes_to_the_bin_and_restore_puts_it_back_in_place(app_dir):
    s = Store()
    for n in ("A", "B", "C"):
        s.put(n, ROBOT)
    item = s.remove("B")
    assert list(s.voices) == ["A", "C"] and item.index == 1
    assert [i.name for i in Store().items()] == ["B"]          # kept on disk
    taken = s.take(item.id)
    assert s.restore(taken, taken.index) == "B"
    assert list(s.voices) == ["A", "B", "C"] and not s.deleted


def test_restore_under_a_free_name_if_its_been_reused(app_dir):
    s = Store()
    s.put("A", ROBOT)
    item = s.remove("A")
    s.put("A", {})
    assert s.restore(s.take(item.id)) == "A (2)"


def test_the_bin_forgets_after_keep_days(app_dir):
    s = Store()
    s.put("Old", ROBOT)
    s.remove("Old")
    s.deleted[0].when = time.time() - (savedvoices.KEEP_DAYS + 1) * 86400
    s.save()
    assert Store().deleted == []


def test_a_damaged_file_is_set_aside(app_dir):
    savedvoices.path().write_text("{not json", encoding="utf-8")
    s = Store()
    assert s.voices == {} and s.writable
    assert list(app_dir.glob("voices.json.broken-*"))


def test_damaged_entries_are_dropped(app_dir):
    savedvoices.path().write_text(json.dumps({"voices": [
        {"name": "Good", "effects": {"pitch": {"on": True, "semitones": 2}}},
        {"name": "", "effects": {}}, "junk", {"name": "No effects"},
        {"name": "good", "effects": {}},                     # the same name again
        {"name": "Bad numbers", "effects": {"pitch": {"on": "yes", "semitones": "x"}}},
    ], "deleted": [{"name": "no id"}, 5]}), encoding="utf-8")
    s = Store()
    assert list(s.voices) == ["Good", "Bad numbers"]
    assert s.voices["Bad numbers"] == {"pitch": {}}
    assert s.deleted == []


def test_an_unreadable_file_is_never_written_over(app_dir, monkeypatch):
    savedvoices.path().write_text(json.dumps({"voices": [{"name": "Keep", "effects": {}}]}),
                                  encoding="utf-8")
    real = type(savedvoices.path()).read_text

    def locked(self, *a, **k):
        if self.name == "voices.json":
            raise PermissionError("locked")
        return real(self, *a, **k)
    with monkeypatch.context() as m:
        m.setattr(type(savedvoices.path()), "read_text", locked)
        s = Store()
        assert not s.writable
        s.put("New", ROBOT)
    assert list(Store().voices) == ["Keep"]


def test_backup_settings_carry_them_and_merge_adds_only_new_names(app_dir):
    Store().put("Mine", ROBOT)
    out = backup.settings_of(library.Config())
    assert out[backup.SAVED_VOICES] == [{"name": "Mine", "effects": ROBOT}]
    # an older version importing these settings skips the unknown key
    assert backup.SAVED_VOICES not in library.Config.__dataclass_fields__
    s = Store()
    s.put("Here", {})
    assert s.merge([{"name": "here", "effects": ROBOT},
                    {"name": "New", "effects": ROBOT}, "junk"]) == 1
    assert list(s.voices) == ["Mine", "Here", "New"] and s.voices["Here"] == {}


def test_no_saved_voices_no_key_in_the_backup(app_dir):
    assert backup.SAVED_VOICES not in backup.settings_of(library.Config())
