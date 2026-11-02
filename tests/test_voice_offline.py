"""Voices that need a download (the animals' recordings) aren't offered while the app
can't download voices: Offline mode or Settings > Privacy's "voices" switch."""
import random

import pytest
from PySide6.QtWidgets import QMenu, QWidget

from soundboard import voicefx
from soundboard.online import net
from soundboard.speech import tts

ANIMALS = ("Cat", "Dog", "Goat", "Duck", "Pig", "Sheep", "Cow", "Farm")


def test_every_animal_needs_a_download():
    from soundboard.voicefx.builtin.animals import _Critter
    critters = {t for t, cls in voicefx.REGISTRY.items() if issubclass(cls, _Critter)}
    assert {"cat", "dog", "goat", "duck", "pig", "sheep", "cow", "farm"} <= critters
    made_in_code = {"chatter", "whistle", "kazoo"}   # (they listen like one, play no recordings)
    for t, cls in voicefx.REGISTRY.items():
        assert cls.needs_download == (t in critters - made_in_code), t
    for name in ANIMALS:
        assert voicefx.needs_download(voicefx.PRESETS[name]), name
    assert not voicefx.needs_download(voicefx.PRESETS["Robot"])
    # a saved voice: only an animal that's switched on counts
    assert voicefx.needs_download({"cat": {"on": True}, "pitch": {"on": True}})
    assert not voicefx.needs_download({"cat": {"on": False}, "pitch": {"on": True}})
    assert not voicefx.needs_download({})


@pytest.fixture
def fx(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicefxpanel import VoiceFxPanel
    holder = QWidget()
    panel = VoiceFxPanel({})
    panel.setParent(holder)
    holder.show()
    panel.setGeometry(0, 0, 1200, 1400)
    qapp.processEvents()
    yield panel
    holder.deleteLater()


@pytest.mark.parametrize("off", [{"offline": True}, {"off": ["voices"]}])
def test_animal_cards_hide_while_voices_cant_download(fx, qapp, off):
    assert all(n in fx._shown for n in ANIMALS)
    net.configure_features(**off)
    qapp.processEvents()
    assert not any(n in fx._shown for n in ANIMALS)
    assert not any(fx._tile[n].isVisible() for n in ANIMALS)
    assert "Robot" in fx._shown and fx._tile["Robot"].isVisible()
    fx.bar.search.setText("cat")   # search doesn't find them either
    assert "Cat" not in fx._shown
    fx.bar.search.setText("")
    net.configure_features()       # back on: they're back, no restart
    qapp.processEvents()
    assert all(n in fx._shown and fx._tile[n].isVisible() for n in ANIMALS)


def test_random_voice_never_picks_an_animal_offline(fx):
    net.configure_features(offline=True)
    rng = random.Random(1)
    for _i in range(200):
        assert fx.roll(rng) not in ANIMALS


def test_the_voice_on_stays_on_when_downloads_go_off(fx, qapp):
    fx.pick("Cat")
    net.configure_features(offline=True)
    qapp.processEvents()
    assert fx.preset == "Cat"            # kept (its made-up call), only not offered
    assert "Cat" not in fx._roll_pool()


def test_saved_voice_with_an_animal_hides_too(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voice.voicefxpanel import VoiceFxPanel
    panel = VoiceFxPanel({})
    panel.store.voices["Barky"] = {"dog": {"on": True}}
    panel.store.voices["Plain"] = {"pitch": {"on": True, "semitones": 3}}
    assert panel.offered("Barky") and panel.offered("Plain")
    net.configure_features(offline=True)
    assert not panel.offered("Barky") and panel.offered("Plain")
    panel.deleteLater()


def test_mix_in_a_voice_leaves_the_animals_out_offline(fx, monkeypatch):
    from soundboard.ui.voice import voicefxpanel
    seen: list[str] = []

    class Menu(QMenu):
        def exec(self, *_a):   # the entries, instead of opening
            def walk(m):
                for a in m.actions():
                    if a.menu() is not None:
                        if a.isVisible():
                            walk(a.menu())
                    elif a.text():
                        seen.append(a.text())
            walk(self)
    monkeypatch.setattr(voicefxpanel, "QMenu", Menu)
    fx._mix_menu()
    assert any(fx.title_of(n) in seen for n in ANIMALS)
    seen.clear()
    net.configure_features(offline=True)
    fx._mix_menu()
    assert seen and not any(fx.title_of(n) in seen for n in ANIMALS)
