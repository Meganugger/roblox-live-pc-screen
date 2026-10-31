# CHANGELOG.md

## Unreleased

- 2026-10-31 (28th session, PR #1) — **Live pipeline test** (`tests/e2e/`): real capture → frame service → the real
  Roblox scripts under an engine emulation, 21 checks, also on a real Windows desktop in CI. **Instant start** (`idle`
  polls), **stream pacing** (`MaxBytesPerSecond`), client checks zstd content size first, safe `RlpsFace` lookup, frame
  service ignores pollers that hang up. **Windows scripts** (`scripts/windows/`), `--token-only`. **Docs**: protocol,
  install, troubleshooting, security map, measured performance, improved prompt. **CI** workflow.
- 2026-10-24 — Repository created; persistent project-memory system and full specification added.
