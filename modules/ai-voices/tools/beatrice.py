"""Load the model classes from a beatrice-trainer checkout (MIT licence,
https://huggingface.co/fierce-cats/beatrice-trainer) without its training-only
dependencies. Set BEATRICE_TRAINER to the checkout (default: ./beatrice-trainer).

Dev tool only: needs torch + torchaudio, which the add-on never ships."""
from __future__ import annotations

import gzip
import os
import sys
import types
from pathlib import Path

import torch

TRAINER = Path(os.environ.get("BEATRICE_TRAINER", "beatrice-trainer")).resolve()
_src_file = TRAINER / "beatrice_trainer" / "__main__.py"
if not _src_file.is_file():
    raise SystemExit(f"beatrice-trainer not found at {TRAINER} (set BEATRICE_TRAINER)")
_src = _src_file.read_text(encoding="utf-8")
_src = _src.replace('assert "soundfile" in torchaudio.list_audio_backends()', "pass")
sys.modules.setdefault("pyworld", types.ModuleType("pyworld"))    # training only
_tb = types.ModuleType("torch.utils.tensorboard")
_tb.SummaryWriter = object
sys.modules["torch.utils.tensorboard"] = _tb
bt = types.ModuleType("beatrice_trainer_main")
bt.__file__ = str(_src_file)
exec(compile(_src, bt.__file__, "exec"), bt.__dict__)


def load(checkpoint: Path | None = None):
    """(ConverterNetwork, PhoneExtractor, PitchEstimator) in eval mode. `checkpoint`
    is a trained (or the pretrained 200-speaker) .pt.gz."""
    pre = TRAINER / "assets" / "pretrained"
    pe = bt.PhoneExtractor()
    ck = torch.load(pre / "122_checkpoint_03000000.pt", map_location="cpu")
    pe.load_state_dict(ck["phone_extractor"])
    pi = bt.PitchEstimator()
    ck = torch.load(pre / "104_3_checkpoint_00300000.pt", map_location="cpu")
    pi.load_state_dict(ck["pitch_estimator"])
    ck_file = checkpoint or pre / "151_checkpoint_libritts_r_200_02750000.pt.gz"
    opener = gzip.open if str(ck_file).endswith(".gz") else open
    with opener(ck_file, "rb") as f:
        ck = torch.load(f, map_location="cpu", weights_only=False)
    n_speakers = ck["net_g"]["embed_speaker.weight"].shape[0]
    net = bt.ConverterNetwork(pe, pi, n_speakers, 448, 256)
    net.load_state_dict(ck["net_g"])
    pe.remove_weight_norm()
    for b in net.vocoder.prenet.convnext:
        b.mha.dropout = 0.0     # F.scaled_dot_product_attention drops out even in eval
    net.eval()
    pe.eval()
    pi.eval()
    return net, pe, pi
