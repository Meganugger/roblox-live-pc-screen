# TASKS.md — Persistent execution tracking

Statuses: `TODO` · `IN_PROGRESS` · `BLOCKED` · `DONE` · `NEEDS_RETEST`. A task is DONE only with evidence.

| ID | Task | Status | Depends on | Files | Completion criteria |
| --- | --- | --- | --- | --- | --- |
| T-0001 | Inspect GitHub tools; create + verify private repo | DONE | — | `GITHUB_WORKFLOW.md` | Repo readable via MCP; metadata verified (private, `main`) |
| T-0002 | Create persistent-memory system; push; verify remotely (checkpoint 1) | IN_PROGRESS | T-0001 | all `*.md`, `scripts/agent/` | Commit visible in `list_commits`; blob SHAs match |
| T-0003 | Official Roblox API verification (14 questions) | TODO | T-0002 | `docs/research/ROBLOX_API_FACTS.md`, logs | All answers cited or marked unknown; checkpoint verified |
| T-0004 | Investigate ScreenBlox (Reb0rnEnder) | TODO | T-0002 | `docs/research/` | Source/posts examined; findings + checkpoint |
| T-0005 | Investigate Icy-Monster/Screen-Sharing-in-Roblox | TODO | T-0002 | `docs/research/` | Source examined; findings + checkpoint |
| T-0006 | Investigate RSSP by ssavnayt | TODO | T-0002 | `docs/research/` | Source examined; findings + checkpoint |
| T-0007 | Investigate additional implementations (ScreenShare 2024, Reddit AnyDesk, forks, successors) | TODO | T-0002 | `docs/research/` | Findings + checkpoint |
| T-0008 | Architecture comparison A–F and decision | TODO | T-0003..T-0007 | `DECISIONS.md`, `ARCHITECTURE.md` | Decision recorded before implementation |
| T-0009 | Wire protocol + codec (Python encoder, Luau decoder) | TODO | T-0008 | `desktop/`, `roblox/` | Round-trip tests pass |
| T-0010 | Desktop capture application (Windows) | TODO | T-0008 | `desktop/` | Real capture tested where possible |
| T-0011 | Relay / frame service with auth and rate limits | TODO | T-0008 | `relay/` | Auth + invalid-request tests pass |
| T-0012 | Roblox server + client + physical screen | TODO | T-0008 | `roblox/` | Static analysis + harness tests pass |
| T-0013 | Test suites, benchmarks, CI workflow | TODO | T-0009..T-0012 | `tests/`, `.github/workflows/` | Results recorded |
| T-0014 | Packaging: guides, reports, archive, final audit | TODO | all | `docs/` | Final verified checkpoint |
