"""The measured child's side of the line to the runner.

Messages go out on the process's original stdout as `@@perf {json}` lines (the
app's own prints are sent to stderr instead, so they can't get in the way). A
`mark` waits for the runner's "ok" on stdin: by then the runner has taken its
snapshot, so a phase starts and ends exactly where the child says.
"""
from __future__ import annotations

import json
import os
import sys
import time

PREFIX = "@@perf "

_out = None


def open_line():
    """Keep the real stdout for messages; everything printed goes to stderr."""
    global _out
    if _out is None:
        _out = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr
    return _out


def send(ev: str, **data):
    out = open_line()
    data["ev"] = ev
    data.setdefault("t", time.perf_counter())
    out.write(PREFIX + json.dumps(data, default=str) + "\n")
    out.flush()


def mark(ev: str, **data) -> None:
    """Send and wait until the runner has measured (its "ok")."""
    send(ev, wait=True, **data)
    line = sys.stdin.readline()
    if not line:   # the runner went away: nothing left to measure for
        os._exit(2)


def parse(line: str) -> dict | None:
    """A message line as the runner reads it; None for anything else."""
    line = line.strip()
    if not line.startswith(PREFIX):
        return None
    try:
        msg = json.loads(line[len(PREFIX):])
    except ValueError:
        return None
    return msg if isinstance(msg, dict) and "ev" in msg else None
