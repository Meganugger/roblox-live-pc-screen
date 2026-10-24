# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-24 18:33 UTC (checkpoint R1c — research R1 in progress)._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (see `PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) |
| Branch | `main` |
| Latest verified remote commit | `3287d4ed5aa86f9170b15f6aab5355b9ec455711` — "Research R1b …" (verified 2026-10-24 18:24 UTC by a new Notion AI session: head of `main` per `list_branches`/`list_commits`; `get_commit` lists the 7 expected files; 21 files read back and all local `git hash-object` SHAs MATCH). This file is part of the follow-up commit "Research R1c: RemoteEvent / UnreliableRemoteEvent / buffer / EncodingService facts (F-0013..F-0017, S-0012..S-0017)" (a file cannot contain its own SHA; the SHA is recorded in `WORK_LOG.md` at the next checkpoint and can always be read with `list_commits`). |
| Current milestone | Stage 3 — research (R1: official Roblox API verification) |
| Chosen architecture | **Not chosen yet** (research pending; options A–F in `PROJECT_SPEC.md` §5). Constraints already fixed by official docs: client-side EditableImage reconstruction (F-0005); server-side HTTP polling of a public HTTPS endpoint (F-0007…F-0010); reliable RemoteEvent + buffer fan-out, zstd decompressed natively by `EncodingService` (F-0013…F-0016). |
| Implemented components | None (documentation and agent helper scripts only) |
| Completed work | Tool inspection; repo created and verified; spec preserved (structured + verbatim); memory documents; R1a (EditableImage group, F-0001…F-0006); R1b (HttpService / WebStreamClient / secrets, F-0007…F-0012); R1c (remotes / buffer / EncodingService / network budget, F-0013…F-0017) |
| In-progress work | T-0003 research R1: R1a–R1c done; R1d (VideoFrame / VideoPlayer / SurfaceGui / CaptureService / VideoCaptureService; Q1/Q2/Q13/Q14) next |
| Remaining work | R1d; T-0004…T-0007 (existing projects); T-0008 architecture decision; Stages 6–12 (implementation, tests, packaging, audit) |
| Known blockers | No Windows machine and no Roblox Studio/runtime in the agent sandbox (`KNOWN_ISSUES.md` KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Important verified facts (Roblox) | EditableImage: RGBA8 `WritePixelsBuffer`, max 1024×1024, one displayed image updated per frame, disabled in published games until **Enable Mesh / Image APIs** is on, client memory budget (nil on exhaustion), **does not replicate** (F-0001…F-0006). HttpService: server-side `RequestAsync`, **500 external requests/min per server**, Allow HTTP Requests, localhost only for Studio plugins, ports 80/443/≥1024 (F-0007…F-0009). **WebStreamClient is Studio-only** (F-0010). Secrets: server-only `GetSecret`, domain-bound, URL/headers only (F-0011). Remotes: reliable RemoteEvent ordered, no documented size cap; **UnreliableRemoteEvent drops > 1,000 B** (F-0013, F-0014). buffer little-endian, copied through remotes (F-0015). **EncodingService: native Zstd + Base64 + hashes** (F-0016). ~50 KB/s per-client receive planning target (F-0017). |
| Important assumptions / unverified | Binary-safe HTTP response bodies and maximum response size (F-0007); practical RemoteEvent size/throughput ceiling (F-0013, F-0017); EncodingService availability/speed on clients (F-0016); everything at runtime (no Studio/published test yet). |
| Test status | No tests yet (research phase). |
| Latest successful checkpoint | Research R1b (`3287d4e`) — verified this session; R1c is the commit carrying this file |
| Local vs remote | Synchronized as of `3287d4e` except the R1c edits contained in the commit that carries this file (local working copy `/data/roblox-live-pc-screen` is temporary) |
| **Exact next action** | T-0003 R1d: read `VideoFrame`, `VideoPlayer`, `SurfaceGui`, `CaptureService`, `VideoCaptureService` (+ guides) → F-0018+; answer Q1/Q2/Q13/Q14; mark T-0003 DONE; then T-0004 (ScreenBlox) |
