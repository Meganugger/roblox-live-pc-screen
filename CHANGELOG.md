# CHANGELOG.md

## Unreleased

- 2026-10-31 (29th session, PR #5) — **Latency first** (owner: "it lags way more and has a lot more delay"). A new
  glass-to-glass test (E2E-31…34) found the cause — since PR #3 a client could stop decoding half-way into a frame and
  then drew nothing, so the TV fell behind — and the delays built into the stream: a 150 ms batching wait, up to 1 s of
  playout pacing, and a rate control that let Roblox's send queue fill. Now: frames are drawn the moment they are
  complete, polls answer at once, pacing is capped at 100 ms, the rate follows each player's measured *queueing
  delay*, the decoder is 1.8× faster (bit-identical) and large moving areas are sent at half resolution (DCT2, a
  quarter of the decode work). Measured: single change 0.24 → 0.07 s (Studio-like), 0.35 → 0.20 s (online); video
  0.66–1.14 s → 0.42 s median, p90 0.96–1.90 s → 0.59 s (online). Places with the old saved tuning switch to the new
  defaults automatically.
- 2026-10-31 (29th session, PR #4) — **Forum research** (`docs/research/FORUM_FINDINGS.md`: Reddit via an archive API,
  DevForum, GitHub, official announcements) and what came of it: **moderator kill switch** (`ModeratorUserIds`,
  `Hidden`: hide the screen for everyone from inside the game, logged), **per-player Hide (H)** (nothing sent to that
  player), a clear message when the experience lacks **Allow Mesh / Image APIs** (needs a 13+ ID-verified owner),
  full-screen **Sharp** pixels, and Roblox policy guidance (Content Labels, private audiences, personal information).
- 2026-10-31 (29th session, PR #3) — **Roblox client draws only what changed** (dirty rectangles instead of a bounding
  box, once per game frame, nothing while no TV is in view, far TVs ≤ 10 Hz; pooled buffers; `--!native --!optimize 2`).
  **Viewer modes**: full screen (Fit/Fill), cinema (camera framing the TV, bars, background blur, movement held), mini
  player; buttons near the TV and keys F / C / M; owner setting `ViewerModes`. **Share one app window or one browser
  tab** (`--window`, `--tab`, `--list-windows`, *Change what is shared…* in the sharing window): captured from the
  window itself; a tab pauses while another tab is shown.
- 2026-10-31 (29th session) — **Secret-domain errors explained on the TV**: when Roblox refuses the token secret ("This
  secret cannot be used for a specified domain"), the TV and `LastError` say which domain to enter (e.g.
  `*.trycloudflare.com`) and which host was refused; a failed `/v1/probe` no longer fixes base64 bodies for that URL.
  Live test E2E-22; install and troubleshooting steps clarified (host only, keep `*.`, restart the playtest).
- 2026-10-31 (29th session, PR #1) — **Repository clean-up**: dead code removed, lint (`ruff.toml`) and spec type-checks
  enforced in CI, `.gitignore` tidied, placeholder doc folders removed, docs index `docs/README.md`, explainer renamed
  `docs/explainers/PR-1.md`, `ARCHITECTURE.md` / `GITHUB_WORKFLOW.md` rewritten to describe the current system. The
  desktop status line now also counts frames skipped for the viewers' fps cap.
- 2026-10-31 (29th session, PR #1) — **Per-viewer flow control** (D-0009): clients acknowledge the bytes they
  processed; `RlpsFanout` keeps each viewer's backlog within about one second of its own delivery rate, holds a viewer
  whose window is full and then sends it exactly the frames it missed (or the next keyframe). The rate follows the
  median viewer, so a slow player gets a slideshow instead of degrading everyone's stream. Keyframes for viewers are
  requested with the new `fresh=1` poll flag (no more rewinding every TV to the ring's old keyframe). `LagDropSeconds`
  removed, `LagMs` added.
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
