#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bcencode_selftest.py -- verification harness for bcencode.py.

Run with::

    python bcencode_selftest.py [--quick]

Checks performed
----------------
1. Round-trip random noise 4x4 / 17x13 / 64x64 images through BC1, BC3, BC4 and
   BC5 and assert the decoded shapes and the encoded byte counts are exactly
   ``ceil(w/4) * ceil(h/4) * block_bytes``.
2. Encode/decode the real body-top albedo PNG with BC1 and the real body-top
   normal PNG with BC5 (R,G) and report PSNR per channel and overall, for mip 0
   as well as for the whole mip chain (pixel weighted).
3. Assert ``pack_texture_blob`` output length equals the independently computed
   sum of mip sizes for a 2048x2048 image with a full 12-mip chain.
4. Extra: hand-built blocks that pin the exact bit layout rules, a comparison
   against a naive min/max bounding-box BC1 encoder, and an end-to-end CLI run
   (``bc1`` encode -> ``decode`` back to PNG).

Prints a PASS/FAIL summary and exits non-zero if anything failed.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bcencode as bc  # noqa: E402

TEXDIR = r"<textures>"
ALBEDO_PNG = os.environ.get("TEST_ALBEDO_PNG", os.path.join(TEXDIR, "albedo.png"))
NORMAL_PNG = os.environ.get("TEST_NORMAL_PNG", os.path.join(TEXDIR, "normal.png"))

OUT_BC = os.path.join(HERE, "test_bc1.bc")
OUT_PNG = os.path.join(HERE, "test_bc1_roundtrip.png")

BC1_MIN_PSNR = 32.0     # expected for the albedo
BC5_MIN_PSNR = 38.0     # expected for the normal map (R,G)

_RESULTS: list[tuple] = []


# --------------------------------------------------------------------------
# tiny harness
# --------------------------------------------------------------------------

def check(name: str, ok: bool, detail: str = "") -> bool:
    _RESULTS.append((name, bool(ok), detail))
    tag = "PASS" if ok else "FAIL"
    line = f"  [{tag}] {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    return bool(ok)


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def psnr(a: np.ndarray, b: np.ndarray, peak: float = 255.0) -> float:
    d = a.astype(np.float64) - b.astype(np.float64)
    mse = float((d * d).mean())
    if mse <= 0.0:
        return float("inf")
    return 10.0 * math.log10(peak * peak / mse)


def block_grid_bytes(w: int, h: int, fmt) -> int:
    """Independent re-implementation of the byte-count rule (no library use)."""
    bw = (w + 3) // 4
    bh = (h + 3) // 4
    return bw * bh * bc.block_bytes(fmt)


def load_rgba(path: str) -> np.ndarray:
    from PIL import Image
    with Image.open(path) as im:
        return np.array(im.convert("RGBA"), dtype=np.uint8)


# --------------------------------------------------------------------------
# 1. round-trip / size checks
# --------------------------------------------------------------------------

def test_roundtrip_sizes() -> None:
    section("1. Round-trip shapes and byte counts (random noise)")
    rng = np.random.default_rng(20240607)
    cases = [(4, 4), (17, 13), (64, 64)]

    for (w, h) in cases:
        rgba = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)
        gray = rng.integers(0, 256, (h, w), dtype=np.uint8)
        rg = rng.integers(0, 256, (h, w, 2), dtype=np.uint8)
        nblk = ((w + 3) // 4) * ((h + 3) // 4)
        print(f"\n  -- {w}x{h}: block grid {((w + 3) // 4)}x{((h + 3) // 4)}"
              f" = {nblk} blocks")

        b1 = bc.encode_bc1(rgba)
        d1 = bc.decode_bc1(b1, w, h)
        check(f"{w}x{h} BC1 size == {nblk}*8", len(b1) == nblk * 8,
              f"got {len(b1)}, want {nblk * 8}")
        check(f"{w}x{h} BC1 size == independent formula",
              len(b1) == block_grid_bytes(w, h, "DXT1"))
        check(f"{w}x{h} BC1 decoded shape == ({h}, {w}, 4)",
              d1.shape == (h, w, 4) and d1.dtype == np.uint8, f"got {d1.shape}")

        b3 = bc.encode_bc3(rgba)
        d3 = bc.decode_bc3(b3, w, h)
        check(f"{w}x{h} BC3 size == {nblk}*16", len(b3) == nblk * 16,
              f"got {len(b3)}, want {nblk * 16}")
        check(f"{w}x{h} BC3 size == independent formula",
              len(b3) == block_grid_bytes(w, h, "DXT5"))
        check(f"{w}x{h} BC3 decoded shape == ({h}, {w}, 4)",
              d3.shape == (h, w, 4) and d3.dtype == np.uint8, f"got {d3.shape}")

        b4 = bc.encode_bc4(gray)
        d4 = bc.decode_bc4(b4, w, h)
        check(f"{w}x{h} BC4 size == {nblk}*8", len(b4) == nblk * 8,
              f"got {len(b4)}, want {nblk * 8}")
        check(f"{w}x{h} BC4 size == independent formula",
              len(b4) == block_grid_bytes(w, h, "BC4"))
        check(f"{w}x{h} BC4 decoded shape == ({h}, {w})",
              d4.shape == (h, w) and d4.dtype == np.uint8, f"got {d4.shape}")

        b5 = bc.encode_bc5(rg)
        d5 = bc.decode_bc5(b5, w, h)
        check(f"{w}x{h} BC5 size == {nblk}*16", len(b5) == nblk * 16,
              f"got {len(b5)}, want {nblk * 16}")
        check(f"{w}x{h} BC5 size == independent formula",
              len(b5) == block_grid_bytes(w, h, "BC5"))
        check(f"{w}x{h} BC5 decoded shape == ({h}, {w}, 2)",
              d5.shape == (h, w, 2) and d5.dtype == np.uint8, f"got {d5.shape}")

        # BC5 must be exactly BC4(R) interleaved per block with BC4(G): the
        # first 8 bytes of a block are R, the second 8 are G.
        blk5 = np.frombuffer(b5, dtype=np.uint8).reshape(nblk, 16)
        check(f"{w}x{h} BC5 = per-block BC4(R) then BC4(G)",
              np.array_equal(blk5[:, 8:16], np.frombuffer(
                  bc.encode_bc4(np.ascontiguousarray(rg[:, :, 1])),
                  dtype=np.uint8).reshape(nblk, 8))
              and np.array_equal(blk5[:, 0:8], np.frombuffer(
                  bc.encode_bc4(np.ascontiguousarray(rg[:, :, 0])),
                  dtype=np.uint8).reshape(nblk, 8)))

        # BC3 must be exactly BC4(alpha) then BC1(colour), per block.
        blk3 = np.frombuffer(b3, dtype=np.uint8).reshape(nblk, 16)
        check(f"{w}x{h} BC3 = per-block BC4(alpha) then BC1(colour)",
              np.array_equal(blk3[:, 0:8], np.frombuffer(
                  bc.encode_bc4(np.ascontiguousarray(rgba[:, :, 3])),
                  dtype=np.uint8).reshape(nblk, 8))
              and np.array_equal(blk3[:, 8:16], np.frombuffer(
                  bc.encode_bc1(rgba), dtype=np.uint8).reshape(nblk, 8)))

        # every BC1 colour block must be in 4-colour (opaque) mode
        c0 = blk3[:, 8].astype(np.uint16) | (blk3[:, 9].astype(np.uint16) << 8)
        c1 = blk3[:, 10].astype(np.uint16) | (blk3[:, 11].astype(np.uint16) << 8)
        check(f"{w}x{h} BC3 colour blocks all use c0 > c1",
              bool(np.all(c0 > c1)))
        cb0 = np.frombuffer(b1, dtype=np.uint8).reshape(nblk, 8)
        a0 = cb0[:, 0].astype(np.uint16) | (cb0[:, 1].astype(np.uint16) << 8)
        a1 = cb0[:, 2].astype(np.uint16) | (cb0[:, 3].astype(np.uint16) << 8)
        check(f"{w}x{h} BC1 blocks all use c0 > c1", bool(np.all(a0 > a1)))

        # BC4 blocks must all select the 8-value interpolated mode
        blk4 = np.frombuffer(b4, dtype=np.uint8).reshape(nblk, 8)
        r0 = blk4[:, 0].astype(np.int32)
        r1 = blk4[:, 1].astype(np.int32)
        check(f"{w}x{h} BC4 blocks all use red0 > red1", bool(np.all(r0 > r1)))

        # edge padding must replicate the last pixel, not zero-fill it
        if w % 4 or h % 4:
            solid = np.full((h, w, 4), 77, dtype=np.uint8)
            dec = bc.decode_bc1(bc.encode_bc1(solid), w, h)
            check(f"{w}x{h} edge clamp (not zero fill) round-trips a solid image",
                  int(np.abs(dec[:, :, :3].astype(int) - 77).max()) <= 4,
                  f"max deviation {int(np.abs(dec[:, :, :3].astype(int) - 77).max())}")

    # flat blocks: c0 == c1 must be nudged so the opaque 4-colour mode holds
    for v in (0, 1, 127, 128, 255):
        blk = bc.encode_bc1(np.full((4, 4, 4), v, dtype=np.uint8))
        c0 = int.from_bytes(blk[0:2], "little")
        c1 = int.from_bytes(blk[2:4], "little")
        dec = int(bc.decode_bc1(blk, 4, 4)[0, 0, 0])
        check(f"BC1 flat grey {v}: c0({c0}) > c1({c1}) and decodes to {dec}",
              c0 > c1 and abs(dec - v) <= 4)
    for v in (0, 1, 127, 255):
        blk = bc.encode_bc4(np.full((4, 4), v, dtype=np.uint8))
        dec = int(bc.decode_bc4(blk, 4, 4)[0, 0])
        check(f"BC4 flat grey {v}: red0({blk[0]}) > red1({blk[1]}), decodes to {dec}",
              blk[0] > blk[1] and dec == v)


# --------------------------------------------------------------------------
# 1b. exact bit-layout checks with hand-built blocks
# --------------------------------------------------------------------------

def test_bit_layout() -> None:
    section("1b. Exact bit layout of the index words (hand-built blocks)")

    # BC1: c0 = 0xF800 (pure red) > c1 = 0x001F (pure blue) -> 4-colour mode.
    # palette = [red, blue, (2r+b)/3, (r+2b)/3] = [255,0,0], [0,0,255],
    #           [170,0,85], [85,0,170]
    idx = np.array([p % 4 for p in range(16)], dtype=np.uint32)
    word = int((idx << (2 * np.arange(16, dtype=np.uint32))).sum())
    raw = bytes([0x00, 0xF8, 0x1F, 0x00,
                 word & 0xFF, (word >> 8) & 0xFF,
                 (word >> 16) & 0xFF, (word >> 24) & 0xFF])
    img = bc.decode_bc1(raw, 4, 4)[:, :, :3]
    want = {(0, 0): (255, 0, 0), (0, 1): (0, 0, 255),
            (0, 2): (170, 0, 85), (0, 3): (85, 0, 170),
            (1, 0): (255, 0, 0), (2, 1): (0, 0, 255),
            (3, 3): (85, 0, 170)}
    ok = all(tuple(int(x) for x in img[r, c]) == v for (r, c), v in want.items())
    check("BC1 index bit order: pixel row*4+col at bit 2*index "
          "(top-left in the lowest 2 bits)", ok,
          "decoded " + ", ".join(f"({r},{c})={tuple(int(x) for x in img[r, c])}"
                                 for (r, c) in sorted(want)))

    # BC4: red0 = 255 > red1 = 0 -> palette 255,0,218,182,145,109,72,36
    i4 = np.array([p % 8 for p in range(16)], dtype=np.uint64)
    w48 = int((i4 << (3 * np.arange(16, dtype=np.uint64))).sum())
    raw4 = bytes([255, 0] + [(w48 >> (8 * k)) & 0xFF for k in range(6)])
    dec = bc.decode_bc4(raw4, 4, 4)
    pal = [255, 0, (6 * 255) // 7, (5 * 255) // 7, (4 * 255) // 7,
           (3 * 255) // 7, (2 * 255) // 7, (1 * 255) // 7]
    want4 = np.array([[pal[p % 8] for p in range(16)]], dtype=np.uint8)
    want4 = want4.reshape(4, 4)
    check("BC4 index bit order: pixel row*4+col at bit 3*index "
          "(top-left in the lowest 3 bits)", np.array_equal(dec, want4),
          f"palette {pal}")

    # 48-bit little-endian index word: byte 7 of the block must carry the
    # top bits of index 15 (6 bytes only, no 7th byte of payload).
    high = np.array([0] * 15 + [7], dtype=np.uint64)
    w48b = int((high << (3 * np.arange(16, dtype=np.uint64))).sum())
    rawb = bytes([255, 0] + [(w48b >> (8 * k)) & 0xFF for k in range(6)])
    check("BC4 48-bit word is little-endian (index 15 -> byte 7, top bits)",
          bc.decode_bc4(rawb, 4, 4)[3, 3] == 36 and len(rawb) == 8)

    # BC5/BC3 must be little-endian too: decode a hand-built BC5 block.
    rg = bc.decode_bc5(raw4 + raw4, 4, 4)
    check("BC5 block = 8-byte R word then 8-byte G word",
          np.array_equal(rg[:, :, 0], want4) and np.array_equal(rg[:, :, 1], want4))

    # byte counts must use the padded grid
    check("block_bytes() values", (bc.block_bytes("DXT1"), bc.block_bytes("DXT5"),
                                   bc.block_bytes("BC4"), bc.block_bytes("BC5"))
          == (8, 16, 8, 16))
    check("mip_size() saturates at 1",
          [bc.mip_size(2048, 2048, lv) for lv in (0, 10, 11, 12, 20)]
          == [(2048, 2048), (2, 2), (1, 1), (1, 1), (1, 1)])
    check("mip_size(2048,2048,11,'DXT1') == 8", bc.mip_size(2048, 2048, 11, "DXT1") == 8)


# --------------------------------------------------------------------------
# 2. real image PSNR
# --------------------------------------------------------------------------

def _chain_psnr_accumulate(encode, decode, mips, channels):
    """Return (sum_sq_err_per_channel, pixel_count) over a whole mip chain."""
    se = np.zeros(channels, dtype=np.float64)
    n = 0
    per_level = []
    for lv, m in enumerate(mips):
        enc = encode(m)
        dec = decode(enc, m.shape[1], m.shape[0])
        diff = m[..., :channels].astype(np.float64) - dec[..., :channels].astype(np.float64)
        se += (diff * diff).sum(axis=(0, 1))
        n += m.shape[0] * m.shape[1]
        per_level.append((lv, m.shape[1], m.shape[0], psnr(m[..., :channels],
                                                           dec[..., :channels])))
    return se, n, per_level


def test_real_image_psnr() -> None:
    section("2. PSNR on the real body-top textures")

    for path in (ALBEDO_PNG, NORMAL_PNG):
        if not os.path.isfile(path):
            check(f"input exists: {path}", False)
            return

    # ---- BC1 / DXT1 on the albedo ----------------------------------------
    alb_rgba = load_rgba(ALBEDO_PNG)
    h, w = alb_rgba.shape[:2]
    alb = np.ascontiguousarray(alb_rgba[:, :, :3])
    print(f"\n  BC1 (DXT1) source: {ALBEDO_PNG}")
    print(f"    {w}x{h}, alpha range {int(alb_rgba[:, :, 3].min())}.."
          f"{int(alb_rgba[:, :, 3].max())} -> opaque, BC1 is the right format")

    b1 = bc.encode_bc1(alb_rgba)
    d1 = bc.decode_bc1(b1, w, h)[:, :, :3]
    check("BC1 mip0 byte count", len(b1) == block_grid_bytes(w, h, "DXT1"),
          f"{len(b1)} bytes")
    ch_names = "RGB"
    per_ch = [psnr(alb[:, :, i], d1[:, :, i]) for i in range(3)]
    overall = psnr(alb, d1)
    for i, nm in enumerate(ch_names):
        print(f"    PSNR {nm} (mip 0) : {per_ch[i]:6.2f} dB")
    print(f"    PSNR RGB (mip 0):  {overall:6.2f} dB   (target >= {BC1_MIN_PSNR})")
    check(f"BC1 mip0 overall PSNR >= {BC1_MIN_PSNR} dB", overall >= BC1_MIN_PSNR,
          f"{overall:.2f} dB")

    mips1 = bc.make_mips(alb, bc.full_mip_count(w, h))
    se1, n1, lv1 = _chain_psnr_accumulate(bc.encode_bc1, bc.decode_bc1, mips1, 3)
    chain1 = 10.0 * math.log10(255.0 * 255.0 / (se1.sum() / (n1 * 3)))
    print(f"    full {len(mips1)}-mip chain, pixel-weighted PSNR: "
          f"{chain1:6.2f} dB  over {n1} pixels")
    print("    per-level PSNR: " + " ".join(f"L{lv}:{p:.1f}" for lv, _w, _h, p in lv1))
    check(f"BC1 full-chain weighted PSNR >= {BC1_MIN_PSNR} dB",
          chain1 >= BC1_MIN_PSNR, f"{chain1:.2f} dB")

    # ---- BC5 on the normal map -------------------------------------------
    nrm_rgba = load_rgba(NORMAL_PNG)
    h5, w5 = nrm_rgba.shape[:2]
    rg = np.ascontiguousarray(nrm_rgba[:, :, :2])
    print(f"\n  BC5 source: {NORMAL_PNG}")
    print(f"    {w5}x{h5}, using R and G channels")
    b5 = bc.encode_bc5(rg)
    d5 = bc.decode_bc5(b5, w5, h5)
    check("BC5 mip0 byte count", len(b5) == block_grid_bytes(w5, h5, "BC5"),
          f"{len(b5)} bytes")
    p_r = psnr(rg[:, :, 0], d5[:, :, 0])
    p_g = psnr(rg[:, :, 1], d5[:, :, 1])
    p_rg = psnr(rg, d5)
    print(f"    PSNR R (X) (mip 0): {p_r:6.2f} dB")
    print(f"    PSNR G (Y) (mip 0): {p_g:6.2f} dB")
    print(f"    PSNR RG (mip 0):    {p_rg:6.2f} dB   (target >= {BC5_MIN_PSNR})")
    check(f"BC5 mip0 overall PSNR >= {BC5_MIN_PSNR} dB", p_rg >= BC5_MIN_PSNR,
          f"{p_rg:.2f} dB")

    mips5 = bc.make_mips(rg, bc.full_mip_count(w5, h5))
    se5, n5, lv5 = _chain_psnr_accumulate(bc.encode_bc5, bc.decode_bc5, mips5, 2)
    chain5 = 10.0 * math.log10(255.0 * 255.0 / (se5.sum() / (n5 * 2)))
    print(f"    full {len(mips5)}-mip chain, pixel-weighted PSNR: "
          f"{chain5:6.2f} dB  over {n5} pixels")
    print("    per-level PSNR: " + " ".join(f"L{lv}:{p:.1f}" for lv, _w, _h, p in lv5))
    check(f"BC5 full-chain weighted PSNR >= {BC5_MIN_PSNR} dB",
          chain5 >= BC5_MIN_PSNR, f"{chain5:.2f} dB")

    # ---- quality bar: PCA endpoint fit must beat a naive bbox fit --------
    naive = _encode_bc1_naive(alb)
    naive_dec = bc.decode_bc1(naive, w, h)[:, :, :3]
    naive_psnr = psnr(alb, naive_dec)
    print(f"\n    naive per-channel min/max bbox BC1 baseline: {naive_psnr:6.2f} dB")
    print(f"    PCA/inset endpoint search (this codec):      {overall:6.2f} dB")
    check("PCA + inset refinement beats naive bbox BC1", overall > naive_psnr,
          f"+{overall - naive_psnr:.2f} dB")


def _encode_bc1_naive(rgb: np.ndarray) -> bytes:
    """Reference baseline: per-channel min/max bounding box endpoints only."""
    h, w = rgb.shape[:2]
    ph, pw = (-h) % 4, (-w) % 4
    img = np.pad(rgb, ((0, ph), (0, pw), (0, 0)), mode="edge") if (ph or pw) else rgb
    blocks = (img.reshape(img.shape[0] // 4, 4, img.shape[1] // 4, 4, 3)
                 .transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3))
    x = blocks.astype(np.float32)
    lo = x.min(axis=1)
    hi = x.max(axis=1)

    def pack(v):
        v = np.clip(np.rint(v), 0, 255).astype(np.int32)
        return (((v[:, 0] * 31 + 127) // 255).astype(np.uint16) << 11) | \
               (((v[:, 1] * 63 + 127) // 255).astype(np.uint16) << 5) | \
               ((v[:, 2] * 31 + 127) // 255).astype(np.uint16)

    q0, q1 = pack(hi), pack(lo)
    swap = q0 < q1
    q0, q1 = np.where(swap, q1, q0), np.where(swap, q0, q1)
    eq = q0 == q1
    q1 = np.where(eq & (q1 > 0), q1 - 1, q1)
    q0 = np.where(eq & (q1 == 0), q0 + 1, q0)

    e0 = bc._expand565(q0).astype(np.float32)
    e1 = bc._expand565(q1).astype(np.float32)
    pal = np.stack([e0, e1, (2 * e0 + e1) // 3, (e0 + 2 * e1) // 3], axis=1)
    d = x[:, :, None, :] - pal[:, None, :, :]
    idx = np.einsum("npkc,npkc->npk", d, d).argmin(axis=2).astype(np.uint32)
    words = (idx << (2 * np.arange(16, dtype=np.uint32))[None, :]).sum(axis=1)
    out = np.empty((blocks.shape[0], 8), dtype=np.uint8)
    out[:, 0] = q0 & 0xFF
    out[:, 1] = q0 >> 8
    out[:, 2] = q1 & 0xFF
    out[:, 3] = q1 >> 8
    for k in range(4):
        out[:, 4 + k] = (words >> (8 * k)) & 0xFF
    return out.tobytes()


# --------------------------------------------------------------------------
# 3. 2048x2048 / 12-mip packing check
# --------------------------------------------------------------------------

def test_pack_2048(quick: bool = False) -> None:
    section("3. pack_texture_blob length for 2048x2048 with a full 12-mip chain")

    w = h = 2048
    mips_n = bc.full_mip_count(w, h)
    check("full chain length for 2048x2048 == 12", mips_n == 12, f"got {mips_n}")

    # --- independently computed expectation (no library helpers) ----------
    fmt = "DXT1"
    bpb = 8
    per_level = []
    expected = 0
    for lv in range(mips_n):
        mw = max(1, w >> lv)
        mh = max(1, h >> lv)
        nbytes = ((mw + 3) // 4) * ((mh + 3) // 4) * bpb
        per_level.append((lv, mw, mh, nbytes))
        expected += nbytes

    print(f"\n  format {fmt} ({bpb} bytes/block), {mips_n} levels")
    print("    lvl    mip dims      blocks    bytes")
    for lv, mw, mh, nbytes in per_level:
        print(f"    {lv:3d}   {mw:5d}x{mh:<5d}  {((mw + 3) // 4):3d}x"
              f"{((mh + 3) // 4):<3d}  {nbytes:9d}")
    print(f"    {'':>13} expected total  {expected:9d} bytes")

    # cross-check the library's own helpers against that same table
    lib_total = sum(bc.mip_level_bytes(w, h, lv, fmt) for lv in range(mips_n))
    check("library mip_level_bytes sum == independent total", lib_total == expected,
          f"{lib_total} vs {expected}")
    check("chain_byte_size() == independent total",
          bc.chain_byte_size(w, h, fmt, mips_n) == expected)
    check("mip_size() dims match the table",
          all(bc.mip_size(w, h, lv) == (mw, mh)
              for lv, mw, mh, _b in per_level))

    # --- real encode of the whole chain, then pack -------------------------
    if quick:
        blobs = [bytes(nbytes) for *_x, nbytes in per_level]
        print("    (--quick: synthetic zero blobs of the computed lengths)")
    else:
        rng = np.random.default_rng(1234)
        base = rng.integers(0, 256, (w, h, 3), dtype=np.uint8)
        chain = bc.make_mips(base, mips_n)
        print(f"    encoding {len(chain)} real mip levels of a {w}x{h} image...")
        blobs = [bc.encode_bc1(m) for m in chain]
        check("every encoded mip has its formula length",
              all(len(b) == nbytes for b, (*_x, nbytes) in zip(blobs, per_level)),
              "lens " + ",".join(str(len(b)) for b in blobs))

    blob = bc.pack_texture_blob(blobs, array_count=1)
    print(f"    pack_texture_blob() got  {len(blob):9d} bytes")
    check("pack_texture_blob length == independent expected total",
          len(blob) == expected, f"got {len(blob)}, want {expected}")
    check("pack_texture_blob(array_count=1) is a plain concatenation",
          blob == b"".join(blobs))

    # array_count > 1: DDS mip-major input must come out array-major
    per_array_blobs = [bytes([a]) * 4 + bytes([m]) * 4
                       for m in range(2) for a in range(2)]  # mip-major
    packed = bc.pack_texture_blob(per_array_blobs, array_count=2)
    want = (per_array_blobs[0] + per_array_blobs[2]
            + per_array_blobs[1] + per_array_blobs[3])
    check("pack_texture_blob(array_count=2) re-orders to array-major",
          packed == want, f"{packed!r}")
    check("pack_texture_blob length is array_count * chain size",
          len(packed) == 2 * sum(len(b) for b in per_array_blobs[:2]))

    # documented ambiguity: the iterative reading of the mip rule keeps
    # emitting extra 1x1 levels; report what that alternative total would be.
    alt = 0
    cw, ch = w, h
    for _ in range(mips_n + 2):
        alt += ((cw + 3) // 4) * ((ch + 3) // 4) * bpb
        cw, ch = max(1, cw >> 1), max(1, ch >> 1)
    print(f"    (for reference: iterating max(1, x>>1) for {mips_n + 2} levels "
          f"would give {alt} bytes; the rule as specified saturates at 1x1 and "
          f"gives {expected})")


# --------------------------------------------------------------------------
# 4. CLI end to end
# --------------------------------------------------------------------------

def test_cli() -> None:
    section("4. CLI end to end (bc1 encode -> decode back to PNG)")

    if not os.path.isfile(ALBEDO_PNG):
        check("CLI: albedo input exists", False, ALBEDO_PNG)
        return

    py = sys.executable
    script = os.path.join(HERE, "bcencode.py")

    def run(args):
        return subprocess.run([py, script] + args, capture_output=True,
                              text=True, cwd=HERE)

    r1 = run(["bc1", ALBEDO_PNG, OUT_BC])
    print("    $ python bcencode.py bc1 <albedo.png> " + OUT_BC)
    for line in (r1.stdout or "").splitlines():
        print("      " + line)
    check("CLI bc1 exit code 0", r1.returncode == 0, (r1.stderr or "").strip()[-200:])
    check("CLI wrote the .bc blob", os.path.isfile(OUT_BC),
          f"{os.path.getsize(OUT_BC) if os.path.isfile(OUT_BC) else 0} bytes")

    side = OUT_BC + ".json"
    ok_side = os.path.isfile(side)
    check("CLI wrote the JSON sidecar", ok_side, side)
    if ok_side:
        import json
        with open(side, encoding="utf-8") as fh:
            meta = json.load(fh)
        print(f"      sidecar: {meta}")
        check("sidecar keys/values",
              set(meta) == {"width", "height", "mips", "format", "bytes"}
              and meta["format"] == "DXT1" and meta["width"] == 1024
              and meta["height"] == 1024 and meta["mips"] == 11
              and meta["bytes"] == os.path.getsize(OUT_BC), str(meta))

    with open(OUT_BC, "rb") as fh:
        blob = fh.read()
    check("CLI blob length == independent formula",
          len(blob) == _cli_expected_total(1024, 1024),
          f"{len(blob)} bytes")

    # cross-check the CLI output against a direct library encode
    alb = load_rgba(ALBEDO_PNG)
    lib = bc.pack_texture_blob(
        [bc.encode_bc1(m) for m in bc.make_mips(alb[:, :, :3], 11)], 1)
    check("CLI blob is byte-identical to the library path", lib == blob)

    r2 = run(["decode", OUT_BC, OUT_PNG, "--format", "bc1",
              "--width", "1024", "--height", "1024", "--mips", "11"])
    print("    $ python bcencode.py decode " + OUT_BC + " " + OUT_PNG + " ...")
    for line in (r2.stdout or "").splitlines():
        print("      " + line)
    check("CLI decode exit code 0", r2.returncode == 0, (r2.stderr or "").strip()[-200:])
    check("CLI wrote the round-trip PNG", os.path.isfile(OUT_PNG),
          f"{os.path.getsize(OUT_PNG) if os.path.isfile(OUT_PNG) else 0} bytes")

    if os.path.isfile(OUT_PNG):
        from PIL import Image
        with Image.open(OUT_PNG) as im:
            back = np.array(im.convert("RGB"), dtype=np.uint8)
        ref = bc.decode_bc1(blob, 1024, 1024)[:, :, :3]
        check("round-trip PNG matches the library decode exactly",
              back.shape == ref.shape and np.array_equal(back, ref))
        p = psnr(alb[:, :, :3], back)
        print(f"      PSNR of the decoded PNG vs the source albedo: {p:.2f} dB")
        check(f"round-trip PNG PSNR >= {BC1_MIN_PSNR} dB", p >= BC1_MIN_PSNR,
              f"{p:.2f} dB")

    # --mips override
    r3 = run(["bc1", ALBEDO_PNG, OUT_BC + ".1mip", "--mips", "1"])
    check("CLI --mips 1 exit code 0", r3.returncode == 0)
    check("CLI --mips 1 blob is exactly mip 0",
          os.path.getsize(OUT_BC + ".1mip") == block_grid_bytes(1024, 1024, "DXT1"))
    for f in (OUT_BC + ".1mip", OUT_BC + ".1mip.json"):
        if os.path.isfile(f):
            os.remove(f)

    # bc5 CLI path
    r4 = run(["bc5", NORMAL_PNG, OUT_BC + ".bc5", "--from-normal"])
    check("CLI bc5 --from-normal exit code 0", r4.returncode == 0,
          (r4.stderr or "").strip()[-200:])
    if os.path.isfile(OUT_BC + ".bc5"):
        with open(OUT_BC + ".bc5", "rb") as fh:
            b5 = fh.read()
        check("CLI bc5 blob length == 11-mip BC5 chain",
              len(b5) == _cli_expected_total(1024, 1024, "BC5"))
        nr = load_rgba(NORMAL_PNG)
        want = np.ascontiguousarray(np.stack(
            [nr[:, :, 0], (255 - nr[:, :, 1].astype(np.uint16)).astype(np.uint8)],
            axis=2))
        check("CLI bc5 --from-normal flips G and takes R,G",
              b5 == bc.pack_texture_blob(
                  [bc.encode_bc5(m) for m in bc.make_mips(want, 11)], 1))
        for f in (OUT_BC + ".bc5", OUT_BC + ".bc5.json"):
            if os.path.isfile(f):
                os.remove(f)


def _cli_expected_total(w: int, h: int, fmt: str = "DXT1") -> int:
    return sum(block_grid_bytes(*bc.mip_size(w, h, lv), fmt)
               for lv in range(bc.full_mip_count(w, h)))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="bcencode.py self test")
    ap.add_argument("--quick", action="store_true",
                    help="skip the real 2048x2048 encode in test 3")
    args = ap.parse_args(argv)

    print(f"python  {sys.version.split()[0]}")
    print(f"numpy   {np.__version__}")
    print(f"module  {bc.__file__}")
    print(f"workdir {HERE}")

    tests = [
        ("1  round-trip sizes", lambda: test_roundtrip_sizes()),
        ("1b bit layout", lambda: test_bit_layout()),
        ("2  real image PSNR", lambda: test_real_image_psnr()),
        ("3  2048x2048 packing", lambda: test_pack_2048(args.quick)),
        ("4  CLI end to end", lambda: test_cli()),
    ]
    for name, fn in tests:
        try:
            fn()
        except Exception:
            print(f"\n  [FAIL] {name} raised an exception:")
            traceback.print_exc()
            _RESULTS.append((f"{name} (exception)", False, "see traceback"))

    section("SUMMARY")
    failed = [r for r in _RESULTS if not r[1]]
    for name, ok, detail in _RESULTS:
        if not ok:
            print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))
    npass = len(_RESULTS) - len(failed)
    print(f"\n  {npass}/{len(_RESULTS)} checks passed")
    print("  RESULT: " + ("PASS" if not failed else f"FAIL ({len(failed)} failed)"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
