# DECISIONS.md — Engineering decision records

## D-0001 — Repository visibility, branch model and write path (2026-10-24)

- **Problem**: where and how to persist the project.
- **Options**: public vs private repo; trunk (`main`) vs feature branches + PRs; git CLI vs GitHub MCP writes.
- **Evidence**: owner asked for private unless justified; sandbox has no git credentials; MCP exposes
  `create_repository`, `push_files`, `create_or_update_file`, `create_branch`, PR tools (see `GITHUB_WORKFLOW.md`).
- **Selected**: private repo `Meganugger/roblox-live-pc-screen`; commit directly to `main` in coherent checkpoints;
  write via MCP `push_files` built from local files by `scripts/agent/make_push_payload.py`.
- **Rationale**: single developer agent, no reviewers; PR overhead adds no safety here. Private protects any
  machine-specific notes.
- **Rejected**: public repo (no requirement for it); git CLI push (no credentials, must not request tokens).
- **Consequences**: history is linear; each checkpoint is one commit; binary artefacts avoided.
- **Revisit if**: collaborators join (then use PRs), or the repo must be public for tooling (e.g. a hosted relay
  deployment that pulls from GitHub).

## D-0002 — Architecture: desktop frame service + server long-poll + client EditableImage (2026-10-24, 10th session)

- **Problem**: choose the end-to-end pipeline (T-0008) so implementation can start.
- **Evidence**: official docs (T-0003, `docs/research/ROBLOX_API_FACTS.md`): no desktop capture in Roblox (F-0020);
  only server-side `HttpService:RequestAsync` works in published games, 500 req/min/server, no WebSocket/SSE live
  (F-0007…F-0010); secrets server-only in URL/headers (F-0011); reliable `RemoteEvent` carries `buffer`, Unreliable drops
  > 1,000 B (F-0013…F-0015); native Zstd/Base64 in `EncodingService` (F-0016); `EditableImage` RGBA8, ≤ 1024², does not
  replicate (F-0001…F-0005); `VideoFrame` asset-only (F-0018). ScreenBlox (T-0004) proves the topology but with JSON
  per-pixel payloads and one replicated Frame per pixel (F-0024, F-0027).
- **Selected**:
  1. **Desktop app** (Python ≥ 3.10, Windows): `mss` capture of a chosen monitor → resize (numpy) → quantize (RGB565
     default, RGBA8888 high quality) → change detection → ring of recent frames. Explicit Start/Stop sharing; visible
     indicator; nothing is captured while stopped.
  2. **Frame service** in the same process (stdlib `ThreadingHTTPServer`, bound to `127.0.0.1`), published over HTTPS by
     a tunnel (e.g. Cloudflare Tunnel) or a reverse proxy. `GET /v1/frames?after=<seq>&session=<id>&key=<0|1>&wait=<ms>`
     returns, **computed on demand**, the changed 16×16 tiles between frame `after` and the latest frame (keyframe when
     `after` is unknown or `key=1`), split into independently decodable zstd parts, wrapped in a small binary container,
     base64 text body (binary-safe bodies unverified, F-0007). Bearer-token auth (constant-time), rate limits, bounded
     long-polls, no other routes.
  3. **Roblox server**: one poller per game server (≤ 400 req/min, long-poll, bandwidth pacing), token from the
     experience secret, validates container headers/sizes, forwards compressed parts unchanged via one reliable
     `RemoteEvent` (`buffer`); keyframes for joining/resyncing clients; status broadcast.
  4. **Roblox client**: `EncodingService` zstd decompress (bounded by `GetDecompressedBufferSize`), validates the part,
     writes tiles into an RGBA buffer, one `EditableImage:WritePixelsBuffer` per rendered frame, shown via
     `ImageLabel.ImageContent` on a client-created `SurfaceGui` adorned to the TV screen part; status/stopped/error
     screens.
- **Rationale**: the only topology the official APIs allow in published games; on-demand deltas against the poller's
  last frame give natural backpressure and zero traffic for static screens; tiles are independent, so parts need no
  reassembly; the game server never touches pixels.
- **Rejected**: Roblox-only capture (F-0020); WebSocket/SSE (Studio-only, F-0010); `UnreliableRemoteEvent` (1,000 B cap,
  F-0014); `VideoFrame`/`VideoPlayer` (F-0018, F-0019); server-side EditableImage (no replication, F-0005); per-pixel
  Instances / JSON number arrays (F-0027); a mandatory separate cloud relay (extra infrastructure; can be added later by
  running the frame service on a host and letting the desktop app push to it).
- **Consequences**: owner needs a public HTTPS URL (tunnel) + Allow HTTP Requests + Enable Mesh / Image APIs + a secret.
  Practical frame rate is bounded by ~50 KB/s per client (F-0017) and ≤ 400 polls/min. Wire format: `docs/PROTOCOL.md`.
- **Revisit if**: binary response bodies prove safe (drop base64), `WebStreamClient` becomes available live (T-0015), or
  reliable-remote throughput tests (T-0013) contradict the budget.

## D-0003 — Pivot from surveys to implementation (2026-10-24, 10th session)

- **Problem**: nine sessions produced research only; the owner's directive is to build the software now.
- **Selected**: T-0008 closed by D-0002. T-0005 (Icy-Monster), T-0006 (RSSP) and T-0007 (other projects) are **deferred**:
  they no longer block any implementation decision and are only revisited if a specific implementation question needs
  them. T-0016 (content policy) stays required before publishing guidance (T-0014).
- **Consequences**: next tasks are T-0009 (codec + protocol), T-0010 (capture app), T-0011 (frame service), T-0012
  (Roblox scripts + TV), T-0013 (tests).
