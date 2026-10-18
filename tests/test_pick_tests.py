"""scripts/pick_tests.py: which test files a PR's changes run on CI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pick_tests  # noqa: E402


def test_what_every_test_runs_on_runs_them_all():
    for f in ("tests/conftest.py", "pyproject.toml", "requirements.txt",
              ".github/workflows/checks.yml"):
        assert pick_tests.pick(["CHANGELOG.md", f]) == ["tests"]


def test_a_change_no_test_is_about_runs_none():
    assert pick_tests.pick(["LICENSE"]) == []
    # the changelog runs only the check that it agrees with __init__.py's version
    assert pick_tests.pick(["CHANGELOG.md"]) == ["tests/test_release.py"]


def test_a_module_runs_the_tests_that_import_it():
    picked = pick_tests.pick(["soundboard/ui/sidebar.py"])
    assert "tests/test_sidebar_reorder.py" in picked
    assert "tests/test_dsp.py" not in picked


def test_a_module_a_package_hands_on_runs_the_tests_of_the_package():
    # test_remote imports soundboard.voicefx, whose __init__ re-exports
    # voicefx.builtin's PRESETS: a new preset changed its "did you mean" answer (#702)
    picked = pick_tests.pick(["soundboard/voicefx/builtin.py"])
    assert {"tests/test_voicefx.py", "tests/test_remote.py"} <= set(picked)
    assert "tests/test_dsp.py" not in picked


def test_a_test_file_runs_itself_and_the_tests_that_import_it():
    picked = pick_tests.pick(["tests/test_mainwindow.py"])
    assert {"tests/test_mainwindow.py", "tests/test_audit_main.py"} <= set(picked)


def test_a_file_the_tests_read_runs_them_by_its_name():
    assert "tests/test_design_doc.py" in pick_tests.pick(["docs/DESIGN.md"])
    assert "tests/test_i18n.py" in pick_tests.pick(["assets/lang/de.json"])
    assert "tests/test_directmic.py" in pick_tests.pick(["native/directmic/obmic.cpp"])


def test_local_adds_uncommitted_and_new_files(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        return {"merge-base": ["abc"], "diff": ["soundboard/a.py", "tests/test_b.py"],
                "ls-files": ["soundboard/new.py", "soundboard/a.py"]}[args[0]]

    monkeypatch.setattr(pick_tests, "_git", fake_git)
    assert pick_tests.changed_files("origin/main", local=True) == [
        "soundboard/a.py", "soundboard/new.py", "tests/test_b.py"]
    assert ("diff", "--name-only", "--no-renames", "abc") in calls


def test_a_hub_runs_them_all():
    # signals and lazy imports reach these from everywhere: no import line says which
    # tests a change to one can break, so the whole suite runs
    for f in sorted(pick_tests.HUBS):
        assert pick_tests.pick([f]) == ["tests"], f
    assert pick_tests.pick(["soundboard/ui/sidebar.py"]) != ["tests"]


def test_imports_inside_functions_and_by_name_are_followed(tmp_path, monkeypatch):
    (tmp_path / "soundboard").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    for name in ("__init__", "usage", "theme", "lazy", "other"):
        (tmp_path / "soundboard" / f"{name}.py").write_text("", encoding="utf-8")
    tests = {
        "test_local": "def test_it():\n    from soundboard import usage\n",
        "test_method": "class T:\n    def test_it(self):\n"
                       "        import soundboard.theme\n",
        "test_byname": "import importlib\n\n\ndef test_it():\n"
                       "    importlib.import_module('soundboard.lazy')\n"
                       "    __import__('soundboard.theme')\n",
        "test_other": "from soundboard import other\n",
    }
    for name, text in tests.items():
        (tmp_path / "tests" / f"{name}.py").write_text(text, encoding="utf-8")
    monkeypatch.setattr(pick_tests, "ROOT", tmp_path)
    monkeypatch.setattr(pick_tests, "TESTS", tmp_path / "tests")
    assert pick_tests.pick(["soundboard/usage.py"]) == ["tests/test_local.py"]
    assert pick_tests.pick(["soundboard/theme.py"]) == [
        "tests/test_byname.py", "tests/test_method.py"]
    assert pick_tests.pick(["soundboard/lazy.py"]) == ["tests/test_byname.py"]


def test_times_come_from_the_runs_junit_reports(tmp_path):
    (tmp_path / "times-0").mkdir()
    (tmp_path / "times-0" / "junit.xml").write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.test_a" name="test_x" time="1.25"/>'
        '<testcase classname="tests.test_a.TestIt" name="test_y" time="0.5"/>'
        '<testcase classname="tests.test_b" name="test_z[1]" time="2"/>'
        '</testsuite></testsuites>', encoding="utf-8")
    reports = sorted(tmp_path.rglob("*.xml"))
    assert pick_tests.refresh_times(reports) == {"tests/test_a.py": 1.8,
                                                 "tests/test_b.py": 2.0}


def test_shards_caps_the_number_of_jobs(capsys):
    """main's run after a merge asks for fewer jobs (--shards=3): every test file still
    runs, in no more jobs than asked."""
    assert pick_tests.main(["pick_tests.py", "all", "--matrix", "--shards=3"]) == 0
    import json
    jobs = json.loads(capsys.readouterr().out)
    assert [j["shard"] for j in jobs] == ["1/3", "2/3", "3/3"]
    files = sorted(f for j in jobs for f in j["tests"].split())
    assert files == pick_tests.all_tests()
