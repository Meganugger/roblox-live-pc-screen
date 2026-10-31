# roblox-live-pc-screen

> **MANDATORY: READ THE PROJECT STATE AND SESSION HANDOFF BEFORE DOING ANY WORK.**
>
> **The previous conversation is NOT required and must NOT be assumed to be available.** Everything needed to understand,
> reproduce and continue this project is in this repository. GitHub — not chat memory — is the durable record.

## What this project is

A real, working system that captures the owner's **actual Windows PC desktop** and displays it on a **physical screen
inside a published Roblox experience**. See [`PROJECT_SPEC.md`](PROJECT_SPEC.md) (structured requirements) and
[`docs/ORIGINAL_SPEC_VERBATIM.md`](docs/ORIGINAL_SPEC_VERBATIM.md) (verbatim original assignment).

## Start-of-session procedure for every future AI session (Claude, Notion AI or any other agent)

1. **Locate the authoritative repository**: `Meganugger/roblox-live-pc-screen` (private) via the connected GitHub
   integration. Verify it is accessible (e.g. GitHub MCP `get_file_contents` on `/`). If forks/copies exist, the
   authoritative one is the one named in `PROJECT_STATE.md` with the newest verified commit on `main`.
2. Read [`PROJECT_SPEC.md`](PROJECT_SPEC.md).
3. Read [`PROJECT_STATE.md`](PROJECT_STATE.md).
4. Read [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md).
5. Read [`TASKS.md`](TASKS.md).
6. Inspect relevant entries in [`FINDINGS_LOG.md`](FINDINGS_LOG.md), [`SOURCE_REGISTER.md`](SOURCE_REGISTER.md),
   [`DECISIONS.md`](DECISIONS.md), [`TEST_RESULTS.md`](TEST_RESULTS.md), [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md),
   [`WORK_LOG.md`](WORK_LOG.md).
7. Verify the actual remote branch, commit history (`list_commits`) and repository tree (`get_file_contents` per dir).
8. Compare the checkpoint records against the real source code (documentation alone is not proof that a feature works).
9. Resume the **precise next unfinished task** named in `SESSION_HANDOFF.md`.
10. Preserve new progress with the mandatory checkpoint procedure in [`GITHUB_WORKFLOW.md`](GITHUB_WORKFLOW.md):
    **INVESTIGATE → DOCUMENT → UPDATE STATE → COMMIT → SYNCHRONIZE → VERIFY REMOTELY → CONTINUE.**

**Open pull requests first:** since the 28th session work is delivered on `claude/*` branches with a draft PR (D-0004).
If a PR is open (`list_pull_requests`), its branch is newer than `main` — continue on that branch.

Do not ask the owner what happened in a previous chat if it can be recovered from this repository. Do not restart from
scratch. Do not repeat completed research unnecessarily. Do not assume an old test result is still valid after the code
changed (see "stale" markers in `TEST_RESULTS.md`).

## Quick start (owner)

1. Windows: `scripts\windows\setup.bat`, `show-token.bat`, `start-sharing.bat`, `start-tunnel.bat`.
2. Roblox Studio: open `RlpsDemo.rbxlx` (release ZIP or CI artifact), set `FrameServiceUrl`, add the `rlps_token`
   secret, enable Allow HTTP Requests + Allow Mesh / Image APIs, Play, press **Start sharing** on the PC.
3. Full guide: [`docs/deployment/INSTALL.md`](docs/deployment/INSTALL.md); problems:
   [`docs/deployment/TROUBLESHOOTING.md`](docs/deployment/TROUBLESHOOTING.md).

## Repository map

| Path | Purpose |
| --- | --- |
| `PROJECT_SPEC.md` | Complete requirements (structured) |
| `PROJECT_STATE.md` | Canonical current status, latest verified commit, exact next action |
| `SESSION_HANDOFF.md` | How a clean session continues, step by step |
| `FINDINGS_LOG.md` / `SOURCE_REGISTER.md` | Research findings (F-xxxx) and sources (S-xxxx) |
| `DECISIONS.md` | Engineering decision records (D-xxxx) |
| `TASKS.md` / `WORK_LOG.md` | Task tracking and chronological history |
| `TEST_RESULTS.md` / `KNOWN_ISSUES.md` | Genuine test evidence and open issues |
| `ARCHITECTURE.md` / `SECURITY.md` / `PERFORMANCE.md` | Design, privacy/security model, performance data |
| `GITHUB_WORKFLOW.md` | GitHub capabilities actually verified in the agent environment + checkpoint procedure |
| `CHANGELOG.md` | User-visible changes |
| `docs/` | Research reports, architecture notes, implementation notes, testing and deployment guides |
| `desktop/` | Windows app: capture, codec, frame service (`python -m rlps.app`) |
| `roblox/` | Roblox scripts (`src/`), TV model (`models/`), Luau specs (`tests/`) — built by `default.project.json` (Rojo) |
| `tests/e2e/` | Live pipeline test with the Roblox engine emulation |
| `scripts/` | `windows/*.bat`, `check_roblox.sh`, `bench.py`, `agent/` (MCP push helpers from earlier sessions) |
| `docs/PROTOCOL.md`, `docs/IMPROVED_PROMPT.md` | Wire format; the rewritten project prompt for new sessions |
| `.github/workflows/ci.yml` | CI: Python (Linux+Windows), Luau specs, Rojo + luau-lsp, live pipeline test (Linux+Windows) |
