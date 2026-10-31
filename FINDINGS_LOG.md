# FINDINGS_LOG.md — Every material discovery

Format per finding: ID · date · research question · approach/query · source (S-xxxx + URL) · what was examined ·
finding · evidence · source type · confidence/limitations · why it matters · effect on architecture · action · related
files/decisions · remaining uncertainty · checkpoint. Labels: **[OFFICIAL]** Roblox docs, **[CODE]** inspected source,
**[COMMUNITY]** forum/Reddit claims, **[TESTED]** independently executed, **[ASSUMPTION]**/**[ESTIMATE]** explicitly.

## Research R1 — Official Roblox API verification (T-0003)

All R1 findings were obtained on 2026-10-24 by downloading the **official Creator Docs source files** from the public
`Roblox/creator-docs` GitHub repository (snapshot `4e795e65a41fd48624fd85442292a81baa6bb3f5`, main branch, committed
2026-10-24T10:11:10Z) with `curl` from `raw.githubusercontent.com`, then parsing the YAML with PyYAML. These files are the
source of the pages on `create.roblox.com/docs` (the rendered page URL is given per source). Label: **[OFFICIAL]**.

### F-0001 — `EditableImage` is the supported runtime pixel API; pixels are written as RGBA8 buffers [OFFICIAL]
- **Question**: §10 Q6/Q7 — can an experience build/modify images from raw pixels at runtime; exact API?
- **Source**: S-0001 (`reference/engine/classes/EditableImage.yaml`), S-0002 (`AssetService.yaml`).
- **Finding**: `AssetService:CreateEditableImage(editableImageOptions: Dictionary?) -> EditableImage` creates a blank
  image (default **512×512**; size set via the options table). `EditableImage:WritePixelsBuffer(position: Vector2, size:
  Vector2, buffer: buffer)` writes a rectangular region; `ReadPixelsBuffer(position, size) -> buffer` reads one. Buffer
  layout: **one byte per channel, 4 bytes per pixel, order R,G,B,A** (alpha, not transparency). Origin is **top-left**
  `(0,0)`, bottom-right `(Size.X-1, Size.Y-1)`. `Size` is read-only, **max 1024×1024**, cannot be resized (create a new
  image + `DrawImageTransformed` to rescale). Other methods: `DrawRectangle/DrawLine/DrawCircle/DrawImage/
  DrawImageTransformed/DrawImageProjected/SampleImageProjected/Destroy` (Destroy "immediately reclaim[s] used memory").
  `WritePixelsBuffer` is `thread_safety: Unsafe`; `ReadPixelsBuffer` is `Safe`. Neither has a security restriction.
- **Evidence**: method signatures and descriptions in S-0001/S-0002 (quoted in `docs/research/ROBLOX_API_FACTS.md`).
- **Confidence**: high (generated from the engine API). **Limitation**: no numeric client memory budget is documented.
- **Impact**: a frame of W×H is reconstructed client-side by writing an RGBA8 `buffer` of W·H·4 bytes (or sub-rectangles
  for changed regions). The decoder must output RGBA8, top-left origin, row-major. Max 1024×1024 per image.
- **Action**: codec (T-0009) targets RGBA8 output + rectangle updates; default stream resolution ≤ 1024 wide.

### F-0002 — Only ONE displayed `EditableImage` is updated per frame [OFFICIAL]
- **Question**: §10 Q7 (restrictions) / performance.
- **Source**: S-0001, section "Update Limitations".
- **Finding**: "Only a single `EditableImage` can be updated per frame on the display side. For example, if you update three
  `EditableImage` objects which are currently being displayed, it will take three frames for all of them to be updated."
- **Impact**: splitting the screen into many EditableImage tiles multiplies display latency and can tear across tiles.
  **Use a single EditableImage per screen** (≤ 1024×1024) and apply changed regions with `WritePixelsBuffer` sub-rects.
- **Action**: architecture constraint for T-0008/T-0012.

### F-0003 — `EditableImage` fails by default in published experiences; an owner toggle enables it [OFFICIAL]
- **Question**: §10 Q12/Q13/Q14 — required settings; Studio vs published.
- **Source**: S-0001, section "Enabling for Published Experiences".
- **Finding**: "For security purposes, using `EditableImage` fails by default in published games. To enable it, open the
  Creator Dashboard, go to the game's **Configure ⟩ Settings**, and toggle on **Enable Mesh / Image APIs**. Alternatively,
  in Studio, open **Experience Settings** and toggle on **Allow Mesh / Image APIs** under **Security**." The page asks the
  creator to review the Terms of Use before enabling.
- **Impact**: mandatory deployment step; the troubleshooting guide must cover "works in Studio, fails when published".
- **Action**: add to deployment checklist (T-0014) and to the client's error state ("Mesh/Image APIs disabled").
- **Uncertainty**: the docs do not list account-level eligibility conditions for the toggle; verify on the owner's
  dashboard during the published test.

### F-0004 — Client-side memory budget; creation returns `nil` when exhausted [OFFICIAL]
- **Source**: S-0001 "Memory Limits"; S-0002 `CreateEditableImage` description.
- **Finding**: "`EditableImage` has strict client-side memory budgets, although the server, Studio, and plugins operate
  with unlimited memory." "If the device-specific editable memory budget is exhausted, creation fails and this method
  returns `nil`." Linking one EditableImage to several Content properties ("multi-referencing") is the recommended memory
  optimisation.
- **Impact**: the client must handle `nil` (show an error state, retry with a smaller resolution profile), reuse one image
  across frames (never create one per frame) and `Destroy()` it on cleanup. **Studio success does not prove the client
  budget holds on low-end devices.**
- **Action**: T-0012 must implement nil-handling + reuse + Destroy; test plan includes a low-memory device test.

### F-0005 — `Content.Object` (EditableImage) does NOT replicate; clients see an unusable placeholder [OFFICIAL]
- **Question**: §10 Q8 — do dynamic image changes replicate?
- **Source**: S-0003 (`reference/engine/datatypes/Content.yaml`), S-0001 (`Size` tagged `NotReplicated`).
- **Finding**: "Replication is not yet supported for `Content.Object` values. When an Instance with a Content property
  containing a Content.Object value is replicated, an unusable placeholder Object of the same type will be used instead
  … any attempt to read or write the contents of that placeholder object will throw. These placeholder objects will render
  as a cyan and magenta checkerboard pattern. … For now, do not use EditableImage or EditableMesh as Content on the server
  on an Instance that can replicate to clients."
- **Impact**: **every client must create and update its own EditableImage locally** (LocalScript). The server can only
  forward frame data (bytes) to clients; it cannot render the image for them. This rules out server-side image
  construction and confirms the "client-side reconstruction" part of the intended architecture.
- **Action**: T-0012 places reconstruction in a client script; server only relays validated frame payloads.

### F-0006 — `ImageLabel.ImageContent` displays an EditableImage; `ResampleMode` controls scaling [OFFICIAL]
- **Source**: S-0004 (`reference/engine/classes/ImageLabel.yaml`), S-0001.
- **Finding**: `ImageLabel.ImageContent: Content` "should hold an asset URI or a reference to an EditableImage object"; set
  it with `Content.fromObject(editableImage)`. `MeshPart.TextureContent` also accepts it. `ImageLabel.ResampleMode`
  (`Enum.ResamplerMode`, e.g. `Pixelated`) controls filtering when the image is scaled; `ScaleType` controls fitting.
- **Impact**: physical screen = Part + `SurfaceGui` + full-size `ImageLabel` whose `ImageContent` is the client's
  EditableImage. Aspect ratio handled by ScaleType/`UIAspectRatioConstraint` (to verify in T-0012).

### F-0007 — `HttpService` sends outbound HTTP(S) requests from experience servers; bodies may be binary [OFFICIAL]
- **Date**: 2026-10-24 · **Question**: §10 Q4/Q5 — which HTTP operations, in which contexts?
- **Source**: S-0005 (`reference/engine/classes/HttpService.yaml`), S-0006 (`cloud-services/http-service.md`).
- **Finding**: "`HttpService` allows HTTP requests to be sent from **experience servers** using `RequestAsync`, `GetAsync`
  and `PostAsync`." `RequestAsync(requestOptions: Dictionary) -> Dictionary` supports `GET, HEAD, POST, PUT, DELETE,
  OPTIONS, TRACE, PATCH`; request fields `Url` ("Must use http or https"), `Method`, `Headers`, `Body` ("Can be any
  string, **including binary data**. Must be excluded when using the GET or HEAD HTTP methods"), `Compress`
  (`Enum.HttpCompression.None|Gzip`), `Timeout` (seconds, > 0 and ≤ the default timeout). Response dictionary:
  `Success` (true iff 200–299), `StatusCode`, `StatusMessage`, `Headers`, `Body`. `User-Agent` and `Roblox-Id` headers are
  locked by Roblox; `Content-Length` is computed. Errors (timeout/rejection) are raised → wrap in `pcall`.
  `JSONEncode` "accepts buffers up to 50 MiB, which it encodes to base64 (and often compresses)". All three request
  methods are `Yields`, `thread_safety: Unsafe`, no security restriction tag.
- **Confidence**: high (generated API reference). **Limitations**: the docs do not state a maximum **response** size and
  do not explicitly state that the response `Body` is binary-safe → **[UNVERIFIED]** must be tested in Studio
  (fallback: base64 text payloads).
- **Impact**: the Roblox **game server** is the only documented place that can fetch frames from outside Roblox; it
  must pull with request/response HTTP (it cannot accept inbound connections). Frame payloads should be designed so that
  a base64 fallback is possible if binary response bodies turn out to be mangled.
- **Action**: T-0009 codec must support a binary body and a base64 text body; T-0012 server poller uses `RequestAsync`
  inside `pcall` with an explicit `Timeout`.

### F-0008 — External HTTP is limited to 500 requests per minute per game server [OFFICIAL]
- **Question**: §10 Q4/Q9 (throughput budget). **Source**: S-0005 (`RequestAsync` → "Limitations"), S-0006 ("Rate limits").
- **Finding**: "The current limitation for sending and receiving **external** HTTP requests is **500 requests per
  minute**. There is also a separate limit of 2500 requests per minute for Open Cloud requests. Requests over these
  thresholds will fail." The guide scopes the Open Cloud limit "For each Roblox game server" and says Open Cloud requests
  "do not consume the same overall limit of 500 HTTP requests per minute enforced on all other requests".
  `Enum.HttpError` additionally has `TooManyOutstandingRequests` (concurrent/pending request limit, value not
  documented). Best practice in the guide: exponential backoff, batch requests.
- **Impact** **[CALCULATED]**: 500/min = 8.33 requests/s per server for *all* external HTTP. A one-request-per-frame
  design is capped below ~8 fps; a safe design budget is **≤ 4 requests/s for frames** (leaves headroom for retries
  and control calls). Higher frame rates need **several frames/deltas per response** (batching) or long-poll semantics.
  Each Roblox server has its own budget, so a relay must expect one poller per running server.
- **Action**: T-0008/T-0011: relay API returns "all changes since frame N" (batched, size-capped) with a long-poll
  wait; server poller enforces a client-side token bucket below the limit and backs off on errors.

### F-0009 — HTTP must be enabled per experience; plugin-only localhost; restricted ports [OFFICIAL]
- **Question**: §10 Q12/Q13 — required settings, Studio vs published, localhost reachability.
- **Source**: S-0006 ("Enable HTTP requests", "Use in plugins", "Limitations"), S-0005 (`HttpEnabled`).
- **Finding**: "The `GetAsync()`, `PostAsync()`, and `RequestAsync()` methods aren't enabled by default. To send requests,
  you must **Allow HTTP Requests** under **File ⟩ Experience Settings ⟩ Security** in Studio." (`HttpService.HttpEnabled`,
  write security `LocalUserSecurity`.) "**Plugins** can also communicate with other software running on the same computer
  through the `localhost` and `127.0.0.1` hosts." Guide "Limitations" list: "Only the HTTPS protocol is supported";
  "You cannot use port `1194` or any port below `1024`, except `80` and `443`" (blocked → `403 Forbidden` /
  `ERR_ACCESS_DENIED`); in the same list, Open-Cloud-specific rules (`x-api-key` must be a `Secret`, no `..` in paths).
  "Requests should provide a secure form of authentication, such as a pre-shared secret key, so that bad actors cannot
  pose as one of your Roblox servers."
- **Confidence**: high for the toggle and the plugin-only localhost statement. **Limitation**: the "Limitations" list
  mixes Open Cloud and general rules (RequestAsync itself says http or https) → treat **HTTPS on port 443** as the only
  safe production choice.
- **Impact**: localhost is documented only for **Studio plugins on the same computer**; a published game server runs in
  Roblox's data centre, so the owner's `localhost` is **not reachable** from it (confirms spec hard rule). The desktop
  frames must be exposed through a **publicly reachable HTTPS endpoint** (relay or tunnel) on 443 (or a port ≥ 1024
  other than 1194), protected by a pre-shared secret.
- **Action**: deployment guide (T-0014) includes the Allow HTTP Requests toggle; relay (T-0011) is HTTPS-only with
  bearer-secret auth.

### F-0010 — `WebStreamClient` (SSE / chunked / WebSocket) exists but is **Studio-only** and limited to 4 clients [OFFICIAL]
- **Question**: §10 Q3 — can a published experience hold a persistent WebSocket/SSE connection?
- **Source**: S-0005 (`CreateWebStreamClient`), S-0007 (`WebStreamClient.yaml`), S-0008 (`WebStreamClientType`,
  `WebStreamClientState`).
- **Finding**: `HttpService:CreateWebStreamClient(streamClientType: Enum.WebStreamClientType, requestOptions:
  Dictionary) -> WebStreamClient`; types `SSE` (requires `text/event-stream`), `RawStream` (chunked/any streaming HTTP),
  `WebSocket` (bidirectional; `Send(data: string)` works only for this type); events `Opened(statusCode, headers)`,
  `MessageReceived(message: string)`, `Error(statusCode, message)`, `Closed()`; property `ConnectionState`
  (`Connecting/Open/Error/Closed`). Verbatim: "There is a limit of **four total clients** allowed at one time." "**This
  method is available in Studio only.** If you use it inside scripts, make sure to remove any references before
  publishing the experience. We encourage you to create plugins with this feature". `Enum.HttpError.InactivityTimeout`
  exists for streaming requests.
- **Confidence**: high (explicit statement). **Uncertainty**: Roblox may enable it for live games later → recheck the
  docs at each research refresh.
- **Impact**: **Answer to Q3: No** — per current official docs a *published* experience cannot rely on SSE/WebSocket;
  spec §9 forbids Studio-only features in the essential path. Production transport = **HTTP polling / long-polling with
  `RequestAsync`**. A WebStreamClient path may only be an optional Studio-development transport.
- **Action**: DECISIONS (T-0008) must reject WebSocket/SSE for the production path; record a "recheck WebStreamClient
  availability" item in TASKS.

### F-0011 — Secrets store: server-only `HttpService:GetSecret`, domain-bound, URL/headers only [OFFICIAL]
- **Question**: §10 Q11 — how to protect external credentials.
- **Source**: S-0009 (`datatypes/Secret.yaml`), S-0010 (`cloud-services/secrets.md`), S-0005 (`GetSecret`).
- **Finding**: Per-experience secrets are created by the **game owner / group owner** in **Creator Dashboard ⟩ (game) ⟩
  Secrets ⟩ Create Secret** with a name, the value (≤ 1,024 characters) and an **applicable domain** (`my.example.com`,
  `*.example.com`, or `*` — not recommended); ≤ 500 secrets per game; also manageable via Open Cloud.
  `HttpService:GetSecret(key: string) -> Secret` must be called "within a **server script**"; "the secrets store for
  each game is only available to **live servers** or **collaborative testing** environments … You receive an identical
  error if you try to access secrets **from a client script**" (`Can't find secret with given key`). Local playtests use
  **File ⟩ Experience Settings ⟩ Security ⟩ Local Secrets**. A `Secret` "cannot be printed or logged"
  (`print` → `Secret(name)`); only `AddPrefix`/`AddSuffix`; usable as the `url` argument and in headers — "You can't
  include secrets in the HTTP request body, only the URL and headers." Allow HTTP Requests must be on.
- **Impact**: the relay credential lives only in the Roblox secrets store (domain-restricted to the relay host) and in the
  owner's desktop config (git-ignored). Roblox sends it as `Authorization: Bearer <secret>` via
  `GetSecret(...):AddPrefix("Bearer ")`. Clients never see it. Studio tests need a Local Secret.
- **Action**: SECURITY.md safeguard 13/14/20 mapping; T-0012 server code uses `GetSecret` + header; deployment guide.

### F-0012 — `Enum.HttpError` values usable for diagnostics [OFFICIAL]
- **Source**: S-0011 (`enums/HttpError.yaml`).
- **Finding**: `OK, InvalidUrl, DnsResolve, ConnectFail, OutOfMemory, TimedOut, TooManyRedirects, InvalidRedirect,
  NetFail, Aborted, SslConnectFail, SslVerificationFail, Unknown, ConnectionClosed, ServerProtocolError,
  CreatorEnvironmentsNotSupportedByService` (non-live environment such as Studio not supported by target service),
  `InactivityTimeout` (streaming), `TooManyOutstandingRequests`, `InvalidRangeResponse`.
- **Impact**: the server poller maps failures to user-visible states (relay unreachable / TLS error / rate limited)
  without logging frame content; `TooManyOutstandingRequests` ⇒ keep **one** outstanding frame request per server.

### F-0013 — Reliable `RemoteEvent`: ordered, retransmitted, queued; **no documented payload cap** [OFFICIAL]
- **Date**: 2026-10-24 · **Question**: §10 Q9/Q10 — server→client payload limits and delivery semantics.
- **Source**: S-0012 (`classes/RemoteEvent.yaml`), S-0014 (`scripting/events/remote.md` "Delivery guarantees",
  "Throttling and size limits", "Argument limitations"). Snapshot `4e795e6`.
- **Finding**: RemoteEvents are "reliable and ordered": lost messages are retransmitted while the recipient stays connected;
  messages arrive in firing order "**including across different RemoteEvent instances**" (per connection and direction,
  for `FireClient` and `FireAllClients`). If no handler is connected, messages are queued ("limited in both count and
  memory", then discarded with a `Remote event invocation` error); undelivered messages are lost when the client leaves.
  Client→server throttling: "approximately **500 requests per second, per client**", shared by all remotes of the same type
  (excess RemoteEvent messages are delayed, not dropped). Any Roblox/Luau type may be passed (buffers included; mixed
  tables, metatables and functions are not preserved). **No maximum payload size is documented for reliable
  RemoteEvents** (only for UnreliableRemoteEvent, F-0014).
- **Confidence**: high for semantics; **[UNVERIFIED]** practical per-event size/throughput ceiling (must be measured).
- **Impact**: frame data goes server→client over **one reliable RemoteEvent** with a `buffer` argument; ordering lets the
  client apply deltas safely; a client that joins late or misses data (queue overflow, reconnect) needs a fresh keyframe.
  Chunk large frames into several events (configurable chunk size) instead of one huge event.
- **Action**: T-0009 protocol carries frame IDs + chunk index/count; T-0012 server caches the latest keyframe for late
  joiners; benchmark the per-event size in Studio (TEST plan).

### F-0014 — `UnreliableRemoteEvent` drops payloads > **1,000 bytes**, unordered, no queue → unsuitable for frames [OFFICIAL]
- **Source**: S-0013 (`classes/UnreliableRemoteEvent.yaml`, `BaseRemoteEvent.yaml`), S-0014.
- **Finding**: "Events with payloads larger than **1000 bytes are dropped**" (each Fire* method: "Has a 1000 byte limit to
  the payload of the event"). Engine encodes/compresses some types "such as buffers", so the on-wire size is hard to
  predict. Messages may be lost, reordered, dropped under congestion, dropped when no handler is connected (no queue), and
  client→server excess is dropped.
- **Impact**: never use UnreliableRemoteEvent for pixel data; at most for tiny ephemeral status pings (not needed).
- **Action**: DECISIONS T-0008 rejects it for the frame path.

### F-0015 — `buffer` library: fixed-size little-endian binary memory; copied when sent through remotes [OFFICIAL]
- **Source**: S-0015 (`libraries/buffer.yaml`).
- **Finding**: `buffer.create/fromstring/tostring/len`, `read/write{i8,u8,i16,u16,i32,u32,f32,f64}` (**little-endian**),
  `readbits/writebits`, `readstring/writestring`, `copy(target, targetOffset, source, sourceOffset?, count?)`,
  `fill(b, offset, value, count?)`. Out-of-bounds access throws. "When passed through Roblox APIs, including sending a
  buffer through custom events, the identity of the buffer object is not preserved and the target will receive a copy";
  a buffer cannot be shared between Actor scripts.
- **Impact**: the wire format is little-endian; the Luau decoder reads headers with `readu16/readu32` and bulk-copies
  pixel runs with `buffer.copy`/`buffer.fill`-style loops into the RGBA8 frame buffer passed to `WritePixelsBuffer`
  (F-0001). Out-of-bounds reads throw → decoder must bounds-check first and wrap decoding in `pcall`.

### F-0016 — `EncodingService`: native **Zstd** compress/decompress, Base64, hashes — on buffers [OFFICIAL]
- **Source**: S-0016 (`classes/EncodingService.yaml`, `enums/CompressionAlgorithm.yaml`, `enums/HashAlgorithm.yaml`).
- **Finding**: `Base64Encode(buffer) -> buffer`, `Base64Decode(buffer) -> buffer` (throws on invalid Base64);
  `CompressBuffer(input, Enum.CompressionAlgorithm.Zstd, level=1)` (Zstd levels −7…22); `DecompressBuffer(input, Zstd)`
  ("might throw an error if the compressed data doesn't contain expected decompressed size, if it is larger than 1GB or if
  it is invalid"); `GetDecompressedBufferSize(input, Zstd) -> int?` (nil if size missing/corrupt/> 1 GB; "very important if
  the input buffer contents are outside of your control"); `ComputeBufferHash/ComputeStringHash` with `Enum.HashAlgorithm`
  `Blake2b`, `Blake3`, `Md5`, `Sha1`, `Sha256` (not for passwords). `CompressionAlgorithm` has only `Zstd`. All methods
  `thread_safety: Safe`, **no security tag**; class tags `NotCreatable, Service, NotReplicated`.
- **Confidence**: high (API reference). **[UNVERIFIED]**: availability from client LocalScripts is implied (no security
  restriction) but not runtime-tested; decompression speed on low-end clients not measured.
- **Impact**: the desktop encoder compresses with standard **zstd frames that include the content size**; Roblox
  decompresses natively (C++) — no Luau decompressor is needed, removing the main CPU bottleneck of earlier community
  projects (RLE/palette decoding in Luau). The Base64 fallback for HTTP bodies is native too. Before decompressing, the
  receiver checks `GetDecompressedBufferSize` against the protocol maximum (anti decompression-bomb).
- **Action**: T-0009 codec = custom tile/rect format → zstd; Python side uses the `zstandard` package
  (`write_content_size=True`). T-0012 client: `GetDecompressedBufferSize` ≤ limit → `DecompressBuffer` → decode.

### F-0017 — Network budget: official guidance is "avoid large remote traffic"; ~**50 KB/s** receive per client was a 2024 planning target [OFFICIAL]
- **Source**: S-0017 (`performance-optimization/improve.md` "Networking and replication"; `resources/performance/
  resource.yaml`).
- **Finding**: "Sending a large amount of data through RemoteEvent or RemoteFunction objects or invoking them very
  frequently can lead to a large amount of CPU time being spent processing incoming packets each frame." Mitigation:
  "Avoid sending large amounts of data at once through remote events." The performance resource: the 2024 notebook "aimed
  … below roughly **50 KB/s of receive traffic**. Those last two numbers are historical planning targets; device memory
  pressure and network behavior cannot be reduced to a universal ceiling."
- **Confidence**: medium (guidance, not a limit). **[UNVERIFIED]** real ceiling — measure with Studio network stats and
  in a published server.
- **Impact** **[CALCULATED]**: at 50 KB/s a raw 320×180 RGBA frame (230,400 B) would take 4.6 s; compression + changed-region
  deltas are mandatory. Design default: average ≤ 50 KB/s per client (Balanced profile), keyframes chunked and paced;
  profiles may exceed it only when measured to work.
- **Action**: PERFORMANCE.md budget; server pacing/backpressure in T-0012; quality profiles in T-0010.

### F-0018 — `VideoFrame` plays only uploaded Roblox video assets (or in-experience capture recordings) — no live external stream [OFFICIAL]
- **Date**: 2026-10-24 · **Question**: §10 Q1/Q14 and hard rule "do not assume arbitrary stream URLs work in `VideoFrame`".
- **Source**: S-0018 (`classes/VideoFrame.yaml`), S-0019 (`ui/video-frames.md`, `cloud-services/video-service.md`). Snapshot `4e795e6`.
- **Finding**: class description: "The video must be from a file uploaded to the Roblox website." `VideoFrame.Video: ContentId`
  ("The content ID of the video file"); `VideoFrame.VideoContent: Content` is "either an asset content ID … or a direct
  reference to a `VideoCapture` object for local screen recordings" — such `VideoCapture` objects come from
  `CaptureService:ReadCapturesFromGalleryAsync()` (recordings *of the experience*, F-0020); values are built with
  `Content.fromAssetId()`, `Content.fromUri("rbxassetid://…")` or `Content.fromObject(capture)`. Upload rules (guide): 13+
  ID-verified uploader, ≤ 5 minutes, `.mp4`/`.mov`, ≤ 4096×2160, < 3.75 GB, "**Each video upload costs 2,000 Robux**",
  ≤ 20 uploads/day; "Currently, a **maximum of two videos can play simultaneously**"; "every video asset must be downloaded
  to each player's device before it can play". No URL/stream source property, no API to push frames.
- **Confidence**: high (generated API reference + official guide).
- **Impact**: `VideoFrame` cannot carry a live desktop (each update would be a new ≤ 5-min uploaded asset costing 2,000 Robux
  and passing moderation — neither live nor affordable). **Rejected for the live path**; `EditableImage` (F-0001) remains
  the only documented dynamic-pixel display.
- **Action**: T-0008 records VideoFrame as rejected; troubleshooting guide mentions it.

### F-0019 — `VideoPlayer` / `VideoDisplay` (Wire-based) and `VideoService` / `VideoSampler` are also asset-based [OFFICIAL]
- **Source**: S-0020 (`classes/VideoPlayer.yaml`, `VideoDisplay.yaml`, `VideoService.yaml`, `VideoSampler.yaml`).
- **Finding**: `VideoPlayer` is "An instance for playing video assets"; `VideoContent: Content` = "The asset to be loaded";
  `LoadAsync() -> AssetFetchStatus`, `PlayFailed(error: AssetFetchStatus)`; output goes through a `Wire` to a `VideoDisplay`
  (GuiObject with `ResampleMode`, `ScaleType`, `VideoRectOffset/Size`); both are tagged `NotBrowsable`.
  `VideoService:CreateVideoSamplerAsync(content, options?) -> VideoSampler`; `VideoSampler:GetSamplesAtTimesAsync(times) ->
  List<VideoSample>` returns image frames "from selected timestamps of a video". No class accepts live frames.
- **Impact**: no advantage over EditableImage for live content → rejected for the live path.

### F-0020 — No Roblox API captures the host desktop or exposes Windows capture; Roblox capture APIs record only the experience (camera capture is internal-only) [OFFICIAL]
- **Question**: §10 Q1 (can a normal client capture its host desktop?) and Q2 (can a published experience access Windows
  capture APIs?).
- **Source**: S-0021 (`CaptureService`, `Capture`, `ScreenshotCapture`, `VideoCapture`, enums `CaptureType`,
  `VideoCaptureStartedResult`, `VideoCaptureResult`), S-0022 (`VideoCaptureService`, `VideoDeviceCaptureQuality`), S-0023
  (`StudioCaptureService`), S-0024 (GitHub code search over `Roblox/creator-docs`).
- **Finding**: `CaptureService` "is a **client-side** service that allows developers to control how the screenshot and
  video capture feature integrates with their experiences"; a `Capture` is "a screenshot or a video — **captured within an
  experience**". Methods: `TakeScreenshotCaptureAsync` (UI inclusion via `Enum.UICaptureMode`, default `None`),
  `CaptureScreenshot` (temporary contentId), `StartVideoCaptureAsync` (records "until `StopVideoCapture()` … or when **30
  seconds** have passed", "all user voices are muted", `captureParams` "currently non-operational"), gallery save/share
  prompts, `UploadCaptureAsync`; `Capture.FilePathString` / `VideoCapture.FilePath` require `RobloxScriptSecurity`.
  `VideoCaptureService` "manages **camera** capture, for example for avatar facial-animation tracking … All of its members
  require `RobloxScript` security; **not callable from experience scripts**." `StudioCaptureService` is "a **Studio-only**
  service that lets **plugins** capture screenshots of the active place's 3D viewport" (`PluginSecurity`).
  Negative search: `desktop repo:Roblox/creator-docs path:content/en-us/reference/engine` → 9 files, all platform /
  device / settings items (`Platform`, `DeviceType`, `DeviceForm`, `MatchmakingType`, `AppLifecycleManagerState`,
  `UserGameSettings`, `GuiButton`, `UserInputService`, `StudioDeviceSimulatorService`); `"screen capture" OR "screen
  recording" OR "capture the screen" repo:Roblox/creator-docs` → 0 results.
- **Confidence**: high for what the documented capture APIs do; "no desktop-capture API exists" is an absence-of-evidence
  conclusion over the generated engine reference (limitation: GitHub code search indexes the default branch and literal
  terms only).
- **Impact**: **Q1 = No; Q2 = No.** The real desktop must be captured by a **separate native Windows application** outside
  Roblox (spec options D/E). Option A (Roblox-only Luau) is infeasible. Webcam capture is unavailable to experience scripts
  and is forbidden by the spec anyway (safeguard 5).
- **Action**: T-0008 rejects option A; T-0010 implements capture in the desktop app.

### F-0021 — `SurfaceGui` facts for building the physical screen [OFFICIAL]
- **Question**: §15 physical screen construction.
- **Source**: S-0025 (`classes/SurfaceGui.yaml`), S-0026 (`ui/in-experience-containers.md`).
- **Finding**: a SurfaceGui renders GuiObjects on one part face (`Face`). Either parent it to the part, or place it in
  `StarterGui` (→ `PlayerGui`) and set `Adornee` (+ `Face`) — "Setting `Adornee` overrides direct parent association".
  "Interactive UI elements … inside a `SurfaceGui` will only receive user input if they are parented to the player's
  `PlayerGui`". Canvas = the whole face; scale-based child sizes recommended. Properties: `SizingMode` (fixed size vs
  `PixelsPerStud`), `PixelsPerStud`, `CanvasSize`, `LightInfluence` (0…1), `Brightness` (0…1000; "no effect when either
  `LightInfluence` is `1` or `AlwaysOnTop` is `true`"), `AlwaysOnTop` (default false), `MaxDistance` (default 1000; 0 =
  unlimited), `ZOffset`, `ClipsDescendants`, `ToolPunchThroughDistance`.
- **Impact**: screen = anchored 16:9 Part + **client-created SurfaceGui in `PlayerGui` with `Adornee` = screen part**,
  `Face = Front`, `LightInfluence = 0`, `Brightness ≈ 1–2`, `SizingMode = PixelsPerStud`; child `ImageLabel` (size 1×1
  scale, `ScaleType = Fit`, `ResampleMode` configurable) whose `ImageContent = Content.fromObject(editableImage)` (F-0006).
  The client owns that instance, consistent with F-0005, and any on-screen button can receive input. Status overlay
  (sharing indicator, loading / connecting / error / stopped) = TextLabels on the same SurfaceGui.
- **Action**: T-0012 screen module.

### F-0022 — Studio testing modes vs published servers (consolidated answer to Q13) [OFFICIAL]
- **Source**: S-0027 (`studio/testing-modes.md`) + F-0003, F-0004, F-0009, F-0010, F-0011, F-0012.
- **Finding**: "When testing in either **Test** or **Test Here** mode, Studio runs two separate simulations — one client
  simulation and one server simulation"; Client mode "is a close simulation of the game running on the Roblox application,
  without multiple players"; **Server & Clients** multi-client simulation supports "up to eight" clients; **Team Test**
  (collaborative testing) runs a shared server session; device and network *simulation* exist (emulation, not real
  devices). Official Studio-vs-published differences relevant here: EditableImage fails in published games until **Enable
  Mesh / Image APIs** (F-0003); Studio/server have unlimited editable memory, real clients do not (F-0004); `localhost`
  only from Studio plugins (F-0009); `WebStreamClient` Studio-only (F-0010); secrets only in live servers / collaborative
  testing — local playtests need **Local Secrets** (F-0011); `HttpError.CreatorEnvironmentsNotSupportedByService` for
  non-live environments (F-0012).
- **Impact**: test ladder = (1) Studio *Server & Clients* (2–3 clients) with a Local Secret for logic; (2) Team Test with
  the real secret; (3) published private server run by the owner as the only production proof (spec §9).

## Research R2 — Existing implementations (T-0004…T-0007)

R2 findings come from inspected public source code (**[CODE]**, static review unless marked **[TESTED]**) and forum posts
(**[COMMUNITY]**). Third-party code is studied, never copied (ScreenBlox is GPL-3.0). Notes: `docs/research/EXISTING_PROJECTS.md`.

### F-0023 — ScreenBlox = GitHub `Reb0rnEnder/ScreenBlox`, the code behind the 2024 DevForum "ScreenShare | Free Game Source" resource [CODE][COMMUNITY]
- **Date**: 2026-10-24 · **Question**: T-0004 — what is ScreenBlox, where is its source, how does it relate to the other
  projects in scope?
- **Method**: `web_search` ("ScreenBlox Roblox screen sharing", "ScreenBlox Reb0rnEnder devforum", "ScreenBlox github roblox
  screen share EditableImage") → DevForum topic 2823814 excerpt; `git clone https://github.com/Reb0rnEnder/ScreenBlox`.
- **Source**: S-0028 (DevForum topic, search excerpt only), S-0029 (repository @ `b873f78`).
- **Finding**: the DevForum resource "ScreenShare | Free Game Source [UPDATED] [OVERHAUL]" (topic 2823814, author
  RebornEnder, first post Feb 2024; excerpt: "Update 4.0: Added video downloading & caching", "Update 4.7: Added mouse
  functionality, auto roblox finder, config editor") links "GitHub - Reb0rnEnder/ScreenBlox: Send video data to roblox
  games." Its disclaimer says the tool "can only be used to convert the screen to colours that are stored on a local web
  server and then loaded by the game to color frames accordingly". A reply in the excerpt recommends `EditableImage` with
  `WritePixels` "instead of drawing". Repository: GPL-3.0, 17 commits from 2024-08-17 ("(backup) Initial commit") to
  2026-01-12 (head `b873f7829518b8cf137e933997d5c98e57ef2d7f`, "added missing cv2 dependency"); `Data/Version.json` = 5.2;
  files `Launcher.py`, `Data/App.py`, `requirements.txt` (flask, gevent, pillow, requests, pydirectinput, opencv-python),
  `readme.md`, `notes-for-maintainer`, `LICENSE` and the binary place file `v4.7.rbxl` (124,062 B, the Roblox side).
  PR #2 (regedit-sys, merged 2025-12-02) added README/requirements and changed the bind address to `0.0.0.0`.
- **Confidence**: high for repository contents; medium for forum details (excerpt; thread not loaded yet).
- **Impact**: "ScreenBlox" and "the ScreenShare free-game-source project discussed in 2024" (spec research list) are the
  **same project** → that T-0007 item is covered by T-0004 (full thread still to read).
- **Action**: parse `v4.7.rbxl` scripts and read the full thread (T-0004 part 2); no code reuse (GPL-3.0).

### F-0024 — ScreenBlox desktop pipeline: per-request PIL screenshot → 190×90 → JSON array of hex strings over plain, unauthenticated HTTP :8080 [CODE]
- **Source**: S-0029 `Data/App.py` (lines 122–143, 189–214) @ `b873f78`.
- **Finding**: `GET /` calls `generate_hex()` **inside the request handler**: `ImageGrab.grab().resize((resx, resy))`
  (default **190×90**, Pillow default resampling; `grab()` without `all_screens` = primary monitor) and returns
  `{"HEX": ["rrggbb", …]}` (`application/json`), one quoted 6-hex-digit string per pixel, row-major. No frame ID,
  timestamp, delta, compression or caching: every poll captures and re-encodes a full frame. Other endpoints: `/res`
  (`{"RES": [resx, resy]}`), `/vidsett`, `/key`, `/roblox` (feature flags). Server: Flask under gevent
  `WSGIServer(('0.0.0.0', 8080))` — **plain HTTP, no TLS, no authentication, no rate limit**. Internet exposure relies on
  a third-party TCP tunnel (`notes-for-maintainer`: "use https://tunnel.pyjam.as instead of playit?", or self-hosted FRP).
  "Video mode" pre-converts a local video file with OpenCV into hex frames resampled to 60 fps (`?frame=N`) —
  pre-recorded media, not live capture.
- **Evidence** [CALCULATED]: 17,100 px × 9 B (`"rrggbb",`) − 1 + 11 B wrapper ≈ **153,910 B per frame** (≈ 9 B/pixel vs
  4 B raw RGBA); at the 500 req/min server cap (F-0008) ≤ 8.3 fps ≈ 1.28 MB/s of HTTP per game server, and Luau
  `JSONDecode` must build a 17,100-string table per frame.
- **Confidence**: high (code read). **Not executed** (Windows-only `ImageGrab` behaviour / `pydirectinput`, KI-0001).
- **Impact**: confirms the community topology "desktop HTTP server + public tunnel + Roblox `HttpService` poll"
  (consistent with F-0007…F-0009) and its costs: ~2× raw size, JSON parse per pixel, capture coupled to polling, no
  security. Our design keeps the topology and replaces the weak parts: capture loop independent of requests with a
  latest-frame buffer + frame IDs; binary tile/delta format + zstd (F-0016); HTTPS + bearer secret (F-0011); size caps
  and rate limits.
- **Action**: T-0008 comparison row "ScreenBlox-style JSON hex polling"; T-0009 codec benchmark uses it as a baseline.

### F-0025 — ScreenBlox exposes remote keyboard, remote mouse and process-control endpoints without authentication; its launcher executes code downloaded at run time [CODE]
- **Source**: S-0029 `Data/App.py` lines 35–36, 156–187; `Launcher.py`.
- **Finding**: `/keysend?key=` → `pydirectinput.press(key)` for whitelisted keys `w a s d i o left right space`;
  `/mousclick?x=&y=&btn=` → `pydirectinput.click(x, y, button=btn)` at **arbitrary screen coordinates**;
  `/robloxjoin?placeid=` → `taskkill /f /im RobloxPlayerBeta.exe`, then launches `roblox://placeID=<placeid>` with the
  auto-detected `RobloxPlayerBeta.exe`. Each is gated only by a local config flag (default `false`), **never by
  authentication**: once enabled, anyone who knows the tunnel URL can click on / type into the owner's PC.
  `Launcher.py` downloads `Data/App.py` from `raw.githubusercontent.com/Reb0rnEnder/screenblox/main/` whenever the remote
  `Version.json` is newer and runs it with `os.system("python …")` — no pinning, signature or hash check.
- **Impact**: these are exactly the features the spec forbids (no remote mouse/keyboard control, no command execution,
  no generic remote desktop; `SECURITY.md`). Our capture app exposes **no inbound endpoint** (it pushes frames out to the
  relay), contains no input-injection code and no self-updater that executes downloaded code.
- **Action**: SECURITY.md threat list (T-0011/T-0014): unauthenticated tunnel URL, input injection, auto-update RCE as
  explicit non-goals, with tests where applicable.

### F-0026 — ScreenBlox defects found by static review (not executed) [CODE]
- **Source**: S-0029 `Data/App.py` @ `b873f78`.
- **Finding**: (1) the `/` route is chosen by `if config["video_mode"]:` at **import time**, before `load_config()` runs
  in `__main__`, so a saved `video_mode: true` never switches `/` to video frames. (2) `edit_config()` tests
  `isinstance(new_value, int)` on the string returned by `input()` (never true), so edited numeric values (`resx`,
  `resy`) are stored as **strings** and the next `Image.resize((resx, resy))` would fail. (3) Video mode keeps every frame
  as a hex string in memory (≈ 154 KB per frame at 60 fps).
- **Confidence**: medium-high (Python semantics; not run).
- **Impact**: nothing is reused; lessons: load and type-check configuration before it drives behaviour; bound memory.

### F-0027 — ScreenBlox Roblox side: a server `Script` polls with `GetAsync` + `JSONDecode` in a tight loop and paints one replicated GUI `Frame` per pixel (no EditableImage, no RemoteEvent frames) [CODE]
- **Date**: 2026-10-24 · **Source**: S-0029 `v4.7.rbxl` (124,062 B) parsed with `scripts/agent/rbxl_dump_scripts.py` (LZ4
  chunks; INST/PROP/PRNT): 96 classes, 225 instances, 24 LocalScripts, 3 Scripts, 5 ModuleScripts (third-party Adonis
  admin loader/config, ignored), 3 RemoteEvents.
- **Finding**: `Workspace/Monitor/Object_0/SurfaceGui/LocalRequest` is a **server `Script`** (despite its name) in a part's
  SurfaceGui. Clicking the part `Workspace.Controls.ON` (ClickDetector) calls `GetData(url.."/res")`, `/vidsett`, then
  `while IsClickedOn do Render(Image, GetData(url).HEX) end` — back-to-back `HttpService:GetAsync` + `JSONDecode` with
  **no wait, pacing or backoff** (errors are caught by `pcall`, warned once per distinct message, and retried at once).
  `Controls.PIX` builds the screen: a `UIGridLayout` plus one cloned `Pixel` Frame per pixel (`resx*resy` = **17,100
  Frames** at 190×90, 1-px cells, `SurfaceGui.CanvasSize` = resolution). `Render` (inside `coroutine.wrap`) walks
  `par:GetChildren()` and sets `BackgroundColor3 = Color3.fromHex(hex)` for every pixel whose string differs from the
  previous frame. Because the Frames live in Workspace and are changed by the server, **every changed pixel is a
  replicated property change sent to every client** — that is the whole "replication" mechanism. An FPS label counts
  `Render` calls per second. Video mode downloads every pre-converted frame (`?frame=i`) into a server table, then loops.
- **Evidence** [CALCULATED]: a full-change frame = 17,100 property replications per client + a ~154 KB JSON decode on the
  server; polling is capped by 500 external requests/min (F-0008) ⇒ ≤ 8.3 polls/s, beyond which `GetAsync` fails and the
  loop spins on errors.
- **Static-review defects (not executed)**: (a) `GetChildren()` also returns the `UIGridLayout` (first child), so pixel
  values are applied shifted by one child (the layout's failed assignment is hidden by `pcall`), and the code assumes
  `GetChildren()` order equals the grid's `LayoutOrder` order (all clones share one LayoutOrder) — likely a 1-pixel shift,
  unverified; (b) on HTTP failure `GetData` returns the string `"ERROR"`, `("ERROR").HEX` is `nil`, nothing renders and
  the loop keeps requesting.
- **Confidence**: high (code read); runtime behaviour not observed (KI-0002).
- **Impact**: per-pixel Instances mutated on the server are the community's pre-EditableImage technique; they cost one
  replicated property change per pixel and ~17k Instances per screen. With `EditableImage` (which does **not** replicate,
  F-0005) the server must forward compact frame bytes (reliable `RemoteEvent` + `buffer`, F-0013/F-0015) and each client
  reconstructs locally — the architecture already forced by R1. Polling must be paced (token bucket) and back off.

### F-0028 — ScreenBlox lets any player set the server's HTTP target and trigger host-PC actions; no authorization anywhere [CODE]
- **Source**: S-0029 `v4.7.rbxl` scripts `LocalRequest`, `StarterGui/AdminUI/UI/URLSet/LocalScript`,
  `StarterGui/UI/KeyBoard/KeyHandler`, `StarterGui/UI/JoinGame/JoinHandler`, `ServerScriptService/GAMEJoinTimer`.
- **Finding**: RemoteEvents `ReplicatedStorage.SendURL/SendKEY/SendGAME`. `SendURL.OnServerEvent(plr, url)` sets the
  polling URL to **any client-supplied string** (no admin check, no allow-list) and prints it to the server log; the URL
  textbox is in `StarterGui/AdminUI`, i.e. cloned to **every** player (no permission check exists in any script; the
  bundled Adonis admin keeps its example config and gates nothing). `SendKEY` and `SendGAME` forward client strings to
  `<url>/keysend?key=` and `<url>/robloxjoin?placeid=` by plain concatenation (no URL encoding; the 60-s join cooldown is
  commented out in the handler). The ON/OFF/PIX ClickDetectors accept clicks from any player.
- **Impact**: our server takes the relay host only from owner configuration (domain-bound secret, F-0011), **never** from
  clients; any client→server control (e.g. owner-only start/stop) is authorized and rate-limited on the server
  (exploiters can fire RemoteEvents without the GUI); nothing flows from Roblox to the PC except authenticated polling.
- **Action**: SECURITY.md threats "client-controlled URL", "unauthorized remote use" (T-0011/T-0012); T-0012 server code
  has no client-settable URL.

### F-0029 — The ScreenShare DevForum thread reports no frame rate, latency or bandwidth figures; its performance claims are qualitative and partly absent from the available code [COMMUNITY]
- **Date**: 2026-10-24 · **Question**: T-0004 part 2b — what performance (fps, lag, resolution) did the ScreenBlox
  community report?
- **Method**: Discourse JSON API: `curl https://devforum.roblox.com/t/2823814.json` (first 20 posts) +
  `/t/2823814/posts.json?post_ids[]=…` (remaining 13); `cooked` HTML converted to text with BeautifulSoup; all 33 visible
  posts read (post numbers 1–34, #30 not in the stream = deleted/hidden). Topic created 2024-02-05, last post
  2024-08-29, 7,848 views, 65 likes at access time. Attached screenshots and the demo video (#3) were **not** analysed.
- **Source**: S-0028.
- **Finding**: no post gives an fps, latency, bandwidth or resolution-vs-speed figure (#14 asks "how much fps have you
  managed so far"; #15 answers "didn't add that yet"). Only qualitative statements: #3 (author, 2024-02-05) "changing the
  resolution to a higher one might crash the roblox client! (OLD VERSION ONLY)"; #19 (author, 2024-02-06, during a
  CanvasDraw/EditableImage experiment that #15 says was tested with `math.random` pixels) "i have 480p now (no lag)";
  #23 (2024-02-22) "New map and huge performance upgrades released". The author first could not adopt EditableImage (#8
  "idk how to", #10 "almost no documentation", #12 "editableimage is a studio only beta feature i think?") and then tried
  the CanvasDraw module (#11–#13 "this module is so fast"). The inspected backup `v4.7.rbxl` still paints one replicated
  `Frame` per pixel at 190×90 and contains no EditableImage/CanvasDraw (F-0027): the "480p (no lag)" claim is **not
  reflected in the available code**.
- **Confidence**: high that the thread contains no measurements; low for the qualitative claims (no method, 2024 engine,
  possibly Studio-only).
- **Impact**: ScreenBlox gives **no usable performance baseline**; fps/latency targets must come from our own
  measurements (T-0009 codec benchmarks, T-0013). Client crashes at higher resolutions with per-pixel Frames support
  rendering through one `EditableImage` (F-0001) instead of thousands of GUI objects.
- **Action**: T-0009/T-0013 record measured fps, latency and bytes per frame; `PERFORMANCE.md` cites measurements only.

### F-0030 — Thread claims about transport limits: "no HttpService in a LocalScript" agrees with the docs; "the RemoteEvent data limit is 900 Bytes" contradicts them for reliable RemoteEvents [COMMUNITY]
- **Date**: 2026-10-24 · **Source**: S-0028 posts #15–#19 (author, 2024-02-06).
- **Finding**: #15: "you can't do httpservice on localscript and the remoteevent data limit is 900 Bytes but the screen
  pixel data is ~1MB"; #16 suggests chunking; #17/#18 "that would be slow … every solution is extremely slow"; #19 "i
  didn't actually need to chunk the data cuz i sent the date and the client did the work" (unexplained). The HttpService
  statement matches F-0007 (server-side `RequestAsync`). A 900-byte limit is **not** documented for the reliable
  `RemoteEvent` (no documented cap, F-0013); the only per-event size limit in the current docs is the
  `UnreliableRemoteEvent` drop above 1,000 B (F-0014). "~1MB" matches uncompressed 640×480 RGBA = 1,228,800 B
  [CALCULATED].
- **Confidence**: low (2024 statement without a test). The official docs stay authoritative, but the practical
  reliable-RemoteEvent ceiling remains **unverified** (assumption already listed with F-0013/F-0017).
- **Impact**: the frame transport stays reliable `RemoteEvent` + `buffer`, with compressed, size-bounded chunks so the
  design works whether or not a practical per-event ceiling exists.
- **Action**: T-0009 wire protocol: explicit chunking with a configurable maximum chunk size; T-0013 runtime test
  "largest reliable RemoteEvent payload delivered" (Studio + published) before tuning chunk sizes.

### F-0031 — Live-server reachability in practice: third-party TCP tunnels (playit.gg, ngrok) and a "works in Studio, server offline in Roblox" failure [COMMUNITY]
- **Date**: 2026-10-24 · **Source**: S-0028 posts #20, #22, #24–#26.
- **Finding**: the author exposes the local server through **playit.gg** ("set tcp on port 8080", #20; #22 points out
  playit is a tunnelling proxy, not port forwarding) or **ngrok** (#25). A user using playit.gg reported (#24/#26) it
  "only works in studio … When I try in roblox it says: server offline", then "found the issue and now it's fixed" (cause
  not stated). The author: "it works in a game (except OLD_hi2.rbxl) … You just need to make the server open to the
  global web" (#25).
- **Confidence**: medium (two people, consistent; root cause unknown).
- **Impact**: (1) Studio success does **not** prove live-server connectivity (consistent with F-0008, F-0009, F-0022) → the
  setup guide needs a live-server connectivity check and the screen needs a distinct "relay unreachable" state;
  (2) ScreenBlox sends frames as plain HTTP through a third-party tunnel, so the tunnel operator and any on-path observer
  can see the desktop → our transport must be HTTPS + authenticated end to end, and any tunnel/relay provider must be
  disclosed to the owner (spec: no undisclosed third-party transmission). Hosted relay vs TLS tunnel is part of T-0008.
- **Action**: T-0008 compares relay hosting options; T-0012 status states include "relay unreachable"; T-0014 guide
  includes the live check.

### F-0032 — Content-policy remark: the author considers screen sharing ToS-compliant only while the displayed content is "Roblox friendly"; no official position in the thread [COMMUNITY]
- **Date**: 2026-10-24 · **Source**: S-0028 posts #1 (disclaimer), #4, #7.
- **Finding**: #4 recommends "checking the Terms Of Service just incase this breaks it"; #7 (author): "This shouldn't be
  against tos however it will be if you show some not Roblox friendly images on screen." The first-post disclaimer argues
  it is allowed because the screen is only converted "to colours … loaded by the game to color frames". No Roblox staff
  reply or policy document is cited.
- **Confidence**: low (opinion); the underlying risk is real: whatever the desktop shows is visible to every player in
  the server.
- **Impact**: the owner is responsible for what the in-world screen shows; the design must make accidental exposure
  unlikely (explicit start, visible sharing indicator, instant stop — spec safeguards) and should support limiting the
  experience/screen to trusted players. An official policy check is needed before any publishing guidance.
- **Action**: new task T-0016 (official Terms of Use / Community Standards check); threat "inappropriate or private
  content shown to other players" for `SECURITY.md` (T-0008/T-0011).

### F-0033 — ScreenBlox provenance and successors: the original repository was lost in Aug 2024; the inspected repo is a partial backup; no successor is linked [COMMUNITY][CODE]
- **Date**: 2026-10-24 · **Source**: S-0028 posts #25, #31–#34; S-0029 history (F-0023).
- **Finding**: #31 (2024-08-19) "The github is gone"; #32 (author, 2024-08-22) "My account got locked, meanwhile heres the
  backup one. (It dosent have some things)" linking `Reb0rnEnder/ScreenBlox` — matching its first commit "(backup)
  Initial commit" of 2024-08-17 (F-0023). #25 mentions an older place `OLD_hi2.rbxl` that does not work in live games (not
  in the backup). Successors: #33 (SuperWoahGuy64, 2024-08-27) posts only a screenshot, "i modified it : D" (no code or
  link); no fork, successor or EditableImage version is linked. Thread links (clicks): the GitHub repo (842), the
  CanvasDraw DevForum thread (61, S-0031), EditableImage docs (59 + 36).
- **Confidence**: high for what the thread says; pre-backup history unavailable.
- **Impact**: the inspected code (F-0024…F-0028) is the only available ScreenBlox implementation; claims about lost
  versions (CanvasDraw/480p, F-0029) cannot be verified. GitHub forks of `Reb0rnEnder/ScreenBlox` remain unchecked.
- **Action**: T-0004 DONE; T-0007 checks ScreenBlox forks and CanvasDraw (S-0031) as an EditableImage usage reference.

### F-0034 — Windows desktop capture works through the whole pipeline on a GitHub `windows-latest` runner [MEASURED]
- **Date**: 2026-10-31 (28th session). **Approach**: CI job `e2e-windows` (`.github/workflows/ci.yml`) runs
  `tests/e2e/run_e2e.py` on the runner's interactive desktop (Tk painter window, `mss` GDI capture).
- **Finding**: E2E-01…16 passed at `fb6bcdd`: the runner desktop is 1024×768; frames reached two emulated Roblox
  clients byte-exact; start → picture 0.99 s, desktop change → both TVs 0.16 s, stop → TVs off 0.20 s.
- **Impact**: KI-0001 is partially closed — the capture path works on real Windows (GDI). Still unverified: the owner's
  PC (multi-monitor, high DPI scaling, HDR, hardware-accelerated video that may capture black with GDI).
- **Evidence**: PR #1 comment by `github-actions[bot]` (2026-10-31T14:56:32Z) with the run output.

### F-0035 — Roblox Help Center (Terms of Use / Community Standards) is not reachable from the agent sandbox [NEGATIVE]
- **Approach**: `curl` of `https://en.help.roblox.com/hc/en-us/articles/203313410-Roblox-Community-Standards` (403) and
  of the Wayback Machine copy (403), 2026-10-31.
- **Impact**: T-0016 stays BLOCKED for the agent; the install guide tells the owner to review the rules and lists the
  obvious risks (personal information, content without rights). No rule is claimed from memory.

### F-0036 — Secrets can be the request URL itself (`AddPrefix`/`AddSuffix`, "usable as the url argument") [OFFICIAL]
- **Source**: S-0010 (`cloud-services/secrets.md`, re-read 2026-10-31) and F-0011.
- **Finding**: Local Secrets are edited in Studio ⟩ File ⟩ Experience Settings ⟩ Security ⟩ Local Secrets (UI, no file
  format); published secrets in Creator Dashboard ⟩ Secrets with a domain pattern.
- **Impact / idea (not implemented, T-0017)**: storing the tunnel base URL as a secret would let the owner change a
  quick-tunnel URL in the dashboard without republishing; requires verifying that `RequestAsync` accepts a `Secret` as
  `Url`. Until then the URL is the `FrameServiceUrl` attribute.

### F-0037 — Icy-Monster (and forks) batch several frames per HTTP response to exceed the ~8 requests/s ceiling [CODE]
- **Source**: S-0034, S-0038. `FrameGroups` frames per response, client replays them with `task.wait(1/F)`; README
  "Max FPS is FrameGroups × 8, due to max Roblox HTTP limit". Delta state is a single global shared by all servers (bug).
- **Impact**: adopted (batching + playout, D-0007); our per-poller chain avoids the shared-state bug.

### F-0038 — RSSP reads raw binary HTTP bodies in Roblox (`GetAsync` + `string.byte`, size check `w*h*3`) [CODE][COMMUNITY]
- **Source**: S-0035 (`ServerScriptService.Main`). Evidence that binary bodies arrive intact, not proof (no test by us;
  the official docs are silent, F-0007). Also: dxcam + `cv2.INTER_AREA`; per-pixel Parts coloured on the server;
  credentials in URLs; remote input/commands; "RAT" in v2.2.2.
- **Impact**: frame service gains a binary body mode, used only after a startup probe proves bytes arrive unchanged
  (fallback base64). Capture gains INTER_AREA resize and an optional dxcam backend.

### F-0039 — MahanBig/roblox-screen-stream: lossy DCT (YCbCr 4:2:0) + rate control + batching + time-sliced native decode [CODE]
- **Source**: S-0036. Bit-exact integer IDCT in Python and Luau; closed-loop inter frames; per-frame quantizer search
  to fit a token bucket; `since=SEQ` batches; 6 ms decode slices per game frame. Author's figures (Studio only):
  640×352 @ 15 fps at ~320 KB/s.
- **Impact**: our lossless tiles cost ~86 KB per 480×270 video frame (PERFORMANCE.md) — a DCT mode is the single
  biggest quality lever for moving content. Adopted as a per-tile hybrid (DCT while moving, lossless refinement when
  still), own implementation (D-0007).

### F-0040 — `--!native` speeds up a Luau pixel decoder ~3.4× (luavid, measured by its author); official docs describe it for server scripts [COMMUNITY][OFFICIAL]
- **Source**: S-0037, S-0039. Docs: "server-side scripts in your game can be compiled directly into machine code";
  client availability not stated. Luavid and MahanBig use it in client decoders; the directive is a no-op where
  unsupported, so adding it is safe.
- **Impact**: `--!native` on the decoder modules and the client script; real client gain = owner test.
