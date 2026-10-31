# docs/research/EXISTING_PROJECTS.md — Existing Roblox screen-sharing implementations (R2: T-0004…T-0007)

Studied for design lessons only. **No third-party code is copied** into this repository (ScreenBlox is GPL-3.0; other
licences are recorded per project). Labels: **[CODE]** source read (static review), **[COMMUNITY]** forum/Reddit claim,
**[TESTED]** executed by the agent, **[CALCULATED]**. Findings live in `FINDINGS_LOG.md`, sources in `SOURCE_REGISTER.md`.

## 1. ScreenBlox / "ScreenShare | Free Game Source" — Reb0rnEnder (T-0004)

Status: **done** (T-0004) — Python side (S-0029 @ `b873f78`), Roblox side (`v4.7.rbxl`, parsed with
`scripts/agent/rbxl_dump_scripts.py`) and the full DevForum thread (S-0028, 33 posts) inspected.

| Aspect | What the code does | Evidence |
| --- | --- | --- |
| Identity | GitHub `Reb0rnEnder/ScreenBlox` ("Send video data to roblox games"), GPL-3.0, v5.2, 17 commits 2024-08-17…2026-01-12; same project as the DevForum resource "ScreenShare \| Free Game Source [UPDATED] [OVERHAUL]" (topic 2823814, Feb 2024) | F-0023 |
| Capture | `PIL.ImageGrab.grab()` (primary monitor) **inside each HTTP request**, resized to 190×90 by default | F-0024 |
| Encoding | JSON `{"HEX": ["rrggbb", …]}`, one quoted string per pixel; no compression, deltas, frame IDs or caching; ≈ 153,910 B per 190×90 frame | F-0024 |
| Transport | Flask + gevent `WSGIServer` on `http://0.0.0.0:8080`: plain HTTP, no auth, no rate limit; made public through a third-party TCP tunnel (playit; maintainer notes suggest tunnel.pyjam.as or self-hosted FRP). Roblox **server** `Script` polls with `HttpService:GetAsync` + `JSONDecode` back-to-back (no wait/pacing/backoff) | F-0024, F-0027 |
| Reconstruction | **One GUI `Frame` per pixel** (UIGridLayout, 17,100 Frames at 190×90) on a SurfaceGui in Workspace; the server sets `BackgroundColor3 = Color3.fromHex()` for changed pixels, so each changed pixel replicates to every client as a property change. No EditableImage, no RemoteEvent frame transport (a forum reply recommends EditableImage `WritePixels`) | F-0023, F-0027 |
| Extra features | Video mode (local video pre-converted to 60 fps hex frames = pre-recorded media), remote key presses, remote mouse clicks, kill/relaunch Roblox | F-0024, F-0025 |
| Security | No authentication anywhere; input injection and process control gated only by local config flags; `Launcher.py` runs code downloaded at run time without any integrity check; in Roblox any player can set the polling URL (`SendURL`), send key presses (`SendKEY`) and trigger Roblox relaunch (`SendGAME`) — no authorization | F-0025, F-0028 |
| Community reports (thread) | No fps/latency/bandwidth figure anywhere; higher resolutions crashed clients (old version); a Feb 2024 "480p (no lag)" CanvasDraw/EditableImage experiment is not in the released backup code; "RemoteEvent limit 900 Bytes" claim (contradicts the docs for reliable remotes); playit.gg/ngrok tunnels; "works in Studio, server offline in Roblox" (fixed, cause unstated); ToS "unless not Roblox-friendly images"; original repo lost Aug 2024 → GitHub repo is a partial backup; no successor linked | F-0029…F-0033 |
| Defects (static review) | Python: import-time route selection ignores saved `video_mode`; numeric config edits stored as strings. Luau: `GetChildren()` includes the UIGridLayout → likely 1-pixel shift hidden by `pcall`; `"ERROR"` string result → silent spin without backoff | F-0026, F-0027 |

### Lessons adopted for this project
1. Keep the proven topology (desktop app → public HTTPS endpoint → Roblox server `RequestAsync` poll → clients), but
   **decouple capture from polling** (capture loop + latest-frame buffer + monotonically increasing frame IDs).
2. Replace JSON-per-pixel with a **binary, compressed, delta-capable** format (zstd decoded natively by `EncodingService`,
   F-0016); measure bytes/pixel on real desktop content in T-0009 against this ≈ 9 B/pixel baseline.
3. **Authenticate every request** (bearer secret from the Roblox secrets store, F-0011) and use HTTPS only.
4. **No inbound control surface on the PC**: no input injection, no process control, no self-updater that executes
   downloaded code (spec safeguards, `SECURITY.md`).
5. Load and type-check configuration before it drives behaviour; bound memory use.
6. **Measure our own fps, latency and bytes per frame** — the community reports none (F-0029).
7. Check live-server connectivity separately from Studio and show a "relay unreachable" state (F-0031).
8. Treat the in-world screen as public: explicit start, visible indicator, instant stop, optional trusted-player
   restriction; content-policy check before publishing guidance (F-0032, T-0016).

### Open questions
- ~~Roblox side (`v4.7.rbxl`)~~ — answered by F-0027/F-0028 (server polls; per-pixel replicated Frames; no auth).
- ~~DevForum thread (S-0028)~~ — answered by F-0029…F-0033 (no fps data; tunnels; ToS remark; repo backup history).
- Remaining (T-0007): forks of `Reb0rnEnder/ScreenBlox`; SuperWoahGuy64's modification (screenshot only, no code).

---

# Survey of the other public projects (T-0005, T-0006, T-0007 — 29th session, 2026-10-31)

Method: `search_repositories` (queries "Screen-Sharing-in-Roblox", "RSSP roblox screen", "roblox screen share",
"roblox editableimage video", "roblox screen stream …"), `git clone` of every hit, full read of the Python and Luau
sources, Roblox places parsed with `scripts/agent/rbxl_dump_scripts.py`, RSSP release archives extracted with `bsdtar`
(**read only — nothing from these projects was executed**; RSSP v2.2.2 ships "RAT functionality"). No code is copied
into this repository; ideas are credited below and in `DECISIONS.md` D-0007.

## 2. Icy-Monster/Screen-Sharing-in-Roblox (T-0005) — MIT © 2023 icyCYBERwhynot, **archived**, 13★, last commit 2024-05-21

| Aspect | What the code does | Evidence |
| --- | --- | --- |
| Capture | `PIL.ImageGrab.grab()` inside the Flask request handler, bilinear resize to 400×225, `time.sleep` pacing per frame | `ScreenNew.py`, `ScreenOld.py` |
| Encoding (old) | hex strings per pixel; "unchanged since last frame" runs as `N.0` and "same colour" runs as `N.1` floats, optional 12-bit colour (`RGBToCompHex`) | `ScreenOld.py` |
| Encoding (new) | JSON array of **floats** (r/255, g/255, b/255, 1) per pixel for the 2023 EditableImage beta `WritePixels` — ~20 bytes of JSON per pixel | `ScreenNew.py` |
| **Batching** | `FrameGroups`: N frames per HTTP response; README: "Max FPS is FrameGroups × 8, due to max Roblox HTTP limit" | `ScreenNew.py` settings |
| Transport | server `Script` `PostAsync` → `JSONDecode` → `RemoteEvent:FireAllClients(table)`; a new coroutine per `1/FPS` without awaiting the previous one (overlapping requests); `HTTPAdress = "http://127.0.0.1:1241"`; port forwarding / playit.gg for live servers; no auth | `RequestManager.Script` |
| Reconstruction | (a) one MeshPart per pixel coloured from the client; (b) `Instance.new("EditableImage")` + `:Resize` + `:WritePixels(float table)` — the **pre-2024 beta API, removed since** (current: `AssetService:CreateEditableImage`, `WritePixelsBuffer`) | `ScreenSharingTable`, `EditableImageTest` LocalScripts |
| **Client playout** | plays a received group frame by frame with `task.wait(1/F − decodeTime)` | `ScreenSharingTable` |
| Defects | delta state `LastFrame` is one global for all Roblox servers (two servers corrupt each other's deltas); no frame ids → any lost/duplicated response desyncs until a full refresh | static review |

Forks: `jojogamezHub/RobloxScreenShare` (MIT, 2023-10, same design, adds "host anywhere" notes).
`camymarii/ScreenStreamerForRoblox` (2025-11, Replit-generated Tk GUI around the same `ScreenNew.py`, no auth).

## 3. ssavnayt/RSSP (T-0006) — MIT © 2025 "Alex", **archived**, code only in release archives

| Aspect | What the code does | Evidence |
| --- | --- | --- |
| Capture | `dxcam` (DXGI Desktop Duplication) with `mss` fallback; `cv2.resize(INTER_AREA)` by an integer divisor `SS1` (default 8) | `shared/screen_service.py` (v2.2) |
| Transport v1/v2 | `GET /getscreenimg/{dxcam,mss}?login=…&password=…` returns **raw RGB bytes** (`application/octet-stream`); the Roblox server reads them with `GetAsync` and `string.byte`, checking `#rgbData == w*h*3` — community evidence that binary response bodies reach Roblox intact (not verified by us) | `ServerScriptService.Main` in `ScreenClient_screenimgdeprecated.rbxl`; `modules/getscreenimg/*` |
| Transport v2.2 | SSE via `HttpService:CreateWebStreamClient` ("slow", and Studio-only per official docs, F-0010); frames as hex in JSON | `modules/sse/execute.py`, release notes |
| Reconstruction | one `Part` **with a ClickDetector per pixel**, coloured **on the server** (replicates every pixel change to every client), `RunService.Heartbeat` fetch loop | `ServerScriptService.Main` |
| Security | login/password in the query string; any player's click moves the owner's mouse and clicks (`/movemouse`, `/click`); remote key presses, app launch, shell command execution, clipboard, shutdown; v2.2.2 "auto RAT" (registry autostart) | `Main`, `Script`, release notes |
| Experiments | v1 `dct.py`: JPEG-in-hex test (never wired to Roblox) | `RSSPv1.rar` |

## 4. MahanBig/roblox-screen-stream — MIT, created **2026-10-28** (3 days before this survey), 3 commits

The most advanced public implementation found. Same topology as ours (sender → tunnel → server poll → RemoteEvent →
client EditableImage).

| Aspect | What the code does | Evidence |
| --- | --- | --- |
| Codec | **lossy DCT video codec**: YCbCr 4:2:0, 8×8 integer IDCT (bit-exact Python ↔ Luau), JPEG quantization tables scaled by 40 levels, **closed-loop inter frames** (residual vs. the decoder's own reconstruction), dead-zone rounding, coefficients planar by zigzag index, sign-folded, zstd (decoded natively with `EncodingService`) | `sender/codec.py`, `roblox/StreamDecoder.luau` |
| Rate control | token bucket at ¾ of the budget; per frame a galloping/bisection search for the finest quantizer that fits; frame skipped when nothing fits; a still screen "keeps refining towards near-lossless" | `sender/stream_server.py`, `codec.py` |
| Batching | `GET /frames?t=TOKEN&since=SEQ` returns every record newer than SEQ (base64) — several frames per request | `stream_server.py`, `StreamServer.server.luau` |
| Client | `--!native --!optimize 2` decoder; decode **time-sliced in a coroutine** (6 ms per game frame); playout queue at the stream fps, skips ahead when > 1 s behind; one EditableImage shared by every screen | `StreamClient.client.luau` |
| Claims | 640×352 @ 15 fps in Studio (320 KB/s per player); 320×176 @ 15 fps at 40 KB/s "safe for live servers"; **live servers not tested** by the author | README |
| Weak points | token in the URL query (logged by proxies); `TOKEN` hard-coded in a server script (no secrets store); no stop/indicator semantics; whole-frame DCT also for text (blurry until refined); `(Enum.NormalId :: any)[face]` (raises for unknown names) | static review |

## 5. OddSuvius/luavid — MIT **with attribution requirement**, 2026-10-17

Offline video codec with a pure-Luau decoder (pre-encoded video stored as base64 in ModuleScripts — not streaming).
Measured by the author: 160×120 decoded in 0.7 ms/frame with `--!native` vs 2.3 ms interpreted (**3.4×**), 60 Hz
playback; "bytes, not cycles, are the real wall"; YCbCr with half-resolution colour; crossfade between decoded frames
and a 4×4 Bayer dither to hide banding. Useful as performance evidence for `--!native` in client decoders. No code used
(the licence would require visible credit).

## 6. Other hits (inspected, not useful beyond the note)

| Repo | What it is |
| --- | --- |
| `Harmonyasha/Roblox-ScreenShare` (2023–2026) | Flask + ngrok; text "r,g,b;" per pixel; runs via `require(15681840577)` "in a server-side executor" (a backdoor-style remote module) |
| `LoneHEX/robloxstream` (2022) | requires an exploit client (`syn.websocket`, `Drawing.new`), not usable in a legitimate game |
| `robotgamesrbx-glitch/Roblox-screen-share-controllable-account` (2025) | Flask JSON colour list 192×108 + remote key presses |
| `DeepXx86/video-to-roblox` (2025) | pre-recorded 1-bit packed video frames in ModuleScripts (not live) |
| `bruvie-fr/roblox-video-player` @ `4a66ac9` (2026-09, MIT + Commons Clause) — found in the forum research (T-0026) | videos from a link (yt-dlp + ffmpeg) encoded on the fly into a block codec (768×432 at 30 fps, ~100 kB/s), polled by the Roblox server and fanned out over a RemoteEvent (the same shape as ours), **audio by additive resynthesis** (384 looping sine `AudioPlayer`s, 1024-point FFT per frame), a one-pixel write probe because `CreateEditableImage` succeeds while the API is disabled, and a 192×108 Frame-grid fallback for owners without ID verification. Taken: the probe (E2E-30). Not taken: the Frame grid (D-0012); audio is T-0028 |
| `Stud-del/screenshare`, `SipinSlowly/roblox-screenshare-method-v2`, `decompi/Pixel-Stream-Player`, `DevGeah/roblox-screenshare-scripts` (2024–2026) | part grids or CanvasDraw with JSON frames over playit.gg / ngrok; one HTTP request per frame (~8 fps); nothing new |

The full forum survey (Reddit, DevForum, official announcements) is in [`FORUM_FINDINGS.md`](FORUM_FINDINGS.md).

## 7. What this changes for our project (D-0007)

1. **Batch several frames per HTTP response** (Icy-Monster `FrameGroups`, MahanBig `since=SEQ`): 500 requests/min no
   longer caps the frame rate at ~8 fps.
2. **Play batched frames out at their capture spacing** (both) instead of in bursts.
3. **Lossy DCT for moving content** (MahanBig): ~30× fewer bytes than lossless tiles for video-like content. We keep
   lossless tiles for still content (crisp text) and **refine moving tiles to lossless once they stop changing**.
4. **Time-sliced, `--!native` client decoding** (MahanBig, luavid measurements).
5. **Faster capture**: `cv2.resize(INTER_AREA)` and optional DXGI Desktop Duplication (`dxcam`) as RSSP does.
6. **Binary response bodies** may work (RSSP) → probe once and fall back to base64 automatically.
7. Confirmed anti-patterns to keep avoiding: per-pixel Instances, server-side colouring, JSON per pixel, credentials in
   URLs or scripts, any remote input/command surface.
