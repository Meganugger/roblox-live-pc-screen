# RLPS wire protocol, version 1 (normative)

This document specifies every byte that travels from the desktop app to the Roblox clients. It is the contract between
`desktop/rlps/protocol.py` + `codec.py` + `dct.py` + `hybrid.py` + `server.py` (producer, reference decoder) and
`roblox/src/shared/RlpsProtocol.luau` + `RlpsDecoder.luau` + `RlpsDct.luau` + `RlpsClientCore.luau` +
`roblox/src/server/RlpsRelayCore.luau` + `RlpsFanout.luau` (consumers). Both implementations are cross-checked by
`roblox/tests/run_luau_tests.py` (identical error strings, bit-identical pixels).

All integers are **little-endian**. "MUST reject" means: discard the whole unit, change no state, report the error.

## 1. HTTP endpoints

```
GET /v1/frames?after=<u32>&session=<u32>&key=<0|1>&fresh=<0|1>&wait=<ms>&idle=<0|1>&rate=<B/s>&fps=<n>&batch=<ms>&max=<bytes>&enc=<0|1>
GET /v1/probe
Authorization: Bearer <token>
```

| Parameter | Default | Meaning |
| --- | --- | --- |
| `after` | 0 | seq of the last frame the poller has (0 = none) |
| `session` | 0 | session id of that frame |
| `key` | 0 | 1 = start from a keyframe (the poller's chain is unknown or broken) |
| `fresh` | 0 | 1 = continue the chain, but make the next captured frame a keyframe (viewers of the poller need one) |
| `wait` | 10000 | long-poll: max ms to wait for a frame newer than `after` (≤ 25000) |
| `idle` | 0 | 1 = the poller already shows STOPPED; hold the poll while sharing is off |
| `rate` | 0 | byte rate the poller's viewers sustain (congestion control, §6); 0 = not reported |
| `fps` | 0 | frame rate the poller's viewers can decode (§6); 0 = not reported |
| `batch` | 0 | after the first new frame, keep collecting frames for this many ms (≤ 1000) |
| `max` | 4 MiB | response size cap (65536 … 16 MiB); at least one frame is always returned |
| `enc` | 0 | 0 = base64 text body, 1 = raw binary body (only after a successful probe) |

* Only these two paths and GET exist. Other paths → 404, other methods → 405, a request body → 400; unknown or
  repeated parameters, non-decimal or out-of-range values → 400; `/v1/probe` with parameters → 400.
* Authentication: `Bearer` token, constant-time compare; failure → 401. Failed attempts: 0.5/s burst 10 → 429
  `Retry-After: 5`. Authorized requests: 20/s burst 40 → 429 `Retry-After: 1`. ≤ 8 concurrent polls → else 503.
* `/v1/probe` returns 1024 bytes `00 01 … FF` repeated 4 times (`application/octet-stream`). A poller uses raw bodies
  only if it receives them unchanged (Roblox does not document binary-safe response bodies, F-0007; community code
  reads raw bytes, F-0038), and falls back to base64 if a raw body ever fails to parse.
* `/v1/frames` → 200 with one **bundle** (§2): standard padded base64 (`text/plain`) or raw (`application/octet-stream`).

### 1.1 What a poll returns

Frames are **encoded once, at capture time**, into one chain per sharing session (a keyframe, then deltas against the
decoder-side picture) and kept in a bounded ring (64 MiB / 1024 records). Evaluated under one lock:

1. Sharing off → bundle `[STOPPED]`. With `idle=1` a poll that *arrives* while sharing is off is held until sharing
   starts or `wait` expires; a poll held while live always learns a stop at once.
2. The poller's chain continues (`session` current and `after` within the ring) → every record with seq > `after`.
   With `fresh=1` the next capture is forced to be a keyframe — even of an unchanged screen — unless the ring already
   holds a keyframe newer than `after` (that one answers the request). `key=1` would instead replay the ring from its
   newest keyframe: old frames every viewer has already seen.
3. Otherwise (`key=1`, unknown session, `after` = 0 or left the ring) → the ring from its newest keyframe, if that
   keyframe is at most 24 records back; else the next capture is forced to be a keyframe and the poll waits for it.
4. Nothing new within `wait` → bundle `[LIVE + UNCHANGED]` whose seq is `after` (current session) or 0 — **never
   newer than `after`** (a newer seq would mean "frames identical up to here" and make a relay skip deltas).
5. Once a record is available, more are collected for `batch` ms (or until `max` bytes). The Roblox server sends
   `batch=0` by default (D-0013): a poll returns as soon as one frame exists, and the frames captured while the next
   poll travels arrive together with it — several frames per HTTP request anyway, so 500 requests/min do not limit the
   frame rate, without adding a batching wait to the delay.

## 2. Bundle (`RLPB`)

`magic "RLPB" | version u8 = 1 | reserved u8 | count u16 (1…256) | bodyLength u32`, then `count` ×
`(tOffsetMs u32, length u32, container[length])`. `tOffsetMs` = capture time of the container relative to the first
one (the Roblox server plays them out at this spacing). MUST reject: > 16 MiB, short header, bad magic/version,
`bodyLength` ≠ size − 12, count 0 or > 256, truncated entries, trailing bytes.

## 3. Container (32-byte header + parts)

| Offset | Size | Field | Rule |
| --- | --- | --- | --- |
| 0 | 4 | magic | `"RLPS"` |
| 4 | 1 | version | 1 |
| 5 | 1 | state | 0 STOPPED, 1 LIVE |
| 6 | 1 | flags | bit0 KEYFRAME, bit1 UNCHANGED |
| 7 | 1 | reserved | 0 |
| 8 | 4 | sessionId | random per sharing session |
| 12 | 4 | seq | 1-based frame number |
| 16 | 4 | baseSeq | delta base = previous seq (0 for keyframes) |
| 20 | 2 / 2 | width / height | 1…1024 |
| 24 | 1 | format | 1 RGB565, 2 RGB888, 3 RGBA8, **4 HYBRID** |
| 25 | 1 | tileSize | 8, 16 or 32 (**16** for HYBRID, whose width and height must be multiples of 16) |
| 26 | 2 | partCount | 1…512 (0 for STOPPED/UNCHANGED) |
| 28 | 4 | bodyLength | total − 32 |

MUST reject as before (length, magic, version, flags, state, dimensions, format, tile size, part count, `seq = 0`,
delta with `baseSeq` 0 or = seq, parts disagreeing with the container — including the REF flag of part 0 —,
truncation, trailing bytes), plus HYBRID with tile size ≠ 16 or dimensions not divisible by 16.

## 4. Part record = 36-byte header + payload

Header: `version u8 | compression u8 (0 none, 1 zstd with content size) | format u8 | flags u8 | tileSize u8 |
reserved u8 | partIndex u16 | partCount u16 | width u16 | height u16 | tileCount u16 | sessionId u32 | seq u32 |
baseSeq u32 | rawLength u32 | compLength u32`.

Part flags: bit0 KEYFRAME (= container's), bit1 **REF** (the frame copies from the picture as it was before the frame;
set on every part of the frame; never with KEYFRAME; HYBRID only). Every part repeats the frame identity, so the Roblox
server forwards records unchanged and clients validate them on their own.

Decompressed payload = `tileCount` × u16 tile indices (strictly increasing, row-major), then the tiles' data in the
same order:

* RGB565 / RGB888 / RGBA8: the clipped tile's pixels, row-major (2 / 3 / 4 bytes per pixel). Clients expand to RGBA8
  (RGB565 by bit replication; RGBA8 rows are copied as-is).
* **HYBRID**: one entry per tile, by its first byte:
  * `0 RAW`: 1024 bytes = 16×16 RGBA8 (lossless);
  * `1 DCT`: quality u8 (0…15) + 384 int16 = 6 blocks (Y00, Y01, Y10, Y11, Cb, Cr) × 64 coefficients in zigzag
    order (YCbCr 4:2:0 macroblock);
  * `2 COPY`: dx i16, dy i16 — the 16×16 block at (x0+dx, y0+dy) of the reference picture (REF parts only);
  * `3 DCT2`: exactly like `1 DCT`, but the decoded 16×16 macroblock is drawn at twice its size into the **32×32**
    area of this tile and its right, lower and lower-right neighbours (every pixel becomes a 2×2 square;
    `rlps.dct.upscale2`). Those three tiles are not listed. The encoder uses it for complete, aligned 2×2 groups of
    moving tiles when the moving area is large (≥ 6 % of the frame, ≥ 48 tiles): video costs clients a quarter of the
    decode work and bytes; still content is refined to lossless full-resolution tiles as usual. The source of the
    macroblock is the 2×2 box average `(a+b+c+d+2) >> 2` (encoder only, `rlps.dct.downscale2`).

**DCT decoding (exact integer specification):** quality q → IJG factor `s = q<50 ? 5000//q : 200−2q` for
q ∈ {10,20,30,40,50,60,70,75,80,85,88,90,92,94,96,98}; table = `clamp((base·s + 50)//100, 1, 255)` (ITU T.81 Annex K
luma/chroma bases); `D[k] = coef[k] · table[k]`; `out = Mᵀ·D·M` with `M = round(4096 · DCT-II basis)`;
sample = `clamp(floor((out + 2²³) / 2²⁴) + 128, 0, 255)`; colour = BT.601 full range in 16.16 fixed point:
`R = Y + floor((91881·Cr' + 32768)/65536)`, `G = Y − floor((22554·Cb' + 46802·Cr' + 32768)/65536)`,
`B = Y + floor((116130·Cb' + 32768)/65536)` (Cb' = Cb − 128, nearest-neighbour chroma), clamped, alpha 255. Every
intermediate is an integer below 2⁵³, so Luau (doubles) and numpy produce identical pixels — required, because the
encoder predicts later frames from this exact picture.

MUST reject (before writing any pixel): raw-length bounds (`2·tileCount < rawLength ≤ min(tileCount·maxTile,
256 KiB)`, maxTile = 1027 for HYBRID, else 2 + tile²·bpp), compressed-length rules, zstd declared content size ≠
`rawLength` (checked before decompressing), unordered/out-of-range indices, pixel byte counts (non-hybrid); for HYBRID:
unknown tile mode, entry overrun, quality ≥ 16, COPY without REF, COPY source outside the frame, DCT2 area outside the
frame (`x0 + 32 > width` or `y0 + 32 > height`), trailing bytes, REF part without a reference picture. Entries are
applied in order (a later entry overwrites an earlier one's pixels), so both decoders stay bit-identical.

## 5. Chain rules (relay and clients)

* The Roblox server (`RlpsRelayCore`) forwards a container only if it extends its chain (keyframe, or delta with
  `baseSeq` = its seq), drops anything else and asks for a keyframe (`key=1`). The **played history** (`RlpsFanout`) =
  the last keyframe broadcast + every frame broadcast after it, in playout order (beyond 48 MiB a fresh keyframe is
  requested). STOPPED clears chain, history and the playout queue.
* A client (`RlpsClientCore`) applies parts in order; part 0 of a keyframe restarts; part 0 of a delta needs its base;
  later parts must follow in order; anything else → desync → `sync` request (retried every 3 s while desynced). A part
  0 with REF first snapshots the current picture (COPY tiles read the snapshot). Only complete frames are drawn.
* RemoteEvent messages, server → client: `("status", s, detail?)`, `("part", buffer)`, `("advance", sid, from, to)`,
  `("reset")`; client → server: `("sync", processed)`, `("ack", sessionId, seq, decodeMsPerFrame, processed, waitMs,
  ageMs)` — `waitMs` = average time the parts acknowledged by this ack waited in the client's decode queue, `ageMs` =
  how long ago the newest of them was processed (both optional: older clients omit them).
  `processed` = total bytes of `part` buffers the client has handled, or dropped (queue cleared on STOPPED or
  overflow), since it started. The server clamps it to [previous value, bytes sent to that client].

## 6. Flow and congestion control

* **Playout:** the server schedules each container of a bundle at `arrival + tOffsetMs · k`, never earlier than the
  previous one, where `k = min(1, PlayoutMs / span)` compresses a bundle spanning more than `PlayoutMs` (default
  100 ms): motion keeps its spacing, but no frame waits more than `PlayoutMs`; more than 2 × `PlayoutMs` of backlog is
  forwarded at once.
* **Acks:** clients acknowledge (≤ 20/s, whenever something changed) their newest complete frame, their average
  decode time per frame, their `processed` byte count, the decode-queue wait and the ack's own age.
* **Client drawing:** a client decodes on Heartbeat within its time budget and draws the newest complete frame in the
  same Heartbeat. After completing a frame it only continues decoding if every part of the next frame is already
  queued and less than half the budget is used — so a Heartbeat never ends half-way into a frame while a complete
  one waits to be drawn.
* **Per-viewer flow control (`RlpsFanout`):** a viewer's *backlog* = bytes sent to it − `processed` (in the network or
  in its decode queue; reliable RemoteEvents cannot be recalled). Its *window* = max(64 KiB, 0.5 s × its delivery rate),
  the delivery rate being the windowed maximum (5 s) of samples (bytes processed during a message's flight ÷ flight
  time). A frame is sent to a **live** viewer unless its backlog is non-zero and backlog + frame > window: then the
  viewer is **held** (only status messages reach it). When its backlog is zero it rejoins: it is sent exactly the
  played frames after the last one it was sent (no reset), or — if that would exceed 24 frames, 8 MiB or 2 × the
  keyframe + max(its window, 128 KiB) — it **waits** for the next keyframe, which the server requests with `fresh=1` (at most every
  2 s). `sync` (join, desync) is answered the same way, starting with `("reset")` and the status, from the keyframe;
  a sync arriving before the previous answer was processed, or within 1 s of it, is ignored. Status messages go to
  every viewer immediately; STOPPED reaches a held viewer after at most its window of backlog.
* **Rate (delay-based AIMD, every 0.5 s, D-0013):** every ack yields a delay sample per viewer: send time of the
  newest fully processed message → ack time, minus the ack's `ageMs`. Its minimum over the last 10 s is the viewer's
  *base delay* (network + decode, no queue); the smoothed excess is its *queueing delay*, minus its reported decode
  wait (that is CPU, handled by the frame rate) — the time bytes spend in Roblox's send queue. An unacknowledged
  message older than base + 0.15 s counts as queued too. Over the viewers past a 1 s warm-up (live or held) the
  **lower median** drives the rate: queue > 3 × `TargetQueueMs` (100 ms) or lag > 2 × `TargetLagSeconds` (0.6 s) →
  rate = min(rate × 0.7, 0.85 × the median delivery rate) (the queue drains); queue > target or lag > limit → × 0.9;
  queue < target/2 and the stream used ≥ 60 % of the rate and rate < 1.25 × the measured delivery rate → × 1.04
  (× 1.12 below target/4) + 10 kB/s. Clamped to [`MinBytesPerSecond` 30 kB/s, `MaxBytesPerSecond`], starting at
  `StartBytesPerSecond` (500 kB/s); reported as `rate` on every poll.
* **Frame rate:** fps cap = `ClientDecodeBudgetMs × 60 × 0.7 / decodeMsPerFrame` for the lower-median decode cost of
  the live viewers (drops at once, rises by ≤ 2 fps per step; × 0.8 when lag is high or the median decode wait
  exceeds `TargetQueueMs`); reported as `fps`. The desktop
  app skips captures to respect it.
* **Encoder budget:** token bucket at `rate` (capacity rate × 0.25 s: small bursts, because a burst waits in the
  players' network queues; keyframes may overdraw); per frame, moving tiles go lossless if they fit, else DCT at the
  best quality that fits (large moving areas as DCT2 groups); tiles that stopped moving are refined to lossless with
  the remaining budget; scrolled content is sent as COPY tiles; a frame that cannot fit at the lowest quality is skipped
  (the next frame carries its changes).
* **Diagnostics** (server script attributes): `RateBps`, `LagMs` (the median viewer's delay), `QueueMs` (its network
  queueing delay), `DecodeWaitMs` (its decode-queue wait), `MaxLagMs`, `FpsCap`, `Viewers`, `LaggingViewers` (held or
  waiting), `ForwardFps`.
