# CHANGELOG.md

## Unreleased

- 2026-10-31 (29th session, PR #1) — **Stream v2, maximum quality**: hybrid per-tile codec (lossless / bit-exact DCT /
  scroll COPY tiles, lossless refinement when still), 1024×576 @ 30 fps default, several frames per HTTP response with
  playout, adaptive byte rate and frame-rate cap from client acknowledgements, lagging viewers paused and re-synced,
  binary bodies after a probe, OpenCV resize + optional DXGI capture, integer scaling with letterbox. Public projects
  surveyed at source level (Icy-Monster, RSSP, MahanBig, luavid and 6 more).

- 2026-10-31 (28th session, PR #1) — **Live pipeline test** (`tests/e2e/`): real capture → frame service → the real
  Roblox scripts under an engine emulation, 21 checks, also on a real Windows desktop in CI. **Instant start** (`idle`
  polls), **stream pacing** (`MaxBytesPerSecond`), client checks zstd content size first, safe `RlpsFace` lookup, frame
  service ignores pollers that hang up. **Windows scripts** (`scripts/windows/`), `--token-only`. **Docs**: protocol,
  install, troubleshooting, security map, measured performance, improved prompt. **CI** workflow.
- 2026-10-24 — Repository created; persistent project-memory system and full specification added.
