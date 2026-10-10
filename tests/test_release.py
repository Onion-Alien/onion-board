"""scripts/release.py: the version bump, and the version agreeing everywhere."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release  # noqa: E402

LOG = "# Changelog\n\n## Unreleased\n\n- A thing.\n\n## 1.0.0 - 2026-01-01\n\n- Old.\n"


def test_dates_unreleased_and_opens_a_fresh_one():
    out = release.date_changelog(LOG, "1.0.1", "2026-02-02")
    assert out == ("# Changelog\n\n## Unreleased\n\n## 1.0.1 \u2014 2026-02-02\n\n- A thing.\n\n"
                   "## 1.0.0 - 2026-01-01\n\n- Old.\n")


def test_refuses_an_empty_unreleased_or_a_repeat():
    with pytest.raises(SystemExit, match="empty"):
        release.date_changelog("## Unreleased\n\n## 1.0.0 - x\n", "1.0.1", "d")
    with pytest.raises(SystemExit, match="already"):
        release.date_changelog(LOG, "1.0.0", "d")


def test_bumps_init_and_wants_a_newer_version(monkeypatch, tmp_path):
    assert release.bump_init('x = 1\n__version__ = "1.0.0"\n', "1.0.1") == \
        'x = 1\n__version__ = "1.0.1"\n'
    init, log = tmp_path / "__init__.py", tmp_path / "CHANGELOG.md"
    init.write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    log.write_text(LOG, encoding="utf-8")
    monkeypatch.setattr(release, "INIT", init)
    monkeypatch.setattr(release, "CHANGELOG", log)
    with pytest.raises(SystemExit, match="isn't newer"):
        release.main(["1.0.0"])
    assert release.main(["1.0.1", "--dry-run"]) == 0
    assert log.read_text(encoding="utf-8") == LOG   # dry run wrote nothing


def test_version_matches_the_newest_changelog_release():
    """__init__.py and CHANGELOG.md drift apart when a release is cut by hand."""
    from soundboard import __version__
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## (\d[\d.]*)\s", text, flags=re.M).group(1)
    assert newest == __version__, "bump both with scripts/release.py"
