"""docs/DESIGN.md stays true to the code: every colour token and code path it names
exists, so agents following it don't reach for things that aren't there."""
import re
from pathlib import Path

from soundboard import theme

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")


def _front_matter() -> str:
    m = re.match(r"---\n(.*?)\n---\n", DOC, re.S)
    assert m, "DESIGN.md starts with a --- front matter block"
    return m.group(1)


def test_every_colour_token_it_names_is_in_every_theme():
    block = _front_matter().split("colour_roles:", 1)[1].split("\nradius:", 1)[0]
    names = set()
    for line in block.splitlines():
        value = line.split("#", 1)[0].partition(":")[2]
        value = re.sub(r"\(.*?\)", "", value)          # "(secondary)": words, not tokens
        names |= set(re.findall(r"[a-z][a-z0-9_]*\*?", value))
    assert {"accent", "panel", "bg", "muted"} <= names
    for theme_name, tokens in theme.THEMES.items():
        for n in names:
            if n.endswith("_*"):
                assert any(k.startswith(n[:-1]) for k in tokens), (theme_name, n)
            else:
                assert n in tokens, f"{theme_name} has no {n!r} (DESIGN.md colour_roles)"


def test_every_code_path_it_names_exists():
    paths = set(re.findall(r"`(soundboard/[\w/]+\.py)`", DOC))
    paths |= {f"soundboard/{p}" for p in re.findall(r"`(ui/[\w]+\.py)`", DOC)}
    assert paths
    missing = sorted(p for p in paths if not (ROOT / p).exists())
    # files from UI work still in review are allowed while their PRs are open
    pending = {"soundboard/ui/sidebar.py", "soundboard/ui/feedbackdialog.py"}
    assert not [p for p in missing if p not in pending], missing


def test_the_style_names_it_lists_are_in_the_app_style_sheet():
    names = re.findall(r"`(#[a-z]+)`", DOC) + re.findall(r"`\[([a-z]+)\]`", DOC)
    sheet = theme.STYLE.template
    assert names
    for n in names:
        assert (n if n.startswith("#") else f"[{n}=") in sheet, n
