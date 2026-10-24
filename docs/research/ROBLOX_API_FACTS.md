# ROBLOX_API_FACTS.md — Official Roblox API verification (task T-0003)

**Status: DONE (documentation level) — 2026-10-24.** R1a (EditableImage group), R1b (HttpService, WebStreamClient,
secrets), R1c (RemoteEvent / UnreliableRemoteEvent / buffer / EncodingService / network budget), R1d (VideoFrame /
VideoPlayer / SurfaceGui / capture services / Studio testing modes). All 14 questions are answered from official docs;
runtime confirmation in Studio and in a published server is still required (owner tests, `KNOWN_ISSUES.md` KI-0002).

**Method.** Official Creator Docs source files were downloaded from the public `Roblox/creator-docs` repository
(snapshot `4e795e65a41fd48624fd85442292a81baa6bb3f5`, main, committed 2026-10-24T10:11:10Z) and parsed with PyYAML.
These files generate the pages on `https://create.roblox.com/docs/...`. Each answer cites findings (`F-xxxx`,
`FINDINGS_LOG.md`) and sources (`S-xxxx`, `SOURCE_REGISTER.md`). Official facts are kept separate from community claims
(none used here) and from assumptions (marked **[ASSUMPTION]**).

## Answers to the 14 mandatory questions (`PROJECT_SPEC.md` §4 / verbatim §10)

| # | Question | Answer (official unless marked) | Evidence |
| --- | --- | --- | --- |
| 1 | Can a normal Roblox client capture its host desktop? | **No.** No documented API does it. `CaptureService` (client-side) captures only screenshots / ≤ 30 s videos **of the experience** into the user's Captures gallery; `VideoCaptureService` (camera) requires `RobloxScript` security, "not callable from experience scripts"; `StudioCaptureService` is Studio-only, plugin-only, 3D viewport only. Searching the engine reference for "desktop" finds only platform/device items. ⇒ a **native Windows app outside Roblox** must capture the desktop. | F-0020 |
| 2 | Can a published experience access Windows capture APIs? | **No.** No OS/Win32/DXGI/Graphics-Capture access is documented; experience scripts run in the Luau sandbox (no FFI, no file paths: capture file paths are `RobloxScriptSecurity`). | F-0020 |
| 3 | Can it hold a persistent external WebSocket/SSE connection? | **Not in a published experience.** `HttpService:CreateWebStreamClient` (SSE / RawStream / WebSocket) "is available in **Studio only**" and is limited to **4 clients** at once. Production must use request/response HTTP (polling / long-polling). | F-0010 |
| 4 | Which HTTP operations can it perform? | `RequestAsync` (GET, HEAD, POST, PUT, DELETE, OPTIONS, TRACE, PATCH; custom headers except locked `User-Agent`/`Roblox-Id`; request body any string incl. binary; optional gzip request compression; `Timeout`), plus `GetAsync`/`PostAsync` shorthands. **500 external requests/min per server** (Open Cloud separately 2500/min). Ports: not 1194, not < 1024 except 80/443. Response-size limit and binary-safe response bodies **not documented → test**. | F-0007, F-0008, F-0009 |
| 5 | In which execution contexts? | **Experience servers** (class description: requests "sent from experience servers"); secrets only in **server scripts** (client scripts get `Can't find secret with given key`); `localhost`/`127.0.0.1` documented only for **Studio plugins** on the same computer. Client-side HTTP is not documented as supported. | F-0007, F-0009, F-0011 |
| 6 | Can it build/modify images from raw pixels at runtime? | **Yes** — `AssetService:CreateEditableImage` + `EditableImage:WritePixelsBuffer` (RGBA8 buffer). | F-0001 |
| 7 | Exact EditableImage APIs, parameter types, pixel formats, memory limits, restrictions? | `CreateEditableImage(options: Dictionary?) -> EditableImage?` (default 512×512, **max 1024×1024**, not resizable); `WritePixelsBuffer(position: Vector2, size: Vector2, buffer)`; `ReadPixelsBuffer(position, size) -> buffer`; 4 bytes/pixel **R,G,B,A**, top-left origin; strict **client** memory budget (returns `nil` when exhausted; server/Studio unlimited); **only one displayed EditableImage updates per frame**; **disabled by default in published games** (Enable Mesh / Image APIs). | F-0001…F-0004 |
| 8 | Do dynamic image changes replicate? | **No.** `Content.Object` values are not replicated; clients receive an unusable checkerboard placeholder. Each client must build its own EditableImage. | F-0005 |
| 9 | Practical RemoteEvent / binary payload and bandwidth limits? | **Reliable `RemoteEvent`**: ordered + retransmitted, `buffer` arguments allowed (copied, engine-compressed), **no documented payload cap**; client→server ≈ 500 msgs/s per client per remote type. **`UnreliableRemoteEvent`: payloads > 1,000 bytes are dropped**, unordered, no queue. Official guidance: avoid large remote traffic; ~**50 KB/s** receive traffic per client was a 2024 planning target (not a hard limit). Practical ceiling **[UNVERIFIED]** → measure. Native `EncodingService` Zstd/Base64 makes compact binary payloads cheap to decode. | F-0013…F-0017 |
| 10 | Efficient multi-client delivery? | Each client must rebuild its own image (Q8), and clients cannot make HTTP requests (Q5), so **one server poller fetches each frame once and fans it out** with `RemoteEvent:FireAllClients(buffer)` (or `FireClient` for subscribed/nearby players). Forward the **compressed** payload unchanged (server validates header/size only; clients decompress natively); cache the latest keyframe for late joiners/resync; pace by the per-client budget. Server egress grows linearly with players **[CALCULATED]**. | F-0005, F-0013, F-0016, F-0017 |
| 11 | Protecting external credentials? | Experience **secrets store** (Creator Dashboard ⟩ Secrets; owner only; value ≤ 1,024 chars; bound to a domain pattern). `HttpService:GetSecret(key)` → non-printable `Secret`, server-only, usable in URL/headers via `AddPrefix`/`AddSuffix` (not in body). Studio playtests need **Local Secrets** (Experience Settings ⟩ Security). | F-0011 |
| 12 | Required HTTP/domain/permission settings? | **Allow HTTP Requests** (Studio ⟩ File ⟩ Experience Settings ⟩ Security) **and** **Enable Mesh / Image APIs** (Creator Dashboard ⟩ Configure ⟩ Settings, or Studio ⟩ Experience Settings ⟩ Security ⟩ Allow Mesh / Image APIs); a secret whose domain matches the relay host; relay on HTTPS port 443. | F-0003, F-0009, F-0011 |
| 13 | Studio vs published differences? | Studio *Test* runs separate client + server simulations, *Server & Clients* simulates up to 8 clients, *Team Test* = collaborative server — all simulations, not production. Differences: EditableImage fails when published until **Enable Mesh / Image APIs**; unlimited editable memory in Studio/server but budgeted on clients; `localhost` only from Studio plugins; `WebStreamClient` Studio-only; secrets only on live/collaborative servers (Local Secrets for solo playtests); `CreatorEnvironmentsNotSupportedByService` errors in non-live environments. | F-0003, F-0004, F-0009…F-0012, F-0022 |
| 14 | What works in real published games? | **Documented as supported** (with Allow HTTP Requests + Enable Mesh / Image APIs): server `HttpService:RequestAsync` to a public HTTPS endpoint (500 req/min/server, secret in headers); reliable `RemoteEvent` with `buffer` payloads; client `EditableImage` + `WritePixelsBuffer` shown via `ImageLabel.ImageContent` on a `SurfaceGui`; `EncodingService` Zstd/Base64. **Not available**: desktop capture, `WebStreamClient`, owner's `localhost`, live video in `VideoFrame`/`VideoPlayer` (uploaded assets only, 2,000 Robux each, max 2 playing). Runtime proof **[UNVERIFIED]** until the owner's published test (KI-0002). | F-0001…F-0022 |

## Key verbatim quotes (official)

- EditableImage, Update Limitations: "Only a single `EditableImage` can be updated per frame on the display side."
- EditableImage, Enabling for Published Experiences: "For security purposes, using `EditableImage` fails by default in
  published games."
- EditableImage, Memory Limits: "`EditableImage` has strict client-side memory budgets, although the server, Studio, and
  plugins operate with unlimited memory."
- EditableImage.Size: "The maximum size is 1024×1024. An `EditableImage` cannot be resized."
- WritePixelsBuffer: "pixels stored in a sequence of four bytes (red, green, blue, and alpha)".
- Content: "Replication is not yet supported for `Content.Object` values … do not use `EditableImage` or `EditableMesh` as
  `Content` on the server on an `Instance` that can replicate to clients."

- HttpService.CreateWebStreamClient: "There is a limit of four total clients allowed at one time." … "This method is
  available in Studio only. If you use it inside scripts, make sure to remove any references before publishing the
  experience."
- RequestAsync, Limitations: "The current limitation for sending and receiving **external** HTTP requests is 500 requests
  per minute. … Requests over these thresholds will fail."
- RequestAsync, Body: "Can be any string, including binary data. Must be excluded when using the GET or HEAD HTTP methods."
- HTTP guide: "To send requests, you must **Allow HTTP Requests** under **File** ⟩ **Experience Settings** ⟩ **Security**
  in Studio." "Plugins can also communicate with other software running on the same computer through the `localhost` and
  `127.0.0.1` hosts." "You cannot use port `1194` or any port below `1024`, except `80` and `443`."
- Secrets guide: "the secrets store for each game is only available to live servers or collaborative testing
  environments … You receive an identical error if you try to access secrets from a client script." "You can't include
  secrets in the HTTP request body, only the URL and headers."

- UnreliableRemoteEvent: "Events with payloads larger than 1000 bytes are dropped."
- Remote guide: RemoteEvent messages "arrive in the order you fire them, including across different RemoteEvent
  instances".
- EncodingService.GetDecompressedBufferSize: use it before decompressing — "very important if the input buffer contents
  are outside of your control".
- VideoFrame: "The video must be from a file uploaded to the Roblox website." Video guide: "Each video upload costs 2,000
  Robux." "Currently, a maximum of two videos can play simultaneously."
- CaptureService: "a client-side service that allows developers to control how the screenshot and video capture feature
  integrates with their experiences". StartVideoCaptureAsync: recording stops "when 30 seconds have passed".
- VideoCaptureService: "All of its members require `RobloxScript` security; not callable from experience scripts."
- StudioCaptureService: "a Studio-only service that lets plugins capture screenshots of the active place's 3D viewport".
- SurfaceGui guide: "Interactive UI elements … inside a `SurfaceGui` will only receive user input if they are parented to
  the player's `PlayerGui`".
- Testing modes: "Studio runs two separate simulations — one client simulation and one server simulation".
- buffer: "When passed through Roblox APIs, including sending a buffer through custom events, the identity of the buffer
  object is not preserved and the target will receive a copy."

## Design consequences so far

1. Reconstruction happens **in a client script**, one EditableImage per client per screen (F-0005).
2. One EditableImage per screen, ≤ 1024×1024; update changed rectangles with `WritePixelsBuffer` (F-0001, F-0002).
3. Decoder output format = RGBA8 row-major, top-left origin (F-0001).
4. Client must handle `CreateEditableImage` returning `nil` and must reuse/destroy images (F-0004).
5. Deployment requires the Mesh / Image APIs toggle (F-0003) **and** the Allow HTTP Requests toggle (F-0009).
6. PC → Roblox transport = the **Roblox game server pulls** frames from a **public HTTPS endpoint** with `RequestAsync`
   (no inbound connections, no WebSocket/SSE in published games, owner's localhost unreachable) (F-0007, F-0009, F-0010).
7. Request budget ≤ 500/min/server ⇒ batch several frame updates per response + long-poll; keep one outstanding request
   (F-0008, F-0012).
8. Relay credential = experience secret, sent as `Authorization: Bearer …` by the server only (F-0011).
9. Server→client frame path = one reliable `RemoteEvent` carrying `buffer` payloads (never JSON number arrays);
   UnreliableRemoteEvent is excluded (1,000-byte cap) (F-0013, F-0014).
10. Compression = standard zstd frames (content size included) made on the PC; Roblox decompresses with
    `EncodingService:DecompressBuffer` after a `GetDecompressedBufferSize` bound check; Base64 fallback is native (F-0016).
11. The game server forwards compressed payloads without decompressing them (header/size validation only) and caches
    the latest keyframe for late joiners (F-0013, F-0016).
12. Default bandwidth budget ≈ 50 KB/s average per client; large keyframes are chunked and paced (F-0017).
13. Desktop capture happens in a **native Windows application outside Roblox**; nothing inside Roblox can capture the
    desktop (F-0020). Option A (Roblox-only) is infeasible.
14. Display = client `EditableImage` → `ImageLabel.ImageContent` on a **client-created SurfaceGui in `PlayerGui`** with
    `Adornee` = screen part (F-0021). `VideoFrame` / `VideoPlayer` are rejected for live content (F-0018, F-0019).
15. Test ladder: Studio *Server & Clients* + Local Secret → Team Test → published private server (owner) (F-0022).
