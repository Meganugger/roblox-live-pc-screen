# TASKS.md — Persistent execution tracking

Statuses: `TODO` · `IN_PROGRESS` · `BLOCKED` · `DONE` · `NEEDS_RETEST`. A task is DONE only with evidence.

| ID | Task | Status | Depends on | Files | Completion criteria |
| --- | --- | --- | --- | --- | --- |
| T-0001 | Inspect GitHub tools; create + verify private repo | DONE | — | `GITHUB_WORKFLOW.md` | Repo readable via MCP; metadata verified (private, `main`) |
| T-0002 | Create persistent-memory system; push; verify remotely (checkpoint 1) | DONE (`67a6e4a`) | T-0001 | all `*.md`, `scripts/agent/` | Commit visible in `list_commits`; blob SHAs match |
| T-0003 | Official Roblox API verification (14 questions) — R1a (EditableImage group, `9de19e7`); R1b (HttpService/WebStreamClient/secrets, F-0007…F-0012, `3287d4e`); R1c (remotes/buffer/EncodingService/network budget, F-0013…F-0017, `9a6b1f4`); R1d (VideoFrame/VideoPlayer/SurfaceGui/capture services/testing modes, F-0018…F-0022) — all 14 answered at documentation level; runtime confirmation belongs to T-0012/T-0013 + owner tests | DONE | T-0002 | `docs/research/ROBLOX_API_FACTS.md`, logs | All answers cited or marked unknown; checkpoint verified |
| T-0004 | Investigate ScreenBlox (Reb0rnEnder) — part 1 done (8th session: repo `Reb0rnEnder/ScreenBlox` @ `b873f78` located, Python side read, F-0023…F-0026); part 2 next: Roblox side `v4.7.rbxl` + full DevForum thread 2823814 | IN_PROGRESS | T-0002 | `docs/research/EXISTING_PROJECTS.md`, logs | Python + Roblox source and thread examined; findings + checkpoint |
| T-0005 | Investigate Icy-Monster/Screen-Sharing-in-Roblox | TODO | T-0002 | `docs/research/` | Source examined; findings + checkpoint |
| T-0006 | Investigate RSSP by ssavnayt | TODO | T-0002 | `docs/research/` | Source examined; findings + checkpoint |
| T-0007 | Investigate additional implementations (Reddit "I was tired, so I made AnyDesk in Roblox", archived Screen-Sharing-in-Roblox + forks, DevForum "EditableImage Screen \"Sharing\"" S-0030, successors). The 2024 "ScreenShare free game source" thread is ScreenBlox itself (F-0023) → covered by T-0004 | TODO | T-0002 | `docs/research/` | Findings + checkpoint |
| T-0008 | Architecture comparison A–F and decision | TODO | T-0003..T-0007 | `DECISIONS.md`, `ARCHITECTURE.md` | Decision recorded before implementation |
| T-0009 | Wire protocol + codec (Python encoder, Luau decoder) | TODO | T-0008 | `desktop/`, `roblox/` | Round-trip tests pass |
| T-0010 | Desktop capture application (Windows) | TODO | T-0008 | `desktop/` | Real capture tested where possible |
| T-0011 | Relay / frame service with auth and rate limits | TODO | T-0008 | `relay/` | Auth + invalid-request tests pass |
| T-0012 | Roblox server + client + physical screen | TODO | T-0008 | `roblox/` | Static analysis + harness tests pass |
| T-0013 | Test suites, benchmarks, CI workflow | TODO | T-0009..T-0012 | `tests/`, `.github/workflows/` | Results recorded |
| T-0014 | Packaging: guides, reports, archive, final audit | TODO | all | `docs/` | Final verified checkpoint |
| T-0015 | Recheck whether `HttpService:CreateWebStreamClient` became available in live games (currently Studio-only, F-0010) | TODO | — | `FINDINGS_LOG.md` | Docs re-read at each research refresh; finding updated |
