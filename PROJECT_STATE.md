# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-25 ~13:01 UTC (17th session, start). The 16th session (12:37 UTC) pushed only its start record
`300c4de` and none of its T-0012 work (KI-0004 recurrence); the 17th session started in a fresh sandbox (`/data` empty),
so nothing unpushed was recoverable. Always run `list_commits` first: newer commits may exist._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (`PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) · branch `main` (only branch) |
| Latest verified remote commit | `300c4de8dde7fd17e8d408e8b641e51e36217f38` — "chore(state): 16th-session start …" (12:37:45Z), verified by the 17th session (`list_branches` head; `list_commits`; blob SHAs of the state files match). Code baseline is unchanged since `3f8ce59` (T-0009 DONE). Newer commits carry this file — always run `list_commits` first |
| Architecture | D-0002 (`ARCHITECTURE.md`): Windows capture app + authenticated on-demand delta frame service (HTTPS tunnel) → Roblox server long-poll (`HttpService:RequestAsync`) → reliable `RemoteEvent` buffer fan-out → client zstd decode (`EncodingService`) → `EditableImage` on a client-owned `SurfaceGui` adorned to a TV part |
| Implemented (code + local tests, sandbox) | `desktop/rlps/protocol.py` + `codec.py` (RLPS v1 container/part format, RGB565/RGB888 tiles, zstd parts, deltas, reference decoder; TR-0001); `server.py` frame service (Bearer auth, rate limits, long-poll ≤ 25 s, STOPPED/UNCHANGED/KEYFRAME/DELTA; TR-0002); `capture.py` (mss) + `app.py` (profiles, capture loop, start/stop controller, token config, Tk sharing indicator, console; TR-0003: 63/63 by the 12th session); `roblox/src/shared/RlpsProtocol.luau` + `RlpsDecoder.luau` (check-for-check Luau mirror of the codec; TR-0004: 5,344/5,344 Python-generated vectors, `luau-analyze` OK) |
| Not implemented | Roblox server poller, client renderer, TV model, status states (T-0012); `docs/PROTOCOL.md` (referenced by `protocol.py`, never pushed); deployment/tunnel guide (T-0014); CI (T-0013) |
| Unverified | Real Windows capture (KI-0001); everything on Roblox (KI-0002): binary/base64 body limits of `RequestAsync`, reliable RemoteEvent size ceiling, `EncodingService` zstd on clients, EditableImage memory budget |
| Blockers | No Windows and no Roblox Studio/runtime in the agent sandbox (KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Exact next action | T-0012 (IN_PROGRESS, restarted by the 17th session; the 16th session's work was lost): `roblox/src/server` poller (`RequestAsync` long-poll with a `Secret` token, reliable `RemoteEvent` fan-out, single capture source), `roblox/src/client` renderer (`RlpsDecoder` → `EditableImage` on a TV `SurfaceGui`; CONNECTING/LIVE/STOPPED/ERROR states), TV model builder; standalone-Luau harness tests |
