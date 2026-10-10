"""Old and half-swapped add-on copies in %APPDATA%\\OnionBoard are cleaned at start-up:
the newest one per add-on is kept, the folder an add-on runs from never goes, and
nothing that isn't an add-on copy is touched."""
import json
import os

from soundboard import modules


def _copy(folder, module_id, age, kind="remote"):
    folder.mkdir(parents=True)
    (folder / "module.json").write_text(json.dumps(
        {"id": module_id, "name": module_id, "version": "1.0", "kind": kind}), "utf-8")
    (folder / "pkg").mkdir()
    (folder / "pkg" / "a.py").write_text("x = 1\n", "utf-8")
    t = 1_700_000_000 + age
    os.utime(folder, (t, t))
    return folder


def test_old_copies_pruned_newest_kept(tmp_path):
    app_dir = tmp_path
    mods = app_dir / "modules"
    live_watch = _copy(mods / "onion-watch", "onion-watch", 100)
    live_pocket = _copy(mods / "onion-pocket", "onion-pocket", 100)
    watch_old = [_copy(app_dir / n, "onion-watch", age) for n, age in [
        ("onion-watch-old", 1), ("onion-watch-old2", 2), ("onion-watch-old3", 3),
        ("onion-watch-old-20261005104859", 4), ("onion-watch-old-1791149972606", 5),
        ("onion-watch-staged-069", 6)]]
    newest_watch = _copy(app_dir / "onion-watch-old-20261007233706591", "onion-watch", 50)
    in_modules = _copy(mods / "onion-watch-old-20261005112119891", "onion-watch", 99)
    pocket_old = _copy(app_dir / "onion-pocket-old-20261005111322", "onion-pocket", 1)
    newest_pocket = _copy(app_dir / "onion-pocket-old-20261005205304", "onion-pocket", 9)
    temps = [_copy(app_dir / "modules-new-1a2b3c4d" / "onion-watch.old", "onion-watch", 1)
             .parent, app_dir / "modules-old-5e6f7a8b"]
    temps[1].mkdir()
    for p in temps:
        os.utime(p, (1_700_000_000, 1_700_000_000))
    installing = app_dir / "modules-new-99999999"   # an install going on right now
    installing.mkdir()
    # not add-on copies: a user's folder, a name that only looks like one, a file
    others = [app_dir / "sounds", app_dir / "onion-watch-old-notes", app_dir / "radio-old"]
    for p in others:
        p.mkdir()
        (p / "keep.txt").write_text("mine", "utf-8")
    a_file = app_dir / "onion-watch-old.txt"
    a_file.write_text("mine", "utf-8")

    gone = modules.prune_leftovers(app_dir)

    assert gone == len(watch_old) + 1 + 1 + len(temps)
    for p in [*watch_old, in_modules, pocket_old, *temps]:
        assert not p.exists(), p
    for p in [live_watch, live_pocket, newest_watch, newest_pocket, installing, *others,
              a_file]:
        assert p.exists(), p
    assert modules.prune_leftovers(app_dir) == 0   # nothing more the second time


def test_folder_an_addon_runs_from_is_never_deleted(tmp_path):
    """No `modules\\onion-watch`: discovery picks the old copy in modules\\, so it's the
    one loaded; and a copy whose code is imported in this process stays too."""
    app_dir = tmp_path
    mods = app_dir / "modules"
    running = _copy(mods / "onion-watch-old-1", "onion-watch", 1)
    imported = _copy(app_dir / "onion-pocket-old-1", "onion-pocket", 1)
    _copy(app_dir / "onion-pocket-old-2", "onion-pocket", 2)
    in_use = _copy(app_dir / "modules-new-0badf00d" / "ai-voices", "ai-voices", 1).parent

    gone = modules.prune_leftovers(
        app_dir, loaded=[imported / "pkg" / "a.py", in_use / "ai-voices" / "pkg" / "a.py"])

    assert gone == 0
    assert running.exists() and imported.exists() and in_use.exists()


def test_missing_app_dir_is_fine(tmp_path):
    assert modules.prune_leftovers(tmp_path / "nope") == 0
