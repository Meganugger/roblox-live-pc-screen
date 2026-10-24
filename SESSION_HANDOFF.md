# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-24 20:10 UTC, 8th session — `2ec64d0` verified; T-0004 part 1 checkpointed (ScreenBlox located, Python side read, F-0023…F-0026)._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private) · **Branch**: `main`
- **Latest verified commit**: `2ec64d0b8ac12f0c2409e3138b829c8a48c6b897` ("Session 7 start …", verified by the 8th session).
  This file is carried by the newer "Research R2a …" commit (or later ones): always run `list_commits` first and read the
  last rows of `WORK_LOG.md`.
- **Objective**: real Windows desktop → physical screen in a published Roblox experience (`PROJECT_SPEC.md`).
- **Selected architecture**: not formally chosen (T-0008). Forced by official docs: native Windows capture app (F-0020) →
  public HTTPS endpoint polled by the Roblox server with `RequestAsync` (F-0007…F-0010) → reliable `RemoteEvent` + `buffer`
  fan-out, zstd via `EncodingService` (F-0013…F-0016) → client `EditableImage` on a client-owned `SurfaceGui` (F-0005,
  F-0021). Rejected: Roblox-only capture (F-0020), WebSocket/SSE (F-0010), UnreliableRemoteEvent (F-0014), VideoFrame /
  VideoPlayer (F-0018, F-0019). ScreenBlox (F-0024) confirms the community uses the same topology (desktop HTTP server +
  tunnel + HttpService polling) with JSON-per-pixel payloads and no security.
- **Completed work**: tool inspection; repo + memory system; T-0003 R1a–R1d (F-0001…F-0022, S-0001…S-0027); T-0004 part 1:
  ScreenBlox = GitHub `Reb0rnEnder/ScreenBlox` (GPL-3.0, head `b873f78`) = the 2024 DevForum "ScreenShare | Free Game
  Source" resource; Python side read (F-0023…F-0026, S-0028…S-0030, `docs/research/EXISTING_PROJECTS.md`).
- **Recently changed files**: `FINDINGS_LOG.md`, `SOURCE_REGISTER.md`, `docs/research/EXISTING_PROJECTS.md` (new),
  `TASKS.md`, `KNOWN_ISSUES.md`, `WORK_LOG.md`, `PROJECT_STATE.md`, `SESSION_HANDOFF.md`.
- **Decisions**: D-0001 (private repo, `main` only, push via MCP `push_files`). No architecture decision yet.
- **Tests actually executed**: none (research phase; ScreenBlox code was read, not run). **Unverified**: binary-safe HTTP
  response bodies / max response size (F-0007); practical RemoteEvent size ceiling (F-0013, F-0017); EncodingService on
  clients (F-0016); all runtime behaviour.
- **Known issues**: KI-0001 (no Windows), KI-0002 (no Roblox runtime), KI-0003 (no CI inspection tool), KI-0004 (work lost
  when a chat ends — recurred in the 6th **and** 7th sessions: no start-only commits, read only the files you will edit,
  push the first findings within ~10 minutes, then after every source / sub-step).

## How to recover a working copy (no git credentials in the agent sandbox)

1. `list_commits` on `main` → note the head SHA. 2. `get_file_contents` for each file you will edit (directory listings
give blob SHAs). 3. Save each tool result to a file (`save_tool_result_to_file`) and write the decoded `resource.text` to
`/data/roblox-live-pc-screen/<path>` (the `resource.uri` ends with `/contents/<path>`); `git init` there and run
`scripts/agent/verify_remote.py` on saved directory listings (all must MATCH before editing). Public sources can be
fetched with `curl`/`git clone` (internet works; the private repo cannot be cloned).
4. Checkpoint with `scripts/agent/make_push_payload.py` + `run_mcp_tool_from_file` → GitHub `push_files` (see
`GITHUB_WORKFLOW.md`), then verify with `list_commits`, `get_commit` and `get_file_contents` + `verify_remote.py`.

## Exact next task

**T-0004 part 2 — ScreenBlox Roblox side + DevForum thread** (`TASKS.md`).
- Method: `git clone https://github.com/Reb0rnEnder/ScreenBlox /data/cache/ScreenBlox`; parse the binary place file
  `v4.7.rbxl` with a small Python script (Roblox binary format: `<roblox!` header, then chunks with a 16-byte header
  (name, compressed length, uncompressed length, reserved) whose payload is LZ4 (or zstd) compressed; `INST` chunks name
  the classes, `PROP` chunks named `Source` hold script text; `lz4` is preinstalled) → read every Script / LocalScript /
  ModuleScript. Then load `https://devforum.roblox.com/t/2823814.json` (or `web_load_page` on the topic URL).
- Record: who polls (server/client), URL configuration, poll rate, JSON decoding, how pixels are drawn (Frames / parts /
  EditableImage), resolution, replication to other players (RemoteEvents?), reported fps / lag / tunnel problems,
  successors. F-0027+, S-0031+, update `docs/research/EXISTING_PROJECTS.md` §1.
- Completion criteria: Roblox scripts + thread read; findings + sources recorded; checkpoint verified; T-0004 DONE. Then
  T-0005 (Icy-Monster/Screen-Sharing-in-Roblox), T-0006 (RSSP by ssavnayt), T-0007 (Reddit "AnyDesk in Roblox", archived
  Screen-Sharing-in-Roblox forks, S-0030 thread, successors), T-0008 (architecture decision → `DECISIONS.md`,
  `ARCHITECTURE.md`), then T-0009 (wire protocol + codec with tests).
