"""Clean mic's Strong: DeepFilterNet, downloaded on first use (voicefx.deepfilter, the
Cleaner handing the mic to it, the card offering the download)."""
import os
import shutil
import threading
import time
import types

import numpy as np
import pytest

from soundboard.core import updates
from soundboard.speech import tts
from soundboard.voicefx import cleanmic, deepfilter
from test_cleanmic import FakeCleaner, _db, _noisy
from test_voicepanel import FakeEngine

F = deepfilter.FRAME
real_rnnoise = pytest.mark.skipif(
    not cleanmic.available(), reason="RNNoise not fetched (scripts/buildtools/fetch_rnnoise.py)")
# the real plugin DLL: ONIONBOARD_TEST_DEEPFILTER=<path to the downloaded DLL> (50 MB, not
# fetched by the tests)
REAL_DLL = os.environ.get("ONIONBOARD_TEST_DEEPFILTER", "")
real_dll = pytest.mark.skipif(not os.path.isfile(REAL_DLL),
                              reason="ONIONBOARD_TEST_DEEPFILTER isn't set to the plugin DLL")


class FakePlugin:
    """Halves each frame and answers it a frame late, as the real one does."""

    def __init__(self, hang: threading.Event | None = None):
        self.lock = threading.Lock()
        self.broken = ""
        self._last = np.zeros(F, np.float32)
        self.hang = hang
        self.runs = 0

    def delay(self):
        return F

    def run(self, frame):
        if self.hang is not None and self.runs >= 3:
            self.hang.wait()
        self.runs += 1
        out, self._last = self._last, np.asarray(frame, np.float32) * np.float32(0.5)
        return out


@pytest.fixture
def fake_plugin(monkeypatch):
    made = {}

    def plugin(use):
        p = made.get(use)
        if p is None:
            p = made[use] = FakePlugin()
        if p.broken:
            raise RuntimeError(p.broken)
        return p
    monkeypatch.setattr(deepfilter, "plugin", plugin)
    return made


def _ready(stream, timeout=5.0):
    end = time.monotonic() + timeout
    while stream.feed(np.zeros(0, np.float32)) is None and not stream.error:
        assert time.monotonic() < end, "Strong never started"
        time.sleep(0.005)


def _feed(stream, x, block):
    """Feed in blocks as the mic would, giving its thread a moment between them."""
    out = []
    for i in range(0, len(x), block):
        out.append(stream.feed(x[i:i + block]))
        time.sleep(0.002)
    return np.concatenate(out)


# ---------------------------------------------------------------- download
def test_strong_is_a_saved_strength():
    assert cleanmic.clean_settings({"on": True, "strength": "strong"}) == {
        "on": True, "strength": "strong"}


def test_download_is_the_pinned_file_into_the_app_folder(app_dir, monkeypatch):
    got = {}

    def fetch(url, sha, dest, trusted, max_size, what, size, progress, cancelled, feature):
        got.update(url=url, sha=sha, dest=dest, trusted=trusted, feature=feature)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"dll")
        progress(3, 3)
        return dest
    monkeypatch.setattr(updates, "fetch", fetch)
    seen = []
    assert not deepfilter.downloaded()
    path = deepfilter.download(lambda d, t: seen.append((d, t)), lambda: False)
    assert path == app_dir / "models" / "deepfilter" / deepfilter.NAME and deepfilter.downloaded()
    assert got["url"].startswith(got["trusted"][0]) and "Rikorose/DeepFilterNet" in got["url"]
    assert len(got["sha"]) == 64 and got["feature"] == "addons" and seen == [(3, 3)]


def test_remove_deletes_it_or_moves_it_aside_when_its_loaded(app_dir, monkeypatch):
    p = deepfilter.path()
    p.parent.mkdir(parents=True)
    p.write_bytes(b"dll")
    deepfilter.remove()
    assert not p.exists() and not deepfilter.downloaded()
    deepfilter.remove()                      # nothing there: fine
    p.write_bytes(b"dll")
    real_unlink = type(p).unlink

    def locked(self, *a, **k):
        if self.name == deepfilter.NAME:
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(type(p), "unlink", locked)
    deepfilter.remove()
    assert not deepfilter.downloaded()
    left = list(p.parent.glob(f"{deepfilter.NAME}.old-*"))
    assert len(left) == 1
    monkeypatch.setattr(type(p), "unlink", real_unlink)
    monkeypatch.setattr(updates, "fetch", lambda *a, **k: p)
    deepfilter.download()                    # the next download clears it
    assert not left[0].exists()


def test_failed_downloads_read_as_sentences():
    assert deepfilter.friendly(updates.UpdateError("the download failed (x)")) == \
        "The download failed (x)"
    assert "internet" in deepfilter.friendly(OSError("no route"))


# ---------------------------------------------------------------- the plugin's guard
def test_it_stops_long_before_the_plugin_would_end_the_app(monkeypatch):
    p = object.__new__(deepfilter._Plugin)
    p.broken, p._late, p._calm = "", 0, 0
    p._in, p._out = np.zeros(F, np.float32), np.zeros(F, np.float32)
    slow = {"s": 0.0}

    class D:
        @staticmethod
        def run(h, n):
            time.sleep(slow["s"])
    p._d, p._h = D, None
    clock = iter(range(10 ** 6))
    # each run "takes" one and a half frames (late) or nothing, by a fake clock
    monkeypatch.setattr(deepfilter, "time", types.SimpleNamespace(
        perf_counter=lambda: next(clock) * (1.5 * F / deepfilter.RATE) * slow["late"]))
    slow["late"] = 0
    for _ in range(1100):                     # quick runs: never late, never below zero
        assert p.run(np.zeros(F, np.float32)) is not None
    assert p._late == 0 and p.delay() == deepfilter.DELAY
    slow["late"] = 1
    for _ in range(deepfilter.GIVE_UP - 1):
        assert p.run(np.zeros(F, np.float32)) is not None
    assert p.delay() == deepfilter.DELAY + (deepfilter.GIVE_UP - 1) * F
    assert p.run(np.zeros(F, np.float32)) is None and "too slow" in p.broken
    assert p.run(np.zeros(F, np.float32)) is None     # for good
    assert deepfilter.GIVE_UP < 100   # the plugin ends the process at a second of delay


# ---------------------------------------------------------------- the stream
@pytest.mark.parametrize("block", [480, 441, 1024])
def test_stream_cleans_any_block_size_and_says_its_latency(fake_plugin, block):
    s = deepfilter.Stream()
    try:
        _ready(s)
        x = np.sin(np.arange(48000) / 7).astype(np.float32)
        y = _feed(s, x, block)
        assert len(y) == len(x) and not s.error
        lag = round(s.latency() * deepfilter.RATE)
        assert lag >= deepfilter.PRIME + F    # (a block over PRIME: that much more, once)
        h = len(x) // 2
        assert np.allclose(y[h:], x[h - lag:len(x) - lag] * 0.5, atol=1e-6)
    finally:
        s.close()


def test_stream_that_wont_start_says_why(monkeypatch):
    def no(use):
        raise RuntimeError("Strong isn't downloaded")
    monkeypatch.setattr(deepfilter, "plugin", no)
    s = deepfilter.Stream()
    for _ in range(500):
        if s.feed(np.zeros(480, np.float32)) is None and s.error:
            break
        time.sleep(0.005)
    assert s.error == "Strong isn't downloaded"


def test_stream_that_stalls_gives_up(monkeypatch):
    hang = threading.Event()
    p = FakePlugin(hang)
    monkeypatch.setattr(deepfilter, "plugin", lambda use: p)
    s = deepfilter.Stream()
    try:
        _ready(s)
        out = [s.feed(np.ones(480, np.float32)) for _ in range(80)]   # 0.8 s, none back
        assert s.error == "it stopped answering"
        assert all(o is None or len(o) == 480 for o in out)
    finally:
        hang.set()
        s.close()


def test_clip_is_lined_up_with_the_recording(fake_plugin, monkeypatch):
    monkeypatch.setattr(deepfilter, "time", types.SimpleNamespace(
        perf_counter=time.perf_counter, sleep=lambda s: None))
    x = np.sin(np.arange(9000) / 5).astype(np.float32)
    y = deepfilter.clean_clip(x)
    assert len(y) == len(x) and np.allclose(y, x * 0.5, atol=1e-6)


# ---------------------------------------------------------------- the Cleaner
@real_rnnoise
def test_cleaner_uses_strong_once_its_running(fake_plugin):
    c = cleanmic.Cleaner(48000, "strong")
    try:
        _ready(c._deep)
        x = np.full(48000, 0.2, np.float32)
        y = []
        for i in range(0, len(x), 480):
            y.append(c.process(x[i:i + 480]))
            time.sleep(0.001)
        assert np.allclose(np.concatenate(y)[-4800:], 0.1, atol=1e-4) and not c.note
        assert c.latency() >= (deepfilter.PRIME + F + c._prime) / 48000
        c.set_strength("normal")              # off Strong: its stream goes
        assert c._deep is None
    finally:
        c.close()


@real_rnnoise
def test_cleaner_falls_back_to_normal_when_strong_cant_run(monkeypatch):
    def no(use):
        raise RuntimeError("Strong isn't downloaded")
    monkeypatch.setattr(deepfilter, "plugin", no)
    c = cleanmic.Cleaner(48000, "strong")
    try:
        m = _noisy()
        for i in range(0, len(m), 480):
            c.process(m[i:i + 480])
            if c.note:
                break
            time.sleep(0.001)
        assert c.note == "Strong isn't downloaded" and c._deep is None
        y = np.concatenate([c.process(m[i:i + 480]) for i in range(0, len(m), 480)])
        assert len(y) == len(m) and np.all(np.isfinite(y))   # Normal goes on cleaning
    finally:
        c.close()


@real_rnnoise
@real_dll
def test_the_real_plugin_takes_the_noise_out(app_dir):
    deepfilter.folder().mkdir(parents=True)
    shutil.copy(REAL_DLL, deepfilter.path())
    m = _noisy(seconds=3.0)
    noise = (0.03 * np.random.default_rng(1).standard_normal(48000)).astype(np.float32)
    c = cleanmic.Cleaner(48000, "strong")
    try:
        _ready(c._deep, 10)
        out = []
        for i in range(0, 48000, 480):          # in real time, as a mic
            out.append(c.process(noise[i:i + 480]))
            time.sleep(0.009)
        y = np.concatenate(out)
        assert not c.note and _db(y[-24000:]) < _db(noise) - 20
    finally:
        c.close()
    y = cleanmic.clean_clip(m, 48000, "strong")
    assert len(y) == len(m) and np.all(np.isfinite(y))


# ---------------------------------------------------------------- the card
@pytest.fixture
def card(qapp, monkeypatch, app_dir):
    FakeCleaner.made = []
    monkeypatch.setattr(cleanmic, "Cleaner", FakeCleaner)
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    monkeypatch.setattr(cleanmic, "available", lambda: True)
    from soundboard.ui.voice.voicepanel import VoicePanel
    saved = []
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}}, {})
    p.speech_changed.connect(saved.append)
    yield p, saved
    p.shutdown()
    p.deleteLater()


def _wait(qapp, cond):
    for _ in range(500):
        qapp.processEvents()
        if cond():
            return
        time.sleep(0.002)
    raise AssertionError("never happened")


def _fake_download(monkeypatch, gate=None, fail=None):
    def download(progress=None, cancelled=None):
        progress(10, 100)
        if gate is not None:
            while not gate.is_set():
                if cancelled():
                    raise updates.UpdateError("cancelled")
                time.sleep(0.002)
        if fail:
            raise updates.UpdateError(fail)
        deepfilter.folder().mkdir(parents=True, exist_ok=True)
        deepfilter.path().write_bytes(b"dll")
        progress(100, 100)
        return deepfilter.path()
    monkeypatch.setattr(deepfilter, "download", download)


def test_picking_strong_offers_the_download_then_uses_it(card, qapp, monkeypatch):
    p, saved = card
    c = p.clean
    c.b_on.click()
    gate = threading.Event()
    _fake_download(monkeypatch, gate)
    c.b_strength["strong"].click()
    assert c.s["strength"] == "normal" and c.b_strength["normal"].isChecked()
    assert not c.get_box.isHidden() and "51 MB" in c.lbl_get.text()
    assert "51 MB" in c.b_get.text() and c.b_drop.isHidden()
    c.b_get.click()
    _wait(qapp, lambda: "10%" in c.lbl_get.text())
    assert c.b_get.isHidden() and not c.b_cancel.isHidden() and not c.get_bar.isHidden()
    gate.set()
    _wait(qapp, lambda: c.s["strength"] == "strong")
    assert c.get_box.isHidden() and c.b_strength["strong"].isChecked()
    assert p.chain._clean_want == "strong" and saved[-1]["clean"]["strength"] == "strong"
    assert not c.b_drop.isHidden() and "Strong" in c.lbl_strength.text()
    c.b_drop.click()                          # removed: Normal cleans again
    assert c.s["strength"] == "normal" and not deepfilter.downloaded()
    assert c.b_drop.isHidden() and p.chain._clean_want == "normal"


def test_a_failed_or_cancelled_download_can_be_tried_again(card, qapp, monkeypatch):
    p, _saved = card
    c = p.clean
    _fake_download(monkeypatch, fail="the download failed (offline)")
    c.b_strength["strong"].click()
    c.b_get.click()
    _wait(qapp, lambda: "Couldn't download" in c.lbl_get.text())
    assert "offline" in c.lbl_get.text() and c.b_get.text() == "Try again"
    assert c.s["strength"] == "normal" and not c.b_get.isHidden()
    gate = threading.Event()
    _fake_download(monkeypatch, gate)
    c.b_get.click()
    _wait(qapp, lambda: not c.b_cancel.isHidden())
    c.b_cancel.click()
    _wait(qapp, lambda: not c.b_get.isHidden())
    assert "one-time download" in c.lbl_get.text() and c.s["strength"] == "normal"
    c.b_strength["light"].click()             # another strength: the offer goes
    assert c.get_box.isHidden() and c.s["strength"] == "light"


def test_when_strong_stops_the_card_says_so_and_shows_normal(card, monkeypatch):
    p, _saved = card
    c = p.clean
    deepfilter.folder().mkdir(parents=True)
    deepfilter.path().write_bytes(b"dll")
    c.b_on.click()
    c.b_strength["strong"].click()
    assert c.s["strength"] == "strong"
    p.chain.process(np.zeros((480, 1), np.float32), 48000)   # the fake cleaner is made
    p.chain.cleaner.note = "it's too slow on this PC"
    c._tick()
    assert c.s["strength"] == "normal" and c.b_strength["normal"].isChecked()
    assert "too slow" in c.lbl_fallback.text() and not c.lbl_fallback.isHidden()
    c.b_strength["light"].click()             # picked again: the message goes
    assert c.lbl_fallback.isHidden()
