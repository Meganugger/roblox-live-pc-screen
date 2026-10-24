# GITHUB_WORKFLOW.md — Verified GitHub capabilities and checkpoint procedure

Only capabilities that were **actually exercised** in the agent environment are marked ✅. Everything else is marked with
its real status. Update this file when a capability is verified, fails, or changes.

## Environment (verified 2026-10-24)

- Agent: Notion AI agent with a connected **GitHub MCP server** (tool names below are the exact names exposed).
- Authenticated GitHub user (`get_me`): **`Meganugger`** (display name "Sivalmagic").
- Sandbox: Linux x86_64 with internet access, `git` CLI present but **no GitHub credentials** in the sandbox. Do not ask
  the owner for a token; all remote writes go through the GitHub MCP tools.
- The local working copy (`/data/roblox-live-pc-screen` in the agent sandbox) is **temporary**. Never treat it as durable.

## Capability matrix

| Need | Tool | Status |
| --- | --- | --- |
| Identify account | `get_me` | ✅ verified (returned login `Meganugger`) |
| List/search repos | `search_repositories` (`user:Meganugger`) | ✅ verified (13 repos incl. private before creation) |
| Check repo existence | `get_file_contents` on `/` | ✅ verified (404 before creation, listing after) |
| Create repo | `create_repository` (`private: true`, `autoInit: true`) | ✅ repo created — **but the tool call itself returned a transport error** ("upstream connect error … remote connection failure"). The repo nevertheless existed on read-back. Lesson: after any write error, **read back before retrying** to avoid duplicates. |
| Repo metadata/visibility | `search_repositories` with `minimal_output:false` | ✅ verified: `private: true`, `visibility: private`, default branch `main`, permissions admin/push |
| Branches | `list_branches` | ✅ verified (`main` @ `ef29fbf…` initial commit) |
| Commit history | `list_commits` (`fields` filter supported) | ✅ verified |
| Multi-file commit | `push_files` (via `arguments_file_path` JSON built by `scripts/agent/make_push_payload.py`) | ✅ verified: checkpoint 1 pushed 25 files (107 KB payload) in one commit `67a6e4a`; returns the new ref SHA |
| Single-file create/update | `create_or_update_file` (requires blob `sha` for updates) | available, not yet exercised |
| Commit details / changed files | `get_commit` (`detail: stats`) | ✅ verified (file list + additions for `67a6e4a`) |
| Read file / directory | `get_file_contents` (returns blob `sha`; `fields` filter works for dirs) | ✅ verified for `/`, `docs`, `scripts/agent`; `verify_remote.py` reported MATCH for all 20 files listed |
| Create branch | `create_branch` | available, not exercised (work happens on `main`; no PR review loop needed) |
| Delete file | `delete_file` | available, not exercised |
| Code search (public GitHub) | `search_code` | available (used for research) |
| Secret scan of content | `run_secret_scanning` | available (use before pushing config-like files) |
| **Workflow runs / CI logs** | — | ❌ **no GitHub Actions tool is exposed** by this MCP server. CI results cannot be inspected through the integration; the repo is private so public web pages are not readable either. Record CI as "not inspectable from agent environment" unless a future environment exposes it. |
| Recursive tree API | — | ❌ not exposed; walk directories with `get_file_contents` per directory. |
| Binary file upload | `push_files` / `create_or_update_file` carry text | ⚠️ text only — keep committed artefacts text-based (e.g. `.rbxlx`/`.rbxmx` XML instead of binary `.rbxl`). |

## Checkpoint procedure (use for every substantial source / milestone)

1. Edit files locally in the working copy; `git add -A && git commit` locally (local history is only a convenience).
2. Build the payload: `python3 scripts/agent/make_push_payload.py -m "<message>" -o /tmp/payload.json <changed paths…>`
   (or `--all`). Payload must be ≤ 1 MiB; split otherwise.
3. Call GitHub MCP `push_files` with `arguments_file_path=/tmp/payload.json`.
4. **Verify remotely**: `list_commits` (new head SHA + message), `get_commit` (`detail: stats`, file list), and
   `get_file_contents` on the changed directories; save the listing and run
   `python3 scripts/agent/verify_remote.py <listing.json>` to compare remote blob SHAs with local `git hash-object`.
5. Record the verified SHA in `WORK_LOG.md` (and in `PROJECT_STATE.md` at the next checkpoint — a file cannot contain
   its own commit SHA, so `PROJECT_STATE.md` always names the latest *previously verified* commit plus the expected
   message of the commit that contains it).
6. If a write call errors: do **not** blindly retry — read back first (`list_commits`), then retry only what is missing.

## Recovering a working copy in a new session

No credentials ⇒ no `git clone`. Recreate files by reading them with `get_file_contents` (directory by directory). Only
fetch what the next task needs. Never push an old local copy over newer remote content: compare blob SHAs first.
