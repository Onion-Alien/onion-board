"""bootmark.py: the start-up breadcrumb that catches a start that never made it."""
from __future__ import annotations

import os

from soundboard import bootmark


def test_a_leftover_breadcrumb_names_the_run(tmp_path):
    assert bootmark.read(tmp_path) == ("", 0)   # nothing to say
    path = bootmark.mark("1.9.28", tmp_path)
    assert path == tmp_path / bootmark.NAME
    assert bootmark.read(tmp_path) == ("1.9.28", os.getpid())
    bootmark.clear(tmp_path)
    assert bootmark.read(tmp_path) == ("", 0)
    assert not (tmp_path / bootmark.NAME).exists()


def test_start_reads_the_last_run_before_leaving_this_one(tmp_path):
    bootmark.mark("1.9.27", tmp_path)     # the run before, still here
    bootmark.start("1.9.28", tmp_path)    # this run: read then replace
    assert bootmark.previous() == ("1.9.27", os.getpid())
    assert bootmark.read(tmp_path) == ("1.9.28", os.getpid())
    bootmark.clear(tmp_path)              # this run reached its running state
    bootmark.start("1.9.28", tmp_path)    # so the next run has nothing to explain
    assert bootmark.previous() == ("", 0)


def test_a_broken_or_odd_file_is_ignored(tmp_path):
    for text in ("not json", "", "{}", '{"version": ""}', '{"version": "<script>"}',
                 '{"version": 12}'):
        (tmp_path / bootmark.NAME).write_text(text, encoding="utf-8")
        assert bootmark.read(tmp_path) == ("", 0)


def test_clear_is_harmless_when_there_is_nothing(tmp_path):
    bootmark.clear(tmp_path)
    bootmark.clear(tmp_path)


def test_every_one_off_command_leaves_no_breadcrumb():
    """Each command app.main() handles and exits before the breadcrumb is cleared (the
    installer's --install-addon, say) is in main.py's _ONE_OFF, or the next normal start
    counts a startup-failed for a run that only did its job."""
    import re
    from pathlib import Path

    from soundboard import app
    assert list(app.ONE_OFF_COMMANDS) == list(bootmark.ONE_OFF)
    root = Path(__file__).resolve().parent.parent
    assert "bootmark.ONE_OFF" in (root / "main.py").read_text(encoding="utf-8")
    # nothing else in main() looks at a "--flag" before the breadcrumb is cleared, however
    # it's written (a one-off command there would leave a breadcrumb behind)
    src = (root / "soundboard" / "app.py").read_text(encoding="utf-8")
    body = src[src.index("\ndef main():"):]
    early = body[:body.index("from soundboard import bootmark")]
    assert "ONE_OFF_COMMANDS" in early
    assert not re.findall(r'"--[a-z-]+"', early), re.findall(r'"--[a-z-]+"', early)
