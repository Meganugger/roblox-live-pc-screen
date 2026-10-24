# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-24 18:03 UTC (checkpoint R1a — research R1 in progress)._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (see `PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) |
| Branch | `main` |
| Latest verified remote commit | `764439c07322d0978176f52e63a96faed76697bf` — "Checkpoint 1b …" (re-verified 2026-10-24 17:58 UTC by a new session: head of `main`; 20 files read back, SHAs match). This file is in the follow-up commit "Research R1a …" (its SHA is recorded in `WORK_LOG.md` at the next checkpoint). |
| Current milestone | Stage 3 — research (R1: official Roblox API verification) |
| Chosen architecture | **Not chosen yet** (research pending; options A–F in `PROJECT_SPEC.md` §5) |
| Implemented components | None (documentation and agent helper scripts only) |
| Completed work | Tool inspection; repo created and verified; spec preserved (structured + verbatim); memory documents drafted |
| In-progress work | T-0003 research R1: R1a done (EditableImage group, F-0001…F-0006); R1b–R1d pending |
| Remaining work | Everything in Stages 3–12 (research, feasibility, architecture, implementation, tests, packaging, audit) |
| Known blockers | No Windows machine and no Roblox Studio/runtime in the agent sandbox (see `KNOWN_ISSUES.md` KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Important verified facts | Repo exists, private, owner `Meganugger`, default branch `main`; GitHub MCP read/write tools listed in `GITHUB_WORKFLOW.md` |
| Important verified facts (Roblox) | EditableImage: RGBA8 `WritePixelsBuffer`, max 1024×1024, one displayed image updated per frame, disabled in published games until **Enable Mesh / Image APIs** is on, client memory budget (nil on exhaustion), **does not replicate** → client-side reconstruction (F-0001…F-0006) |
| Important assumptions | None about Roblox — all Roblox capabilities must be verified from official docs before use |
| Test status | No tests yet |
| Latest successful checkpoint | Checkpoint 1b (`764439c`) — re-verified this session |
| Local vs remote | Synchronized as of `764439c` except the R1a edits contained in the commit that carries this file |
| **Exact next action** | T-0003 R1b: HttpService (limits, contexts, `GetSecret`), `WebStreamClient` (+ enums), `Secret`, http-service & secrets guides; then R1c, R1d |
