"""RLPS wire protocol v1: constants and fixed binary layouts.

Normative description: ``docs/PROTOCOL.md``. All integers are little-endian (Luau ``buffer`` is little-endian).
The Luau mirror of this module is ``roblox/src/shared/RlpsProtocol.luau``; keep both in sync.
"""

from __future__ import annotations

import struct

VERSION = 1
CONTAINER_MAGIC = b"RLPS"

# Pixel formats of quantized tile data.
FMT_RGB565 = 1  # 2 bytes/pixel, little-endian u16 = r5 << 11 | g6 << 5 | b5
FMT_RGB888 = 2  # 3 bytes/pixel, bytes R, G, B
FMT_RGBA8 = 3  # 4 bytes/pixel, bytes R, G, B, A (lossless; clients copy rows without per-pixel work)
FMT_HYBRID = 4  # per-tile mode byte: RAW RGBA8 (lossless) or DCT YCbCr 4:2:0 macroblock; tile size 16, dims % 16 == 0
BYTES_PER_PIXEL = {FMT_RGB565: 2, FMT_RGB888: 3, FMT_RGBA8: 4, FMT_HYBRID: 4}

# FMT_HYBRID tile entry modes (first byte of each tile's data).
TILE_MODE_RAW = 0  # mode u8 | 16*16*4 RGBA8 bytes
TILE_MODE_DCT = 1  # mode u8 | quality u8 | 384 int16 zigzag coefficients (rlps.dct)
TILE_MODE_COPY = 2  # mode u8 | dx i16 | dy i16: copy the 16x16 block at (x0+dx, y0+dy) of the *previous* picture
#                     (scrolling, moved windows); only in parts flagged PFLAG_REF
TILE_MODE_DCT2 = 3  # mode u8 | quality u8 | 384 int16: a DCT macroblock at *half* resolution covering the 32x32 area of
#                     this tile and its right, lower and lower-right neighbours (pixel-doubled); those three tiles are
#                     not listed. For large moving areas (video): a quarter of the client's DCT work and bytes
HYBRID_TILE = 16
HYBRID_RAW_ENTRY = 1 + 16 * 16 * 4  # 1025
HYBRID_DCT_ENTRY = 2 + 384 * 2  # 770
HYBRID_COPY_ENTRY = 5

# Part payload compression.
COMP_NONE = 0
COMP_ZSTD = 1  # one standard zstd frame with content size (EncodingService Zstd)

# Sharing state carried by every container.
STATE_STOPPED = 0  # owner is not sharing: no pixels exist; parts must be empty
STATE_LIVE = 1

# Container flags.
CFLAG_KEYFRAME = 0x01  # parts cover every tile; apply without a base frame
CFLAG_UNCHANGED = 0x02  # no frame newer than ``after``; no parts

# Part flags.
PFLAG_KEYFRAME = 0x01
PFLAG_REF = 0x02  # the frame copies from the picture as it was before this frame (set on every part of it)

ALLOWED_TILE_SIZES = (8, 16, 32)
DEFAULT_TILE_SIZE = 16
MAX_DIM = 1024  # EditableImage maximum (F-0001)
MAX_PARTS = 512
MAX_PART_RAW_BYTES = 256 * 1024  # decompressed payload cap per part (decoder-enforced)
DEFAULT_PART_RAW_BYTES = 32 * 1024  # encoder target: keeps RemoteEvent messages small
MAX_CONTAINER_BYTES = 4 * 1024 * 1024

# Bundle = the HTTP response body: several containers of one chain, oldest first, with capture-time offsets so the
# Roblox server can play them out at their original spacing.
# magic "RLPB", version u8, reserved u8, count u16, bodyLength u32 | count x (tOffsetMs u32, length u32, container)
BUNDLE_MAGIC = b"RLPB"
BUNDLE_HEADER = struct.Struct("<4sBBHI")
BUNDLE_ENTRY = struct.Struct("<II")
MAX_BUNDLE_ENTRIES = 256
MAX_BUNDLE_BYTES = 16 * 1024 * 1024

# magic, version, state, flags, reserved, sessionId, seq, baseSeq, width, height, format, tileSize, partCount, bodyLength
CONTAINER_HEADER = struct.Struct("<4sBBBBIIIHHBBHI")
CONTAINER_HEADER_SIZE = CONTAINER_HEADER.size  # 32

# version, compression, format, flags, tileSize, reserved, partIndex, partCount, width, height, tileCount,
# sessionId, seq, baseSeq, rawLength, compLength
PART_HEADER = struct.Struct("<BBBBBBHHHHHIIIII")
PART_HEADER_SIZE = PART_HEADER.size  # 36

assert CONTAINER_HEADER_SIZE == 32 and PART_HEADER_SIZE == 36 and BUNDLE_HEADER.size == 12


def max_raw_per_tile(fmt: int, tile_size: int) -> int:
    """Upper bound of one tile's bytes in a decompressed part payload, including its u16 index."""
    if fmt == FMT_HYBRID:
        return 2 + HYBRID_RAW_ENTRY
    return 2 + tile_size * tile_size * BYTES_PER_PIXEL[fmt]


def tiles_per_axis(width: int, height: int, tile_size: int) -> tuple[int, int]:
    """Number of tile columns and rows (edge tiles are clipped, not padded)."""
    return (width + tile_size - 1) // tile_size, (height + tile_size - 1) // tile_size


def tile_rect(index: int, width: int, height: int, tile_size: int) -> tuple[int, int, int, int]:
    """Return (x0, y0, w, h) of tile ``index`` (row-major: index = ty * tilesX + tx), clipped to the frame."""
    tiles_x, _ = tiles_per_axis(width, height, tile_size)
    ty, tx = divmod(index, tiles_x)
    x0, y0 = tx * tile_size, ty * tile_size
    return x0, y0, min(tile_size, width - x0), min(tile_size, height - y0)


class ProtocolError(ValueError):
    """Malformed, truncated, oversized or inconsistent RLPS data."""
