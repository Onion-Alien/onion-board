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
