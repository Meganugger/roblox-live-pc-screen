# docs/research/EXISTING_PROJECTS.md — Existing Roblox screen-sharing implementations (R2: T-0004…T-0007)

Studied for design lessons only. **No third-party code is copied** into this repository (ScreenBlox is GPL-3.0; other
licences are recorded per project). Labels: **[CODE]** source read (static review), **[COMMUNITY]** forum/Reddit claim,
**[TESTED]** executed by the agent, **[CALCULATED]**. Findings live in `FINDINGS_LOG.md`, sources in `SOURCE_REGISTER.md`.

## 1. ScreenBlox / "ScreenShare | Free Game Source" — Reb0rnEnder (T-0004)

Status: **in progress** — Python side (S-0029 @ `b873f78`) and Roblox side (`v4.7.rbxl`, parsed with
`scripts/agent/rbxl_dump_scripts.py`) inspected; the full DevForum thread (S-0028) is still to read.

| Aspect | What the code does | Evidence |
| --- | --- | --- |
| Identity | GitHub `Reb0rnEnder/ScreenBlox` ("Send video data to roblox games"), GPL-3.0, v5.2, 17 commits 2024-08-17…2026-01-12; same project as the DevForum resource "ScreenShare \| Free Game Source [UPDATED] [OVERHAUL]" (topic 2823814, Feb 2024) | F-0023 |
| Capture | `PIL.ImageGrab.grab()` (primary monitor) **inside each HTTP request**, resized to 190×90 by default | F-0024 |
| Encoding | JSON `{"HEX": ["rrggbb", …]}`, one quoted string per pixel; no compression, deltas, frame IDs or caching; ≈ 153,910 B per 190×90 frame | F-0024 |
| Transport | Flask + gevent `WSGIServer` on `http://0.0.0.0:8080`: plain HTTP, no auth, no rate limit; made public through a third-party TCP tunnel (playit; maintainer notes suggest tunnel.pyjam.as or self-hosted FRP). Roblox **server** `Script` polls with `HttpService:GetAsync` + `JSONDecode` back-to-back (no wait/pacing/backoff) | F-0024, F-0027 |
| Reconstruction | **One GUI `Frame` per pixel** (UIGridLayout, 17,100 Frames at 190×90) on a SurfaceGui in Workspace; the server sets `BackgroundColor3 = Color3.fromHex()` for changed pixels, so each changed pixel replicates to every client as a property change. No EditableImage, no RemoteEvent frame transport (a forum reply recommends EditableImage `WritePixels`) | F-0023, F-0027 |
| Extra features | Video mode (local video pre-converted to 60 fps hex frames = pre-recorded media), remote key presses, remote mouse clicks, kill/relaunch Roblox | F-0024, F-0025 |
| Security | No authentication anywhere; input injection and process control gated only by local config flags; `Launcher.py` runs code downloaded at run time without any integrity check; in Roblox any player can set the polling URL (`SendURL`), send key presses (`SendKEY`) and trigger Roblox relaunch (`SendGAME`) — no authorization | F-0025, F-0028 |
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

### Open questions (T-0004 part 2)
- ~~Roblox side (`v4.7.rbxl`)~~ — answered by F-0027/F-0028 (server polls; per-pixel replicated Frames; no auth).
- DevForum thread (S-0028): reported frame rates/lag, tunnel problems, ToS/moderation discussion, successor versions.
