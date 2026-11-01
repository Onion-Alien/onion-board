"""AI voices to pick from: the built-in list, writing it and your own voices into the
installed add-on, your own voices' file and bin, samples, and the All voices window."""
from collections import OrderedDict
import json
from pathlib import Path

import numpy as np
import pytest

from soundboard.addons import modules
from soundboard.speech import aipreview
from soundboard.speech import aivoicelist as avl

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "modules" / "ai-voices"


def addon_copy(tmp_path, speakers=None) -> Path:
    """An installed-looking add-on folder; its model holds `speakers` (None: a model
    file that can't be read)."""
    folder = tmp_path / "ai-voices"
    folder.mkdir()
    for f in ("module.json", "voices.json"):
        (folder / f).write_bytes((ADDON / f).read_bytes())
    (folder / "model").mkdir()
    if speakers is None:
        (folder / "model" / "voices.npz").write_bytes(b"x")
    else:
        np.savez(folder / "model" / "voices.npz", ids=np.array(sorted(speakers)))
    return folder


def all_speakers():
    return {s for v in avl.BUILT_IN for s, _w in v["mix"]}


def mine(name="Robo", **kw):
    v = {"id": avl.new_id(), "name": name, "emoji": "🤖", "description": "", "about": "",
         "tags": [], "mix": [[171, 0.7], [27, 0.3]], "formant": 0.5, "pitch_hz": 150}
    v.update(kw)
    return v


def test_the_app_and_the_addon_list_the_same_voices():
    data = json.loads((ADDON / "voices.json").read_text(encoding="utf-8"))
    assert data["voices"] == avl.BUILT_IN
    for v in avl.BUILT_IN:
        assert avl.clean_voice(v) == v          # already clean
        assert v["about"] and v["tags"] and avl.pitch_word(v["pitch_hz"])


def test_new_voices_use_only_speakers_the_released_model_has():
    """The first released model (ai-voices 0.1.0) holds only the speakers its six
    voices used: a new built-in voice must be a blend of those, so it works without
    downloading a new model."""
    first_six = {171, 60, 85, 188, 80, 5, 156, 151, 127, 29, 108, 27, 136, 53, 18, 110, 141}
    assert all_speakers() <= first_six


def test_pitch_words_and_tag_lines():
    assert avl.pitch_word(72) == "Rumbling"
    assert avl.pitch_word(118) == "Low"
    assert avl.pitch_word(265) == "High"
    assert avl.pitch_word("x") == avl.pitch_word(0) == ""
    assert avl.tag_line(avl.BUILT_IN[0]) == "Man · Very deep"
    assert avl.tag_line(mine()).startswith("Your voice · ")


def test_voices_are_cleaned():
    v = avl.clean_voice({"id": "my-x", "name": "  A   very long name that goes on and on ",
                         "mix": [[1, 2.0], ["bad"], [2, -1], [3, 0.5]], "formant": 9,
                         "pitch_hz": 5000, "tags": ["Man", 3], "recipe": {"base": "bear",
                                                                          "amount": 7}})
    assert len(v["name"]) <= avl.MAX_NAME and "  " not in v["name"]
    assert v["mix"] == [[1, 1.0], [3, 0.5]]
    assert v["formant"] == 2.0 and v["pitch_hz"] == 400 and v["tags"] == ["Man"]
    assert v["recipe"] == {"base": "bear", "other": "", "amount": 0.5}
    assert avl.clean_voice({"id": "x", "name": "n", "mix": []}) is None
    assert avl.clean_voice({"id": "x", "name": "n", "mix": [[1, 1]]}, speakers={2}) is None
    assert avl.clean_voice("nope") is None


def test_blend_mixes_in_part_of_another_voice():
    by_id = {v["id"]: v for v in avl.BUILT_IN}
    bear, nova = by_id["bear"], by_id["nova"]
    assert avl.blend(bear) == [[171, 0.5], [60, 0.25], [85, 0.25]]
    mix = dict(avl.blend(bear, nova, 0.2))
    assert mix[171] == pytest.approx(0.4) and mix[27] == pytest.approx(0.1)
    assert sum(mix.values()) == pytest.approx(1.0)


def test_sync_brings_an_old_addon_up_to_date_with_your_voices(tmp_path):
    folder = addon_copy(tmp_path, all_speakers())
    data = json.loads((folder / "voices.json").read_text(encoding="utf-8"))
    data["voices"] = data["voices"][:2] + [{"id": "old", "name": "Old", "mix": [[5, 1]]}]
    (folder / "voices.json").write_text(json.dumps(data), encoding="utf-8")
    me = mine()
    voices = avl.sync(folder, [me, mine("Bad", mix=[[999, 1.0]])])
    ids = [v["id"] for v in voices]
    assert ids == [v["id"] for v in avl.BUILT_IN] + [me["id"], "old"]
    written = json.loads((folder / "voices.json").read_text(encoding="utf-8"))
    assert written["voices"] == voices and written["model"] == data["model"]
    # nothing changed: not written again
    before = (folder / "voices.json").stat().st_mtime_ns
    assert avl.sync(folder, [me]) == voices
    assert (folder / "voices.json").stat().st_mtime_ns == before
    # your voice deleted: gone from the add-on too
    assert me["id"] not in [v["id"] for v in avl.sync(folder, [])]


def test_sync_leaves_out_voices_the_model_cant_make(tmp_path):
    folder = addon_copy(tmp_path, all_speakers() - {60})
    data = json.loads((folder / "voices.json").read_text(encoding="utf-8"))
    data["voices"] = [v for v in data["voices"] if v["id"] == "max"]
    (folder / "voices.json").write_text(json.dumps(data), encoding="utf-8")
    ids = [v["id"] for v in avl.sync(folder, [])]
    assert "bear" not in ids and "titan" not in ids and "max" in ids and "nova" in ids


def test_sync_with_an_unreadable_model_uses_only_known_speakers(tmp_path):
    folder = addon_copy(tmp_path, None)
    ids = [v["id"] for v in avl.sync(folder, [mine(mix=[[999, 1.0]])])]
    assert ids == [v["id"] for v in avl.BUILT_IN]


def test_sync_doesnt_write_into_a_copy_that_isnt_installed(tmp_path):
    folder = addon_copy(tmp_path, all_speakers())
    before = (folder / "voices.json").read_bytes()
    me = mine()
    # your voices are still listed (its helper reads them from your file)
    assert [v["id"] for v in avl.sync(folder, [me, mine("Bad", mix=[[999, 1.0]])],
                                      write=False)] == \
        [v["id"] for v in avl.BUILT_IN] + [me["id"]]
    assert (folder / "voices.json").read_bytes() == before


def test_your_voices_are_kept_and_deleted_ones_can_come_back(app_dir):
    s = avl.Store()
    a, b = s.put(mine("A")), s.put(mine("B"))
    assert [v["name"] for v in avl.Store().voices] == ["A", "B"]
    item = s.remove(a["id"])
    assert [v["name"] for v in avl.Store().voices] == ["B"]
    assert [i.name for i in avl.Store().items()] == ["A"]
    assert s.restore(s.take(item.id))["id"] == a["id"]
    assert [v["name"] for v in avl.Store().voices] == ["A", "B"] and not s.deleted
    assert s.put({"id": "bear", "name": "Not mine", "mix": [[1, 1]]}) is None
    assert b == s.get(b["id"])


def test_a_damaged_file_is_set_aside_not_overwritten(app_dir):
    avl.path().write_text("{not json", encoding="utf-8")
    s = avl.Store()
    assert s.voices == [] and list(app_dir.glob("ai-voices.json.broken-*"))


def test_samples_are_made_once_per_sound(monkeypatch):
    calls = []
    monkeypatch.setattr(aipreview, "_cache", OrderedDict())
    monkeypatch.setattr(aipreview, "sample", lambda: np.zeros(16000, np.float32))

    def render(module, voice, mono16):
        calls.append(voice["id"])
        return np.full(24000, 2.0, np.float32)
    monkeypatch.setattr(aipreview, "render", render)
    v = dict(avl.BUILT_IN[0])
    out = aipreview.make(None, v)
    assert out.shape == (48000, 2) and np.max(np.abs(out)) <= 0.8 + 1e-6
    renamed = dict(v, id="other", name="Other")
    assert aipreview.make(None, renamed) is out and calls == ["bear"]


def test_render_without_the_addons_python_says_so(tmp_path):
    info = modules.ModuleInfo("ai-voices", "AI voices", "1", "", "service", tmp_path)
    with pytest.raises(aipreview.PreviewError, match="installed"):
        aipreview.render(info, avl.BUILT_IN[0], np.zeros(10, np.float32))


# ---------------------------------------------------------------- the card

class FakePreviewer:
    def __init__(self):
        self.heard = []
        self.busy = False

    def available(self):
        return True

    def hear(self, btn, voice, sig, on_error):
        self.heard.append(voice["id"])

    def done(self, *a):
        pass


def test_make_your_own_voice_from_two_others(qapp, app_dir):
    from soundboard.ui.voice.aivoicebrowser import AiVoiceEditor
    d = AiVoiceEditor(avl.BUILT_IN, None, FakePreviewer())
    try:
        d.ed_name.setText("Gravel Nova")
        d.cb_base.setCurrentIndex(d.cb_base.findData("nova"))
        assert d.sl_pitch.value() == 215          # starts at its height
        d.cb_other.setCurrentIndex(d.cb_other.findData("brick"))
        d.sl_amount.setValue(25)
        d.sl_formant.setValue(-1)
        v = d.result_voice()
        assert v["name"] == "Gravel Nova" and avl.is_mine(v)
        assert v["formant"] == -0.5 and v["pitch_hz"] == 215
        assert dict(v["mix"])[156] == pytest.approx(0.125)
        assert v["description"] == "Made from Nova with 25% Brick."
        assert v["recipe"] == {"base": "nova", "other": "brick", "amount": 0.25}
        kept = avl.Store().put(v)
        again = AiVoiceEditor(avl.BUILT_IN, kept, FakePreviewer())
        assert again.cb_base.currentData() == "nova" and again.sl_amount.value() == 25
        assert again.result_voice()["id"] == v["id"]
        again.deleteLater()
    finally:
        d.deleteLater()


def test_your_voice_can_have_its_own_picture(qapp, app_dir, monkeypatch):
    from PySide6.QtGui import QColor, QImage
    from soundboard.ui.voice import aivoicebrowser
    from soundboard.ui.voice.aivoicebrowser import AiVoiceEditor
    src = app_dir / "wide.png"
    img = QImage(300, 100, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    assert img.save(str(src))
    d = AiVoiceEditor(avl.BUILT_IN, None, FakePreviewer())
    try:
        assert d.b_pic_clear.isHidden()                 # none yet: My own mix's
        d.save_picture()
        assert not avl.picture_path(d.vid).exists()     # nothing picked: nothing written
        monkeypatch.setattr(aivoicebrowser.QFileDialog, "getOpenFileName",
                            lambda *a, **k: (str(src), ""))
        d.b_pic.click()
        assert not d.b_pic_clear.isHidden()
        d.reject()                                      # Cancel: not kept
        assert not avl.picture_path(d.vid).exists()
        d.accept()                                      # Save: a square PNG by its id
        kept = QImage(str(avl.picture_path(d.vid)))
        assert (kept.width(), kept.height()) == (aivoicebrowser.PIC_SAVED,) * 2
        v = avl.Store().put(d.result_voice())
        assert v is not None and v["emoji"] == ""
        again = AiVoiceEditor(avl.BUILT_IN, v, FakePreviewer())
        assert again.picture is not None and not again.b_pic_clear.isHidden()
        again.b_pic_clear.click()
        again.accept()
        assert not avl.picture_path(d.vid).exists()
        again.deleteLater()
        d.accept()
        s = avl.Store()                                 # deleted for good: picture too
        item = s.remove(v["id"])
        assert avl.picture_path(v["id"]).exists()       # (kept for Undo)
        s.forget(item.id)
        assert not avl.picture_path(v["id"]).exists()
    finally:
        d.deleteLater()


def ready_panel(app_dir, monkeypatch, settings=None):
    """The AI voices card with the add-on installed (yours: you can make voices)."""
    from soundboard.addons import aiaddon
    from soundboard.speech.aivoice import AiVoiceController
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel
    from soundboard.voicefx import VoiceChain
    folder = addon_copy(app_dir, all_speakers())
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    for f in ("stream.onnx", "speaker.onnx"):
        (folder / "model" / f).write_bytes(b"x")
    monkeypatch.setattr(aiaddon, "removable", lambda m, base=None: True)
    (info,) = modules.discover([app_dir])
    p = AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), settings or {},
                     [info])
    p.previewer = FakePreviewer()
    return p


def test_card_shows_every_voice_as_a_card_under_its_kind(qapp, app_dir, monkeypatch):
    p = ready_panel(app_dir, monkeypatch, {"voice": "titan"})
    shown = lambda: [vid for vid, b in p._tile.items() if not b.isHidden()]  # noqa: E731
    try:
        assert sorted(p._tile) == sorted(v["id"] for v in avl.BUILT_IN)
        assert p.picked_name.text() == "Titan"
        assert not any(b.isChecked() for b in p._tile.values())   # off: none lit up
        assert p.picked_name.toolTip().startswith("Monster · Rumbling. Deeper than")
        assert p.picked.isHidden()                               # off: no voice bar
        assert p._tile["bear"].toolTip().startswith("Man · Very deep. ")
        assert p.b_edit.isHidden() and p.b_delete.isHidden()     # not one of yours
        p.bar.choose("women")
        g = p._tile_grid
        order = sorted(shown(), key=lambda vid: (g.getItemPosition(g.indexOf(p._tile[vid]))))
        assert order == ["onyx", "ivy", "sage", "nana", "nova", "zoe", "pixie"]   # lowest first
        p.bar.choose("mine")
        # none of yours yet: just the card that makes one
        assert shown() == [] and not p.make_tile.isHidden()
        saved, starts = [], []
        p.changed.connect(saved.append)
        monkeypatch.setattr(p.ctl, "start", lambda m, voice, *a: starts.append(voice))
        monkeypatch.setattr(p.ctl, "stop", lambda: None)
        p.bar.choose("")
        p._tile["bear"].click()                                   # picks it and starts it
        assert saved[-1]["voice"] == "bear" and p.current_voice() == "bear"
        assert starts == ["bear"] and p.is_on()
        assert p.picked_name.text() == "Bear" and not p._tile["titan"].isChecked()
        assert p._tile["bear"].isChecked()                        # on: its card lit
        p.stop()
        assert not p.is_on() and not p._tile["bear"].isChecked()
        p.b_hear.click()
        assert p.previewer.heard == ["bear"]
    finally:
        p.shutdown()
        p.deleteLater()


def test_card_favorites_are_kept_in_the_order_starred(qapp, app_dir, monkeypatch):
    from soundboard.speech import aivoice
    p = ready_panel(app_dir, monkeypatch)
    shown = lambda: {vid for vid, b in p._tile.items() if not b.isHidden()}  # noqa: E731
    saved = []
    p.changed.connect(saved.append)
    try:
        p.bar.choose("favs")
        assert shown() == set() and not p.no_favs.isHidden()
        p._tile["nova"].star.click()
        p._tile["bear"].star.click()
        assert shown() == {"nova", "bear"} and p.no_favs.isHidden()
        assert saved[-1]["favorites"] == ["nova", "bear"]
        assert aivoice.clean_settings(saved[-1])["favorites"] == ["nova", "bear"]
        p._tile["nova"].star.click()
        assert shown() == {"bear"} and saved[-1]["favorites"] == ["bear"]
        assert aivoice.clean_settings({"favorites": ["a", 3, "a", ""]})["favorites"] == ["a"]
        (app_dir / "again").mkdir()
        again = ready_panel(app_dir / "again", monkeypatch, saved[-1])
        assert again.favorites == ["bear"] and again._tile["bear"].star.isChecked()
        again.shutdown()
        again.deleteLater()
    finally:
        p.shutdown()
        p.deleteLater()


def test_card_makes_changes_and_deletes_your_own_voices(qapp, app_dir, monkeypatch):
    from soundboard.ui.voice import aivoicebrowser
    p = ready_panel(app_dir, monkeypatch, {"voice": "nova"})
    made = mine("Robo", tags=["Man"], pitch_hz=100)
    monkeypatch.setattr(aivoicebrowser.AiVoiceEditor, "exec", lambda self: 1)
    monkeypatch.setattr(aivoicebrowser.AiVoiceEditor, "result_voice", lambda self: made)
    try:
        p.b_make.click()                                # made, and picked
        assert made["id"] in p._tile and p.current_voice() == made["id"]
        assert p.b_edit.isHidden() and p.b_delete.isHidden()   # on its right-click
        p.bar.choose("mine")
        assert [vid for vid, b in p._tile.items() if not b.isHidden()] == [made["id"]]
        p.b_delete.click()                              # gone: back to the first voice
        assert made["id"] not in p._tile and avl.Store().voices == []
        assert p.current_voice() == p.voices[0]["id"] and p.undo_bar.active()
        assert p.b_bin.text() == "Recently deleted (1)" and not p.b_bin.isHidden()
        p.undo_bar.undo()
        assert made["id"] in p._tile and [v["name"] for v in avl.Store().voices] == ["Robo"]
    finally:
        p.shutdown()
        p.deleteLater()


def test_card_makes_your_own_voices_with_a_copy_shipped_with_the_app(qapp, app_dir,
                                                                     monkeypatch):
    """Running from source the add-on is the source tree's copy, never written to:
    Make your own voice still works, and the voice is listed from your file."""
    from soundboard.addons import aiaddon
    from soundboard.ui.voice import aivoicebrowser
    p = ready_panel(app_dir, monkeypatch, {"voice": "nova"})
    monkeypatch.setattr(aiaddon, "removable", lambda m, base=None: False)
    before = (app_dir / "ai-voices" / "voices.json").read_bytes()
    made = mine("Robo")
    monkeypatch.setattr(aivoicebrowser.AiVoiceEditor, "exec", lambda self: 1)
    monkeypatch.setattr(aivoicebrowser.AiVoiceEditor, "result_voice", lambda self: made)
    try:
        p._refresh()
        assert p.make_tile.isEnabled() and p.b_make.isEnabled()
        assert not p.b_remove.isHidden()           # Remove shows for this copy too
        p.make_tile.click()
        assert made["id"] in p._tile and p.current_voice() == made["id"]
        assert (app_dir / "ai-voices" / "voices.json").read_bytes() == before
    finally:
        p.shutdown()
        p.deleteLater()


def test_voices_sort_into_who():
    kinds = {v["id"]: avl.who(v) for v in avl.BUILT_IN}
    assert kinds["bear"] == kinds["riley"] == "men"
    assert kinds["sage"] == kinds["pixie"] == "women"
    assert kinds["river"] == kinds["squeak"] == kinds["titan"] == "other"
    assert avl.who(mine(tags=["Woman"])) == "women" and avl.who(mine()) == "other"




def test_a_built_in_voice_shows_its_picture_when_there_is_one(qapp, monkeypatch):
    from PySide6.QtGui import QIcon, QPixmap
    from soundboard.ui.voice import aivoicepanel, art
    pic = QIcon(QPixmap(8, 8))
    asked = []
    monkeypatch.setattr(art, "icon",
                        lambda key: asked.append(key) or (pic if key == "ai-voice-bear" else None))
    by_id = {v["id"]: v for v in avl.BUILT_IN}
    assert aivoicepanel.voice_icon(by_id["bear"]) is pic
    assert aivoicepanel.voice_icon(by_id["nova"]) is not pic       # no picture: its emoji
    assert aivoicepanel.art_key(mine()) == "" and asked == ["ai-voice-bear", "ai-voice-nova"]


def test_card_works_like_the_voice_changer(qapp, app_dir, monkeypatch):
    """The voice changer's switch, cards-or-list and voice bar, with Edit voice's pitch
    in a pop-up; the switch can't be turned on before the add-on is there."""
    from soundboard.speech.aivoice import AiVoiceController
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel
    from soundboard.voicefx import VoiceChain
    bare = AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {}, [])
    try:
        assert not bare.b_start.isEnabled() and bare.b_start.text() == "Off"
        assert bare.b_start.toolTip() == bare.lbl_missing.text() != ""
    finally:
        bare.deleteLater()
    p = ready_panel(app_dir, monkeypatch, {"voice": "bear"})
    monkeypatch.setattr(p.ctl, "start", lambda m, voice, *a: None)
    monkeypatch.setattr(p.ctl, "stop", lambda: None)
    try:
        assert p.b_start.isEnabled() and p.lbl_state.isHidden() and p.picked.isHidden()
        p.b_start.setChecked(True)                    # the switch starts the picked voice
        assert p.is_on() and p.b_start.text() == "On"
        assert not p.picked.isHidden() and p.picked_name.text() == "Bear"
        assert not p.lbl_state.isHidden()             # starting…: says so under the words
        p.btn_tweak.click()                           # Edit voice: the pitch, in a pop-up
        assert p.tweak_pop is not None and p.tweak_pop.isVisible()
        assert p.chk_auto.window() is p.tweak_pop and p.sl_pitch.isVisible()
        p.tweak_pop.close()
        p.set_view("list")                            # the voice changer's list view
        assert all(b.listed for b in p._tile.values()) and p.make_tile.listed
        assert p.view_toggle.view() == "list"
        p.b_start.setChecked(False)
        assert not p.is_on() and p.b_start.text() == "Off"
        assert p.picked.isHidden() and p.lbl_state.isHidden()
        assert not any(b.isChecked() for b in p._tile.values())
        p._tile["bear"].click()                       # a card: on with that voice
        assert p.is_on() and p._tile["bear"].isChecked() and p.b_start.text() == "On"
        p._tile["bear"].click()                       # the lit one again: off
        assert not p.is_on() and not p._tile["bear"].isChecked()
        assert p.b_start.text() == "Off" and p.picked.isHidden()
    finally:
        p.deleteLater()
