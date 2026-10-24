# PROJECT_SPEC.md — Complete Project Specification

> Authoritative requirements for `roblox-live-pc-screen`.
> The **verbatim original assignment** (all 12 parts, ~57 KB) is preserved (line endings normalised to LF) in
> [`docs/ORIGINAL_SPEC_VERBATIM.md`](docs/ORIGINAL_SPEC_VERBATIM.md). If this structured summary and the verbatim text ever
> disagree, **the verbatim text wins**. Section numbers below (§n) refer to the verbatim document.

## 0. One-sentence objective

Build a real, working, reproducible system that displays the owner's **actual Windows PC desktop** (real OS screen capture —
never prerecorded video, static images, simulated desktops or fake demos) on a **physical television/monitor inside a
published Roblox experience**, updating as the desktop changes, with all research, decisions, code, tests and next steps
persisted in this GitHub repository so that a brand-new AI chat with zero memory can continue the work.

## 1. Owner priorities (in order, §7)

1. Genuine end-to-end functionality. 2. Correctness and supported APIs. 3. Reliability. 4. Useful image quality and
responsive updates. 5. Security and privacy. 6. Low bandwidth/resource use. 7. Easy installation and troubleshooting.
8. Sensible operating cost. Never sacrifice genuine functionality for appearance.

## 2. Intended data flow (may be redesigned if research proves a better supported method, §7)

```
ACTUAL PC DESKTOP → REAL SCREEN CAPTURE → FRAME PROCESSING / ENCODING / COMPRESSION → SECURE TRANSPORT OR RELAY
→ PUBLISHED ROBLOX EXPERIENCE (server) → ROBLOX CLIENT-SIDE IMAGE RECONSTRUCTION → PHYSICAL SCREEN IN 3D WORLD
→ AUTHORIZED PLAYERS SEE THE CHANGING PC DISPLAY
```

Behaviour: opening a browser, moving windows, scrolling, playing a video, launching apps — the Roblox screen must update.

## 3. GitHub persistence requirements (§1–§6, §35–§37)

- Use the connected GitHub integration to actually execute operations (inspect tools, create repo, commit, verify). Never
  invent tools, URLs, SHAs, branches or results. Never expose tokens/secrets. Prefer a **private** repo.
- Repo name `roblox-live-pc-screen` (reuse only if it is genuinely this project; never modify unrelated repos).
- Mandatory cycle for every substantial source/milestone:
  **INVESTIGATE → DOCUMENT → UPDATE PROJECT STATE → COMMIT → SYNCHRONIZE → VERIFY REMOTELY → CONTINUE.**
  Do not move past a substantial source or milestone while its results exist only in working memory.
- Distinguish: local write ≠ GitHub write ≠ commit ≠ sync ≠ remote read-back verification. Never claim a save without
  remote evidence. On failure: inspect error, determine local vs remote state, retry safely, check conflicts, document.
- No force-push / history rewriting; never overwrite newer remote work with an older local copy.
- Required documents (purpose must be preserved; structure adaptable): `README.md`, `PROJECT_SPEC.md`, `PROJECT_STATE.md`,
  `SESSION_HANDOFF.md`, `FINDINGS_LOG.md`, `SOURCE_REGISTER.md`, `DECISIONS.md`, `TASKS.md`, `WORK_LOG.md`,
  `TEST_RESULTS.md`, `KNOWN_ISSUES.md`, `ARCHITECTURE.md`, `SECURITY.md`, `PERFORMANCE.md`, `CHANGELOG.md`,
  `GITHUB_WORKFLOW.md`, plus `docs/{research,architecture,implementation,testing,deployment}/`, and source dirs as needed
  (`roblox/`, `desktop/`, `relay/`, `tests/`, `scripts/`, `.github/workflows/`).
- Field requirements per document (see §5.1–§5.12 verbatim): findings need IDs `F-0001…`, date, research question,
  query/approach, source ID+URL, what was examined, finding, evidence, source type, confidence/limitations, impact on
  architecture, resulting action, related files/decisions, uncertainty, checkpoint commit. Sources need statuses
  *Discovered / Accessed / Read / Source code inspected / Independently tested / Unavailable / Requires further
  investigation*. Tasks use `TODO / IN_PROGRESS / BLOCKED / DONE / NEEDS_RETEST`. Tests record ID, purpose, environment,
  commit, command, expected, actual, pass/fail, evidence, defects, fixes, rerun-needed; mark stale results when code changes.
- Initial memory system must be committed and remotely verified **before** substantial research (§6).
- Every new session: locate repo → inspect branch/commits/tree/CI → read continuity docs in order (§35 Step 3) →
  cross-check docs against real code → resume the exact next task → keep checkpointing → before stopping update
  `PROJECT_STATE.md`, `SESSION_HANDOFF.md`, `TASKS.md`, `WORK_LOG.md`, findings/decisions/tests/issues.

## 4. Mandatory research (§8–§10)

Use web search, browsing, GitHub search and code reading. Search with alternative terminology; follow links to originals.
Topics: Roblox screen sharing; streaming a Windows desktop into Roblox; dynamic in-world rendering; `EditableImage` and
runtime image construction; pixel grids; Python screen capture; HTTP frame retrieval; SSE and WebSockets; binary image
transport; RemoteEvent bandwidth/payload limits; delta frames; changed-region updates; palette compression; RLE;
reduced-colour formats; local servers vs remote relays; tunnelling; published-game HTTP restrictions; dynamic media/video
limits; multi-client distribution; compression and latency; existing implementations and successors.

Named projects that **must** be investigated (source code, revisions, issues, forks, licences — not just intros/videos):
- **ScreenBlox** (Roblox DevForum resource by **Reb0rnEnder**): capture method, transport, image format, reconstruction
  (pixel elements vs EditableImage), update rate/quality, hosting requirements, bugs, forks/successors, and forum
  discussions on RemoteEvent payload size, EditableImage performance, local servers and exposed endpoints.
- **Icy-Monster/Screen-Sharing-in-Roblox** (GitHub): Python + Roblox parts, compression (repetition/RLE), transport,
  reconstruction, install, port-forwarding, licence, issues, forks, archive status, successors; useful vs replaceable parts.
- **RSSP by ssavnayt** ("Roblox screen-sharing API"): source, config, endpoints, auth, capture, Roblox integration, deps,
  history, issues; HTTP polling vs SSE vs raw bytes vs compression across versions; which parts work under current rules.
- Additional: the archived Screen-Sharing-in-Roblox project and forks; the 2024 DevForum **ScreenShare** free game source;
  Reddit "**I was tired, so I made AnyDesk in Roblox**"; older DevForum screen-casting threads; EditableImage / pixel-grid /
  palette / delta implementations; newer successors; other credible solutions. Respect licences (no copying without
  checking licence/attribution).

Official Roblox API verification (current Creator docs) for: `VideoFrame`, `EditableImage`, `AssetService`, `SurfaceGui`,
`ImageLabel`/image APIs, `HttpService` (restrictions, quotas, execution contexts), `RemoteEvent`, `UnreliableRemoteEvent`,
`buffer` and supported data types, Creator Dashboard security settings, server-side secrets, published-experience
networking restrictions, runtime image construction/updates, asset/media restrictions. Must answer the 14 questions in §10:
(1) can a normal client capture its host desktop? (2) can a published experience access Windows capture APIs? (3) can it
hold a persistent external WebSocket/SSE connection? (4) which HTTP operations can it perform? (5) in which execution
contexts? (6) can it build/modify images from raw pixels at runtime? (7) exact EditableImage APIs, parameter types, pixel
formats, memory limits, availability restrictions? (8) do dynamic image changes replicate? (9) practical RemoteEvent /
binary payload and bandwidth limits? (10) efficient multi-client delivery? (11) protecting external credentials? (12)
required HTTP/domain/permission settings? (13) Studio vs published differences? (14) what works in real published games?
Separate official docs from community reports and assumptions.
Hard rules: no Roblox-only desktop capture without credible evidence; do not assume arbitrary stream URLs work in
`VideoFrame`; do not assume localhost is reachable from a remote Roblox server; do not assume client-side image changes
replicate; do not invent APIs. Save findings to GitHub before relying on them.

## 5. Architecture comparison (§11)

Compare at least: **A** Roblox-only Luau; **B** grid of parts/GUI pixels; **C** EditableImage reconstruction; **D** Windows
capture app + local HTTP service; **E** capture app + secure external relay + client-side reconstruction; **F** anything
better found. Criteria: feasibility, API support, image quality, resolution, update rate, latency, bandwidth, CPU/memory,
Roblox server cost, client rendering, multi-client scalability, reliability, deployment complexity, security, operating
cost. Name existing projects demonstrating each; distinguish demonstrated vs theoretical. Record the selection in
`DECISIONS.md` and `ARCHITECTURE.md` **before** extensive implementation; preserve reasons for later changes.

## 6. Implementation requirements (§12–§16)

Build every component the chosen architecture needs (capture app, processing/compression, transport, local service, relay,
HTTP API, auth, Roblox server/client scripts, shared Luau modules, screen model, config templates, install/start/stop
scripts, automated tests, diagnostics, benchmarks, docs) and connect them end-to-end. No unnecessary services.

**Desktop capture app (§13):** genuine capture with a maintained Windows-compatible library; primary monitor by default;
configurable resolution and capture rate; quality/performance settings; handle resolution changes; recover from capture
source loss without crashing; detect unchanged frames; avoid needless encoding/transfer; clear sharing status; explicit
start action; immediate stop; recover from temporary network failures; diagnostics without logging screen contents; monitor
selection where practical; window capture only if genuinely supported. Test real capture where possible; pin compatible
dependency versions; respect licences.

**Encoding/transport (§14):** evaluate RGB/RGBA, reduced resolution, RGB565/compact colour, palette, RLE, delta frames,
changed regions, hybrids; optimise the whole pipeline (capture, convert, compress, transmit, validate, reconstruct, render).
Do not assume Roblox decodes JPEG/PNG/H.264. Verify EditableImage buffer formats. Verify RemoteEvent constraints and
packetise/reassemble as needed; never send millions of JSON numbers; no Instance-per-pixel unless benchmarks justify it.
Must implement: frame IDs, dimension validation, packet-size limits, bounds checks, integrity checks, timeouts,
incomplete-frame rejection, out-of-order handling, reconnection, rate limiting, backpressure, queue/memory limits, cleanup
of incomplete transfers. **Never display a partially reconstructed frame as complete.** Producer must not overwhelm clients.
Record benchmark methods/results.

**Physical screen (§15):** rectangular display; SurfaceGui (or other supported mechanism); dynamically updated image;
correct orientation and aspect ratio; housing/frame; visible sharing indicator; loading, connecting, error and
stopped-sharing states; simple demo room with an easy-to-find TV if no map is supplied; maintainable construction.

**Server/client split (§16):** separate capture, external comms, server frame retrieval, authn/authz, validation, client
reconstruction, display, sync, error reporting, reconnection. Verify whether images must be built per client. One capture
source per experience (not per player). Avoid unnecessary requests, duplicate frames, excess events, unbounded queues,
leaks. Test multi-client where possible; document concurrency limits.

## 7. Performance (§17, §28)

Quality profiles **Low bandwidth / Balanced / High quality**; default chosen by testing or defensible estimate. Benchmark
capture time, encode time, frame sizes before/after compression, bandwidth, server processing, client reconstruction,
end-to-end latency, CPU, memory, dropped frames, queue growth — for static desktops and fast-changing content. Do not market
a static-desktop system as video streaming. Pick realistic FPS if 30/60 are impractical. Label measurements vs calculations
vs estimates vs assumptions. Record commands, environments and commits in `TEST_RESULTS.md` and `PERFORMANCE.md`.

## 8. Security and privacy (§18) — 20 mandatory safeguards

1 no silent capture start; 2 explicit user action to share; 3 clear active-sharing indicator; 4 immediate stop; 5 no
webcam/microphone; 6 no keylogging/hidden surveillance; 7 no remote mouse control; 8 no remote keyboard input; 9 no
arbitrary command execution; 10 no general remote-desktop features; 11 no persistent storage of captures by default; 12 no
transmission to undisclosed/untrusted endpoints; 13 no credentials in client-visible code; 14 authenticate external
endpoints; 15 validate requests + rate limits; 16 sharing controls only for authorised users; 17 players cannot access
local files; 18 no generic HTTP proxy; 19 reliable cleanup/shutdown; 20 protect config and keep secrets out of git.
Use Roblox's supported secret-management (investigate), explain relay/tunnel risks, use narrowest access, document tests.

## 9. Published-experience compatibility (§19)

Distinguish Studio, Studio play-testing, published private test servers, public live servers. Document Creator Dashboard
settings, HTTP permissions, domain restrictions, external credentials and deployment steps. Studio success ≠ production.
No Studio-only feature in the essential path. Prefer supported APIs; document experimental/unsupported items.

## 10. Code quality and tests (§20–§24)

No pseudocode, missing modules, undefined variables, unimplemented calls, essential TODOs, placeholder endpoints presented
as real, dummy frames presented as captures, fake success messages, unsupported API calls, unexplained deps, hard-coded
credentials, contradictory instructions, or claimed-but-unrun tests. Use module boundaries, validation, structured errors,
timeouts, cleanup, pinned deps.
- Desktop tests: startup/shutdown, real capture, dimensions, pixel format, resolution change, compression round-trip, change
  detection, auth, invalid requests, network interruption, missing deps, recovery.
- Encoding tests: solid colour, text-heavy, gradients, random noise, changing frames, corrupt payloads, truncated packets,
  wrong dimensions, invalid frame IDs, out-of-order packets; verify orientation, pixel order, colour precision, integrity,
  compression effectiveness.
- Roblox tests: static validation, Luau analysis, automated tests, Studio tests, multi-client; script placement, remotes,
  API compatibility, image creation, buffer updates, frame assembly, payload validation, reconnect, cleanup, repeated
  updates, capture-service-unavailable behaviour. If the Roblox runtime is unavailable, list exactly what could not be run.
- **End-to-end acceptance test (§24):** start capture app on Windows → explicitly enable sharing → start experience →
  approach screen → it shows real PC pixels → change desktop → Roblox display updates → stop sharing → transmission stops
  and screen shows stopped state. If impossible here, build everything, run all intermediate tests, and list remaining
  real-world steps. Never present static tests as end-to-end verification.

## 11. Deliverables (§25–§33)

Research & feasibility report (with links to sources genuinely inspected); complete clean source tree (Roblox scripts,
capture code, codecs, relay if required, config templates, dependency manifests, start/stop scripts, tests, docs; valid Rojo
project if Rojo is used; Studio-importable place/model file if practical — only claim it exists after creating and
verifying it); Windows + Studio installation guide with real commands, separating local development from published
deployment, free/self-hosted options before paid ones; performance report; test report; troubleshooting guide (black
screen, unreachable service, HTTP failures, auth errors, EditableImage restrictions, corrupt frames, wrong orientation, slow
updates, oversized payloads, Studio-vs-published differences, server overload, capture-process crash); convenient Windows
start/stop scripts; ZIP archive (verified contents) if supported; verified GitHub handoff (URL, visibility, branch, latest
verified commit, key dirs, files verified remotely, tests performed, CI results inspected, remaining limitations).

## 12. Workflow stages (§34)

1 GitHub setup & memory → 2 workspace inspection → 3 research (checkpoint each discovery) → 4 feasibility → 5 architecture
→ 6 implementation (checkpoint steps) → 7 testing → 8 debugging (root causes + fixes) → 9 optimisation (benchmarks) →
10 GitHub verification (tree, commits, CI) → 11 packaging (reports, guides, archive) → 12 final audit (consistency; update
all state docs; final verified checkpoint). Do not stop after a plan, a few scripts or a static image. Do not replace real
capture with prerecorded media. If full-motion streaming is impossible within Roblox limits, implement the strongest
genuine alternative and explain the trade-off honestly.

## 13. Final acceptance checklist (§38) — tick only with evidence

Tools inspected · real repo created/selected · repo verified remotely · full spec saved · memory files committed before
research · clean-chat recovery procedure · `PROJECT_STATE.md` current · actionable `SESSION_HANDOFF.md` · findings logged ·
sources registered · decisions recorded · tasks tracked · work log · real test evidence · known issues · named GitHub
projects investigated · official docs checked · real capture implemented · encoder + transport implemented · Roblox
server + client complete · physical screen present/constructible · display updates from real pixels when verified ·
supported APIs only · multi-client within limits · network failures/invalid data handled · credentials and screen content
protected · explicit start/stop · published restrictions investigated · performance measured/estimated · all feasible tests
run · unverified behaviour documented · latest work committed and synced · latest remote checkpoint verified · repo matches
implementation · CI reported accurately · setup matches code · no essential placeholders · archive created/checked if
supported · a new chat can resume without this conversation.

## 14. Required final handoff (§39)

Start with what was actually built, whether the full architecture is feasible, and what is unverified; then Architecture,
Research, GitHub (URL, branch, latest confirmed commit, structure, sync status, CI), Installation, Tests (automated vs local
vs Studio vs published), Performance, Remaining issues (with reasons), Continuity (latest verified checkpoint; whether
continuity files are synced and verified; exact next task from `SESSION_HANDOFF.md`), Files (archive path only if verified).
Never invent URLs/SHAs/findings/results; never present code review as runtime testing or Studio as production proof.
