# docs/research/EXISTING_PROJECTS.md — Existing Roblox screen-sharing implementations (R2: T-0004…T-0007)

Studied for design lessons only. **No third-party code is copied** into this repository (ScreenBlox is GPL-3.0; other
licences are recorded per project). Labels: **[CODE]** source read (static review), **[COMMUNITY]** forum/Reddit claim,
**[TESTED]** executed by the agent, **[CALCULATED]**. Findings live in `FINDINGS_LOG.md`, sources in `SOURCE_REGISTER.md`.

## 1. ScreenBlox / "ScreenShare | Free Game Source" — Reb0rnEnder (T-0004)

Status: **in progress** — Python side inspected (S-0029 @ `b873f78`); Roblox side (`v4.7.rbxl`) and the full DevForum
thread (S-0028) still to read.

| Aspect | What the code does | Evidence |
| --- | --- | --- |
| Identity | GitHub `Reb0rnEnder/ScreenBlox` ("Send video data to roblox games"), GPL-3.0, v5.2, 17 commits 2024-08-17…2026-01-12; same project as the DevForum resource "ScreenShare \| Free Game Source [UPDATED] [OVERHAUL]" (topic 2823814, Feb 2024) | F-0023 |
| Capture | `PIL.ImageGrab.grab()` (primary monitor) **inside each HTTP request**, resized to 190×90 by default | F-0024 |
| Encoding | JSON `{"HEX": ["rrggbb", …]}`, one quoted string per pixel; no compression, deltas, frame IDs or caching; ≈ 153,910 B per 190×90 frame | F-0024 |
| Transport | Flask + gevent `WSGIServer` on `http://0.0.0.0:8080`: plain HTTP, no auth, no rate limit; made public through a third-party TCP tunnel (playit; maintainer notes suggest tunnel.pyjam.as or self-hosted FRP); the game presumably polls with `HttpService` (to confirm in `v4.7.rbxl`) | F-0024 |
| Reconstruction | Forum disclaimer: the game "color[s] frames accordingly" (GUI Frames / parts per pixel?); a reply recommends `EditableImage` + `WritePixels` "instead of drawing" — **to confirm in `v4.7.rbxl`** | F-0023 |
| Extra features | Video mode (local video pre-converted to 60 fps hex frames = pre-recorded media), remote key presses, remote mouse clicks, kill/relaunch Roblox | F-0024, F-0025 |
| Security | No authentication anywhere; input injection and process control gated only by local config flags; `Launcher.py` runs code downloaded at run time without any integrity check | F-0025 |
| Defects (static review) | Import-time route selection ignores saved `video_mode`; numeric config edits are stored as strings | F-0026 |

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
- Roblox side (`v4.7.rbxl`): which scripts poll, from server or client, at what rate; how pixels are drawn (Frames vs
  parts vs EditableImage); replication to other players; URL configuration; client-count limits.
- DevForum thread: reported frame rates/lag, tunnel problems, ToS/moderation discussion, successor versions.
