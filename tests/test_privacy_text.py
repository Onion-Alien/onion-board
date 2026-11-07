"""The privacy wording has to admit the mic set-up log, everywhere it's described."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_CLAIMS = (
    "Never your name or device info",
    "The only thing it sends us",
    "One thing goes out on its own",
    "logs never leave your PC",
)


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_app_text_no_longer_says_the_count_is_all_that_goes_out():
    for rel in ("soundboard/ui/settings/countdialog.py", "soundboard/ui/settings/privacy.py"):
        text = _source(rel)
        for claim in OLD_CLAIMS:
            assert claim not in text, f"{rel}: {claim}"


def test_settings_text_names_the_log():
    assert "one log if your mic's set-up fails" in _source("soundboard/ui/settings/privacy.py")


def test_privacy_page_describes_the_mic_log():
    text = _source("docs/PRIVACY.md")
    for claim in OLD_CLAIMS:
        assert claim not in text, claim
    assert "**The mic set-up log,**" in text
    assert "SECURITY.md#the-mic-set-up-log" in text


def test_readme_and_every_site_page_mention_it_with_the_count():
    pages = [ROOT / "README.md", *sorted((ROOT / "site").rglob("*.html"))]
    said = 0
    for page in pages:
        text = re.sub(r"\s+", " ", page.read_text(encoding="utf-8"))
        if "It never sends your name" in text:
            raise AssertionError(f"{page.name}: old footer")
        if "Onion Board sends an anonymous daily count" in text or page.name == "README.md":
            assert "one log if your mic's set-up fails" in text, page
            said += 1
    assert said >= 2
