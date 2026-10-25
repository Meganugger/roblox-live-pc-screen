# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-25 ~16:07 UTC (19th session, start). The 18th session pushed `1e44429` (start record), `8a1f74e`
(WIP `RlpsClientCore`) and `158e2e8` (`RlpsClientCore` spec) but did not update the state files afterwards; any work it
did after 13:49 UTC is lost (KI-0004 pattern). The 19th session started in a fresh sandbox (`/data` empty), so nothing
unpushed was recoverable. Always run `list_commits` first: newer commits may exist._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (`PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) · branch `main` (only branch) |
| Latest verified remote commit | `158e2e85f1c4dba298843c26f9383da1423bce6b` — "test(roblox): RlpsClientCore spec (154 checks …)" (13:49:12Z), verified by the 19th session (`list_branches` head; `list_commits`; directory listings of `roblox/src/shared`, `roblox/tests`, `desktop/rlps`, `scripts/agent`). Newer commits carry this file — always run `list_commits` first |
| Architecture | D-0002 (`ARCHITECTURE.md`): Windows capture app + authenticated on-demand delta frame service (HTTPS tunnel) → Roblox server long-poll (`HttpService:RequestAsync`) → reliable `RemoteEvent` buffer fan-out → client zstd decode (`EncodingService`) → `EditableImage` on a client-owned `SurfaceGui` adorned to a TV part |
| Implemented (code + local tests, sandbox) | `desktop/rlps/protocol.py` + `codec.py` (RLPS v1 container/part format, RGB565/RGB888 tiles, zstd parts, deltas, reference decoder; TR-0001); `server.py` frame service (Bearer auth, rate limits, long-poll ≤ 25 s, STOPPED/UNCHANGED/KEYFRAME/DELTA; TR-0002); `capture.py` (mss) + `app.py` (profiles, capture loop, start/stop controller, token config, Tk sharing indicator, console; TR-0003); `roblox/src/shared/RlpsProtocol.luau` + `RlpsDecoder.luau` (Luau mirror of the codec, dirty-rect `Bounds`) + `RlpsBase64.luau` (strict base64 fallback) + `RlpsClientCore.luau` (client frame assembler: delta chain, desync → resync, dirty rect, reset, copyRect); harness `roblox/tests/run_luau_tests.py` runs every `*.spec.luau` (`158e2e8` message reports 5,565/5,565 + `luau-analyze` OK — to be re-run by the 19th session) |
| Not implemented | Roblox server poller + `RemoteEvent` fan-out, client renderer (`EditableImage` binding, CONNECTING/LIVE/STOPPED/ERROR states), TV model builder (T-0012); `docs/PROTOCOL.md`; deployment/tunnel guide (T-0014); CI (T-0013) |
| Unverified | Real Windows capture (KI-0001); everything on Roblox (KI-0002): binary/base64 body limits of `RequestAsync`, reliable RemoteEvent size ceiling, `EncodingService` zstd on clients, EditableImage memory budget |
| Blockers | No Windows and no Roblox Studio/runtime in the agent sandbox (KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Exact next action | T-0012 (IN_PROGRESS, 19th session): `roblox/src/server` poller (`RequestAsync` long-poll with a `Secret` token, reliable `RemoteEvent` fan-out, single capture source, late-joiner keyframe), `roblox/src/client` renderer (`RlpsClientCore` → `EditableImage` on a TV `SurfaceGui`; status states), TV model builder; standalone-Luau harness tests with Roblox API stubs |
