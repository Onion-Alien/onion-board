"""Record a sound with the mic: the engine's take (raw or through the voice changer,
never mixed up with the mic test's recording), its spool, and the window."""
import numpy as np
from PySide6.QtWidgets import QMessageBox

from soundboard import library
from soundboard.engine import SR, Engine
from soundboard.recorder import MicTake
from soundboard.ui import recordmic
from soundboard.ui.recordmic import RecordDialog, next_name, quiet_bounds

from test_mainwindow import window  # noqa: F401  (the real MainWindow)

BLOCK = 480


def mic_engine(rate=SR) -> Engine:
    e = Engine()
    e.names["mic"] = "Test mic"
    e.mic_stream = object()   # stands in for an open mic
    e.rates["mic"] = rate
    return e


def feed(e: Engine, value: float, blocks: int, rate=None):
    n = BLOCK if rate is None else rate // 100
    for _ in range(blocks):
        e._mic(np.full((n, 1), value, np.float32))


class Halver:
    """A voice chain stand-in that halves the mic."""
    def process(self, x, rate):
        return x * np.float32(0.5)


# ------------------------------------------------------------------ the engine's take

def test_take_gets_the_raw_mic_or_the_changed_one():
    e = mic_engine()
    e.voice_chain = Halver()
    raw = e.start_mic_take(processed=False)
    feed(e, 0.4, 3)
    assert e.stop_mic_take() is raw and len(raw) == 3
    assert np.allclose(np.concatenate(raw), 0.4)
    fx = e.start_mic_take(processed=True)
    feed(e, 0.4, 2)
    e.stop_mic_take()
    assert np.allclose(np.concatenate(fx), 0.2)
    feed(e, 0.4, 2)   # stopped: nothing more lands anywhere
    assert len(fx) == 2 and not e.taking


def test_take_blocks_are_copies_not_the_drivers_buffer():
    e = mic_engine()
    blocks = e.start_mic_take()
    buf = np.full((BLOCK, 2), 0.3, np.float32)
    e._mic(buf)
    buf[:] = 0.9   # PortAudio reuses its buffer for the next block
    assert np.allclose(blocks[0], 0.3)


def test_take_leaves_the_mic_test_recording_alone():
    e = mic_engine()
    e.start_test_record(1.0)
    blocks = e.start_mic_take()
    feed(e, 0.25, 2)
    e.stop_mic_take()
    test = e.take_mic_recording()
    assert test is not None and len(test[0]) == 2 * BLOCK   # the test got its own copy
    assert len(blocks) == 2
    assert e._mic_rec is None   # and taking it didn't touch the take


# ------------------------------------------------------------------ the spool

def test_mic_take_spools_to_disk_and_resamples_to_sr(app_dir):
    e = mic_engine(rate=44100)
    t = MicTake(e, spool_path=app_dir / "take.wav")
    feed(e, 0.5, 50, rate=44100)   # half a second at 44.1 kHz
    assert t.pump() == 50 * 441
    assert (app_dir / "take.wav").exists() and not t._blocks
    feed(e, 0.5, 50, rate=44100)
    data = t.stop()
    assert data.dtype == np.float32 and data.shape[1] == 2
    assert abs(len(data) - SR) <= 2   # one second, now at 48 kHz
    assert abs(float(np.median(data)) - 0.5) < 0.01
    assert not (app_dir / "take.wav").exists() and not e.taking


def test_mic_take_stops_at_the_cap(app_dir, monkeypatch):
    monkeypatch.setattr("soundboard.recorder.MAX_SECONDS", 0.05)
    e = mic_engine()
    t = MicTake(e, spool_path=app_dir / "take.wav")
    feed(e, 0.5, 10)   # 0.1 s
    t.pump()
    assert t.full and t.frames == int(0.05 * SR)
    assert len(t.stop()) == int(0.05 * SR)


def test_mic_take_cancel_forgets_it(app_dir):
    e = mic_engine()
    t = MicTake(e, spool_path=app_dir / "take.wav")
    feed(e, 0.5, 3)
    t.pump()
    t.cancel()
    assert not e.taking and not (app_dir / "take.wav").exists()


# ------------------------------------------------------------------ helpers

def test_next_name_counts_past_the_highest():
    assert next_name([]) == "Recording 1"
    assert next_name(["Boom", "Recording 1", "Recording 7", "Recording x"]) == "Recording 8"


def test_quiet_bounds_cut_hiss_off_both_ends():
    hiss = np.full((SR, 2), 0.006, np.float32)   # a mic's noise floor, above -54 dBFS
    voice = np.full((SR // 2, 2), 0.5, np.float32)
    a, b = quiet_bounds(np.concatenate([hiss, voice, hiss]))
    pad = int(0.05 * SR)
    assert a == SR - pad and abs(b - (SR + SR // 2 + pad)) <= 1
    assert quiet_bounds(hiss) == (0, SR)   # all hiss: nothing to cut against


# ------------------------------------------------------------------ the window

def make_dialog(e, saved, voice=False, names=("Boom",)):
    devices = []
    d = RecordDialog(e, lambda: voice, lambda: list(names),
                     lambda data, name: saved.append((data, name)) or True,
                     lambda: devices.append(1))
    d.devices_opened = devices
    return d


def record(d, e, quiet_blocks=50, loud_blocks=50):
    assert d.start()
    feed(e, 0.0, quiet_blocks)
    feed(e, 0.5, loud_blocks)
    feed(e, 0.0, quiet_blocks)
    d._tick()
    d.stop()


def test_record_stop_save_adds_one_trimmed_pad(qapp, app_dir):
    e, saved = mic_engine(), []
    d = make_dialog(e, saved)
    assert d.opt_fx.isHidden() and not d.source.isHidden()   # voice changer off: mic or playing
    record(d, e)
    assert d.data is not None and len(d.data) == 150 * BLOCK
    assert d.name.text() == "Recording 1"
    s, end = d.trim.values()
    assert s > 0.4 and end < 1.1   # the silent half seconds are cut off
    assert d.save()
    (data, name), = saved
    assert name == "Recording 1"
    assert abs(len(data) - (50 * BLOCK + 2 * int(0.05 * SR))) <= 2
    assert d.result() == RecordDialog.Accepted and not e.taking
    d.deleteLater()


def test_through_the_voice_changer_records_the_changed_voice(qapp, app_dir):
    e, saved = mic_engine(), []
    e.voice_chain = Halver()
    d = make_dialog(e, saved, voice=True)
    assert not d.opt_fx.isHidden()
    d.opt_fx.setChecked(True)
    record(d, e, quiet_blocks=0)
    assert abs(float(d.data.max()) - 0.25) < 1e-6
    d.discard()
    d.deleteLater()


def test_close_with_an_unsaved_take_asks_once_and_keeps_it_on_no(qapp, app_dir, monkeypatch):
    e, saved = mic_engine(), []
    d = make_dialog(e, saved)
    record(d, e)
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.No)
    d.reject()
    assert len(asked) == 1 and d.data is not None   # kept
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.Yes)
    d.reject()
    assert len(asked) == 2 and d.data is None and not saved
    d.deleteLater()


def test_no_mic_says_so_and_offers_devices(qapp, app_dir):
    e, saved = Engine(), []
    e.names["mic"] = None
    d = make_dialog(e, saved)
    assert not d.problem.isHidden() and "No mic" in d.problem_text.text()
    assert not d.btn_rec.isEnabled() and not d.start()
    e.names["mic"] = "Broken mic"   # picked, but it didn't open
    e.errors["mic"] = "The device is in use."
    d._show_state()
    assert "can't open" in d.problem_text.text() and "in use" in d.problem_text.text()
    d.btn_devices.click()
    assert d.devices_opened == [1] and not saved
    d.deleteLater()


def test_silence_from_the_mic_is_reported(qapp, app_dir):
    e, saved = mic_engine(), []
    d = make_dialog(e, saved)
    d.start()
    for _ in range(int(recordmic.NO_SOUND_S * 1000 / recordmic.PUMP_MS) + 1):
        d._tick()   # no blocks at all
    assert "Nothing is coming" in d.status.text()
    d.stop()
    assert d.data is None and "Nothing was recorded" in d.status.text()
    d.deleteLater()


def test_the_window_adds_a_recording_as_a_selected_pad(window, monkeypatch):  # noqa: F811
    before = window.cfg.to_raw()
    e = window.engine
    e.names["mic"], e.mic_stream = "Test mic", object()
    try:
        d = RecordDialog(e, lambda: False, lambda: [m.name for m in window.cfg.sounds],
                         window.add_recording, lambda: None, window)
        n = len(window.cfg.sounds)
        record(d, e)
        assert window.cfg.to_raw() == before   # a take changes no setting
        assert d.save()
        assert len(window.cfg.sounds) == n + 1
        m = window.cfg.sounds[-1]
        assert m.name == "Recording 1" and window.current == m.id and m.id in window.pads
        assert library.Path(m.file).exists()
        d.deleteLater()
    finally:
        e.mic_stream = None


def test_cancel_adds_nothing(window, monkeypatch):  # noqa: F811
    e = window.engine
    e.names["mic"], e.mic_stream = "Test mic", object()
    try:
        n = len(window.cfg.sounds)
        d = RecordDialog(e, lambda: False, lambda: [], window.add_recording, lambda: None,
                         window)
        record(d, e)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        d.reject()
        assert len(window.cfg.sounds) == n and not e.taking
        d.deleteLater()
    finally:
        e.mic_stream = None


# ------------------------------------------------------------------ what's playing

def out_engine(*outs) -> Engine:
    e = Engine()
    e.dest, e.limiter_on, e.send_mono = None, False, False   # no shaping, exact samples
    for o in outs:
        setattr(e, f"{o}_stream", object())
        e.names[o] = f"fake {o}"
    return e


def test_play_take_records_the_sounds_and_radio_without_the_mic():
    e = out_engine("main")
    e.ring_rmain.prefill = 0
    e.play("song", np.full((SR, 2), 0.25, np.float32), 1.0, loop=True)
    e.ring_main.write(np.full((BLOCK * 4, 2), 0.5, np.float32))   # your mic, on its way out
    out = np.zeros((BLOCK, 2), np.float32)
    e._main(out, BLOCK)                       # past the sound's fade-in
    blocks = e.start_play_take()
    assert e.play_take_out == "main" and e.play_taking
    e.feed_radio(np.full((BLOCK * 2, 2), 0.1, np.float32))
    e.radio_live = False                      # the radio not sent out: still recorded
    e._main(out, BLOCK)
    assert e.stop_play_take() is blocks and not e.play_taking
    assert len(blocks) == 1 and np.allclose(blocks[0][-10:], 0.25 + 0.1, atol=1e-3)
    e._main(out, BLOCK)
    assert len(blocks) == 1                   # stopped: nothing more lands


def test_play_take_comes_from_the_headphones_with_no_send_device():
    e = out_engine("mon")
    e.monitor_sounds = True
    e.play("song", np.full((SR, 2), 0.25, np.float32), 1.0, loop=True)
    out = np.zeros((BLOCK, 2), np.float32)
    e._mon(out, BLOCK)
    blocks = e.start_play_take()
    assert e.play_take_out == "mon"
    e._mon(out, BLOCK)
    e.stop_play_take()
    assert len(blocks) == 1 and np.allclose(blocks[0][-10:], 0.25, atol=1e-3)


def test_the_window_records_whats_playing_and_names_it(app_dir):
    e = out_engine("main")
    saved = []
    d = RecordDialog(e, lambda: False, lambda: ["Boom"],
                     lambda data, name: saved.append((data, name)) or True, lambda: None,
                     playing_name=lambda: "Haddaway - What Is Love")
    d.opt_play.setChecked(True)
    assert not d.problem.isVisibleTo(d) and d.btn_rec.isEnabled()   # no mic needed
    assert d.start() and d.take.playing
    for _ in range(50):
        e._play_take.append(np.full((BLOCK, 2), 0.3, np.float32))
    d._tick()
    d.stop()
    assert d.data is not None and abs(len(d.data) - 50 * BLOCK) <= 2
    assert d.name.text() == "Haddaway - What Is Love"
    assert d.save() and saved[0][1] == "Haddaway - What Is Love"
    assert RecordDialog.last_source == "play"
    RecordDialog.last_source = "mic"
    d.deleteLater()


def test_recording_silence_from_whats_playing_says_nothing_played(app_dir):
    e = out_engine("main")
    d = RecordDialog(e, lambda: False, lambda: [], lambda *a: True, lambda: None)
    d.opt_play.setChecked(True)
    assert d.start()
    e._play_take.append(np.zeros((BLOCK, 2), np.float32))
    d.stop()
    assert d.data is None and "nothing played" in d.status.text()
    RecordDialog.last_source = "mic"
    d.deleteLater()


def test_whats_playing_needs_an_open_device(app_dir):
    e = Engine()
    d = RecordDialog(e, lambda: False, lambda: [], lambda *a: True, lambda: None)
    d.opt_play.setChecked(True)
    assert "No audio device" in d.problem_text.text() and not d.start()
    d.deleteLater()


def test_the_record_window_leaves_the_board_usable(window):  # noqa: F811
    window.record_dialog()
    d = window._record_dlg
    assert d is not None and d.isVisible() and not d.isModal()
    window.record_dialog()                     # a second click brings the same one up
    assert window._record_dlg is d
    d.reject()
    assert window._record_dlg is None
