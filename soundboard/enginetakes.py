"""The engine's recordings: the setup test's recording and the mic / playback takes
(recording a sound). Only starts, stops and hands over: the audio callbacks append
the blocks themselves (engine.py), to the lists these methods set up.

A mixin Engine inherits, so every `self.` lookup is the same as before.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np


class EngineTakes:
    """Test recording and takes (see the module)."""

    if TYPE_CHECKING:   # the engine's own (Engine.__init__, the audio path), used here
        rates: dict[str, int]
        main_stream: Any
        mic_stream: Any

    # ----------------------------------------------------------------- test record
    @property
    def rec_done(self) -> tuple[np.ndarray, int] | None:
        """(audio, rate) of the finished test recording, or None."""
        done = self._rec_done
        if done is None:
            return None
        blocks, rate = done
        if isinstance(blocks, list):
            blocks = np.concatenate(blocks)
            self._rec_done = (blocks, rate)
        return blocks, rate

    @rec_done.setter
    def rec_done(self, value):
        self._rec_done = value

    def start_test_record(self, seconds: float):
        self.rec_done = None
        self._rec_frames_left = int(seconds * self.rates["main"])
        self._mic_rec = [] if self.mic_stream is not None else None
        self._rec_buf = []

    def cancel_test_record(self):
        """Give up on a test recording (its output device stopped mid-way)."""
        self._rec_buf = None      # first: the main callback checks it before finishing
        self._rec_frames_left = 0
        self._mic_rec = None
        self.rec_done = None

    def take_mic_recording(self) -> tuple[np.ndarray, int] | None:
        """The mic captured during the last test, at the mic's rate: (n, 2) with the
        raw mic in column 0 and the mic as sent (after the voice changer) in column 1,
        which is what testcheck.analyze looks for in the output."""
        rec, self._mic_rec = self._mic_rec, None
        if not rec:
            return None
        return np.concatenate(rec), self.rates["mic"]

    @property
    def recording(self) -> bool:
        return self._rec_buf is not None

    def start_mic_take(self, processed: bool = False) -> list[np.ndarray]:
        """Record a sound with the mic: from now on every mic block (the raw mic, or with
        `processed` the mic after the voice changer) is appended, as a copy at the mic's
        rate (`rates["mic"]`), to the list returned. The caller takes blocks off its
        front as it goes (`del blocks[:n]`: safe against the audio thread's append) and
        ends it with stop_mic_take(). A test recording running meanwhile is untouched."""
        self._take_fx = processed
        self._take = blocks = []
        return blocks

    def stop_mic_take(self) -> list[np.ndarray]:
        """End the take; returns its list (with any blocks not yet taken off it)."""
        blocks, self._take = self._take, None
        return blocks if blocks is not None else []

    @property
    def taking(self) -> bool:
        return self._take is not None

    def start_play_take(self) -> list[np.ndarray]:
        """Record a sound from what's playing: from now on every block of your sounds
        (web results and the link bar's too) and the radio, as you hear them and
        without your mic, is appended at the main output's rate (`rates["main"]`) to
        the list returned, like start_mic_take. With no send device open it's taken from
        your headphones instead (`play_take_out`, at that rate)."""
        self.play_take_out = "main" if self.main_stream is not None else "mon"
        self._play_take = blocks = []
        return blocks

    def stop_play_take(self) -> list[np.ndarray]:
        blocks, self._play_take = self._play_take, None
        return blocks if blocks is not None else []

    @property
    def play_taking(self) -> bool:
        return self._play_take is not None
