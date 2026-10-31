# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-31, end of the 29th session (Notion custom agent through the Claude harness)._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private).
- **Newest work**: `main` (PRs #1–#4 merged by the agent at the owner's request, D-0010). First calls:
  `list_pull_requests` (an open PR is newer than `main`), `list_commits` on `main`. New work: a new `claude/*` branch +
  PR; CI failures are posted on the PR as comments by the workflow (`get_comments`).
- **What exists**: complete pipeline at maximum quality (stream v2: `ARCHITECTURE.md`, `docs/PROTOCOL.md`, D-0007,
  D-0008; per-viewer flow control `RlpsFanout`, D-0009); client redraw economy, viewer modes, window / tab sharing
  (D-0011); in-game moderation (moderator kill switch, per-player hide), image-API probe, Sharp (D-0012); research of
  every public project found (`docs/research/EXISTING_PROJECTS.md`) and of the forums (`docs/research/FORUM_FINDINGS.md`);
  install / troubleshooting / security / performance docs; Windows scripts; CI (ruff, pytest, Luau specs +
  luau-analyze, Rojo + luau-lsp, live test on Linux and Windows); explainers `docs/explainers/PR-1.md`, `PR-3.md`,
  `PR-4.md`; docs index `docs/README.md`.
- **Verified**: Python 93 (+2 Windows-only), Luau 6,661/0, Rojo + luau-lsp OK, live pipeline 35/35 in the sandbox
  (TR-0011…TR-0016). Unverified: real Roblox and the owner's PC (KI-0002, KI-0007).
- **Failed approaches (do not repeat)**: holding every poll while stopped (15 s stop delay); "no news" status with the
  newest seq (made relays skip deltas); `#t` on a queue with leading nils (dropped parts); scroll detection against
  the lossy client picture with exact matching (never matched) or against the previous capture (sub-pixel drift);
  lowering only the byte rate for CPU-bound clients (needs the fps cap); detecting slow viewers by time-based lag from
  a global forward log (sync retries reset the window, bytes of a viewer that acked nothing were invisible → D-0009);
  `key=1` for keyframes wanted by viewers (replays old frames to everyone → `fresh=1`); resuming a hidden screen
  straight into an idle poll (kept "hidden by a moderator" for up to 15 s → status `connecting` first); reading CI logs via
  `api.github.com` (401/403); Roblox help center from the sandbox (403).

## Reproduce the baseline (≈ 5 minutes)

```bash
pip install -r desktop/requirements.txt pytest ruff python-xlib  # + Xvfb, Luau CLI 0.744, Lune 0.10.4
ruff check .                                                      # lint (ruff.toml)
(cd desktop && python3 -m pytest -q)                              # 93 passed, 2 skipped (Windows-only)
python3 roblox/tests/run_luau_tests.py --analyze                  # TOTAL passed=6661 failed=0
scripts/check_roblox.sh                                           # Rojo build + luau-lsp OK -> build/RlpsDemo.rbxlx
python3 tests/e2e/run_e2e.py                                      # 35/35, ~5 min
DISPLAY=:N python3 scripts/bench.py --frames 12                   # codec + capture numbers (needs an X display)
```

Release ZIP: `git archive --format=zip --prefix=rlps/ -o dist/rlps-src.zip HEAD`, then add `build/RlpsDemo.rbxlx`.

## Exact next task

**T-0018 — owner acceptance test** (needs Windows + Roblox Studio + the owner's account; the agent cannot do it).
Dependencies: none (PRs #1–#4 merged). Before publishing: INSTALL C.1 (ID verification) and C.1b (Content Labels
questionnaire, `ModeratorUserIds`). Procedure: `docs/deployment/INSTALL.md` parts A–E. Completion criteria: in a
published private server the TV shows the real desktop, follows window moves, scrolling and a video, sharpens when
still, shows "Screen sharing is off" after Stop, and a moderator can hide and show it in game. Record TR-0017: Windows version, monitor size/scaling, profile,
tunnel type, `RlpsServer` `RateBps` / `FpsCap` / `LagMs` / `MaxLagMs` / `LaggingViewers` / `BodyMode` / `LastError`,
client `DecodeMsPerFrame` / `LastRedrawPixels`, the sharing window's `encode … ms`, and screenshots.

**Then (agent)**: tune `StartBytesPerSecond`, `ClientDecodeBudgetMs`, profile defaults from TR-0017; if `BodyMode` is
base64 on live servers, drop the probe; if clients decode slowly, consider a lower default profile for weak PCs.
Optional: T-0017 (tunnel URL as a secret). T-0028 (live audio) only after the owner decides the policy question
(FORUM_FINDINGS §1.8).
