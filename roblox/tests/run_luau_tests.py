#!/usr/bin/env python3
"""Cross-language tests of the Luau RLPS modules against the Python reference codec (T-0009, T-0012).

1. Encodes test frames with ``desktop/rlps`` (the real encoder) and computes the expected outcome of every case with the
   Python reference decoder (``parse_container`` / ``apply_part``): parsed fields, exact error strings, frame CRC-32.
2. Writes the vectors as a Luau module, copies the ModuleScripts of ``roblox/src/{shared,server,client}`` into one temp
   dir (rewriting Roblox-style ``require(script.Parent.X)`` to ``require("./X")``) and runs every
   ``roblox/tests/*.spec.luau`` with the standalone ``luau`` CLI.
3. Optionally type-checks those modules with ``luau-analyze`` (``--analyze``).

zstd parts: standalone Luau has no zstd, so the spec injects a decompressor shim that maps each compressed payload produced
here to its raw bytes (on Roblox the same hook is ``EncodingService:DecompressBuffer``). Every other check runs for real.

Usage: python3 roblox/tests/run_luau_tests.py [--luau PATH] [--analyze] [--keep]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "desktop"))

from rlps import codec as C  # noqa: E402
from rlps import hybrid as HY  # noqa: E402
from rlps import protocol as P  # noqa: E402
from rlps import server as SV  # noqa: E402
from rlps.protocol import ProtocolError  # noqa: E402

import zstandard  # noqa: E402

_ESC = [chr(i) if 0x20 <= i <= 0x7E and chr(i) not in '"\\' else "\\x%02x" % i for i in range(256)]


def lstr(b: bytes) -> str:
    return '"' + "".join(_ESC[x] for x in b) + '"'


def lval(v) -> str:
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, bytes):
        return lstr(v)
    if isinstance(v, str):
        return lstr(v.encode("utf-8"))
    if isinstance(v, (list, tuple)):
        return "{" + ", ".join(lval(x) for x in v) + "}"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {lval(x)}" for k, x in v.items()) + "}"
    raise TypeError(type(v))


ZSTD_MAP: dict[bytes, bytes] = {}


def note_zstd(container: bytes) -> None:
    """Record raw payloads of zstd parts so the Luau shim can 'decompress' them."""
    c = C.parse_container(container)
    for part in c.parts:
        if part.compression == P.COMP_ZSTD:
            ZSTD_MAP[part.payload] = zstandard.ZstdDecompressor().decompress(part.payload)


def fields(c: C.Container) -> dict:
    return dict(state=c.state, flags=c.flags, sessionId=c.session_id, seq=c.seq, baseSeq=c.base_seq, width=c.width,
                height=c.height, format=c.fmt, tileSize=c.tile_size, partCount=len(c.parts))


def hybrid_modes(raw: bytes, n: int) -> list[int]:
    sizes = {P.TILE_MODE_RAW: P.HYBRID_RAW_ENTRY, P.TILE_MODE_DCT: P.HYBRID_DCT_ENTRY,
             P.TILE_MODE_DCT2: P.HYBRID_DCT_ENTRY, P.TILE_MODE_COPY: P.HYBRID_COPY_ENTRY}
    out, off = [], 2 * n
    for _ in range(n):
        out.append(raw[off])
        off += sizes[raw[off]]
    return out


def dirty_rect(c: C.Container) -> list[int]:
    """[x, y, w, h] = union of the tile rectangles carried by every part (what RlpsClientCore.takeDirty reports)."""
    x0 = y0 = 1 << 30
    x1 = y1 = -1
    for part in c.parts:
        raw = C.decompress_part(part)
        indices = np.frombuffer(raw, dtype="<u2", count=part.tile_count).tolist()
        modes = hybrid_modes(raw, part.tile_count) if part.fmt == P.FMT_HYBRID else [None] * len(indices)
        for idx, mode in zip(indices, modes):
            tx, ty, tw, th = P.tile_rect(idx, c.width, c.height, c.tile_size)
            if mode == P.TILE_MODE_DCT2:  # a half-resolution macroblock covers 32x32
                tw, th = 2 * tw, 2 * th
            x0, y0, x1, y1 = min(x0, tx), min(y0, ty), max(x1, tx + tw), max(y1, ty + th)
    return [x0, y0, x1 - x0, y1 - y0]


def frame_crc(frame: np.ndarray) -> int:
    return zlib.crc32(np.ascontiguousarray(frame).tobytes()) & 0xFFFFFFFF


def expect_case(data: bytes) -> dict:
    """Expected Luau outcome for one container: parse error, or fields + apply error/CRC on a fresh zero frame."""
    try:
        c = C.parse_container(data)
    except ProtocolError as e:
        return {"err": str(e)}
    out = {"fields": fields(c)}
    if c.state == P.STATE_LIVE and not c.flags & P.CFLAG_UNCHANGED:
        frame = np.zeros((c.height, c.width, 4), np.uint8)
        ref = frame.copy() if c.parts and c.parts[0].flags & P.PFLAG_REF else None
        apply_err = None
        for part in c.parts:
            try:
                C.apply_part(frame, part, ref)
            except ProtocolError as e:
                msg = str(e)
                apply_err = "*" if msg.startswith(("bad zstd frame", "zstd decode failed")) else msg
                break
        out["applyErr"] = apply_err
        out["crc"] = frame_crc(frame)
    return out


# ------------------------------------------------------------------------------------------------- test images


def img_solid(w, h, rgb):
    a = np.empty((h, w, 3), np.uint8)
    a[:] = rgb
    return a


def img_gradient(w, h):
    y, x = np.mgrid[0:h, 0:w]
    return np.stack([(x * 255 // max(w - 1, 1)), (y * 255 // max(h - 1, 1)), ((x + y) * 7) % 256], -1).astype(np.uint8)


def img_noise(w, h, seed):
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


def img_text(w, h, seed):
    a = img_solid(w, h, (250, 250, 250))
    r = np.random.default_rng(seed)
    for row in range(2, h - 3, 6):
        for col in range(2, w - 2, 4):
            if r.random() < 0.6:
                a[row:row + 4, col:col + 2] = (20, 20, 30)
    return a


def moved_rect(base, x, y, s, rgb):
    a = base.copy()
    a[y:y + s, x:x + s] = rgb
    return a


def sequences():
    out = []
    configs = [
        # name, fmt, tile, comp, maxPart, frames
        ("1x1-rgb565-zstd", P.FMT_RGB565, 16, P.COMP_ZSTD, P.DEFAULT_PART_RAW_BYTES,
         [img_solid(1, 1, (200, 100, 50)), img_solid(1, 1, (1, 2, 3))]),
        ("17x9-rgb888-t8-none", P.FMT_RGB888, 8, P.COMP_NONE, 300,
         [img_gradient(17, 9), moved_rect(img_gradient(17, 9), 9, 1, 3, (255, 0, 0))]),
        ("33x31-rgb565-t32-oneTilePerPart", P.FMT_RGB565, 32, P.COMP_NONE, 2 + 32 * 32 * 3,
         [img_noise(33, 31, 1), moved_rect(img_noise(33, 31, 1), 32, 30, 1, (0, 255, 0))]),
        ("64x64-rgb565-t8-noise-none", P.FMT_RGB565, 8, P.COMP_NONE, P.DEFAULT_PART_RAW_BYTES,
         [img_noise(64, 64, 2), moved_rect(img_noise(64, 64, 2), 63, 63, 1, (9, 9, 9)), img_noise(64, 64, 3)]),
        ("320x180-rgb565-t16-zstd-text", P.FMT_RGB565, 16, P.COMP_ZSTD, P.DEFAULT_PART_RAW_BYTES,
         [img_text(320, 180, 4), moved_rect(img_text(320, 180, 4), 100, 50, 40, (0, 120, 255)),
          moved_rect(img_text(320, 180, 4), 140, 60, 40, (0, 120, 255))]),
        ("160x90-rgb888-t16-zstd-gradient", P.FMT_RGB888, 16, P.COMP_ZSTD, 8 * 1024,
         [img_gradient(160, 90), moved_rect(img_gradient(160, 90), 0, 0, 20, (255, 255, 0)), img_noise(160, 90, 5)]),
        ("resize-48x20-then-20x48", P.FMT_RGB565, 16, P.COMP_ZSTD, P.DEFAULT_PART_RAW_BYTES,
         [img_gradient(48, 20), img_gradient(20, 48)]),
        ("37x21-rgba8-t16-zstd", P.FMT_RGBA8, 16, P.COMP_ZSTD, P.DEFAULT_PART_RAW_BYTES,
         [img_noise(37, 21, 8), moved_rect(img_noise(37, 21, 8), 30, 14, 7, (255, 0, 255))]),
        # scattered changes (dirty rectangles): a corner tile, the opposite corner, then an L of three tiles
        ("200x120-rgb565-t16-scattered", P.FMT_RGB565, 16, P.COMP_ZSTD, P.DEFAULT_PART_RAW_BYTES,
         [img_gradient(200, 120), moved_rect(moved_rect(img_gradient(200, 120), 2, 3, 5, (255, 0, 0)), 190, 110, 6,
                                             (0, 255, 0)),
          moved_rect(moved_rect(moved_rect(moved_rect(moved_rect(img_gradient(200, 120), 2, 3, 5, (255, 0, 0)), 190,
                                                      110, 6, (0, 255, 0)), 70, 40, 4, (9, 9, 9)), 86, 40, 4,
                                (9, 9, 9)), 70, 56, 4, (9, 9, 9))]),
    ]
    for name, fmt, ts, comp, max_part, frames in configs:
        enc = C.FrameEncoder(compression=comp, max_part_raw_bytes=max_part, tile_size=ts)
        session = 0xA5A5_0000 + len(out)
        prev_q, ref, seq, steps = None, None, 0, []
        for rgb in frames:
            q = C.quantize(rgb, fmt)
            seq += 1
            delta_ok = prev_q is not None and prev_q.shape == q.shape
            data = enc.encode(q, fmt, session_id=session, seq=seq, base_seq=seq - 1 if delta_ok else 0,
                              prev=prev_q if delta_ok else None, keyframe=not delta_ok)
            if data is None:
                seq -= 1
                continue
            note_zstd(data)
            c = C.parse_container(data)
            ref = C.apply_container(ref, c)
            assert np.array_equal(ref[..., :3] >> 3, C.expand_to_rgba(q, fmt)[..., :3] >> 3)
            steps.append({"data": data, "fields": fields(c), "crc": frame_crc(ref), "dirty": dirty_rect(c)})
            prev_q = q
        out.append({"name": name, "steps": steps})
    out.extend(hybrid_sequences())
    return out


def img_smooth(w, h, t):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.stack([128 + 110 * np.sin((xx + 9 * t) / 11), 128 + 110 * np.sin((yy - 4 * t) / 7),
                  128 + 100 * np.sin((xx * 2 + yy) / 13)], axis=2)
    return np.clip(a + np.random.default_rng(t).normal(0, 9, a.shape), 0, 255).astype(np.uint8)


def hybrid_sequences():
    """FMT_HYBRID chains with DCT tiles at many quality steps, lossless refinement and extreme pixels (clamping)."""
    out = []
    w, h = 64, 48
    extreme = img_solid(w, h, (0, 0, 0))
    extreme[:, w // 2:] = (255, 255, 255)
    extreme[::2, ::3] = (255, 0, 0)
    frames = [(img_smooth(w, h, 0), 1500, True)] + [(img_smooth(w, h, t), b, False)
                                                    for t, b in ((1, 2500), (2, 4000), (3, 6000), (4, 9000))]
    frames += [(img_smooth(w, h, 4), 4000, False)] * 4 + [(extreme, 2500, False), (extreme, 2500, False),
                                                           (extreme, None, False)]
    frames += [(img_smooth(w, h, 20 + i), b, True) for i, b in enumerate((1500, 2300, 3100, 4000))]  # DCT keyframes
    page = img_text(w, h * 3, 11)  # scrolling text: COPY tiles from the previous picture
    frames += [(page[:h], None, False)] + [(page[6 * k:6 * k + h], 6000, False) for k in range(1, 5)]
    for name, max_part, comp in (("64x48-hybrid-zstd", P.DEFAULT_PART_RAW_BYTES, P.COMP_ZSTD),
                                 ("64x48-hybrid-none-small-parts", 3 * 1027, P.COMP_NONE)):
        enc = HY.HybridEncoder(w, h, packer=C.FrameEncoder(compression=comp, tile_size=16, max_part_raw_bytes=max_part))
        session = 0xB0B0_0000 + len(out)
        ref, seq, steps, qualities, copies = None, 0, [], set(), 0
        scale = 1 if comp == P.COMP_ZSTD else 5  # uncompressed DCT tiles are 770 bytes at every quality
        for rgb, budget, force in frames:
            data, info = enc.encode(C.quantize(rgb, P.FMT_HYBRID), session_id=session, seq=seq + 1, base_seq=seq,
                                    budget=None if budget is None else budget * scale, force_keyframe=force)
            if data is None:
                continue
            seq += 1
            qualities.add(info.quality)
            copies += info.copied_tiles
            note_zstd(data)
            c = C.parse_container(data)
            ref = C.apply_container(ref, c)
            assert np.array_equal(ref, enc.recon)
            steps.append({"data": data, "fields": fields(c), "crc": frame_crc(ref), "dirty": dirty_rect(c)})
        if comp == P.COMP_ZSTD:
            assert len(qualities - {-1}) >= 3, qualities  # several DCT quality steps exercised
        assert -1 in qualities and len(qualities) >= 2, qualities  # lossless and DCT frames
        assert copies > 0, "scroll frames must produce COPY tiles"
        out.append({"name": name, "steps": steps})
    # large moving area: half-resolution macroblocks (TILE_MODE_DCT2) next to full-resolution ones and lossless tiles
    w2, h2 = 112, 80  # 7x5 tiles: the last tile column and row can only be full-resolution
    enc = HY.HybridEncoder(w2, h2)
    enc.HALF_RES_MIN_TILES = 8
    base = img_smooth(w2, h2, 3).astype(np.float32)
    seq, steps, modes, ref = 0, [], set(), None
    for k, budget in enumerate((3000, 3500, 4000, 5000, 6000, 3000, None)):
        rgb = np.clip(base * (0.5 + 0.12 * k), 0, 255).astype(np.uint8)
        rgb[k * 7 % h2, :] = (255, 0, 255)  # extreme values: clamping in the doubled pixels
        data, info = enc.encode(C.quantize(rgb, P.FMT_HYBRID), session_id=0xD2D2_0001, seq=seq + 1, base_seq=seq,
                                budget=budget, force_keyframe=k == 0)
        if data is None:
            continue
        seq += 1
        note_zstd(data)
        c = C.parse_container(data)
        for part in c.parts:
            modes |= set(hybrid_modes(C.decompress_part(part), part.tile_count))
        ref = C.apply_container(ref, c)
        assert np.array_equal(ref, enc.recon)
        steps.append({"data": data, "fields": fields(c), "crc": frame_crc(ref), "dirty": dirty_rect(c)})
    assert {P.TILE_MODE_DCT2, P.TILE_MODE_DCT} <= modes, modes
    out.append({"name": "112x80-hybrid-halfres", "steps": steps})
    return out


def corruption_cases():
    """Truncations and single-byte mutations of a small 2-part uncompressed container + status containers."""
    enc = C.FrameEncoder(compression=P.COMP_NONE, max_part_raw_bytes=300, tile_size=8)
    base = enc.encode(C.quantize(img_gradient(17, 9), P.FMT_RGB888), P.FMT_RGB888, session_id=77, seq=5)
    assert len(C.parse_container(base).parts) == 2
    delta = enc.encode(C.quantize(moved_rect(img_gradient(17, 9), 0, 0, 2, (1, 2, 3)), P.FMT_RGB888),
                       P.FMT_RGB888, session_id=77, seq=6, base_seq=5,
                       prev=C.quantize(img_gradient(17, 9), P.FMT_RGB888))
    cases = []
    for blob_name, blob in (("key", base), ("delta", delta)):
        for n in range(len(blob)):
            cases.append({"blob": blob_name, "op": "trunc", "n": n, **expect_case(blob[:n])})
            if n >= P.CONTAINER_HEADER_SIZE:
                fixed = bytearray(blob[:n])
                fixed[28:32] = (n - P.CONTAINER_HEADER_SIZE).to_bytes(4, "little")
                cases.append({"blob": blob_name, "op": "truncfix", "n": n, **expect_case(bytes(fixed))})
        for off in range(len(blob)):
            orig = blob[off]
            for v in sorted({0x00, 0xFF, orig ^ 0x01, orig ^ 0x80, (orig + 1) & 0xFF}):
                if v == orig:
                    continue
                m = bytearray(blob)
                m[off] = v
                cases.append({"blob": blob_name, "op": "set", "off": off, "v": v, **expect_case(bytes(m))})
        cases.append({"blob": blob_name, "op": "append", **expect_case(blob + b"\x00")})
    statuses = {
        "stopped": C.status_container(P.STATE_STOPPED),
        "unchanged": C.status_container(P.STATE_LIVE, session_id=9, seq=41, width=640, height=360, fmt=P.FMT_RGB888),
    }
    for name, blob in statuses.items():
        cases.append({"blob": name, "op": "none", **expect_case(blob)})
        for off in range(len(blob)):
            m = bytearray(blob)
            m[off] ^= 0x01
            cases.append({"blob": name, "op": "set", "off": off, "v": m[off], **expect_case(bytes(m))})
    blobs = {"key": base, "delta": delta, **statuses}
    return blobs, cases


def payload_cases():
    """Hand-built uncompressed parts with bad tile index lists / lengths (exercise applyRecord's payload checks)."""
    w, h, ts, fmt = 24, 16, 8, P.FMT_RGB565  # 3x2 tiles of 8x8
    tile_bytes = 8 * 8 * 2

    def container(indices, tile_count=None, extra=b""):
        raw = np.asarray(indices, "<u2").tobytes() + b"\x11" * (tile_bytes * len(indices)) + extra
        tc = len(indices) if tile_count is None else tile_count
        ph = P.PART_HEADER.pack(P.VERSION, P.COMP_NONE, fmt, P.PFLAG_KEYFRAME, ts, 0, 0, 1, w, h, tc, 3, 1, 0,
                                len(raw), len(raw))
        body = ph + raw
        return P.CONTAINER_HEADER.pack(P.CONTAINER_MAGIC, P.VERSION, P.STATE_LIVE, P.CFLAG_KEYFRAME, 0, 3, 1, 0, w, h,
                                       fmt, ts, 1, len(body)) + body

    specs = {
        "ok-0-5": container([0, 5]),
        "dup-index": container([2, 2]),
        "decreasing": container([4, 1]),
        "out-of-range": container([0, 6]),
        "short-data": container([0, 1], extra=b"")[:-2],
        "long-data": container([0, 1], extra=b"\x00\x00"),
        "count-mismatch": container([0, 1, 2], tile_count=2),
    }
    cases = []
    for name, blob in specs.items():
        if name == "short-data":  # keep the container self-consistent: fix the part + body lengths after truncating
            b = bytearray(blob)
            raw_len = len(b) - 32 - 36
            b[28:32] = (len(b) - 32).to_bytes(4, "little")
            b[32 + 28:32 + 32] = raw_len.to_bytes(4, "little")
            b[32 + 32:32 + 36] = raw_len.to_bytes(4, "little")
            blob = bytes(b)
        cases.append({"name": name, "data": blob, **expect_case(blob)})
    cases.extend(hybrid_payload_cases())
    return cases


def hybrid_payload_cases():
    """Hand-built uncompressed FMT_HYBRID parts: tile modes, entry lengths, quality byte, dimensions."""
    from rlps import dct
    w, h = 32, 16  # 2x1 tiles

    def container(entries, width=w, height=h, indices=None):
        idx = list(range(len(entries))) if indices is None else indices
        raw = np.asarray(idx, "<u2").tobytes() + b"".join(entries)
        ph = P.PART_HEADER.pack(P.VERSION, P.COMP_NONE, P.FMT_HYBRID, P.PFLAG_KEYFRAME, 16, 0, 0, 1, width, height,
                                len(idx), 3, 1, 0, len(raw), len(raw))
        body = ph + raw
        return P.CONTAINER_HEADER.pack(P.CONTAINER_MAGIC, P.VERSION, P.STATE_LIVE, P.CFLAG_KEYFRAME, 0, 3, 1, 0, width,
                                       height, P.FMT_HYBRID, 16, 1, len(body)) + body

    raw_tile = bytes((P.TILE_MODE_RAW,)) + bytes(range(256)) * 4
    qz = dct.quantize(dct.forward_coefficients(img_smooth(16, 16, 3)[None]), 6)
    dct_tile = dct.pack_entries(qz, 6)[0]
    max_coef = bytes((P.TILE_MODE_DCT, 15)) + np.full(384, 32767, "<i2").tobytes()
    min_coef = bytes((P.TILE_MODE_DCT, 0)) + np.full(384, -32768, "<i2").tobytes()
    def copy_entry(dx, dy):
        return bytes((P.TILE_MODE_COPY,)) + dx.to_bytes(2, "little", signed=True) + dy.to_bytes(2, "little", signed=True)

    def ref_container(entries, flags=P.PFLAG_REF):
        idx = list(range(len(entries)))
        raw = np.asarray(idx, "<u2").tobytes() + b"".join(entries)
        ph = P.PART_HEADER.pack(P.VERSION, P.COMP_NONE, P.FMT_HYBRID, flags, 16, 0, 0, 1, w, h, len(idx), 3, 2, 1,
                                len(raw), len(raw))
        body = ph + raw
        return P.CONTAINER_HEADER.pack(P.CONTAINER_MAGIC, P.VERSION, P.STATE_LIVE, 0, 0, 3, 2, 1, w, h, P.FMT_HYBRID,
                                       16, 1, len(body)) + body

    specs = {
        "hy-copy-ok": ref_container([copy_entry(16, 0), raw_tile]),
        "hy-copy-outside": ref_container([copy_entry(-1, 0), raw_tile]),
        "hy-copy-outside-y": ref_container([copy_entry(0, 1), raw_tile]),
        "hy-copy-no-ref-flag": ref_container([copy_entry(16, 0), raw_tile], flags=0),
        "hy-key-with-ref": container([raw_tile]) [:32 + 3] + bytes((P.PFLAG_KEYFRAME | P.PFLAG_REF,)) + container([raw_tile])[32 + 4:],
        "hy-raw+dct": container([raw_tile, dct_tile]),
        "hy-dct-extremes": container([max_coef, min_coef]),
        "hy-unknown-mode": container([raw_tile, bytes((5,)) + dct_tile[1:]]),
        "hy-bad-quality": container([raw_tile, dct_tile[:1] + bytes((16,)) + dct_tile[2:]]),
        "hy-short-entry": container([raw_tile, dct_tile[:-2]]),
        "hy-long-data": container([raw_tile, dct_tile + b"\x00"]),
        "hy-odd-dims": container([raw_tile], width=24, height=16, indices=[0]),
    }
    return [{"name": name, "data": blob, **expect_case(blob)} for name, blob in specs.items()]


def bundle_cases():
    """RLPB bundles: a valid one (entries + offsets) and malformed variants with Python's verdict."""
    good = SV.bundle([(0, b"abc"), (33, b"defgh"), (70000, b"")])
    variants = {"good": good, "empty-count": SV.bundle([]), "trunc-header": good[:11], "bad-magic": b"RLPX" + good[4:],
                "bad-version": good[:4] + b"\x02" + good[5:], "length+1": good + b"\x00", "length-1": good[:-1]}
    big = bytearray(good)
    big[12 + 4:12 + 8] = (1000).to_bytes(4, "little")  # first entry claims 1000 bytes
    variants["entry-overrun"] = bytes(big)
    out = []
    for name, blob in variants.items():
        try:
            entries = SV.parse_bundle(blob)
            off, offs = P.BUNDLE_HEADER.size, []
            for t, c in entries:
                off += P.BUNDLE_ENTRY.size
                offs.append({"t": t, "offset": off, "length": len(c)})
                off += len(c)
            out.append({"name": name, "data": blob, "entries": offs})
        except ProtocolError as e:
            out.append({"name": name, "data": blob, "err": str(e)})
    return out


def base64_cases():
    """Canonical bodies (codec.to_body) of random bytes + malformed inputs, with Python's validate=True verdict."""
    import base64
    import binascii
    import random

    r = random.Random(7)
    inputs = [base64.b64encode(bytes(r.randrange(256) for _ in range(n))) for n in [*range(40), 255, 256, 257, 4096]]
    inputs += [b"A", b"AB", b"ABC", b"====", b"A===", b"AB=C", b"QQ==QQ==", b"QQ= =", b" QQ==", b"QQ==\n", b"QUJD\n",
               b"QU*D", b"QR==", b"QUJ=", b"Zm9v", b"Zm9vYg==", b"Zm9vYmE=", b"-_8=", b"\x00\x00\x00\x00", b"\xff\xff\xff\xff",
               b"=QUJ", b"Q===", b"QUJDRA=="]
    out = []
    for s in inputs:
        canonical = False
        try:
            dec = base64.b64decode(s, validate=True)
            canonical = base64.b64encode(dec) == s
            out.append({"s": s, "out": dec, "canonical": canonical})
        except (binascii.Error, ValueError):
            out.append({"s": s, "err": True})
    return out


def write_vectors(path):
    seqs = sequences()
    blobs, ccases = corruption_cases()
    pcases = payload_cases()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("-- generated by roblox/tests/run_luau_tests.py; do not edit\nreturn {\n")
        fh.write("\tzstd = {\n")
        for comp, raw in ZSTD_MAP.items():
            fh.write(f"\t\t[{lstr(comp)}] = {lstr(raw)},\n")
        fh.write("\t},\n\tsequences = {\n")
        for s in seqs:
            fh.write(f"\t\t{{ name = {lval(s['name'])}, steps = {{\n")
            for st in s["steps"]:
                fh.write(f"\t\t\t{{ data = {lstr(st['data'])}, fields = {lval(st['fields'])}, crc = {st['crc']}, dirty = {lval(st['dirty'])} }},\n")
            fh.write("\t\t} },\n")
        fh.write("\t},\n\tblobs = {\n")
        for k, b in blobs.items():
            fh.write(f"\t\t{k} = {lstr(b)},\n")
        fh.write("\t},\n\tcorruption = {\n")
        for c in ccases:
            fh.write("\t\t" + lval(c) + ",\n")
        fh.write("\t},\n\tpayload = {\n")
        for c in pcases:
            fh.write("\t\t" + lval(c) + ",\n")
        fh.write("\t},\n\tbundles = {\n")
        for c in bundle_cases():
            fh.write("\t\t" + lval(c) + ",\n")
        fh.write("\t},\n\tbase64 = {\n")
        for c in base64_cases():
            fh.write("\t\t" + lval(c) + ",\n")
        fh.write("\t},\n}\n")
    return len(seqs), sum(len(s["steps"]) for s in seqs), len(ccases), len(pcases)


def find_tool(name, explicit):
    for cand in (explicit, os.environ.get(name.upper().replace("-", "_")), shutil.which(name),
                 os.path.join("/data/agent_tools/luau", name)):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    sys.exit(f"{name} not found: install the Luau CLI (https://github.com/luau-lang/luau/releases) or pass --luau")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--luau")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    luau = find_tool("luau", a.luau)
    tmp = tempfile.mkdtemp(prefix="rlps-luau-")
    try:
        modules = []
        for sub in ("shared", "server", "client"):
            d = os.path.join(REPO, "roblox", "src", sub)
            for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                # Scripts (*.server.luau / *.client.luau) use Roblox globals: type-checked separately, never run here.
                if fn.endswith(".luau") and not fn.endswith((".server.luau", ".client.luau")):
                    with open(os.path.join(d, fn), encoding="utf-8") as fh:
                        src = re.sub(r"require\(script\.Parent\.(\w+)\)", r'require("./\1")', fh.read())
                    with open(os.path.join(tmp, fn), "w", encoding="utf-8") as fh:
                        fh.write(src)
                    modules.append(fn)
        specs = sorted(fn for fn in os.listdir(HERE) if fn.endswith(".spec.luau"))
        for fn in specs + [f for f in os.listdir(HERE) if f.endswith("_helpers.luau")]:
            shutil.copy(os.path.join(HERE, fn), tmp)
        counts = write_vectors(os.path.join(tmp, "vectors.luau"))
        print("vectors: %d sequences / %d containers, %d corruption cases, %d payload cases" % counts)
        rc = 0
        if a.analyze:
            analyze = os.path.join(os.path.dirname(luau), "luau-analyze")
            r = subprocess.run([analyze, *modules, *specs], cwd=tmp, capture_output=True, text=True)
            clean = r.returncode == 0 and not (r.stdout + r.stderr).strip()  # type errors and lint warnings both fail
            print(f"luau-analyze ({len(modules)} modules, {len(specs)} specs):", "OK" if clean else "FAIL")
            if not clean:
                print(r.stdout + r.stderr)
                rc = 1
        total_pass = total_fail = 0
        for spec in specs:
            r = subprocess.run([luau, spec], cwd=tmp, capture_output=True, text=True)
            out = r.stdout + r.stderr
            fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
            for ln in fails[:40]:
                print(ln)
            summary = [ln for ln in out.splitlines() if ln.startswith("SUMMARY")]
            print(spec + ":", summary[-1] if summary else out[-2000:])
            m = re.search(r"passed=(\d+) failed=(\d+)", summary[-1]) if summary else None
            if m:
                total_pass, total_fail = total_pass + int(m.group(1)), total_fail + int(m.group(2))
            if r.returncode or fails or not summary:
                rc = 1
        print("TOTAL passed=%d failed=%d (%d specs)" % (total_pass, total_fail, len(specs)))
        return rc
    finally:
        if a.keep:
            print("kept", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
