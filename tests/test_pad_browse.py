"""Finding your way round a big board: the pads' order (A-Z, newest, most played) with
a play count per sound, the list view, Ctrl+wheel volume on a pad, a colour per
category, and a typed text-to-speech line saved as a pad."""
import json

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from soundboard import library
from soundboard.library import Config, SoundMeta, sorted_sounds
from soundboard.speech import tts
from soundboard.ui.widgets import SLIM_PAD_H, Pad, pad_height
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)
from tests.conftest import process_events


@pytest.fixture
def window(main_window):  # noqa: F811
    w = main_window
    for sid in ("s0", "s1"):
        w.audio[sid] = np.zeros((480, 2), np.float32)
    return w


def metas():
    return [SoundMeta(id="a", name="zebra", file="a.wav", plays=1),
            SoundMeta(id="b", name="Apple", file="b.wav", plays=9, added=200.0),
            SoundMeta(id="c", name="mango", file="c.wav", plays=1, added=100.0),
            SoundMeta(id="d", name="kiwi", file="d.wav")]


def ids(sounds):
    return [m.id for m in sounds]


def test_sorted_sounds_orders():
    s = metas()
    assert ids(sorted_sounds(s, "custom")) == ["a", "b", "c", "d"]
    assert ids(sorted_sounds(s, "name")) == ["b", "d", "c", "a"]       # case doesn't count
    assert ids(sorted_sounds(s, "plays")) == ["b", "a", "c", "d"]      # ties keep the order
    # newest: by when it was added; ones from before that was kept come after, the later
    # in the board the newer
    assert ids(sorted_sounds(s, "newest")) == ["b", "c", "d", "a"]
    assert ids(s) == ["a", "b", "c", "d"]   # the board's own order is untouched


def test_new_settings_round_trip_and_bad_values_fall_back(app_dir):
    cfg = Config(sounds=[SoundMeta(id="a", name="A", file="a.wav", plays=4, added=123.5)],
                 pad_sort="plays", pad_view="list", categories=["Memes"],
                 category_colors={"Memes": "#ff5c8a"})
    back = Config.from_raw(json.loads(json.dumps(cfg.to_raw())))
    assert (back.pad_sort, back.pad_view, back.category_colors) == \
        ("plays", "list", {"Memes": "#ff5c8a"})
    assert (back.sounds[0].plays, back.sounds[0].added) == (4, 123.5)
    raw = cfg.to_raw()
    raw.update(pad_sort="by_mood", pad_view="tiles",
               category_colors={"Memes": "red", "X": "#00ff00", "Y": 3})
    raw["sounds"][0].update(plays=-5, added="soon")
    odd = Config.from_raw(raw)
    assert (odd.pad_sort, odd.pad_view) == ("custom", "grid")
    assert odd.category_colors == {"X": "#00ff00"}
    assert (odd.sounds[0].plays, odd.sounds[0].added) == (0, 0.0)
    # a newer version's order or view isn't lost by saving here
    assert (odd.to_raw()["pad_sort"], odd.to_raw()["pad_view"]) == ("by_mood", "tiles")


def test_old_config_loads_with_defaults(app_dir):
    raw = Config(sounds=[SoundMeta(id="a", name="A", file="a.wav")]).to_raw()
    for k in ("pad_sort", "pad_view", "category_colors"):
        raw.pop(k)
    for k in ("plays", "added"):
        raw["sounds"][0].pop(k)
    cfg = Config.from_raw(raw)
    assert (cfg.pad_sort, cfg.pad_view, cfg.category_colors) == ("custom", "grid", {})
    assert (cfg.sounds[0].plays, cfg.sounds[0].added) == (0, 0.0)


def test_saved_clips_know_when_they_were_added(app_dir):
    meta, _data = library.save_clip(np.zeros((4800, 2), np.float32), "Clip", "#7c5cff")
    assert meta.added > 0 and meta.plays == 0


def test_playing_counts_and_most_played_sorts(window, monkeypatch):
    w = window
    monkeypatch.setattr(w.engine, "play", lambda *a, **k: object())
    w.play("s1")
    w.play("s1")
    assert (w.meta("s0").plays, w.meta("s1").plays) == (0, 2)
    assert w._count_save.isActive()   # saved soon, not on each press
    assert [p.meta.id for p in w.grid.pads] == ["s0", "s1"]   # not re-sorted under the mouse
    w.set_pad_sort("plays")
    assert [p.meta.id for p in w.grid.pads] == ["s1", "s0"]
    assert w.btn_view.text() == "Most played"
    w.set_pad_sort("name")
    assert [p.meta.id for p in w.grid.pads] == ["s1", "s0"]   # Airhorn, Boom
    assert [m.id for m in w.cfg.sounds] == ["s0", "s1"]          # own order kept
    w.set_pad_sort("custom")
    assert [p.meta.id for p in w.grid.pads] == ["s0", "s1"]


def test_dragging_while_sorted_keeps_the_own_order(window):
    w = window
    w.set_pad_sort("name")
    w.on_reorder("s0", 0)
    assert [m.id for m in w.cfg.sounds] == ["s0", "s1"]
    w.set_pad_sort("custom")
    w.on_reorder("s1", 0)
    assert [m.id for m in w.cfg.sounds] == ["s1", "s0"]


def test_view_menu_lists_orders_and_views(window):
    w = window
    menu = w.btn_view.menu()
    w._fill_view_menu(menu)
    names = [a.text() for a in menu.actions() if a.text()]
    assert names == ["My order", "A–Z", "Newest", "Most played", "Pads", "List"]
    checked = [a.text() for a in menu.actions() if a.isChecked()]
    assert checked == ["My order", "Pads"]


def test_list_view_rows_in_columns(window):
    w = window
    w.resize(1200, 800)
    w.grid.resize(900, 600)
    w.set_pad_view("list")
    assert w.grid.listed and w.cfg.pad_view == "list"
    pad = w.pads["s0"]
    assert pad.height() == SLIM_PAD_H
    cols, width = w.grid.fit_width(900 - 8)
    assert cols >= 3 and width >= 260
    w.set_pad_view("grid")
    assert not w.grid.listed
    assert pad.height() == pad_height(pad.width())


def test_list_view_survives_the_mini_player(window):
    w = window
    w.set_pad_view("list")
    w._set_mini(True)
    assert w.grid.fit_width(300) == (1, 300)   # one row a line in the mini player
    w._set_mini(False)
    assert w.grid.listed


def wheel(pad: Pad, dy: int, mods=Qt.ControlModifier) -> QWheelEvent:
    e = QWheelEvent(QPointF(5, 5), QPointF(pad.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                    QPoint(0, dy), Qt.NoButton, mods, Qt.NoScrollPhase, False)
    pad.wheelEvent(e)
    return e


def test_ctrl_wheel_changes_a_pads_volume(window, monkeypatch):
    w = window
    gains = []
    monkeypatch.setattr(w.engine, "set_gain", lambda sid, g: gains.append((sid, g)))
    pad = w.pads["s0"]
    assert wheel(pad, 120).isAccepted()
    assert w.meta("s0").volume == pytest.approx(1.05)
    wheel(pad, -360)
    assert w.meta("s0").volume == pytest.approx(0.9)
    assert gains and gains[-1][0] == "s0"
    for _ in range(60):
        wheel(pad, -120)
    assert w.meta("s0").volume == 0.0                # never below silent
    wheel(pad, 60)                                   # half a notch (a touchpad)...
    assert w.meta("s0").volume == 0.0
    wheel(pad, 60)                                   # ...and the other half
    assert w.meta("s0").volume == pytest.approx(0.05)
    assert w._count_save.isActive()


def test_plain_wheel_still_scrolls(window):
    w = window
    e = wheel(w.pads["s0"], 120, Qt.NoModifier)
    assert not e.isAccepted()
    assert w.meta("s0").volume == 1.0


def test_pad_menu_volume_slider(window):
    w = window
    from PySide6.QtWidgets import QMenu, QSlider
    act = w._volume_action(QMenu(w), w.meta("s1"))
    sl = act.defaultWidget().findChild(QSlider)
    assert sl.value() == 100
    sl.setValue(140)
    assert w.meta("s1").volume == pytest.approx(1.4)


def test_category_colour_on_tab_rename_and_delete(window):
    w = window
    w.cfg.categories.append("Memes")
    w._fill_categories()
    assert w.cat_tabs.tabIcon(1).isNull()
    w.set_category_color("Memes", "#ff5c8a")
    assert w.cfg.category_colors == {"Memes": "#ff5c8a"}
    assert not w.cat_tabs.tabIcon(1).isNull()
    w.rename_category("Memes", "Funny")
    assert w.cfg.category_colors == {"Funny": "#ff5c8a"}
    w.set_category_color("Funny", "")
    assert w.cfg.category_colors == {}
    w.set_category_color("Funny", "#13ce66")
    w.delete_category("Funny")
    assert w.cfg.category_colors == {}


class FakeEngine:
    voice_chain = None
    mic_stream = None
    level_mic = 0.0

    def play(self, *a, **k):
        pass

    def stop(self, sid):
        pass


@pytest.fixture
def speech(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"voice": "Microsoft Zira Desktop"})
    yield p
    p.shutdown()
    p.deleteLater()


def test_typed_line_saved_as_a_sound(speech, qapp, monkeypatch):
    p = speech
    tone = np.sin(np.arange(22050) / 22050 * 2 * np.pi * 220).astype(np.float32) * 0.3
    asked = []

    def synth(text, voice="", rate=0):
        asked.append((text, voice))
        return tone, 22050
    monkeypatch.setattr(p.controller.tts, "synth", synth)
    got = []
    p.clip_ready.connect(lambda data, name: got.append((data, name)))
    p.speech.ed.setText("  hello   there friend  ")
    p.speech.b_keep.click()
    assert process_events(qapp, lambda: got)
    data, name = got[0]
    assert name == "hello there friend"
    assert data.dtype == np.float32 and data.shape[1] == 2
    assert len(data) == pytest.approx(library.SR, rel=0.01)   # 1 s at the board's rate
    assert asked[0][0].strip() == "hello   there friend"
    assert p.speech.ed.text().strip()   # the line stays: Say can still say it


def test_save_as_sound_with_nothing_typed_uses_the_last_line(speech, qapp, monkeypatch):
    p = speech
    monkeypatch.setattr(p.controller.tts, "synth",
                        lambda text, voice="", rate=0: (np.ones(2205, np.float32) * .1, 22050))
    monkeypatch.setattr(p.controller, "say", lambda text: None)
    got = []
    p.clip_ready.connect(lambda data, name: got.append(name))
    p.speech.ed.setText("gg ez")
    p.speech._say()
    assert p.speech.ed.text() == ""
    p.speech.b_keep.click()
    assert process_events(qapp, lambda: got)
    assert got == ["gg ez"]


def test_save_as_sound_says_why_it_failed(speech, qapp, monkeypatch):
    p = speech

    def broken(text, voice="", rate=0):
        raise RuntimeError("speech engine stopped")
    monkeypatch.setattr(p.controller.tts, "synth", broken)
    got = []
    p.clip_ready.connect(lambda data, name: got.append(name))
    p.speech.ed.setText("hi")
    p.speech.b_keep.click()
    assert process_events(qapp, lambda: not p.speech.tts_err.isHidden()
                          or "speech engine stopped" in p.speech.tts_err.text())
    assert "speech engine stopped" in p.speech.tts_err.text()
    assert not got
