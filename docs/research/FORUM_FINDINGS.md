# Forum research: what developers discuss about in-game screen sharing (T-0026)

_Searched 2026-10-31 (29th session). Owner request: "search public forums like Reddit about public projects like
these and note everything they discuss, to make our project as good as possible."_

## Method and coverage

| Forum | Access | What was searched | Read in full |
| --- | --- | --- | --- |
| Reddit | Direct access refused (HTTP 403) → **Arctic Shift** archive API (`arctic-shift.photon-reddit.com`), the same posts and comment trees | 15 title terms × r/robloxgamedev, r/roblox, r/RobloxDevelopers, r/robloxhackers → 400 candidate posts, **141 relevant** | 17 threads incl. comment trees: 1sp88kg (the owner's link), 1sovo51, 1sq1agw, t0oqel (149 comments), unf28z (128), 10ug26x, 1d65m3d, lti097, 1fovuwm, 5lg7y6, 6jx3gc, 1l0eqdk, 1elmm3i, 1m3rxe3, jxgr7z, 12y5zaq, mnq61f |
| Roblox Developer Forum | Discourse JSON API | 80 queries → **1,383 + 620 topics** listed | 33 topics in full (every post), listed below |
| Web | DuckDuckGo | 5 queries | led to the Reddit threads above and to 6 GitHub projects |
| GitHub | clone / MCP | projects named in the threads | `bruvie-fr/roblox-video-player` (source), `Stud-del/screenshare`, `SipinSlowly/roblox-screenshare-method-v2`, `decompi/Pixel-Stream-Player`, `DevGeah/roblox-screenshare-scripts` (READMEs + layout) |
| Official docs | `Roblox/creator-docs` repository | EditableImage, AssetService, AudioPlayer, HttpService | `EditableImage.yaml`, `AssetService.yaml`, `AudioPlayer.yaml` |

DevForum topics read in full: 2612752 *Screen Sharing!* (129 posts), 2087700 *Screen sharing in Roblox* (124), 3127592
*EditableImage Screen "Sharing"*, 4949105 *First live stream in Roblox at 480p and 24fps*, 1684044 *Roblox gui that
shows computer screen in realtime* (43), 2390620 *Screenshare Game*, 4879403 *EditableImages rewritten every frame never
display on some devices*, 4882527 *Feedback on CreateWebStreamClient*, 4021932 *WebSockets Support in Studio* (112),
3905367 *HTTP Streaming: Server-Sent Events* (51), 3267293 *In-experience Mesh & Image APIs in published experiences*
(479, official), 3225681 (293, official), 4541898 *CreateDataModelContent* (150, official), 3818624 *EditableMesh and
EditableImage Improvements* (81, official), 3981479 *Remove required id verification* (49), 3858566 *A complete guide to
EditableImages*, 4754431 *Super Mario 64 natively (20–30 fps)*, 4634716 *Ro2D*, 4630135 *load any video as GIF*,
2423381 / 1154477 *Video Player* (41 / 135), 4950870 *EditableMesh writes ~350× slower on Windows*, 4753653 *Pass2D CPU*,
4805722, 4608885 *EditableSound* (41), 4756578 *stream video & audio into Roblox*, 2848873 *New Audio API* (582,
official), 4852202 *experience unavailable after failing the questionnaire*, 4880208 *Creator Roadmap 2026 Fall*,
and on music through voice chat 3938457, 4616522, 4715118, 3923371.

Labels: **[OFFICIAL]** Roblox staff / documentation · **[COMMUNITY]** a developer's claim · **[CODE]** read in source.

## 1. What people discuss, and where this project stands

### 1.1 Throughput: the 500 requests/minute ceiling

* Nearly every project is stuck at **~8 fps** because it makes one HTTP request per frame (500/min ≈ 8.3/s): the
  owner's link, t0oqel ("0.12 s per request"), 2087700 ("capped at 8 frames per second due to the http get limit"),
  opwip in 1sp88kg. **[COMMUNITY]**
* The answers that work: put several frames in one response (Icy-Monster "chunking", the video-player guide: "3 frames
  per request → 24 fps" **[COMMUNITY]**), and send **only the pixels that changed** (unf28z: "a json object for changed
  pixels since the last requested frame"; Nexaes in 1sp88kg).
* **Here**: bundles of every frame since the poller's position plus 150 ms of batching (D-0007), tile deltas, COPY tiles
  for scrolling, zstd, binary bodies, rate control. 30 fps at 1024×576 is limited by bandwidth and decode time, not by
  the request count. *Nothing to add.*

### 1.2 WebSockets / streaming instead of polling

* Developers wait for WebSockets in live games ("if websocket got released to live games i will use it 100%",
  1sp88kg). **[OFFICIAL]** (4021932, 3905367): `CreateWebStreamClient` (SSE + WebSocket) works **only in Studio**;
  "Any CreateWebStreamClient() requests made in a live experience will be blocked"; at most 4 clients (the docs said 6;
  corrected in 4882527). The Fall 2026 roadmap lists no live-game date.
* **Here**: long-poll + bundles remain the right transport (F-0010 unchanged). *Revisit T-0015 when live support ships.*

### 1.3 Drawing: Parts → Frames → EditableImage

* History: grids of Parts / Frames with one instance per pixel (t0oqel "made of individual parts", 1684044, 2087700 HD at
  "about 2 fps"); GUI trees stop rendering past ~80k Frames (1684044). **[COMMUNITY]**
* EditableImage: "My implementation uses WritePixels once per frame … The worst case is calling WritePixels with a size
  of (1,1)" (2612752 #81); Icy-Monster first found EditableImage *slower*, because it wrote small pieces many times.
  **[COMMUNITY]**
* **[OFFICIAL]** (EditableImage reference): "Only a single EditableImage can be updated per frame on the display side"
  — three images take three frames. Linking one image to several Content properties saves memory.
* **[OFFICIAL]** acknowledged bug (4879403, 2026-09): when ~3.7 MB of EditableImage pixels are rewritten *every frame*
  (8 images), some images never display on some Macs and phones; at 2.36 MB per frame every image updated. "Most likely
  it's on the rendering side. We'll look into this."
* Ro2D (4634716): zero-allocation loop, pooled upload buffers, 32-bit writes, **dirty-region uploads**, optional
  Actor-parallel rasterising of horizontal bands. SM64 (4754431): one EditableImage, whole buffer per frame, 20–30 fps
  with native code; "abysmal on mobile". **[COMMUNITY]**
* **Here**: one EditableImage per client, shown by every view (D-0011); writes only dirty rectangles, ≤ 12 calls, once
  per Heartbeat; pooled buffers; nothing written while no TV is visible. A full redraw (keyframe) is 1024×576×4 =
  **2.36 MB** — exactly the size the bug report found safe; incremental frames are far smaller (E2E-23: 2,048–6,144
  pixels). *Nothing to add; KI-0010 records the bug.*

### 1.4 Codecs and data formats

* JSON arrays of RGB values or hex strings (most hobby projects), base64 (t0oqel), custom formats ("custom encoding
  format (.hlve) … render a single frame at 2 ms … though it requires 30–60 Mbps", 4949105), a block codec at
  "768x432 at 30 fps, ~100 KB/s" (bruvie-fr). **[COMMUNITY]**
* **Here**: hybrid lossless / bit-exact DCT / COPY tiles at the adaptive rate; 768×432 profile video at 2 MB/s and DCT
  quality 92–98 (PERFORMANCE.md). *Nothing to add.*

### 1.5 Tunnels and hosting

* Port forwarding fails often ("works in studio but not in game"); **playit.gg** and **ngrok** are recommended for a
  stable public address (2087700, Stud-del, DevGeah); "Cloudflare is so slow sometimes. But when using localhost, it's
  fast" (4021932 #52). YouTube blocks data-centre IPs, so a VPS cannot fetch YouTube (bruvie-fr README). **[COMMUNITY]**
* **Here**: cloudflared quick tunnel, Tailscale Funnel or a named Cloudflare tunnel (INSTALL A.3); the frame service
  runs on the owner's PC, so there is no YouTube/VPS issue. *Added: a TROUBLESHOOTING note that a quick tunnel adds
  latency and how to compare (KI-0005 already covers the changing URL).*

### 1.6 Moderation, Terms of Use, takedowns (the most discussed topic)

* Repeated claims that screen-sharing games and resources were taken down for bypassing image moderation ("Misuse of
  Roblox Systems", "Evading Safety and Security Systems"; 2612752 #15, #21, #55; 2390620; t0oqel; unf28z), countered by
  "it is only against the rules if you show prohibited content" (2612752 #92–#100). Authors keep their code closed
  "because people could show inappropriate images" (1sp88kg). Suggestions: keep the game private, "only allow
  specific people" (unf28z), an in-game whitelist (5lg7y6). **[COMMUNITY]**
* **[OFFICIAL]** (3267293 *Trust and Safety*):
  * EditableImage in published games requires the **experience owner — or the group owner — to be 13+ and
    ID-verified**, and to opt in (Allow Mesh / Image APIs). Staff (#219): the same applies to Studio *play mode*.
  * Experiences that show users **unmoderated 2D content created outside Roblox moderation must say so in the Content
    Labels questionnaire**; they become **Moderate (13+)**.
  * Tips: "Do not load asset-like content from off-platform sites or unmoderated sources"; make every free-form
    creation **attributable and removable**.
* 4852202: an experience became unavailable after two "incorrectly filled" questionnaire violations. 2390620 #4: sharing
  personal information (names, addresses, e-mails) is not allowed — a desktop shows such things easily. **[COMMUNITY]**
* **Here before this session**: Start/Stop only on the PC, visible indicator, authenticated service, `ViewerUserIds`
  allowlist, owner-only control, window / tab sharing (D-0011).
* **Added now (D-0012)**: an **in-game moderator kill switch** (`ModeratorUserIds` + the owner of a user-owned
  experience: "⛔ Hide screen for everyone" drops every viewer's pixels and stops pulling frames from the PC; the owner
  can also set `Hidden` from the server console; each use is logged with the moderator's name), a **per-player "Hide"**
  (nothing is drawn, and the server sends that player nothing), and INSTALL / SECURITY guidance (ID verification,
  Content Labels questionnaire, private / friends-only experiences, personal information).

### 1.7 "EditableImage not working" and the ID-verification gate

* bruvie-fr (**[CODE]**): "`CreateEditableImage` succeeds even when the API is disabled, and only the write fails.
  Checking creation alone gives you a renderer that looks fine and then throws once per frame forever." It falls back to
  a grid of up to 192×108 Frames for owners who cannot ID-verify.
* 3981479 (49 posts): many developers refuse ID verification; saving the place to a local file avoids the gate in Studio
  only. **[COMMUNITY]**
* **Added now**: the client probes with a one-pixel write right after creating the image. If writing fails, the TV
  says "the owner must enable Allow Mesh / Image APIs (Game Settings > Security; needs a 13+ ID-verified owner)" and
  retries only every 30 s (E2E-30).
* **Rejected**: a Frame-grid fallback. Roblox gates EditableImage behind owner ID verification *to make creators
  accountable for unmoderated imagery*; a renderer whose purpose is to show unmoderated external pictures without that
  gate would defeat the safety measure (D-0012).

### 1.8 Audio (the most requested missing feature)

* "if only there was a way to stream audio" (2612752 #2); "No sound since there's no way for me to parse that to
  ROBLOX" (5lg7y6); feature request *EditableSound* (4608885, 41 posts); *stream video & audio for 1M+ Robux*
  (4756578). **[COMMUNITY]**
* **[OFFICIAL]** facts: the Audio API reference has 26 `Audio*` classes — sources are `AudioPlayer` (an uploaded asset;
  `PlaybackSpeed`, `Volume`, `TimePosition`), `AudioDeviceInput` (a player's microphone, i.e. voice chat) and
  `AudioTextToSpeech` (text only); the rest are effects, analyzers, emitters / listeners and wires. **No oscillator /
  generator and no raw-sample input** (no `AudioGenerator` / `AudioOscillator` / `AudioStreamPlayer` class exists).
  `AudioRecorder` is "in development and not available yet", records in-experience streams only, and cannot record
  `AudioDeviceInput`.
* Working community technique: **additive resynthesis** — a bank of looping sine-tone `AudioPlayer`s, each tuned with
  `PlaybackSpeed` to one frequency band, volume from an FFT of the audio. bruvie-fr (**[CODE]**): 384 voices, 1024-point
  FFT per frame, `TimePosition` set every frame for phase, ≈ 8.3 kHz ceiling, two public sine assets; others (4608885):
  128–256 voices, "music typically works better, whereas voice … struggle", "a bit echoey".
* The other route people use: **music through voice chat** (Voicemeeter / a virtual cable into the microphone; 3938457,
  4616522: "like a lot of other people do"). The new Audio API could even wire the owner's `AudioDeviceInput` to an
  emitter on the TV (2848873: "broadcast live events using Voice Chat"). But Roblox's automatic voice moderation
  flags music — warnings, repeated 5-minute voice suspensions, even for quiet instrumental music (3938457, 4715118) —
  and a moderation answer to an appeal is quoted as "Streaming audio is not permitted under Roblox policy" (4616522
  #5). Voice also works only in servers of ≤ 50 players and only for voice-enabled listeners (3923371, 2848873).
  **[COMMUNITY]**, quoting moderation. → *Rejected* as an audio path.
* Policy consequence for resynthesis too: every uploaded Roblox audio asset is moderated, and there is no Content
  Label for unmoderated audio (only for 2D content). Resynthesised desktop audio would be unmoderated audio, so live
  audio is a **policy question for the owner first**, a technical one second.
* **Here**: not implemented. Design for a live version (T-0028, proposed): the PC captures system audio (WASAPI
  loopback), computes per-frame band frequencies and levels (≈ 128–256 values × 30 fps ≈ 8–16 kB/s), sends them inside
  the bundles; clients drive a voice bank of a sine tone the **owner uploads** (asset permissions: a public sine asset
  from someone else may stop working), delayed to the video playout. Unknowns that need ears and a real client: sound
  quality, CPU cost of ~256 `AudioPlayer` updates per frame on low-end devices, A/V sync. Needs the owner's go-ahead
  on the policy question above.

### 1.9 Performance problems reported on real clients

* "EditableMesh writes … ~350× slower in Windows client 744, never in Studio" (4950870, staff investigating; Mac not
  affected); "Pass2D and PlayerAdorns eating 40 ms" with lots of visible UI (4753653, fixed by an engine update).
  **[COMMUNITY]**, partly **[OFFICIAL]**.
* **Here**: our UI is small (one SurfaceGui per TV, a few buttons), and client diagnostics (`DecodeMsPerFrame`,
  `LastRedrawPixels`, `Redraws`, `SkippedRedraws`) let the owner spot a regression. KI-0007 (real client speed) stays
  open.

### 1.10 Viewer features asked for

* Movie-theatre games (1fovuwm, 5lg7y6 "a movie theatre game"), watch-together with friends (2612752 #104), jumbotron /
  event streams (t0oqel "broadcast the driver's POV"), YouTube browsers (1l0eqdk, 4630135), pausing/controls by an
  operator only (bruvie-fr "username argument … gives control of playback"). **[COMMUNITY]**
* **Here**: cinema / full screen / mini player (D-0011), owner-only control on the PC, moderators in game (new).
  "Sharp" pixels in full screen (new, `ResampleMode = Pixelated`) keep enlarged text crisp.

### 1.11 Parallel Luau

* Ro2D renders bands in parallel Actors; Realtime minimap uses Parallel Luau (2776543). **[COMMUNITY]**
* **Here**: not used. Decoding is already time-sliced (`ClientDecodeBudgetMs`) and the fps cap follows the median
  decode time. A parallel decoder would need Actors with their own frame buffers and a copy back — worth it only if
  owner measurements show clients CPU-bound (KI-0007). Recorded as an option, not a task.

### 1.12 Delay and lag (second pass, after the owner reported more delay — D-0013)

* The owner's thread (1sp88kg, with its reposts 1sovo51 and 1sq1agw) was fetched again and read comment by comment.
  Its author gets "1 fps 2 fps" and blames HTTP ("roblox http is ahh"); the suggestions are a buffer, compression,
  sending only the pixel changes and waiting for WebSockets. Nothing about delay beyond that. **[COMMUNITY]**
* Roblox replication runs after Heartbeat, and RemoteEvents above a soft per-client budget (~50 KB/s cited) are
  **queued, not dropped** (DevForum 4209361 #8, #14); Studio's network stats over-report bandwidth (4963686). A stream
  sent faster than a player's connection therefore turns into delay. **[COMMUNITY]**, consistent with the official
  ~50 KB/s planning figure (F-0017).
* Native code generation is documented for server scripts only (S-0039): clients decode **interpreted** Luau. Measured
  here: 0.3 ms per DCT tile, 0.7 s for a full-screen frame of motion (F-0050). Ro2D and the SM64 port (§1.3) report
  the same pressure ("abysmal on mobile").
* **Here**: the delay is now measured end to end (E2E-31…34); the fixes are in D-0013 — frame-boundary drawing, no
  batching wait, pacing capped at 100 ms, delay-based rate control that keeps Roblox's queue short, a faster decoder
  and half-resolution macroblocks for large moving areas.

## 2. Changes made from this research (D-0012, TR-0016)

| Finding | Change | Verified by |
| --- | --- | --- |
| 1.6 content must be removable; moderation is the #1 concern | moderator kill switch (`ModeratorUserIds`, `Hidden`, logged) | E2E-29 (forged request from a non-moderator ignored; pixels dropped; no polls while hidden; exact picture after showing; "sharing is off" at once when shown while sharing is off) |
| 1.6 viewers may not want to see it | per-player Hide / Show (key H); server stops sending to that player | E2E-28 (0 bytes received while hidden) |
| 1.7 creation succeeds when the API is disabled | one-pixel probe write, clear message, 30 s retry | E2E-30 |
| 1.10 enlarged text looks soft | full-screen "Sharp" (`ResamplerMode.Pixelated`) | E2E-25 |
| 1.12 queued RemoteEvents, interpreted clients (second pass) | latency-first stream (D-0013) | E2E-31…34, TR-0017 |
| 1.6 ID verification, Content Labels, personal information | INSTALL C.1 / C.1b, SECURITY, TROUBLESHOOTING | review |

## 3. Not adopted, and why

| Idea | Why not |
| --- | --- |
| Frame-grid fallback without EditableImage | would sidestep Roblox's owner-accountability gate for unmoderated imagery (1.7) |
| Live audio now | unmoderated audio is a policy question for the owner (1.8); a large new subsystem whose quality cannot be judged without hearing it on real clients; needs an owner-uploaded tone asset — designed as T-0028, awaiting the owner |
| Audio through voice chat | voice moderation strikes music; quoted moderation answer: "Streaming audio is not permitted"; ≤ 50-player servers (1.8) |
| Parallel (Actor) decoding | no measurement shows clients CPU-bound yet (1.11) |
| WebSockets | blocked in live games (1.2) |
| One EditableImage per screen | one image updates per frame and memory budgets are tight (1.3) |
