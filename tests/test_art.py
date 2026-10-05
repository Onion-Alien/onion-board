"""Optional artwork (ui/art.py): pictures are used when present, emoji / painted icons
when not, and the Voice tab shows the picture of whoever's talking for you."""
import pytest
from PySide6.QtGui import QColor, QImage

from soundboard.speech import tts
from soundboard.ui import art


def _png(folder, key, w=300, h=200):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#ff8800"))
    img.save(str(folder / f"{key}.png"))


@pytest.fixture
def art_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "ART_DIR", tmp_path)
    art.reload()
    yield tmp_path
    art.reload()


def test_keys():
    assert art.voice_key("Stadium announcer") == "voice-stadium-announcer"
    assert art.voice_key("Walkie-talkie") == "voice-walkie-talkie"
    assert art.voice_key("Custom") == "voice-custom"


def test_missing_pictures_are_fine(qapp, art_dir):
    assert not art.exists("voice-robot")
    assert art.icon("voice-robot") is None
    assert art.pixmap("voice-robot", 32) is None
    assert art.first("voice-robot", "") == ""


def test_picture_is_cropped_square_with_round_corners(qapp, art_dir):
    _png(art_dir, "voice-robot")
    pm = art.pixmap("voice-robot", 40)
    assert (pm.width(), pm.height()) == (40, 40)
    img = pm.toImage()
    assert img.pixelColor(0, 0).alpha() == 0            # a rounded corner
    assert img.pixelColor(20, 20).name() == "#ff8800"   # the middle is the picture
    assert not art.icon("voice-robot").isNull()
    assert art.first("voice-demon", "voice-robot") == "voice-robot"


def test_tab_icon_accepts_a_picture(qapp, art_dir):
    from PySide6.QtWidgets import QTabWidget, QWidget

    from soundboard.ui import icons
    _png(art_dir, "voice-robot")
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "")
    icons.set_tab_icon(tabs, 0, "art:voice-robot", "#13ce66")
    assert not tabs.tabIcon(0).isNull()
    icons.set_tab_icon(tabs, 0, "art:voice-missing")    # gone: an empty icon, no crash
    icons.retheme()


class FakeEngine:
    voice_chain = None

    def play(self, *a, **k):
        pass

    def stop(self, sid):
        pass


@pytest.fixture
def panel(qapp, art_dir, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    _png(art_dir, "voice-robot")
    from soundboard.ui.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}}, {"voice": ""})
    yield p
    p.shutdown()
    p.deleteLater()


def test_voice_tiles_use_consistent_line_icons(panel):
    robot, demon = panel.fx._tile["Robot"], panel.fx._tile["Demon"]
    assert robot.text() == "Robot" and not robot.icon().isNull()
    assert demon.text() == "Demon" and not demon.icon().isNull()


def test_voice_tab_keeps_its_icon_and_reports_live_state(panel):
    assert panel.tab_icon() == "voice"                 # nothing on: the painted mask
    seen = []
    panel.active_changed.connect(seen.append)
    panel.fx.pick("Robot")
    assert panel.tab_icon() == "voice"
    assert seen and seen[-1] is True
    panel.fx.pick("Demon")                             # no picture for it
    assert panel.tab_icon() == "voice"
