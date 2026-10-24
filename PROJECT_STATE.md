# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-24 18:20 UTC (checkpoint R1b — research R1 in progress)._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (see `PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) |
| Branch | `main` |
| Latest verified remote commit | `9de19e74e5dc0fcd2d710fd7f1702360ede80a9f` — "Research R1a …" (verified 2026-10-24 18:15 UTC by a new Notion AI session: head of `main` per `list_branches`/`list_commits`; `get_commit` lists the 7 expected files; 20 files read back and all local `git hash-object` SHAs MATCH). This file is part of the follow-up commit "Research R1b: HttpService / WebStreamClient / secrets facts (F-0007..F-0012, S-0005..S-0011)" (a file cannot contain its own SHA; the SHA is recorded in `WORK_LOG.md` at the next checkpoint and can always be read with `list_commits`). |
| Current milestone | Stage 3 — research (R1: official Roblox API verification) |
| Chosen architecture | **Not chosen yet** (research pending; options A–F in `PROJECT_SPEC.md` §5). Constraints already fixed by official docs: client-side EditableImage reconstruction (F-0005), server-side HTTP polling of a public HTTPS endpoint (F-0007…F-0010). |
| Implemented components | None (documentation and agent helper scripts only) |
| Completed work | Tool inspection; repo created and verified; spec preserved (structured + verbatim); memory documents; R1a (EditableImage group, F-0001…F-0006); R1b (HttpService / WebStreamClient / secrets, F-0007…F-0012) |
| In-progress work | T-0003 research R1: R1a + R1b done; R1c (RemoteEvent / UnreliableRemoteEvent / buffer / EncodingService) next; R1d (VideoFrame / VideoPlayer / SurfaceGui / CaptureService / VideoCaptureService, Q1/Q2/Q13/Q14) after |
| Remaining work | R1c, R1d; T-0004…T-0007 (existing projects); T-0008 architecture decision; Stages 6–12 (implementation, tests, packaging, audit) |
| Known blockers | No Windows machine and no Roblox Studio/runtime in the agent sandbox (see `KNOWN_ISSUES.md` KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Important verified facts | Repo exists, private, owner `Meganugger`, default branch `main`; GitHub MCP read/write tools listed in `GITHUB_WORKFLOW.md` |
| Important verified facts (Roblox) | EditableImage: RGBA8 `WritePixelsBuffer`, max 1024×1024, one displayed image updated per frame, disabled in published games until **Enable Mesh / Image APIs** is on, client memory budget (nil on exhaustion), **does not replicate** → client-side reconstruction (F-0001…F-0006). HttpService: server-side `RequestAsync`, **500 external requests/min per server**, Allow HTTP Requests toggle, localhost only for Studio plugins, ports 80/443/≥1024 (not 1194) (F-0007…F-0009). **WebStreamClient (SSE/WebSocket) is Studio-only** (F-0010). Secrets: server-only `GetSecret`, domain-bound, URL/headers only (F-0011). |
| Important assumptions / unverified | Binary-safe HTTP response bodies and maximum response size (undocumented, F-0007); everything at runtime (no Studio/published test yet). |
| Test status | No tests yet (research phase). |
| Latest successful checkpoint | Research R1a (`9de19e7`) — verified this session; R1b is the commit carrying this file |
| Local vs remote | Synchronized as of `9de19e7` except the R1b edits contained in the commit that carries this file (local working copy `/data/roblox-live-pc-screen` is temporary) |
| **Exact next action** | T-0003 R1c: read `RemoteEvent`, `UnreliableRemoteEvent`, `BaseRemoteEvent`, `buffer` library, `EncodingService`, `CompressionAlgorithm`, guide `scripting/events/remote.md` (payload limits, supported types, throttling); record F-0013+; then R1d |
