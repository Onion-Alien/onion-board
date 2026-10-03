"""The stream output (OBS): what others hear, clean, on a device of its own."""
import numpy as np

from soundboard.library import Config
from test_engine import engine_with, tone
from test_mainwindow import window  # noqa: F401  (the real MainWindow)


def block(e, which, n=480):
    out = np.zeros((n, 2), np.float32)
    getattr(e, f"_{which}")(out, n)
    return out


def test_sounds_reach_the_stream_output_clean_and_at_its_volume():
    e = engine_with("main", "mon", "obs")
    e.send_mono = True               # the cable's mono stage never touches the stream
    d = tone(0.05) * np.array([1.0, 0.0], np.float32)   # left only
    v = e.play("a", d, 1.0)
    assert v.outs == {"main", "mon", "obs"}
    out = block(e, "obs")
    assert np.allclose(out, d[:480]) and not out[:, 1].any()   # still stereo, untouched
    e.obs_vol = 0.5
    assert np.allclose(block(e, "obs"), d[480:960] * 0.5)


def test_previews_stay_off_the_stream_and_only_them_skips_the_headphones():
    e = engine_with("main", "mon", "obs")
    assert e.play("a:preview", tone(), 1.0, preview=True).outs == {"mon"}
    assert e.play("b", tone(), 1.0, only=("main", "obs")).outs == {"main", "obs"}
    assert e.play("c", tone(), 1.0, only="main").outs == {"main"}   # the voice chat check


def test_stream_gets_the_mic_only_when_asked_and_sent():
    e = engine_with("obs")
    e.ring_obs.prefill = 0
    mic = np.full((480, 1), 0.5, np.float32)
    e._mic(mic)
    assert block(e, "obs").any()
    e.mic_enabled = False            # "send my mic" unticked: not to the stream either
    e._mic(mic)
    assert not block(e, "obs").any()
    e.mic_enabled, e.obs_voice = True, False   # OBS records the mic itself
    e._mic(mic)
    assert not block(e, "obs").any()


def test_muted_sends_the_stream_silence_too():
    e = engine_with("obs")
    e.play("a", tone(), 1.0)
    e.sending = False
    assert not block(e, "obs").any()


def test_live_radio_and_programs_go_to_the_stream():
    e = engine_with("obs")
    e.ring_robs.prefill = 0
    e.feed_radio(np.full((480, 2), 0.25, np.float32))
    assert not block(e, "obs").any()          # radio not live: only you hear it
    e.radio_live = True
    e.feed_radio(np.full((480, 2), 0.25, np.float32))
    assert block(e, "obs").any()
    src = e.add_aux(("app", "music.exe"))
    src.ring_obs.prefill = 0
    e.radio_live = False
    e.feed_aux(src, np.full((480, 2), 0.25, np.float32))
    assert block(e, "obs").any()


def test_closing_the_stream_output_finishes_its_part_of_a_sound():
    e = engine_with("main", "obs")
    v = e.play("a", tone(), 1.0)
    e._close("obs_stream")
    assert "obs" in v.done and e.active_outputs() == {"main"}


def test_window_never_streams_to_the_cable_or_headphones(window, monkeypatch):  # noqa: F811
    w = window
    opened = []
    monkeypatch.setattr(w.engine, "set_obs_device", opened.append)
    w.cfg.main_device, w.cfg.mon_device = "CABLE Input", "Headphones"
    w.set_obs_device("CABLE Input")
    w.set_obs_device("Headphones")
    w.set_obs_device("CABLE-A Input")
    w.set_obs_device(None)
    assert opened == [None, None, "CABLE-A Input", None]
    assert w.cfg.obs_device is None


def test_stream_settings_are_saved_but_never_exported(app_dir):
    from soundboard import backup
    cfg = Config(obs_device="CABLE-A Input", obs_vol=50.0, obs_voice=False)
    cfg.save()
    back = Config.load()
    assert (back.obs_device, back.obs_voice) == ("CABLE-A Input", False)
    assert back.obs_vol <= 10.0                  # clamped to the volume box
    assert "obs_device" in backup.LOCAL_SETTINGS  # another PC has other devices


def test_another_end_of_the_cable_in_use_is_never_the_stream_output(window, monkeypatch):  # noqa: F811
    from soundboard import engine
    assert engine.same_cable("CABLE In 16ch (VB-Audio Virtual Cable)",
                             "CABLE Input (VB-Audio Virtual Cable)")
    assert not engine.same_cable("CABLE-A Input (VB-Audio Cable A)",
                                 "CABLE Input (VB-Audio Virtual Cable)")
    assert not engine.same_cable("Speakers (Realtek(R) Audio)", "Speakers (Realtek(R) Audio)")
    w = window
    opened = []
    monkeypatch.setattr(w.engine, "set_obs_device", opened.append)
    w.cfg.main_device = "CABLE Input (VB-Audio Virtual Cable)"
    w.set_obs_device("CABLE In 16ch (VB-Audio Virtual Cable)")
    w.set_obs_device("CABLE-A Input (VB-Audio Cable A)")
    assert opened == [None, "CABLE-A Input (VB-Audio Cable A)"]
