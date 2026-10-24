# ROBLOX_API_FACTS.md — Official Roblox API verification (task T-0003)

**Status: IN PROGRESS.** Done: R1a (EditableImage group), R1b (HttpService, WebStreamClient, secrets). Still to do:
R1c (RemoteEvent / UnreliableRemoteEvent / buffer / EncodingService), R1d (VideoFrame / VideoPlayer / SurfaceGui,
Studio vs published, desktop-capture question).

**Method.** Official Creator Docs source files were downloaded from the public `Roblox/creator-docs` repository
(snapshot `4e795e65a41fd48624fd85442292a81baa6bb3f5`, main, committed 2026-10-24T10:11:10Z) and parsed with PyYAML.
These files generate the pages on `https://create.roblox.com/docs/...`. Each answer cites findings (`F-xxxx`,
`FINDINGS_LOG.md`) and sources (`S-xxxx`, `SOURCE_REGISTER.md`). Official facts are kept separate from community claims
(none used here) and from assumptions (marked **[ASSUMPTION]**).

## Answers to the 14 mandatory questions (`PROJECT_SPEC.md` §4 / verbatim §10)

| # | Question | Answer (official unless marked) | Evidence |
| --- | --- | --- | --- |
| 1 | Can a normal Roblox client capture its host desktop? | _Pending R1d._ | — |
| 2 | Can a published experience access Windows capture APIs? | _Pending R1d._ | — |
| 3 | Can it hold a persistent external WebSocket/SSE connection? | **Not in a published experience.** `HttpService:CreateWebStreamClient` (SSE / RawStream / WebSocket) "is available in **Studio only**" and is limited to **4 clients** at once. Production must use request/response HTTP (polling / long-polling). | F-0010 |
| 4 | Which HTTP operations can it perform? | `RequestAsync` (GET, HEAD, POST, PUT, DELETE, OPTIONS, TRACE, PATCH; custom headers except locked `User-Agent`/`Roblox-Id`; request body any string incl. binary; optional gzip request compression; `Timeout`), plus `GetAsync`/`PostAsync` shorthands. **500 external requests/min per server** (Open Cloud separately 2500/min). Ports: not 1194, not < 1024 except 80/443. Response-size limit and binary-safe response bodies **not documented → test**. | F-0007, F-0008, F-0009 |
| 5 | In which execution contexts? | **Experience servers** (class description: requests "sent from experience servers"); secrets only in **server scripts** (client scripts get `Can't find secret with given key`); `localhost`/`127.0.0.1` documented only for **Studio plugins** on the same computer. Client-side HTTP is not documented as supported. | F-0007, F-0009, F-0011 |
| 6 | Can it build/modify images from raw pixels at runtime? | **Yes** — `AssetService:CreateEditableImage` + `EditableImage:WritePixelsBuffer` (RGBA8 buffer). | F-0001 |
| 7 | Exact EditableImage APIs, parameter types, pixel formats, memory limits, restrictions? | `CreateEditableImage(options: Dictionary?) -> EditableImage?` (default 512×512, **max 1024×1024**, not resizable); `WritePixelsBuffer(position: Vector2, size: Vector2, buffer)`; `ReadPixelsBuffer(position, size) -> buffer`; 4 bytes/pixel **R,G,B,A**, top-left origin; strict **client** memory budget (returns `nil` when exhausted; server/Studio unlimited); **only one displayed EditableImage updates per frame**; **disabled by default in published games** (Enable Mesh / Image APIs). | F-0001…F-0004 |
| 8 | Do dynamic image changes replicate? | **No.** `Content.Object` values are not replicated; clients receive an unusable checkerboard placeholder. Each client must build its own EditableImage. | F-0005 |
| 9 | Practical RemoteEvent / binary payload and bandwidth limits? | _Pending R1c._ | — |
| 10 | Efficient multi-client delivery? | _Pending R1c_ (consequence of Q8: server must forward bytes to every client). | F-0005 |
| 11 | Protecting external credentials? | Experience **secrets store** (Creator Dashboard ⟩ Secrets; owner only; value ≤ 1,024 chars; bound to a domain pattern). `HttpService:GetSecret(key)` → non-printable `Secret`, server-only, usable in URL/headers via `AddPrefix`/`AddSuffix` (not in body). Studio playtests need **Local Secrets** (Experience Settings ⟩ Security). | F-0011 |
| 12 | Required HTTP/domain/permission settings? | **Allow HTTP Requests** (Studio ⟩ File ⟩ Experience Settings ⟩ Security) **and** **Enable Mesh / Image APIs** (Creator Dashboard ⟩ Configure ⟩ Settings, or Studio ⟩ Experience Settings ⟩ Security ⟩ Allow Mesh / Image APIs); a secret whose domain matches the relay host; relay on HTTPS port 443. | F-0003, F-0009, F-0011 |
| 13 | Studio vs published differences? | Partial: EditableImage fails by default when published until the toggle is on; Studio/server have unlimited editable memory, clients do not. | F-0003, F-0004 |
| 14 | What works in real published games? | _Pending R1d + owner test (no Roblox runtime in the agent sandbox, KI-0002)._ | — |

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
