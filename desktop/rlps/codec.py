"""RLPS frame codec: quantization, tile change detection, part/container encoding and a reference decoder.

The reference decoder mirrors the Luau client decoder (``roblox/src/shared/RlpsDecoder.luau``) check for check, so
malformed-input tests written here describe the behaviour expected on Roblox too.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

import numpy as np

from . import protocol as P
from .protocol import ProtocolError

try:  # optional at import time so the reference decoder works without it; required for COMP_ZSTD encoding
    import zstandard as _zstd
except ImportError:  # pragma: no cover - exercised only on machines without the dependency
    _zstd = None


# ----------------------------------------------------------------------------------------------- quantization


def quantize(rgb: np.ndarray, fmt: int) -> np.ndarray:
    """Quantize an (H, W, 3) uint8 RGB frame. RGB565 -> (H, W) uint16; RGB888 -> (H, W, 3) uint8 copy."""
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError(f"expected (H, W, 3) uint8 RGB, got {rgb.shape} {rgb.dtype}")
    h, w = rgb.shape[:2]
    if not (1 <= w <= P.MAX_DIM and 1 <= h <= P.MAX_DIM):
        raise ValueError(f"frame {w}x{h} outside 1..{P.MAX_DIM}")
    if fmt == P.FMT_RGB565:
        r = rgb[:, :, 0].astype(np.uint16) >> 3
        g = rgb[:, :, 1].astype(np.uint16) >> 2
        b = rgb[:, :, 2].astype(np.uint16) >> 3
        return (r << 11) | (g << 5) | b
    if fmt == P.FMT_RGB888:
        return np.ascontiguousarray(rgb)
    if fmt in (P.FMT_RGBA8, P.FMT_HYBRID):
        if fmt == P.FMT_HYBRID and (w % P.HYBRID_TILE or h % P.HYBRID_TILE):
            raise ValueError(f"hybrid frames need dimensions divisible by {P.HYBRID_TILE}, got {w}x{h}")
        out = np.empty((h, w, 4), np.uint8)
        out[..., :3] = rgb
        out[..., 3] = 255
        return out
    raise ValueError(f"unknown pixel format {fmt}")


def expand_to_rgba(q: np.ndarray, fmt: int) -> np.ndarray:
    """Expand quantized pixels to (H, W, 4) uint8 RGBA exactly as the Luau decoder does (bit replication)."""
    if fmt == P.FMT_RGB565:
        q = q.astype(np.uint16)
        r5, g6, b5 = (q >> 11) & 31, (q >> 5) & 63, q & 31
        out = np.empty(q.shape + (4,), np.uint8)
        out[..., 0] = (r5 << 3) | (r5 >> 2)
        out[..., 1] = (g6 << 2) | (g6 >> 4)
        out[..., 2] = (b5 << 3) | (b5 >> 2)
        out[..., 3] = 255
        return out
    if fmt == P.FMT_RGB888:
        out = np.empty(q.shape[:2] + (4,), np.uint8)
        out[..., :3] = q
        out[..., 3] = 255
        return out
    if fmt in (P.FMT_RGBA8, P.FMT_HYBRID):
        return np.array(q, np.uint8, copy=True)
    raise ValueError(f"unknown pixel format {fmt}")


# ------------------------------------------------------------------------------------------- change detection


def changed_tiles(prev: np.ndarray | None, cur: np.ndarray, tile_size: int = P.DEFAULT_TILE_SIZE) -> np.ndarray:
    """Row-major indices of tiles whose quantized pixels differ (all tiles when ``prev`` is None or reshaped)."""
    h, w = cur.shape[:2]
    tiles_x, tiles_y = P.tiles_per_axis(w, h, tile_size)
    if prev is None or prev.shape != cur.shape:
        return np.arange(tiles_x * tiles_y, dtype=np.int64)
    diff = prev != cur
    if diff.ndim == 3:
        diff = diff.any(axis=2)
    pad_h, pad_w = tiles_y * tile_size - h, tiles_x * tile_size - w
    if pad_h or pad_w:
        diff = np.pad(diff, ((0, pad_h), (0, pad_w)))
    per_tile = diff.reshape(tiles_y, tile_size, tiles_x, tile_size).any(axis=(1, 3))
    return np.flatnonzero(per_tile)


# ---------------------------------------------------------------------------------------------------- encoding


@dataclass
class EncodeStats:
    tiles: int = 0
    parts: int = 0
    raw_bytes: int = 0
    compressed_bytes: int = 0
    container_bytes: int = 0


def _tile_bytes(q: np.ndarray, index: int, width: int, height: int, tile_size: int) -> bytes:
    x0, y0, tw, th = P.tile_rect(index, width, height, tile_size)
    block = q[y0 : y0 + th, x0 : x0 + tw]
    if block.dtype == np.uint16:
        block = block.astype("<u2", copy=False)
    return np.ascontiguousarray(block).tobytes()


class FrameEncoder:
    """Encodes quantized frames into RLPS containers. Reuses one zstd compressor (not thread-safe)."""

    def __init__(self, level: int = 3, compression: int = P.COMP_ZSTD,
                 max_part_raw_bytes: int = P.DEFAULT_PART_RAW_BYTES, tile_size: int = P.DEFAULT_TILE_SIZE):
        if compression == P.COMP_ZSTD and _zstd is None:
            raise RuntimeError("the 'zstandard' package is required for zstd compression (pip install zstandard)")
        if tile_size not in P.ALLOWED_TILE_SIZES:
            raise ValueError(f"tile size {tile_size} not in {P.ALLOWED_TILE_SIZES}")
        if not (2 + tile_size * tile_size * 2 <= max_part_raw_bytes <= P.MAX_PART_RAW_BYTES):
            raise ValueError("max_part_raw_bytes must hold at least one tile and stay within MAX_PART_RAW_BYTES")
        self.compression = compression
        self.max_part_raw_bytes = max_part_raw_bytes
        self.tile_size = tile_size
        self._cctx = _zstd.ZstdCompressor(level=level, write_content_size=True) if compression == P.COMP_ZSTD else None

    def encode(self, cur: np.ndarray, fmt: int, *, session_id: int, seq: int, base_seq: int = 0,
               prev: np.ndarray | None = None, keyframe: bool | None = None,
               stats: EncodeStats | None = None) -> bytes | None:
        """Encode ``cur`` as a keyframe (``prev`` None / ``keyframe`` True) or as a delta against ``prev``.

        Returns None for a delta without visible change (the frame service then answers UNCHANGED, keeping the
        poller's base frame)."""
        h, w = cur.shape[:2]
        if keyframe is None:
            keyframe = prev is None
        if keyframe:
            prev, base_seq = None, 0
        elif prev is None:
            raise ValueError("a delta needs the base frame")
        if not (1 <= seq <= 0xFFFFFFFF) or not (0 <= base_seq < 0x100000000) or not (0 <= session_id < 0x100000000):
            raise ValueError("seq/base_seq/session_id out of range")
        ts = self.tile_size
        if fmt == P.FMT_HYBRID:
            raise ValueError("FMT_HYBRID frames are encoded by rlps.hybrid.HybridEncoder")
        indices = changed_tiles(prev, cur, ts)
        if not keyframe and indices.size == 0:
            return None
        entries = [(int(i), _tile_bytes(cur, int(i), w, h, ts)) for i in indices.tolist()]
        return self.pack(entries, fmt, w, h, session_id=session_id, seq=seq, base_seq=base_seq, keyframe=keyframe,
                         stats=stats)

    def pack(self, entries: list[tuple[int, bytes]], fmt: int, w: int, h: int, *, session_id: int, seq: int,
             base_seq: int, keyframe: bool, stats: EncodeStats | None = None, ref: bool = False) -> bytes:
        """Build a container from (tile index, tile data) pairs in increasing index order.

        Tile data is the raw pixel bytes (RGB565/RGB888/RGBA8) or a hybrid entry (mode byte + data)."""
        ts = self.tile_size
        flags = P.CFLAG_KEYFRAME if keyframe else 0
        # Greedy split into parts of at most max_part_raw_bytes decompressed bytes.
        groups: list[list[tuple[int, bytes]]] = []
        current: list[tuple[int, bytes]] = []
        size = 0
        for entry in entries:
            cost = 2 + len(entry[1])
            if cost > self.max_part_raw_bytes:
                raise ValueError("max_part_raw_bytes is smaller than one tile of this pixel format")
            if current and size + cost > self.max_part_raw_bytes:
                groups.append(current)
                current, size = [], 0
            current.append(entry)
            size += cost
        if current:
            groups.append(current)
        if len(groups) > P.MAX_PARTS:
            raise ValueError(f"frame needs {len(groups)} parts > {P.MAX_PARTS}; raise max_part_raw_bytes")
        records = []
        st = stats if stats is not None else EncodeStats()
        for part_index, group in enumerate(groups):
            raw = (np.asarray([i for i, _ in group], dtype="<u2").tobytes() + b"".join(d for _, d in group))
            comp, payload = P.COMP_NONE, raw
            if self._cctx is not None:
                z = self._cctx.compress(raw)
                if len(z) < len(raw):
                    comp, payload = P.COMP_ZSTD, z
            pflags = (P.PFLAG_KEYFRAME if keyframe else 0) | (P.PFLAG_REF if ref else 0)
            header = P.PART_HEADER.pack(P.VERSION, comp, fmt, pflags, ts, 0,
                                        part_index, len(groups), w, h, len(group), session_id, seq, base_seq,
                                        len(raw), len(payload))
            records.append(header + payload)
            st.tiles += len(group)
            st.raw_bytes += len(raw)
            st.compressed_bytes += len(payload)
        st.parts += len(groups)
        body = b"".join(records)
        container = P.CONTAINER_HEADER.pack(P.CONTAINER_MAGIC, P.VERSION, P.STATE_LIVE, flags, 0, session_id, seq,
                                            base_seq, w, h, fmt, ts, len(groups), len(body)) + body
        st.container_bytes += len(container)
        return container


def status_container(state: int, *, session_id: int = 0, seq: int = 0, width: int = 0, height: int = 0,
                     fmt: int = 0, tile_size: int = P.DEFAULT_TILE_SIZE) -> bytes:
    """A part-less container: STOPPED, or LIVE + UNCHANGED (long-poll timeout without a newer frame)."""
    flags = P.CFLAG_UNCHANGED if state == P.STATE_LIVE else 0
    return P.CONTAINER_HEADER.pack(P.CONTAINER_MAGIC, P.VERSION, state, flags, 0, session_id, seq, seq,
                                   width, height, fmt, tile_size, 0, 0)


def to_body(container: bytes) -> bytes:
    """HTTP response body: standard base64 (RFC 4648, padded) of the container (binary-safe bodies unverified)."""
    return base64.b64encode(container)


def from_body(body: bytes | str) -> bytes:
    try:
        return base64.b64decode(body, validate=True)
    except (ValueError, TypeError) as exc:
        raise ProtocolError(f"body is not valid base64: {exc}") from None


# ---------------------------------------------------------------------------------------------------- decoding


@dataclass
class Part:
    compression: int
    fmt: int
    flags: int
    tile_size: int
    part_index: int
    part_count: int
    width: int
    height: int
    tile_count: int
    session_id: int
    seq: int
    base_seq: int
    raw_length: int
    payload: bytes


@dataclass
class Container:
    state: int
    flags: int
    session_id: int
    seq: int
    base_seq: int
    width: int
    height: int
    fmt: int
    tile_size: int
    parts: list[Part] = field(default_factory=list)

    @property
    def keyframe(self) -> bool:
        return bool(self.flags & P.CFLAG_KEYFRAME)


def parse_container(data: bytes) -> Container:
    """Validate the container and split it into part records (payloads stay compressed)."""
    if len(data) > P.MAX_CONTAINER_BYTES:
        raise ProtocolError("container too large")
    if len(data) < P.CONTAINER_HEADER_SIZE:
        raise ProtocolError("truncated container header")
    (magic, version, state, flags, _r, session_id, seq, base_seq, width, height, fmt, ts, part_count,
     body_length) = P.CONTAINER_HEADER.unpack_from(data, 0)
    if magic != P.CONTAINER_MAGIC:
        raise ProtocolError("bad magic")
    if version != P.VERSION:
        raise ProtocolError(f"unsupported version {version}")
    if body_length != len(data) - P.CONTAINER_HEADER_SIZE:
        raise ProtocolError("body length mismatch (truncated or trailing bytes)")
    if flags & ~(P.CFLAG_KEYFRAME | P.CFLAG_UNCHANGED):
        raise ProtocolError("unknown container flags")
    if state == P.STATE_STOPPED or flags & P.CFLAG_UNCHANGED:
        if part_count != 0 or body_length != 0:
            raise ProtocolError("stopped/unchanged container must not carry parts")
        if state not in (P.STATE_STOPPED, P.STATE_LIVE):
            raise ProtocolError(f"unknown state {state}")
        return Container(state, flags, session_id, seq, base_seq, width, height, fmt, ts)
    if state != P.STATE_LIVE:
        raise ProtocolError(f"unknown state {state}")
    if not (1 <= width <= P.MAX_DIM and 1 <= height <= P.MAX_DIM):
        raise ProtocolError("invalid dimensions")
    if fmt not in P.BYTES_PER_PIXEL:
        raise ProtocolError(f"unknown pixel format {fmt}")
    if ts not in P.ALLOWED_TILE_SIZES:
        raise ProtocolError(f"invalid tile size {ts}")
    if not (1 <= part_count <= P.MAX_PARTS):
        raise ProtocolError("invalid part count")
    if fmt == P.FMT_HYBRID and (ts != P.HYBRID_TILE or width % P.HYBRID_TILE or height % P.HYBRID_TILE):
        raise ProtocolError("hybrid frames need tile size 16 and dimensions divisible by 16")
    if seq == 0 or (not flags & P.CFLAG_KEYFRAME and (base_seq == 0 or base_seq == seq)):
        raise ProtocolError("invalid sequence numbers")
    c = Container(state, flags, session_id, seq, base_seq, width, height, fmt, ts)
    off = P.CONTAINER_HEADER_SIZE
    for i in range(part_count):
        if off + P.PART_HEADER_SIZE > len(data):
            raise ProtocolError(f"truncated part header {i}")
        part, comp_length = parse_part_header(data, off)
        expect = (fmt, ts, i, part_count, width, height, session_id, seq, base_seq)
        got = (part.fmt, part.tile_size, part.part_index, part.part_count, part.width, part.height,
               part.session_id, part.seq, part.base_seq)
        if got != expect or bool(part.flags & P.PFLAG_KEYFRAME) != bool(flags & P.CFLAG_KEYFRAME) or (
                c.parts and (part.flags & P.PFLAG_REF) != (c.parts[0].flags & P.PFLAG_REF)):
            raise ProtocolError(f"part {i} header inconsistent with container")
        off += P.PART_HEADER_SIZE
        if off + comp_length > len(data):
            raise ProtocolError(f"truncated part payload {i}")
        part.payload = bytes(data[off : off + comp_length])
        off += comp_length
        c.parts.append(part)
    if off != len(data):
        raise ProtocolError("trailing bytes after last part")
    return c


def parse_part_header(data: bytes, off: int = 0) -> tuple[Part, int]:
    """Parse and range-check one 36-byte part header. Returns (part without payload, compLength)."""
    (version, comp, fmt, flags, ts, _r, part_index, part_count, width, height, tile_count, session_id, seq,
     base_seq, raw_length, comp_length) = P.PART_HEADER.unpack_from(data, off)
    if version != P.VERSION:
        raise ProtocolError("unsupported part version")
    if comp not in (P.COMP_NONE, P.COMP_ZSTD):
        raise ProtocolError("unknown compression")
    if fmt not in P.BYTES_PER_PIXEL or ts not in P.ALLOWED_TILE_SIZES:
        raise ProtocolError("invalid part format/tile size")
    if flags & ~(P.PFLAG_KEYFRAME | P.PFLAG_REF):
        raise ProtocolError("unknown part flags")
    if flags & P.PFLAG_KEYFRAME and flags & P.PFLAG_REF:
        raise ProtocolError("keyframe parts cannot use a reference")
    if flags & P.PFLAG_REF and fmt != P.FMT_HYBRID:
        raise ProtocolError("only hybrid parts can use a reference")
    if not (1 <= width <= P.MAX_DIM and 1 <= height <= P.MAX_DIM):
        raise ProtocolError("invalid part dimensions")
    if not (1 <= part_count <= P.MAX_PARTS and part_index < part_count):
        raise ProtocolError("invalid part index")
    tiles_x, tiles_y = P.tiles_per_axis(width, height, ts)
    if not (1 <= tile_count <= tiles_x * tiles_y):
        raise ProtocolError("invalid tile count")
    max_raw = tile_count * P.max_raw_per_tile(fmt, ts)
    if not (2 * tile_count < raw_length <= min(max_raw, P.MAX_PART_RAW_BYTES)):
        raise ProtocolError("invalid raw length")
    if comp == P.COMP_NONE and comp_length != raw_length:
        raise ProtocolError("uncompressed part length mismatch")
    if comp_length == 0 or comp_length > P.MAX_PART_RAW_BYTES + 1024:
        raise ProtocolError("invalid compressed length")
    return Part(comp, fmt, flags, ts, part_index, part_count, width, height, tile_count, session_id, seq,
                base_seq, raw_length, b""), comp_length


def decompress_part(part: Part) -> bytes:
    if part.compression == P.COMP_NONE:
        raw = part.payload
    else:
        if _zstd is None:
            raise RuntimeError("zstandard is required to decode zstd parts")
        try:
            params = _zstd.get_frame_parameters(part.payload)
        except _zstd.ZstdError as exc:
            raise ProtocolError(f"bad zstd frame: {exc}") from None
        if params.content_size != part.raw_length:  # mirrors EncodingService:GetDecompressedBufferSize check
            raise ProtocolError("zstd content size does not match rawLength")
        try:
            raw = _zstd.ZstdDecompressor().decompress(part.payload, max_output_size=part.raw_length)
        except _zstd.ZstdError as exc:
            raise ProtocolError(f"zstd decode failed: {exc}") from None
    if len(raw) != part.raw_length:
        raise ProtocolError("decompressed length mismatch")
    return raw


def apply_part(frame_rgba: np.ndarray, part: Part, ref: np.ndarray | None = None) -> list[int]:
    """Decode one part into ``frame_rgba`` ((H, W, 4) uint8). Validates fully before writing; returns tile indices.

    ``ref`` = the picture as it was before this frame (required by COPY tiles of PFLAG_REF parts)."""
    if frame_rgba.shape != (part.height, part.width, 4):
        raise ProtocolError("frame buffer size does not match part dimensions")
    raw = decompress_part(part)
    n, ts, w, h = part.tile_count, part.tile_size, part.width, part.height
    tiles_x, tiles_y = P.tiles_per_axis(w, h, ts)
    indices = np.frombuffer(raw, dtype="<u2", count=n).tolist()
    last = -1
    for idx in indices:
        if idx <= last or idx >= tiles_x * tiles_y:
            raise ProtocolError("tile indices must be strictly increasing and in range")
        last = idx
    if part.fmt == P.FMT_HYBRID:
        if ts != P.HYBRID_TILE or w % ts or h % ts:
            raise ProtocolError("hybrid frames need tile size 16 and dimensions divisible by 16")
        spans = []
        off = 2 * n
        for idx in indices:
            if off >= len(raw):
                raise ProtocolError("tile data length mismatch")
            mode = raw[off]
            size = (P.HYBRID_RAW_ENTRY if mode == P.TILE_MODE_RAW else
                    P.HYBRID_DCT_ENTRY if mode == P.TILE_MODE_DCT else
                    P.HYBRID_COPY_ENTRY if mode == P.TILE_MODE_COPY else 0)
            if size == 0:
                raise ProtocolError("unknown tile mode")
            if off + size > len(raw):
                raise ProtocolError("tile data length mismatch")
            if mode == P.TILE_MODE_DCT and raw[off + 1] >= len(_dct().QUALITIES):
                raise ProtocolError("invalid DCT quality")
            if mode == P.TILE_MODE_COPY:
                if not part.flags & P.PFLAG_REF:
                    raise ProtocolError("copy tile without reference")
                dx, dy = int.from_bytes(raw[off + 1:off + 3], "little", signed=True), \
                    int.from_bytes(raw[off + 3:off + 5], "little", signed=True)
                x0, y0, _, _ = P.tile_rect(idx, w, h, ts)
                if not (0 <= x0 + dx <= w - ts and 0 <= y0 + dy <= h - ts):
                    raise ProtocolError("copy tile outside the frame")
            spans.append((idx, mode, off))
            off += size
        if off != len(raw):
            raise ProtocolError("tile data length mismatch")
        if part.flags & P.PFLAG_REF and (ref is None or ref.shape != frame_rgba.shape):
            raise ProtocolError("copy tile without reference")
        dct_spans = [(idx, off) for idx, mode, off in spans if mode == P.TILE_MODE_DCT]
        decoded = {}
        if dct_spans:  # one vectorized integer decode for all DCT tiles of the part
            D = _dct()
            qz = np.stack([np.frombuffer(raw, "<i2", count=384, offset=off + 2) for _, off in dct_spans])
            qis = np.array([raw[off + 1] for _, off in dct_spans])
            tiles = D.reconstruct(qz.reshape(-1, 6, 64), qis)
            decoded = {idx: tiles[k] for k, (idx, _) in enumerate(dct_spans)}
        for idx, mode, off in spans:
            x0, y0, _, _ = P.tile_rect(idx, w, h, ts)
            if mode == P.TILE_MODE_RAW:
                tile = np.frombuffer(raw, np.uint8, offset=off + 1, count=ts * ts * 4).reshape(ts, ts, 4)
            elif mode == P.TILE_MODE_COPY:
                dx = int.from_bytes(raw[off + 1:off + 3], "little", signed=True)
                dy = int.from_bytes(raw[off + 3:off + 5], "little", signed=True)
                tile = ref[y0 + dy: y0 + dy + ts, x0 + dx: x0 + dx + ts]
            else:
                tile = decoded[idx]
            frame_rgba[y0: y0 + ts, x0: x0 + ts] = tile
        return indices
    bpp = P.BYTES_PER_PIXEL[part.fmt]
    expected = 2 * n
    for idx in indices:
        _, _, tw, th = P.tile_rect(idx, w, h, ts)
        expected += tw * th * bpp
    if expected != len(raw):
        raise ProtocolError("tile data length mismatch")
    off = 2 * n
    for idx in indices:
        x0, y0, tw, th = P.tile_rect(idx, w, h, ts)
        nbytes = tw * th * bpp
        if part.fmt == P.FMT_RGB565:
            q = np.frombuffer(raw, dtype="<u2", offset=off, count=tw * th).reshape(th, tw)
        else:
            q = np.frombuffer(raw, dtype=np.uint8, offset=off, count=nbytes).reshape(th, tw, bpp)
        frame_rgba[y0: y0 + th, x0: x0 + tw] = expand_to_rgba(q, part.fmt)
        off += nbytes
    return indices


def _dct():
    from . import dct  # local import: dct imports protocol only, but keeps codec importable without it
    return dct


def apply_container(frame_rgba: np.ndarray | None, container: Container) -> np.ndarray | None:
    """Reference client: apply every part of a LIVE container; returns the (possibly new) RGBA frame."""
    if container.state != P.STATE_LIVE or container.flags & P.CFLAG_UNCHANGED:
        return frame_rgba
    shape = (container.height, container.width, 4)
    if container.keyframe and (frame_rgba is None or frame_rgba.shape != shape):
        frame_rgba = np.zeros(shape, np.uint8)
    if frame_rgba is None or frame_rgba.shape != shape:
        raise ProtocolError("delta without a matching base frame")
    ref = frame_rgba.copy() if container.parts and container.parts[0].flags & P.PFLAG_REF else None
    for part in container.parts:
        apply_part(frame_rgba, part, ref)
    return frame_rgba
