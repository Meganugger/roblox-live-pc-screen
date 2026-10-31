# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-31, end of the 29th session (Notion custom agent through the Claude harness)._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private).
- **Newest work**: `main` (PR #1 merged, D-0010). First calls: `list_pull_requests` (an open PR is newer than `main`),
  `list_commits` on `main`. New work: a new `claude/*` branch + draft PR; CI failures are posted on the PR as comments
  by the workflow (`get_comments`).
- **What exists**: complete pipeline at maximum quality (stream v2: `ARCHITECTURE.md`, `docs/PROTOCOL.md`, D-0007,
  D-0008; per-viewer flow control `RlpsFanout`, D-0009); research of every public project found (`docs/research/EXISTING_PROJECTS.md`); install / troubleshooting /
  security / performance docs; Windows scripts; CI (ruff, pytest, Luau specs + luau-analyze, Rojo + luau-lsp, live test on
  Linux and Windows); explainer `docs/explainers/PR-1.md`; docs index `docs/README.md`.
- **Verified**: Python 85/85, Luau 6,588/0, Rojo + luau-lsp OK, live pipeline 25/25 in the sandbox (TR-0011, TR-0012).
  Unverified: real Roblox and the owner's PC (KI-0002, KI-0007).
- **Failed approaches (do not repeat)**: holding every poll while stopped (15 s stop delay); "no news" status with the
  newest seq (made relays skip deltas); `#t` on a queue with leading nils (dropped parts); scroll detection against
  the lossy client picture with exact matching (never matched) or against the previous capture (sub-pixel drift);
  lowering only the byte rate for CPU-bound clients (needs the fps cap); detecting slow viewers by time-based lag from
  a global forward log (sync retries reset the window, bytes of a viewer that acked nothing were invisible → D-0009);
  `key=1` for keyframes wanted by viewers (replays old frames to everyone → `fresh=1`); reading CI logs via
  `api.github.com` (401/403); Roblox help center from the sandbox (403).

## Reproduce the baseline (≈ 5 minutes)

```bash
pip install -r desktop/requirements.txt pytest ruff python-xlib  # + Xvfb, Luau CLI 0.744, Lune 0.10.4
ruff check .                                                      # lint (ruff.toml)
(cd desktop && python3 -m pytest -q)                              # 85 passed
python3 roblox/tests/run_luau_tests.py --analyze                  # TOTAL passed=6588 failed=0
scripts/check_roblox.sh                                           # Rojo build + luau-lsp OK -> build/RlpsDemo.rbxlx
python3 tests/e2e/run_e2e.py                                      # 25/25, ~2.5 min
DISPLAY=:N python3 scripts/bench.py --frames 12                   # codec + capture numbers (needs an X display)
```

Release ZIP: `git archive --format=zip --prefix=rlps/ -o dist/rlps-src.zip HEAD`, then add `build/RlpsDemo.rbxlx`.

## Exact next task

**T-0018 — owner acceptance test** (needs Windows + Roblox Studio + the owner's account; the agent cannot do it).
Dependencies: none (PR #1 merged, T-0019). Procedure: `docs/deployment/INSTALL.md` parts A–E. Completion criteria: in a
published private server the TV shows the real desktop, follows window moves, scrolling and a video, sharpens when
still, and shows "Screen sharing is off" after Stop. Record TR-0014: Windows version, monitor size/scaling, profile,
tunnel type, `RlpsServer` `RateBps` / `FpsCap` / `LagMs` / `MaxLagMs` / `LaggingViewers` / `BodyMode` / `LastError`,
client `DecodeMsPerFrame`,
the sharing window's `encode … ms`, and screenshots.

**Then (agent)**: tune `StartBytesPerSecond`, `ClientDecodeBudgetMs`, profile defaults from TR-0012; if `BodyMode` is
base64 on live servers, drop the probe; if clients decode slowly, consider a lower default profile for weak PCs.
Optional: T-0017 (tunnel URL as a secret).
