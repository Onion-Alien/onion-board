"""Text-to-speech with the voices built into Windows (no download, works in the exe).

System.Speech is a .NET API, so a single hidden PowerShell process is kept running
and handed one line per sentence. It writes a WAV file and answers "OK", and
`SapiTTS.synth` reads that file back. Starting PowerShell takes about a second, so
it is started once, on first use (or ahead of time with `warm_up`).

`Speaker` queues sentences and plays them one after another through a callback,
so a second line never talks over the first.
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from collections.abc import Callable

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)

TTS_RATE = 22050

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$names = ($s.GetInstalledVoices() | Where-Object { $_.Enabled } |
    ForEach-Object { $_.VoiceInfo.Name }) -join '|'
[Console]::Out.WriteLine('READY ' + $names)
[Console]::Out.Flush()
$utf8 = [Text.Encoding]::UTF8
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($line -eq $null) { break }
    try {
        $f = $line.Split(' ')
        if ($f[0] -ne '-') { $s.SelectVoice($utf8.GetString([Convert]::FromBase64String($f[0]))) }
        $s.Rate = [int]$f[1]
        $out = $utf8.GetString([Convert]::FromBase64String($f[2]))
        $text = $utf8.GetString([Convert]::FromBase64String($f[3]))
        $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(RATE,
            [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
            [System.Speech.AudioFormat.AudioChannel]::Mono)
        $s.SetOutputToWaveFile($out, $fmt)
        $s.Speak($text)
        $s.SetOutputToNull()
        [Console]::Out.WriteLine('OK')
    } catch {
        $s.SetOutputToNull()
        [Console]::Out.WriteLine('ERR ' + ($_.Exception.Message -replace "`r?`n", ' '))
    }
    [Console]::Out.Flush()
}
""".replace("RATE", str(TTS_RATE))


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


class SapiTTS:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.voices: list[str] = []
        self.error = ""

    def _start(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        enc = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
        self._proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", enc],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = self._proc.stdout.readline().strip()
        if not line.startswith("READY"):
            self.close()
            raise RuntimeError(f"Windows speech didn't start: {line or 'no answer'}")
        self.voices = [v for v in line[5:].strip().split("|") if v]
        log.info("Windows speech ready: %s", ", ".join(self.voices) or "no voices")

    def warm_up(self) -> list[str]:
        with self._lock:
            try:
                self._start()
                self.error = ""
            except (OSError, RuntimeError) as e:
                self.error = str(e)
                log.warning("text-to-speech unavailable: %s", e)
            return self.voices

    def synth(self, text: str, voice: str = "", rate: int = 0) -> tuple[np.ndarray, int]:
        """Speak `text` into memory: (float32 mono samples, sample rate)."""
        text = " ".join(text.split())
        if not text:
            return np.zeros(0, np.float32), TTS_RATE
        fd, path = tempfile.mkstemp(prefix="sb-tts-", suffix=".wav")
        os.close(fd)
        try:
            with self._lock:
                self._start()
                req = " ".join([_b64(voice) if voice else "-", str(int(max(-10, min(10, rate)))),
                                _b64(path), _b64(text)])
                self._proc.stdin.write(req + "\n")
                self._proc.stdin.flush()
                ans = self._proc.stdout.readline().strip()
            if ans != "OK":
                if not ans:
                    self.close()
                raise RuntimeError(ans[4:] if ans.startswith("ERR") else "speech engine stopped")
            data, sr = sf.read(path, dtype="float32", always_2d=False)
            return np.ascontiguousarray(data, np.float32), int(sr)
        finally:
            Path(path).unlink(missing_ok=True)

    def close(self):
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.stdin.close()
                p.wait(timeout=2)
            except Exception:  # noqa: BLE001
                p.kill()


class Speaker:
    """Say lines one at a time, in order, on a background thread.

    `play(stereo_float32, rate)` is called for each synthesized line; the speaker
    then waits for the line's length before starting the next. `on_error(msg)`
    reports a line that couldn't be spoken."""

    def __init__(self, tts: SapiTTS, play: Callable[[np.ndarray, int], None],
                 on_error: Callable[[str], None] = lambda m: None):
        self.tts, self.play, self.on_error = tts, play, on_error
        self.voice = ""
        self.rate = 0
        self._q: deque[str] = deque(maxlen=20)
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._busy_until = 0.0
        threading.Thread(target=self._run, name="tts-speaker", daemon=True).start()

    def say(self, text: str):
        if text.strip():
            self._q.append(text)
            self._wake.set()

    def stop(self):
        """Drop anything queued and cut the current line's wait short."""
        self._q.clear()
        self._cancel.set()
        self._busy_until = 0.0

    @property
    def busy(self) -> bool:
        return bool(self._q) or time.monotonic() < self._busy_until

    def _run(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            while self._q:
                text = self._q.popleft()
                self._cancel.clear()
                try:
                    mono, sr = self.tts.synth(text, self.voice, self.rate)
                except Exception as e:  # noqa: BLE001
                    log.warning("text-to-speech failed: %s", e)
                    self.on_error(str(e))
                    continue
                if not len(mono) or self._cancel.is_set():
                    continue
                self.play(np.repeat(mono[:, None], 2, axis=1), sr)
                dur = len(mono) / sr
                self._busy_until = time.monotonic() + dur
                self._cancel.wait(dur + 0.08)
