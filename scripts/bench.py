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

from rlps import app, capture, codec  # noqa: E402

CLIENT_BUDGET = 50_000  # bytes/s per client (F-0017 planning target, not a hard limit)


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


def bench_codec(frames: int) -> list[dict]:
    rows = []
    for prof in app.PROFILES.values():
        w, h = capture.fit_size(1920, 1080, prof.max_w, prof.max_h)
        for name, seq in workloads(w, h, frames):
            enc = codec.FrameEncoder()
            qs = [codec.quantize(f, prof.fmt) for f in seq]
            t0 = time.perf_counter()
            key = enc.encode(qs[0], prof.fmt, session_id=1, seq=1)
            key_ms = (time.perf_counter() - t0) * 1000
            sizes, times = [], []
            for i in range(1, len(qs)):
                t0 = time.perf_counter()
                d = enc.encode(qs[i], prof.fmt, session_id=1, seq=i + 1, base_seq=i, prev=qs[i - 1])
                times.append((time.perf_counter() - t0) * 1000)
                sizes.append(0 if d is None else len(codec.to_body(d)))
            mean = statistics.mean(sizes)
            rows.append({
                "profile": prof.name, "size": f"{w}x{h}", "fmt": "RGB565" if prof.fmt == 1 else "RGB888",
                "fps": prof.fps, "workload": name,
                "keyframe_body_bytes": len(codec.to_body(key)), "keyframe_encode_ms": round(key_ms, 1),
                "delta_body_bytes_mean": round(mean), "delta_encode_ms_median": round(statistics.median(times), 2),
                "bytes_per_s_at_profile_fps": round(mean * prof.fps),
                "fps_within_50KBps": None if mean == 0 else round(CLIENT_BUDGET / mean, 1),
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
                codec.quantize(capture.bgra_to_rgb(bgra, prof.max_w, prof.max_h), prof.fmt)
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
    print(f"{'profile':9} {'workload':38} {'key B':>8} {'delta B':>8} {'enc ms':>7} {'B/s':>8} {'fps@50KB/s':>10}")
    for r in result["codec"]:
        print(f"{r['profile']:9} {r['workload']:38} {r['keyframe_body_bytes']:>8} {r['delta_body_bytes_mean']:>8} "
              f"{r['delta_encode_ms_median']:>7} {r['bytes_per_s_at_profile_fps']:>8} "
              f"{str(r['fps_within_50KBps']):>10}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
