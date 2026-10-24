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
