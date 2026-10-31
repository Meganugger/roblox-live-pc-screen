# ARCHITECTURE.md

_Architecture selected in D-0002; stream design D-0006…D-0009. Wire format (normative): `docs/PROTOCOL.md`._

```
Windows desktop ─mss/DXGI─► desktop app (Python)                        Roblox game server (Luau)               Roblox clients (Luau)
                            capture → INTER_AREA resize → RGBA          one poll loop: RequestAsync              time-budgeted decode queue
                            hybrid encoder at the reported byte rate:   bundles of frames (batch 150 ms)         RAW / DCT (bit-exact) / COPY tiles
                            lossless | DCT | COPY tiles, refinement     relay chain, playout at capture spacing  one EditableImage, SurfaceGui on the TV
                            chain ring, frame service 127.0.0.1:8787    fan-out with per-viewer flow control     acks: processed bytes + decode ms
                            GET /v1/frames ◄──tunnel (HTTPS)── poll ──► one reliable RemoteEvent (buffers) ────► ("sync" / "ack") back to the server
```

## Components

| Component | Path | Responsibility |
| --- | --- | --- |
| Codec + protocol (Python) | `desktop/rlps/protocol.py`, `codec.py`, `dct.py`, `hybrid.py` | tiles, bit-exact DCT, hybrid encoder with rate control and scroll copies, parts / containers / bundles, reference decoder |
| Capture | `desktop/rlps/capture.py`, `windows.py` | `mss` (GDI) or DXGI (`dxcam`) monitor / region capture; one window or one browser tab's page via `PrintWindow` (Windows); resize with integer factors + letterbox |
| Frame service | `desktop/rlps/server.py` | bearer auth, rate limits, long-poll, encode-once chain ring, bundles, `/v1/probe` |
| App | `desktop/rlps/app.py` | CLI / Tk window, explicit Start / Stop, sharing indicator, profiles, token config |
| Roblox shared | `roblox/src/shared/` | protocol constants, container / part / bundle decoder, `RlpsDct`, frame assembler with dirty rectangles (`RlpsClientCore`), view math (`RlpsView`), base64 fallback |
| Roblox server | `roblox/src/server/` | `RlpsServer` (poll loop, playout, rate control, diagnostics), `RlpsRelayCore` (chain validation, poll cursor, status), `RlpsFanout` (played history, per-viewer delivery) |
| Roblox client | `roblox/src/client/` | decode queue, dirty-rectangle redraws with visibility culling, EditableImage shown on every tagged screen + full screen + mini player, cinema camera, viewer controls, status screens, acks |
| TV model | `roblox/models/RlpsTV.model.json` → `Workspace.RlpsTV` (Rojo) | screen part tagged `RlpsScreen` (16×9 studs), bezel, neck, base |
| Windows scripts | `scripts/windows/*.bat` | setup, show token, start app, start quick tunnel, emergency stop |
| Tests | `desktop/tests/`, `roblox/tests/`, `tests/e2e/` | unit tests, cross-language Luau specs, live pipeline test under a Lune engine emulation (`docs/testing/E2E.md`) |

## How a frame travels

1. **Capture and encode once** (`hybrid.py`, D-0007). Each 16×16 tile of the new frame is compared with the picture
   the clients have; the encoder keeps that picture bit-exactly. Moving tiles go **lossless** if the byte budget allows,
   else **DCT** (YCbCr 4:2:0, JPEG tables, best quality that fits). Scrolled content becomes 5-byte **COPY** tiles from
   the previous picture. Tiles that stopped moving are **refined to lossless** with the remaining budget, so a still
   screen becomes a pixel-exact copy. The budget is a token bucket at the rate Roblox reports; the frame rate obeys the
   reported fps cap. Records go into a chain ring (keyframe, then deltas).
2. **Poll** (`server.py`, `RlpsServer`). One long-poll per experience server returns a **bundle** of every record newer
   than the poller's position (plus 150 ms of batching), so 500 requests/min never cap the frame rate. Bodies are raw
   bytes once `/v1/probe` proved them intact, base64 otherwise. While sharing is off the server polls with `idle=1`
   and the service holds the poll until Start (picture ≈ 1 s after Start; TV off ≈ 0.2 s after Stop, D-0006).
3. **Relay and play out** (`RlpsRelayCore`). Only containers that extend the chain are forwarded; anything else is
   dropped and the chain is re-requested from a keyframe (`key=1`). Containers are played out at their capture spacing.
4. **Fan out** (`RlpsFanout`, D-0009). The played history (last keyframe + later frames) serves late joiners and
   desynced clients (`sync`). Each viewer's backlog — bytes sent minus bytes it reported processed — stays within
   max(128 KiB, 1 s × its measured delivery rate). A viewer whose window is full is *held*; once drained it receives
   exactly the frames it missed, or waits for the next keyframe when that is cheaper (requested with `fresh=1`: the
   chain continues, the next capture is a keyframe). Status messages, Stop included, reach every viewer at once.
5. **Decode and show** (`RlpsClient`, `RlpsClientCore`, D-0011). Clients decode within a per-Heartbeat time budget and
   redraw once per game frame — only the **dirty rectangles** (runs of changed 16 px cells, at most 12, else their
   bounding box) are copied (pooled buffers) and written to the one EditableImage that every view shows: each tagged
   TV screen, the **full-screen** overlay, the **mini player**; **cinema** frames a TV with the camera. Redraws are
   skipped while no picture is visible (screens out of range, behind the camera or seen from behind, no overlay
   open) and far screens are redrawn at ≤ 10 Hz; frames are still decoded so the picture is exact when it comes back.
   Clients acknowledge processed bytes and decode time (≤ 10/s).
6. **Adapt** (`RlpsServer`, D-0008/D-0009). Every 0.5 s the byte rate follows the **median** viewer's delay (AIMD) and
   the fps cap its decode time; both go to the PC with every poll. A minority of slow viewers is held and caught up
   instead of degrading the stream for everyone.

## Where the safeguards live

Start / Stop only on the PC, visible indicator, authenticated single-route service on 127.0.0.1, token as a Roblox
secret, strict validation on both decoders, optional `ViewerUserIds` allowlist: `SECURITY.md`.
