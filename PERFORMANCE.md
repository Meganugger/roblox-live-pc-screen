# PERFORMANCE.md

Every number is labelled **MEASURED** (command, environment, commit), **CALCULATED** (from measured numbers),
**ESTIMATE** or **ASSUMPTION**. Nothing here was measured inside Roblox (no Roblox runtime in the agent sandbox,
KI-0002); Roblox-side costs are the owner's Studio/published tests.

## Defaults

| Profile | Frame | Pixel format | Capture rate (max) | Use |
| --- | --- | --- | --- | --- |
| low | 320×180 | RGB565 | 2/s | weak devices, many viewers |
| **balanced (default)** | 480×270 | RGB565 | 4/s | desktop, text, browsing |
| high | 640×360 | RGB888 | 6/s | few viewers on good connections |

Roblox server stream budget `MaxBytesPerSecond` = 48,000 B/s (Roblox's planning figure for remote traffic is
~50 KB/s per client, F-0017 — **ASSUMPTION** that this is a sensible ceiling; the real reliable-RemoteEvent ceiling
is unverified). Polls: ≤ 5/s (`MinPollInterval` 0.2 s) = ≤ 300/min of the 500/min HttpService limit.

## Codec output per workload (MEASURED)

`python3 scripts/bench.py --frames 15` — agent sandbox, Linux x86_64, 4 vCPU Intel Xeon @ 2.10 GHz, Python 3.11.17,
numpy 2.4.6, zstandard (level 3), commit `7e63e1c` (codec unchanged since). Sizes are HTTP body bytes (base64
container, ≈ 4/3 × binary); "delta" is the mean over 14 consecutive frames. Raw data:
[`docs/testing/evidence/bench.json`](docs/testing/evidence/bench.json).

| Profile | Workload | Keyframe | Delta | Encode/delta | Stream at profile rate | Frames/s within 48 KB/s (CALCULATED) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| low | static desktop | 6.9 KB | 0 | 0.1 ms | 0 | — (nothing sent) |
| low | text scroll 8 px/frame | 6.9 KB | 6.9 KB | 0.8 ms | 13.8 KB/s | 7 → capped at 2 |
| low | window drag | 6.5 KB | 0.6 KB | 0.2 ms | 1.2 KB/s | capped at 2 |
| low | video in ¼ of the screen | 42.6 KB | 38.9 KB | 0.3 ms | 77.8 KB/s | ~1.2 |
| low | full-screen video | 149 KB | 150 KB | 0.8 ms | 301 KB/s | ~0.3 |
| balanced | static desktop | 14.8 KB | 0 | 0.2 ms | 0 | — |
| balanced | text scroll | 15.7 KB | 15.5 KB | 1.3 ms | 62 KB/s | ~3 |
| balanced | window drag | 13.7 KB | 0.6 KB | 0.3 ms | 2.3 KB/s | capped at 4 |
| balanced | video in ¼ of the screen | 96 KB | 86 KB | 0.8 ms | 344 KB/s | ~0.6 |
| balanced | full-screen video | 335 KB | 335 KB | 1.6 ms | 1.3 MB/s | ~0.15 |
| high | text scroll | 39 KB | 38 KB | 6.8 ms | 227 KB/s | ~1.3 |
| high | full-screen video | 885 KB | 887 KB | 6.6 ms | 5.3 MB/s | ~0.05 |

The synthetic "video" is a worst case (smooth moving gradients plus per-pixel noise, which zstd cannot compress);
real video compresses somewhat better, but the conclusion holds: **this is a desktop-sharing system, not a video
stream.** Static desktops cost nothing, text and window work is fluid at the profile rate, and full-motion content is
slowed by design to well under 1 frame/s (pacing coalesces frames instead of queueing them, E2E-16).

## Capture cost on the PC (MEASURED)

Same environment, real `mss` grab of a 1920×1080 Xvfb screen: grab 3.1–3.3 ms; resize + quantize 40 ms (low),
51 ms (balanced), 56 ms (high) per frame (pure numpy box + bilinear filter). At the balanced rate that is ~20 % of one
core **[CALCULATED]**. A real Windows desktop (GDI `BitBlt` through `mss`) is typically slower to grab than Xvfb
**[ESTIMATE]**; the sharing window shows the actual `ms/frame`. The Windows CI job measures it on a real Windows
desktop (see `TEST_RESULTS.md`).

## End-to-end latency (MEASURED, emulated Roblox)

`python3 tests/e2e/run_e2e.py` (TR-0008; real capture → real frame service over loopback HTTP → unmodified Roblox
scripts under the Lune emulation, no tunnel, no Roblox network):

| Event | Time until the TV shows it |
| --- | ---: |
| join → "Screen sharing is off" | 1.0 s |
| Start sharing → first picture | 1.0–1.1 s (≤ 1 s `StoppedPollInterval` + one capture) |
| desktop change → both TVs | 0.2 s (≤ one capture interval at 4/s) |
| late joiner → picture | 0.26 s |
| Stop → both TVs off | 0.2 s |
| frame service back after outage → picture | ~8 s (exponential backoff 2, 4 … s) |

In production add the tunnel round trip (tens of ms **[ESTIMATE]**) and Roblox's server→client replication delay
(unknown, owner test).

## Multi-client scaling (CALCULATED)

One poll per game server regardless of viewers; the server forwards the same compressed records to every viewer, so
server CPU is O(bytes) and outbound traffic = viewers × stream rate (balanced desktop work ≈ 2–60 KB/s, capped at 48
KB/s by default). Each additional game server of the same experience polls separately (≤ 8 concurrent polls accepted by
the frame service). Each client decodes only changed tiles; one `WritePixelsBuffer` per rendered frame covering the
dirty rectangle. Client decode cost on real devices: **unmeasured** (owner test).
