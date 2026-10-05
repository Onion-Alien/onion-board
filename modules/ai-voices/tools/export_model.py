"""Export the AI voices model for the add-on (dev tool: needs torch + a trainer checkout).

    set BEATRICE_TRAINER=path\\to\\beatrice-trainer
    python export_model.py [--checkpoint my_voices.pt.gz] [--out model]

Writes into --out:
    stream.onnx   the streaming converter (fp32, ~38 MB)
    speaker.onnx  speaker embedding -> the vocoder's attention keys/values
    voices.npz    only the speakers voices.json uses, plus the formant table
and model.zip of all three, printing its size and SHA-256 for voices.json's "model".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import torch

import stream_model
from beatrice import load
from stream_model import SpeakerNet, StreamNet, W_ATTN

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=Path)
    ap.add_argument("--out", type=Path, default=HERE / "model")
    ap.add_argument("--voices", type=Path, default=HERE.parent / "voices.json")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    net, pe, pi = load(a.checkpoint)
    net.merge_weights()
    pe.merge_weights()
    pi.merge_weights()
    stream_model.MERGED = True
    sn, spkn = StreamNet(net).eval(), SpeakerNet(net).eval()
    T = 2
    states = sn.state_names()
    with torch.inference_mode():
        kv = spkn(net.key_value_speaker_embedding.weight[0].view(384, 128))
    args = (torch.zeros(1, 1, 240 + 160 * (T - 1)), torch.zeros(T, 449),
            torch.zeros(T, W_ATTN + T), torch.zeros(256), kv, net.vq.codebooks[0].float(),
            torch.tensor(0.0), *sn.zero_states())
    with torch.no_grad():
        torch.onnx.export(sn, args, str(a.out / "stream.onnx"),
                          input_names=["wav", "pfeat", "mask", "spk", "spk_kv", "codebook",
                                       "shift"] + states,
                          output_names=["ir_amp", "ir_phase", "aper", "post", "hz", "uv"]
                          + ["n" + s for s in states],
                          opset_version=20, dynamic_axes={"codebook": {0: "K"}}, dynamo=False)
        torch.onnx.export(spkn, (torch.zeros(384, 128),), str(a.out / "speaker.onnx"),
                          input_names=["kv"], output_names=["spk_kv"], opset_version=17,
                          dynamo=False)
    voices = json.loads(a.voices.read_text(encoding="utf-8"))["voices"]
    ids = sorted({int(s) for v in voices for s, _w in v["mix"]})
    idx = torch.tensor(ids)
    np.savez_compressed(
        a.out / "voices.npz", ids=np.array(ids),
        embed=net.embed_speaker.weight[idx].detach().numpy().astype(np.float16),
        formant=net.embed_formant_shift.weight.detach().numpy().astype(np.float16),
        kv=net.key_value_speaker_embedding.weight[idx].detach().numpy().astype(np.float16),
        codebooks=net.vq.codebooks[idx].numpy().astype(np.float16),
        ir_window=net.vocoder.ir_window.detach().numpy().astype(np.float32))
    z = a.out / "model.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("stream.onnx", "speaker.onnx", "voices.npz"):
            zf.write(a.out / name, name)
    data = z.read_bytes()
    print(json.dumps({"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}))


if __name__ == "__main__":
    main()
