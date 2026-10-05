"""Streaming (stateful) Beatrice 2 converter for ONNX export, time-major ([T, C]).

One call = T new 10 ms frames. Every causal conv keeps its last K-1 input frames as
state ([K-1, C]); the phone extractor's causal self-attention reads a ring buffer of
W past keys/values (kept by the caller, which also builds the 4-phase mask) and
returns only the new frames' keys/values.

The FFT parts (pitch features, the vocoder's overlap-add, noise, post filter) run
in numpy (dsp.py). Call merge_weights() on the modules first and set MERGED."""
from __future__ import annotations

import math
import torch
import torch.nn as nn
import torch.nn.functional as F

from beatrice import bt

W_ATTN = 400        # self-attention history, frames (4 s = the training clip length)
MERGED = False      # set after merge_weights(): scales and norms are in the weights


def _w(conv):
    if isinstance(conv, (bt.WSConv1d, bt.WSLinear)) and not MERGED:
        return conv.standardized_weight()
    return conv.weight


def sconv(conv: nn.Conv1d, x, state):
    """causal conv over [state; x] (time-major). Returns (y [T, Cout], new state)."""
    xx = torch.cat([state, x], 0)                    # [K-1+T, Cin]
    k = conv.kernel_size[0]
    T = x.size(0)
    w = _w(conv)                                     # [Cout, Cin/g, K]
    if conv.groups > 1:                              # depthwise
        wt = w[:, 0].transpose(0, 1)                 # [K, C]
        y = torch.stack([(xx[t:t + k] * wt).sum(0) for t in range(T)], 0)
    else:                                            # dense: windows @ flattened weight
        wf = w.permute(2, 1, 0).reshape(k * w.size(1), w.size(0))   # [K*Cin, Cout]
        win = torch.stack([xx[t:t + k].reshape(-1) for t in range(T)], 0)
        y = torch.matmul(win, wf)
    if conv.bias is not None:
        y = y + conv.bias
    return y, xx[T:]


def lin(layer, x):
    return F.linear(x, _w(layer), layer.bias)


def pconv(conv, x):
    """1x1 conv on [T, C]"""
    return F.linear(x, _w(conv)[:, :, 0], conv.bias)


def self_attn(block, x, kc, vc, mask):
    # x: [T, C]; kc, vc: [W, C] (ring, any order); mask: [T, W+T] additive
    mha: nn.MultiheadAttention = block.mha
    C = x.size(1)
    h = mha.num_heads
    d = C // h
    T, W = x.size(0), kc.size(0)
    qkv = F.linear(block.attn_norm(x), mha.in_proj_weight, mha.in_proj_bias)
    q, k, v = qkv.split(C, dim=1)
    qh = (q * (1.0 / math.sqrt(d))).view(T, h, d).transpose(0, 1)      # [h, T, d]
    kch = kc.view(W, h, d).permute(1, 2, 0)                              # [h, d, W]
    vch = vc.view(W, h, d).transpose(0, 1)                               # [h, W, d]
    kh = k.view(T, h, d).permute(1, 2, 0)
    vh = v.view(T, h, d).transpose(0, 1)
    att = (torch.cat([torch.matmul(qh, kch), torch.matmul(qh, kh)], 2) + mask).softmax(-1)
    o = torch.matmul(att[:, :, :W], vch) + torch.matmul(att[:, :, W:], vh)
    o = mha.out_proj(o.transpose(0, 1).reshape(T, C))
    return x + o, k, v


def cross_attn(block, x, k, v):
    # k, v: [h, L, d] precomputed for the speaker (SpeakerNet)
    ca: bt.CrossAttention = block.mha
    T = x.size(0)
    h, d = ca.num_heads, ca.head_qk_channels
    q = ca.q_projection(block.attn_norm(x)) * (1.0 / math.sqrt(d))
    qh = q.view(T, h, d).transpose(0, 1)
    att = torch.matmul(qh, k.transpose(1, 2)).softmax(-1)
    o = torch.matmul(att, v).transpose(0, 1).reshape(T, ca.vo_channels)
    return x + ca.out_projection(o)


def block_conv(block, x, st):
    identity = x
    if block.enable_scaling and not MERGED:
        x = x * block.pre_scale
    x, st = sconv(block.dwconv, x, st)
    x = block.norm(x)
    x = F.gelu(lin(block.pwconv1, x), approximate="tanh")
    x = lin(block.pwconv2, x)
    if not MERGED:
        if not block.use_weight_standardization:
            x = x * block.gamma
        if block.enable_scaling:
            x = x * (block.post_scale * block.post_scale_weight)
    return identity + x, st


def stack_states(stack: bt.ConvNeXtStack):
    """zero states: [embed] + one per block, time-major"""
    out = [torch.zeros(stack.embed.kernel_size[0] - 1, stack.embed.in_channels)]
    for b in stack.convnext:
        out.append(torch.zeros(b.dwconv.kernel_size[0] - 1, stack.embed.out_channels))
    return out


def run_stack(stack, x, states, attn=None, cross=None):
    """attn = (kcache [n,W,C], vcache, mask) for the self-attention stack; cross = [(k, v)]."""
    new = []
    x, s = sconv(stack.embed, x, states[0])
    new.append(s)
    x = stack.norm(x)
    nk, nv = [], []
    for i, b in enumerate(stack.convnext):
        if b.use_mha:
            if b.cross_attention:
                x = cross_attn(b, x, *cross[i])
            else:
                kc, vc, mask = attn
                x, k2, v2 = self_attn(b, x, kc[i], vc[i], mask)
                nk.append(k2)
                nv.append(v2)
        x, s = block_conv(b, x, states[1 + i])
        new.append(s)
    x = stack.final_layer_norm(x)
    if attn is not None:
        return x, new, torch.stack(nk), torch.stack(nv)
    return x, new


class SpeakerNet(nn.Module):
    """kv speaker embedding [384, 128] -> per prenet block K, V: [4, 2, h, 384, d]."""

    def __init__(self, net):
        super().__init__()
        self.prenet = net.vocoder.prenet

    def forward(self, kv):
        out = []
        for b in self.prenet.convnext:
            ca = b.mha
            k, v = ca.kv_projection(kv).split([ca.qk_channels, ca.vo_channels], 1)
            h = ca.num_heads
            k = k.view(-1, h, ca.head_qk_channels).transpose(0, 1)
            v = v.view(-1, h, ca.head_vo_channels).transpose(0, 1)
            out.append(torch.stack([k, v]))
        return torch.stack(out)


def sample_pitch(logits, bins_per_octave: int = 96, band_width: int = 4):
    """logits [T, 448] -> quantized [T] (long), features [T, 3] (PitchEstimator.sample_pitch)."""
    p = logits.softmax(1)
    nb = p.size(1)
    unvoiced = p[:, 0]
    p = torch.cat([torch.full_like(p[:, :1], -100.0), p[:, 1:]], 1)
    band = p[:, 0:nb - 3] + p[:, 1:nb - 2] + p[:, 2:nb - 1] + p[:, 3:nb]   # [T, 445]
    qb = band.argmax(1)
    band_p = band.gather(1, qb[:, None])[:, 0]
    half = band.gather(1, (qb - bins_per_octave).clamp(min=1)[:, None])[:, 0]
    half = torch.where(qb <= bins_per_octave, torch.zeros_like(half), half)
    dbl = band.gather(1, (qb + bins_per_octave).clamp(max=nb - band_width)[:, None])[:, 0]
    dbl = torch.where(qb > nb - band_width - bins_per_octave, torch.zeros_like(dbl), dbl)
    ar = torch.arange(nb)[None, :]
    mask = (qb[:, None] <= ar) & (ar < qb[:, None] + band_width)
    q = (p * mask.to(p.dtype)).argmax(1)
    feats = torch.stack([unvoiced, half / (band_p + 1e-6), dbl / (band_p + 1e-6)], 1)
    return q, feats


class StreamNet(nn.Module):
    """Inputs (T frames per call):
        wav      [1, 1, 240 + 160 (T-1)]  16 kHz: samples [160 k0 - 40, 160 (k0+T-1) + 200)
        pfeat    [T, 449]  pitch features (192 instfreq, 256 corr, 1 energy), frames k0-1..
        mask     [T, W+T]  additive self-attention mask (ring order, then the new frames)
        spk      [256]  embed_speaker + embed_formant_shift
        spk_kv   [4, 2, 4, 384, 32]  from SpeakerNet
        codebook [K, 128]  VQ codebook
        shift    []  pitch shift in bins (8 per semitone)
        + states (attention: the ring buffers [n, W, C], read only)
    Outputs: ir_amp [T, 257], ir_phase [T, 257], aper [T, 240], post [T, 512], hz [T],
        uv [T] (how likely each frame is unvoiced),
        then the new states (attention: just the new k, v [n, T, C]).
    Vocoder frames come out 2 frames behind the phone frames (k0-2 ..)."""

    def __init__(self, net):
        super().__init__()
        self.net = net
        self.pe = net.frozen_modules["phone_extractor"]
        self.pi = net.frozen_modules["pitch_estimator"]
        self.voc = net.vocoder
        self.stacks = {
            "phone": self.pe.backbone, "pitch": self.pi.backbone, "prenet": self.voc.prenet,
            "ir": self.voc.ir_generator, "ap": self.voc.aperiodicity_generator,
            "pf": self.voc.post_filter_generator,
        }
        self.state_shapes = {name: [tuple(s.shape) for s in stack_states(st)]
                             for name, st in self.stacks.items()}
        n_attn = sum(1 for b in self.pe.backbone.convnext if b.use_mha)
        self.attn_shape = (n_attn, W_ATTN, self.pe.backbone.convnext[0].mha.embed_dim)
        odd = torch.zeros(257)
        odd[1::2] = math.pi
        self.register_buffer("odd", odd)

    def state_names(self):
        names = []
        for name, shapes in self.state_shapes.items():
            names += [f"s_{name}_{i}" for i in range(len(shapes))]
        return names + ["s_attn_k", "s_attn_v"]

    def zero_states(self):
        out = [torch.zeros(s) for shapes in self.state_shapes.values() for s in shapes]
        return out + [torch.zeros(self.attn_shape), torch.zeros(self.attn_shape)]

    def forward(self, wav, pfeat, mask, spk, spk_kv, codebook, shift, *states):
        it = iter(states)
        st = {name: [next(it) for _ in shapes] for name, shapes in self.state_shapes.items()}
        kc, vc = next(it), next(it)
        new = {}

        # ---- phone extractor (the feature convs see the whole short window)
        fe = self.pe.feature_extractor
        x = wav
        for conv in (fe.conv0, fe.conv1, fe.conv2, fe.conv3, fe.conv4, fe.conv5):
            x = F.gelu(conv(x), approximate="tanh")
        x = self.pe.feature_projection.norm(x[0].transpose(0, 1))           # [T, 128]
        x, new["phone"], k2, v2 = run_stack(self.pe.backbone, x, st["phone"], attn=(kc, vc, mask))
        phone = pconv(self.pe.head, F.gelu(x, approximate="tanh"))           # [T, 128]
        # VQ: mean of the 4 nearest codes in the speaker's codebook
        q = F.normalize(phone, dim=1, eps=1e-6)
        _, idx = torch.matmul(q, codebook.transpose(0, 1)).topk(4, dim=1)    # [T, 4]
        phone = codebook[idx.reshape(-1)].view(-1, 4, codebook.size(1)).mean(1)
        phone = phone * torch.rsqrt(phone.square().mean(1, keepdim=True)
                                    + torch.finfo(torch.float).eps)

        # ---- pitch estimator (logits come out 1 frame behind its input: k0-2 ..)
        pi = self.pi
        a = F.gelu(pconv(pi.instfreq_embed_0, pfeat[:, :192]), approximate="tanh")
        a = pconv(pi.instfreq_embed_1, a)
        b = F.gelu(pconv(pi.corr_embed_0, pfeat[:, 192:448]), approximate="tanh")
        b = pconv(pi.corr_embed_1, b)
        y, new["pitch"] = run_stack(pi.backbone, F.gelu(a + b, approximate="tanh"), st["pitch"])
        qp, pf3 = sample_pitch(pconv(pi.head, y))
        qp = torch.where(qp == 0, qp, (qp.float() + shift).round().long().clamp(1, 447))
        # offline: conditioning frame t = phone t + energy t-1 + pitch t-2, which is
        # exactly what these inputs are; the vocoder's f0 is the unshifted pitch,
        # i.e. frames k0-2.. = the prenet's (2-frame-lagged) output frames
        hz = 55.0 * torch.pow(2.0, qp.float() / 96.0)
        n = self.net
        x = (pconv(n.embed_phone, phone)
             + n.embed_quantized_pitch(qp)
             + pconv(n.embed_pitch_features, torch.cat([pfeat[:, 448:449], pf3], 1))
             + spk)
        x = F.silu(x)

        # ---- vocoder networks
        cross = [(spk_kv[i, 0], spk_kv[i, 1]) for i in range(spk_kv.size(0))]
        x, new["prenet"] = run_stack(self.voc.prenet, x, st["prenet"], cross=cross)
        ir, new["ir"] = run_stack(self.voc.ir_generator, x, st["ir"])
        ir = pconv(self.voc.ir_generator_post, F.silu(ir))
        ap, new["ap"] = run_stack(self.voc.aperiodicity_generator, x, st["ap"])
        ap = pconv(self.voc.aperiodicity_generator_post, F.silu(ap))
        pf, new["pf"] = run_stack(self.voc.post_filter_generator, x, st["pf"])
        pf = pconv(self.voc.post_filter_generator_post, F.silu(pf))
        if not MERGED:
            ir = ir * self.voc.ir_scale
            ap = ap * self.voc.aperiodicity_scale
            pf = pf * self.voc.post_filter_scale
        ir_amp = ir[:, :257].exp()
        ir_phase = F.pad(ir[:, 257:], (1, 1)) + self.odd
        pf = torch.cat([pf[:, :1] + 1.0, pf[:, 1:]], 1)
        flat = [s for name in self.state_shapes for s in new[name]]
        return (ir_amp, ir_phase, ap, pf, hz, pf3[:, 0], *flat, k2, v2)
