# GITHUB_WORKFLOW.md — Verified GitHub capabilities and checkpoint procedure

Only capabilities that were **actually exercised** in an agent environment are marked ✅. Update this file when a
capability is verified, fails, or changes.

## Write path (D-0001, revised by D-0004)

Work goes to a `claude/*` branch with a **draft pull request** into `main`; the owner merges. `main` is never pushed
directly. If a PR is open (`list_pull_requests`), its branch is newer than `main`: continue on it.

## Environment A — repository mounted as a git clone (28th session onwards) ✅ primary

- Clone at `/workspace/roblox-live-pc-screen` with a credential helper: `git fetch` / `git push` work, but pushes are
  accepted **only for `claude/*` branches**.
- The credential is not a GitHub REST token (`api.github.com` answers 401/403): use the GitHub MCP tools for API work —
  ✅ `create_pull_request`, `update_pull_request`, `pull_request_read` (`get_check_runs` for CI status, `get_comments`).
- CI logs cannot be read directly; the workflow posts each failure's output as a PR comment (KNOWN_ISSUES KI-0003).
  Read the newest with `get_comments` and pagination (e.g. `perPage: 1`, last page).

**Checkpoint procedure**

1. `git add -A && git commit` (co-author trailer for the owner's e-mail when known).
2. `git push` (retry only on network errors).
3. Verify: `git ls-remote origin <branch>` must equal `git rev-parse HEAD`.
4. CI: `pull_request_read get_check_runs` until all jobs complete; failures → `get_comments`.
5. Record the verified SHA in `WORK_LOG.md` (a file cannot contain its own commit SHA, so `PROJECT_STATE.md` names the
   latest *previously* verified commit).

## Environment B — no clone, GitHub MCP only (sessions 1–27) — fallback

The sandbox had no git credentials; every remote write went through MCP tools. The helpers in `scripts/agent/` exist
for this case:

1. `python3 scripts/agent/make_push_payload.py -m "<message>" --branch claude/<name> -o /tmp/payload.json <paths…>`
   (≤ 1 MiB per payload; split otherwise; text files only).
2. MCP `push_files` with `arguments_file_path=/tmp/payload.json` (✅ verified: 25 files in one commit, `67a6e4a`).
3. Verify: `list_commits`, `get_commit` (`detail: stats`), and `get_file_contents` on the changed directories; save
   the listing and run `python3 scripts/agent/verify_remote.py <listing.json>` (compares remote blob SHAs with local
   `git hash-object`).
4. After any write error, **read back before retrying** (a `create_repository` call once reported a transport error
   although the repository had been created).

To recover a working copy without a clone, read files with `get_file_contents` directory by directory — only what the
next task needs — and never push an old local copy over newer remote content (compare blob SHAs first).

## Capability matrix (GitHub MCP)

| Need | Tool | Status |
| --- | --- | --- |
| Identify account | `get_me` | ✅ login `Meganugger` (display name "Sivalmagic") |
| Repositories | `search_repositories`, `get_file_contents` on `/` | ✅ |
| Branches / history | `list_branches`, `list_commits`, `get_commit` | ✅ |
| Multi-file commit | `push_files` | ✅ (environment B) |
| Pull requests | `create_pull_request`, `update_pull_request`, `pull_request_read` | ✅ |
| CI status | `pull_request_read get_check_runs` | ✅ job status; ❌ logs (workaround: failure comments) |
| Recursive tree | — | ❌ not exposed: walk directories with `get_file_contents` |
| Binary files | `push_files` / `create_or_update_file` | ⚠️ text only; in environment A binary files go through git normally |
