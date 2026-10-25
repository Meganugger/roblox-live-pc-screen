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
