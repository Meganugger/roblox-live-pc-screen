# SESSION_HANDOFF.md — Resume from a completely clean conversation

_Last updated: 2026-10-31, end of the 28th session (Notion custom agent through the Claude harness)._

- **Repository**: https://github.com/Meganugger/roblox-live-pc-screen (private).
- **Where the newest work is**: branch `claude/rlps-session-28-finish`, draft **PR #1** → `main`. `main` (`e44fa8a`)
  does **not** contain it until the owner merges. First calls: `list_pull_requests`, `list_commits` on the branch,
  `pull_request_read get_check_runs` and `get_comments` for PR #1 (CI failures are posted there as comments).
- **Architecture**: `ARCHITECTURE.md` (D-0002, D-0006). Wire format: `docs/PROTOCOL.md`.
- **Done**: full pipeline implemented and tested up to verification level L3 (`docs/IMPROVED_PROMPT.md` ladder):
  Python 66/66, Luau 5,664/0, Rojo + luau-lsp OK, live pipeline test 21/21 locally, CI green on Linux and the live
  pipeline passing with real Windows capture (F-0034). Docs for install/troubleshooting/security/performance done;
  Windows scripts done; release ZIP built by the session (`dist/` is git-ignored; rebuild with the commands below).
- **Failed approaches this session (do not repeat)**: holding *every* poll while sharing is off (delayed stop news by
  15 s); reading CI logs through `api.github.com` with the git credential (401 — it is not a REST token); fetching the
  Roblox help center (403, F-0035).
- **Recently changed files**: `desktop/rlps/{server,app}.py`, `roblox/src/server/{RlpsServer.server,RlpsRelayCore}.luau`,
  `roblox/src/client/RlpsClient.client.luau`, `default.project.json`, `tests/e2e/*`, `scripts/{bench.py,windows/*}`,
  `.github/workflows/ci.yml`, all state docs, `docs/{PROTOCOL,IMPROVED_PROMPT}.md`, `docs/deployment/*`, `docs/testing/*`.

## Reproduce the baseline (≈ 3 minutes)

```bash
pip install -r desktop/requirements.txt pytest python-xlib       # + Xvfb, Luau CLI 0.744, Lune 0.10.4
(cd desktop && python3 -m pytest -q)                              # 66 passed
python3 roblox/tests/run_luau_tests.py --analyze                  # TOTAL passed=5664 failed=0
scripts/check_roblox.sh                                           # Rojo build + luau-lsp OK -> build/RlpsDemo.rbxlx
python3 tests/e2e/run_e2e.py                                      # 21/21, ~60 s
```

Release ZIP: `git archive --format=zip --prefix=rlps/ -o dist/rlps-src.zip HEAD`, then add `build/RlpsDemo.rbxlx`.

## Exact next task

**T-0018 — owner acceptance test (cannot be done by the agent: needs Windows + Roblox Studio + the owner's account).**
Dependencies: PR #1 merged (T-0019). Procedure: `docs/deployment/INSTALL.md` parts A–E. Completion criteria: in a
published private server the TV shows the owner's real desktop, follows a window move, and shows "Screen sharing is
off" after Stop. Record in `TEST_RESULTS.md` as TR-0011: date, PC (Windows version, monitor resolution/scaling),
profile, tunnel type, observed latencies, `RlpsServer` attributes (`Status`, `LastError`, `ForwardedBytes`), screenshots.

**If the owner reports a problem**, the next agent session: reproduce it in `tests/e2e/` where possible (add a
scenario), fix, rerun all four commands above, push to a `claude/*` branch, update PR, update this file.

**Optional agent work while waiting**: T-0017 (tunnel URL stored as a secret, F-0036 — needs a live check first),
deferred research T-0005/T-0006/T-0007 (non-blocking, D-0003).
