# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-24 19:56 UTC (7th session start — `a5dc5ee` verified; T-0004 ScreenBlox research restarted)._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (see `PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) |
| Branch | `main` |
| Latest verified remote commit | `a5dc5ee38a88b969c8281d16c8842649c61f1a55` — "Session 6 start …" (verified 2026-10-24 19:55 UTC by the 7th Notion AI session: head of `main` per `list_branches`/`list_commits` (8 commits); 21 files read back, all local `git hash-object` SHAs MATCH the root, `docs/research` and `scripts/agent` listings). This file is part of a follow-up commit (a file cannot contain its own SHA; read it with `list_commits`; it is recorded in `WORK_LOG.md` at the next checkpoint). |
| Current milestone | Stage 3 — research: R1 (official API) **done**; R2 (existing projects T-0004…T-0007) next |
| Chosen architecture | **Not formally chosen yet** (T-0008 after T-0004…T-0007). Official-docs constraints already force: native Windows capture app outside Roblox (F-0020); public HTTPS endpoint polled by the Roblox **server** with `RequestAsync` (F-0007…F-0010); reliable `RemoteEvent` + `buffer` fan-out, zstd decompressed by `EncodingService` (F-0013…F-0016); client-side `EditableImage` on a client-owned `SurfaceGui` (F-0005, F-0021). `VideoFrame`/`VideoPlayer` rejected for live content (F-0018, F-0019). |
| Implemented components | None (documentation and agent helper scripts only) |
| Completed work | Tool inspection; repo created and verified; spec preserved (structured + verbatim); memory documents; T-0003 official API verification R1a–R1d (F-0001…F-0022; all 14 questions answered at documentation level) |
| In-progress work | T-0004 ScreenBlox investigation — **restarted** by the 7th session at 19:55 UTC. The 6th session started T-0004 at 19:06 UTC but no commit after `a5dc5ee` exists, so its T-0004 work was never checkpointed and is lost (KI-0004) |
| Remaining work | T-0004…T-0007 (existing projects); T-0008 architecture decision; T-0009…T-0014 (codec, capture app, relay, Roblox scripts, tests, packaging) |
| Known blockers | No Windows machine and no Roblox Studio/runtime in the agent sandbox (`KNOWN_ISSUES.md` KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Important verified facts (Roblox, official docs) | EditableImage: RGBA8 `WritePixelsBuffer`, max 1024×1024, one displayed image updated per frame, disabled in published games until **Enable Mesh / Image APIs**, client memory budget (nil on exhaustion), **does not replicate** (F-0001…F-0006). HttpService: server-side `RequestAsync`, **500 external requests/min per server**, Allow HTTP Requests, localhost only for Studio plugins, ports 80/443/≥1024 (F-0007…F-0009). **WebStreamClient is Studio-only** (F-0010). Secrets: server-only `GetSecret`, domain-bound, URL/headers only (F-0011). Remotes: reliable RemoteEvent ordered, no documented size cap; **UnreliableRemoteEvent drops > 1,000 B** (F-0013, F-0014). buffer little-endian, copied through remotes (F-0015). **EncodingService: native Zstd + Base64 + hashes** (F-0016). ~50 KB/s per-client receive planning target (F-0017). **VideoFrame = uploaded assets only** (2,000 Robux/upload, max 2 playing) (F-0018, F-0019). **No API captures the desktop**; CaptureService records only the experience (F-0020). SurfaceGui in PlayerGui + Adornee recipe (F-0021). Studio test modes are simulations (F-0022). |
| Important assumptions / unverified | Binary-safe HTTP response bodies and maximum response size (F-0007); practical RemoteEvent size/throughput ceiling (F-0013, F-0017); EncodingService availability/speed on clients (F-0016); everything at runtime (no Studio/published test yet). |
| Test status | No tests yet (research phase). |
| Latest successful checkpoint | Session 6 start (`a5dc5ee`) — verified by the 7th session |
| Local vs remote | Synchronized as of `a5dc5ee` except the edits contained in the commit that carries this file (local working copy `/data/roblox-live-pc-screen` is temporary) |
| **Exact next action** | T-0004: investigate ScreenBlox (Reb0rnEnder) — locate the DevForum resource and any source repository, read the source (capture, transport, image format, reconstruction, update rate, hosting), record F-0023+ / S-0028+ and `docs/research/EXISTING_PROJECTS.md`; checkpoint; then T-0005 (Icy-Monster), T-0006 (RSSP), T-0007, T-0008 |
