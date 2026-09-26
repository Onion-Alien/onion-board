"""Example effects module: an 8-bit bitcrusher.

Copy this folder to start your own. Onion Board calls `register(api)` once at
startup. Effects subclass `api.Effect`, declare their sliders as `api.Param`s and
implement `run(x, rate)`: x is a 1-D float32 block of mic audio (about 10 ms);
return a block of the same length. It runs on the audio thread, so keep it to
numpy maths: no file or network access, no sleeping, no locks. Only import what
Onion Board itself ships (numpy, scipy, the standard library).
"""
import numpy as np


def register(api):
    class Bitcrusher(api.Effect):
        type = "retro.bitcrush"          # unique id: prefix it with your module's name
        name = "Bitcrusher"
        description = "Low bit depth and sample rate: an old game console."
        params = (api.Param("bits", "Bits", 2, 12, 6, "", 1),
                  api.Param("downsample", "Crunch", 1, 32, 8, "x", 1),
                  api.Param("mix", "Mix", 0, 1, 1))

        def __init__(self, rate, values=None):
            super().__init__(rate, values)
            self.held = 0.0      # last held sample, carried across blocks
            self.count = 0       # position inside the current hold

        def run(self, x, rate):
            k = int(self.p["downsample"])
            # sample-and-hold every k samples, continuing the hold from the last block
            idx = (np.arange(len(x)) + self.count) // k
            first = (np.arange(len(x)) + self.count) % k == 0
            starts = np.flatnonzero(first)
            held = np.empty_like(x)
            if len(starts):
                held[:starts[0]] = self.held
                vals = x[starts]
                held[starts[0]:] = vals[idx[starts[0]:] - idx[starts[0]]]
            else:
                held[:] = self.held
            self.held = float(held[-1])
            self.count = (self.count + len(x)) % k
            steps = 2 ** (int(self.p["bits"]) - 1)
            wet = np.round(held * steps) / steps
            mix = np.float32(self.p["mix"])
            return (x * (1 - mix) + wet * mix).astype(np.float32)

    api.register_effect(Bitcrusher)
