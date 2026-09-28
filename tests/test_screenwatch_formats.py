"""Screen triggers: the frames Desktop Duplication hands over are decoded by their
DXGI format. An HDR ("advanced colour") monitor gives 16-bit float scRGB, a 10-bit
desktop packed 10-bit channels, the usual desktop 8-bit BGRA; all must come out as
the same grey the pictures are on. No screen is captured: the frames are made up."""
import ctypes
import logging

import numpy as np
import pytest

from soundboard import screenwatch as sw


def srgb_to_linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


# (r, g, b) as 8-bit sRGB pixels, the shape a picture (and the SDR desktop) comes in
COLOURS = [(0, 0, 0), (255, 255, 255), (128, 128, 128), (255, 0, 0), (0, 255, 0), (0, 0, 255),
           (200, 50, 120)]


def bgra8(colours) -> np.ndarray:
    px = np.zeros((1, len(colours), 4), np.uint8)
    for i, (r, g, b) in enumerate(colours):
        px[0, i] = (b, g, r, 255)
    return px


def rgba16f(colours) -> np.ndarray:
    px = np.zeros((1, len(colours), 4), np.float16)
    for i, c in enumerate(colours):
        px[0, i, :3] = [srgb_to_linear(v / 255) for v in c]
        px[0, i, 3] = 1.0
    return px


def rgb10a2(colours) -> np.ndarray:
    px = np.zeros((1, len(colours)), np.uint32)
    for i, (r, g, b) in enumerate(colours):
        r10, g10, b10 = (round(v / 255 * 1023) for v in (r, g, b))
        px[0, i] = r10 | (g10 << 10) | (b10 << 20) | (3 << 30)
    return px


def test_hdr_float_frames_give_the_same_grey_as_8_bit_pictures():
    want = sw.to_gray(bgra8(COLOURS))
    got = sw.frame_gray(rgba16f(COLOURS), sw.FMT_RGBA16F)
    assert got.dtype == np.float32 and got.shape == want.shape
    assert got == pytest.approx(want, abs=0.02)
    # mid grey: 0.214 linear is about 0.5 in sRGB, which is what an 8-bit 128 means
    assert got[0, 2] == pytest.approx(128 / 255, abs=0.02)


def test_hdr_highlights_above_white_are_clipped_to_white():
    px = rgba16f([(255, 255, 255)])
    px[0, 0, :3] = 4.0                                  # an HDR highlight, brighter than white
    assert sw.frame_gray(px, sw.FMT_RGBA16F)[0, 0] == pytest.approx(1.0, abs=1e-3)
    px[0, 0, :3] = -0.5                                 # scRGB can go negative too
    assert sw.frame_gray(px, sw.FMT_RGBA16F)[0, 0] == 0.0


def test_10_bit_frames_give_the_same_grey_as_8_bit_pictures():
    want = sw.to_gray(bgra8(COLOURS))
    got = sw.frame_gray(rgb10a2(COLOURS), sw.FMT_RGB10A2)
    assert got.dtype == np.float32 and got.shape == want.shape
    assert got == pytest.approx(want, abs=0.02)


def test_8_bit_frames_go_through_to_gray_and_gray_2x():
    px = bgra8(COLOURS)
    for fmt in (sw.FMT_BGRA8, sw.FMT_BGRX8):
        assert np.array_equal(sw.frame_gray(px, fmt), sw.to_gray(px))
    block = np.zeros((4, 4, 4), np.uint8)
    block[:2, :2, 2] = 255
    block[2:, 2:, :3] = 255
    assert np.array_equal(sw.frame_gray(block, sw.FMT_BGRA8, factor=2), sw.gray_2x(block))


def test_hdr_frames_are_averaged_2x2_at_factor_2():
    # a 4x4 frame: top-left 2x2 white, bottom-right 2x2 mid grey, the rest black
    px = np.zeros((4, 4, 4), np.float16)
    px[:2, :2, :3] = 1.0
    px[2:, 2:, :3] = srgb_to_linear(128 / 255)
    g = sw.frame_gray(px, sw.FMT_RGBA16F, factor=2)
    assert g.shape == (2, 2) and g.dtype == np.float32
    assert g[0, 0] == pytest.approx(1.0, abs=0.01)
    assert g[1, 1] == pytest.approx(128 / 255, abs=0.02)
    assert g[0, 1] == 0.0 and g[1, 0] == 0.0
    # a block half white, half black averages to half
    px[2:, :2, :3] = 0.0
    px[2, :2, :3] = 1.0
    assert sw.frame_gray(px, sw.FMT_RGBA16F, factor=2)[1, 0] == pytest.approx(0.5, abs=0.01)


def test_frame_view_reads_each_format_out_of_padded_rows():
    width, rows = 3, 2
    # 8-bit: BGRA, rows padded to 16 bytes
    raw = np.zeros((rows, 16), np.uint8)
    raw[1, 4:8] = (10, 20, 30, 255)                     # row 1, pixel 1
    px = sw.frame_view(raw, sw.FMT_BGRA8, width)
    assert px.shape == (rows, width, 4) and tuple(px[1, 1]) == (10, 20, 30, 255)
    # 16-bit float: RGBA, 8 bytes a pixel, rows padded to 32 bytes
    raw = np.zeros((rows, 32), np.uint8)
    raw[0, 16:24] = np.array([0.25, 0.5, 1.0, 1.0], np.float16).view(np.uint8)   # row 0, pixel 2
    px = sw.frame_view(raw, sw.FMT_RGBA16F, width)
    assert px.shape == (rows, width, 4) and px.dtype == np.float16
    assert tuple(px[0, 2]) == (0.25, 0.5, 1.0, 1.0)
    # 10-bit: one uint32 a pixel
    raw = np.zeros((rows, 16), np.uint8)
    raw[1, 8:12] = np.array([1023 | (512 << 10)], np.uint32).view(np.uint8)       # row 1, pixel 2
    px = sw.frame_view(raw, sw.FMT_RGB10A2, width)
    assert px.shape == (rows, width) and px.dtype == np.uint32
    assert px[1, 2] & 1023 == 1023 and (px[1, 2] >> 10) & 1023 == 512


def test_an_unknown_format_is_refused_not_misread():
    with pytest.raises(OSError, match="unsupported duplication format 28"):
        sw.frame_gray(np.zeros((2, 2, 4), np.uint8), 28)         # R8G8B8A8_UNORM
    with pytest.raises(OSError, match="unsupported duplication format 28"):
        sw.frame_view(np.zeros((2, 16), np.uint8), 28, 2)


def test_the_duplication_falls_back_to_gdi_on_an_unknown_format(monkeypatch, caplog):
    """_duplicate refuses a mode in a format it can't decode (so open_grabber goes
    to GDI) and says so in the log once, not every retry."""
    class FakeCom:
        def __init__(self, fill=None):
            self.fill = fill
            self.p = ctypes.c_void_p()

        def release(self):
            pass

        def call(self, slot, *args, **kw):
            if self.fill:
                self.fill(args)
            return 0

    def fill_desc(args):
        d = args[0]._obj
        d.Width, d.Height, d.Format, d.Rotation = 1920, 1080, 28, 1

    g = object.__new__(sw.DupGrabber)
    g.device, g.staging = FakeCom(), FakeCom()
    g.output1, g.dup = FakeCom(), FakeCom(fill_desc)
    g._mode = None
    monkeypatch.setattr(sw, "_unknown_formats", set())
    with caplog.at_level(logging.INFO, logger="soundboard.screenwatch"):
        for _ in range(2):
            with pytest.raises(OSError, match="unsupported duplication format 28"):
                g._duplicate()
    assert sum("DXGI format 28" in r.message for r in caplog.records) == 1
