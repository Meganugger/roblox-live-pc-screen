# ARCHITECTURE.md

_Selected 2026-10-24 (10th session) — `DECISIONS.md` D-0002. Wire format: `docs/PROTOCOL.md`._

```
Windows desktop ──mss──► desktop app (Python)                      Roblox game server (Luau)            Roblox clients (Luau)
                         capture → resize → quantize → ring        poller: RequestAsync long-poll        decompress (EncodingService)
                         Start/Stop sharing + indicator            Bearer token from experience secret   validate part, write tiles
                         frame service 127.0.0.1:8787 ──tunnel──►  validate container, fan out parts ──► RGBA buffer → EditableImage
                         GET /v1/frames (delta tiles, zstd)  HTTPS  one reliable RemoteEvent (buffer)     ImageLabel on SurfaceGui → TV
```

| Component | Path | Responsibility |
| --- | --- | --- |
| Codec + protocol (Python) | `desktop/rlps/protocol.py`, `desktop/rlps/codec.py` | quantize, tile diff, part/container encoding |
| Capture | `desktop/rlps/capture.py` | `mss` monitor capture, resize, interruptions |
| Frame service | `desktop/rlps/server.py` | auth, rate limits, long-poll, on-demand deltas |
| App | `desktop/rlps/app.py` | CLI/GUI, explicit start/stop, indicator, config/token |
| Roblox shared | `roblox/src/shared/` | protocol constants, part decoder, tile blitter, base64 fallback |
| Roblox server | `roblox/src/server/` | poller, validation, fan-out, keyframes for joiners, status |
| Roblox client | `roblox/src/client/` | reconstruction, SurfaceGui, status/stopped/error screens |
| TV model | `roblox/models/RlpsTV.model.json` → `Workspace.RlpsTV` (Rojo) | screen part tagged `RlpsScreen` (16×9 studs), bezel, neck, base |
| Windows scripts | `scripts/windows/*.bat` | setup, show token, start app, start quick tunnel, emergency stop |
| Live pipeline test | `tests/e2e/` | real capture → frame service → unmodified Roblox scripts under a Lune engine emulation (`docs/testing/E2E.md`) |

## Flow control (D-0006)

* **Idle polls**: once the server shows STOPPED it polls with `idle=1`; the frame service holds such a poll until the
  owner presses Start (picture ≈ 1 s after Start) or the wait expires. Polls that believe sharing is live learn a stop
  immediately (TV off ≈ 0.2 s after Stop).
* **Pacing**: after forwarding N bytes the server waits N / `MaxBytesPerSecond` (48 KB/s) before polling again. The
  frame service computes each delta against the server's last forwarded frame, so slower polling means fewer, larger
  deltas — never a queue. Static screens cost nothing; video is slowed to fit the budget (`PERFORMANCE.md`).
* **Late joiners / desync**: the server keeps the last keyframe + later deltas (≤ 384 KiB) and replays it on `sync`.
