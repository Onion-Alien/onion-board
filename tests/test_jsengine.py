"""The JavaScript engine yt-dlp gets for YouTube's player challenge (soundboard.online.jsengine)."""
from __future__ import annotations

import pytest

from soundboard.online import jsengine, ytdl


@pytest.fixture
def engines(monkeypatch, tmp_path):
    """Fake installed engines {name: version} and an optional bundled QuickJS."""
    installed: dict[str, tuple] = {}
    qjs_dir = tmp_path / "qjs"
    qjs_dir.mkdir()
    monkeypatch.setattr(jsengine, "QJS_DIR", qjs_dir)
    monkeypatch.setattr(jsengine.shutil, "which",
                        lambda name: f"C:/fake/{name}.exe" if name in installed else None)

    def version(exe, quickjs=False):
        if quickjs:
            return (0, 17, 0)
        return installed.get(exe.rsplit("/", 1)[1].removesuffix(".exe"))
    monkeypatch.setattr(jsengine, "_version", version)
    jsengine.forget()
    yield installed, qjs_dir
    jsengine.forget()


def bundle(qjs_dir):
    (qjs_dir / jsengine.QJS_EXE).write_bytes(b"MZ")


def test_order_deno_node_bun_then_quickjs(engines):
    installed, qjs_dir = engines
    bundle(qjs_dir)
    installed.update(deno=(2, 5, 0), node=(24, 1, 0), bun=(1, 3, 0))
    assert [e.name for e in jsengine.detect()] == ["deno", "node", "bun", "quickjs"]
    del installed["deno"]
    assert [e.name for e in jsengine.detect()] == ["node", "bun", "quickjs"]
    del installed["node"]
    assert [e.name for e in jsengine.detect()] == ["bun", "quickjs"]
    del installed["bun"]
    assert [e.name for e in jsengine.detect()] == ["quickjs"]


def test_too_old_engines_are_skipped(engines):
    installed, qjs_dir = engines
    bundle(qjs_dir)
    installed.update(deno=(2, 2, 9), node=(20, 11, 0), bun=(1, 2, 11))
    assert [e.name for e in jsengine.detect()] == ["bun", "quickjs"]


def test_runtimes_best_engine_with_quickjs_behind_it(engines):
    installed, qjs_dir = engines
    bundle(qjs_dir)
    installed.update(node=(22, 0, 0))
    qjs = str(qjs_dir / jsengine.QJS_EXE)
    assert jsengine.runtimes() == {"node": {"path": "C:/fake/node.exe"},
                                   "quickjs": {"path": qjs}}


def test_bun_goes_alone(engines):
    # yt-dlp ranks QuickJS above Bun: passing both would pick QuickJS
    installed, qjs_dir = engines
    bundle(qjs_dir)
    installed.update(bun=(1, 3, 0))
    assert jsengine.runtimes() == {"bun": {"path": "C:/fake/bun.exe"}}


def test_only_the_bundled_quickjs(engines):
    _installed, qjs_dir = engines
    bundle(qjs_dir)
    assert jsengine.runtimes() == {"quickjs": {"path": str(qjs_dir / jsengine.QJS_EXE)}}


def test_missing_qjs_and_no_engine_goes_without(engines):
    assert jsengine.bundled_qjs() is None
    assert jsengine.runtimes() == {}
    assert ytdl._opts()["js_runtimes"] == {}


def test_detected_once_per_run(engines, monkeypatch):
    calls = []
    monkeypatch.setattr(jsengine, "detect", lambda: calls.append(1) or [])
    jsengine.runtimes()
    ytdl._opts()
    assert calls == [1]


def test_fake_qjs_is_not_used(monkeypatch, tmp_path):
    """A qjs.exe that isn't QuickJS (won't start, or says something else) is left out."""
    monkeypatch.setattr(jsengine, "QJS_DIR", tmp_path)
    monkeypatch.setattr(jsengine.shutil, "which", lambda name: None)
    (tmp_path / jsengine.QJS_EXE).write_bytes(b"not a program")
    jsengine.forget()
    try:
        assert jsengine.detect() == []
        assert jsengine.runtimes() == {}
    finally:
        jsengine.forget()


def test_version_parsing(monkeypatch):
    class Done:
        def __init__(self, out, err=""):
            self.stdout, self.stderr = out, err
    outs = {"node": Done("v24.18.0\n"), "deno": Done("deno 2.5.1 (stable, release)\n"),
            "qjs": Done("QuickJS-ng version 0.17.0\nusage: qjs\n"),
            "other": Done("usage: something 1.2\n")}
    monkeypatch.setattr(jsengine.subprocess, "run", lambda cmd, **kw: outs[cmd[0]])
    assert jsengine._version("node") == (24, 18, 0)
    assert jsengine._version("deno") == (2, 5, 1)
    assert jsengine._version("qjs", quickjs=True) == (0, 17, 0)
    assert jsengine._version("other", quickjs=True) is None

    def boom(cmd, **kw):
        raise OSError("not a valid Win32 application")
    monkeypatch.setattr(jsengine.subprocess, "run", boom)
    assert jsengine._version("node") is None
