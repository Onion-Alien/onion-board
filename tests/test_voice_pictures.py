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


def test_save_whats_on_sits_over_the_bars_with_more_than_one_voice(window, monkeypatch):  # noqa: F811
    """It looked like one more tab beside the tabs, with its words cut off (a height
    measured before the theme applied). Now it's over the voices' bars, only while
    there's more than one voice to keep together."""
    from PySide6.QtWidgets import QApplication
    vp = window.voice
    save, row = vp.btn_save_mix, vp.save_mix_row
    window.tabs.setCurrentIndex(window.tabs.indexOf(vp))
    window.resize(1400, 900)
    window.show()
    assert save.parentWidget() is row and row.parentWidget() is vp

    def voices(*keys):
        monkeypatch.setattr(vp, "on_keys", lambda: list(keys))
        vp._update_bar()
        QApplication.processEvents()
        return row.isVisibleTo(vp)

    assert not voices() and not voices("fx") and not voices("lang")
    assert voices("fx", "ai") and voices("fx", "ai", "lang")
    for key in vp._tabs:                                 # on every tab, as the bars are
        vp.show_tab(key)
        assert row.isVisibleTo(vp)
    vp.fx.pick("Robot")
    QApplication.processEvents()
    assert row.y() + row.height() <= vp.fx.picked.y()    # over the bars
    assert save.x() == 0 and save.height() >= save.sizeHint().height()
    assert save.width() == save.sizeHint().width()       # as wide as its words
    window.themectl._apply_theme("Light")                # (a theme change keeps it whole)
    QApplication.processEvents()
    assert save.height() >= save.sizeHint().height()
    pause, stop = vp._bar_ctl["fx"]                      # the bar's buttons: one height
    assert pause.height() == stop.height() == vp.fx.btn_effects.height()
    window.resize(640, 900)
    QApplication.processEvents()
    assert save.height() >= save.sizeHint().height() and save.width() <= row.width()


def test_the_combos_tab_shows_once_you_have_one(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QApplication, QInputDialog, QLabel
    vp = window.voice
    tab = vp._tabs["mixes"]
    assert not tab.isVisibleTo(vp)                       # none yet: no tab
    vp.fx.pick("Robot")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Robo", True)))
    vp.btn_save_mix.click()
    assert list(vp.setups.setups) == ["Robo"] and tab.isVisibleTo(vp)
    vp.show_tab("mixes")
    bar = vp.setups_bar
    assert bar.isVisibleTo(vp)
    assert list(bar.buttons) == ["Robo"] and bar.btn_save.isVisibleTo(vp)
    words = [t.text() for t in bar.buttons["Robo"].findChildren(QLabel)]
    assert "Robo" in words and "Voice changer: Robot" in words   # says what's in it
    window.themectl._apply_theme("Light")                # (a theme change kept its height)
    window.show()
    QApplication.processEvents()
    card = bar.buttons["Robo"]
    assert card.height() == bar.btn_save.height() and card.height() >= 60
    vp.fx.btn_power.setChecked(False)
    bar.buttons["Robo"].click()                          # one click: it's on again
    assert vp.fx.btn_power.isChecked() and vp.fx.preset == "Robot"
    bar._delete("Robo")                                  # the last one: Undo is there
    assert tab.isVisibleTo(vp) and vp.current_tab() == "mixes"
    assert bar.btn_undo.isVisibleTo(vp)
    bar.btn_undo.click()                                 # back
    assert list(vp.setups.setups) == ["Robo"] and tab.isVisibleTo(vp)
    bar._delete("Robo")
    bar._forget_undo()                                   # Undo ran out: the tab goes
    assert not tab.isVisibleTo(vp) and vp.current_tab() == "fx"


def test_make_your_own_voice_card_opens_edit_voice_on_your_own_mix(window):  # noqa: F811
    from soundboard.ui.voice.voicetiles import CUSTOM
    fx = window.voice.fx
    b = fx._tile[CUSTOM]
    assert b.title == "Make your own voice" and b.star.isHidden()
    b.click()
    assert fx.btn_power.isChecked() and fx.preset == CUSTOM and fx.dlg.isVisible()
    fx.dlg.close()
    b.click()                                            # on already: stays on, opens again
    assert fx.btn_power.isChecked() and fx.dlg.isVisible()
    fx.dlg.close()
