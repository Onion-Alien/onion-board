"""Your voices' own pictures (ui/voice/voicepics.py), and an AI voice's Save as a voice
making one of your own AI voices (AI voices > Mine)."""
from PySide6.QtGui import QColor, QImage

from soundboard.mic import savedvoices
from soundboard.mic.savedvoices import Store
from soundboard.speech import aivoicelist as avl
from soundboard.ui.voice import aivoicepanel, voicepics

from test_mainwindow import window  # noqa: F401

ROBOT = {"pitch": {"on": True, "semitones": 4.0}}


def red() -> QImage:
    img = QImage(40, 20, QImage.Format.Format_ARGB32)
    img.fill(QColor("red"))
    return img


def test_a_saved_voices_picture_survives_rename_delete_and_undo(app_dir):
    s = Store()
    s.put("Robo", ROBOT)
    assert s.picture("Robo") is None
    assert voicepics.write(red(), savedvoices.picture_path("0123456789ab"))
    s.set_picture("Robo", "0123456789ab")
    assert Store().picture("Robo") == app_dir / "voice-pictures" / "0123456789ab.png"
    assert QImage(str(s.picture("Robo"))).size().width() == voicepics.SAVED   # square
    s.rename("Robo", "Bot")
    assert Store().pics == {"Bot": "0123456789ab"}
    item = s.remove("Bot")
    assert not s.pics and Store().deleted[0].data["pic"] == "0123456789ab"
    s.take(item.id)
    s.restore(item)
    assert s.picture("Bot") is not None
    s.set_picture("Bot", "")                   # back to My own mix's
    assert Store().picture("Bot") is None


def test_a_pic_id_never_names_a_file_elsewhere(app_dir):
    (app_dir / "voices.json").write_text(
        '{"version": 1, "voices": [{"name": "A", "effects": {}, "pic": "../../x"}]}',
        encoding="utf-8")
    assert Store().pics == {}


def test_the_picker_offers_the_apps_pictures_my_own_mix_first():
    k = voicepics.keys()
    assert k[0] == voicepics.DEFAULT
    assert "voice-robot" in k and "ai-voice-bjorn" in k
    assert not any(x.startswith("achievement") or x == "onion-watch" for x in k)


def test_ai_save_as_a_voice_goes_under_ai_voices_mine(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QInputDialog
    vp, ai = window.voice, window.voice.ai
    bjorn = next(v for v in avl.BUILT_IN if v["id"] == "bjorn")
    monkeypatch.setattr(aivoicepanel, "read_voices",
                        lambda module, mine=None: [*avl.BUILT_IN, *ai.store.voices])
    monkeypatch.setattr(ai, "can_make", lambda: True)
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Deep Bjorn", True)))
    ai.set_modules([], voices=[*avl.BUILT_IN])
    saved_before = list(vp.fx.store.voices)
    ai.edit_voice("bjorn")
    ed = vp.ai_edit
    ed.rows["pitch"].chk.setChecked(True)
    ed.save_voice()
    mine = ai.store.voices
    assert [v["name"] for v in mine] == ["Deep Bjorn"]
    vid = mine[0]["id"]
    assert avl.is_mine(mine[0]) and mine[0]["mix"] == bjorn["mix"]
    assert mine[0]["recipe"]["base"] == "bjorn"
    assert list(vp.fx.store.voices) == saved_before   # not a voice changer voice
    assert vp.ai_fx[vid]["pitch"]["on"]              # it keeps the effects
    assert ai.current_voice() == vid and ed.voice_id == vid
    assert avl.picture_path(vid).is_file()           # Bjorn's picture, to start with
    assert ed.dlg_pic.property("editable")           # one of yours: its picture changes
    ed.dlg.close()


def grid_row(grid, w) -> int:
    return grid.getItemPosition(grid.indexOf(w))[0]


def test_voice_changer_mine_row_goes_first_once_you_save_one(window):  # noqa: F811
    from soundboard.ui.voice.voicetiles import MINE
    fx = window.voice.fx
    g = fx._tile_grid
    first = next(iter(k for k in fx._heads if k != MINE))
    assert grid_row(g, fx._heads[MINE]) > grid_row(g, fx._heads[first])   # none: last
    fx.store.put("Robo", ROBOT)
    fx._fill_saved()
    assert grid_row(g, fx._heads[MINE]) == 0                              # first
    mine_row = grid_row(g, fx._tile["Robo"])
    assert grid_row(g, fx.random_tile) in (mine_row, mine_row + 1)        # the die with it
    assert grid_row(g, fx.random_tile) < grid_row(g, fx._heads[first])


def test_ai_mine_row_goes_first_once_you_have_one(window, monkeypatch):  # noqa: F811
    from soundboard.ui.voice.aivoicecards import MINE
    ai = window.voice.ai
    monkeypatch.setattr(aivoicepanel, "read_voices",
                        lambda module, mine=None: [*avl.BUILT_IN, *ai.store.voices])
    monkeypatch.setattr(ai, "can_make", lambda: True)
    ai.set_modules([], voices=[*avl.BUILT_IN])
    g = ai._tile_grid
    assert grid_row(g, ai._heads[MINE]) > grid_row(g, ai._heads["men"])   # none: last
    ai.save_copy(next(v for v in avl.BUILT_IN if v["id"] == "bjorn"), "My Bjorn")
    assert grid_row(g, ai._heads[MINE]) == 0
