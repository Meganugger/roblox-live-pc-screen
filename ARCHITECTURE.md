# ARCHITECTURE.md

_Selected 2026-10-24 (10th session) — `DECISIONS.md` D-0002. Wire format: `docs/PROTOCOL.md`._

```
Windows desktop ─mss/DXGI─► desktop app (Python)                        Roblox game server (Luau)             Roblox clients (Luau)
                            capture → INTER_AREA resize → RGBA          one poll loop: RequestAsync            time-budgeted decode queue
                            hybrid encoder at the reported byte rate:   bundles of frames (batch 150 ms)       RAW / DCT (bit-exact) / COPY tiles
                            lossless | DCT | COPY tiles, refinement     relay chain + history, playout at      one EditableImage, SurfaceGui on the TV
                            chain ring, frame service 127.0.0.1:8787    capture spacing, AIMD rate + fps cap   acks: seq + decode ms/frame
                            GET /v1/frames ◄──tunnel (HTTPS)── poll ──► one reliable RemoteEvent (buffers) ──► ("ack") back to the server
```

| Component | Path | Responsibility |
| --- | --- | --- |
| Codec + protocol (Python) | `desktop/rlps/protocol.py`, `codec.py`, `dct.py`, `hybrid.py` | tiles, DCT, hybrid encoder with rate control and scroll copies, parts/containers/bundles |
| Capture | `desktop/rlps/capture.py` | `mss` monitor capture, resize, interruptions |
| Frame service | `desktop/rlps/server.py` | auth, rate limits, long-poll, on-demand deltas |
| App | `desktop/rlps/app.py` | CLI/GUI, explicit start/stop, indicator, config/token |
| Roblox shared | `roblox/src/shared/` | protocol constants, part/bundle decoder, `RlpsDct` (bit-exact DCT), assembler, base64 fallback |
| Roblox server | `roblox/src/server/` | poller, validation, fan-out, keyframes for joiners, status |
| Roblox client | `roblox/src/client/` | reconstruction, SurfaceGui, status/stopped/error screens |
| TV model | `roblox/models/RlpsTV.model.json` → `Workspace.RlpsTV` (Rojo) | screen part tagged `RlpsScreen` (16×9 studs), bezel, neck, base |
| Windows scripts | `scripts/windows/*.bat` | setup, show token, start app, start quick tunnel, emergency stop |
| Live pipeline test | `tests/e2e/` | real capture → frame service → unmodified Roblox scripts under a Lune engine emulation (`docs/testing/E2E.md`) |

## Stream v2 (D-0007, D-0008 — 29th session)

* **Encode once, at capture time** (`desktop/rlps/hybrid.py`): each 16×16 tile of the new frame is compared with the
  client's picture (the encoder keeps it bit-exactly). Moving tiles go **lossless** if the byte budget allows, else
  **DCT** (YCbCr 4:2:0, JPEG tables, best quality that fits); scrolled content is sent as 5-byte **COPY** tiles from the
  client's previous picture; tiles that stopped moving are **refined to lossless** with the remaining budget, so a still
  screen becomes a pixel-exact copy of the desktop.
* **Bundles**: one HTTP response carries every frame newer than the poller's position (plus 150 ms of batching), so
  500 requests/min do not cap the frame rate; the server plays them out at their capture spacing.
* **Congestion control**: clients acknowledge frames with their decode time; the server adapts the byte rate (AIMD on
  the age of unacknowledged frames) and a frame-rate cap (decode time), and reports both with every poll; the encoder
  obeys them. A viewer far behind is paused and re-synced instead of slowing everyone.
* **Binary bodies** are used after a probe proved them intact; otherwise base64.

## Flow control (D-0006)

* **Idle polls**: once the server shows STOPPED it polls with `idle=1`; the frame service holds such a poll until the
  owner presses Start (picture ≈ 1 s after Start) or the wait expires. Polls that believe sharing is live learn a stop
  immediately (TV off ≈ 0.2 s after Stop).
* **Pacing** (superseded by D-0008): the byte budget is now enforced by the encoder at capture time (token bucket at
  the rate the server reports); frames that do not fit are skipped and their changes go into the next frame.
* **Late joiners / desync**: the server keeps the last keyframe + later deltas (≤ 384 KiB) and replays it on `sync`.
