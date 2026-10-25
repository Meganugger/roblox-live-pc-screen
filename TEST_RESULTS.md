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
