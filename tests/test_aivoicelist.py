"""AI voices to pick from: the built-in list, writing it and your own voices into the
installed add-on, your own voices' file and bin, samples, and the All voices window."""
import json
from pathlib import Path

import numpy as np
import pytest

from soundboard import modules
from soundboard.speech import aipreview
from soundboard.speech import aivoicelist as avl
from tests.conftest import process_events

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
    bear, nova = avl.BUILT_IN[0], avl.BUILT_IN[8]
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
    assert [v["id"] for v in avl.sync(folder, [mine()], write=False)] == \
        [v["id"] for v in avl.BUILT_IN]
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
    monkeypatch.setattr(aipreview, "_cache", {})
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


# ---------------------------------------------------------------- the window

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


def test_all_voices_window_lists_every_voice_with_its_words(qapp, app_dir):
    from soundboard.ui.aivoicebrowser import AiVoiceBrowser
    store = avl.Store()
    store.put(mine("Robo"))
    voices = avl.BUILT_IN + store.voices
    prev = FakePreviewer()
    d = AiVoiceBrowser(voices, "pixie", store, prev, True)
    picked = []
    d.picked.connect(picked.append)
    try:
        assert len(d.cards) == len(voices)
        bear = d.card("bear")
        assert bear.tags.text() == "Man · Very deep" and "deep" in bear.about.text()
        assert not d.card("pixie").b_use.isEnabled()
        bear.b_hear.click()
        assert prev.heard == ["bear"]
        bear.b_use.click()
        assert picked == ["bear"] and not bear.b_use.isEnabled()
        assert d.card("pixie").b_use.isEnabled()
        robo = d.cards[-1]
        assert robo.b_edit is not None and bear.b_edit is None
        robo.b_delete.click()
        assert store.voices == [] and not d.undo_bar.isHidden()
        assert d.b_bin.text() == "Recently deleted (1)"
        d.undo_bar.undo()
        assert [v["name"] for v in store.voices] == ["Robo"]
    finally:
        d.deleteLater()


def test_make_your_own_voice_from_two_others(qapp, app_dir):
    from soundboard.ui.aivoicebrowser import AiVoiceEditor
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
        assert v["description"] == "Made from Nova with 25 % Brick."
        assert v["recipe"] == {"base": "nova", "other": "brick", "amount": 0.25}
        kept = avl.Store().put(v)
        again = AiVoiceEditor(avl.BUILT_IN, kept, FakePreviewer())
        assert again.cb_base.currentData() == "nova" and again.sl_amount.value() == 25
        assert again.result_voice()["id"] == v["id"]
        again.deleteLater()
    finally:
        d.deleteLater()


def test_card_shows_who_the_voice_is_and_opens_the_window(qapp, app_dir, monkeypatch):
    from soundboard.speech.aivoice import AiVoiceController
    from soundboard.ui import aivoicebrowser
    from soundboard.ui.aivoicepanel import AiVoicePanel
    from soundboard.voicefx import VoiceChain
    folder = addon_copy(app_dir, all_speakers())
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    for f in ("stream.onnx", "speaker.onnx"):
        (folder / "model" / f).write_bytes(b"x")
    (info,) = modules.discover([app_dir])
    p = AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {"voice": "titan"},
                     [info])
    opened = []
    monkeypatch.setattr(aivoicebrowser.AiVoiceBrowser, "exec",
                        lambda self: opened.append(self) or 0)
    try:
        assert p.cb_voice.count() == len(avl.BUILT_IN)
        assert p.lbl_about.text().startswith("Monster · Rumbling. Deeper than")
        p.b_all.click()
        process_events(qapp, lambda: bool(opened))
        assert len(opened[0].cards) == len(avl.BUILT_IN)
    finally:
        for d in opened:
            d.deleteLater()
        p.shutdown()
        p.deleteLater()
