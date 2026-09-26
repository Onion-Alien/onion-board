"""Text-to-speech with the voices built into Windows (no download, works in the exe).

Two kinds of Windows voice: the classic desktop ones (System.Speech: David, Zira,
Hazel…) and the newer ones Windows adds with a language's speech pack (WinRT
Windows.Media.SpeechSynthesis: Katja for German, Helena for Spanish…). Both are
.NET / WinRT APIs, so a single hidden PowerShell process is kept running
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
$list = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } |
    ForEach-Object { $_.VoiceInfo.Name + "`t" + $_.VoiceInfo.Culture.Name })
$desk = @{}
foreach ($v in $s.GetInstalledVoices()) { $desk[$v.VoiceInfo.Name] = 1 }
# the newer voices, where Windows has them; one already listed as "<name> Desktop" is skipped
$w = $null; $wv = @{}; $asTask = $null
try {
    $ns = 'Windows.Media.SpeechSynthesis'
    $null = [Type]::GetType("$ns.SpeechSynthesizer, $ns, ContentType=WindowsRuntime", $true)
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0].MakeGenericMethod(
        [Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $w = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
    foreach ($v in [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices) {
        $n = $v.DisplayName
        if ($desk.ContainsKey($n) -or $desk.ContainsKey($n + ' Desktop')) { continue }
        $wv[$n] = $v
        $list += $n + "`t" + $v.Language
    }
} catch { $w = $null }
[Console]::Out.WriteLine('READY ' + ($list -join '|'))
[Console]::Out.Flush()
$utf8 = [Text.Encoding]::UTF8
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($line -eq $null) { break }
    try {
        $f = $line.Split(' ')
        $name = ''
        if ($f[0] -ne '-') { $name = $utf8.GetString([Convert]::FromBase64String($f[0])) }
        $out = $utf8.GetString([Convert]::FromBase64String($f[2]))
        $text = $utf8.GetString([Convert]::FromBase64String($f[3]))
        if ($name -and $wv.ContainsKey($name)) {
            $w.Voice = $wv[$name]
            try { $w.Options.SpeakingRate = [Math]::Pow(2, [int]$f[1] / 10.0) } catch {}
            $t = $asTask.Invoke($null, @($w.SynthesizeTextToStreamAsync($text)))
            $t.Wait()
            $st = $t.Result
            $in = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($st)
            $fs = [System.IO.File]::Create($out)
            try { $in.CopyTo($fs) } finally { $fs.Close(); $in.Close(); $st.Dispose() }
        } else {
            if ($name) { $s.SelectVoice($name) }
            $s.Rate = [int]$f[1]
            $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(RATE,
                [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
                [System.Speech.AudioFormat.AudioChannel]::Mono)
            $s.SetOutputToWaveFile($out, $fmt)
            $s.Speak($text)
            $s.SetOutputToNull()
        }
        [Console]::Out.WriteLine('OK')
    } catch {
        $s.SetOutputToNull()
        [Console]::Out.WriteLine('ERR ' + ($_.Exception.Message -replace "`r?`n", ' '))
    }
    [Console]::Out.Flush()
}
""".replace("RATE", str(TTS_RATE))


def parse_voices(listing: str) -> tuple[list[str], dict[str, str]]:
    """The READY line's "name<TAB>language|…" into (names, {name: language})."""
    names, langs = [], {}
    for entry in listing.strip().split("|"):
        name, _, lang = entry.partition("	")
        name = name.strip()
        if name and name not in langs:
            names.append(name)
            langs[name] = lang.strip()
    return names, langs


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


class SapiTTS:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.voices: list[str] = []
        self.voice_langs: dict[str, str] = {}   # voice name -> its language, like "de-DE"
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
        self.voices, self.voice_langs = parse_voices(line[5:])
        log.info("Windows speech ready: %s", ", ".join(self.voices) or "no voices")

    def voice_for(self, lang: str, prefer: str = "") -> str:
        """A voice that speaks `lang` ("de", "zh"…): `prefer` if it does, else the
        first one installed; "" when Windows has none."""
        def speaks(name: str) -> bool:
            return self.voice_langs.get(name, "").lower().split("-")[0] == lang.lower()
        if prefer and speaks(prefer):
            return prefer
        return next((v for v in self.voices if speaks(v)), "")

    def warm_up(self) -> list[str]:
        with self._lock:
            try:
                self._start()
                self.error = ""
            except (OSError, RuntimeError) as e:
                self.error = str(e)
                log.warning("text-to-speech unavailable: %s", e)
            return self.voices

    def refresh(self) -> list[str]:
        """Look for voices again (one was just installed in Windows settings)."""
        with self._lock:
            self.close()
        return self.warm_up()

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
        self._q: deque[tuple[str, str | None]] = deque(maxlen=20)
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._gen = 0           # bumped by stop(); a line from an older gen is dropped
        self._busy_until = 0.0
        threading.Thread(target=self._run, name="tts-speaker", daemon=True).start()

    def say(self, text: str, voice: str | None = None):
        """Queue a line; `voice` overrides `self.voice` for this line only."""
        if text.strip():
            self._q.append((text, voice))
            self._wake.set()

    def stop(self):
        """Drop anything queued and cut the current line's wait short."""
        self._gen += 1
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
            while True:
                gen = self._gen     # read before popping, so a stop() in between is seen
                try:
                    text, voice = self._q.popleft()
                except IndexError:
                    break
                self._cancel.clear()
                try:
                    mono, sr = self.tts.synth(text, self.voice if voice is None else voice,
                                              self.rate)
                except Exception as e:  # noqa: BLE001
                    log.warning("text-to-speech failed: %s", e)
                    self.on_error(str(e))
                    continue
                if not len(mono) or gen != self._gen:
                    continue
                self.play(np.repeat(mono[:, None], 2, axis=1), sr)
                dur = len(mono) / sr
                self._busy_until = time.monotonic() + dur
                self._cancel.wait(dur + 0.08)
