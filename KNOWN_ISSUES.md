# KNOWN_ISSUES.md — Persistent blockers and open problems

| ID | Symptom | Reproduction | Severity | Root cause | Related | Attempts | Status | Next diagnostic action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KI-0001 | No Windows machine available to the agent | Agent sandbox is Linux x86_64 | High (blocks Windows-specific capture verification) | Environment | `desktop/` | — | OPEN | Use a cross-platform capture library that also runs on Linux for partial verification; owner runs the Windows acceptance test |
| KI-0002 | No Roblox Studio / Roblox runtime available to the agent | Linux sandbox; Studio is Windows/macOS only | High (blocks Studio + published tests) | Environment | `roblox/` | — | OPEN | Use Luau CLI / analysis tools and an emulation harness for logic; owner runs Studio and published tests |
| KI-0003 | CI results cannot be inspected | GitHub MCP exposes no Actions/workflow-run tool; repo is private | Medium | Integration limits | `.github/workflows/` | — | OPEN | Run the same checks locally in the sandbox and record results; owner can view Actions tab |
