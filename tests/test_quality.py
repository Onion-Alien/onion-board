"""Settings > Data & quality: low data mode, download / video formats, the radio cap."""
import pytest
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel

from soundboard import library, quality, radio, ytdl
from soundboard.settings import SettingsDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


@pytest.fixture(autouse=True)
def fresh_prefs():
    quality.load({})
    yield
    quality.load({})


def test_saved_prefs_load_and_odd_values_keep_their_defaults():
    p = quality.from_raw({"download": "small", "radio_kbps": 64, "patient": True,
                          "save_video": 1, "video_height": 999, "web_extras": "no"})
    assert (p.download, p.radio_kbps, p.patient) == ("small", 64, True)
    assert p.save_video is False and p.video_height == 720 and p.web_extras is True
    assert quality.from_raw({"download": "huge", "radio_kbps": 5}).to_raw() == \
        quality.Prefs().to_raw()
    assert quality.from_raw(None).to_raw() == quality.Prefs().to_raw()


def test_low_data_mode_is_every_choice_at_its_lightest():
    assert not quality.current.low_data
    quality.change(**quality.LOW)
    assert quality.current.low_data
    quality.change(radio_kbps=128)     # one choice back up: no longer "low data"
    assert not quality.current.low_data
    quality.change(**quality.NORMAL)
    assert quality.current.to_raw() == quality.Prefs().to_raw()


def test_radio_cap_keeps_stations_under_it_and_unknown_ones():
    st = [radio.Station(uuid=str(k), name=str(k), url="http://example.com/s", bitrate=k)
          for k in (0, 32, 64, 128, 320)]
    assert radio.fits(st) == st and radio._kbps_query() == ""
    quality.change(radio_kbps=64)
    assert [s.bitrate for s in radio.fits(st)] == [0, 32, 64]
    assert radio._kbps_query() == "&bitrateMax=64"
    assert radio._patience() == 1.0
    quality.change(patient=True)
    assert radio._patience() > 1.0


def test_download_format_follows_the_quality(monkeypatch):
    monkeypatch.setattr(ytdl.net, "ytdlp_proxy", lambda *a, **k: None)
    assert ytdl._opts()["format"] == "bestaudio/best"
    quality.change(download="small")
    assert ytdl._opts()["format"].startswith("bestaudio[abr<=")
    assert ytdl._opts()["max_filesize"] == ytdl.MAX_BYTES


def test_video_merges_with_ffmpeg_and_falls_back_to_single_files(monkeypatch):
    monkeypatch.setattr(ytdl.net, "ytdlp_proxy", lambda *a, **k: None)
    quality.change(video_height=480)
    monkeypatch.setattr(library, "_ffmpeg", lambda: "ffmpeg.exe")
    o = ytdl._opts(video=True)
    assert o["format"].startswith("bv*[height<=480]") and o["merge_output_format"] == "mp4"
    assert o["ffmpeg_location"] == "ffmpeg.exe" and o["max_filesize"] == ytdl.VIDEO_MAX_BYTES
    monkeypatch.setattr(library, "_ffmpeg", lambda: None)
    o = ytdl._opts(video=True)
    assert "+" not in o["format"] and "merge_output_format" not in o
    assert o["format"].startswith("b[height<=480]")


def test_save_video_copies_under_the_title_without_clobbering(tmp_path):
    quality.change(video_dir=str(tmp_path / "vids"))
    src = tmp_path / "abc.mp4"
    src.write_bytes(b"video")
    a = ytdl.save_video(src, 'A: "Song" / live')
    b = ytdl.save_video(src, 'A: "Song" / live')
    assert a.parent == tmp_path / "vids" and a.read_bytes() == b"video"
    assert a != b and b.name.endswith("(2).mp4") and src.exists()
    audio = tmp_path / "abc.m4a"
    audio.write_bytes(b"x")
    assert ytdl.save_video(audio, "Song") is None     # the site only gave the sound


def test_settings_page_switches_low_data_mode_and_saves_it(window):  # noqa: F811
    d = SettingsDialog(window, "data")
    page = d.tabs.currentWidget().widget()
    assert {"Low data mode", "Downloads", "Radio", "Sounds from the web"} <= {
        lb.text() for lb in page.findChildren(QLabel)}
    assert not d.data_low.isChecked()
    assert not d._data_widgets["video_height"].isEnabled()   # until videos are kept
    d.data_low.setChecked(True)
    assert quality.current.low_data and window.cfg.data["download"] == "small"
    assert d._data_widgets["radio_kbps"].currentData() == quality.LOW_RADIO_KBPS
    assert not d._data_widgets["web_extras"].isChecked()
    d._data_widgets["download"].setCurrentIndex(0)           # one back to best
    assert not d.data_low.isChecked() and quality.current.download == "best"
    box = next(b for b in page.findChildren(QCheckBox) if b.text() == "Also save the video")
    box.setChecked(True)
    assert window.cfg.data["save_video"] and d._data_widgets["video_height"].isEnabled()
    assert isinstance(d._data_widgets["video_height"], QComboBox)
    d.close()
