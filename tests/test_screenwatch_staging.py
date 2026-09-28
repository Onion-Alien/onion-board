"""Desktop Duplication: the frames don't always come in the format the duplication
announces. On an HDR desktop the mode says 16-bit float (DXGI format 10) while the
acquired textures are 8-bit BGRA (87); CopyResource between different formats copies
nothing, so every frame read as black. grab() must size and type its staging copy
from the acquired frame itself. Fake COM objects, no Direct3D."""
import ctypes
import logging

import numpy as np

from soundboard import screenwatch as sw


class FakeCom:
    def __init__(self, handler=None):
        self.handler = handler
        self.p = ctypes.c_void_p(1)
        self.released = 0

    def release(self):
        self.released += 1

    def query(self, iid):
        return self.handler("query", iid)

    def call(self, slot, *args, **kw):
        if self.handler:
            r = self.handler("call", slot, args)
            if r is not None:
                return r
        return 0


def _grabber(monkeypatch, frame_fmt, frame_w, frame_h, pixel_bgra):
    """A DupGrabber whose duplication announced 1920x1080 format 10, but whose frames
    arrive in `frame_fmt` at frame_w x frame_h filled with one BGRA8 pixel."""
    created = []                       # (w, h, format) of every staging texture made
    bpp = sw.FRAME_FORMATS.get(frame_fmt, 4)
    pitch = frame_w * bpp
    buf = (ctypes.c_uint8 * (frame_h * pitch))()
    if bpp == 4:                       # 8-bit formats: one BGRA pixel repeated
        img = np.frombuffer(buf, np.uint8).reshape(frame_h, pitch)
        img[:] = np.tile(np.array(pixel_bgra, np.uint8), frame_w)

    def tex_handler(kind, slot, args=None):
        if kind == "call" and slot == sw.DupGrabber.TEX_GET_DESC:
            d = args[0]._obj
            d.Width, d.Height, d.Format = frame_w, frame_h, frame_fmt
        return 0

    tex = FakeCom(tex_handler)

    def res_handler(kind, *a):
        if kind == "query":
            return tex
        return 0

    def dup_handler(kind, slot, args=None):
        if kind == "call" and slot == sw.DupGrabber.DUP_ACQUIRE:
            info = args[1]._obj
            info[0] = 1                # LastPresentTime != 0: a real frame
        return 0

    def ctx_handler(kind, slot, args=None):
        if kind == "call" and slot == sw.DupGrabber.CTX_MAP:
            m = args[4]._obj
            m.pData = ctypes.addressof(buf)
            m.RowPitch = pitch
        return 0

    def device_handler(kind, slot, args=None):
        if kind == "call" and slot == sw.DupGrabber.DEVICE_CREATE_TEXTURE2D:
            d = args[0]._obj
            created.append((int(d.Width), int(d.Height), int(d.Format)))
        return 0

    monkeypatch.setattr(sw, "_COM", lambda: FakeCom(res_handler))
    g = object.__new__(sw.DupGrabber)
    g.src = sw.Monitor(0, 0, 1920, 1080, True)
    g.w, g.h = 320, 180
    g.device, g.ctx = FakeCom(device_handler), FakeCom(ctx_handler)
    g.output1, g.dup, g.staging = FakeCom(), FakeCom(dup_handler), FakeCom()
    g.last = None
    g.lost = False
    g._lost_at = g._lost_since = 0.0
    g._mode = None
    g._make_staging((1920, 1080, sw.FMT_RGBA16F))    # what the duplication announced
    created.clear()
    return g, created


def test_frames_in_another_format_than_announced_are_still_read(monkeypatch, caplog):
    g, created = _grabber(monkeypatch, sw.FMT_BGRA8, 1920, 1080, (200, 100, 50, 255))
    with caplog.at_level(logging.INFO, logger="soundboard.screenwatch"):
        gray = g.grab(100)
    assert created == [(1920, 1080, sw.FMT_BGRA8)]          # staging rebuilt for the frame
    assert g._mode == (1920, 1080, sw.FMT_BGRA8)
    expect = sw.to_gray(np.array([[[200, 100, 50, 255]]], np.uint8))[0, 0]
    assert gray.shape == (180, 320)
    assert abs(float(gray.mean()) - float(expect)) < 1e-3
    assert any("reading them as they come" in r.message for r in caplog.records)
    # the next frame in the same format doesn't rebuild anything
    g.grab(100)
    assert created == [(1920, 1080, sw.FMT_BGRA8)]


def test_frames_in_the_announced_format_do_not_rebuild(monkeypatch):
    g, created = _grabber(monkeypatch, sw.FMT_RGBA16F, 1920, 1080, (0, 0, 0, 0))
    g.grab(100)
    assert created == []


def test_a_frame_in_a_format_that_cannot_be_read_gives_up_to_gdi(monkeypatch):
    import pytest
    g, created = _grabber(monkeypatch, 28, 1920, 1080, (0, 0, 0, 0))
    monkeypatch.setattr(sw, "_unknown_formats", set())
    with pytest.raises(sw.CaptureLost, match="unsupported duplication format 28"):
        g.grab(100)
    assert created == []


def test_the_first_frame_is_read_even_when_nothing_has_moved_yet(monkeypatch):
    """The frame a new duplication starts with has LastPresentTime 0. It used to be
    skipped as blank, so on a screen where nothing moves (a static death screen, a
    launcher) the grabber never had a picture. Now it's read once; later frames
    with LastPresentTime 0 (only the mouse moved) are still skipped."""
    g, created = _grabber(monkeypatch, sw.FMT_BGRA8, 1920, 1080, (90, 90, 90, 255))
    calls = {"copy": 0}
    real = g.ctx.handler

    def counting(kind, slot, args=None):
        if kind == "call" and slot == sw.DupGrabber.CTX_COPY_RESOURCE:
            calls["copy"] += 1
        return real(kind, slot, args)

    g.ctx.handler = counting
    dup_real = g.dup.handler

    def still(kind, slot, args=None):
        r = dup_real(kind, slot, args)
        if kind == "call" and slot == sw.DupGrabber.DUP_ACQUIRE:
            args[1]._obj[0] = 0        # LastPresentTime 0
        return r

    g.dup.handler = still
    first = g.grab(100)
    assert first is not None and abs(float(first.mean()) - 90 / 255) < 1e-3
    assert calls["copy"] == 1
    again = g.grab(100)
    assert again is first and calls["copy"] == 1       # unchanged screen: no second copy
