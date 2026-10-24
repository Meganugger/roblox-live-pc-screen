# MASTER PROJECT: BUILD A REAL, WORKING PC SCREEN-SHARING SYSTEM INSIDE ROBLOX

# PART I — CRITICAL EXECUTION OVERRIDE

## 1. YOUR FIRST JOB IS TO CREATE THE ACTUAL GITHUB REPOSITORY

You are operating as a principal Roblox engine engineer, senior Luau developer, Windows desktop-software engineer, Python engineer, networking architect, cybersecurity engineer, GitHub repository maintainer, performance engineer, technical researcher, and QA engineer.

Your mission is to research, architect, implement, test, debug, optimize, document, and package the strongest technically feasible system that displays my actual Windows PC screen on a physical television or monitor inside a Roblox experience.

However, before you begin the technical research or implementation, you must establish a permanent, remotely accessible GitHub project workspace.

**My connected GitHub account is a mandatory part of this assignment. You must actively use the actual GitHub integration available to you. Your job is to execute GitHub operations, not merely describe them or tell me how to do them myself.**

I have authorized the permissions available through my connected GitHub integration for this project. Use those permissions for the operations required to complete the assignment.

Do not claim to have unrestricted capabilities without checking what the integration actually exposes. At the same time, do not assume a capability is unavailable without inspecting the tools and supported operations.

### 1.1. Execute these actions FIRST, in this exact order

**ACTION 1 — Inspect your actual tools.**

Inspect the available tools and integration documentation to identify the actual operations supported for:

- Identifying my connected GitHub account.
- Listing accessible repositories.
- Reading repository metadata and files.
- Creating a repository.
- Creating and updating repository files.
- Creating commits.
- Creating branches.
- Reading commit history.
- Inspecting repository trees.
- Inspecting workflows and CI results.
- Verifying remotely stored files.

Use the actual available tool names, schemas, and parameters. Never invent a tool or claim an operation is supported without evidence.

**ACTION 2 — Create the dedicated GitHub repository.**

Create a repository named:

`roblox-live-pc-screen`

Prefer a private repository unless a demonstrable technical requirement justifies another visibility setting.

Before creating it, check whether the name already exists in the appropriate namespace.

If a repository with that name exists, inspect it. Reuse it only if it is genuinely the correct project repository. If it is unrelated, create an appropriately named alternative.

Do not modify unrelated repositories.

If the GitHub integration exposes repository creation, execute the operation immediately.

If it does not, investigate the other authorized methods genuinely available in the environment, such as authenticated GitHub CLI access or another supported GitHub interface.

Do not ask me to supply credentials already available through the connection. Never expose access tokens, passwords, private keys, or other authentication secrets.

**ACTION 3 — Verify that the repository exists remotely.**

Retrieve the repository from GitHub after creation.

Verify its actual name, owner or namespace, URL, visibility where available, and accessibility.

Confirm whether you can read its contents and create or update files using an authorized method.

Do not accept your intention to create the repository as proof that it exists.

Do not invent a URL, commit hash, branch, repository, or successful operation.

**ACTION 4 — Create the permanent project-memory files.**

Immediately create the required documentation described in Part II.

Do not begin the substantial Roblox research until the initial project specification, persistent-memory documents, and recovery instructions have been created and successfully saved to GitHub.

**ACTION 5 — Commit, synchronize, and verify.**

Commit the initial documentation using the available GitHub integration.

Verify that the resulting files and commit actually exist in the remote repository.

If a GitHub operation fails, inspect the error, attempt an appropriate safe recovery, and accurately document the result.

If every available authorized repository-creation method fails, state the precise blocker. Do not pretend the repository exists. Continue with safe local work only where appropriate, and keep repository creation as an explicit unresolved blocker.

**Do not answer with a plan instead of attempting these actions. Do not begin with a lengthy explanation of what you intend to do. Execute the available operations first.**

The first concrete deliverable is the actual GitHub repository containing the persistent project-memory system.

## 2. GITHUB IS THE PROJECT'S PERMANENT MEMORY AND SOURCE OF TRUTH

I may close this conversation, open an entirely new Claude chat, and expect the project to continue from exactly where it left off.

The new chat may have no access to:

- This conversation.
- Earlier Claude responses.
- Previous research notes.
- Previous reasoning.
- Earlier terminal output.
- The preceding session's temporary files.
- Any other context not explicitly preserved.

Therefore:

**Everything essential for reproducing, understanding, and continuing the project must be recoverable from the GitHub repository and the actual source files.**

Do not use conversation history as the only record of progress.

Do not rely on your own memory.

Do not assume future chats will inherit the current workspace.

Do not store important decisions exclusively in an assistant response.

GitHub must be used continuously, from the first research finding through the final implementation and maintenance work.

## 3. MANDATORY CHECKPOINTING AFTER EVERY MEANINGFUL STEP

You must record and preserve every material finding, important investigation result, implementation milestone, failed approach, test result, architectural decision, security consideration, dependency discovery, and relevant technical limitation.

**Whenever you discover something relevant, document it immediately and save it to GitHub before proceeding to the next substantial investigation.**

The required cycle is:

**INVESTIGATE → DOCUMENT → UPDATE PROJECT STATE → COMMIT → SYNCHRONIZE → VERIFY REMOTELY → CONTINUE.**

For each substantial research source:

1. Inspect the actual source.
2. Identify all relevant findings.
3. Record those findings and the supporting evidence.
4. Update the source register.
5. Update the architectural decision record if necessary.
6. Update relevant tasks and the project state.
7. Inspect the changed files.
8. Commit the coherent changes.
9. Synchronize the changes with GitHub.
10. Verify the remote files or commit.
11. Proceed to the next substantial source only after attempting this checkpoint.

For each meaningful implementation milestone:

1. Save the source code.
2. Save associated tests.
3. Record the files changed.
4. Record implementation decisions.
5. Record test results or explain why testing was impossible.
6. Update the outstanding task list.
7. Update the project-state and session-handoff documents.
8. Commit the changes.
9. Synchronize them with GitHub.
10. Verify the resulting remote state.

A single checkpoint may cover several tightly related findings or changes. Do not create pointless commits after every trivial edit, but never postpone completed research or important implementation work until the end of an entire phase.

If you finish inspecting a repository, its material discoveries must not remain only in the browser, terminal, or conversation.

If you discover that a proposed technique is impossible, document the evidence and the consequences.

If a source is inaccessible, record the attempted URL, the access failure, and the next investigative approach.

If an earlier conclusion turns out to be incorrect, update the records and explain why.

**Do not move on from a substantial source or milestone while its material results exist only in temporary working memory.**

For important reasoning, preserve concise engineering decision records containing the evidence, alternatives, conclusions, assumptions, uncertainties, and implications. Do not attempt to store a private internal reasoning transcript. Store the complete useful engineering record another session needs to reproduce the work.

## 4. VERIFY EVERY SAVE

These are different operations:

1. Writing a file locally.
2. Creating or updating a file through the GitHub integration.
3. Committing changes.
4. Synchronizing changes to the remote repository.
5. Reading the remote repository to confirm the expected state.

Do not treat them as interchangeable.

Always distinguish local progress from progress confirmed in GitHub.

If an operation fails:

- Inspect the actual error.
- Determine what was saved locally.
- Determine what was saved remotely.
- Preserve local work where possible.
- Retry through an appropriate authorized method.
- Check for conflicts or concurrent changes.
- Verify remote contents before claiming synchronization.
- Record the remaining problem.

Do not discard unsaved changes during conflict resolution.

If remote synchronization remains impossible, explain exactly what was saved locally, what is missing remotely, and how the next session should recover it.

Never claim that everything is safely stored in GitHub unless you have evidence.

---

# PART II — CREATE THE COMPLETE PERSISTENT-MEMORY SYSTEM

## 5. REQUIRED REPOSITORY STRUCTURE

After creating the repository, immediately create a meaningful initial documentation system.

Adapt the following structure to the actual implementation, but preserve the purpose of every required document.

```text
roblox-live-pc-screen/
│
├── README.md
├── PROJECT_SPEC.md
├── PROJECT_STATE.md
├── SESSION_HANDOFF.md
├── FINDINGS_LOG.md
├── SOURCE_REGISTER.md
├── DECISIONS.md
├── TASKS.md
├── WORK_LOG.md
├── TEST_RESULTS.md
├── KNOWN_ISSUES.md
├── ARCHITECTURE.md
├── SECURITY.md
├── PERFORMANCE.md
├── CHANGELOG.md
├── GITHUB_WORKFLOW.md
│
├── docs/
│   ├── research/
│   ├── architecture/
│   ├── implementation/
│   ├── testing/
│   └── deployment/
│
├── roblox/
│   └── ...
│
├── desktop/
│   └── ...
│
├── relay/
│   └── ...
│
├── tests/
│   └── ...
│
├── scripts/
│   └── ...
│
└── .github/
    └── workflows/
        └── ...
```

The source directories are examples, not a requirement to create unnecessary components.

The following documents are mandatory:

### 5.1. `PROJECT_SPEC.md` — The complete original specification

Preserve the full functional and technical requirements of this prompt so that a fresh Claude chat can understand the complete assignment without access to this conversation.

Include:

- The objective of displaying my actual Windows screen on a physical screen inside Roblox.
- The required end-to-end functionality.
- All research requirements.
- All named projects to investigate.
- Official Roblox API verification requirements.
- Architecture-comparison requirements.
- Desktop capture requirements.
- Encoding and transport requirements.
- Roblox server/client requirements.
- Rendering requirements.
- Performance requirements.
- Security and privacy requirements.
- Testing requirements.
- Publication and deployment requirements.
- Installation and troubleshooting requirements.
- GitHub workflow and persistence requirements.
- Required deliverables.
- Acceptance criteria.

Do not reduce the specification to a vague summary such as "build Roblox screen sharing."

Preserve enough detail that another session can execute the project correctly.

### 5.2. `README.md` — Instructions for every future session

At the very top, include:

**MANDATORY: READ THE PROJECT STATE AND SESSION HANDOFF BEFORE DOING ANY WORK.**

Tell future Claude sessions to:

1. Locate the authoritative repository.
2. Read `PROJECT_SPEC.md`.
3. Read `PROJECT_STATE.md`.
4. Read `SESSION_HANDOFF.md`.
5. Read `TASKS.md`.
6. Inspect relevant findings, sources, decisions, test records, and known issues.
7. Verify the actual remote branch, commit history, and repository tree.
8. Compare the checkpoint records against the real source code.
9. Resume the precise next unfinished task.
10. Preserve new progress through the mandatory GitHub checkpoint procedure.

Explicitly state that the previous conversation is not required and must not be assumed to be available.

### 5.3. `PROJECT_STATE.md` — Canonical project status

Keep this concise and current.

Include:

- Objective.
- Repository URL.
- Current branch.
- Latest verified remote commit.
- Current milestone.
- Chosen architecture.
- Implemented components.
- Completed work.
- In-progress work.
- Remaining work.
- Known blockers.
- Important verified facts.
- Important assumptions.
- Test status.
- Latest successful checkpoint.
- Whether local and remote states are synchronized.
- Exact next action.

Distinguish implemented features from proposed features.

Distinguish locally tested features from remotely committed code and production-verified functionality.

Update the project state after every substantial checkpoint.

### 5.4. `SESSION_HANDOFF.md` — Resume from a completely clean conversation

This file must tell a new Claude chat exactly how to continue.

Include:

- Repository URL.
- Branch.
- Latest verified commit.
- Project objective.
- Selected architecture.
- Completed work.
- Recently changed files.
- New research findings.
- Important decisions.
- Tests actually executed.
- Tests that remain unverified.
- Known issues.
- Failed approaches and why they failed.
- Current blockers.
- Files to inspect first.
- The exact next task.
- Its dependencies.
- Its completion criteria.
- The tests to run.
- The correct next checkpoint.

Never write vague instructions such as "continue development."

Give a concrete next action that can be executed without the previous conversation.

### 5.5. `FINDINGS_LOG.md` — Every material discovery

For each relevant finding, record:

- A unique finding ID such as `F-0001`.
- Discovery date and time when available.
- Research question.
- Search query or investigation approach.
- Source ID.
- Source URL.
- Specific files, pages, APIs, issues, or discussions inspected.
- What was actually examined.
- The finding.
- Supporting evidence.
- Source type.
- Confidence and limitations.
- Why the finding matters.
- Its effect on the proposed architecture.
- The resulting action.
- Related files or decisions.
- Remaining uncertainty.
- The checkpoint or commit containing the finding.

Record negative findings, conflicting evidence, discarded approaches, and failed investigations when relevant.

Do not mark an illustrative example as an actual result.

Do not record a claim as verified merely because it appears in a search snippet or README.

If the finding is an estimate or assumption, label it explicitly.

### 5.6. `SOURCE_REGISTER.md` — Track every researched source

For each source, record:

- Source ID.
- Name.
- Actual URL.
- Source category.
- Date accessed when available.
- Whether the source was accessible.
- Which pages or files were read.
- Whether actual source code was inspected.
- Whether issues, commits, forks, or licenses were examined.
- Whether the source was independently tested.
- Its useful information.
- Its reliability limitations.
- Related finding IDs.
- Whether additional research is necessary.

Distinguish these statuses:

- Discovered.
- Accessed.
- Read.
- Source code inspected.
- Independently tested.
- Unavailable.
- Requires further investigation.

Never claim a repository was inspected just because it appeared in search results.

### 5.7. `DECISIONS.md` — Permanent engineering decision records

For each important decision, include:

- Problem or question.
- Options considered.
- Evidence.
- Selected approach.
- Rationale.
- Rejected alternatives.
- Relevant finding IDs.
- Consequences.
- Remaining uncertainties.
- Conditions that would justify revisiting the decision.

Do not silently reverse major decisions.

If new evidence invalidates a previous choice, record the new evidence and explain the replacement.

### 5.8. `TASKS.md` — Persistent execution tracking

Track meaningful tasks with explicit statuses:

- `TODO`
- `IN_PROGRESS`
- `BLOCKED`
- `DONE`
- `NEEDS_RETEST`

Record dependencies, related files, and completion criteria.

Do not mark a task complete merely because code has been written.

### 5.9. `WORK_LOG.md` — Chronological project history

Record substantial research, coding, testing, debugging, decisions, failures, fixes, GitHub operations, and packaging work.

Include the files affected and commit identifiers where available.

### 5.10. `TEST_RESULTS.md` — Genuine test evidence

For every significant test, record:

- Test ID.
- Purpose.
- Environment.
- Code or commit tested.
- Command or procedure.
- Expected result.
- Actual result.
- Pass/fail status.
- Relevant output or evidence.
- Defects discovered.
- Fixes applied.
- Whether the test must be rerun.

If source code changes, identify which earlier results are now stale.

### 5.11. `KNOWN_ISSUES.md` — Persistent blockers

For each issue, record:

- Issue ID.
- Symptom.
- Reproduction steps.
- Severity.
- Root cause if known.
- Related code.
- Previous attempts.
- Current status.
- Next diagnostic action.

Do not allow unresolved issues to disappear when chats change.

### 5.12. `GITHUB_WORKFLOW.md` — Actual persistence procedure

Record the GitHub capabilities, operations, and checkpoint process that have actually been verified in the current environment.

Never fabricate capabilities or write that an operation is available without confirming it.

## 6. VERIFY THE INITIAL MEMORY SYSTEM BEFORE RESEARCH

After creating these documents:

1. Read back their actual contents.
2. Verify that the project specification is sufficiently complete.
3. Verify that the clean-chat instructions are present.
4. Commit the files.
5. Synchronize them remotely.
6. Re-read the remote repository.
7. Verify the expected files and commit.
8. Record the actual URL, branch, and verified commit in `PROJECT_STATE.md`.
9. Commit and verify that updated state.

**Only after this initial checkpoint is remotely verified should the substantial technical research begin.**

If any operation fails, document the actual outcome and investigate a safe recovery.

Do not skip this requirement because the project prompt is long.

---

# PART III — THE ACTUAL ROBLOX SCREEN-SHARING PROJECT

## 7. YOUR OBJECTIVE

Create a Roblox experience containing a large physical screen in its 3D world.

The screen must display my real computer desktop.

When I open a browser, the Roblox screen should show it. When I move windows, scroll webpages, play a video, launch an application, or change the visible desktop, the Roblox screen should update accordingly.

The system must use real operating-system screen capture.

It must not be a prerecorded video, static image, simulated desktop, unrelated Roblox viewport, or fake demonstration.

The intended data flow is:

**ACTUAL PC DESKTOP**  
↓  
REAL SCREEN-CAPTURE MECHANISM  
↓  
FRAME PROCESSING, ENCODING, AND COMPRESSION  
↓  
SECURE TRANSPORT OR RELAY  
↓  
PUBLISHED ROBLOX EXPERIENCE  
↓  
ROBLOX CLIENT-SIDE IMAGE RECONSTRUCTION  
↓  
PHYSICAL SCREEN IN THE 3D WORLD  
↓  
AUTHORIZED PLAYERS SEE THE CHANGING PC DISPLAY

You may redesign this architecture if research demonstrates a better supported method.

My priorities are:

1. Genuine end-to-end functionality.
2. Correctness and supported APIs.
3. Reliability.
4. Useful image quality and responsive updates.
5. Security and privacy.
6. Low bandwidth and resource consumption.
7. Easy installation and troubleshooting.
8. Sensible operating cost.

Do not sacrifice genuine functionality for appearance.

## 8. MANDATORY INTERNET AND GITHUB RESEARCH

Use the available search, browsing, GitHub, repository-inspection, terminal, and code-reading tools.

Research official Roblox documentation, Roblox Developer Forum discussions, GitHub repositories, archived implementations, source code, issue trackers, pull requests, Reddit discussions, community tutorials, and relevant technical articles.

Do not stop after reading a few search results.

Search using alternative terminology and follow useful links to original implementations.

Investigate:

- Screen sharing inside Roblox.
- Streaming a Windows desktop into Roblox.
- Actual PC capture and dynamic in-world screen rendering.
- Roblox EditableImage and runtime image construction.
- Pixel-grid rendering.
- Python screen capture.
- HTTP frame retrieval.
- Server-Sent Events and WebSockets.
- Binary image transport.
- RemoteEvent bandwidth and payload constraints.
- Delta-frame encoding.
- Changed-region updates.
- Palette compression.
- Run-length encoding.
- Reduced-color representations.
- Local servers and remote relays.
- Network tunnelling.
- Published-game HTTP restrictions.
- Dynamic media and video limitations.
- Multi-client image distribution.
- Compression and latency.
- Existing implementations and their successors.

**GitHub research findings must be recorded in the repository as they are discovered.**

For each substantial source, complete the findings documentation and remote checkpoint before moving on to the next source.

## 9. SPECIFIC PROJECTS THAT MUST BE INVESTIGATED

These are starting points, not an exhaustive list.

### 9.1. ScreenBlox

Investigate the ScreenBlox project associated with the Roblox Developer Forum screen-sharing resource published by Reb0rnEnder.

Examine its original post, available source code, revisions, discussions, and related resources.

Determine:

- How capture is performed.
- How captured content reaches Roblox.
- Which image format is used.
- How image data is transmitted.
- How the Roblox client reconstructs the image.
- Whether the implementation uses pixel elements, EditableImage, or another method.
- Reported update rates and supported image quality, when verifiable.
- Networking and hosting requirements.
- Known bugs and compatibility issues.
- Existing forks or successors.

Investigate discussions about RemoteEvent payload size, EditableImage performance, frame transfer, local servers, and externally exposed endpoints.

Do not assess it solely from the introduction or a demonstration video.

### 9.2. Icy-Monster's Screen-Sharing-in-Roblox

Investigate the GitHub repository titled `Screen-Sharing-in-Roblox` by Icy-Monster.

Study its Python components and Roblox project.

Determine its compression methods, including repetition-based encoding, transport, image reconstruction, installation process, port-forwarding requirements, licensing, issues, forks, archive status, and possible successors.

Identify useful techniques and aspects that should be replaced.

### 9.3. RSSP by ssavnayt

Investigate the GitHub repository called `RSSP`, described as a Roblox screen-sharing API.

Inspect its actual source, configuration, API endpoints, authentication, capture process, Roblox integration, dependencies, history, and issues.

Investigate its approaches involving HTTP polling, SSE, raw bytes, compression, and different versions.

Examine associated Roblox demonstrations where accessible.

Determine which components work under current Roblox restrictions.

Do not assume repository claims are correct without appropriate verification.

### 9.4. Additional implementations

Investigate:

- The archived Screen-Sharing-in-Roblox project and its forks.
- The ScreenShare free-game-source project discussed on the Roblox Developer Forum in 2024.
- The Reddit discussion approximately titled "I was tired, so I made AnyDesk in Roblox."
- Older Roblox Developer Forum screen-casting discussions.
- Implementations using EditableImage, pixel grids, palette compression, delta encoding, or frame reconstruction.
- Newer implementations published after the projects named above.
- Other credible solutions discovered during research.

Inspect actual source code wherever possible.

If a repository is unavailable, record the failed access, search surviving forks and references, and investigate alternatives.

Respect open-source licenses. Do not copy code without checking the applicable licensing and attribution requirements.

## 10. AUTHORITATIVE ROBLOX API VERIFICATION

Consult current official Roblox Creator documentation for:

- `VideoFrame`.
- `EditableImage`.
- `AssetService`.
- `SurfaceGui`.
- `ImageLabel` and other relevant image APIs.
- `HttpService`.
- HTTP restrictions, quotas, and execution contexts.
- `RemoteEvent`.
- `UnreliableRemoteEvent`.
- Binary buffers and supported data types.
- Creator Dashboard security settings.
- Server-side secret management.
- Published-experience networking restrictions.
- Runtime image construction and updates.
- Relevant asset and media restrictions.

Investigate and answer these questions:

1. Can a normal Roblox client capture its host computer's desktop?
2. Can a published Roblox experience access Windows operating-system capture APIs?
3. Can a published experience maintain a persistent external WebSocket or SSE connection?
4. Which HTTP operations can a live experience perform?
5. Which execution contexts can perform those operations?
6. Can Roblox create or modify dynamic images from raw pixel data at runtime?
7. What are the exact current EditableImage APIs, parameter types, pixel formats, memory constraints, and availability restrictions?
8. Do dynamically modified image contents replicate automatically?
9. What are the practical payload and bandwidth constraints for RemoteEvents and binary data?
10. How should frames be delivered efficiently to multiple clients?
11. How should external credentials be protected?
12. What HTTP, domain, or permission settings are needed?
13. Which capabilities differ between Studio and published experiences?
14. Which approaches work in actual published games rather than only in a development environment?

Use current documentation and cite the original sources in the project research records.

Separate official documentation from community reports, assumptions, and experimental workarounds.

**Do not implement a Roblox-only desktop-capture script unless there is credible evidence that the required operating-system functionality is genuinely accessible to ordinary Roblox scripts.**

Do not assume an arbitrary stream URL can be assigned to `VideoFrame`.

Do not assume localhost is reachable from a remote Roblox server.

Do not assume client-side image modifications replicate automatically.

Do not invent APIs, properties, permissions, or networking capabilities.

Save important findings to GitHub before relying on them in the architecture.

## 11. ARCHITECTURE COMPARISON

Compare at least these possibilities:

A. Roblox-only Luau.

B. A grid of Roblox parts or GUI elements representing pixels.

C. EditableImage with dynamically reconstructed pixels.

D. A Windows capture application and local HTTP service.

E. A desktop capture application, secure external relay, and client-side image reconstruction.

F. Any superior architecture discovered during research.

Evaluate each approach in terms of:

- Actual feasibility.
- Supported API compatibility.
- Image quality.
- Resolution.
- Update frequency.
- Latency.
- Bandwidth.
- CPU and memory consumption.
- Roblox server processing.
- Client-side rendering.
- Multi-client scalability.
- Reliability.
- Deployment complexity.
- Security.
- Operating cost.

Identify existing projects that demonstrate each approach and distinguish demonstrated capabilities from theoretical potential.

Select the strongest practical architecture based on evidence.

If the system requires a Windows application, local service, relay, or tunnel, implement the necessary components.

Clearly distinguish local development from published deployment.

Do not choose an architecture merely because it appears elegant.

Do not spend most of the task forcing unsupported Roblox-only functionality to work.

Document the selected architecture and reasoning in `DECISIONS.md` and `ARCHITECTURE.md` before extensive implementation.

If later evidence changes the design, preserve the reason for the change.

---

# PART IV — IMPLEMENT THE COMPLETE SYSTEM

## 12. BUILD ALL NECESSARY COMPONENTS

Implement the complete system required by the chosen architecture.

Depending on actual requirements, this may include:

- Windows desktop screen-capture application.
- Frame processing and compression.
- Transport protocol.
- Local service.
- Secure relay.
- HTTP API.
- Authentication.
- Roblox server-side scripts.
- Roblox client-side scripts.
- Shared Luau modules.
- Physical screen model.
- Configuration templates.
- Installation scripts.
- Startup and shutdown scripts.
- Automated tests.
- Diagnostics.
- Performance benchmarks.
- Documentation.

Do not add unnecessary services.

Every required component must be implemented and connected to the complete pipeline.

## 13. DESKTOP CAPTURE APPLICATION

Implement genuine screen capture using an appropriate, maintained, Windows-compatible library.

Requirements:

- Capture the primary monitor by default.
- Allow configuration of resolution and capture frequency.
- Offer practical quality/performance settings.
- Handle screen-resolution changes gracefully.
- Recover from unavailable capture sources without crashing.
- Detect unchanged frames when that reduces resource use.
- Avoid unnecessary encoding and network transfers.
- Display a clear sharing status.
- Require an explicit action to start sharing.
- Provide an immediate stop operation.
- Recover from temporary network failures.
- Log useful diagnostics without logging sensitive screen contents.
- Support monitor selection where practical.
- Support window capture only if the selected implementation genuinely supports it.

Test the actual capture mechanism on a supported environment if available.

Do not claim capture works based solely on code inspection.

Specify compatible dependency versions and respect their licenses.

## 14. FRAME ENCODING AND TRANSPORT

Research and choose a representation suited to the actual Roblox rendering method.

Evaluate:

- RGB or RGBA pixel buffers.
- Reduced-resolution images.
- RGB565 or another compact color representation.
- Palette-based encoding.
- Run-length encoding.
- Delta frames.
- Changed-region updates.
- Hybrid techniques.

Optimize the complete pipeline rather than only the compression ratio.

Account for the cost of capturing pixels, converting them, compressing them, transmitting them, validating data, reconstructing images, and rendering frames.

Do not assume Roblox can directly decode arbitrary JPEG, PNG, H.264, or other encoded bytes. Verify the entire pipeline, or implement an appropriate conversion step.

When using EditableImage, verify the exact supported buffer format, APIs, and runtime limitations.

When using RemoteEvents, verify the actual data constraints and implement suitable packetization and reassembly when necessary.

Avoid transmitting millions of JSON numbers when a compact binary representation or better transport is feasible.

Do not create one Roblox Instance per pixel unless research and benchmarks demonstrate a compelling advantage.

Implement:

- Frame identifiers.
- Dimension validation.
- Packet-size limits.
- Bounds checks.
- Integrity checks where appropriate.
- Timeouts.
- Incomplete-frame rejection.
- Out-of-order packet handling.
- Reconnection.
- Rate limiting.
- Backpressure.
- Queue and memory limits.
- Cleanup of incomplete transfers.

Never display a partially reconstructed frame as if it were complete.

Ensure the producer cannot overwhelm downstream clients.

Record benchmark methods and results in GitHub.

## 15. PHYSICAL IN-WORLD SCREEN

Create a visible, functional television or monitor inside the Roblox world.

Include:

- A rectangular physical display.
- A suitable SurfaceGui or another supported rendering mechanism.
- A dynamically updated image.
- Correct image orientation.
- Correct aspect ratio.
- A screen housing or frame.
- A visible sharing indicator.
- Loading and connection states.
- An error state.
- A stopped-sharing state.

If no existing map is supplied, create a simple demonstration room and place the television where it is easy to locate.

Use maintainable construction techniques rather than manually creating unnecessary numbers of objects.

Prioritize legibility, correct orientation, image quality, and performance.

## 16. ROBLOX SERVER AND CLIENT ARCHITECTURE

Separate responsibilities properly.

The architecture must distinguish:

- Desktop capture.
- External service communication.
- Server-side frame retrieval, if appropriate.
- Authentication and authorization.
- Data validation.
- Client-side reconstruction.
- Image display.
- Synchronization.
- Error reporting.
- Reconnection.

Verify whether dynamically modified image content must be created and updated locally by each client.

Do not assume that EditableImage modifications replicate automatically.

Implement the correct delivery mechanism so authorized players looking at the screen see the same shared PC display.

Use a single capture source for the experience unless testing demonstrates a better design.

Do not start a separate desktop-capture pipeline for each Roblox player.

Avoid unnecessary requests, duplicated frames, excessive event traffic, unbounded queues, and memory leaks.

Test with multiple clients where tools are available.

Document realistic concurrency limitations.

---

# PART V — PERFORMANCE AND RELIABILITY

## 17. BENCHMARK REAL PERFORMANCE

Provide configurable quality profiles:

- Low bandwidth.
- Balanced.
- High quality.

Choose the default based on testing or defensible engineering estimates.

Evaluate multiple practical resolutions and update rates.

Benchmark where possible:

- Capture duration.
- Encoding duration.
- Frame sizes before and after compression.
- Network bandwidth.
- Server processing.
- Client reconstruction.
- End-to-end latency.
- CPU usage.
- Memory usage.
- Dropped frames.
- Queue growth.

Test both static desktops and rapidly changing content, including videos or games when safe and feasible.

A system that works only for a static desktop must not be advertised as a high-performance video-streaming system.

Explain how motion and image complexity affect performance.

If 30 or 60 FPS is impractical, select a more realistic target.

Clearly distinguish measurements, calculations, engineering estimates, and unverified assumptions.

Record actual results, commands, environments, and relevant commit identifiers in `TEST_RESULTS.md` and `PERFORMANCE.md`.

## 18. SECURITY AND PRIVACY

The system transmits my actual desktop. Privacy must be built into the design.

Mandatory safeguards:

1. Screen capture must not start silently.
2. Sharing must require an explicit user action.
3. The application must display a clear active-sharing indicator.
4. Sharing must stop immediately when requested.
5. Do not capture a webcam or microphone.
6. Do not implement keylogging or hidden surveillance.
7. Do not implement remote mouse control.
8. Do not implement remote keyboard input.
9. Do not implement arbitrary command execution.
10. Do not implement general-purpose remote desktop capabilities.
11. Do not permanently store captured images or video by default.
12. Do not transmit content to an undisclosed or untrusted endpoint.
13. Do not expose credentials in client-visible code.
14. Authenticate external endpoints.
15. Validate requests and apply sensible rate limits.
16. Restrict sharing controls to authorized users.
17. Do not allow arbitrary players to access unrelated local files.
18. Do not create a generic HTTP proxy.
19. Ensure reliable cleanup and shutdown.
20. Protect configuration files and exclude secrets from source control.

Investigate current supported Roblox secret-management mechanisms and use them where appropriate.

If an external relay or tunnel is necessary, explain the risks and configure the narrowest practical access.

Document relevant decisions and security tests.

## 19. PUBLISHED-EXPERIENCE COMPATIBILITY

The solution must be designed for a real published Roblox experience.

Distinguish:

- Studio.
- Studio local play testing.
- Published private test servers.
- Public live servers.

Document the required Creator Dashboard settings, HTTP permissions, domain restrictions, external credentials, and deployment procedures.

Studio success does not establish production compatibility.

Do not use a Studio-only feature as an essential part of the published architecture.

Prefer supported APIs over undocumented workarounds.

If something is experimental, unsupported, unreliable, or unavailable, document the limitation and use a better approach where possible.

Save compatibility findings to GitHub as they are discovered.

---

# PART VI — CODE QUALITY, TESTING, AND DEBUGGING

## 20. IMPLEMENTATION QUALITY

Treat the codebase as a real software engineering project.

All necessary source code must be complete, internally consistent, readable, maintainable, properly integrated, and appropriately documented.

Do not include:

- Pseudocode instead of required implementation.
- Missing modules.
- Undefined variables.
- Functions that are called but not implemented.
- Essential TODOs.
- Placeholder endpoints presented as operational.
- Dummy frames presented as actual captures.
- Fake success messages.
- Unsupported Roblox API calls.
- Unexplained dependencies.
- Hard-coded production credentials.
- Contradictory setup instructions.
- Claims of testing that did not occur.

Use sensible module boundaries, input validation, structured errors, timeouts, resource cleanup, and compatible dependency versions.

Keep the design as simple as possible without sacrificing the essential requirements.

Inspect the existing workspace before modifying files.

Do not overwrite unrelated files.

Checkpoint significant code changes to GitHub.

## 21. DESKTOP APPLICATION TESTS

Implement and run available tests for:

- Application startup and shutdown.
- Actual desktop capture.
- Frame dimensions.
- Pixel format.
- Resolution changes.
- Compression and decompression.
- Change detection.
- Authentication.
- Invalid requests.
- Network interruptions.
- Missing dependencies.
- Recovery after temporary failures.

## 22. ENCODING TESTS

Create tests for:

- Solid-color images.
- Text-heavy images.
- Gradients.
- Random pixel patterns.
- Changing frames.
- Corrupt payloads.
- Truncated packets.
- Incorrect dimensions.
- Invalid frame identifiers.
- Out-of-order packets.

Verify dimensions, orientation, pixel ordering, expected color precision, reconstruction, integrity checks, rejection of corrupt data, and compression effectiveness.

## 23. ROBLOX TESTS

Use the best available combination of:

- Static validation.
- Luau analysis.
- Automated tests.
- Roblox Studio testing.
- Multi-client testing.

Check:

- Correct script placement.
- Required Instances and remotes.
- API compatibility.
- Dynamic image creation.
- Pixel-buffer updates.
- Frame assembly.
- Payload validation.
- Disconnect/reconnect behavior.
- Resource cleanup.
- Repeated updates.
- Behavior when the external capture service is unavailable.

If the Roblox runtime is not available, identify the precise tests that could not be performed and execute everything else possible.

## 24. END-TO-END ACCEPTANCE TEST

The main acceptance test is:

1. Start the capture application on the Windows PC.
2. Explicitly enable sharing.
3. Start the Roblox experience.
4. Approach the physical screen in the map.
5. Confirm that it displays real pixels captured from the PC.
6. Change a clearly visible part of the desktop.
7. Confirm that the Roblox display updates.
8. Stop sharing.
9. Confirm that transmission stops and the in-world display changes to its stopped state.

If the available environment cannot perform this complete test, build the complete testable system, run all feasible intermediate tests, and explain which real-world steps remain.

Never claim a complete screen-sharing pipeline works without evidence that the actual pixels traverse the relevant components.

Never misrepresent static testing as end-to-end verification.

Record every significant test and result in GitHub.

When a source-code change invalidates a prior test, mark the affected test as needing to be rerun.

---

# PART VII — COMPLETE DELIVERABLES

## 25. RESEARCH AND FEASIBILITY REPORT

Deliver a report explaining:

- Which implementations were investigated.
- Which source files, discussions, and documentation were actually inspected.
- What techniques were useful.
- What limitations were observed.
- Which official Roblox constraints affect the project.
- Which architectures were compared.
- Which architecture was selected.
- Why it was selected.
- What remains uncertain.

Include links to sources genuinely inspected.

Maintain detailed research records in the repository.

## 26. COMPLETE PROJECT SOURCE

Provide a clean, complete project repository.

Include all necessary:

- Roblox scripts.
- Desktop capture code.
- Frame-processing and compression modules.
- Relay components if required.
- Configuration templates.
- Dependency manifests.
- Startup and shutdown scripts.
- Tests.
- Documentation.
- Required supporting files.

If Rojo is used, provide a valid project configuration and source hierarchy.

If practical, generate a Roblox Studio-importable model or place file containing the television and necessary Roblox objects.

If that is not possible, provide complete scripts and exact Explorer placement instructions.

Do not claim that an importable file exists without creating and verifying it.

## 27. INSTALLATION GUIDE

Write a step-by-step guide for Windows and Roblox Studio.

Explain:

- Required software.
- Dependency installation.
- Roblox project setup.
- Component import.
- Configuration.
- Authentication.
- External service or relay setup.
- Startup.
- Connection.
- Testing.
- Stopping sharing.
- Troubleshooting.

Include real commands and configuration examples.

Separate local development from published deployment.

Do not omit necessary settings, relay steps, domain configuration, credentials, or permissions.

Investigate free and self-hosted alternatives before requiring a paid service.

If payment is unavoidable, explain why and identify the practical alternatives.

## 28. PERFORMANCE REPORT

Document measured or estimated:

- Default resolution.
- Default update rate.
- Practical maximum settings.
- Frame sizes.
- Bandwidth.
- Latency.
- CPU and memory consumption.
- Multi-client limitations.
- Quality profiles.
- Roblox-imposed restrictions.

Label every measurement, estimate, and assumption accurately.

## 29. TEST REPORT

Record the actual tests run, their environment, results, defects discovered, fixes made, and remaining unverified behavior.

Do not fabricate results.

## 30. TROUBLESHOOTING GUIDE

Cover:

- Black screen.
- Unreachable capture service.
- HTTP requests failing.
- Authentication errors.
- EditableImage restrictions.
- Corrupt frame data.
- Incorrect image orientation.
- Slow updates.
- Oversized payloads.
- Published-versus-Studio differences.
- Server overload.
- Unexpected capture-process termination.

Ensure every solution matches the implementation.

## 31. CONVENIENT STARTUP AND SHUTDOWN

Where practical, provide Windows scripts or another straightforward mechanism to start and stop the required components.

Explain which programs or services must remain running.

## 32. PROJECT ARCHIVE

If the environment supports file creation, create a complete ZIP archive.

Verify the archive contains the necessary source tree and instructions.

Provide an actual downloadable link only if the archive exists and its path has been confirmed.

## 33. VERIFIED GITHUB HANDOFF

Report:

- Actual repository URL.
- Visibility, when available.
- Current branch.
- Latest verified commit.
- Key source directories.
- Files verified remotely.
- Tests actually performed.
- CI results actually inspected.
- Remaining integration limitations.
- Current checkpoint state.

Never invent URLs, commits, files, or test results.

---

# PART VIII — MANDATORY DEVELOPMENT WORKFLOW

## 34. FOLLOW THESE STAGES IN ORDER

Do not ask me to approve every ordinary decision.

### Stage 1 — GitHub setup and persistent memory

Create the repository, create all required initial documentation, preserve the full specification, commit it, synchronize it, and verify the remote state.

### Stage 2 — Workspace inspection

Inspect the working directory and existing repositories. Avoid overwriting unrelated files.

### Stage 3 — Research

Investigate the named projects, additional implementations, and official Roblox documentation.

Record each substantial discovery and verify its GitHub checkpoint.

### Stage 4 — Feasibility

Establish which approaches genuinely work under current platform constraints.

Document important limitations before making architectural commitments.

### Stage 5 — Architecture design

Compare viable options and document the final decision and evidence.

### Stage 6 — Implementation

Build and integrate the complete desktop-to-Roblox pipeline.

Persist meaningful implementation steps as they are completed.

### Stage 7 — Testing

Run static checks, unit tests, networking tests, encoding tests, and available Roblox tests.

Record exact results.

### Stage 8 — Debugging

Fix reproducible defects. Do not stop at the first compile error or failed request.

Document root causes and fixes.

### Stage 9 — Optimization

Benchmark the system and improve the real bottlenecks.

### Stage 10 — GitHub verification

Verify the actual remote source tree and recent commits.

Inspect CI results where available.

Resolve synchronization problems where possible.

### Stage 11 — Packaging

Create the research report, installation guide, troubleshooting guide, performance report, tests report, and project archive where supported.

### Stage 12 — Final audit

Check that the source, repository, dependencies, configuration, instructions, and test evidence are consistent.

Update all persistent state documents.

Commit, synchronize, and verify the final checkpoint.

Do not stop after writing a plan.

Do not stop after creating a few scripts.

Do not stop after showing a static image.

Do not silently replace actual screen capture with prerecorded media.

If full-motion streaming cannot achieve the desired quality within actual Roblox limitations, determine the strongest genuine alternative and implement it. Explain the trade-off honestly.

---

# PART IX — AUTOMATIC RECOVERY IN EVERY NEW CLAUDE CHAT

## 35. ASSUME THE NEXT CHAT HAS ZERO MEMORY

Whenever a new Claude chat begins work on this project, assume it has no previous conversation history.

**Do not ask me what happened in the old chat if the information can be recovered from GitHub.**

Do not restart the project from scratch.

Do not repeat completed research unnecessarily.

Do not assume a previous result remains valid after the source has changed.

Begin by following this procedure:

### Step 1 — Locate the authoritative repository

Use the connected GitHub account.

Find the repository identified in the state and handoff files.

Verify its real URL and current accessibility.

If several forks or copies exist, identify the authoritative one using the project records, branch information, and actual commit history.

### Step 2 — Inspect the latest remote state

Read the branch, recent commits, current tree, and available workflow results.

Identify the most recent verified remote checkpoint.

Check whether subsequent commits have changed the project state.

### Step 3 — Read the continuity documents

Read:

1. `PROJECT_SPEC.md`
2. `README.md`
3. `PROJECT_STATE.md`
4. `SESSION_HANDOFF.md`
5. `TASKS.md`
6. The relevant recent entries in `FINDINGS_LOG.md`
7. The relevant entries in `SOURCE_REGISTER.md`
8. `DECISIONS.md`
9. `WORK_LOG.md`
10. `TEST_RESULTS.md`
11. `KNOWN_ISSUES.md`
12. Other documents and source files relevant to the next task

### Step 4 — Reconstruct and verify the project state

Cross-check the documentation against actual source files, commits, tests, and workflow results.

Distinguish:

- Implemented.
- Locally tested.
- Committed.
- Verified remotely.
- CI tested.
- Verified in Studio.
- Verified in a published experience.
- Not yet verified.

Documentation alone is not proof that a feature works.

### Step 5 — Resume the precise unfinished task

Consult `SESSION_HANDOFF.md` and `TASKS.md`.

Inspect the relevant source code before modifying it.

Continue from the latest verified state.

Do not reimplement completed components without a reason.

If a previous conclusion is contradicted by new evidence, correct it and record the change.

### Step 6 — Continue documenting and checkpointing

Use the same mandatory cycle:

**INVESTIGATE → DOCUMENT → COMMIT → SYNCHRONIZE → VERIFY → CONTINUE.**

### Step 7 — Prepare the next clean session

Before reaching a stopping point, update and synchronize:

- `PROJECT_STATE.md`
- `SESSION_HANDOFF.md`
- `TASKS.md`
- `WORK_LOG.md`
- Relevant findings and decision documents.
- Test records and issue records.

Write exact next-step instructions.

The next chat must not need the previous chat to understand the project or determine what to do next.

**GitHub, not conversation memory, is the durable record of the engineering work.**

---

# PART X — HANDLING INTERRUPTIONS AND FAILURES

## 36. NEVER LOSE IMPORTANT PROGRESS

Assume the conversation may end unexpectedly at any time.

Do not leave important implementation code only in a temporary workspace.

Do not leave crucial findings only in a browser tab.

Do not leave test results only in terminal output.

Do not leave architecture decisions only in conversation history.

Do not leave the next steps undocumented.

Checkpoint stable progress before undertaking long or risky work.

If a session ends unexpectedly, the next session must recover the project by checking GitHub, inspecting local state where available, and reconciling the actual contents.

Do not blindly overwrite newer remote changes with an older local copy.

Do not force-push or rewrite history merely to simplify synchronization.

Preserve work carefully when resolving conflicts.

If synchronization fails, document the failure and maintain the safest recoverable copy available.

## 37. NEVER FABRICATE SUCCESS

Never claim:

- A repository exists without verifying it.
- A file has been uploaded when only a local file exists.
- A commit succeeded without evidence.
- A push succeeded without checking the remote state.
- A test passed without execution.
- A source was inspected when only a search snippet was read.
- The published experience works because Studio worked.
- The entire screen-sharing pipeline works because one component was tested.

When a capability is unavailable, explain precisely which operation is blocked.

When a claim is an assumption, label it.

The checkpoint system must preserve accurate status, including failures, not fictional success.

---

# PART XI — FINAL ACCEPTANCE CRITERIA

## 38. PROJECT REQUIREMENTS

Before declaring completion, verify every applicable item:

- [ ] The connected GitHub tools were inspected.
- [ ] A real repository was created or an appropriate existing project repository was selected.
- [ ] The repository exists remotely and was verified.
- [ ] The full specification is saved in `PROJECT_SPEC.md`.
- [ ] Initial memory files were committed before substantial technical research.
- [ ] The repository includes a clean-chat recovery procedure.
- [ ] `PROJECT_STATE.md` is current.
- [ ] `SESSION_HANDOFF.md` contains actionable next steps.
- [ ] `FINDINGS_LOG.md` records material discoveries.
- [ ] `SOURCE_REGISTER.md` records investigated sources.
- [ ] `DECISIONS.md` records important engineering choices.
- [ ] `TASKS.md` tracks all substantial work.
- [ ] `WORK_LOG.md` records completed milestones.
- [ ] `TEST_RESULTS.md` contains actual testing evidence.
- [ ] `KNOWN_ISSUES.md` identifies remaining problems.
- [ ] Relevant GitHub projects were actually investigated.
- [ ] Official Roblox documentation was checked.
- [ ] The real desktop capture mechanism is implemented.
- [ ] The frame encoder and transport are implemented.
- [ ] The Roblox server and client components are complete.
- [ ] The physical screen is present or reproducibly constructible.
- [ ] The display can update from real desktop pixels when the pipeline is verified.
- [ ] The rendering approach uses supported APIs.
- [ ] Multi-client handling is implemented within realistic limits.
- [ ] Network failures and invalid data are handled.
- [ ] Credentials and screen contents are protected.
- [ ] Sharing can be explicitly started and stopped.
- [ ] Published-experience restrictions have been investigated.
- [ ] Performance has been measured or responsibly estimated.
- [ ] All feasible tests have been run.
- [ ] Remaining unverified behavior is explicitly documented.
- [ ] The latest meaningful work has been committed and synchronized.
- [ ] The latest remote checkpoint has been verified.
- [ ] The repository contents match the implementation.
- [ ] CI results are reported accurately where available.
- [ ] Setup instructions match the actual code.
- [ ] There are no essential placeholder components.
- [ ] The project archive has been created and checked if supported.
- [ ] A new Claude chat can resume work without this conversation.

Do not mark items complete without evidence.

---

# PART XII — REQUIRED FINAL ENGINEERING HANDOFF

## 39. REPORT THE ACTUAL RESULT

At the end, provide a concise but useful engineering handoff.

Begin with what you actually built, whether the full architecture is feasible, and what remains unverified.

Then explain:

### Architecture

The chosen architecture, why it was chosen, and how the components communicate.

### Research

The most useful existing implementations, official Roblox restrictions, and relevant findings.

### GitHub

The verified repository URL, branch, latest confirmed commit, directory structure, synchronization status, and CI results where available.

### Installation

Actual setup commands and steps.

### Tests

Executed tests and genuine results, separating automated tests, local execution, Studio tests, and published-experience tests.

### Performance

Measured or estimated resolution, frame rate, latency, bandwidth, and resource consumption.

### Remaining issues

Specific unresolved defects, limitations, and the reason each remains unresolved.

### Continuity

Identify the latest verified checkpoint.

State whether the continuity files have actually been synchronized and verified.

Give the exact next task recorded in `SESSION_HANDOFF.md`.

### Files

Provide the actual archive path or download link if an archive was created and verified.

Never invent repository URLs, commit identifiers, source findings, test results, or CI results.

Never misrepresent a code review as a runtime test.

Never misrepresent a Studio demonstration as proof of published-experience functionality.

Do not finish with an offer to make a better version later.

Complete as much of the project as your actual environment permits and leave it in a state from which a fresh Claude chat can resume immediately.

---

# FINAL DIRECTIVE — EXECUTE, PERSIST, VERIFY, CONTINUE

**FIRST: INSPECT THE ACTUAL GITHUB TOOLS, CREATE THE REPOSITORY, CREATE THE REQUIRED PROJECT-MEMORY FILES, COMMIT THEM, SYNCHRONIZE THEM, AND VERIFY THAT THE REMOTE FILES EXIST.**

**SECOND: RESEARCH THE SCREEN-SHARING PROBLEM, RECORD EVERY MATERIAL FINDING AND SOURCE, AND SAVE VERIFIED CHECKPOINTS TO GITHUB THROUGHOUT THE RESEARCH.**

**THIRD: IMPLEMENT THE COMPLETE SCREEN-SHARING PIPELINE, TEST IT, DEBUG IT, OPTIMIZE IT, DOCUMENT IT, AND SAVE EACH MEANINGFUL MILESTONE TO GITHUB.**

**FOURTH: BEFORE STOPPING, UPDATE AND VERIFY THE PROJECT STATE AND EXACT NEXT-SESSION INSTRUCTIONS.**

Every new Claude conversation must begin by recovering the latest verified project state from GitHub, not by asking me to explain the previous conversation.

Do not let valuable findings remain only in working memory.

Do not let source code remain only in a temporary workspace.

Do not delay documentation until the end.

Do not claim a change has been saved when it has not been verified remotely.

Do not stop after planning, researching, or creating placeholder files.

Repository creation and persistent memory are the mandatory first milestone. The actual working screen-sharing system remains the main objective.

**THE FINAL GOAL IS A REAL, WORKING, REPRODUCIBLE SYSTEM THAT DISPLAYS MY ACTUAL WINDOWS PC SCREEN ON A PHYSICAL SCREEN INSIDE A ROBLOX WORLD, WITH THE COMPLETE IMPLEMENTATION, EVERY MATERIAL FINDING, EVERY IMPORTANT ENGINEERING DECISION, TEST EVIDENCE, AND EXACT NEXT STEPS PRESERVED IN MY GITHUB ACCOUNT SO THAT A COMPLETELY CLEAN NEW CLAUDE CHAT CAN CONTINUE THE PROJECT CORRECTLY WITHOUT ANY PREVIOUS CONVERSATION HISTORY.**