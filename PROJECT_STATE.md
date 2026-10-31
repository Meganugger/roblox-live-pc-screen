# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-31 (29th session, end). **PR #1 is merged into `main`** (D-0010; the owner asked the agent
to merge). `main` is the current state; new work goes to a new `claude/*` branch + PR. Start with
`list_pull_requests` (a newer open PR supersedes this file) and `list_commits` on `main`._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (`PROJECT_SPEC.md`; rewritten prompt `docs/IMPROVED_PROMPT.md`). Owner directive 2026-10-31: **maximum quality, ignore the 50 KB/s guidance, PC requirements apply** |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private) |
| Branches | `main` = merge of PR #1 (head `claude/rlps-session-28-finish`, last verified head before this file: `WORK_LOG.md` last row); the merged branch is deleted after the merge |
| Architecture | D-0002 + D-0006…D-0009 (`ARCHITECTURE.md`, `docs/PROTOCOL.md`): capture (mss / DXGI) → hybrid encoder at capture time (lossless / bit-exact DCT / scroll COPY tiles, lossless refinement) under the byte rate and fps cap reported by Roblox → chain ring → authenticated long-poll returning **bundles** of frames → tunnel → one Roblox server poll loop (playout; `RlpsFanout`: played history + per-viewer flow control from processed-byte acks — slow viewers held and caught up (D-0009); AIMD rate and fps cap follow the median viewer; `fresh=1` keyframe requests) → reliable RemoteEvent → clients decode in a time-budgeted queue → one EditableImage per client on the TV |
| Research | Done at source level: ScreenBlox (T-0004), Icy-Monster, RSSP (incl. release archives), MahanBig/roblox-screen-stream, luavid + 6 more (T-0005…T-0007, `docs/research/EXISTING_PROJECTS.md` §2–7, F-0037…F-0040) |
| Verified (sandbox) | ruff clean; Python 85/85 (+327 subtests); Luau specs 6,588/0 (modules and specs type-checked) (Luau pixels bit-identical to Python incl. DCT and COPY; fan-out with real vectors and a network simulation); Rojo build + luau-lsp strict OK; **live pipeline 25/25** (real capture → real frame service → unmodified Roblox scripts under emulation; lossy DCT frames shown bit-exactly, refinement to the exact desktop, scrolling via copies, a 10 kB/s viewer held while the fast one keeps the full rate, base64 fallback) — TR-0011…TR-0013 |
| Verified (CI) | PR #1 GitHub Actions: all 5 jobs green at `6033ac1` incl. the live test with real Windows GDI capture (F-0034); at `96badc5` the Windows live test exposed the slow-viewer bug fixed by D-0009; **5/5 green again at `5a56a07`** (TR-0012) and after the clean-up at `bc9ea90` (TR-0013) |
| Performance (MEASURED, 2.1 GHz sandbox) | 1024×576 @ 30 fps: desktop work, scrolling, video in a window ≤ 22 ms/frame, full-screen motion 34–37 ms; at 2 MB/s video DCT q 92–98; text scrolling 176 kB/s lossless via copies; static 0 B/s (PERFORMANCE.md) |
| Not verified | Real Roblox: replication throughput, client decode speed (`--!native` on clients), raw-body probe on live servers, Creator Dashboard settings, tunnel hop; owner's PC (encode time, dxcam, multi-monitor/DPI/HDR); Tk sharing window |
| Blockers | None for the agent. Owner-only (needs Windows + Roblox Studio + the owner's Roblox account): acceptance test INSTALL D/E (T-0018), Community Standards review (T-0016) |
| Exact next action | Owner runs `docs/deployment/INSTALL.md` A–E and records `RlpsServer` attributes `RateBps`, `FpsCap`, `LagMs`, `MaxLagMs`, `LaggingViewers`, `BodyMode`, `LastError` and each client's `DecodeMsPerFrame` in a new `TEST_RESULTS.md` row (TR-0014). Agent (next session): tune defaults from those numbers; optional T-0017 |
