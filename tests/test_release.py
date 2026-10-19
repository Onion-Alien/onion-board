"""scripts/release.py: the version bump, and the version agreeing everywhere."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release  # noqa: E402

# the action's own "Version" is indented deeper: only the plugin's moves
MANIFEST = ('{\n  "Name": "X",\n  "Version": "1.0.0.0",\n'
            '  "Actions": [{\n    "Version": "9"\n  }]\n}\n')
LOG = "# Changelog\n\nNot released yet: changelog.d/\n\n## 1.0.0 - 2026-01-01\n\n- Old.\n"


def fake_run(head="abc", main="abc", runs='[{"status":"completed","conclusion":"success"}]'):
    """subprocess.run with git rev-parse answering head/main and gh answering runs."""
    def run(cmd, *a, **k):
        out = ""
        if cmd[:2] == ["git", "rev-parse"]:
            out = head if cmd[2] == "HEAD" else main
        elif cmd[0] == "gh":
            out = runs
        return type("R", (), {"returncode": 0, "stdout": out, "stderr": ""})()
    return run


def test_puts_the_entries_under_the_new_version():
    out = release.date_changelog(LOG, "1.0.1", "2026-02-02", ["- B.", "- A,\n  two lines."])
    assert out == ("# Changelog\n\nNot released yet: changelog.d/\n\n"
                   "## 1.0.1 \u2014 2026-02-02\n\n- B.\n- A,\n  two lines.\n\n"
                   "## 1.0.0 - 2026-01-01\n\n- Old.\n")


def test_refuses_no_entries_a_repeat_or_an_unreleased_section():
    with pytest.raises(SystemExit, match="no entries"):
        release.date_changelog(LOG, "1.0.1", "d", ["", ""])
    with pytest.raises(SystemExit, match="already"):
        release.date_changelog(LOG, "1.0.0", "d", ["- A."])
    with pytest.raises(SystemExit, match="changelog.d"):
        release.date_changelog("## Unreleased\n\n- A.\n" + LOG, "1.0.1", "d", ["- B."])


def test_release_moves_the_fragments_into_the_changelog(monkeypatch, tmp_path):
    assert release.bump_init('x = 1\n__version__ = "1.0.0"\n', "1.0.1") == \
        'x = 1\n__version__ = "1.0.1"\n'
    init, log, frags = tmp_path / "__init__.py", tmp_path / "CHANGELOG.md", tmp_path / "f"
    frags.mkdir()
    init.write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    log.write_text(LOG, encoding="utf-8")
    (frags / "README.md").write_text("# not an entry\n", encoding="utf-8")
    (frags / "a.md").write_text("- A.\n", encoding="utf-8")
    monkeypatch.setattr(release, "INIT", init)
    monkeypatch.setattr(release, "CHANGELOG", log)
    monkeypatch.setattr(release, "FRAGMENTS", frags)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(MANIFEST, encoding="utf-8")
    monkeypatch.setattr(release, "MANIFEST", manifest)
    monkeypatch.setattr(release.subprocess, "run", fake_run())   # no git/gh/i18n/docs
    with pytest.raises(SystemExit, match="isn't newer"):
        release.main(["1.0.0"])
    assert release.main(["1.0.1", "--dry-run"]) == 0
    assert log.read_text(encoding="utf-8") == LOG   # dry run wrote nothing
    assert release.main(["1.0.1"]) == 0
    assert "## 1.0.1 \u2014 " in log.read_text(encoding="utf-8")
    assert "- A.\n\n## 1.0.0" in log.read_text(encoding="utf-8")
    assert sorted(p.name for p in frags.iterdir()) == ["README.md"]
    assert '"1.0.1"' in init.read_text(encoding="utf-8")
    assert manifest.read_text(encoding="utf-8") == MANIFEST.replace("1.0.0.0", "1.0.1.0")


OK = {"status": "completed", "conclusion": "success"}
BAD = {"status": "completed", "conclusion": "failure"}
GOING = {"status": "in_progress", "conclusion": ""}


def test_ci_verdict_needs_a_passed_checks_run():
    assert release.ci_verdict([OK]) is None
    assert release.ci_verdict([BAD, OK]) is None   # a later run (dispatch) passed
    assert "no 'checks' run" in release.ci_verdict([])
    assert "still going" in release.ci_verdict([GOING])
    assert "didn't pass (failure)" in release.ci_verdict([BAD])
    assert "didn't pass (cancelled)" in release.ci_verdict(
        [{"status": "completed", "conclusion": "cancelled"}])


def _release_dir(monkeypatch, tmp_path):
    init, log, frags = tmp_path / "__init__.py", tmp_path / "CHANGELOG.md", tmp_path / "f"
    frags.mkdir()
    init.write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    log.write_text(LOG, encoding="utf-8")
    (frags / "a.md").write_text("- A.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(MANIFEST, encoding="utf-8")
    for name, path in (("INIT", init), ("CHANGELOG", log), ("FRAGMENTS", frags),
                       ("MANIFEST", manifest)):
        monkeypatch.setattr(release, name, path)
    return log


@pytest.mark.parametrize("kw, why", [
    ({"runs": "[]"}, "no 'checks' run"),
    ({"runs": '[{"status":"completed","conclusion":"failure"}]'}, "didn't pass"),
    ({"runs": '[{"status":"queued","conclusion":""}]'}, "still going"),
    ({"head": "abc", "main": "def"}, "isn't origin/main"),
])
def test_release_refuses_without_green_ci_on_origin_main(monkeypatch, tmp_path, kw, why):
    log = _release_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(release.subprocess, "run", fake_run(**kw))
    for args in (["1.0.1", "--dry-run"], ["1.0.1"]):
        with pytest.raises(SystemExit, match=why):
            release.main(args)
    assert log.read_text(encoding="utf-8") == LOG   # nothing written


def test_skip_ci_check_warns_but_still_needs_origin_main(monkeypatch, tmp_path, capsys):
    _release_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(release.subprocess, "run", fake_run(runs="[]"))
    assert release.main(["1.0.1", "--dry-run", "--skip-ci-check"]) == 0
    assert "WARNING: --skip-ci-check" in capsys.readouterr().out
    monkeypatch.setattr(release.subprocess, "run", fake_run(main="def"))
    with pytest.raises(SystemExit, match="isn't origin/main"):
        release.main(["1.0.1", "--dry-run", "--skip-ci-check"])


def test_changelog_has_no_unreleased_section():
    """Unreleased changes go in changelog.d/<branch>.md, one file each, so stacked
    pull requests don't all edit the top of CHANGELOG.md and conflict."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert not re.search(r"^## Unreleased\b", text, flags=re.M), (
        "put your entry in changelog.d/<branch-name>.md instead of CHANGELOG.md "
        "(see changelog.d/README.md)")


def test_changelog_d_entries_are_bullets():
    for p in release.fragment_files():
        text = release.read_fragment(p)
        assert text.startswith("- "), f"{p.name}: start each entry with '- '"
        assert "## " not in text, f"{p.name}: no headings, just '- ' lines"
        assert re.fullmatch(r"[\w.-]+\.md", p.name), f"{p.name}: use letters, digits, - _ ."


def test_version_matches_the_newest_changelog_release():
    """__init__.py and CHANGELOG.md drift apart when a release is cut by hand."""
    from soundboard import __version__
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## (\d[\d.]*)\s", text, flags=re.M).group(1)
    assert newest == __version__, "bump both with scripts/release.py"


def test_stream_deck_plugin_version_matches_the_app():
    """build.ps1 packs the plugin for each release; Stream Deck only offers an update
    when its Version goes up, so release.py moves it with __version__."""
    import json
    from soundboard import __version__
    version = json.loads(release.MANIFEST.read_text(encoding="utf-8"))["Version"]
    assert version == f"{__version__}.0", "bump both with scripts/release.py"
