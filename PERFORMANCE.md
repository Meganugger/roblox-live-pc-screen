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
(100 kB/s) and `MaxBytesPerSecond` (8 MB/s) to what the median viewer keeps up with (acks); slower viewers are held
and caught up per viewer (D-0009). The frame rate is capped by the median viewer's measured decode time. A 1920×1080 or 3840×2160 desktop is sent at 960×540 (an integer factor,
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
| Start sharing → picture | 1.2 s |
| desktop change → both TVs | 0.17 s (test polling granularity included; precise glass-to-glass below) |
| late joiner → picture | 0.3 s |
| Stop → TVs off | 0.06–0.1 s |
| scrolling a text page 15 steps | 32,343 copy tiles; 245 kB including refinement in the pauses (resending would be ≈ 15 × 50 kB) |
| congestion (E2E-20) | rate grew 100 kB/s → ≈ 280 kB/s with one viewer (as far as the moving picture needed at the fps its decode time allows) and kept following it when a 10 kB/s viewer joined (held, `LaggingViewers` = 1); the fast viewer showed 83 distinct pictures meanwhile; both ended exact |

The Lune emulator decodes interpreted Luau, like real Roblox clients (native code generation is documented for
server scripts only, S-0039); the fps cap follows the measured decode time.

## Glass-to-glass delay (MEASURED, D-0013)

`python3 tests/e2e/run_e2e.py --scenario latency` — a counter drawn on the real screen is read back from each
client's EditableImage the moment it is written (E2E-31…34). Network models: *studio* (5 ms each way, unlimited link,
20 ms tunnel round trip), *online* (60 ms each way, a queueing 400 kB/s link per player, 150 ms tunnel round trip);
"video" = 20 counter changes/s plus a moving picture in a sixth of the screen. Same harness for both versions
(`--scripts`, plus the old desktop code for "before"):

| | single change, median | video median | video p90 | changes shown |
| --- | ---: | ---: | ---: | ---: |
| studio, before (PR #4) | 0.236 s | 0.253 s | 0.279 s | 99 % |
| **studio, after** | **0.07–0.08 s** | **0.21–0.22 s** | **0.25–0.26 s** | 99–100 % |
| online, 2 players, before (3 runs) | 0.37 s | 0.56 / 0.75 / 0.99 s | 1.12 / 1.88 / 1.63 s | 71–93 % |
| **online, 2 players, after (3 runs)** | **0.21 s** | **0.47–0.49 s** | **0.56–0.63 s** | 92–95 % |
| online, 1 player, before / after | 0.35 / 0.20 s | 0.66 / 0.42 s | 0.96 / 0.59 s | 98 / 98 % |

(Two players share the emulator's one CPU, so they model slower clients.) Where the remaining online delay goes
(ESTIMATE from the model): up to one tunnel round trip waiting for the next poll (avg ≈ 75 ms) + half a round trip back
(75 ms) + pacing (≤ 100 ms) + 60 ms RemoteEvent + link serialization and the queue the rate control allows (≤ 100 ms)
+ capture, encode, decode (≈ 50 ms).

## Client decode cost (MEASURED, interpreted Luau, 2.1 GHz)

| Tile | before D-0013 | after |
| --- | ---: | ---: |
| DCT tile, 10 non-zero coefficients per block | 0.306 ms | 0.170 ms |
| DCT tile, DC only / empty blocks | — | 0.056–0.065 ms (colour conversion floor) |
| 32×32 area of video | 4 DCT tiles ≈ 1.2 ms | one DCT2 macroblock ≈ 0.2 ms |
| same tile with native code (server only) | 0.062 ms | 0.029 ms |

## Client redraws (MEASURED under emulation, D-0011)

What a Roblox client does with a decoded frame: write only what changed into its EditableImage, once per game frame,
and nothing while no TV (or overlay) is in view.

| Situation (1024×576 picture = 589,824 pixels) | Pixels written per redraw | Before D-0011 |
| --- | ---: | ---: |
| two small changes in opposite corners (E2E-23) | 6,144 (1 %) | ≈ 589,000 (bounding box) |
| one changed region (window drag, typing) | its rectangle(s) | its bounding box (same) |
| several frames completed in one game frame (catch-up) | one redraw of their union | one redraw per frame |
| TV behind the camera / seen from behind / > 300 studs (E2E-24) | 0 (E2E-24: 45 redraws skipped while looking away) | every frame |
| TV 120–300 studs away | ≤ 10 redraws/s | every frame |

Each redraw also costs one `WritePixelsBuffer` call per rectangle (at most 12) and a copy into a pooled buffer
(a full-width band is one contiguous copy; the whole picture is written straight from the frame buffer). Real-client
timings remain an owner measurement (KI-0007): watch `LastRedrawPixels`, `Redraws` and `SkippedRedraws` on
`RlpsClient`.

## What limits quality in a real game (ESTIMATE / owner tests)

1. **Roblox replication bandwidth per client** — unknown; the ack-driven controller finds it.
2. **Client decode time** — DCT tiles cost far more Luau work than RAW/COPY tiles (above); large moving areas go
   half-resolution; the fps cap adapts to each viewer's decode time and decode-queue wait.
3. **PC encode time** — ≤ 22 ms per 1024×576 frame on this 2.1 GHz sandbox for desktop work, scrolling and video in a
   window; 34–37 ms for full-screen motion (≈ 27–29 fps here; a current desktop CPU is faster — ESTIMATE).
4. **HTTP** — 500 requests/min per server; every response carries all frames since the previous poll, so this is
   irrelevant to the frame rate; the tunnel's round trip is part of the delay (above).
