"""Edit sound → Effects → Voice: a voice changer voice, an AI voice or a saved voice combo
laid over a sound, picked from cards (ui.voicepicker)."""
import numpy as np
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard.audio import soundfx
from soundboard import voicefx
from soundboard.mic import voicesetups
from soundboard.speech import soundvoice
from soundboard.ui.sounds.dialogs import EffectsPanel
from soundboard.ui.sounds.voicepicker import ALL, FAVS, Catalog, VoicePicker, describe

ROBOT = {"robot": {"on": True, "freq": 100, "noise": 0.2, "mix": 1}}
ECHO = {"echo": {"on": True, "delay": 200, "feedback": 0.3, "mix": 0.3}}
RIVER = {"id": "river", "name": "River", "emoji": "🌊"}
BEAR = {"id": "bear", "name": "Bear", "emoji": "🐻"}


def catalog(**kw):
    cat = Catalog(fx=[("Robot", "Robot", ROBOT, None, False),
                      ("My echo", "My echo", ECHO, None, True)],
                  ai=[RIVER, BEAR], ai_ready=True)
    for k, v in kw.items():
        setattr(cat, k, v)
    return cat


def test_cards_put_a_voice_and_an_ai_voice_on_together(qapp):
    p = VoicePicker(catalog(), {})
    assert p.voice == {}
    p.fx_tiles["Robot"].click()
    p.ai_tiles["river"].click()
    v = p.voice
    assert v["effects"] == ROBOT and v["ai"]["id"] == "river" and v["name"] == "Robot + River"
    assert p.fx_tiles["Robot"].isChecked() and p.ai_tiles["river"].isChecked()
    p.fx_tiles["Robot"].click()                         # again: off
    assert "effects" not in p.voice or not p.voice["effects"]
    assert p.voice["ai"]["id"] == "river" and p.voice["name"] == "River"
    p.ai_tiles["river"].click()
    assert p.voice == {}


def test_favorites_and_your_own_come_first(qapp):
    starred = []
    p = VoicePicker(catalog(fx_favs=["My echo"], ai_favs=[],
                            star_fx=lambda n, on: starred.append((n, on))), {})
    assert p.fx_chips[FAVS].isChecked()                 # opens on your favorites
    shown = [n for n, t in p.fx_tiles.items() if not t.isHidden()]
    assert shown == ["My echo"]
    assert p.ai_chips[ALL].isChecked()                  # no AI favorites yet: all of them
    p.fx_tiles["Robot"].star.setChecked(True)           # a star here is one on the Voice tab
    assert starred == [("Robot", True)]


def test_a_setup_puts_its_whole_mix_on_and_can_be_saved(qapp):
    mix = {"name": "Deep girl", "effects": ECHO, "ai": {"id": "bear", "name": "Bear"}}
    saved = {}
    p = VoicePicker(catalog(setups=[("Deep girl", soundfx.clean_voice(mix))]), {},
                    lambda name, v: saved.setdefault(name, v) and name)
    p.setup_tiles["Deep girl"].click()
    assert p.voice["name"] == "Deep girl" and p.voice["ai"]["id"] == "bear"
    assert p.voice["effects"] == ECHO and p.ai_tiles["bear"].isChecked()
    assert p.btn_save.isEnabled()                       # saving again just renames it


def test_no_ai_add_on_says_where_to_get_it(qapp):
    p = VoicePicker(catalog(ai=[], ai_ready=False), {})
    assert not p.ai_tiles and not p.ai_chips


def test_the_effects_tab_shows_the_pick_and_takes_it_off(qapp):
    picked = {"name": "Robot + River", "effects": ROBOT,
              "ai": {"id": "river", "name": "River"}}
    p = EffectsPanel({}, None, lambda cur: picked)
    assert p.voice.text() == "Pick a voice" and p.voice_off.isHidden()
    p.voice.click()
    f = p.fx()
    assert f["voice"]["ai"]["id"] == "river" and p.voice.text() == "Robot + River"
    p.preset.setCurrentIndex(p.preset.findData("Nightcore"))   # a preset keeps the voice
    assert p.fx()["voice"]["name"] == "Robot + River"
    p.voice_off.click()
    assert not p.fx().get("voice")
    assert describe({}) == "No voice"


def test_setups_are_kept_in_their_own_file(app_dir):
    s = voicesetups.Store()
    assert s.put("  Deep   girl ", {"effects": ECHO, "ai": {"id": "bear"}}) == "Deep girl"
    assert s.put("nothing", {}) == ""
    again = voicesetups.Store()
    assert list(again.setups) == ["Deep girl"] and again.setups["Deep girl"]["ai"]["id"] == "bear"
    assert again.remove("Deep girl") and voicesetups.Store().setups == {}


def test_an_ai_voice_is_said_before_the_sounds_own_effects(monkeypatch):
    said = []

    def fake(mono, rate, vid, pitch=0.0, **_k):
        said.append((vid, len(mono)))
        return mono * 0.5
    monkeypatch.setattr(soundvoice, "render", fake)
    x = np.full((4800, 2), 0.4, np.float32)
    y = soundfx.render(x, {"voice": {"name": "River", "ai": {"id": "river"}}})
    assert said == [("river", 4800)] and np.allclose(y, 0.2, atol=1e-3)


def test_without_the_ai_add_on_the_sound_still_plays(monkeypatch):
    def gone(*_a, **_k):
        raise soundvoice.Unavailable("not installed")
    monkeypatch.setattr(soundvoice, "render", gone)
    x = np.full((4800, 2), 0.4, np.float32)
    y = soundfx.render(x, {"voice": {"name": "River", "ai": {"id": "river"}}})
    assert np.allclose(y, 0.4, atol=1e-3)


def test_the_ai_voices_delay_is_taken_out():
    rate = 48000
    rng = np.random.default_rng(1)
    a = np.repeat(rng.random(60), rate // 10).astype(np.float32)   # a bumpy loudness
    b = np.concatenate([np.zeros(int(0.03 * rate), np.float32), a])
    assert soundvoice.delay(a, b, rate) == int(0.03 * rate)


def test_the_catalog_has_every_built_in_voice(window):  # noqa: F811
    cat = window.editctl.voice_catalog()
    names = [n for n, *_x in cat.fx]
    assert names[:len(voicefx.PRESETS)] == list(voicefx.PRESETS)
    assert all(c["on"] for c in cat.fx[0][2].values())


# ---------------------------------------------------------------- the Voice tab's My voice combos

def test_the_voice_tab_saves_whats_on_and_turns_a_setup_back_on(window, app_dir):  # noqa: F811
    if not window.tabctl.tab_on("voice"):
        return
    vp = window.voice
    assert vp.current_setup() == {}                 # nothing on: nothing to save
    vp.fx.pick("Robot")
    now = vp.current_setup()
    assert now["fx"] == "Robot" and now["effects"]["robot"]["on"] and now["name"] == "Robot"
    assert vp.setups.put("Robo", now) == "Robo"
    assert "Robo" in vp.setups_bar.buttons          # the row shows it straight away
    vp.fx.btn_power.setChecked(False)
    vp.setups_bar.buttons["Robo"].click()           # one click: the voice is back on
    assert vp.fx.btn_power.isChecked() and vp.fx.preset == "Robot"
    # the sound picker lists it too, as a voice a sound can take
    names = [n for n, _v in window.editctl.voice_catalog().setups]
    assert names == ["Robo"]


def test_a_setup_whose_voice_was_deleted_still_turns_its_mix_on(window, app_dir):  # noqa: F811
    if not window.tabctl.tab_on("voice"):
        return
    vp = window.voice
    vp.use_setup({"name": "Gone", "fx": "No such voice", "effects": ECHO})
    assert vp.fx.btn_power.isChecked() and vp.fx.spec()["effects"]["echo"]["on"]
    vp.use_setup({"name": "Nothing"})                # a setup without it turns it off
    assert not vp.fx.btn_power.isChecked()


def test_deleting_a_setup_can_be_undone(window, app_dir):  # noqa: F811
    if not window.tabctl.tab_on("voice"):
        return
    vp = window.voice
    vp.setups.put("Robo", {"fx": "Robot", "effects": ROBOT})
    vp.setups_bar._delete("Robo")
    assert "Robo" not in vp.setups.setups and not vp.setups_bar.btn_undo.isHidden()
    vp.setups_bar.btn_undo.click()
    assert "Robo" in vp.setups.setups


def test_a_setup_can_be_renamed_to_any_name_in_its_place(app_dir):
    s = voicesetups.Store()
    s.put("Chipmunk + Bear", {"effects": ECHO})
    s.put("Robo", {"fx": "Robot", "effects": ROBOT})
    assert s.rename("Chipmunk + Bear", "  funny   high pitch one ") == "funny high pitch one"
    assert list(s.setups) == ["funny high pitch one", "Robo"]       # same place in the row
    assert s.setups["funny high pitch one"]["name"] == "funny high pitch one"
    assert s.rename("Robo", "FUNNY HIGH PITCH ONE") == ""           # another one's name
    assert s.rename("Robo", "   ") == "" and s.rename("Gone", "x") == ""
    assert s.rename("Robo", "ROBO") == "ROBO"                       # just its case
    assert list(voicesetups.Store().setups) == ["funny high pitch one", "ROBO"]


def test_the_setup_menu_renames_and_says_when_the_name_is_taken(window, app_dir, monkeypatch):  # noqa: F811
    if not window.tabctl.tab_on("voice"):
        return
    from soundboard.ui.voice import voicesetupsbar
    vp = window.voice
    vp.setups.put("Robo", {"fx": "Robot", "effects": ROBOT})
    vp.setups.put("Echo", {"effects": ECHO})
    answers = iter([("Echo", True), ("My robot", True)])
    monkeypatch.setattr(voicesetupsbar.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: next(answers)))
    vp.setups_bar._rename("Robo")
    assert list(vp.setups.setups) == ["Robo", "Echo"] and "Echo" in vp.setups_bar.note.text()
    vp.setups_bar._rename("Robo")
    assert list(vp.setups.setups) == ["My robot", "Echo"] and "My robot" in vp.setups_bar.buttons


def test_the_voice_tabs_and_my_setups_scroll_away_with_the_card(window, qapp):  # noqa: F811
    """On a short window the voice list had a sliver: the part tabs and My voice combos were
    pinned above it. They're the top of the scrolling part now; the Say bar and the
    bottom bar stay."""
    from tests.conftest import process_events
    w = window
    w.show()
    w.tabs.setCurrentWidget(w.voice)
    w.resize(900, 640)
    process_events(qapp, lambda: False, 0.3)
    v = w.voice
    page = v._scroll.widget()
    assert page.isAncestorOf(v.setups_bar) and page.isAncestorOf(v._tabs["fx"])
    assert not page.isAncestorOf(v.speech.say_bar) and not page.isAncestorOf(v.bar)


def test_a_short_voice_tab_on_a_tall_window_leaves_no_gap_above_it(window, qapp):  # noqa: F811
    """The spare height of a tall window went to the tabs and My voice combos (a 200 px gap
    under the tabs, My voice combos 200 px tall): it goes under the card."""
    from tests.conftest import process_events
    w = window
    w.show()
    w.tabs.setCurrentWidget(w.voice)
    w.resize(1400, 1100)
    v = w.voice
    for key in ("addons", "speak"):
        v.show_tab(key)
        process_events(qapp, lambda: False, 0.3)
        bar = v.setups_bar
        assert bar.height() <= bar.sizeHint().height() + 4, key
        tabs_bottom = v._tabs[key].mapTo(v._body, v._tabs[key].rect().bottomLeft()).y()
        assert bar.mapTo(v._body, bar.rect().topLeft()).y() - tabs_bottom < 40, key
