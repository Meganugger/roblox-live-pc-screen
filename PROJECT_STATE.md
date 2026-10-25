# PROJECT_STATE.md — Canonical project status

_Last updated: 2026-10-25 ~11:00 UTC (13th session, start). Replaces stale 9th-session text that the 12th session had
corrected locally but never pushed (KI-0004)._

| Field | Value |
| --- | --- |
| Objective | Show the owner's real Windows desktop on a physical screen in a published Roblox experience (`PROJECT_SPEC.md`) |
| Repository | https://github.com/Meganugger/roblox-live-pc-screen (private, verified) · branch `main` (only branch) |
| Latest verified remote commit | `8435dd932a78a475a0623e051edc7332f6e860b0` — "feat(desktop): sharing app …" (10:45:29Z), verified by the 13th session (`list_branches`/`list_commits` head; `desktop/rlps` + `desktop/tests` listings contain `app.py`, `test_app.py`). Newer commits carry this file — always run `list_commits` first |
| Architecture | D-0002 (`ARCHITECTURE.md`): Windows capture app + authenticated on-demand delta frame service (HTTPS tunnel) → Roblox server long-poll (`HttpService:RequestAsync`) → reliable `RemoteEvent` buffer fan-out → client zstd decode (`EncodingService`) → `EditableImage` on a client-owned `SurfaceGui` adorned to a TV part |
| Implemented (code + local tests, sandbox) | `desktop/rlps/protocol.py` + `codec.py` (RLPS v1 container/part format, RGB565/RGB888 tiles, zstd parts, deltas, reference decoder; TR-0001); `server.py` frame service (Bearer auth, rate limits, long-poll ≤ 25 s, STOPPED/UNCHANGED/KEYFRAME/DELTA; TR-0002); `capture.py` (mss) + `app.py` (profiles, capture loop, start/stop controller, token config, Tk sharing indicator, console; TR-0003: 63/63 by the 12th session) |
| Not implemented | Roblox side (T-0012: server poller, client decoder/renderer, TV model, status states) and the Luau decoder half of T-0009; `docs/PROTOCOL.md` (referenced by `protocol.py`, never pushed); deployment/tunnel guide (T-0014); CI (T-0013) |
| Unverified | Real Windows capture (KI-0001); everything on Roblox (KI-0002): binary/base64 body limits of `RequestAsync`, reliable RemoteEvent size ceiling, `EncodingService` zstd on clients, EditableImage memory budget |
| Blockers | No Windows and no Roblox Studio/runtime in the agent sandbox (KI-0001, KI-0002); no CI-inspection tool (KI-0003) |
| Exact next action | T-0009/T-0012: write `roblox/src/shared/RlpsProtocol.luau` + `RlpsDecoder.luau` (mirror of `codec.py` checks), test them with a standalone Luau runtime against Python-encoded vectors, then the server poller, client renderer and TV model |
