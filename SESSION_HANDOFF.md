# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-25 ~11:31 UTC, 15th session start. Read `WORK_LOG.md` (last rows) and `list_commits` first: later
commits may already contain the work listed under "Exact next task"._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private) · **Branch**: `main`.
- **Baseline verified by the 15th session**: `3f8ce595b98095beac122464917d7e7648636c74` ("test(roblox): Luau decoder cross-checked …").
- **Architecture**: D-0002 / `ARCHITECTURE.md` (capture app → authenticated delta frame service over an HTTPS tunnel →
  Roblox server long-poll → reliable `RemoteEvent` buffers → client zstd decode → `EditableImage` on a TV `SurfaceGui`).
- **Done (code + sandbox tests)**: Python codec (`desktop/rlps/protocol.py`, `codec.py`), frame service (`server.py`),
  capture (`capture.py`), sharing app (`app.py`), Luau protocol + decoder (`roblox/src/shared/`, harness
  `roblox/tests/run_luau_tests.py`) — `TEST_RESULTS.md` TR-0001…TR-0004.
- **Not done**: Roblox server poller, client renderer, TV model (T-0012), `docs/PROTOCOL.md`, tunnel/deployment
  guide (T-0014), CI (T-0013). Real Windows capture and every Roblox runtime behaviour are unverified (KI-0001/KI-0002).

## How to recover a working copy (no git credentials in the agent sandbox)

1. `list_commits` on `main` → head SHA. 2. `get_file_contents` for each file you need (directory listings give blob SHAs).
3. `save_tool_result_to_file` for each result, then write `resource.text` to `/data/roblox-live-pc-screen/<path>` (path =
   end of `resource.uri` after `/contents/`); `git init`; compare `git hash-object` with the listing SHAs
   (`scripts/agent/verify_remote.py`). Internet works (pip, curl, public GitHub releases); the private repo cannot be cloned.
4. Checkpoint: `scripts/agent/make_push_payload.py` → `run_mcp_tool_from_file` with GitHub `push_files`; verify with
   `list_commits` + `get_file_contents` listings (blob SHAs must MATCH). Push within ~8 minutes of starting and after every
   coherent unit (KI-0004: four sessions lost unpushed work).

## Exact next task

T-0012 Roblox side (the shared decoder is DONE): `roblox/src/server` poller (`HttpService:RequestAsync` long-poll with a
`Secret` Bearer token, one poll loop per server, reliable `RemoteEvent` fan-out of container buffers, late-joiner
keyframe), `roblox/src/client` renderer (`RlpsDecoder` → `EditableImage` on a TV `SurfaceGui`, CONNECTING/LIVE/STOPPED/
ERROR states) + TV model builder; extend the standalone-Luau harness with Roblox API stubs.
