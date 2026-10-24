# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-24 18:33 UTC, checkpoint R1c — research R1 in progress._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private) · **Branch**: `main`
- **Latest verified commit**: `3287d4ed5aa86f9170b15f6aab5355b9ec455711` ("Research R1b …") — newer commits may exist; always run `list_commits` first and read the
  last rows of `WORK_LOG.md` (authoritative history).
- **Objective**: real Windows desktop → physical screen in a published Roblox experience (`PROJECT_SPEC.md`).
- **Selected architecture**: **Not chosen yet** (research pending; options A–F in `PROJECT_SPEC.md` §5). Constraints already fixed by official docs: client-side EditableImage reconstruction (F-0005); server-side HTTP polling of a public HTTPS endpoint (F-0007…F-0010); reliable RemoteEvent + buffer fan-out, zstd decompressed natively by `EncodingService` (F-0013…F-0016).
- **Completed work**: Tool inspection; repo created and verified; spec preserved (structured + verbatim); memory documents; R1a (EditableImage group, F-0001…F-0006); R1b (HttpService / WebStreamClient / secrets, F-0007…F-0012); R1c (remotes / buffer / EncodingService / network budget, F-0013…F-0017)
- **Recently changed files**: `FINDINGS_LOG.md`, `SOURCE_REGISTER.md`, `docs/research/ROBLOX_API_FACTS.md`, `PROJECT_STATE.md`, `SESSION_HANDOFF.md`, `TASKS.md`, `WORK_LOG.md`.
- **New research findings**: F-0013…F-0017 (reliable RemoteEvent semantics; UnreliableRemoteEvent 1,000 B cap; buffer; **EncodingService Zstd/Base64**; 50 KB/s planning target).
- **Important decisions**: D-0001 (private repo, `main` only, push via MCP `push_files`). No architecture decision yet.
- **Tests actually executed**: No tests yet (research phase). **Unverified**: Binary-safe HTTP response bodies and maximum response size (F-0007); practical RemoteEvent size/throughput ceiling (F-0013, F-0017); EncodingService availability/speed on clients (F-0016); everything at runtime (no Studio/published test yet).
- **Known issues**: KI-0001 (no Windows), KI-0002 (no Roblox runtime), KI-0003 (no CI inspection tool).
- **Failed approaches**: none.
- **Files to inspect first**: `PROJECT_STATE.md`, `TASKS.md`, `docs/research/ROBLOX_API_FACTS.md`, `GITHUB_WORKFLOW.md`, last rows of `WORK_LOG.md`.

## How to recover a working copy (no git credentials in the agent sandbox)

1. `list_commits` on `main` → note the head SHA. 2. `get_file_contents` for each file you will edit (directory listings
give blob SHAs). 3. Save each tool result to a file (`save_tool_result_to_file`) and write the decoded `resource.text` to
`/data/roblox-live-pc-screen/<path>`; `git init` there and check `git hash-object <file>` equals the remote blob SHA (all
must MATCH before editing). Public sources can be fetched with `curl`/`git clone` (internet works; private repo cannot).
4. Checkpoint with `scripts/agent/make_push_payload.py` + MCP `push_files` (see `GITHUB_WORKFLOW.md`), then verify with
`list_commits`, `get_commit` and `get_file_contents` + `scripts/agent/verify_remote.py`.

## Exact next task

**T-0003 R1d — VideoFrame / VideoPlayer / SurfaceGui / CaptureService / VideoCaptureService** (see `TASKS.md`).
- Dependencies: R1a–R1c verified on GitHub.
- Method: `curl -sS https://raw.githubusercontent.com/Roblox/creator-docs/4e795e65a41fd48624fd85442292a81baa6bb3f5/content/en-us/<path>`
  for `reference/engine/classes/{VideoFrame,VideoPlayer,SurfaceGui,CaptureService,VideoCaptureService}.yaml` (+ video guide);
  parse YAML with PyYAML; record facts as F-0018+ with sources S-0018+.
- Questions to answer: Q1, Q2 (desktop capture from Roblox), Q13 (Studio vs published), Q14 (what works live).
- Completion criteria: all 14 rows of `docs/research/ROBLOX_API_FACTS.md` answered or marked unknown; T-0003 DONE; checkpoint verified.
- Then T-0004 (ScreenBlox), T-0005 (Icy-Monster), T-0006 (RSSP), T-0007 (others), T-0008 (decision).
