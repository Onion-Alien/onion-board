"""monkeypatch.undo() in a test also undoes every fixture's patches, the autouse guard
that keeps tests out of the real %APPDATA%\\OnionBoard included: a test that saved after
it wrote its temp board into the developer's real settings."""
from pathlib import Path


def test_no_test_calls_monkeypatch_undo():
    here = Path(__file__).parent
    bad = [f"{p.name}:{n}" for p in sorted(here.rglob("*.py")) if p.name != Path(__file__).name
           for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
           if "monkeypatch.undo()" in line]
    assert not bad, f"undo only your own patch instead: {bad}"
