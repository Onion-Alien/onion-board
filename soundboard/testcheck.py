"""Output self-test: is my voice / are my sounds really in what others receive?

Given a recording of the real output (e.g. captured from CABLE Output) and the
raw mic recorded at the same time, find the mic inside the output by
cross-correlation. A sharp correlation peak means the voice made it through;
subtracting that copy leaves the sounds, so the two levels can be compared.
"""
from __future__ import annotations

import numpy as np
import soxr


def _db(x: float) -> float:
    return 20 * np.log10(max(x, 1e-9))


def _active_level(x: np.ndarray, rate: int) -> float:
    """Loudness while something is actually happening (90th pct of 50ms blocks)."""
    n = max(rate // 20, 1)
    k = len(x) // n
    if k == 0:
        return _db(float(np.sqrt((x ** 2).mean()))) if len(x) else -180.0
    blocks = np.sqrt((x[: k * n].reshape(k, n) ** 2).mean(axis=1))
    return _db(float(np.percentile(blocks, 90)))


def analyze(out: np.ndarray, out_rate: int, mic: np.ndarray | None, mic_rate: int,
            sound_vol: float) -> dict:
    o = (out.mean(axis=1) if out.ndim == 2 else out).astype(np.float64)
    res = {"talked": False, "voice_in": False, "sounds_in": False,
           "voice_db": None, "sounds_db": None, "advice": ""}

    if mic is None or len(mic) < mic_rate // 2:
        res["sounds_db"] = _active_level(o, out_rate)
        res["sounds_in"] = res["sounds_db"] > -45
        return res

    m = soxr.resample(mic.astype(np.float32), mic_rate, out_rate).astype(np.float64)
    k = min(len(o), len(m))
    o, m = o[:k], m[:k]
    res["talked"] = _active_level(m, out_rate) > -48

    # where (0..500 ms later) does the mic show up in the output?
    n = 1 << int(np.ceil(np.log2(2 * k)))
    xc = np.fft.irfft(np.fft.rfft(o, n) * np.conj(np.fft.rfft(m, n)), n)
    lags = xc[: int(out_rate * 0.5)]
    i = int(np.abs(lags).argmax())
    ratio = abs(lags[i]) / (np.median(np.abs(lags)) + 1e-12)
    res["voice_in"] = res["talked"] and ratio > 12

    if res["voice_in"]:
        g = lags[i] / (m ** 2).sum()
        voice = np.zeros_like(o)
        voice[i:] = g * m[: k - i]
        rest = o - voice
        res["voice_db"] = _active_level(voice, out_rate)
    else:
        rest = o
    res["sounds_db"] = _active_level(rest, out_rate)
    # if the voice wasn't found, "rest" still contains it, so only trust it as sound
    # when it's clearly louder than the mic itself
    res["sounds_in"] = res["sounds_db"] > -45 and (
        res["voice_in"] or not res["talked"]
        or res["sounds_db"] > _active_level(m, out_rate) + 6)

    if res["voice_in"] and res["sounds_in"]:
        diff = res["sounds_db"] - res["voice_db"]
        res["diff"] = diff
        if diff > 6:
            pct = int(round(sound_vol * 100 * 10 ** (-(diff - 2) / 20) / 5) * 5)
            res["advice"] = (f"Sounds are {diff:.0f} dB louder than your voice — they'll drown "
                             f"you out. Try the Sounds tab's volume around {max(pct, 5)}%.")
        elif diff < -12:
            res["advice"] = ("Sounds are much quieter than your voice — turn the Sounds tab's "
                             "volume up.")
    return res


def summary_html(r: dict, cable: str | None, mic_sent: bool = True) -> str:
    """`mic_sent` False = sounds-only mode: the voice isn't expected in the output."""
    ok, bad, warn = "#13ce66", "#ff4d4f", "#ffb020"
    lines = []
    if not mic_sent:
        lines.append((ok, "— Sounds only: your mic isn't sent (untick/tick “send” next to "
                          "My mic to change that)"))
    elif not r["talked"]:
        lines.append((warn, "⚠ Didn't hear you talk — talk during the test to check your mic"))
    elif r["voice_in"]:
        lines.append((ok, "✓ Your VOICE is in the output"))
    else:
        lines.append((bad, "✗ Your voice is NOT reaching the output — is “send” ticked "
                           "next to My mic?"))
    if r["sounds_in"]:
        lines.append((ok, "✓ SOUNDS are in the output"))
    else:
        lines.append((warn, "— No soundboard sound was playing during the test"))
    if r["advice"]:
        lines.append((warn, "⚠ " + r["advice"]))
    src = (f"Checked the real {cable} — exactly what Discord / the game receives."
           if cable else "Checked the app's output mix.")
    body = "<br>".join(f"<span style='color:{c}'>{t}</span>" for c, t in lines)
    return f"{body}<br><span style='color:#8a90a6'>{src}</span>"
