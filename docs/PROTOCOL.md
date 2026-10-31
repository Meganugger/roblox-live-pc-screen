# RLPS wire protocol, version 1 (normative)

This document specifies every byte that travels from the desktop app to the Roblox clients. It is the contract between
`desktop/rlps/protocol.py` + `codec.py` + `server.py` (producer, reference decoder) and
`roblox/src/shared/RlpsProtocol.luau` + `RlpsDecoder.luau` + `RlpsClientCore.luau` + `roblox/src/server/RlpsRelayCore.luau`
(consumers). Both implementations are cross-checked by `roblox/tests/run_luau_tests.py` (identical error strings).

All integers are **little-endian** and unsigned. "MUST reject" means: discard the whole unit, change no state, report
the error string.

## 1. HTTP endpoint

```
GET /v1/frames?after=<u32>&session=<u32>&key=<0|1>&wait=<ms>&idle=<0|1>
Authorization: Bearer <token>
```

| Parameter | Default | Meaning |
| --- | --- | --- |
| `after` | 0 | seq of the last frame the poller forwarded (0 = none) |
| `session` | 0 | session id of that frame |
| `key` | 0 | 1 = answer with a keyframe |
| `wait` | 10000 | long-poll: max ms to wait for a frame newer than `after` (≤ 25000) |
| `idle` | 0 | 1 = the poller already shows STOPPED; hold the poll while sharing is off |

* Only this path and method exist. Any other path → 404, other methods → 405, a request body → 400, unknown or repeated
  parameters, non-decimal or out-of-range values → 400.
* Authentication: `Bearer` token compared in constant time; failure → 401 (`WWW-Authenticate: Bearer`). Failed attempts
  are rate-limited separately (0.5/s, burst 10 → 429 `Retry-After: 5`). Authorized requests: 20/s, burst 40 → 429
  `Retry-After: 1`. At most 8 concurrent polls → 503 `Retry-After: 1`.
* Success → 200, `Content-Type: text/plain; charset=us-ascii`, `Cache-Control: no-store`. The body is the **standard
  padded base64 (RFC 4648 §4)** of exactly one container (§2). Base64 is used because binary-safe `RequestAsync`
  response bodies are not documented by Roblox (F-0007).

### 1.1 Which container a poll gets

Evaluated under one lock, in this order:

1. Sharing off → **STOPPED**. Exception: with `idle=1`, a poll that *arrives* while sharing is off is held until sharing
   starts (then continue with rule 2) or `wait` expires (then STOPPED). A poll held while sharing is live always learns
   a stop immediately.
2. Live, no newer frame within `wait` (or no frame yet) → **LIVE + UNCHANGED** carrying the current `session`/`seq`.
3. `key=1`, `after=0`, `session` ≠ current session, or frame `after` no longer in the ring (8 frames) → **KEYFRAME**.
4. Otherwise → **DELTA** from frame `after` to the newest frame: exactly the tiles that differ. If none differ (the
   content changed and changed back), **LIVE + UNCHANGED** with the newer `seq` (the poller just advances).

Deltas are computed on demand against the poller's own last frame, so a slow poller receives fewer, larger deltas and
nothing is ever queued for it (backpressure by coalescing).

## 2. Container

| Offset | Size | Field | Rule |
| --- | --- | --- | --- |
| 0 | 4 | magic | `"RLPS"` |
| 4 | 1 | version | 1 |
| 5 | 1 | state | 0 = STOPPED, 1 = LIVE |
| 6 | 1 | flags | bit0 KEYFRAME, bit1 UNCHANGED; other bits MUST be 0 |
| 7 | 1 | reserved | 0 |
| 8 | 4 | sessionId | random per sharing session, ≠ 0 when live |
| 12 | 4 | seq | frame number, 1-based within the session |
| 16 | 4 | baseSeq | delta base (0 for keyframes; = seq for UNCHANGED) |
| 20 | 2 | width | 1…1024 (EditableImage maximum) |
| 22 | 2 | height | 1…1024 |
| 24 | 1 | format | 1 = RGB565, 2 = RGB888 |
| 25 | 1 | tileSize | 8, 16 (default) or 32 |
| 26 | 2 | partCount | 1…512 for frames; 0 for STOPPED/UNCHANGED |
| 28 | 4 | bodyLength | = total length − 32 |
| 32 | … | body | `partCount` part records, back to back |

A decoder MUST reject: total length > 4 MiB or < 32, bad magic/version, `bodyLength` mismatch, unknown flags or state,
STOPPED/UNCHANGED with parts or body, dimensions/format/tile size out of range, `seq = 0`, a delta with `baseSeq = 0`
or `baseSeq = seq`, any part whose header disagrees with the container, truncated or trailing bytes.

## 3. Part record = 36-byte header + payload

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | version (1) |
| 1 | 1 | compression: 0 none, 1 zstd (one standard frame **with content size**) |
| 2 | 1 | format (as container) |
| 3 | 1 | flags: bit0 KEYFRAME (must equal the container's) |
| 4 | 1 | tileSize |
| 5 | 1 | reserved |
| 6 | 2 | partIndex (0-based, < partCount) |
| 8 | 2 | partCount |
| 10 | 2 | width |
| 12 | 2 | height |
| 14 | 2 | tileCount (≥ 1, ≤ number of tiles) |
| 16 | 4 | sessionId |
| 20 | 4 | seq |
| 24 | 4 | baseSeq |
| 28 | 4 | rawLength (decompressed payload length) |
| 32 | 4 | compLength (payload length in the record) |

Every part repeats the frame identity, so a part record is **self-describing**: the Roblox server forwards records
unchanged to clients (one `RemoteEvent` message each) and a client can validate it without the container.

Decompressed payload = `tileCount` × u16 tile indices (strictly increasing, row-major: `index = ty·tilesX + tx`),
followed by the pixels of those tiles in the same order, each tile row-major. Edge tiles are clipped to the frame,
not padded. RGB565 pixel = u16 `r5<<11 | g6<<5 | b5`; RGB888 = bytes R, G, B. Clients expand to RGBA8 by bit
replication (`r8 = r5<<3 | r5>>2`, `g8 = g6<<2 | g6>>4`), alpha 255 — both decoders produce identical bytes.

A decoder MUST reject: `2·tileCount < rawLength ≤ min(tileCount·(2 + tileSize²·bpp), 256 KiB)` violated,
uncompressed `compLength ≠ rawLength`, `compLength = 0` or > 257 KiB, a zstd frame whose declared content size ≠
`rawLength` (checked *before* decompressing, via `EncodingService:GetDecompressedBufferSize` / zstd frame header),
decompressed length ≠ `rawLength`, unordered/out-of-range indices, pixel byte count ≠ the tiles' clipped areas.
The encoder keeps parts ≤ 32 KiB decompressed so each `RemoteEvent` message stays small.

## 4. Chain rules (relay and clients)

The stream is a chain per session: a keyframe, then deltas whose `baseSeq` equals the previous `seq`, or *advance*
messages (`fromSeq → toSeq`, from UNCHANGED containers with a newer `seq`).

* The Roblox server (`RlpsRelayCore`) forwards a container only if it extends its chain; otherwise it drops it and asks
  for a keyframe. It keeps the last keyframe + later deltas/advances (bounded: 384 KiB, then a fresh keyframe) as the
  history for late joiners. STOPPED clears the chain and the history.
* A client (`RlpsClientCore`) applies parts in arrival order (reliable `RemoteEvent`s are ordered). Part 0 of a
  keyframe always restarts; part 0 of a delta needs `sessionId`/`baseSeq` = its last complete frame; later parts must
  follow in order. Anything else → **desync**: it ignores deltas and requests a `sync`, the server answers with
  `reset` + status + history. A frame is drawn only when its last part arrived (no torn frames).
* RemoteEvent messages (server → client): `("status", status, detail?)`, `("part", buffer)`,
  `("advance", sessionId, fromSeq, toSeq)`, `("reset")`; client → server: `("sync")` (rate-limited on both sides).

## 5. Pacing

The Roblox server waits `forwardedBytes / MaxBytesPerSecond` (default 48,000 B/s) before the next poll after a frame,
plus `MinPollInterval` (default 0.2 s) between poll starts (≤ 300 requests/min of the 500/min HttpService budget).
Because deltas are computed against the last forwarded frame, pacing lowers the frame rate for busy content instead of
building a queue anywhere.
