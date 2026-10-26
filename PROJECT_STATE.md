# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-25 ~19:10 UTC (21st session, start). The 20th session pushed only its start record `661cf06`;
everything it did afterwards was lost (KI-0004 again: it pushed too late). The 21st session started in a fresh sandbox
(`/data` empty, nothing unpushed recoverable) and verified `661cf06` as baseline (`list_branches` head = `list_commits` head,
11 fetched blobs hash-identical). Rule from the owner (2026-10-25): push every file as soon as it exists — WIP is fine.
Always run `list_commits` first: newer commits may exist._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (`PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) · branch `main` (only branch) |
| Latest verified remote commit | `e34d392fa6190b87d493e1e92252672f60cf2044` — "chore(log): 24th-session start …" (22:10:28Z), on top of `7775c3e` ("fix(roblox): TV model JSON now builds with Rojo 7.7.1 …", TR-0006). Newer commits carry this file — always run `list_commits` first |
| Architecture | D-0002 (`ARCHITECTURE.md`): Windows capture app + authenticated on-demand delta frame service (HTTPS tunnel) → Roblox server long-poll (`HttpService:RequestAsync`) → reliable `RemoteEvent` buffer fan-out → client zstd decode (`EncodingService`) → `EditableImage` on a client-owned `SurfaceGui` adorned to a TV part |
| Implemented (code + local tests, sandbox) | `desktop/rlps/protocol.py` + `codec.py` (RLPS v1, RGB565/RGB888 tiles, zstd parts, deltas, reference decoder; TR-0001); `server.py` frame service (Bearer auth, rate limits, long-poll ≤ 25 s, STOPPED/UNCHANGED/KEYFRAME/DELTA; TR-0002); `capture.py` (mss) + `app.py` (profiles, capture loop, start/stop controller, token config, Tk sharing indicator, console; TR-0003); `roblox/src/shared/` `RlpsProtocol`/`RlpsDecoder`/`RlpsBase64`/`RlpsClientCore` (TR-0004, spec harness); `roblox/src/server/RlpsRelayCore.luau` (spec 95 checks) + `RlpsServer.server.luau` (HttpService long-poll with Secret Bearer, RemoteEvent fan-out, sync for late joiners, viewer allowlist, backoff); `roblox/src/client/RlpsClient.client.luau` (EditableImage renderer, CONNECTING/LIVE/STOPPED/ERROR screens, sync/desync); `roblox/models/RlpsTV.model.json` + `default.project.json` (Rojo build OK) and `scripts/check_roblox.sh` (Rojo build + luau-lsp strict analysis with Roblox definitions: TR-0006 PASS) |
| Not implemented | Integration harness that runs the real server/client scripts against the real Python frame service (T-0012/T-0013, in progress in the 25th session); `docs/PROTOCOL.md`; deployment/tunnel guide (T-0014); CI (T-0013); release ZIP |
| Unverified | Real Windows capture (KI-0001); everything on Roblox (KI-0002): binary/base64 body limits of `RequestAsync`, reliable RemoteEvent size ceiling, `EncodingService` zstd on clients, EditableImage memory budget |
| Blockers | No Windows and no Roblox Studio/runtime in the agent sandbox (KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Exact next action | T-0012/T-0013: Lune-based integration harness (`roblox/tests/integration/`): Roblox API emulation (instances, attributes, RemoteEvent server↔clients, HttpService via real HTTP, EncodingService base64+zstd, EditableImage) running the unmodified `RlpsServer.server.luau` + 2× `RlpsClient.client.luau` against the real `desktop/rlps/server.py`, fed by the real capture loop (Xvfb + mss when available); assert reconstructed pixels, updates, stop → STOPPED |
