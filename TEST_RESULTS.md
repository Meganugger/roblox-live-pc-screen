# TEST_RESULTS.md — Genuine test evidence

Each entry: Test ID · purpose · environment · code/commit tested · command/procedure · expected · actual · PASS/FAIL ·
evidence · defects · fixes · rerun needed (STALE when the tested code changed).

## TR-0001 — Python codec + protocol unit tests (T-0009)

- **Purpose**: quantization (RGB565/RGB888), keyframe/delta round trips (solid, gradient, text-like, noise; 1×1 … 1024×1024),
  part splitting, zstd/none compression, status containers, base64 bodies, malformed input (truncation at every length,
  header/part field mutations, corrupted zstd, tile-index rules, no write on failed part).
- **Environment**: agent sandbox, Linux x86_64, Python 3.13, numpy 2.5.4, zstandard 0.25.0 (11th session, 2026-10-25).
- **Code tested**: `desktop/rlps/{protocol,codec}.py` + `desktop/tests/test_codec.py` at `c02868a`.
- **Command**: `cd desktop && python3 -m unittest discover -s tests -t .`
- **Result**: `Ran 25 tests in 0.404s — OK` → **PASS** (automated unit tests only; no Windows capture, no Roblox runtime).

## TR-0002 — Frame service tests (T-0011)

- **Purpose**: real HTTP on 127.0.0.1 (ephemeral port): 401 without/with wrong token, 404/405/400 (unknown path, other
  methods, malformed/unknown/repeated/out-of-range params), failed-auth and request rate limits (429), STOPPED while not
  sharing, LIVE+UNCHANGED before the first frame and at long-poll timeout, keyframe → delta (1 changed tile) →
  reconstruction equals the source, identical frames not republished, long-poll wake-up on publish, stop wakes waiters
  and drops frames, keyframes for unknown session / evicted base / `key=1`, new session id after restart, resolution
  change → keyframe, reverted change → UNCHANGED advancing the base, 6 concurrent pollers get one cached body.
- **Environment**: agent sandbox (Linux, Python 3.13, numpy 2.5.4, zstandard 0.25.0), 11th session.
- **Command**: `cd desktop && python3 -m unittest discover -s tests -t .` → `Ran 41 tests in 9.0s — OK` (25 codec + 16
  service) → **PASS**. Not tested: public tunnel/HTTPS, Roblox `RequestAsync` against it.

## TR-0003 — Capture + desktop app tests (T-0010)

- **Purpose**: `fit_size`/box+bilinear resize/BGRA→RGB, mss monitor + region selection, missing monitor, grab error →
  reopen, geometry refresh (resolution change), profiles, nothing captured before Start, start/stop idempotence, stop
  closes the source + drops frames + no grabs afterwards, new session on restart, interruption backoff/recovery, profile
  change, token config create/reuse/rotate/0600/short-token rejection, console commands, and a test-double screen →
  capture loop → real HTTP frame service → reference decoder (keyframe equals the stored frame, 1-tile delta, STOPPED
  after stop).
- **Environment**: agent sandbox (Linux, Python 3.13.15, numpy 2.5.4, zstandard 0.25.0, mss 10.2.0 installed but no
  display), 12th session. **Code tested**: working tree of checkpoint "feat(desktop): sharing app …".
- **Command**: `cd desktop && python3 -m unittest discover -s tests -t .` → `Ran 63 tests in 12.2s — OK` (25 codec + 16
  service + 12 capture + 10 app) → **PASS**. Not run: real `mss` capture (no display/Windows, KI-0001), Tk window.

## TR-0004 — Luau decoder vs Python reference codec (T-0009)

- **Purpose**: prove `roblox/src/shared/RlpsDecoder.luau` + `RlpsProtocol.luau` decode exactly what `desktop/rlps/codec.py`
  encodes and reject exactly what the reference decoder rejects, with identical error strings: 7 keyframe→delta sequences
  (17 containers: 1×1 … 320×180, RGB565/RGB888, tiles 8/16/32, zstd + none, one-tile-per-part splits, resolution change)
  compared by CRC-32 of the reconstructed RGBA frame after every container; 5,316 corruption cases (every truncation,
  every truncation with a re-fixed `bodyLength`, every single-byte mutation with 4–5 values of a 2-part keyframe and a
  delta, trailing byte, STOPPED/UNCHANGED status containers and their mutations); 7 hand-built payloads (duplicate,
  decreasing, out-of-range tile indices, short/long tile data, tile-count mismatch); record-level checks (trailing byte,
  frame-size mismatch); and "a failed part never modifies the frame".
- **Environment**: agent sandbox (Linux x86_64), Luau CLI **0.744** (`luau`, `luau-analyze` from luau-lang releases),
  Python 3.13, numpy 2.5.4, zstandard 0.25.0 (14th session, 2026-10-25).
- **Command**: `python3 roblox/tests/run_luau_tests.py --analyze` → `luau-analyze: OK`, `SUMMARY passed=5344 failed=0`
  (0.9 s) → **PASS**.
- **Negative controls** (harness can fail): G6 bit-replication shift changed 4→5 → 5 failures (CRC mismatch); tile-index
  rule `<=` → `<` → 8 failures (duplicate index accepted). Both reverted (decoder blob `1cfdac3` = remote).
- **Limits**: zstd parts use a test shim mapping each Python-compressed payload to its raw bytes — the real
  `EncodingService:DecompressBuffer` path is unverified until Studio (KI-0002). Not a Roblox runtime test.

## TR-0005 — Luau + Python suite rerun at session start (22nd session, recovery baseline)

- **Purpose**: confirm the recovered remote head `0d12851` still passes every automated Luau check before new work.
- **Environment**: agent sandbox (Linux x86_64), Luau CLI 0.744, Python 3.13.15, numpy 2.5.4, zstandard 0.25.0 (2026-10-25).
- **Command**: `python3 roblox/tests/run_luau_tests.py --luau <luau> --analyze`
- **Result**: vectors 7 sequences / 17 containers, 5,316 corruption cases, 7 payloads; `luau-analyze (5 modules): OK`;
  Base64 67/67, ClientCore 154/154, Decoder 5344/5344, RelayCore 95/95 → **TOTAL 5660 passed, 0 failed → PASS**.
- **Python suite**: `cd desktop && python3 -m unittest discover -s tests -t .` → `Ran 63 tests in 12.0s — OK` → **PASS**.
- **Limits**: `RlpsServer.server.luau` / `RlpsClient.client.luau` are not analyzed or executed by this harness (they need
  Roblox globals); still no Roblox runtime (KI-0002).

## TR-0006 — Rojo build + strict Roblox-API type check of every Roblox script (23rd session)

- **Purpose**: first static check of `RlpsServer.server.luau` / `RlpsClient.client.luau` against the real Roblox API surface
  (they were never analyzed: TR-0005 limit) and first build of the Rojo project.
- **Environment**: agent sandbox (Linux x86_64), Rojo 7.7.1, luau-lsp 1.70.1 + its `globalTypes.d.luau` (Roblox API
  definitions), Luau CLI latest release (2026-10-25).
- **Command**: `scripts/check_roblox.sh` (downloads the pinned tools, `rojo build` → `build/RlpsDemo.rbxlx`, `rojo sourcemap`,
  `luau-lsp analyze --platform=roblox --definitions=@roblox=… --sourcemap=… roblox/src`).
- **Result before fixes (`55c9793`)**: **FAIL** — (1) `rojo build`: "File is not a valid JSON model: RlpsTV.model.json …
  data did not match any variant of untagged enum UnresolvedValue" (CFrame written as `{position, orientation}`; Rojo's
  implicit CFrame is 12 numbers; the attribute must be the lowercase top-level `attributes` key); (2) luau-lsp:
  `RlpsServer.server.luau(105)` "Cannot call a value of type {Message} in union" (`for … in messages or {}`),
  `RlpsClient.client.luau(189)` "Types EditableImage and nil cannot be compared" (nil-budget check).
- **Fixes**: model CFrames → 12-number form, `attributes.RlpsFace = "Front"` (verified in the built place:
  `AttributesSerialize` decodes to `RlpsFace = "Front"`; `Tags` = `RlpsScreen`); `broadcast` guards `nil`;
  `CreateEditableImage` result typed `EditableImage?`.
- **Result after fixes**: `Built project to RlpsDemo.rbxlx` (21 items) and
  `luau-lsp analyze (Roblox definitions, roblox/src): OK` → **PASS**. Luau harness rerun: 5660 passed / 0 failed; Python 63/63 OK.
- **Limits**: static only — no Roblox runtime (KI-0002).

## TR-0007 — Baseline rerun at `6027eee` (26th session, 2026-10-26)

- **Environment**: agent sandbox (Linux x86_64), Python 3.13.15, numpy 2.5.4, zstandard 0.25.0, mss 10.2.0, Rojo 7.7.1,
  luau-lsp 1.70.1, Luau CLI 0.744. Fresh `git clone` of `main` at `6027eee` (the repository is clonable over HTTPS now).
- **Commands / results**: `cd desktop && python3 -m pytest -q` → **63 passed, 327 subtests passed**;
  `python3 roblox/tests/run_luau_tests.py --analyze` → luau-analyze OK, **TOTAL passed=5660 failed=0**;
  `scripts/check_roblox.sh` → `Built project to RlpsDemo.rbxlx`, `luau-lsp analyze (Roblox definitions, roblox/src): OK`
  → **PASS** (static + unit level only; no Roblox runtime, KI-0002).

## TR-0008 — Live pipeline test L3: real capture → frame service → unmodified Roblox scripts under emulation (28th session)

- **Purpose**: first run of the complete pipeline with real pixels: Xvfb desktop drawn by `tests/e2e/painter.py` →
  `mss` → `SharingController`/`CaptureLoop` → `FrameService` (loopback HTTP, real token) → unmodified
  `RlpsServer.server.luau` and 2 × `RlpsClient.client.luau` (plus all modules, placed as in `default.project.json`)
  under `tests/e2e/roblox_emulator.luau` (Lune 0.10.4; emulates Instances/attributes, ordered copied RemoteEvent
  delivery, HttpService via real HTTP + secrets, EncodingService base64/zstd/GetDecompressedBufferSize,
  EditableImage pixel store, Heartbeat). Docs: `docs/testing/E2E.md`.
- **Environment**: agent sandbox Linux x86_64 4 vCPU, Python 3.11.17, numpy 2.4.6, zstandard, mss 10.x, python-xlib
  0.33, Xvfb 1280×720×24, Lune 0.10.4. Command: `python3 tests/e2e/run_e2e.py`.
- **Result history**: first run at `2e1ff4c`+harness: 9/10 then FAIL E2E-08 — a **test** bug (the wait accepted the old
  frame before the capture loop saw the change) → `wait_match(after_seq=…)`. Defects found **in the product** by this
  test and fixed: (1) frame service printed a traceback when a poller hung up mid long-poll (`960f9df`, later widened to
  any `ConnectionError` on read or write, `339d6a3`); (2) Start took 3.1 s to reach the TV (stopped polls every 3 s) →
  `idle=1` held polls (`a6bdd7f`): 1.0 s; a first version of that change delayed *stop* news by 15 s (caught by the
  test: stop latency 15.25 s) and was corrected before commit; (3) no byte-rate pacing → `MaxBytesPerSecond` (`7e63e1c`);
  (4) `Enum.NormalId[<unknown>]` would raise in `addScreen` → enum-item lookup; (5) zstd content size not checked
  before decompressing on clients → `GetDecompressedBufferSize` check (`31d8e3d`).
- **Final result at `339d6a3`**: **21/21 PASS** (E2E-01…17, `docs/testing/evidence/e2e-report.json` from the
  `7e63e1c` run + TV snapshots `tv-*.png`): byte-exact EditableImage == newest captured frame for 2 clients, late
  joiner, deltas, 9 rapid changes, outage → error screen → recovery, Stop → TVs off and images destroyed, no script
  errors, pacing within budget (2,161 B/s ≤ 3,000), viewer allowlist, wrong token → no pixels. Latencies in
  `PERFORMANCE.md`.
- **Limits**: emulated Roblox engine (no real RemoteEvent limits, timeouts, EditableImage budget or rendering; tunnel
  hop emulated by URL rewrite). Not Studio, not published (KI-0002).

## TR-0009 — CI on GitHub Actions, including the live pipeline test on a real Windows desktop (28th session)

- **Workflow**: `.github/workflows/ci.yml` (jobs: Python tests ubuntu + windows; Luau specs + Rojo + luau-lsp; e2e on
  Ubuntu/Xvfb; e2e on `windows-latest` with real `mss` capture of the runner's desktop). Results read with GitHub MCP
  `pull_request_read get_check_runs`; failure output is posted by the workflow as a PR comment (no log API available
  to the agent, KI-0003 workaround).
- **Run at `fb6bcdd` (PR #1)**: Linux jobs PASS. `windows-latest` Python tests FAIL: the new hang-up test (Windows
  raises the reset on the *read* of the next keep-alive request, which the fix did not cover). e2e Windows: one run
  PASS, one FAIL — **E2E-01…16 all passed on the real Windows desktop (1024×768: start → picture 0.99 s, change → both
  TVs 0.16 s, stop 0.20 s)**; the failure was the test reading `state.json` while Lune replaced it
  (`PermissionError`) during E2E-15.
- **Fixes**: `339d6a3` (handler ignores `ConnectionError` on either side; test tolerates the replace race; emulator
  retries the replace). **Rerun at `6033ac1` (PR #1 head): all 5 jobs green** — Python ubuntu + windows, Luau/Rojo/
  luau-lsp, e2e Linux, **e2e Windows (real desktop capture, all scenarios)** (`get_check_runs`, completed 15:02:37Z).
- **Significance**: first evidence of **real Windows screen capture** through the whole pipeline (KI-0001 partially
  closed: Windows Server runner desktop, not the owner's PC/monitor setup).

## TR-0010 — Baseline suites at the end of the 28th session

- `cd desktop && python3 -m pytest -q` → **66 passed, 327 subtests**; `python3 roblox/tests/run_luau_tests.py --analyze`
  → **TOTAL passed=5664 failed=0**, luau-analyze OK; `scripts/check_roblox.sh` → Rojo build OK, luau-lsp (Roblox
  definitions) OK. TR-0001…TR-0007 results are superseded by these reruns (code changed: `server.py`, `app.py`,
  `RlpsServer`, `RlpsClient`, `RlpsRelayCore`).

## TR-0011 — Stream v2 (29th session, 2026-10-31): hybrid codec, bundles, congestion control, scroll copies

- **Environment**: agent sandbox (Linux x86_64, 4 vCPU Xeon 2.1 GHz), Python 3.11.17, numpy 2.4.6, OpenCV 5.0,
  zstandard, mss 10.x, Xvfb, Lune 0.10.4, Luau 0.744, Rojo 7.7.1, luau-lsp 1.70.1.
- **Commands / results at the session's final commit**: `cd desktop && python3 -m pytest -q` → **84 passed** (+327
  subtests; new `test_hybrid.py`: bit-exact float/integer IDCT, budgets, skip, convergence, scroll copies, copy
  validation); `python3 roblox/tests/run_luau_tests.py --analyze` → **5,984 / 0** (hybrid DCT sequences at many
  qualities, extreme coefficients, COPY tiles, bundles, hybrid corruption cases — Luau pixels bit-identical to Python);
  `scripts/check_roblox.sh` → Rojo build + luau-lsp strict (Roblox API types) OK; `python3 tests/e2e/run_e2e.py` →
  **25 / 25** (`docs/testing/evidence/e2e-report.json`).
- **Defects found by the live test and fixed during this work**: client queue used `#` on a table with leading `nil`s
  and silently dropped frame parts (desyncs); a "no news" status carried the newest seq and made the relay skip deltas
  (v1 advance semantics); a keyframe request could be cleared by a delta finishing at the same time; a desynced client
  retried sync only once; frame rate was not limited by client decode speed (even an unthrottled client fell behind);
  long history replays re-lagged resynced clients; scroll detection compared against a lossy picture (never matched)
  and against the previous capture (sub-pixel drift).
- **Benchmark**: `scripts/bench.py` → `docs/testing/evidence/bench.txt` (PERFORMANCE.md).
- **Not verified**: real Roblox (replication throughput, native-code decode speed on clients, raw-body probe outcome on
  live servers), the owner's PC (encode time, dxcam). CI status of the final commit: see PR #1 checks.
- **CI** at `96badc5`: 4/5 green; the Windows live test failed E2E-20 (`min_rate == rate_after_growth`,
  `max_lagging_viewers` 0: the 10 kB/s viewer was never detected) — root cause and fix in TR-0012 / D-0009. The failure
  report itself was missing: the Windows step runs `bash -eo pipefail` and a `grep` without matches ended it before it
  posted (fixed in `ce34fa9`).

## TR-0012 — Per-viewer flow control (29th session, 2026-10-31)

- **Commands / results**: `cd desktop && python3 -m pytest -q` → **85 passed** (+327 subtests; new
  `test_fresh_continues_the_chain_and_forces_one_new_keyframe`); `python3 roblox/tests/run_luau_tests.py --analyze` →
  luau-analyze OK, **6,588 / 0** (new `RlpsFanout.spec.luau`: 659 checks — every vector sequence relayed to an early
  viewer and a late joiner after every step with CRC-exact pictures, Stop, ack clamping, sync suppression, hold +
  suffix catch-up, waiting for a keyframe, history limit, median stats, and a 60 Hz network simulation);
  `scripts/check_roblox.sh` → Rojo + luau-lsp strict OK; `python3 tests/e2e/run_e2e.py` → **25 / 25**.
- **Simulation** (`RlpsFanout.spec.luau` §C, per-viewer bandwidth + latency): 1 MB/s, 30 fps stream, fast viewer 8 MB/s
  + 10 kB/s viewer → fast viewer received all 1,031 frames, held once while warming up, backlog ≤ 363 KiB; slow viewer
  backlog ≤ 120 KiB, 4 pictures, ended on the last frame; 8 keyframes in 70 s. Three similar viewers at 60 fps / 2.4 MB/s
  → no frame skipped after warm-up. A 500 kB/s viewer next to a fast one: fast unaffected, the slow one saw ~45 % of
  the frames.
- **E2E-20**: rate 300 kB/s → 1.46 MB/s, unchanged when the 10 kB/s viewer joined (`LaggingViewers` = 1), fast viewer
  107 distinct pictures in 14 s, both exact at the end.
- **CI** at `5a56a07` (PR #1): **5 / 5 green** — Python on Linux and Windows, Luau specs + Rojo + luau-lsp, live test on
  Xvfb and on the real Windows desktop (where E2E-20 had failed at `96badc5`).

## TR-0013 — Repository clean-up (29th session, 2026-10-31)

- **Commands / results**: `ruff check .` → clean (new `ruff.toml`; also a CI step); `cd desktop && python3 -m pytest -q`
  → **85 passed** (+327 subtests); `python3 roblox/tests/run_luau_tests.py --analyze` → luau-analyze OK on 7 modules
  **and the 6 specs** (lint warnings now fail too), **6,588 / 0**; `scripts/check_roblox.sh` → OK;
  `python3 tests/e2e/run_e2e.py` → **25 / 25**.
- **Finding**: E2E-21's byte bound (½ × 15 lossless keyframes) was inside the run-to-run spread — 262–386 kB for the
  same ~32,400 copied tiles, because refinement during the 0.12 s pauses depends on machine load. One full-suite run
  failed at 385.5 kB vs 377.6 kB; bound set to ⅔ (docs/testing/E2E.md); the copy-share criterion is unchanged.
- **CI** at `bc9ea90`: **5 / 5 green** (ruff now runs in both Python jobs).

## TR-0014 — Secret domain mismatch reported by the owner (29th session, 2026-10-31)

- **Owner report**: Studio TV showed "Screen unavailable / request failed: This secret cannot be used for a specified
  domain" — Roblox refused to attach the `rlps_token` secret because its domain did not match the `FrameServiceUrl`
  host (official rule, creator-docs `cloud-services/secrets.md`: `*`, `*.example.com` or an exact host).
- **Fix**: the server turns that error into "set the domain of secret 'rlps_token' to *.trycloudflare.com or <host>
  (host only, no https://): it does not allow <host>" (fix first: the TV shows ~160 characters; full text in
  `LastError`); a failed `/v1/probe` is retried instead of fixing base64 bodies for the URL.
- **Test**: the emulator now enforces Roblox's secret domain patterns (`RLPS_SECRET_DOMAIN`); new E2E-22 (domain
  `trycloudflare.com` → hint on the TV, no pixel; `*.trycloudflare.com` → exact desktop).
- **Results**: ruff clean; Python 85 passed; Luau 6,588 / 0; Rojo + luau-lsp OK; live pipeline **26 / 26**.

## TR-0015 — Client redraw economy, viewer modes, window / tab sharing (29th session, 2026-10-31)

- **Commands / results** (sandbox): `ruff check .` clean; `cd desktop && python3 -m pytest -q` → **93 passed, 2 skipped**
  (the two real-Windows tests); `python3 roblox/tests/run_luau_tests.py --analyze` → 8 modules + 7 specs analyzed OK,
  **6,657 / 0** (new: dirty rectangles on a scattered-change vector sequence, shadow picture CRC-exact; `RlpsView.spec`);
  `scripts/check_roblox.sh` OK (camera / ContextActionService / DepthOfField code type-checked against the Roblox API);
  `python3 tests/e2e/run_e2e.py` → **31 / 31** checks.
- **Measured**: E2E-23 two corner squares → `LastRedrawPixels` 6,144 of 589,824; E2E-24 45 redraws skipped while the
  camera looked away, picture exact after looking back; E2E-26 cinema camera distance 7.970 (computed 7.970), aim 1.0.
- **Not verified here**: real Roblox clients (WritePixelsBuffer cost per call, camera feel, DepthOfField look), window
  capture on the owner's PC; the real-Windows tests run in CI (see PR #3 checks).
- **CI** at `6ee3067` (PR #3): **5 / 5 green**. On the real Windows runner `test_windows.py` passed both real tests: a Tk
  window covered by a topmost window was captured by `PrintWindow` with its own colour (no screen fallback) and the
  client-area crop dropped its title bar; minimize / close were reported; a Chromium browser page opened in a new
  window was cropped to the page only and sharing paused when another tab opened. (The first run failed because the
  covering window inherited the same title and, correctly, the topmost match was captured — the test now titles it.)


## TR-0016 — Forum research changes: moderator kill switch, per-player hide, image-API probe, Sharp (29th session, 2026-10-31)

- **Commands / results** (sandbox): `ruff check .` clean; `cd desktop && python3 -m pytest -q` → **93 passed, 2 skipped**
  (Windows-only); `python3 roblox/tests/run_luau_tests.py --analyze` → 8 modules + 7 specs analyzed OK, **6,661 / 0**
  (new `RlpsRelayCore.spec` 11b: `suspend`); `scripts/check_roblox.sh` OK; `python3 tests/e2e/run_e2e.py` → **35 / 35**
  checks (32 before + E2E-28, E2E-29, E2E-30; report `docs/testing/evidence/e2e-report.json`).
- **Measured**: E2E-28 Alice received **0 bytes** while she had hidden the screen (Bob's TV followed a desktop change);
  E2E-29 Bob's forged `moderate` request ignored, both TVs dropped their pixels, **0 HTTP polls** in 2 s while hidden,
  exact picture after showing; shown while sharing was off → "Screen sharing is off" after **0.66 s**; E2E-30 one
  creation attempt, message names the owner setting and ID verification; E2E-25 Sharp → `ResampleMode = Pixelated`.
- **Defect found in review and fixed**: showing a hidden screen left the relay `stopped`, so the next poll was an
  idle poll held by the PC for up to `PollWaitMs` (15 s) while sharing was off → the TVs kept "hidden by a
  moderator". Fix: status `connecting` first. **Mutation check**: with that line removed E2E-29 fails (timeout after
  10 s, TVs still "hidden by a moderator"); with it, 0.6 s. Also: an in-flight poll's *error* could have replaced the
  hidden message → `pollOnce` discards any answer once `Hidden` is set.
- **Not verified here**: real Roblox (whether `game.CreatorId` is the owner in Team Create test servers, the buttons
  on phones, `ResamplerMode.Pixelated` look); the official policy pages themselves (help center 403, T-0016).
