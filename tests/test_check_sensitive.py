"""scripts/check_sensitive.py: full-history scans stream blobs in bounded batches."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("check_sensitive",
                                                  ROOT / "scripts" / "check_sensitive.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_history_blobs_reads_in_bounded_batches(monkeypatch):
    """Full-history scans have >10 GB of blobs; reading them all in one `git cat-file
    --batch` call OOM-killed the nightly CI runner. Each call must stay bounded."""
    cs = _load()
    files = {
        "a" * 40: ("a.txt", b"x" * 60),
        "b" * 40: ("b.txt", b"y" * 60),
        "c" * 40: ("c.txt", b"z" * 60),
    }

    def fake_git(*args: str) -> bytes:
        assert args[:2] == ("rev-list", "--objects")
        return "\n".join(f"{sha} {path}" for sha, (path, _) in files.items()).encode()

    batch_calls: list[list[str]] = []

    def fake_git_in(stdin: bytes, *args: str) -> bytes:
        shas = [s for s in stdin.decode().splitlines() if s]
        if args[1].startswith("--batch-check"):
            return "\n".join(f"{s} blob {len(files[s][1])}" for s in shas).encode()
        assert args == ("cat-file", "--batch")
        batch_calls.append(shas)
        out = bytearray()
        for s in shas:
            data = files[s][1]
            out += f"{s} blob {len(data)}\n".encode() + data + b"\n"
        return bytes(out)

    monkeypatch.setattr(cs, "git", fake_git)
    monkeypatch.setattr(cs, "git_in", fake_git_in)
    monkeypatch.setattr(cs, "BATCH_BYTES", 100, raising=False)

    got = list(cs.history_blobs(["--all"]))
    assert got == [(path, sha, data) for sha, (path, data) in files.items()]
    assert len(batch_calls) == 3
    assert all(len(c) == 1 for c in batch_calls)
