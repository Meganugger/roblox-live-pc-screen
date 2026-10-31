# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-31 (28th session, end). Work of this session is on branch **`claude/rlps-session-28-finish`**
(draft **PR #1** into `main`), not yet on `main` (D-0004). Always start with `list_pull_requests` + `list_commits` on
that branch: newer commits may exist._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (`PROJECT_SPEC.md`; rewritten prompt: `docs/IMPROVED_PROMPT.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private) |
| Branches | `main` @ `e44fa8a` (27th session) · `claude/rlps-session-28-finish` = PR #1 (this session; the commit containing this file is its head — see `WORK_LOG.md` last row for the last verified SHA before it) |
| Architecture | D-0002 + D-0006 (`ARCHITECTURE.md`): Windows app (mss capture → RGB565/888 16×16 tile deltas → zstd parts) serving one authenticated long-poll endpoint on 127.0.0.1 → HTTPS tunnel → one Roblox server poll loop (idle polls, byte pacing) → reliable `RemoteEvent` fan-out of unchanged part records → every client validates, assembles complete frames, writes one `EditableImage` on the TV `SurfaceGui` |
| Implemented | Complete pipeline: `desktop/rlps/` (capture, codec, frame service, app with Tk indicator + console, `--token-only`); `roblox/src/` (server poll loop + relay core, client renderer + assembler, shared protocol/decoder/base64); TV model + Rojo place; `scripts/windows/*.bat`; `tests/e2e/` live pipeline test with a Roblox engine emulation; `scripts/bench.py`; CI `.github/workflows/ci.yml`; docs (PROTOCOL, INSTALL, TROUBLESHOOTING, E2E, SECURITY map, PERFORMANCE, explainer `docs/explainers/SESSION_28.md`) |
| Verified (sandbox) | Python 66/66 (+327 subtests); Luau specs 5,664/0 + luau-analyze; Rojo build + luau-lsp strict with Roblox API definitions; **live pipeline test 21/21** (real Xvfb capture → real frame service → unmodified Roblox scripts under emulation, byte-exact pixels on 2 clients, late joiner, outage recovery, stop, pacing, viewer allowlist, wrong token) — TR-0008, TR-0010 |
| Verified (CI, GitHub Actions on PR #1) | **All 5 jobs green at `6033ac1`**: Python (ubuntu, windows), Luau specs + Rojo + luau-lsp, live pipeline test on Xvfb, **live pipeline test with real GDI capture on a `windows-latest` desktop** (F-0034, TR-0009) |
| Not verified | Roblox Studio and published servers (KI-0002): real RemoteEvent throughput, `RequestAsync` timeouts/body limits on live servers, client EditableImage memory budget, SurfaceGui rendering, Creator Dashboard settings, tunnel hop; the owner's own PC (multi-monitor/DPI/HDR); the Tk sharing window (never run with a display) |
| Blockers | None for the agent. Owner actions: review + merge PR #1 (T-0019), run the acceptance test INSTALL D/E (T-0018), read the Roblox Community Standards (T-0016) |
| Performance (MEASURED, sandbox) | balanced 480×270 RGB565 ≤ 4 fps: static 0 B/s, text scroll ~62 KB/s raw → paced to ~3 fps, window drag ~2 KB/s; full-screen video ≪ 1 fps at 48 KB/s (by design). Start → TV 1.0 s, change → TV 0.2 s, stop → TV off 0.2 s (emulated Roblox) |
| Exact next action | Owner: merge PR #1, then INSTALL.md parts A–E on the real PC + Studio + a private published server; paste results (TV text, `RlpsServer` attributes `Status`/`LastError`, perceived latency) into a new `TEST_RESULTS.md` row. Agent (next session): act on those results; optional T-0017 |
