"""A sound whose file was moved or deleted says so in plain words, not ffmpeg's."""
from conftest import process_events

from soundboard.sounds import library
from soundboard.sounds.library import SoundMeta
from test_mainwindow import window  # noqa: F401 - the real window, offscreen


def test_a_missing_sound_file_says_its_gone_and_where_it_was(qapp, window, tmp_path):  # noqa: F811
    gone = str(tmp_path / "moved away.wav")
    window.cfg.sounds.append(SoundMeta(id="gone", name="Gone", file=gone))
    window._rebuild_pads()
    window.soundctl._load_all()
    window.soundctl._load_thread.join(15)
    pad = window.pads["gone"]
    assert process_events(qapp, lambda: pad.state == "error")
    said = []
    window.toast = lambda text, *a, **k: said.append(text)
    window.playctl.play("gone")
    assert said and f"its file is gone (it was at {gone})" in said[0]
    assert "ffmpeg" not in said[0].lower() and "Error opening" not in said[0]


def test_reading_a_missing_file_never_asks_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_ffmpeg_source", lambda *a: (_ for _ in ()).throw(
        AssertionError("asked ffmpeg")))
    try:
        library.decode(str(tmp_path / "nope.mp3"))
    except RuntimeError as e:
        assert str(e) == f"its file is gone (it was at {tmp_path / 'nope.mp3'})"
    else:
        raise AssertionError("decoded a file that isn't there")
