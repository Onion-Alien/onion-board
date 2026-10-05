"""Output self-test: is my voice / are my sounds really in what others receive?

Given a recording of the real output (e.g. captured from CABLE Output) and the
mic recorded at the same time, find the mic inside the output by
cross-correlation. A sharp correlation peak means the voice made it through;
subtracting that copy leaves the sounds, so the two levels can be compared.
With the voice changer on, the output holds the changed voice, so the mic as
sent (after the changer) is what's looked for; the raw mic still says whether
you talked.
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
    """`mic` is the raw mic (n,), or (n, 2): the raw mic and the mic as sent (what
    Engine.take_mic_recording returns)."""
    o = (out.mean(axis=1) if out.ndim == 2 else out).astype(np.float64)
    res = {"talked": False, "voice_in": False, "sounds_in": False, "replaced": False,
           "voice_db": None, "sounds_db": None, "advice": ""}

    if mic is None or len(mic) < mic_rate // 2:
        res["sounds_db"] = _active_level(o, out_rate)
        res["sounds_in"] = res["sounds_db"] > -45
        return res

    raw = mic[:, 0] if mic.ndim == 2 else mic
    sent = mic[:, 1] if mic.ndim == 2 else mic

    def at_out_rate(x):
        return soxr.resample(np.ascontiguousarray(x, dtype=np.float32), mic_rate,
                             out_rate).astype(np.float64)
    m = at_out_rate(sent)
    heard = m if sent is raw else at_out_rate(raw)
    k = min(len(o), len(m), len(heard))
    o, m, heard = o[:k], m[:k], heard[:k]
    res["talked"] = _active_level(heard, out_rate) > -48
    # you talked, but nothing of it is sent: the computer voice mutes the real mic
    res["replaced"] = res["talked"] and not np.any(m)

    # where (0..500 ms later) does the mic show up in the output?
    n = 1 << int(np.ceil(np.log2(2 * k)))
    cross = np.fft.rfft(o, n) * np.conj(np.fft.rfft(m, n))
    xc = np.fft.irfft(cross, n)
    lags = xc[: int(out_rate * 0.5)]
    i = int(np.abs(lags).argmax())
    ratio = abs(lags[i]) / (np.median(np.abs(lags)) + 1e-12)
    # the same, whitened (GCC-PHAT): a voice changer's buzz (robot) or pitch shift is
    # so periodic that the plain correlation has a peak every period and no clear
    # winner; whitened, the real delay is one sharp spike (no match stays under ~8)
    mag = np.abs(cross)
    ph = np.fft.irfft(cross / (mag + 1e-9 * mag.max() + 1e-30), n)[: len(lags)]
    j = int(np.abs(ph).argmax())
    pratio = abs(ph[j]) / (np.median(np.abs(ph)) + 1e-12)
    if pratio > 25:
        i = j
    res["voice_in"] = res["talked"] and (ratio > 12 or pratio > 25)

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
                             "you out. Try the sounds volume (the speaker slider in the player "
                             f"bar) around {max(pct, 5)}%.")
        elif diff < -12:
            res["advice"] = ("Sounds are much quieter than your voice — turn the sounds volume "
                             "(the speaker slider in the player bar) up.")
    return res


def summary_html(r: dict, cable: str | None, mic_sent: bool = True) -> str:
    """`mic_sent` False = sounds-only mode: the voice isn't expected in the output."""
    from soundboard import theme   # the current theme's readable green / red / amber
    ok, bad, warn = theme.status("ok"), theme.status("error"), theme.status("warn")
    lines = []
    if not mic_sent:
        lines.append((ok, "— Sounds only: your mic isn't sent (tick “Others hear it” under "
                          "MY MIC to change that)"))
    elif not r["talked"]:
        lines.append((warn, "⚠ Didn't hear you talk — talk during the test to check your mic"))
    elif r.get("replaced"):
        lines.append((ok, "— Computer voice is on: your real voice is muted, so others hear "
                          "only the spoken voice"))
    elif r["voice_in"]:
        lines.append((ok, "✓ Your VOICE is in the output"))
    else:
        lines.append((bad, "✗ Your voice is NOT reaching the output — is “Others hear it” "
                           "ticked under MY MIC?"))
    if r["sounds_in"]:
        lines.append((ok, "✓ SOUNDS are in the output"))
    else:
        lines.append((warn, "— No soundboard sound was playing during the test"))
    if r["advice"]:
        lines.append((warn, "⚠ " + r["advice"]))
    src = (f"Checked the real {cable} — exactly what Discord / the game receives."
           if cable else "Checked the app's output mix.")
    body = "<br>".join(f"<span style='color:{c}'>{t}</span>" for c, t in lines)
    muted = theme.T["muted"]   # a fixed grey was unreadable on the light themes
    return f"{body}<br><span style='color:{muted}'>{src}</span>"
