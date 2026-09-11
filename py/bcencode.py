#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bcencode.py -- CPU block-compression codec producing the exact byte layout that
Mount & Blade II: Bannerlord expects for texture pixel blobs inside ``.tpac``
asset files.

Formats
-------
===========  ==========  ===================  ==========================
material     tpac name   codec                bytes / 4x4 block
===========  ==========  ===================  ==========================
albedo       DXT1        BC1 (opaque, 4-col)  8
albedo+alpha DXT5        BC3 (BC4 a + BC1)    16
normal       BC5         BC4(R) + BC4(G)      16
specular     DXT1        BC1 (opaque, 4-col)  8
===========  ==========  ===================  ==========================

tpac pixel blob layout (no header, no padding, no alignment)::

    for array in range(array_count):     # normally 1
        for mip in range(mip_count):     # mip 0 is full size
            <raw block compressed bytes for that (array, mip)>

Mip dimension of level L is ``max(1, w >> L)`` / ``max(1, h >> L)``; the byte
length of one mip is ``ceil(mw/4) * ceil(mh/4) * block_bytes(fmt)``.
The full chain length is ``floor(log2(max(w, h))) + 1``.

Encoding rules implemented here
-------------------------------
* Everything is little-endian raw bytes (written with explicit shifts, so this
  is endianness independent).
* BC1 block  = c0:u16le | c1:u16le | index_word:u32le, index word carries
  sixteen 2-bit palette indices, pixel ``row*4+col`` lives at bit ``2*index``
  (top-left pixel in the LOWEST 2 bits).
* BC1 opaque mode always guarantees ``c0 > c1`` (unsigned 16-bit compare) so
  the 4-colour palette is used.  The BC1 colour block embedded in BC3 uses the
  same rule.
* BC4 block  = red0:u8 | red1:u8 | index_word:u48le, sixteen 3-bit indices,
  pixel ``row*4+col`` at bit ``3*index``.  ``red0 > red1`` selects the 8-value
  interpolated mode.
* BC3 block  = 8-byte BC4(alpha) block, then 8-byte BC1(colour) block, per
  block (16 bytes / block).
* BC5 block  = 8-byte BC4(R) block, then 8-byte BC4(G) block, per block
  (16 bytes / block) -- i.e. the two channels are interleaved per 4x4 block,
  which is what a BC5_UNORM GPU texture actually is.
* Edges: if W or H is not a multiple of 4 the image is padded by *clamping*
  (replicating the last row / column); both the encoder and the reported byte
  count use the padded ``ceil(w/4) x ceil(h/4)`` block grid.

Quality
-------
BC1 endpoints come from a per-block principal component (PCA) fit: block mean,
dominant eigenvector of the 3x3 RGB covariance, extreme projections onto that
axis, then an inset refinement over a small set of (lo, hi) shrink factors
scored by the true squared error of the *quantised* palette.  BC4 uses min/max
plus a small refinement search over a handful of (outset / inset) endpoint
pairs, also scored by true squared error.

CLI
---
::

    python bcencode.py bc1 <in.png> <out.bc> [--mips N]
    python bcencode.py bc3 <in.png> <out.bc> [--mips N]
    python bcencode.py bc5 <in.png> <out.bc> [--mips N] [--from-normal]
    python bcencode.py decode <in.bc> <out.png> --format bc1|bc3|bc5 \
                              --width W --height H [--mips N]

A JSON sidecar ``<out.bc>.json`` is written next to every encoded blob:
``{"width":..,"height":..,"mips":..,"format":"DXT1|DXT5|BC5","bytes":..}``.

INTERPRETATIONS (points where the written spec left room)
---------------------------------------------------------
1. ``encode_bc5``/``encode_bc3`` grouping: the spec says "BC5 = encode_bc4(R)
   concatenated with encode_bc4(G)" while also fixing the block size at 16
   bytes.  Taken literally (whole-image concat) a BC5 texture could not be a
   valid 16-byte-per-block GPU format, so the implemented layout is the real
   hardware layout: per 4x4 block, R block then G block.  Same reasoning for
   BC3 (alpha block then colour block, per block).
2. ``pack_texture_blob(mips, array_count)``: ``mips`` is read as the flat list
   of mip blobs for *all* array slices in DDS/mip-major order (all arrays of
   mip 0, then all arrays of mip 1, ...) and is re-ordered into the tpac
   array-major order (all mips of array 0, then all mips of array 1, ...).
   With ``array_count == 1`` (the normal case) both orders are identical and
   the call is a plain concatenation.
3. ``mip_size(w, h, level)`` returns the pixel dimension tuple
   ``(max(1, w>>level), max(1, h>>level))``.  Pass ``fmt=`` to get the byte
   size of that level instead; ``mip_level_bytes()`` is the explicit helper.
4. RGB565 <-> RGB888 uses round-to-nearest on encode and the hardware
   bit-replication expansion ``r8 = (r5<<3)|(r5>>2)`` on decode, which is what
   ``directxtex``/``squish``/GPU samplers do.
5. Interpolated palette entries use the truncating integer arithmetic of the
   D3D BC1/BC4 specs, and the encoder scores candidates with those exact same
   integer palette values, so encode and decode are bit-consistent.
6. ``--from-normal`` on the ``bc5`` CLI sub-command means "input is a
   tangent-space RGB normal map": take R as X and G as Y and flip the green
   channel (``255 - G``) to convert the common OpenGL-style (Y-up) map into the
   DirectX-style (Y-down) convention Bannerlord expects.  Without the flag an
   RGB input simply donates its R and G channels unchanged.

Requires Python 3.13 + numpy.  Pillow is imported lazily and is only needed by
the CLI.
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

__all__ = [
    "block_bytes",
    "mip_size",
    "mip_level_bytes",
    "full_mip_count",
    "encode_bc1",
    "encode_bc3",
    "encode_bc4",
    "encode_bc5",
    "decode_bc1",
    "decode_bc3",
    "decode_bc4",
    "decode_bc5",
    "make_mips",
    "pack_texture_blob",
    "main",
]

# --------------------------------------------------------------------------
# format tables
# --------------------------------------------------------------------------

FORMAT_ALIASES = {
    "bc1": "BC1", "dxt1": "BC1", "dtx1": "BC1",
    "bc3": "BC3", "dxt5": "BC3", "dxt4": "BC3",
    "bc4": "BC4", "ati1": "BC4",
    "bc5": "BC5", "ati2": "BC5", "3dc": "BC5",
}

#: bytes per 4x4 block, keyed by canonical format name
BLOCK_BYTES = {"BC1": 8, "BC3": 16, "BC4": 8, "BC5": 16}

#: name Bannerlord/TpacTool prints for the format stored in the tpac
TPAC_FORMAT_NAME = {"BC1": "DXT1", "BC3": "DXT5", "BC4": "BC4", "BC5": "BC5"}

#: encoder memory chunking, in 4x4 blocks
BLOCKS_PER_CHUNK = 8192


def block_bytes(fmt) -> int:
    """Return the number of bytes a single 4x4 block occupies for *fmt*.

    Accepts ``"bc1"``/``"dxt1"``/``"bc3"``/``"dxt5"``/``"bc4"``/``"bc5"`` in any
    case, or the canonical ``"BC1"`` forms.  Raises ``ValueError`` otherwise.
    """
    if isinstance(fmt, str):
        key = FORMAT_ALIASES.get(fmt.strip().lower())
        if key is None:
            raise ValueError(f"unknown texture format: {fmt!r}")
        return BLOCK_BYTES[key]
    raise TypeError(f"format must be a string, got {type(fmt).__name__}")


def _canon(fmt) -> str:
    if isinstance(fmt, str):
        key = FORMAT_ALIASES.get(fmt.strip().lower())
        if key is None:
            raise ValueError(f"unknown texture format: {fmt!r}")
        return key
    raise TypeError(f"format must be a string, got {type(fmt).__name__}")


def mip_size(w: int, h: int, level: int, fmt=None):
    """Dimension of mip *level* of a *w* x *h* texture.

    Returns ``(max(1, w >> level), max(1, h >> level))`` -- note the shift is
    taken from the *original* dimensions and saturates at 1, so level 12 of a
    2048x2048 texture is 1x1, not 0x0.

    If *fmt* is given (e.g. ``"DXT1"``) the block-compressed **byte** size of
    that level is returned instead::

        ceil(mw/4) * ceil(mh/4) * block_bytes(fmt)
    """
    if level < 0:
        raise ValueError("level must be >= 0")
    mw = max(1, int(w) >> int(level))
    mh = max(1, int(h) >> int(level))
    if fmt is None:
        return (mw, mh)
    return ((mw + 3) // 4) * ((mh + 3) // 4) * block_bytes(fmt)


def mip_level_bytes(w: int, h: int, level: int, fmt) -> int:
    """Block-compressed byte size of mip *level* for format *fmt*."""
    return mip_size(w, h, level, fmt=fmt)


def full_mip_count(w: int, h: int) -> int:
    """Length of the full mip chain: ``floor(log2(max(w, h))) + 1``."""
    m = max(1, int(w), int(h))
    return int(m).bit_length()  # == floor(log2(m)) + 1 for m >= 1


def chain_byte_size(w: int, h: int, fmt, mip_count: int | None = None) -> int:
    """Total size of a whole mip chain (all levels, no padding)."""
    n = full_mip_count(w, h) if mip_count is None else int(mip_count)
    return sum(mip_level_bytes(w, h, lv, fmt) for lv in range(n))


# --------------------------------------------------------------------------
# small helpers: 565 conversion and the D3D integer palettes
# --------------------------------------------------------------------------

def _pack565(rgb) -> np.ndarray:
    """(..., 3) values in 0..255 -> (...) uint16 RGB565 codes.

    Round to nearest (``(v*31+127)//255``) rather than truncating, which pairs
    exactly with the bit-replication expansion used on decode.
    """
    v = np.clip(np.rint(np.asarray(rgb, dtype=np.float64)), 0.0, 255.0)
    v = v.astype(np.int32)
    r5 = (v[..., 0] * 31 + 127) // 255
    g6 = (v[..., 1] * 63 + 127) // 255
    b5 = (v[..., 2] * 31 + 127) // 255
    return ((r5.astype(np.uint16) << 11)
            | (g6.astype(np.uint16) << 5)
            | b5.astype(np.uint16))


def _expand565(code) -> np.ndarray:
    """(...) uint16 RGB565 codes -> (..., 3) int32 RGB888 (bit replication)."""
    c = np.asarray(code, dtype=np.uint16)
    r5 = (c >> 11) & 0x1F
    g6 = (c >> 5) & 0x3F
    b5 = c & 0x1F
    r = ((r5 << 3) | (r5 >> 2)).astype(np.int32)
    g = ((g6 << 2) | (g6 >> 4)).astype(np.int32)
    b = ((b5 << 3) | (b5 >> 2)).astype(np.int32)
    return np.stack([r, g, b], axis=-1)


def _bc1_palette_codes(c0, c1) -> np.ndarray:
    """4-colour BC1 palette for ``c0 > c1`` codes -> (..., 4, 3) float32."""
    e0 = _expand565(c0)                       # (..., 3) int32
    e1 = _expand565(c1)
    p2 = (2 * e0 + e1) // 3
    p3 = (e0 + 2 * e1) // 3
    pal = np.stack([e0, e1, p2, p3], axis=-2)
    return pal.astype(np.float32)


def _bc4_palette(r0, r1) -> np.ndarray:
    """Palettes for BC4/BC4-alpha blocks.

    ``r0``/``r1`` broadcast to the same shape.  Returns ``(..., 8)`` int32.
    Where ``r0 > r1`` the 8-value interpolated mode is used, otherwise the
    6-value mode with an implicit 0 and 255.
    """
    r0 = np.asarray(r0, dtype=np.int32)
    r1 = np.asarray(r1, dtype=np.int32)
    eight = r0 > r1
    p2 = np.where(eight, (6 * r0 + 1 * r1) // 7, (4 * r0 + 1 * r1) // 5)
    p3 = np.where(eight, (5 * r0 + 2 * r1) // 7, (3 * r0 + 2 * r1) // 5)
    p4 = np.where(eight, (4 * r0 + 3 * r1) // 7, (2 * r0 + 3 * r1) // 5)
    p5 = np.where(eight, (3 * r0 + 4 * r1) // 7, (1 * r0 + 4 * r1) // 5)
    p6 = np.where(eight, (2 * r0 + 5 * r1) // 7, np.zeros_like(r0))
    p7 = np.where(eight, (1 * r0 + 6 * r1) // 7, np.full_like(r0, 255))
    return np.stack([r0, r1, p2, p3, p4, p5, p6, p7], axis=-1)


def _bc1_palette_full(c0, c1) -> np.ndarray:
    """Palette for decoding, honouring both the 4-colour and 3-colour modes."""
    e0 = _expand565(c0)
    e1 = _expand565(c1)
    four = (np.asarray(c0) > np.asarray(c1))
    p2 = np.where(four[..., None], (2 * e0 + e1) // 3, (e0 + e1) // 2)
    p3 = np.where(four[..., None], (e0 + 2 * e1) // 3, np.zeros_like(e0))
    return np.stack([e0, e1, p2, p3], axis=-2)


# --------------------------------------------------------------------------
# image <-> block reshaping (with edge clamping)
# --------------------------------------------------------------------------

def _clamp_pad(img: np.ndarray) -> np.ndarray:
    """Pad ``(H, W[, C])`` uint8 by replicating the last row/column to a
    multiple of 4 in both dimensions.  Returns the array unchanged if it is
    already aligned."""
    h, w = img.shape[0], img.shape[1]
    ph = (-h) % 4
    pw = (-w) % 4
    if ph == 0 and pw == 0:
        return img
    if img.ndim == 2:
        pads = ((0, ph), (0, pw))
    else:
        pads = ((0, ph), (0, pw)) + ((0, 0),) * (img.ndim - 2)
    return np.pad(img, pads, mode="edge")


def _to_blocks(img: np.ndarray) -> np.ndarray:
    """``(H, W, C)`` (already 4-aligned) -> ``(N, 16, C)`` with
    ``p = row*4 + col`` inside each 4x4 block, blocks in raster order."""
    h, w, c = img.shape
    return (img.reshape(h // 4, 4, w // 4, 4, c)
               .transpose(0, 2, 1, 3, 4)
               .reshape(-1, 16, c))


def _from_blocks(blocks: np.ndarray, ph: int, pw: int, c: int) -> np.ndarray:
    """``(N, 16, C)`` -> ``(ph, pw, C)`` (inverse of :func:`_to_blocks`)."""
    return (blocks.reshape(ph // 4, pw // 4, 4, 4, c)
                  .transpose(0, 2, 1, 3, 4)
                  .reshape(ph, pw, c))


def _as_image(img, channels_min: int, name: str) -> np.ndarray:
    a = np.asarray(img)
    if a.dtype != np.uint8:
        raise TypeError(f"{name} must be uint8, got {a.dtype}")
    if a.ndim == 2:
        a = a[:, :, None]
    if a.ndim != 3:
        raise ValueError(f"{name} must be (H, W, C), got shape {a.shape}")
    if a.shape[2] < channels_min:
        raise ValueError(
            f"{name} must have at least {channels_min} channels, got {a.shape[2]}")
    return np.ascontiguousarray(a)


# --------------------------------------------------------------------------
# BC1 encoding (also used for the colour half of BC3)
# --------------------------------------------------------------------------

#: (lo inset, hi inset) shrink factors applied along the principal axis
_BC1_SHRINK = (
    (0.00, 0.00),
    (0.02, 0.02),
    (0.05, 0.05),
    (0.08, 0.08),
    (0.12, 0.12),
    (0.18, 0.18),
    (0.25, 0.25),
    (0.05, 0.00),
    (0.00, 0.05),
    (0.12, 0.03),
    (0.03, 0.12),
)


def _bc1_indices(px: np.ndarray, c0: np.ndarray, c1: np.ndarray) -> np.ndarray:
    """Nearest-colour indices ``(N, 16)`` uint8 for a 4-colour palette."""
    pal = _bc1_palette_codes(c0, c1)                  # (N, 4, 3) float32
    d = px[:, :, None, :] - pal[:, None, :, :]        # (N, 16, 4, 3)
    return np.einsum("npkc,npkc->npk", d, d).argmin(axis=2).astype(np.uint8)


def _encode_bc1_blocks(px: np.ndarray) -> np.ndarray:
    """``px``: ``(N, 16, 3)`` uint8 -> ``(N, 8)`` uint8 BC1 blocks."""
    n = px.shape[0]
    x = px.astype(np.float32)
    mean = x.mean(axis=1)                                # (N, 3)
    cen = x - mean[:, None, :]                           # (N, 16, 3)
    cov = np.einsum("npc,npd->ncd", cen, cen) / 16.0     # (N, 3, 3)

    # dominant principal axis; eigh returns ascending eigenvalues so the last
    # eigenvector is the direction of greatest variance.
    _evals, evecs = np.linalg.eigh(cov)
    axis = np.nan_to_num(evecs[:, :, 2], nan=1.0, posinf=1.0, neginf=-1.0)
    t = np.einsum("npc,nc->np", cen, axis)               # (N, 16)
    t_lo = t.min(axis=1)
    t_hi = t.max(axis=1)
    p_lo = np.clip(mean + t_lo[:, None] * axis, 0.0, 255.0)
    p_hi = np.clip(mean + t_hi[:, None] * axis, 0.0, 255.0)
    span = p_hi - p_lo

    best_err = None
    best_c0 = None
    best_c1 = None
    for s_lo, s_hi in _BC1_SHRINK:
        e0 = np.clip(p_lo + s_lo * span, 0.0, 255.0)
        e1 = np.clip(p_hi - s_hi * span, 0.0, 255.0)
        q0 = _pack565(e0)
        q1 = _pack565(e1)
        # order the pair descending: the 4-colour palette as a *set* is
        # unchanged by the swap, so the error is unaffected.
        hi = np.maximum(q0, q1)
        lo = np.minimum(q0, q1)
        pal = _bc1_palette_codes(hi, lo)                 # (N, 4, 3)
        d = x[:, :, None, :] - pal[:, None, :, :]
        err = np.einsum("npkc,npkc->npk", d, d).min(axis=2).sum(axis=1)
        if best_err is None:
            best_err, best_c0, best_c1 = err, hi, lo
        else:
            upd = err < best_err
            best_err = np.where(upd, err, best_err)
            best_c0 = np.where(upd, hi, best_c0)
            best_c1 = np.where(upd, lo, best_c1)

    # enforce the strict c0 > c1 ordering required for opaque 4-colour mode
    eq = best_c0 == best_c1
    if np.any(eq):
        c1_new = np.where(best_c1 > 0, best_c1 - 1, best_c1)
        c0_new = np.where(best_c1 > 0, best_c0, best_c0 + 1)
        best_c0 = np.where(eq, c0_new, best_c0)
        best_c1 = np.where(eq, c1_new, best_c1)

    idx = _bc1_indices(x, best_c0, best_c1)              # (N, 16)
    shifts = (2 * np.arange(16, dtype=np.uint32))[None, :]
    words = (idx.astype(np.uint32) << shifts).sum(axis=1)

    out = np.empty((n, 8), dtype=np.uint8)
    out[:, 0] = best_c0 & 0xFF
    out[:, 1] = (best_c0 >> 8) & 0xFF
    out[:, 2] = best_c1 & 0xFF
    out[:, 3] = (best_c1 >> 8) & 0xFF
    out[:, 4] = words & 0xFF
    out[:, 5] = (words >> 8) & 0xFF
    out[:, 6] = (words >> 16) & 0xFF
    out[:, 7] = (words >> 24) & 0xFF
    return out


def _encode_bc1_chan(rgb: np.ndarray) -> np.ndarray:
    """``(H, W, 3)`` uint8 -> ``(N, 8)`` uint8 BC1 blocks (padded grid)."""
    padded = _clamp_pad(rgb)
    blocks = _to_blocks(padded)
    chunks = []
    for i in range(0, blocks.shape[0], BLOCKS_PER_CHUNK):
        chunks.append(_encode_bc1_blocks(blocks[i:i + BLOCKS_PER_CHUNK]))
    if not chunks:
        return np.empty((0, 8), dtype=np.uint8)
    return np.concatenate(chunks, axis=0)


def encode_bc1(rgba: np.ndarray) -> bytes:
    """``(H, W, 4)`` uint8 RGBA -> opaque BC1 bytes (8 bytes / 4x4 block).

    The alpha channel is ignored; use :func:`encode_bc3` when alpha matters.
    """
    img = _as_image(rgba, 3, "rgba")
    return _encode_bc1_chan(np.ascontiguousarray(img[:, :, :3])).tobytes()


# --------------------------------------------------------------------------
# BC4 encoding (channel coder, also the alpha half of BC3 and both halves of BC5)
# --------------------------------------------------------------------------

#: (lo shift, hi shift) applied to (min, max): negative values expand outward
_BC4_REFINE = (
    (0, 0),
    (0, 1), (1, 0), (1, 1), (0, 2), (2, 0), (2, 1), (1, 2), (0, 3), (3, 0),
    (-1, -1), (-1, 0), (0, -1), (-2, -2),
)


def _encode_bc4_blocks(px: np.ndarray) -> np.ndarray:
    """``px``: ``(N, 16)`` uint8 -> ``(N, 8)`` uint8 BC4 blocks."""
    n = px.shape[0]
    x = px.astype(np.float32)
    mn = x.min(axis=1)                                   # (N,)
    mx = x.max(axis=1)

    best_err = None
    best_r0 = None
    best_r1 = None
    for d_lo, d_hi in _BC4_REFINE:
        r0 = np.clip(mx - d_lo, 0.0, 255.0)
        r1 = np.clip(mn + d_hi, 0.0, 255.0)
        valid = r0 > r1
        pal = _bc4_palette(r0.astype(np.int32), r1.astype(np.int32))
        d = x[:, :, None] - pal.astype(np.float32)[:, None, :]
        err = np.einsum("npk,npk->np", d, d).min(axis=1)
        err = np.where(valid, err, np.inf)
        if best_err is None:
            best_err, best_r0, best_r1 = err, r0, r1
        else:
            upd = err < best_err
            best_err = np.where(upd, err, best_err)
            best_r0 = np.where(upd, r0, best_r0)
            best_r1 = np.where(upd, r1, best_r1)

    # every real block has at least the (0, 0) candidate valid unless it is
    # perfectly flat, and the (-1, -1) outset candidate covers the flat case.
    bad = ~np.isfinite(best_err)
    if np.any(bad):
        v = mx
        r0f = np.where(v < 255, v + 1.0, 255.0)
        r1f = np.where(v < 255, v, 254.0)
        best_r0 = np.where(bad, r0f, best_r0)
        best_r1 = np.where(bad, r1f, best_r1)

    r0i = np.rint(best_r0).astype(np.int32)
    r1i = np.rint(best_r1).astype(np.int32)
    pal = _bc4_palette(r0i, r1i).astype(np.float32)      # (N, 8)
    d = x[:, :, None] - pal[:, None, :]
    idx = (d * d).argmin(axis=2).astype(np.uint8)        # (N, 16)

    shifts = (3 * np.arange(16, dtype=np.uint64))[None, :]
    words = (idx.astype(np.uint64) << shifts).sum(axis=1)   # 48-bit values

    out = np.empty((n, 8), dtype=np.uint8)
    out[:, 0] = r0i & 0xFF
    out[:, 1] = r1i & 0xFF
    for byte in range(6):
        out[:, 2 + byte] = (words >> (8 * byte)) & 0xFF
    return out


def _channel_blocks(chan: np.ndarray) -> np.ndarray:
    """``(H, W)`` uint8 -> ``(N, 16)`` uint8 blocks on the padded grid."""
    padded = _clamp_pad(chan)
    return _to_blocks(padded[:, :, None])[:, :, 0]


def encode_bc4(chan: np.ndarray) -> bytes:
    """``(H, W)`` uint8 -> BC4 bytes (8 bytes / 4x4 block)."""
    a = np.asarray(chan)
    if a.ndim == 3 and a.shape[2] == 1:
        a = a[:, :, 0]
    if a.ndim != 2:
        raise ValueError(f"chan must be (H, W), got shape {a.shape}")
    if a.dtype != np.uint8:
        raise TypeError(f"chan must be uint8, got {a.dtype}")
    blocks = _channel_blocks(np.ascontiguousarray(a))
    chunks = [_encode_bc4_blocks(blocks[i:i + BLOCKS_PER_CHUNK])
              for i in range(0, blocks.shape[0], BLOCKS_PER_CHUNK)]
    if not chunks:
        return b""
    return np.concatenate(chunks, axis=0).tobytes()


# --------------------------------------------------------------------------
# BC3 / BC5
# --------------------------------------------------------------------------

def encode_bc3(rgba: np.ndarray) -> bytes:
    """``(H, W, 4)`` uint8 RGBA -> BC3 bytes (16 bytes / 4x4 block).

    Layout per block: 8-byte BC4(alpha) block then 8-byte BC1(colour) block.
    A 3-channel input is accepted and treated as fully opaque.
    """
    img = _as_image(rgba, 3, "rgba")
    colour = _encode_bc1_chan(np.ascontiguousarray(img[:, :, :3]))
    if img.shape[2] >= 4:
        alpha_chan = np.ascontiguousarray(img[:, :, 3])
    else:
        alpha_chan = np.full(img.shape[:2], 255, dtype=np.uint8)
    ab = _channel_blocks(alpha_chan)
    alpha = np.concatenate(
        [_encode_bc4_blocks(ab[i:i + BLOCKS_PER_CHUNK])
         for i in range(0, ab.shape[0], BLOCKS_PER_CHUNK)], axis=0)
    out = np.concatenate([alpha, colour], axis=1)        # (N, 16)
    return out.tobytes()


def encode_bc5(rg: np.ndarray) -> bytes:
    """``(H, W, 2)`` uint8 -> BC5 bytes (16 bytes / 4x4 block).

    Layout per block: 8-byte BC4(R) block then 8-byte BC4(G) block, i.e. the
    two channels are interleaved per 4x4 block exactly as a BC5 GPU texture.
    """
    img = _as_image(rg, 2, "rg")
    r = np.ascontiguousarray(img[:, :, 0])
    g = np.ascontiguousarray(img[:, :, 1])
    outs = []
    for chan in (r, g):
        blk = _channel_blocks(chan)
        outs.append(np.concatenate(
            [_encode_bc4_blocks(blk[i:i + BLOCKS_PER_CHUNK])
             for i in range(0, blk.shape[0], BLOCKS_PER_CHUNK)], axis=0))
    out = np.concatenate([outs[0], outs[1]], axis=1)     # (N, 16)
    return out.tobytes()


# --------------------------------------------------------------------------
# decoders
# --------------------------------------------------------------------------

def _block_grid(w: int, h: int):
    bw = (int(w) + 3) // 4
    bh = (int(h) + 3) // 4
    return bw, bh, bw * bh


def _check_len(data, need: int, what: str) -> None:
    if len(data) < need:
        raise ValueError(
            f"{what}: need {need} bytes for the block grid, got {len(data)}")


def _decode_bc1_blocks(blk: np.ndarray) -> np.ndarray:
    """``(N, 8)`` uint8 -> ``(N, 16, 4)`` uint8 RGBA."""
    c0 = blk[:, 0].astype(np.uint16) | (blk[:, 1].astype(np.uint16) << 8)
    c1 = blk[:, 2].astype(np.uint16) | (blk[:, 3].astype(np.uint16) << 8)
    words = (blk[:, 4].astype(np.uint32)
             | (blk[:, 5].astype(np.uint32) << 8)
             | (blk[:, 6].astype(np.uint32) << 16)
             | (blk[:, 7].astype(np.uint32) << 24))
    shifts = (2 * np.arange(16, dtype=np.uint32))[None, :]
    idx = ((words[:, None] >> shifts) & 0x3).astype(np.int64)   # (N, 16)

    pal = _bc1_palette_full(c0, c1).astype(np.int32)            # (N, 4, 3)
    rgba = np.take_along_axis(pal, idx[:, :, None], axis=1)     # (N, 16, 3)
    four = (c0 > c1)[:, None, None]
    alpha = np.where(four, 255, np.where(idx[:, :, None] == 3, 0, 255))
    return np.concatenate([rgba.astype(np.uint8), alpha.astype(np.uint8)],
                          axis=2)


def _decode_bc4_blocks(blk: np.ndarray) -> np.ndarray:
    """``(N, 8)`` uint8 -> ``(N, 16)`` uint8."""
    r0 = blk[:, 0].astype(np.int32)
    r1 = blk[:, 1].astype(np.int32)
    words = np.zeros(blk.shape[0], dtype=np.uint64)
    for byte in range(6):
        words |= blk[:, 2 + byte].astype(np.uint64) << (8 * byte)
    shifts = (3 * np.arange(16, dtype=np.uint64))[None, :]
    idx = ((words[:, None] >> shifts) & 0x7).astype(np.int64)   # (N, 16)
    pal = _bc4_palette(r0, r1)                                  # (N, 8)
    return np.take_along_axis(pal, idx, axis=1).astype(np.uint8)


def _finish(blocks_flat: np.ndarray, w: int, h: int, c: int) -> np.ndarray:
    bw, bh, _n = _block_grid(w, h)
    img = _from_blocks(blocks_flat, bh * 4, bw * 4, c)
    return np.ascontiguousarray(img[:h, :w])


def decode_bc1(data: bytes, w: int, h: int) -> np.ndarray:
    """BC1 bytes -> ``(H, W, 4)`` uint8 RGBA (alpha is 0/255)."""
    _bw, _bh, n = _block_grid(w, h)
    _check_len(data, n * 8, "decode_bc1")
    blk = np.frombuffer(bytes(data[:n * 8]), dtype=np.uint8).reshape(n, 8)
    return _finish(_decode_bc1_blocks(blk), w, h, 4)


def decode_bc3(data: bytes, w: int, h: int) -> np.ndarray:
    """BC3 bytes -> ``(H, W, 4)`` uint8 RGBA."""
    _bw, _bh, n = _block_grid(w, h)
    _check_len(data, n * 16, "decode_bc3")
    blk = np.frombuffer(bytes(data[:n * 16]), dtype=np.uint8).reshape(n, 16)
    alpha = _decode_bc4_blocks(blk[:, 0:8])
    rgb = _decode_bc1_blocks(blk[:, 8:16])[:, :, :3]
    out = np.concatenate([rgb, alpha[:, :, None]], axis=2)
    return _finish(out, w, h, 4)


def decode_bc4(data: bytes, w: int, h: int) -> np.ndarray:
    """BC4 bytes -> ``(H, W)`` uint8."""
    _bw, _bh, n = _block_grid(w, h)
    _check_len(data, n * 8, "decode_bc4")
    blk = np.frombuffer(bytes(data[:n * 8]), dtype=np.uint8).reshape(n, 8)
    return _finish(_decode_bc4_blocks(blk)[:, :, None], w, h, 1)[:, :, 0]


def decode_bc5(data: bytes, w: int, h: int) -> np.ndarray:
    """BC5 bytes -> ``(H, W, 2)`` uint8 (R = X, G = Y)."""
    _bw, _bh, n = _block_grid(w, h)
    _check_len(data, n * 16, "decode_bc5")
    blk = np.frombuffer(bytes(data[:n * 16]), dtype=np.uint8).reshape(n, 16)
    r = _decode_bc4_blocks(blk[:, 0:8])
    g = _decode_bc4_blocks(blk[:, 8:16])
    return _finish(np.stack([r, g], axis=2), w, h, 2)


# --------------------------------------------------------------------------
# mip generation and tpac packing
# --------------------------------------------------------------------------

def _halve(img: np.ndarray) -> np.ndarray:
    """Box-filter a ``(H, W[, C])`` uint8 image down by 2 with rounding."""
    h, w = img.shape[0], img.shape[1]
    nw = max(1, w >> 1)
    nh = max(1, h >> 1)
    if w == 1 and h == 1:
        return img.copy()
    if w == 1:
        src = img[:nh * 2].astype(np.uint16)
        out = (src[0::2] + src[1::2] + 1) // 2
    elif h == 1:
        src = img[:, :nw * 2].astype(np.uint16)
        out = (src[:, 0::2] + src[:, 1::2] + 1) // 2
    else:
        src = img[:nh * 2, :nw * 2].astype(np.uint16)
        out = (src[0::2, 0::2] + src[0::2, 1::2]
               + src[1::2, 0::2] + src[1::2, 1::2] + 2) // 4
    return np.ascontiguousarray(out.astype(np.uint8))


def make_mips(img: np.ndarray, mip_count: int) -> list:
    """Return ``mip_count`` levels of *img*, level 0 being *img* itself.

    Each subsequent level is a 2x2 box filter of the previous one with
    ``max(1, x >> 1)`` dimensions, so the chain saturates at 1x1.  Asking for
    more levels than the natural chain yields extra 1x1 levels (which is what
    the ``level``-based formula in the tpac layout describes).
    """
    a = np.asarray(img)
    if a.dtype != np.uint8:
        raise TypeError(f"img must be uint8, got {a.dtype}")
    if a.ndim not in (2, 3):
        raise ValueError(f"img must be (H, W) or (H, W, C), got {a.shape}")
    n = int(mip_count)
    if n < 1:
        raise ValueError("mip_count must be >= 1")
    out = [a]
    cur = a
    for _ in range(n - 1):
        cur = _halve(cur)
        out.append(cur)
    return out


def pack_texture_blob(mips, array_count: int = 1) -> bytes:
    """Pack mip blobs into the tpac pixel-blob layout.

    ``mips`` holds the raw block-compressed bytes for every array slice, laid
    out in DDS/mip-major order (all arrays of mip 0, then all arrays of mip 1,
    ...).  The tpac order is array-major (all mips of array 0, then all mips of
    array 1, ...), and that re-ordering is what this function performs.  With
    ``array_count == 1`` -- normally the case -- the two orders coincide and
    the result is a plain concatenation with no header and no padding.
    """
    ac = int(array_count)
    if ac < 1:
        raise ValueError("array_count must be >= 1")
    blobs = [bytes(m) for m in mips]
    if ac == 1:
        return b"".join(blobs)
    if len(blobs) % ac != 0:
        raise ValueError(
            f"mip blob count {len(blobs)} is not a multiple of array_count {ac}")
    chain = len(blobs) // ac
    out = bytearray()
    for arr in range(ac):
        for mip in range(chain):
            out += blobs[mip * ac + arr]
    return bytes(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

_CLI_ENCODE = {
    "bc1": ("BC1", "DXT1"),
    "bc3": ("BC3", "DXT5"),
    "bc5": ("BC5", "BC5"),
}
_CLI_DECODE = {"bc1": "BC1", "bc3": "BC3", "bc5": "BC5"}


def _load_png(path: str) -> np.ndarray:
    from PIL import Image  # lazy: the codec itself does not need Pillow

    with Image.open(path) as im:
        im = im.convert("RGBA")
        return np.array(im, dtype=np.uint8)


def _save_png(path: str, arr: np.ndarray) -> None:
    from PIL import Image

    Image.fromarray(arr).save(path)


def _write_sidecar(bc_path: str, width: int, height: int, mips: int,
                   fmt_label: str, nbytes: int) -> str:
    side = bc_path + ".json"
    with open(side, "w", encoding="utf-8") as fh:
        json.dump({"width": int(width), "height": int(height), "mips": int(mips),
                   "format": fmt_label, "bytes": int(nbytes)}, fh, indent=2)
        fh.write("\n")
    return side


def _cli_encode(args) -> int:
    fmt, label = _CLI_ENCODE[args.cmd]
    rgba = _load_png(args.src)
    h, w = rgba.shape[:2]

    if args.mips is None:
        n_mips = full_mip_count(w, h)
    else:
        n_mips = int(args.mips)
        if n_mips < 1:
            raise SystemExit("--mips must be >= 1")

    if fmt == "BC1":
        src = np.ascontiguousarray(rgba[:, :, :3])
        mips = make_mips(src, n_mips)
        blobs = [encode_bc1(m) for m in mips]
    elif fmt == "BC3":
        mips = make_mips(rgba, n_mips)
        blobs = [encode_bc3(m) for m in mips]
    else:  # BC5
        if args.from_normal:
            g = (255 - rgba[:, :, 1].astype(np.uint16)).astype(np.uint8)
        else:
            g = rgba[:, :, 1]
        src = np.ascontiguousarray(np.stack([rgba[:, :, 0], g], axis=2))
        mips = make_mips(src, n_mips)
        blobs = [encode_bc5(m) for m in mips]

    blob = pack_texture_blob(blobs, array_count=1)
    with open(args.dst, "wb") as fh:
        fh.write(blob)
    side = _write_sidecar(args.dst, w, h, n_mips, label, len(blob))

    expected = chain_byte_size(w, h, fmt, n_mips)
    print(f"{args.cmd}: {args.src} {w}x{h} -> {args.dst}")
    print(f"  format={label} mips={n_mips} bytes={len(blob)} "
          f"(formula={expected})")
    print(f"  sidecar={side}")
    if len(blob) != expected:
        print("  ERROR: blob length does not match the mip-size formula",
              file=sys.stderr)
        return 2
    return 0


def _cli_decode(args) -> int:
    with open(args.src, "rb") as fh:
        data = fh.read()
    fmt = _CLI_DECODE[args.format]
    w, h = int(args.width), int(args.height)
    n_mips = full_mip_count(w, h) if args.mips is None else int(args.mips)

    first = mip_level_bytes(w, h, 0, fmt)
    if len(data) < first:
        raise SystemExit(
            f"{args.src}: need at least {first} bytes for mip 0, got {len(data)}")
    if args.mips is not None:
        expected = chain_byte_size(w, h, fmt, n_mips)
        if len(data) != expected:
            raise SystemExit(
                f"{args.src}: expected {expected} bytes for {n_mips} mips of "
                f"{w}x{h} {fmt}, got {len(data)}")

    if fmt == "BC1":
        img = decode_bc1(data, w, h)[:, :, :3]
    elif fmt == "BC3":
        img = decode_bc3(data, w, h)
    else:
        rg = decode_bc5(data, w, h)
        img = np.dstack([rg, np.full(rg.shape[:2], 255, dtype=np.uint8)])
    _save_png(args.dst, img)

    chain = chain_byte_size(w, h, fmt, n_mips)
    print(f"decode: {args.src} ({len(data)} bytes) -> {args.dst}")
    print(f"  format={fmt} size={w}x{h} mips={n_mips} "
          f"mip0={first} chain={chain} written_mip=0")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bcencode.py",
        description="Encode images into Bannerlord .tpac block-compressed "
                    "texture blobs (BC1/DXT1, BC3/DXT5, BC5) and decode them "
                    "back.")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("bc1", "bc3", "bc5"):
        sp = sub.add_parser(name, help=f"encode to {_CLI_ENCODE[name][1]}")
        sp.add_argument("src", help="input PNG")
        sp.add_argument("dst", help="output .bc blob")
        sp.add_argument("--mips", type=int, default=None,
                        help="number of mip levels (default: full chain)")
        if name == "bc5":
            sp.add_argument("--from-normal", action="store_true",
                            help="treat the input as a tangent-space normal map "
                                 "and flip the G channel (OpenGL -> DirectX)")
        sp.set_defaults(func=_cli_encode)

    sp = sub.add_parser("decode", help="decode a .bc blob to PNG (mip 0)")
    sp.add_argument("src", help="input .bc blob")
    sp.add_argument("dst", help="output PNG")
    sp.add_argument("--format", required=True, choices=["bc1", "bc3", "bc5"])
    sp.add_argument("--width", type=int, required=True)
    sp.add_argument("--height", type=int, required=True)
    sp.add_argument("--mips", type=int, default=None,
                    help="number of mip levels stored in the blob; if given the "
                         "blob length is validated against it")
    sp.set_defaults(func=_cli_decode)
    return p


def main(argv=None) -> int:
    """CLI entry point.  Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
