"""Real-time voice conversion: 16 kHz mic in, 24 kHz character voice out.

The model is Beatrice 2's design (trained with the MIT beatrice-trainer), exported to
ONNX as a streaming graph (tools/stream_model.py): every causal convolution keeps its
last frames as state, so each call does only 20 ms of new work. The parts that are
FFTs run here in numpy:

    mic 16 kHz ─┬─ PitchFeatures (FFT, autocorrelation) ─┐
                └─ raw window ───────────────────────────┴─ stream.onnx ─┐
       ir amplitude/phase, aperiodicity, post filter, f0 per 10 ms frame ┘
                                    ─ Synth (pulse train + shaped noise + filter) ─ 24 kHz

Frames are 10 ms: 160 samples in, 240 out. Converter.process() takes 20 ms.
Only numpy and onnxruntime: this runs in the add-on's own environment.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

HOP_IN, HOP_OUT = 160, 240
IN_RATE, OUT_RATE = 16000, 24000
T = 2                        # frames per call (20 ms)
W_ATTN = 400                 # self-attention history in frames (the model's 4 s training clips)
WIN, CORR_WIN, CUT = 560, 304, 64
_COS_WIN = np.sin(np.pi * (np.arange(WIN) + 0.5) / WIN)


class PitchFeatures:
    """The pitch estimator's input features, frame by frame (frame k needs input
    samples [160k - 200, 160k + 360))."""

    def __init__(self):
        self.prev_spec = None

    def __call__(self, frames: np.ndarray) -> np.ndarray:
        """frames [n, 560] -> [n, 449]: 192 instantaneous-frequency, 256 correlation, 1 energy."""
        y = frames.astype(np.float64)
        spec = np.fft.rfft(y, n=WIN, axis=1)[:, :CUT]
        logp = np.log10(np.abs(spec) + 1e-5)
        prev = np.concatenate([self.prev_spec[None] if self.prev_spec is not None
                               else np.zeros((1, CUT), complex), spec[:-1]], 0)
        d = spec * np.conj(prev)
        d = d / (np.abs(d) + 1e-5)
        if self.prev_spec is None:
            d[0] = 0
        self.prev_spec = spec[-1].copy()
        fl = y[:, ::-1]
        spec_ab = np.fft.rfft(fl, n=WIN, axis=1) * np.fft.rfft(y[:, -CORR_WIN:], n=WIN, axis=1)
        corr = np.fft.irfft(spec_ab, n=WIN, axis=1)[:, CORR_WIN:]
        cs = np.cumsum(fl * fl, axis=1)
        diff = cs[:, CORR_WIN - 1:CORR_WIN] + (cs[:, CORR_WIN:] - cs[:, :-CORR_WIN]) - 2.0 * corr
        cd = np.sqrt(np.maximum(diff, 0.0) * (2.0 / CORR_WIN))
        energy = np.log10(np.maximum(((y * _COS_WIN) ** 2).sum(1, keepdims=True), 1e-3)) * 0.5
        return np.concatenate([logp, d.real, d.imag, cd, energy], 1).astype(np.float32)


class Synth:
    """The vocoder's signal part, streaming: a pulse train (one shaped impulse response
    per pitch period), plus noise shaped by the aperiodicity, both through the
    per-frame post filter. feed() returns T*240 finished samples."""

    def __init__(self, ir_window: np.ndarray, rng: np.random.Generator):
        self.rng = rng
        self.win = ir_window.astype(np.float64)
        self.phase = None                     # pulse-train phase at the last sample fed
        self.per = np.zeros(512)              # pulse carry into the next chunk
        self.noise_carry = np.zeros(HOP_OUT)
        self.exc_tail = None
        self.fold = np.zeros(768)             # post-filter carry
        self.prev = None                      # the last frame's (amp, phase, post)
        self.hann = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(2 * HOP_OUT) / (2 * HOP_OUT))
        self.k = np.arange(257)

    def feed(self, amp, ph, aper, post, hz) -> np.ndarray:
        """amp, ph [n, 257]; aper [n, 240]; post [n, 512]; hz [n] (frame-major)."""
        n_fr = amp.shape[0]
        n = n_fr * HOP_OUT
        f = np.repeat(np.asarray(hz, np.float64) / OUT_RATE, HOP_OUT)
        if self.phase is None:
            f[0] = self.rng.random()
            seq, off = np.cumsum(f) % 1.0, 0
        else:
            seq, off = np.concatenate([[self.phase], (self.phase + np.cumsum(f)) % 1.0]), -1
        self.phase = float(seq[-1])
        marks = np.nonzero(seq[:-1] > seq[1:])[0]            # the phase wrapped: a pulse
        per = np.zeros(n + 512)
        per[:512] = self.per
        late = None
        if len(marks):
            num = 1.0 - seq[marks]
            frac = num / (num + seq[marks + 1])
            idx = marks + off
            fr = np.maximum(idx // HOP_OUT, 0)
            A, P = amp[fr].astype(np.float64), ph[fr].astype(np.float64)
            if idx[0] < 0 and self.prev is not None:          # on the previous chunk's last sample
                A[0], P[0] = self.prev[0], self.prev[1]
            dph = self.k[None, :] * (-2 * np.pi / 512) * frac[:, None]
            ir = np.fft.irfft(A * np.exp(1j * (P + dph)), n=512, axis=1) * self.win
            for i, s in enumerate(idx):
                if s < 0:
                    late = ir[i, 0]
                    per[:511] += ir[i, 1:]
                else:
                    per[s:s + 512] += ir[i]
        sig = per[:n]
        self.per = per[n:]
        if self.exc_tail is None:
            self.exc_tail = self.rng.random(HOP_OUT) - 0.5
        exc = np.concatenate([self.exc_tail, self.rng.random(n) - 0.5])
        self.exc_tail = exc[-HOP_OUT:]
        frames = np.lib.stride_tricks.sliding_window_view(exc, 2 * HOP_OUT)[::HOP_OUT][:n_fr]
        spec = np.fft.rfft(frames, axis=1)
        spec[:, 0] = 0
        spec[:, 1:] *= aper
        nz = np.fft.irfft(spec, n=2 * HOP_OUT, axis=1) * self.hann
        noise = np.zeros(n + HOP_OUT)
        noise[:HOP_OUT] = self.noise_carry
        for j in range(n_fr):
            noise[j * HOP_OUT:(j + 2) * HOP_OUT] += nz[j]
        self.noise_carry = noise[n:]
        sig = sig + noise[:n]
        y = np.fft.irfft(np.fft.rfft(sig.reshape(n_fr, HOP_OUT), n=768, axis=1)
                         * np.fft.rfft(post, n=768, axis=1), n=768, axis=1)
        fold = np.zeros(n + 768)
        fold[:768] = self.fold
        if late is not None and self.prev is not None:
            fold[:511] += late * self.prev[2][1:]   # its very first sample is already out
        for j in range(n_fr):
            fold[j * HOP_OUT:j * HOP_OUT + 768] += y[j]
        self.fold = fold[n:]
        self.prev = (amp[-1].astype(np.float64), ph[-1].astype(np.float64), post[-1])
        return fold[:n].astype(np.float32)


class PitchTracker:
    """Your typical pitch (median of the voiced frames of the last ~6 s of talking),
    so a character voice can sit at its own pitch whoever is talking."""

    def __init__(self, keep: int = 600):
        self.buf = np.zeros(keep)
        self.n = 0

    def add(self, hz: np.ndarray, voiced: np.ndarray):
        for v in np.log2(np.asarray(hz, np.float64)[voiced]):
            self.buf[self.n % len(self.buf)] = v
            self.n += 1

    def median_hz(self) -> float | None:
        if self.n < 40:                          # under ~0.4 s of voiced speech: no guess
            return None
        return float(2.0 ** np.median(self.buf[:min(self.n, len(self.buf))]))


def _session(path: Path, threads: int):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # no busy-waiting: an idle helper must use no CPU while you're quiet or gaming
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    so.log_severity_level = 3
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


class Converter:
    """One voice conversion stream. `voice` (from voices.json):
        {"mix": [[speaker, weight], ...], "formant": semitones (-2..2),
         "pitch_hz": the voice's own pitch (auto pitch aims for it), "pitch": extra semitones}
    """

    def __init__(self, model_dir: Path, voice: dict, threads: int = 1, seed: int | None = None):
        self.dir = Path(model_dir)
        self.sess = _session(self.dir / "stream.onnx", threads)
        self.spk_sess = _session(self.dir / "speaker.onnx", 1)
        tab = np.load(self.dir / "voices.npz")
        self.tab = {k: tab[k] for k in tab.files}
        self.ids = [int(s) for s in self.tab["ids"]]          # model speaker -> row
        ins = self.sess.get_inputs()
        self.state_names = [i.name for i in ins[7:]]
        self.zero = {i.name: np.zeros(i.shape, np.float32) for i in ins[7:]}
        self.out_names = [o.name for o in self.sess.get_outputs()]
        self.rng = np.random.default_rng(seed)
        self.auto_pitch = True
        self.user_hz: float | None = None       # fixed "your pitch" (tests, the self-test)
        self.set_voice(voice)
        self.reset()

    # ---------------------------------------------------------------- voice
    def set_voice(self, voice: dict):
        mix = [(int(s), float(w)) for s, w in voice["mix"] if float(w) > 0]
        if not mix:
            raise ValueError("a voice needs at least one speaker")
        total = sum(w for _s, w in mix)
        rows = [(self.ids.index(s), w / total) for s, w in mix]
        f_idx = min(max(int(round((float(voice.get("formant", 0.0)) + 2.0) * 2.0)), 0), 8)
        emb = sum(w * self.tab["embed"][r].astype(np.float32) for r, w in rows)
        kv = sum(w * self.tab["kv"][r].astype(np.float32) for r, w in rows)
        self.spk = (emb + self.tab["formant"][f_idx].astype(np.float32)).astype(np.float32)
        self.spk_kv = self.spk_sess.run(None, {"kv": kv.reshape(384, 128).astype(np.float32)})[0]
        # the phone codes come from the main speaker (an average of codebooks means nothing)
        self.codebook = self.tab["codebooks"][max(rows, key=lambda rw: rw[1])[0]].astype(np.float32)
        self.voice_hz = float(voice.get("pitch_hz", 0.0)) or None
        self.extra = float(voice.get("pitch", 0.0))
        self.shift_st = self.extra                 # semitones in use right now

    def target_shift(self) -> float:
        """Semitones to move your pitch by: to the voice's own pitch (auto), plus extra."""
        st = self.extra
        mine = self.user_hz or self.tracker.median_hz()
        if self.auto_pitch and self.voice_hz and mine:
            st += 12.0 * math.log2(self.voice_hz / mine)
        return max(-24.0, min(24.0, st))

    def settle_pitch(self, force: bool = False):
        """Move to the target pitch: called between sentences (a jump mid-word sounds
        wrong); `force` for the first guess."""
        t = self.target_shift()
        if force or abs(t - self.shift_st) >= 0.75:
            self.shift_st = round(t * 2) / 2

    # ---------------------------------------------------------------- stream
    def reset(self):
        self.states = {k: v.copy() for k, v in self.zero.items()}
        self.cache_idx = np.full(W_ATTN, -10 ** 9)
        self.ring_pos = 0
        self.p0 = 0
        self.buf = np.zeros(560 + HOP_IN * T, np.float32)
        self.pf = PitchFeatures()
        self.synth = Synth(self.tab["ir_window"], self.rng)
        self.tracker = PitchTracker()
        self.started = False
        self._guessed = False

    def process(self, x16: np.ndarray) -> np.ndarray:
        """320 new samples (16 kHz, float) -> 480 samples (24 kHz)."""
        x16 = np.asarray(x16, np.float32)
        if len(x16) != HOP_IN * T:
            raise ValueError(f"process() takes {HOP_IN * T} samples")
        self.buf = np.concatenate([self.buf[HOP_IN * T:], x16])
        n = len(self.buf)
        # buf[-1] ends the newest phone frame's window: frames p0..p0+T-1 need samples
        # [160 p0 - 40, 160 (p0+T-1) + 200); pitch frames p0-1+j need [160k-200, 160k+360)
        wav = self.buf[n - (240 + HOP_IN * (T - 1)):]
        fr = np.stack([self.buf[n + HOP_IN * (j - T) - 400:n + HOP_IN * (j - T) + 160]
                       for j in range(T)])
        t = np.arange(self.p0, self.p0 + T)
        keys = np.concatenate([self.cache_idx, t])
        ok = (keys[None] >= 0) & (keys[None] % 4 == t[:, None] % 4) & (keys[None] <= t[:, None])
        feed = {"wav": wav[None, None], "pfeat": self.pf(fr),
                "mask": np.where(ok, 0.0, -1e9).astype(np.float32),
                "spk": self.spk, "spk_kv": self.spk_kv, "codebook": self.codebook,
                "shift": np.array(self.shift_st * 8.0, np.float32)}
        feed.update(self.states)
        out = dict(zip(self.out_names, self.sess.run(None, feed)))
        for name in self.state_names:
            val = out["n" + name]
            if name in ("s_attn_k", "s_attn_v"):        # only the new frames: into the ring
                self.states[name][:, self.ring_pos:self.ring_pos + T] = val
            else:
                self.states[name] = val
        self.cache_idx[self.ring_pos:self.ring_pos + T] = t
        self.ring_pos = (self.ring_pos + T) % W_ATTN
        self.p0 += T
        # your own pitch: the output's f0 less the shift in use
        voiced = out["uv"] < 0.5
        if voiced.any():
            self.tracker.add(out["hz"] * 2.0 ** (-self.shift_st / 12.0), voiced)
            if not self._guessed and self.tracker.median_hz():
                self._guessed = True
                self.settle_pitch(force=True)
        if not self.started:          # the first call's vocoder frames come before the start
            self.started = True
            return np.zeros(HOP_OUT * T, np.float32)
        return self.synth.feed(out["ir_amp"], out["ir_phase"], out["aper"], out["post"], out["hz"])


def self_test(model_dir: Path, voice: dict, seconds: float = 2.0) -> float:
    """Real-time factor on this PC (compute time / audio time, median chunk) for a
    synthetic voice."""
    import time
    c = Converter(model_dir, voice, seed=0)
    c.user_hz = 120.0
    t = np.arange(int(IN_RATE * seconds)) / IN_RATE
    f0 = 120 + 20 * np.sin(2 * np.pi * 0.5 * t)
    x = (0.2 * np.sign(np.sin(2 * np.pi * np.cumsum(f0) / IN_RATE))).astype(np.float32)
    step = HOP_IN * T
    for i in range(0, step * 10, step):        # warm up (first calls allocate)
        c.process(x[i:i + step])
    times = []
    for i in range(step * 10, len(x) - step, step):
        t0 = time.perf_counter()
        c.process(x[i:i + step])
        times.append(time.perf_counter() - t0)
    # the median chunk: another program's burst of CPU (a build, a game loading) mustn't
    # make a fast PC look too slow
    return float(np.median(times)) / (step / IN_RATE)
