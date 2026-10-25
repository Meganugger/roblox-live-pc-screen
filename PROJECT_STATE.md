# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-25 ~16:57 UTC (20th session, start). The 19th session pushed `0ccbd08` (start record), `b1b95fa`
(WIP `RlpsRelayCore`) and `2608039` (`RlpsRelayCore` spec) but did not update the state files afterwards; any later work
is lost (KI-0004 pattern). The 20th session started in a fresh sandbox (`/data` empty): nothing unpushed was recoverable.
Always run `list_commits` first: newer commits may exist._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (`PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) · branch `main` (only branch) |
| Latest verified remote commit | `260803926d080550407b8e51eb0f28eae087d800` — "test(roblox): RlpsRelayCore spec (95 checks …)" (16:12:07Z), verified by the 20th session (`list_branches` head = `list_commits` head; listings of `roblox/src/server`, `roblox/src/shared`, `roblox/tests`, `desktop/rlps`, `scripts/agent`; 22 fetched blobs hash-identical). Newer commits carry this file — always run `list_commits` first |
| Architecture | D-0002 (`ARCHITECTURE.md`): Windows capture app + authenticated on-demand delta frame service (HTTPS tunnel) → Roblox server long-poll (`HttpService:RequestAsync`) → reliable `RemoteEvent` buffer fan-out → client zstd decode (`EncodingService`) → `EditableImage` on a client-owned `SurfaceGui` adorned to a TV part |
| Implemented (code + local tests, sandbox) | `desktop/rlps/protocol.py` + `codec.py` (RLPS v1 container/part format, RGB565/RGB888 tiles, zstd parts, deltas, reference decoder; TR-0001); `server.py` frame service (Bearer auth, rate limits, long-poll ≤ 25 s, STOPPED/UNCHANGED/KEYFRAME/DELTA; TR-0002); `capture.py` (mss) + `app.py` (profiles, capture loop, start/stop controller, token config, Tk sharing indicator, console; TR-0003); `roblox/src/shared/RlpsProtocol.luau` + `RlpsDecoder.luau` (Luau mirror of the codec, dirty-rect `Bounds`) + `RlpsBase64.luau` (strict base64 fallback) + `RlpsClientCore.luau` (client frame assembler: delta chain, desync → resync, dirty rect, reset, copyRect); `roblox/src/server/RlpsRelayCore.luau` (server relay core: chain-validated fan-out, poll cursor, late-joiner history, status, failure threshold; spec 95 checks); harness `roblox/tests/run_luau_tests.py` runs every `*.spec.luau` (`2608039` message reports 5,660/5,660 + `luau-analyze` OK — re-run by the 20th session, see `TEST_RESULTS.md`) |
| Not implemented | `RlpsServer.server.luau` (HttpService poller + `RemoteEvent` fan-out around `RlpsRelayCore`), client renderer (`EditableImage` binding, CONNECTING/LIVE/STOPPED/ERROR states), TV model builder (T-0012); `docs/PROTOCOL.md`; deployment/tunnel guide (T-0014); CI (T-0013) |
| Unverified | Real Windows capture (KI-0001); everything on Roblox (KI-0002): binary/base64 body limits of `RequestAsync`, reliable RemoteEvent size ceiling, `EncodingService` zstd on clients, EditableImage memory budget |
| Blockers | No Windows and no Roblox Studio/runtime in the agent sandbox (KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Exact next action | T-0012 (IN_PROGRESS, 20th session): `roblox/src/server/RlpsServer.server.luau` (poll loop + fan-out + late joiners + desync keyframe requests), `roblox/src/client/RlpsClient.client.luau` (`RlpsClientCore` → `EditableImage`, status screens), TV model builder, Rojo project; integration harness running the real scripts against the real Python frame service with Roblox API stubs (Lune) |
