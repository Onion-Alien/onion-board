"""scripts/release.py: the version bump, and the version agreeing everywhere."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release  # noqa: E402

LOG = "# Changelog\n\nNot released yet: changelog.d/\n\n## 1.0.0 - 2026-01-01\n\n- Old.\n"


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
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **k: type(
        "R", (), {"returncode": 0, "stdout": ""})())   # no git, no i18n/docs scripts
    with pytest.raises(SystemExit, match="isn't newer"):
        release.main(["1.0.0"])
    assert release.main(["1.0.1", "--dry-run"]) == 0
    assert log.read_text(encoding="utf-8") == LOG   # dry run wrote nothing
    assert release.main(["1.0.1"]) == 0
    assert "## 1.0.1 \u2014 " in log.read_text(encoding="utf-8")
    assert "- A.\n\n## 1.0.0" in log.read_text(encoding="utf-8")
    assert sorted(p.name for p in frags.iterdir()) == ["README.md"]
    assert '"1.0.1"' in init.read_text(encoding="utf-8")


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
