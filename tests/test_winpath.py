"""Folder links Windows refuses to follow (error 448) don't stop imports."""
import os
import subprocess
import sys

import numpy as np
import pytest
import soundfile as sf

from soundboard import errors, library, winpath

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")


def _junction(link, target):
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                   check=True, capture_output=True)


def _refuse_links(monkeypatch, link):
    """os.stat on anything through `link` fails like newer Windows 11 does."""
    real = os.stat
    pre = os.path.normcase(str(link))

    def stat(p, *a, **k):
        s = os.path.normcase(os.fspath(p))
        through = s.startswith(pre + os.sep) or (s == pre and k.get("follow_symlinks", True))
        if through:   # looking at the link itself (lstat) still works
            raise OSError(22, "The path cannot be traversed because it contains an "
                          "untrusted mount point", os.fspath(p), 448)
        return real(p, *a, **k)
    monkeypatch.setattr(os, "stat", stat)


def test_without_links_spells_out_a_junction(tmp_path):
    real = tmp_path / "real"
    (real / "sub").mkdir(parents=True)
    _junction(tmp_path / "link", real)
    got = winpath.without_links(tmp_path / "link" / "sub" / "a.wav")
    assert got == real / "sub" / "a.wav"
    assert winpath.without_links(real / "sub") == real / "sub"   # no links: unchanged


def test_usable_only_changes_refused_paths(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.wav").write_bytes(b"x")
    _junction(tmp_path / "link", real)
    assert winpath.usable(tmp_path / "link" / "a.wav") == tmp_path / "link" / "a.wav"
    assert winpath.usable(tmp_path / "nope") == tmp_path / "nope"
    _refuse_links(monkeypatch, tmp_path / "link")
    assert winpath.usable(tmp_path / "link" / "a.wav") == real / "a.wav"
    # a folder not made yet, under the refused link
    assert winpath.usable_dir(tmp_path / "link" / "new" / "deep") == real / "new" / "deep"


def test_import_from_behind_a_refused_link(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    t = np.linspace(0, 1, library.SR, dtype=np.float32)
    sf.write(real / "beep.wav", np.sin(2 * np.pi * 440 * t) * 0.3, library.SR)
    _junction(tmp_path / "link", real)
    _refuse_links(monkeypatch, tmp_path / "link")
    src = winpath.usable(tmp_path / "link" / "beep.wav")
    meta, _data = library.import_file(str(src), "#ffffff")
    assert meta.name == "beep" and os.path.isfile(meta.file)


def test_error_448_in_plain_words(tmp_path):
    e = OSError(22, "The path cannot be traversed", "x", 448)
    assert "folder link" in errors.plain(e)
    (tmp_path / "real").mkdir()
    _junction(tmp_path / "link", tmp_path / "real")
    e = OSError(22, "The path cannot be traversed", str(tmp_path / "link" / "a.wav"), 448)
    words = errors.plain(e)   # names the link and where it goes, so it can be fixed
    assert str(tmp_path / "link") in words and str(tmp_path / "real") in words
