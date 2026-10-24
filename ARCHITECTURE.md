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
| TV model | built at runtime by the server script (`Workspace.LiveScreenTV`) | housing, bezel, screen part, stand, status light |
