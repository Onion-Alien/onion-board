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
    import ast
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    one_off = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and getattr(n.targets[0], "id", "") == "_ONE_OFF")
    app = (root / "soundboard" / "app.py").read_text(encoding="utf-8")
    body = app[app.index("\ndef main():"):]
    early = body[:body.index("from soundboard import bootmark")]   # before it's cleared
    handled = set(re.findall(r'if "(--[a-z-]+)" in sys\.argv:', early))
    assert handled, "app.main()'s one-off branches not found"
    assert handled <= set(one_off), sorted(handled - set(one_off))
