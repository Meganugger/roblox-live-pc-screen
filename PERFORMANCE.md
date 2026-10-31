# PERFORMANCE.md

Every number is labelled **MEASURED** (command, environment, commit), **CALCULATED** or **ESTIMATE**. Nothing here was
measured inside the real Roblox engine (no Roblox runtime in the agent sandbox, KI-0002). Roblox-side figures come
from the live pipeline test, which runs the real scripts under an engine emulation in Lune (interpreted Luau, much
slower than Roblox's native code generation).

## Design targets (owner directive 2026-10-31: maximum quality, PC requirements apply)

| Profile | Frame | Capture rate | Coding |
| --- | --- | --- | --- |
| **max (default)** | up to 1024×576 (EditableImage limit 1024) | 30 fps | hybrid: lossless / DCT / copy tiles |
| high | up to 768×432 | 30 fps | hybrid |
| balanced | up to 640×352 | 24 fps | hybrid |
| low | up to 512×288 | 15 fps | hybrid |
| lossless | up to 1024×576 | 15 fps | RGBA8 only (never lossy) |

The byte rate is **not fixed**: it starts at `StartBytesPerSecond` (1 MB/s) and adapts between `MinBytesPerSecond`
(100 kB/s) and `MaxBytesPerSecond` (8 MB/s) to what every viewer keeps up with (acks). The frame rate is capped by
the slowest viewer's measured decode time. A 1920×1080 or 3840×2160 desktop is sent at 960×540 (an integer factor,
letterboxed to 960×544) because integer scaling turns scrolling into exact copies; 2560×1440 and 1366×768 at 1024×576.

## Codec (MEASURED)

`python3 scripts/bench.py --frames 12` — agent sandbox, Linux x86_64, 4 vCPU Intel Xeon @ 2.10 GHz, Python 3.11.17,
numpy 2.4.6, OpenCV 5.0, zstd level 1; this session's final code. Raw output:
[`docs/testing/evidence/bench.txt`](docs/testing/evidence/bench.txt) / `bench.json`. Bytes are container bytes per
frame (raw-body mode; base64 adds 33 %). The budget is a token bucket at the stated rate (what the Roblox server
reports); "q" = mean IJG quality of DCT tiles in the frames that needed them.

| Profile 1024×576, 30 fps | budget | bytes/frame | stream | DCT q | encode/frame |
| --- | ---: | ---: | ---: | ---: | ---: |
| static desktop | any | 0 | 0 | — | 2–3 ms |
| text scroll 8 px/frame | unlimited / 2 MB/s | 5.9 kB | 176 kB/s | lossless + copies | 17–19 ms |
| text scroll 8 px/frame | 500 kB/s | 4.1 kB | 122 kB/s | 20 (few tiles) | 22 ms |
| window drag | 2 MB/s | 6.9 kB | 207 kB/s | lossless | 4 ms |
| video in ¼ of the screen | unlimited | 96.6 kB | 2.9 MB/s | lossless + copies | 13 ms |
| video in ¼ of the screen | 2 MB/s | 56.6 kB | 1.7 MB/s | 98 | 17 ms |
| video in ¼ of the screen | 500 kB/s | 9.7 kB | 290 kB/s | 86 | 19 ms |
| full-screen video | 2 MB/s | 66.9 kB | 2.0 MB/s | 92 | 37 ms |
| full-screen video | 500 kB/s | 15.2 kB | 455 kB/s | 54 | 34 ms |

Scrolling a real text page through a non-integer downscale (live test E2E-21, 1280 → 1024): ~5 kB per scroll step
(97 % of tiles copied), the pauses between steps spent refining to lossless.

Caveat: the synthetic "video" (drifting sine gradients plus grain) partly *translates*, which scroll detection
exploits; real video has less of that, so expect lower DCT quality at the same rate (ESTIMATE). Before this session's
work the same 480×270 video cost 86 kB per frame losslessly (≈ 0.6 fps at 50 kB/s).

## Capture (MEASURED)

Same sandbox, real `mss` grab of a 1920×1080 Xvfb screen: grab 1.7–2.0 ms; OpenCV `INTER_AREA` resize + quantize
2.9–6.7 ms per frame (was 40–56 ms with the numpy filter). On Windows, `--backend auto` uses DXGI Desktop Duplication
when `dxcam` is installed (faster than GDI, captures hardware-accelerated video; not measurable here).

## End to end (MEASURED, real scripts under emulation)

`python3 tests/e2e/run_e2e.py` (report: [`docs/testing/evidence/e2e-report.json`](docs/testing/evidence/e2e-report.json)):

| Event | Time / result |
| --- | ---: |
| Start sharing → picture | 1.1 s |
| desktop change → both TVs | 0.4 s |
| late joiner → picture | 0.2 s |
| Stop → TVs off | 0.06–0.1 s |
| scrolling a text page 15 steps | 32,455 copy tiles; 298 kB including refinement in the pauses (resending would be ≈ 15 × 50 kB) |
| congestion (E2E-20) | rate grew 300 kB/s → 0.99–1.46 MB/s with one viewer; a 40 kB/s viewer was paused while the other kept receiving frames |

The Lune emulator decodes about 8–15 fps of DCT-heavy 768×432 frames (interpreted Luau); the fps cap followed that
measured decode time. Real Roblox clients run `--!native` code (documented for server scripts; client behaviour is an
owner test, F-0040); luavid measured 3.4× for a comparable decoder.

## What limits quality in a real game (ESTIMATE / owner tests)

1. **Roblox replication bandwidth per client** — unknown; the ack-driven controller finds it.
2. **Client decode time** — DCT tiles cost far more Luau work than RAW/COPY tiles; the fps cap adapts to each viewer.
3. **PC encode time** — ≤ 22 ms per 1024×576 frame on this 2.1 GHz sandbox for desktop work, scrolling and video in a
   window; 34–37 ms for full-screen motion (≈ 27–29 fps here; a current desktop CPU is faster — ESTIMATE).
4. **HTTP** — 500 requests/min per server; batching (150 ms) makes this irrelevant to the frame rate.
