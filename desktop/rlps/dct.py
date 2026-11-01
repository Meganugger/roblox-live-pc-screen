"""DCT tile coding for RLPS hybrid frames (pixel format FMT_HYBRID): one 16x16 tile = one macroblock.

A DCT tile is YCbCr 4:2:0 (four 8x8 luma blocks + one 8x8 Cb + one 8x8 Cr), JPEG-style quantization at one of
``len(QUALITIES)`` quality steps, coefficients stored as 6 x 64 little-endian int16 in zigzag order (trailing zeros
are left to zstd). Encoding uses a float forward DCT; **decoding is pure integer arithmetic** so that this module and
``roblox/src/shared/RlpsDecoder.luau`` produce bit-identical pixels (the encoder keeps the decoder's reconstruction).

Entry layout (inside a part payload, see docs/PROTOCOL.md):  mode u8 = 1 | quality u8 | 384 x int16 coefficients
"""

from __future__ import annotations

import numpy as np

from . import protocol as P

COEFS = 6 * 64
ENTRY_BYTES = 2 + COEFS * 2  # 770

# IJG quality values selectable per tile (index = the quality byte). Higher index = better.
QUALITIES = (10, 20, 30, 40, 50, 60, 70, 75, 80, 85, 88, 90, 92, 94, 96, 98)

ZIGZAG = np.array([
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
], np.int64)

# ITU T.81 Annex K tables (row-major).
BASE_LUMA = np.array([
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
], np.int64)
BASE_CHROMA = np.array([
    17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
], np.int64)

IDCT_SHIFT = 24
IDCT_ROUND = 1 << (IDCT_SHIFT - 1)


def _dct_matrix() -> np.ndarray:
    c = np.zeros((8, 8))
    for k in range(8):
        a = np.sqrt(1 / 8) if k == 0 else np.sqrt(2 / 8)
        for n in range(8):
            c[k, n] = a * np.cos(np.pi * (2 * n + 1) * k / 16)
    return c


C = _dct_matrix()
M = np.round(C * 4096).astype(np.int64)  # integer basis shared with the Luau decoder (RlpsDct.M)
# Row-major vec(Mt @ D @ M) = kron(Mt, Mt) @ vec(D): one (blocks x 64) @ (64 x 64) BLAS product for all blocks.
# Entries <= 2009^2 and |D| <= 32767 * 255, so each sum of 64 products stays an exact integer below 2^53.
_K_IDCT = np.kron(M.T, M.T).astype(np.float64).T
_K_FDCT = np.kron(C, C).T  # forward (float, encoder only): vec(C @ X @ C.T) = kron(C, C) @ vec(X)
_K_IDCT_ZZ = _K_IDCT[ZIGZAG]  # input rows permuted to zigzag order


def quant_table(base: np.ndarray, quality_index: int) -> np.ndarray:
    """IJG scaling, integers only (mirrored in Luau): q = clamp((base * s + 50) // 100, 1, 255)."""
    q = QUALITIES[quality_index]
    s = 5000 // q if q < 50 else 200 - 2 * q
    return np.clip((base * s + 50) // 100, 1, 255)


_TABLES = [(quant_table(BASE_LUMA, i), quant_table(BASE_CHROMA, i)) for i in range(len(QUALITIES))]
# dequantization multipliers per quality index, in zigzag order (decoder side)
_TAB_ZZ_LUMA = np.stack([t[0][ZIGZAG] for t in _TABLES]).astype(np.float64)
_TAB_ZZ_CHROMA = np.stack([t[1][ZIGZAG] for t in _TABLES]).astype(np.float64)


def tables(quality_index: int) -> tuple[np.ndarray, np.ndarray]:
    return _TABLES[quality_index]


# ------------------------------------------------------------------------------------------------- encoding


def _to_blocks(tiles_rgb: np.ndarray) -> np.ndarray:
    """(T, 16, 16, 3) uint8 RGB -> (T, 6, 8, 8) float samples minus 128 (Y0 Y1 Y2 Y3 Cb Cr)."""
    rgb = tiles_rgb.astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128.0
    cr = 0.5 * r - 0.418688 * g - 0.081312 * b + 128.0
    t = tiles_rgb.shape[0]
    cb = cb.reshape(t, 8, 2, 8, 2).mean(axis=(2, 4))
    cr = cr.reshape(t, 8, 2, 8, 2).mean(axis=(2, 4))
    out = np.empty((t, 6, 8, 8), np.float32)
    out[:, 0] = y[:, :8, :8]
    out[:, 1] = y[:, :8, 8:]
    out[:, 2] = y[:, 8:, :8]
    out[:, 3] = y[:, 8:, 8:]
    out[:, 4] = cb
    out[:, 5] = cr
    return out - 128.0


def forward_coefficients(tiles_rgb: np.ndarray) -> np.ndarray:
    """(T, 16, 16, 3) RGB -> (T, 6, 64) float DCT coefficients in row-major (not zigzag) order."""
    blocks = _to_blocks(tiles_rgb).astype(np.float64).reshape(-1, 64)
    return (blocks @ _K_FDCT).reshape(tiles_rgb.shape[0], 6, 64)


def quantize(coefs: np.ndarray, quality_index: int) -> np.ndarray:
    """(T, 6, 64) float -> (T, 6, 64) int16 quantized coefficients in **zigzag** order."""
    luma, chroma = tables(quality_index)
    q = np.empty_like(coefs)
    q[:, :4] = coefs[:, :4] / luma
    q[:, 4:] = coefs[:, 4:] / chroma
    q = np.rint(q)
    return np.clip(q, -32768, 32767).astype(np.int16)[:, :, ZIGZAG]


def downscale2(blocks_rgb: np.ndarray) -> np.ndarray:
    """(G, 32, 32, 3) uint8 -> (G, 16, 16, 3) uint8: 2x2 box average, rounded half up (TILE_MODE_DCT2 source)."""
    b = blocks_rgb.astype(np.uint16)
    s = b[:, 0::2, 0::2] + b[:, 1::2, 0::2] + b[:, 0::2, 1::2] + b[:, 1::2, 1::2]
    return ((s + 2) >> 2).astype(np.uint8)


def upscale2(tiles: np.ndarray) -> np.ndarray:
    """(G, 16, 16, C) -> (G, 32, 32, C): every pixel doubled in both directions (how clients draw TILE_MODE_DCT2)."""
    return np.repeat(np.repeat(tiles, 2, axis=1), 2, axis=2)


def pack_entries(qz: np.ndarray, quality_index: int, mode: int = P.TILE_MODE_DCT) -> list[bytes]:
    """One 770-byte entry per tile (``mode`` TILE_MODE_DCT or TILE_MODE_DCT2)."""
    head = bytes((mode, quality_index))
    body = qz.astype("<i2").reshape(qz.shape[0], -1)
    return [head + body[i].tobytes() for i in range(qz.shape[0])]


# ------------------------------------------------------------------------------------------------- decoding


def reconstruct(qz: np.ndarray, quality_indices: np.ndarray | int) -> np.ndarray:
    """Integer decode of (T, 6, 64) zigzag int16 coefficients -> (T, 16, 16, 4) uint8 RGBA (alpha 255).

    Bit-exact specification of the Luau decoder (RlpsDct.decodeTile): dequantize, ``(M^T D M + 2^23) >> 24``,
    +128 and clamp, then fixed-point YCbCr -> RGB with nearest chroma upsampling. Computed with float64 BLAS, which is
    exact here (all intermediates are integers below 2^53; see _K_IDCT)."""
    t = qz.shape[0]
    qi = np.broadcast_to(np.asarray(quality_indices), (t,))
    deq = qz.astype(np.float64)
    deq[:, :4] *= _TAB_ZZ_LUMA[qi][:, None, :]
    deq[:, 4:] *= _TAB_ZZ_CHROMA[qi][:, None, :]
    out = deq.reshape(-1, 64) @ _K_IDCT_ZZ  # rows indexed by zigzag position: no scatter needed
    out += IDCT_ROUND
    out *= 1.0 / (1 << IDCT_SHIFT)  # exact: power of two
    np.floor(out, out=out)
    out += 128
    np.clip(out, 0, 255, out=out)
    samples = out.astype(np.int32).reshape(t, 6, 8, 8)
    y = np.empty((t, 16, 16), np.int32)
    y[:, :8, :8] = samples[:, 0]
    y[:, :8, 8:] = samples[:, 1]
    y[:, 8:, :8] = samples[:, 2]
    y[:, 8:, 8:] = samples[:, 3]
    cb = np.repeat(np.repeat(samples[:, 4] - 128, 2, axis=1), 2, axis=2)
    cr = np.repeat(np.repeat(samples[:, 5] - 128, 2, axis=1), 2, axis=2)
    rgba = np.empty((t, 16, 16, 4), np.uint8)
    rgba[..., 0] = np.clip(y + ((91881 * cr + 32768) >> 16), 0, 255)
    rgba[..., 1] = np.clip(y - ((22554 * cb + 46802 * cr + 32768) >> 16), 0, 255)
    rgba[..., 2] = np.clip(y + ((116130 * cb + 32768) >> 16), 0, 255)
    rgba[..., 3] = 255
    return rgba


def decode_entry(entry: bytes) -> np.ndarray:
    """Reference decode of one DCT entry -> (16, 16, 4) RGBA (a DCT2 entry: its 16x16 samples, before doubling)."""
    if len(entry) != ENTRY_BYTES or entry[0] not in (P.TILE_MODE_DCT, P.TILE_MODE_DCT2):
        raise P.ProtocolError("bad DCT tile entry")
    qi = entry[1]
    if qi >= len(QUALITIES):
        raise P.ProtocolError("invalid DCT quality")
    qz = np.frombuffer(entry, dtype="<i2", offset=2).reshape(1, 6, 64)
    return reconstruct(qz, qi)[0]
