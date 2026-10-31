#!/usr/bin/env python3
"""RLPS benchmark: capture-pipeline cost (real mss grab when a display exists) and codec output per workload/profile.

Every number printed is MEASURED on the machine that runs this script; the budget columns are CALCULATED from the
measured sizes. Usage: python3 scripts/bench.py [--frames 20] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "desktop"))

from rlps import app, capture, codec, hybrid  # noqa: E402



def text_page(w: int, h: int, rng: np.random.Generator) -> np.ndarray:
    """White page with dark 'glyph' blocks in lines (text-heavy content)."""
    img = np.full((h, w, 3), 250, np.uint8)
    line_h, glyph_w = 14, 7
    for y in range(4, h - line_h, line_h + 6):
        x = 6
        while x < w - glyph_w:
            if rng.random() < 0.15:
                x += glyph_w  # word gap
                continue
            gh = int(rng.integers(6, line_h))
            img[y + line_h - gh:y + line_h, x:x + glyph_w - 2] = rng.integers(0, 60)
            x += glyph_w
    return img


def video_frame(w: int, h: int, t: int, rng: np.random.Generator) -> np.ndarray:
    """Natural-looking moving content: drifting gradients + mild noise (worst realistic case per pixel)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = 128 + 100 * np.sin((xx + 7 * t) / 23.0)
    g = 128 + 100 * np.sin((yy - 5 * t) / 17.0)
    b = 128 + 100 * np.sin((xx + yy + 11 * t) / 31.0)
    img = np.stack([r, g, b], axis=2) + rng.normal(0, 6, (h, w, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def workloads(w: int, h: int, frames: int):
    rng = np.random.default_rng(7)
    page = text_page(w, h * 3, rng)
    desk = text_page(w, h, rng)
    yield "static desktop", [desk] * frames
    yield "text scroll (8 px/frame)", [np.ascontiguousarray(page[8 * i:8 * i + h]) for i in range(frames)]
    seq = []
    for i in range(frames):
        f = desk.copy()
        x, y = (20 + 12 * i) % max(1, w - w // 3), h // 4
        f[y:y + h // 3, x:x + w // 3] = (60, 90, 200)
        seq.append(f)
    yield "window drag (12 px/frame)", seq
    seq = []
    for i in range(frames):
        f = desk.copy()
        vw, vh = w // 2, h // 2
        f[h // 4:h // 4 + vh, w // 4:w // 4 + vw] = video_frame(vw, vh, i, rng)
        seq.append(f)
    yield "video in a window (1/4 of the screen)", seq
    yield "full-screen video", [video_frame(w, h, i, rng) for i in range(frames)]


BUDGETS = {"unlimited": None, "2 MB/s": 2_000_000, "500 KB/s": 500_000}


def bench_codec(frames: int) -> list[dict]:
    """Every profile x workload x byte budget: bytes per frame, DCT quality, frames skipped, encode time."""
    rows = []
    for prof in app.PROFILES.values():
        w, h = capture.fit_size(1920, 1080, prof.max_w, prof.max_h, 16 if prof.fmt == 4 else 1)
        for name, seq in workloads(w, h, frames):
            qs = [codec.quantize(f, prof.fmt) for f in seq]
            for bname, rate in BUDGETS.items():
                if prof.fmt != 4 and rate is not None:
                    continue  # lossless profile: no budget-driven quality
                per_frame = None if rate is None else rate / prof.fps
                sizes, times, qualities, skipped = [], [], [], 0
                if prof.fmt == 4:
                    enc = hybrid.HybridEncoder(w, h, packer=codec.FrameEncoder(level=1, tile_size=16,
                                                                               max_part_raw_bytes=96 * 1024))
                    tokens, sq = 0.0, 0
                    for i, q in enumerate(qs):
                        tokens = (per_frame or 0) * 1.5 if i == 0 else min(tokens + (per_frame or 0), (per_frame or 0) * 15)
                        t0 = time.perf_counter()
                        data, info = enc.encode(q, session_id=1, seq=sq + 1, base_seq=sq,
                                                budget=None if per_frame is None else tokens)
                        if i:
                            times.append((time.perf_counter() - t0) * 1000)
                        if data is None:
                            skipped += info.skipped
                            if i:
                                sizes.append(0)
                            continue
                        sq += 1
                        tokens -= len(data)
                        if i:
                            sizes.append(len(data))
                            if info.quality > 0:
                                qualities.append(info.quality)
                else:
                    enc = codec.FrameEncoder(level=1)
                    prev = None
                    for i, q in enumerate(qs):
                        t0 = time.perf_counter()
                        data = enc.encode(q, prof.fmt, session_id=1, seq=i + 1, base_seq=i, prev=prev,
                                          keyframe=prev is None)
                        if i:
                            times.append((time.perf_counter() - t0) * 1000)
                            sizes.append(0 if data is None else len(data))
                        prev = q
                mean = statistics.mean(sizes) if sizes else 0
                rows.append({
                    "profile": prof.name, "size": f"{w}x{h}", "fps": prof.fps, "workload": name, "budget": bname,
                    "bytes_per_frame": round(mean), "bytes_per_s_at_fps": round(mean * prof.fps),
                    "dct_quality_mean": round(statistics.mean(qualities)) if qualities else None,
                    "frames_skipped": skipped, "encode_ms_median": round(statistics.median(times), 1) if times else 0,
                })
    return rows


def bench_capture(frames: int) -> list[dict]:
    if not os.environ.get("DISPLAY") and sys.platform not in ("win32", "darwin"):
        return []
    rows = []
    src = capture.MssSource(1, None)
    try:
        src.grab_bgra()  # warm-up / open
        for prof in app.PROFILES.values():
            grab, conv = [], []
            for _ in range(frames):
                t0 = time.perf_counter()
                bgra = src.grab_bgra()
                t1 = time.perf_counter()
                codec.quantize(capture.bgra_to_rgb(bgra, prof.max_w, prof.max_h, 16 if prof.fmt == 4 else 1),
                               prof.fmt)
                t2 = time.perf_counter()
                grab.append((t1 - t0) * 1000)
                conv.append((t2 - t1) * 1000)
            rows.append({"profile": prof.name, "source": f"{bgra.shape[1]}x{bgra.shape[0]}",
                         "grab_ms_median": round(statistics.median(grab), 2),
                         "resize_quantize_ms_median": round(statistics.median(conv), 2)})
    finally:
        src.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--json")
    args = ap.parse_args()
    env = {"python": platform.python_version(), "machine": platform.machine(), "system": platform.system(),
           "cpu_count": os.cpu_count(), "numpy": np.__version__}
    result = {"environment": env, "capture": bench_capture(args.frames), "codec": bench_codec(args.frames)}
    print(json.dumps(env))
    for r in result["capture"]:
        print("capture", json.dumps(r))
    print(f"{'profile':9} {'workload':38} {'budget':>10} {'B/frame':>8} {'B/s':>9} {'DCT q':>6} {'skip':>5} {'enc ms':>7}")
    for r in result["codec"]:
        print(f"{r['profile']:9} {r['workload']:38} {r['budget']:>10} {r['bytes_per_frame']:>8} "
              f"{r['bytes_per_s_at_fps']:>9} {str(r['dct_quality_mean']):>6} {r['frames_skipped']:>5} "
              f"{r['encode_ms_median']:>7}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
