# Live pipeline test (`tests/e2e/`)

The project's highest verification level that can run without Roblox: real operating-system screen capture, the real
frame service over real HTTP, and the **unmodified** Roblox server and client scripts, with only the Roblox engine
replaced by a small emulation.

```
painter.py (full-screen window with known scenes)
   │  real pixels on a real display (Xvfb on Linux, the desktop on Windows)
   ▼
rlps.capture.MssSource ─► rlps.app.SharingController / CaptureLoop ─► rlps.server.FrameService (127.0.0.1, token)
                                                                              │ HTTP long-poll
roblox_emulator.luau (Lune) ──────────────────────────────────────────────────┘
   ├─ game server peer: RlpsServer.server.luau + RlpsRelayCore/Protocol/Decoder/Base64 (as in default.project.json)
   │     HttpService:RequestAsync → real HTTP; GetSecret → server-only secret; RemoteEvent → ordered, copied delivery
   └─ client peers (Alice, Bob, …): RlpsClient.client.luau + RlpsClientCore/Decoder/Protocol
         EncodingService zstd (Lune serde) → AssetService:CreateEditableImage → WritePixelsBuffer → SurfaceGui on the TV
```

`run_e2e.py` drives both sides and asserts what a player would see, reading the client's actual GUI objects
(`SurfaceGui ⟩ Background ⟩ Picture/Status/LiveBadge`) and the SHA-256 of the EditableImage pixels, which must equal
`codec.expand_to_rgba(<newest frame in the frame service>)` byte for byte. Viewer actions are injected through the
control directory: `press-<client>-<ButtonName>` fires a button's `Activated`, `key-<client>-<KeyCode>` an
`InputBegan`, `look-<client>-away|tv` turns that client's camera; the state file reports the overlays, the camera
(type, distance and aim at the screen), the cinema blur and held movement, and the client's redraw counters. The
emulator implements CFrame/Vector3 math, Roblox's secret-domain patterns, ContextActionService, UserInputService and
Lighting as far as the scripts use them.

## Checks

| ID | What is proven |
| --- | --- |
| E2E-01/02 | before Start: TV says "Screen sharing is off", no image exists, SurfaceGui adorned to the tagged part's Front face |
| E2E-03…06 | after Start: the EditableImage equals the newest captured frame (SHA-256 and full snapshot), LIVE badge, 480×270 geometry, rectangle colour at the right position, fine checkerboard detail preserved |
| E2E-07 | a late joiner gets the same picture from the server's history (sync path) |
| E2E-08/09 | a desktop change reaches both TVs through the delta path; old content gone |
| E2E-10 | 9 rapid changes: chain stays valid, both settle on the exact newest frame |
| E2E-11/12 | frame service outage → "Screen unavailable" on both TVs, picture hidden; service back → exact picture again |
| E2E-13 | Stop → both TVs "Screen sharing is off", EditableImages destroyed, no frames left in the service |
| E2E-14 | no script error on the server or any client during the run |
| E2E-15 | wrong secret → 401 message on the TV; no image is ever created on the client |
| E2E-16 | pacing: with the rate pinned to 3000 B/s the forwarded stream stays within budget while the desktop changes ~2.7×/s, and the final frame is exact |
| E2E-18 | moving grain at 150 kB/s: the encoder emits lossy DCT frames and the client shows ≥ 3 distinct **lossy** pictures bit-exactly (real Luau `RlpsDct`), then the still picture refines to the exact captured desktop |
| E2E-19 | same with binary bodies mangled in transit (emulated text-only HTTP stack): the probe falls back to base64 |
| E2E-20 | congestion control: the rate grows above its start with one fast viewer; a viewer throttled to 10 kB/s makes it back off or is held (`LaggingViewers`), the fast viewer keeps receiving frames, both end exact |
| E2E-21 | scrolling a text page through a non-integer downscale (1280 → 1024): more than half of the changed tiles are COPY tiles, the 15 steps cost less than ⅔ of resending them as lossless keyframes (refinement in the pauses varies with load: 262–386 kB measured), the page ends pixel-exact |
| E2E-22 | secret domain: with `trycloudflare.com` (no wildcard) Roblox refuses the secret — the TV names `*.trycloudflare.com` and the host, no pixel arrives; with `*.trycloudflare.com` the desktop appears (the emulator enforces Roblox's documented domain patterns) |
| E2E-23 | a change in two opposite screen corners redraws only those tiles (≤ 2 % of the picture) — dirty rectangles, not their bounding box (≈ the whole screen) |
| E2E-24 | Alice looks away from the TV: no redraws while frames are still decoded (Bob keeps updating); looking back shows the exact current picture |
| E2E-25 | full screen (key F) and mini player show the same live EditableImage as the TV; Fill crops; Exit, expand and the key switch modes; the controls hide while a mode is open |
| E2E-26 | cinema: the camera looks straight at the TV from the computed framing distance, background blur and held movement; leaving restores the default camera |
| E2E-27 | `ViewerModes = cinema`: only the cinema button is offered, F does nothing; a non-authorized player gets no viewer controls |

## Run it

```bash
# Linux: Xvfb + python-xlib; any OS: Lune 0.10.4 on PATH and desktop/requirements.txt
pip install -r desktop/requirements.txt python-xlib
python3 tests/e2e/run_e2e.py --out build/e2e          # ~60 s; exit code 0 = all checks passed
```

Output: `build/e2e/report.json` (checks + metrics), `tv-<player>-<scene>.png` (what the TV showed),
`emulator-*.log`. CI runs it on Ubuntu (Xvfb) and on a Windows runner (real desktop) — `.github/workflows/ci.yml`.

## What it does not prove (owner tests, `KNOWN_ISSUES.md` KI-0002)

The emulation implements only the documented behaviour the scripts rely on. It cannot show: Roblox's real network
throughput and RemoteEvent limits, real `RequestAsync` timeouts and response-size limits, the client EditableImage
memory budget, the actual rendering of the SurfaceGui, Creator Dashboard settings, or the public tunnel hop (emulated
by rewriting `https://rlps-e2e.test` to the local service). These need Roblox Studio and a published server:
`docs/deployment/INSTALL.md` parts D and E are the acceptance procedure.
