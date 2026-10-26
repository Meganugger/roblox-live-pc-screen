# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-25 ~11:31 UTC, 15th session start. Read `WORK_LOG.md` (last rows) and `list_commits` first: later
commits may already contain the work listed under "Exact next task"._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private) · **Branch**: `main`.
- **Baseline verified by the 25th session**: `e34d392fa6190b87d493e1e92252672f60cf2044` (24th-session start record on top of `7775c3e`).
- **Architecture**: D-0002 / `ARCHITECTURE.md` (capture app → authenticated delta frame service over an HTTPS tunnel →
  Roblox server long-poll → reliable `RemoteEvent` buffers → client zstd decode → `EditableImage` on a TV `SurfaceGui`).
- **Done (code + sandbox tests)**: Python codec, frame service, capture, sharing app (`desktop/rlps/`, TR-0001…TR-0003);
  Luau protocol/decoder/base64/client core + server relay core (`roblox/src/shared`, `roblox/src/server/RlpsRelayCore.luau`,
  spec harness TR-0004/TR-0005); server script `RlpsServer.server.luau`, client script `RlpsClient.client.luau`, TV model +
  Rojo project (Rojo build + strict Roblox-API analysis TR-0006).
- **Not done**: end-to-end integration harness (in progress), `docs/PROTOCOL.md`, tunnel/deployment guide (T-0014), CI
  (T-0013), release ZIP. Real Windows capture and every Roblox runtime behaviour are unverified (KI-0001/KI-0002).

## How to recover a working copy (no git credentials in the agent sandbox)

1. `list_commits` on `main` → head SHA. 2. `get_file_contents` for each file you need (directory listings give blob SHAs).
3. Faster (23rd–25th sessions): per-directory listings with `fields: [type,path,size,download_url]`, `save_tool_result_to_file`,
   then download every tokenized `download_url` with curl/urllib **immediately** (tokens expire within minutes); `git init`. Internet works (pip, curl, public GitHub releases); the private repo cannot be cloned.
4. Checkpoint: `scripts/agent/make_push_payload.py` → `run_mcp_tool_from_file` with GitHub `push_files`; verify with
   `list_commits` + `get_file_contents` listings (blob SHAs must MATCH). Push within ~8 minutes of starting and after every
   coherent unit (KI-0004: four sessions lost unpushed work).

## Exact next task

T-0012/T-0013 integration harness: run the unmodified `RlpsServer.server.luau` and two `RlpsClient.client.luau` instances
under Lune with a Roblox API emulation against the real `desktop/rlps/server.py` fed by the real capture loop; assert the
reconstructed EditableImage pixels, live updates and the STOPPED state. Then `docs/PROTOCOL.md`, deployment guide, ZIP.
