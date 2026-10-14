"""scripts/merge_json.py: the translation catalogs merge by key, so two branches that
both add texts at the end of every catalog no longer conflict."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import merge_json as mj  # noqa: E402


def test_both_sides_add_texts():
    base = {"_meta": {"name": "Deutsch"}, "Ready": "Bereit"}
    ours = {**base, "Stop": "Stopp"}
    theirs = {**base, "Play": "Abspielen"}
    out, clashes = mj.merge(base, ours, theirs)
    assert clashes == []
    assert list(out) == ["_meta", "Ready", "Stop", "Play"]


def test_one_side_changes_the_other_removes_something_else():
    base = {"a": "1", "b": "2", "c": "3"}
    out, clashes = mj.merge(base, {"a": "1", "b": "2", "c": "drei"}, {"a": "1", "c": "3"})
    assert clashes == [] and out == {"a": "1", "c": "drei"}


def test_change_against_removal_is_a_clash():
    base = {"b": "2"}
    _, clashes = mj.merge(base, {"b": "two"}, {})
    assert clashes == ["b"]


def test_same_text_translated_differently_is_a_clash(tmp_path):
    files = []
    for name, value in (("O", "Bereit"), ("A", "Fertig"), ("B", "Los")):
        p = tmp_path / name
        p.write_text(json.dumps({"Ready": value}), encoding="utf-8")
        files.append(str(p))
    assert mj.main(["merge_json.py", *files]) == 1
    assert json.loads(Path(files[1]).read_text(encoding="utf-8")) == {"Ready": "Fertig"}


def test_conflict_markers_are_left_to_a_person(tmp_path):
    o, a, b = (tmp_path / n for n in "OAB")
    o.write_text("{}", encoding="utf-8")
    a.write_text("<<<<<<< ours\n{}", encoding="utf-8")
    b.write_text("{}", encoding="utf-8")
    assert mj.main(["merge_json.py", str(o), str(a), str(b)]) == 1


def test_keeps_crlf_and_the_extract_format(tmp_path):
    o, a, b = (tmp_path / n for n in "OAB")
    o.write_bytes(b'{\r\n  "x": "1"\r\n}\r\n')
    a.write_bytes('{\r\n  "x": "1",\r\n  "Grüße": "ü"\r\n}\r\n'.encode())
    b.write_bytes(b'{\r\n  "x": "1",\r\n  "y": "2"\r\n}\r\n')
    assert mj.main(["merge_json.py", str(o), str(a), str(b)]) == 0
    assert a.read_bytes() == '{\r\n  "x": "1",\r\n  "Grüße": "ü",\r\n  "y": "2"\r\n}\r\n'.encode()


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_real_git_merge_of_two_branches_adding_texts(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    def cat(d):
        (tmp_path / "de.json").write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("config", "core.autocrlf", "false")
    script = (ROOT / "scripts" / "merge_json.py").as_posix()
    driver = f'"{Path(sys.executable).as_posix()}" "{script}" %O %A %B'
    git("config", "merge.langjson.driver", driver)
    (tmp_path / ".gitattributes").write_text("*.json merge=langjson\n", encoding="utf-8")
    cat({"_meta": {"name": "Deutsch"}, "Ready": "Bereit"})
    git("add", ".")
    git("commit", "-qm", "base")
    git("switch", "-qc", "two")
    cat({"_meta": {"name": "Deutsch"}, "Ready": "Bereit", "Play": "Abspielen"})
    git("commit", "-qam", "theirs")
    git("switch", "-q", "main")
    cat({"_meta": {"name": "Deutsch"}, "Ready": "Bereit", "Stop": "Stopp"})
    git("commit", "-qam", "ours")
    git("merge", "-q", "--no-edit", "two")  # check=True: a conflict fails here
    assert json.loads((tmp_path / "de.json").read_text(encoding="utf-8")) == {
        "_meta": {"name": "Deutsch"}, "Ready": "Bereit", "Stop": "Stopp", "Play": "Abspielen"}
