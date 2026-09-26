"""Builds the real MainWindow on Qt's offscreen platform (no window appears, no
audio device is opened, no global hotkey is registered) and exercises the UI
plumbing: pad syncing, the metadata index, the mic-check pulse, the wheel guard."""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("SOUNDBOARD_INSTANCE", "pytest")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import soundfile as sf  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea, QSlider, QVBoxLayout, QWidget  # noqa: E402

import engine  # noqa: E402
import library  # noqa: E402
import main  # noqa: E402
import winkeys  # noqa: E402
from library import SR, Config, SoundMeta  # noqa: E402
from wheelguard import no_wheel  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


@pytest.fixture
def window(qapp, app_dir, monkeypatch):
    # no real devices, no real global hotkeys
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    sounds = []
    for i, name in enumerate(("Boom", "Airhorn")):
        p = app_dir / f"{name}.wav"
        t = np.arange(SR // 10) / SR
        sf.write(p, np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.3, SR)
        sounds.append(SoundMeta(id=f"s{i}", name=name, file=str(p)))
    Config(sounds=sounds).save()
    w = main.MainWindow()
    # the loader thread writes the cache and prunes orphans: it must finish while the
    # temp paths are still patched in, never after the fixture is torn down
    w._load_thread.join(15)
    assert not w._load_thread.is_alive()
    yield w
    w.close()
    assert not w._load_thread.is_alive()


def test_window_builds_with_pads_and_index(window):
    assert set(window.pads) == {"s0", "s1"}
    assert window.meta("s1").name == "Airhorn" and window.meta("zz") is None
    assert window.grid.pads == [window.pads["s0"], window.pads["s1"]]


def test_rebuild_keeps_existing_pad_widgets(window):
    old = dict(window.pads)
    window.cfg.sounds.append(SoundMeta(id="s2", name="New", file="x.wav"))
    window._rebuild_pads()
    assert window.pads["s0"] is old["s0"] and window.pads["s1"] is old["s1"]
    assert "s2" in window.pads and window.meta("s2").name == "New"
    window.cfg.sounds.pop(0)
    window._rebuild_pads()
    assert "s0" not in window.pads and window.meta("s0") is None
    assert [p.meta.id for p in window.grid.pads] == ["s1", "s2"]


def test_reorder_moves_without_recreating(window):
    old = dict(window.pads)
    window.on_reorder("s1", 0)
    assert [m.id for m in window.cfg.sounds] == ["s1", "s0"]
    assert window.pads["s1"] is old["s1"]
    assert [p.meta.id for p in window.grid.pads] == ["s1", "s0"]


def test_mic_check_pulse_runs_only_while_on(window):
    window.on_mic_check(True)
    assert window._pulse.state() == window._pulse.State.Running
    assert window.mic_banner.isVisibleTo(window)
    window.on_mic_check(False)
    assert window._pulse.state() == window._pulse.State.Stopped
    assert window._banner_fx.opacity() == 1.0


def test_tick_runs_without_devices(window):
    for _ in range(31):        # crosses the once-a-second watchdog branch
        window.tick()


def wheel(widget):
    ev = QWheelEvent(QPointF(5, 5), widget.mapToGlobal(QPoint(5, 5)), QPoint(0, 0),
                     QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    QApplication.sendEvent(widget, ev)


def test_wheel_guard_scrolls_the_page_not_the_slider(qapp):
    area = QScrollArea()
    inner = QWidget()
    lay = QVBoxLayout(inner)
    guarded, plain = QSlider(Qt.Horizontal), QSlider(Qt.Horizontal)
    for s in (guarded, plain):
        s.setRange(0, 100)
        s.setValue(50)
        lay.addWidget(s)
    inner.setMinimumHeight(2000)
    area.setWidget(inner)
    area.resize(200, 200)
    no_wheel(guarded)
    wheel(plain)
    assert plain.value() != 50            # an unguarded slider changes
    before = area.verticalScrollBar().value()
    wheel(guarded)
    assert guarded.value() == 50          # a guarded one doesn't...
    assert area.verticalScrollBar().value() != before   # ...the page scrolls instead


def test_window_uses_only_the_temp_config(window, app_dir):
    assert library.CONFIG_PATH == app_dir / "config.json"
    assert len(window.cfg.sounds) == 2
