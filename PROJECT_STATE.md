# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-31 (29th session, end). All work since `e44fa8a` is on branch **`claude/rlps-session-28-finish`**
(draft **PR #1** into `main`), not yet merged (D-0004). Start with `list_pull_requests` + `list_commits` on that
branch: newer commits may exist._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (`PROJECT_SPEC.md`; rewritten prompt `docs/IMPROVED_PROMPT.md`). Owner directive 2026-10-31: **maximum quality, ignore the 50 KB/s guidance, PC requirements apply** |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private) |
| Branches | `main` @ `e44fa8a` · `claude/rlps-session-28-finish` = PR #1 (this file is in its head commit; last verified SHA before it: `WORK_LOG.md` last row) |
| Architecture | D-0002 + D-0006…D-0008 (`ARCHITECTURE.md`, `docs/PROTOCOL.md`): capture (mss / DXGI) → hybrid encoder at capture time (lossless / bit-exact DCT / scroll COPY tiles, lossless refinement) under the byte rate and fps cap reported by Roblox → chain ring → authenticated long-poll returning **bundles** of frames → tunnel → one Roblox server poll loop (playout, relay history, AIMD rate from client acks, fps cap from client decode time, lagging viewers paused/resynced) → reliable RemoteEvent → clients decode in a time-budgeted queue → one EditableImage per client on the TV |
| Research | Done at source level: ScreenBlox (T-0004), Icy-Monster, RSSP (incl. release archives), MahanBig/roblox-screen-stream, luavid + 6 more (T-0005…T-0007, `docs/research/EXISTING_PROJECTS.md` §2–7, F-0037…F-0040) |
| Verified (sandbox) | Python 84/84 (+327 subtests); Luau specs 5,984/0 (Luau pixels bit-identical to Python incl. DCT and COPY); Rojo build + luau-lsp strict OK; **live pipeline 25/25** (real capture → real frame service → unmodified Roblox scripts under emulation; lossy DCT frames shown bit-exactly, refinement to the exact desktop, scrolling via copies, congestion control with a throttled viewer, base64 fallback) — TR-0011 |
| Verified (CI) | PR #1 GitHub Actions: all 5 jobs green at `6033ac1` incl. the live test with real Windows GDI capture (F-0034); later commits: see PR checks / `TEST_RESULTS.md` |
| Performance (MEASURED, 2.1 GHz sandbox) | 1024×576 @ 30 fps: every benchmark workload encodes in < 33 ms; at 2 MB/s full-screen/partial video DCT q≈90; text scrolling 176 kB/s lossless via copies; static 0 B/s (PERFORMANCE.md) |
| Not verified | Real Roblox: replication throughput, client decode speed (`--!native` on clients), raw-body probe on live servers, Creator Dashboard settings, tunnel hop; owner's PC (encode time, dxcam, multi-monitor/DPI/HDR); Tk sharing window |
| Blockers | None for the agent. Owner: merge PR #1 (T-0019), acceptance test INSTALL D/E (T-0018), Community Standards review (T-0016) |
| Exact next action | Owner runs `docs/deployment/INSTALL.md` A–E and records `RlpsServer` attributes `RateBps`, `FpsCap`, `MaxLagMs`, `BodyMode`, `LastError` and each client's `DecodeMsPerFrame` in a new `TEST_RESULTS.md` row (TR-0012). Agent (next session): tune defaults from those numbers; optional T-0017 |
