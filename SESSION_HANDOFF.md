# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-24 20:26 UTC, 9th session — R2b `a00eee6` verified; T-0004 DONE (DevForum thread read, F-0029…F-0033)._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private) · **Branch**: `main`
- **Latest verified commit**: `a00eee67562e55c97176830d25f5be75370e2f13` ("Research R2b …", verified by the 9th session).
  This file is carried by the newer "Research R2c …" commit (or later ones): always run `list_commits` first and read the
  last rows of `WORK_LOG.md`.
- **Objective**: real Windows desktop → physical screen in a published Roblox experience (`PROJECT_SPEC.md`).
- **Selected architecture**: not formally chosen (T-0008). Forced by official docs: native Windows capture app (F-0020) →
  public HTTPS endpoint polled by the Roblox server with `RequestAsync` (F-0007…F-0010) → reliable `RemoteEvent` + `buffer`
  fan-out, zstd via `EncodingService` (F-0013…F-0016) → client `EditableImage` on a client-owned `SurfaceGui` (F-0005,
  F-0021). Rejected: Roblox-only capture (F-0020), WebSocket/SSE (F-0010), UnreliableRemoteEvent (F-0014), VideoFrame /
  VideoPlayer (F-0018, F-0019). ScreenBlox (F-0024, F-0027) uses the same topology (desktop HTTP server + tunnel +
  HttpService polling) with JSON-per-pixel payloads, one replicated Frame per pixel and no security.
- **Completed work**: tool inspection; repo + memory system; T-0003 R1a–R1d (F-0001…F-0022, S-0001…S-0027); **T-0004
  DONE**: ScreenBlox = GitHub `Reb0rnEnder/ScreenBlox` (GPL-3.0, head `b873f78`; a partial backup created after the
  original repo was lost in Aug 2024, F-0033) = the 2024 DevForum "ScreenShare | Free Game Source" resource. Python side
  (F-0023…F-0026), Roblox place `v4.7.rbxl` (F-0027/F-0028) and the full DevForum thread (33 posts; F-0029 no fps data
  anywhere; F-0030 "RemoteEvent limit 900 Bytes" claim contradicts the docs for reliable remotes; F-0031 playit.gg/ngrok
  tunnels + "works in Studio, server offline live"; F-0032 ToS remark → T-0016) read; notes in
  `docs/research/EXISTING_PROJECTS.md` §1 (8 lessons adopted).
- **Recently changed files**: `FINDINGS_LOG.md`, `SOURCE_REGISTER.md` (S-0028 → Read, S-0031 CanvasDraw discovered),
  `docs/research/EXISTING_PROJECTS.md`, `TASKS.md` (T-0004 DONE, T-0007 scope extended, T-0016 added), `WORK_LOG.md`,
  `PROJECT_STATE.md`, `SESSION_HANDOFF.md`.
- **Decisions**: D-0001 (private repo, `main` only, push via MCP `push_files`). No architecture decision yet.
- **Tests actually executed**: none (research phase; third-party code was read, not run). **Unverified**: binary-safe
  HTTP response bodies / max response size (F-0007); practical reliable-RemoteEvent size ceiling (F-0013, F-0017,
  F-0030); EncodingService on clients (F-0016); all runtime behaviour.
- **Known issues**: KI-0001 (no Windows), KI-0002 (no Roblox runtime), KI-0003 (no CI inspection tool), KI-0004 (work lost
  when a chat ends — no start-only commits, read only the files you will edit, push the first findings within ~10
  minutes, then after every source / sub-step; the 9th session pushed its first findings ~8 minutes after starting).

## How to recover a working copy (no git credentials in the agent sandbox)

1. `list_commits` on `main` → note the head SHA. 2. `get_file_contents` for each file you will edit (directory listings
give blob SHAs). 3. Save each tool result to a file (`save_tool_result_to_file`) and write the decoded `resource.text` to
`/data/roblox-live-pc-screen/<path>` (the `resource.uri` ends with `/contents/<path>`); `git init` there and run
`scripts/agent/verify_remote.py` on saved directory listings (all must MATCH before editing). Public sources can be
fetched with `curl`/`git clone` (internet works; the private repo cannot be cloned).
4. Checkpoint with `scripts/agent/make_push_payload.py` + `run_mcp_tool_from_file` → GitHub `push_files` (see
`GITHUB_WORKFLOW.md`), then verify with `list_commits`, `get_commit` and `get_file_contents` + `verify_remote.py`.

## Exact next task

**Superseded by the 10th session (2026-10-24 23:40 UTC)**: architecture selected (`DECISIONS.md` D-0002, `ARCHITECTURE.md`);
surveys T-0005…T-0007 deferred (D-0003). Next: **T-0009** wire protocol + codec (`desktop/rlps/`, `docs/PROTOCOL.md`,
tests), then T-0011 frame service, T-0010 capture app, T-0012 Roblox scripts + TV. Always check `list_commits` and the
last rows of `WORK_LOG.md` first: later commits of the 10th session may already contain this code.
