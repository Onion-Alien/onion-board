"""Built-in voice effects: plain numpy DSP (filters from soundboard.audio.dsp), cheap enough
for the mic callback.

Every effect works on 1-D float32 blocks and keeps its own memory between blocks.
Recursive delays (echo, reverb) are computed in chunks no longer than their delay,
so each chunk only depends on output that already exists: whole-array numpy maths
instead of a per-sample Python loop.

The effects run in the order they are registered, which is the order of the imports
below (pitch first, room last): a voice is shaped, then squashed, then band-limited
and driven, then put in a space. Each module is one family of effects; `parts` holds
the building blocks they share, and the voices in `presets` are built from them.
"""
from __future__ import annotations

# importing a module registers its effects: keep these in the order the effects run
from soundboard.voicefx.builtin.pitch import Growl, Harmony, PitchShift
from soundboard.voicefx.builtin.synth import Monk, RingMod, Robot
from soundboard.voicefx.builtin.animals import Cat, Dog
from soundboard.voicefx.builtin.syllables import Chatter, Drums, Fart
from soundboard.voicefx.builtin.tunes import Kazoo, Whistle
from soundboard.voicefx.builtin.tone import Compressor, Distortion, Helmet, Radio, Shout, Tone
from soundboard.voicefx.builtin.glitch import Glitch
from soundboard.voicefx.builtin.retro import BitCrush
from soundboard.voicefx.builtin.modulation import Chorus, Flanger, Wobble
from soundboard.voicefx.builtin.space import (Echo, ExtraEcho, ExtraRadio, ExtraReverb,
                                              ExtraAutotune, ExtraBitCrush, ExtraRobot,
                                              Reverb)
from soundboard.voicefx.builtin.background import Background
from soundboard.voicefx.builtin.polish import Polish

from soundboard.voicefx.builtin.presets import PRESET_ICONS, PRESETS
from soundboard.voicefx.builtin.texts import shown_texts

__all__ = ["PitchShift", "Harmony", "Growl", "Robot", "Monk", "RingMod", "Cat", "Dog",
           "Compressor", "Tone", "Radio", "Distortion", "Shout", "Helmet", "Glitch", "BitCrush",
           "Chorus",
           "Flanger", "Wobble", "Echo", "Reverb", "ExtraRobot", "ExtraRadio", "ExtraEcho",
           "ExtraAutotune", "ExtraBitCrush",
           "ExtraReverb", "Chatter", "Fart", "Drums", "Whistle", "Kazoo",
           "Background", "Polish", "PRESETS", "PRESET_ICONS", "shown_texts"]
