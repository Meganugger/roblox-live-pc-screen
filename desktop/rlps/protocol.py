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
BYTES_PER_PIXEL = {FMT_RGB565: 2, FMT_RGB888: 3}

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

ALLOWED_TILE_SIZES = (8, 16, 32)
DEFAULT_TILE_SIZE = 16
MAX_DIM = 1024  # EditableImage maximum (F-0001)
MAX_PARTS = 512
MAX_PART_RAW_BYTES = 256 * 1024  # decompressed payload cap per part (decoder-enforced)
DEFAULT_PART_RAW_BYTES = 32 * 1024  # encoder target: keeps RemoteEvent messages small
MAX_CONTAINER_BYTES = 4 * 1024 * 1024

# magic, version, state, flags, reserved, sessionId, seq, baseSeq, width, height, format, tileSize, partCount, bodyLength
CONTAINER_HEADER = struct.Struct("<4sBBBBIIIHHBBHI")
CONTAINER_HEADER_SIZE = CONTAINER_HEADER.size  # 32

# version, compression, format, flags, tileSize, reserved, partIndex, partCount, width, height, tileCount,
# sessionId, seq, baseSeq, rawLength, compLength
PART_HEADER = struct.Struct("<BBBBBBHHHHHIIIII")
PART_HEADER_SIZE = PART_HEADER.size  # 36

assert CONTAINER_HEADER_SIZE == 32 and PART_HEADER_SIZE == 36


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
