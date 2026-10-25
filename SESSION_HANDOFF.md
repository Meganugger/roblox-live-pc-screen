# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-25 ~11:00 UTC, 13th session start. Read `WORK_LOG.md` (last rows) and `list_commits` first: later
commits may already contain the work listed under "Exact next task"._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private) · **Branch**: `main`.
- **Baseline verified by the 13th session**: `8435dd932a78a475a0623e051edc7332f6e860b0` ("feat(desktop): sharing app …").
- **Architecture**: D-0002 / `ARCHITECTURE.md` (capture app → authenticated delta frame service over an HTTPS tunnel →
  Roblox server long-poll → reliable `RemoteEvent` buffers → client zstd decode → `EditableImage` on a TV `SurfaceGui`).
- **Done (code + sandbox tests)**: Python codec (`desktop/rlps/protocol.py`, `codec.py`), frame service (`server.py`),
  capture (`capture.py`), sharing app (`app.py`) — `TEST_RESULTS.md` TR-0001…TR-0003.
- **Not done**: Roblox side (`roblox/`, T-0012) incl. the Luau decoder (T-0009), `docs/PROTOCOL.md`, tunnel/deployment
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

T-0009/T-0012 Roblox side: `roblox/src/shared/RlpsProtocol.luau`, `roblox/src/shared/RlpsDecoder.luau` (check-for-check
mirror of `codec.py` `parse_container`/`apply_part`), standalone-Luau tests against Python-encoded vectors, then
`roblox/src/server` poller (RequestAsync long-poll, Secret token, RemoteEvent fan-out) and `roblox/src/client` renderer
(EditableImage on a TV SurfaceGui, LIVE/STOPPED/ERROR states) + TV model.
