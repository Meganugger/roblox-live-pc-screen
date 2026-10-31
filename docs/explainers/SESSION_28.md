# Session 28 explainer: going from code that is written to code that is proven

This explains the changes in [PR #1](https://github.com/Meganugger/roblox-live-pc-screen/pull/1) (branch
`claude/rlps-session-28-finish`). It assumes you have never seen the project; skip the first section if you have.

## Context

### The problem, for newcomers

The goal is a TV inside a Roblox world that shows the owner's real Windows desktop. Roblox makes this harder than it
sounds, because a Roblox game cannot see anything outside itself:

- Roblox scripts cannot capture a desktop, so a normal Windows program has to do it.
- In a published game, only the **game server** can make HTTP requests (500 per minute), and it cannot reach the
  owner's `localhost`. The PC therefore needs a public HTTPS address, which a tunnel (Cloudflare or Tailscale) provides.
- The picture is drawn with an `EditableImage` (raw RGBA pixels). Changes to it **do not replicate**, so every
  player's client has to rebuild the picture from data the server sends over a `RemoteEvent`.

> **The pipeline in one line.** The Windows app captures the screen, shrinks it, cuts it into 16×16 tiles and keeps
> only the changed tiles, compressed with zstd. Those tiles are served from one long-poll HTTP endpoint behind a
> tunnel. **One** poll loop per Roblox server fetches them and fans the same compressed parts out to every player.
> Each client decodes them and writes one `EditableImage` on the TV.

### Where the project stood before this session

Twenty-seven earlier sessions wrote every component and tested the pieces one at a time:

- Python codec and frame service: unit tests.
- Luau decoder: cross-checked against the Python codec on 5,344 cases.
- Roblox scripts: static type checks only.

What was missing was proof that the pieces work **together**. The two scripts that matter most,
`RlpsServer.server.luau` and `RlpsClient.client.luau`, had never run at all, because the sandbox has neither Windows
nor Roblox.

## Intuition

The central idea: **if you cannot run Roblox, run the real scripts on a small fake Roblox, and feed them real pixels.**

Here is how that works:

1. A test program paints known shapes on a real (virtual) screen, for example a red rectangle at (100, 100).
2. The real capture code grabs that screen, and the real frame service serves it over HTTP.
3. The unmodified Roblox scripts run under Lune with an emulated engine: the server plus two players, Alice and Bob.
4. The test reads the pixels inside Alice's emulated `EditableImage` and checks that they are **byte-for-byte
   identical** to the frame the service captured.
5. It then moves the rectangle, kills the service, restarts it, stops sharing, and checks what each TV says at each
   step.

> **Why byte-for-byte?** A visual "looks right" check lets subtle errors through, such as a wrong row offset or a
> missed dirty rectangle. A SHA-256 over 480×270×4 bytes proves that every tile, every delta and every partial redraw
> landed exactly where it should.

Running the real system exposed problems the unit tests could not see. Two of them shaped the design:

- **Start took 3 seconds.** While sharing was off, the Roblox server asked "anything yet?" every 3 s. The fix: when
  the server already knows sharing is off, it sends `idle=1`, and the PC holds that request open until the owner
  presses Start. The time from Start to picture dropped to 1.0 s.
- **The first version of that fix broke Stop.** It held *every* request while sharing was off, so a request arriving
  just after Stop waited 15 s before it learned about the stop. The test measured 15.25 s and failed. The rule now is
  that only a poller that already shows "off" may be held; every other poller learns about a stop immediately
  (0.2 s).

The third idea is **pacing by coalescing**. Suppose a video plays, each changed frame is 86 KB, and the budget is
48 KB/s per player. After forwarding a frame, the server waits 86 / 48 ≈ 1.8 s before asking again. The PC computes
each delta against *the last frame the server received*, so the next answer covers everything that changed in the
meantime. Nothing queues up anywhere; busy content simply gets a lower frame rate.

## Code

### 1. The live pipeline test (`tests/e2e/`)

- `painter.py` draws the test scenes. On Linux it draws on Xvfb through python-xlib; on Windows it draws on the real
  desktop through Tk. It also reports the real screen size.
- `roblox_emulator.luau` (Lune) builds one DataModel per peer from `default.project.json`, so script placement is
  tested too. It emulates only what the scripts use:
  - Instances and attributes
  - ordered, copied `RemoteEvent` delivery
  - `HttpService:RequestAsync` through real HTTP, and server-only secrets
  - `EncodingService` zstd and base64
  - an `EditableImage` pixel store with bounds checks

  Unknown members raise errors the way the real engine does.
- `run_e2e.py` drives the scenarios and asserts 21 checks (E2E-01…17).

### 2. Product changes the test led to

```python
# desktop/rlps/server.py: a poll that arrives while sharing is off and says idle=1 waits for Start
hold_while_stopped = idle and not self.live  # never delays news of a stop: only already-idle pollers
```

```lua
-- roblox/src/server/RlpsServer.server.luau: pacing
if forwarded > 0 then
	local rate = math.max(1000, tonumber(attr("MaxBytesPerSecond", 48000)) or 48000)
	return math.min(10, forwarded / rate)
end
```

Other fixes:

- The client now checks the zstd declared size (`GetDecompressedBufferSize`) before decompressing.
- The client looks up `RlpsFace` safely. Indexing `Enum.NormalId` with an unknown name raises an error.
- The frame service treats a poller that hangs up as normal. On Windows the hang-up shows up on the read side, which
  only the Windows CI run revealed.

### 3. Delivery

- **Windows scripts** in `scripts/windows/*.bat`: setup, show-token, start-sharing, start-tunnel and stop-all. The app
  also gains a `--token-only` option.
- **CI** in `.github/workflows/ci.yml`:
  - Python tests on Linux and Windows
  - Luau specs
  - Rojo build plus luau-lsp
  - the live test on Xvfb **and on a real Windows desktop**

  Failures are posted as PR comments, because the agent cannot read Actions logs.
- **Docs**:
  - `docs/PROTOCOL.md`: the normative wire format
  - `docs/deployment/INSTALL.md` and `TROUBLESHOOTING.md`
  - `docs/testing/E2E.md`
  - `SECURITY.md`: each of the 20 safeguards mapped to code and evidence
  - `PERFORMANCE.md`: measured numbers
  - `docs/IMPROVED_PROMPT.md`: the rewritten prompt

## Verification

| Level | What ran | Result |
| --- | --- | --- |
| Unit (Python) | `cd desktop && python -m pytest -q` | 66 passed, 327 subtests |
| Cross-language (Luau) | `python roblox/tests/run_luau_tests.py --analyze` | 5,664 passed / 0 failed |
| Static Roblox checks | `scripts/check_roblox.sh` (Rojo + luau-lsp with Roblox API types) | OK |
| Live pipeline (sandbox) | `python tests/e2e/run_e2e.py` | 21 / 21 |
| CI on PR #1, head `6033ac1` | 5 jobs, including the live test on `windows-latest` with real GDI capture | all green |
| Roblox Studio / published game | not run (there is no Roblox in the sandbox) | — |

> **Still unproven:** real Roblox network limits, request timeouts, the `EditableImage` memory budget on real
> devices, actual on-screen rendering, Creator Dashboard settings, and the tunnel hop. Only your Studio and published
> tests can prove those.

### Manual QA, step by step (about 20 minutes)

1. On Windows, run `scripts\windows\setup.bat`, then `show-token.bat`, and copy the token it prints.
2. Run `start-sharing.bat`, but do **not** press Start yet.
3. Run `start-tunnel.bat` and copy the `https://….trycloudflare.com` URL. Check that
   `curl.exe -i <URL>/v1/frames` returns **401**.
4. Open `RlpsDemo.rbxlx` (from the ZIP) in Studio.
5. Configure the place:
   - Set `FrameServiceUrl` on `ServerScriptService.Rlps.RlpsServer` to the tunnel URL.
   - Add a Local Secret named `rlps_token`, with the domain `*.trycloudflare.com`.
   - Turn on **Allow HTTP Requests** and **Allow Mesh / Image APIs**.
6. Press Play and walk to the TV. It should say **"Screen sharing is off"**.
7. Press **Start sharing**. Within about 1 s the desktop appears with **● LIVE**. Move a window and check that the
   TV follows.
8. Press **Stop sharing**. The TV says "Screen sharing is off" again.
9. Publish the place, add the secret on the Creator Dashboard, and repeat steps 6–8 in a private server.

## Alternatives

### A. Wait for Roblox Studio tests instead of emulating the engine

| Pros | Cons |
| --- | --- |
| Real engine, real limits, real rendering | Impossible in the agent sandbox; every iteration needs the owner |
| No emulation code to maintain | The five defects found today would have surfaced one at a time, across owner sessions |
| No risk that the emulation is "too kind" | No automated regression protection in CI |

### B. A cloud relay (the PC pushes frames to a hosted server, and Roblox polls the relay)

| Pros | Cons |
| --- | --- |
| Stable URL, no tunnel on the PC | Needs a hosted service: cost, operations, and one more place your screen passes through |
| The PC can sit behind any network | More moving parts, and upload bandwidth is spent even when nobody is watching |
| Game servers would not each poll the PC | The on-demand deltas would have to move to the relay |

## Who to talk to

- **Sivalmagic** (GitHub `Meganugger`): the owner, and author of 48 of the 59 commits (the earlier sessions, pushed
  through the GitHub integration). They know why D-0002, the architecture decision, was made and the history of
  KI-0004 (lost sessions). Ask them to confirm the assumptions about Roblox.
- No other person has committed to these files. The rest of the history comes from AI sessions, so there is nobody
  else with first-hand knowledge.

## Quiz

<details><summary>1. Why does the server send <code>idle=1</code> only when it already shows "stopped"?</summary>

- A. To save bandwidth while the owner is sharing.
- B. Because a held request must never delay news of a stop. A poller that believes sharing is live has to learn about
  a Stop at once.
- C. Because Roblox forbids long-polls while live.

**Answer: B.** The first version held every request while sharing was off. A poll that arrived just after Stop then
waited up to 15 s; the test measured 15.25 s. A is unrelated, because idle polls happen only while nothing is shared.
C is false: live polls are long-polls too.
</details>

<details><summary>2. A video makes every delta about 86 KB, and <code>MaxBytesPerSecond</code> is 48,000. What happens?</summary>

- A. Frames queue on the server and the TV falls further and further behind.
- B. The server drops parts and the client desyncs.
- C. The server waits about 1.8 s before its next poll, and the next delta covers everything that changed in the
  meantime: a lower frame rate, but no queue.

**Answer: C.** Each delta is computed against the last frame the server forwarded, so slower polling merges frames.
A and B are exactly what the design avoids; dropping parts would break the chain rules (`PROTOCOL.md` §4).
</details>

<details><summary>3. What does E2E-05 compare, and why is that stronger than checking that the TV "looks red"?</summary>

- A. A PNG screenshot against a reference image, with some tolerance.
- B. The client's `EditableImage` bytes against `expand_to_rgba` of the newest captured frame, exactly (SHA-256 and the
  full array).
- C. The number of RemoteEvent messages.

**Answer: B.** An exact comparison catches an off-by-one row, a wrong dirty rectangle or a missed tile; sampling a
colour cannot. The colour checks (E2E-06) are added on top, to show the content is the scene that was painted.
</details>

<details><summary>4. Why must every client decode the stream itself, instead of the server building one image?</summary>

- A. `EditableImage` contents do not replicate, so an image built on the server would reach clients as a placeholder.
- B. The server has no zstd.
- C. To hide the token.

**Answer: A** (official docs, F-0005). B is false: `EncodingService` exists on the server too. C is a separate
concern, and the token never leaves the server anyway.
</details>

<details><summary>5. The Windows CI job failed at first while Linux passed. What was the root cause in the product?</summary>

- A. `mss` could not capture the screen on Windows.
- B. Windows reports a hung-up poller as a reset when the server *reads* the next keep-alive request, and the first
  fix only covered the write side.
- C. Lune cannot run on Windows.

**Answer: B.** The handler now ignores `ConnectionError` on both sides. A is disproved by the same run: capture
worked, and E2E-01…16 passed on the real Windows desktop. C is also false: Lune ran there, and the other Windows
failure (a `state.json` race) was in the test harness, not a Lune limitation.
</details>

---

# Part 2 (29th session): maximum quality, and what other projects taught us

## Context

The owner asked for the best possible stream, with no 50 KB/s budget, since the game will have PC requirements. They
also asked whether the other public projects had been checked. Until then only ScreenBlox had been read. Ten more were
studied this time, all at source level (`docs/research/EXISTING_PROJECTS.md`). Three ideas came from them:

- **Several frames per HTTP response.** From Icy-Monster's `FrameGroups` and MahanBig's `since=SEQ`. Roblox allows
  about 8 requests per second, so one frame per request caps the frame rate at about 8 fps.
- **Lossy DCT coding for moving content.** From MahanBig/roblox-screen-stream, published three days before the survey.
  For video-like content it is about 30× smaller than lossless tiles.
- **Time-budgeted `--!native` decoding.** From MahanBig, and luavid measured a 3.4× speed-up.

## Intuition

Each 16×16 tile picks the cheapest way to show what changed:

```
still and exact          -> nothing (0 bytes)
scrolled                 -> COPY dx,dy  (5 bytes: "take the block 9 rows lower in what you already show")
moved, budget allows     -> RAW lossless (1 KiB before zstd)
moved, budget tight      -> DCT at the best quality that fits (770 bytes before zstd, mostly zeros)
stopped moving but lossy -> RAW again with leftover budget  => a still screen ends pixel-exact
```

Two signals set the budget, and they measure different things. A client that falls behind on **bytes** has a slow
network, so the byte rate drops. A client that falls behind on **decode time** has a slow CPU, so the frame rate is
capped. The live test showed why both are needed: lowering only the byte rate never helped a CPU-bound client. DCT
decode cost grows with the number of frames, not with the number of bytes.

> **Why "bit-exact" matters.** The encoder predicts every later frame from *its copy of what the client shows*. If the
> client's DCT decoder differed by a single pixel value, errors would pile up frame after frame. Both decoders
> (`dct.py`, `RlpsDct.luau`) therefore use integer arithmetic, and the tests compare their pixels exactly.

## Code (map)

- `desktop/rlps/dct.py`: the DCT tile codec, with the exact integer specification computed through float64 BLAS (exact
  below 2^53).
- `desktop/rlps/hybrid.py`: tile decisions, quality search on a sample of tiles, FFT scroll detection measured against
  the client's picture (so it cannot drift), and refinement.
- `desktop/rlps/server.py`: encode-once chain ring, bundles, batch window, rate and fps budgets, `/v1/probe`.
- `roblox/src/shared/RlpsDct.luau`, `RlpsDecoder.luau`, `RlpsClientCore.luau`: the Luau decoders.
- `RlpsServer.server.luau`: playout, acks, AIMD rate control, fps cap, lagging viewers, binary-body probe.
- `RlpsClient.client.luau`: decode queue, acks, diagnostics.

## Verification

| Test | Result |
| --- | --- |
| Python | 84 passed |
| Luau specs (pixels identical to Python, including DCT and COPY tiles) | 5,984 passed |
| Live pipeline | 25 / 25 |

New live checks:

- **E2E-18 / E2E-19:** the client showed 48 distinct lossy pictures bit-exactly, then refined to the exact desktop,
  with both raw and base64 bodies.
- **E2E-20:** the rate grew from 0.3 to about 1 MB/s; a 40 KB/s viewer was paused while the other kept going.
- **E2E-21:** scrolling through a non-integer downscale cost less than one keyframe per 15 steps.

## Alternatives

| Alternative | Pros | Cons |
| --- | --- | --- |
| Whole-frame DCT (as in MahanBig) | Simpler encoder; one code path | Text is always blurry; no pixel-exact still picture |
| Closed-loop residual coding on DCT tiles | Fewer bytes for slowly changing video | More Luau work per frame, on the client CPU that already limits the frame rate |

## Quiz (part 2)

<details><summary>6. Why is scrolling detected against the client's picture rather than against the previous capture?</summary>

- A. It is faster.
- B. A sub-pixel scroll (non-integer downscale) gets rounded every frame. Against the previous capture these rounding
  errors add up into visible drift; against what the client shows, each frame corrects the error.
- C. The previous capture is not kept.

**Answer: B.** The first version used the previous capture. With 12 px steps at 0.8× scale, the true shift is 9.6 px
per frame, so rounding to 10 px every frame would drift by several pixels.
</details>

<details><summary>7. A viewer's PC decodes slowly, but its network is fast. Which control reacts?</summary>

- A. The byte rate (AIMD).
- B. The fps cap, computed from the decode time the client reports with its acks.
- C. Nothing: the viewer is paused immediately.

**Answer: B.** Lowering the byte rate barely reduces DCT decode work per frame; only fewer frames do. If the viewer
still falls more than `LagDropSeconds` behind, C happens as a last resort.
</details>

# Part 3 (29th session, continued): one slow viewer must not hold anyone back

## Context

Every Roblox client rebuilds the shared screen itself, so the game server sends each viewer the same stream of frame
parts over a reliable `RemoteEvent`. "Reliable" has a cost that matters here: once a message is fired, it cannot be
taken back. If a viewer's connection delivers 10 KB/s while the stream runs at 1 MB/s, everything the server keeps
sending piles up in front of that viewer. A pile of 1 MB takes 100 s to drain at 10 KB/s, and every later message
waits behind it, including the "sharing stopped" message.

Part 2 added congestion control: clients acknowledged frames, and the server measured how old the oldest
unacknowledged frame of each viewer was. A viewer more than `LagDropSeconds` behind was paused, then re-synced. That
passed the live test on Linux, but the **Windows CI runner failed E2E-20**: the 10 KB/s viewer was never detected, and
the rate never moved. Two flaws combined:

1. A client that has not shown its first picture yet asks for a `sync` every 3 s. Each re-sync restarted that viewer's
   measurement window, and re-sent the whole history to a viewer that was already drowning.
2. Bytes in flight came from one global log that only knew about broadcasts. For a viewer that had not acknowledged
   anything yet, the answer was "0 KB".

> **Key concept — backlog.** For one viewer: bytes sent to it − bytes it has processed. It sits in the network or in
> the client's decode queue. It is the only number that tells how long a new message (Stop, a new frame) will take to
> reach that screen.

## Intuition

Treat each viewer like a TCP connection with a window.

* **Clients count bytes, not frames.** Every ack (and every sync request) carries `processed`, the total bytes of
  parts the client has handled. The server knows how much it sent, so the backlog is exact, even for a client that
  has desynced or not finished its first frame.
* **The window follows the viewer, not the stream.** The window is max(128 KiB, one second of that viewer's measured
  delivery rate). The rate is measured like BBR: bytes processed during a message's flight ÷ flight time, taking the
  maximum over 5 s.
* **Full window → hold, not drop.** A held viewer gets nothing but status messages. Once its backlog is zero, it is
  sent exactly the frames it missed, from the *played history* (last keyframe + later frames, in broadcast order). If
  replaying would cost more than a fresh keyframe, it waits for the next keyframe instead.

A worked example from the spec's network simulation: a 1 MB/s, 30 fps stream, viewer *Fast* at 8 MB/s, viewer *Slow*
at 10 KB/s.

| | Fast | Slow |
| --- | --- | --- |
| frames received | all 1,031 | 4 pictures (a slideshow) |
| times held | 1, while warming up | 3 |
| largest backlog | 363 KiB | 120 KiB → a Stop reaches it within ~12 s |
| measured delivery rate | 1.98 MB/s | 10 KB/s |
| last frame shown | the last one | the last one |

> **Key concept — the median viewer sets the rate.** The AIMD controller uses the *lower median* viewer delay rather
> than the worst. The game has PC requirements: the stream should be as good as most viewers sustain. A minority of
> slow viewers is held and caught up, and one client cannot degrade the picture for everyone by faking slowness.

> **Edge case — asking for a keyframe used to rewind every TV.** With `key=1` the frame service replays its ring from
> the newest keyframe: frames every viewer has already shown. The new `fresh=1` flag keeps the chain going and makes
> the *next* capture a keyframe, even of an unchanged screen. It is ignored if the ring already holds a keyframe newer
> than the poller's position.

## Code (map)

```lua
-- roblox/src/server/RlpsFanout.luau (new, pure Luau): in Fanout.broadcast, for each live viewer
local backlog = v.sent - v.acked
if bytes > 0 and backlog > 0 and backlog + bytes > window(self, v) then
	v.state = "held" -- resumes once it processed everything (Fanout.ack)
else
	sendFrame(self, key, v, m, now)
end
```

- `RlpsFanout.luau`: played history, viewer states (live / held / waiting), BBR-style rate samples, catch-up vs.
  keyframe choice (more than 24 frames, more than 8 MiB, or more than 2 × keyframe + window → wait), sync
  suppression, lower-median stats.
- `RlpsServer.server.luau`: the global forward log, `syncPlayer` and `pendingSync` are gone. Broadcasts go through
  the fan-out. The control loop uses `fan:stats()` and requests keyframes with `relay:requestFreshKeyframe()` (2 s
  cooldown). `LagDropSeconds` is removed; `LagMs` is new. Changes to `ViewerUserIds` now notify the players who were
  removed or added.
- `RlpsClient.client.luau`: counts `processed`. Parts dropped when the queue is cleared count too, otherwise the
  server would wait for them forever. Acks are sent even before the first picture.
- `RlpsRelayCore.luau`: no history any more (the fan-out owns it, in playout order); records carry `keyframe`;
  `pollParams` returns `fresh`.
- `desktop/rlps/server.py`: the `fresh` query parameter.

## Verification

- `roblox/tests/RlpsFanout.spec.luau`, 659 checks:
  - every vector sequence relayed to an early viewer, plus a new late joiner after every step, all CRC-exact;
  - Stop, ack clamping, ignored sync spam, hold + exact catch-up, waiting for a keyframe;
  - a 60 Hz network simulation (above).
- `desktop/tests/test_server.py::test_fresh_continues_the_chain_and_forces_one_new_keyframe`.
- Live test **25/25** locally. In E2E-20 the rate grew to 1.46 MB/s and *stayed* there when the 10 KB/s viewer joined
  (`LaggingViewers` = 1). The fast viewer showed 107 distinct pictures in 14 s, and both ended exact.
- Manual QA, in a published private server: join with one fast client, and a second one on a deliberately slow
  connection (for example a throttled phone hotspot). Studio's *Incoming Replication Lag* setting adds delay only, not
  a bandwidth limit. Watch `RlpsServer.LaggingViewers` rise to 1 and `RateBps` stay high while the fast client stays
  smooth. Then press Stop and time how long the slow client takes to show "Screen sharing is off".

## Alternatives

| Alternative | Pros | Cons |
| --- | --- | --- |
| Lower the rate to the slowest viewer | Everyone sees the same smooth stream | One bad connection ruins the picture for all; a client can degrade it on purpose |
| Simulcast (a second, low-resolution stream for slow viewers) | Slow viewers get smooth motion instead of a slideshow | Twice the encoding on the owner's PC and two chains to relay; kept as a possible extension (KI-0008) |

## Quiz (part 3)

<details><summary>8. Why do clients acknowledge processed bytes rather than the newest frame?</summary>

- A. Bytes are smaller to send.
- B. The server can compute each viewer's exact backlog, even for a client that has not completed a frame or has
  desynced. Frame acks say nothing until a frame completes.
- C. Roblox limits the number of acks.

**Answer: B.** The failing viewer of the Windows run had acknowledged nothing, so a frame-based backlog was "0 KB".
</details>

<details><summary>9. A held viewer drains its backlog. What does it receive next?</summary>

- A. A full re-sync starting with "reset".
- B. Exactly the played frames after the last one it was sent, unless that costs more than a fresh keyframe; then it
  waits for the next keyframe.
- C. Only the newest frame.

**Answer: B.** A is what a `sync` request (join or desync) gets. C is impossible: a delta needs its predecessor.
</details>

<details><summary>10. Why does the server ask for viewers' keyframes with `fresh=1` rather than `key=1`?</summary>

- A. `key=1` is slower.
- B. `key=1` makes the frame service replay its ring from the newest keyframe, which is old frames, so every TV
  briefly rewinds. `fresh=1` continues the chain and makes the next capture a keyframe.
- C. `fresh=1` is smaller.

**Answer: B.** `key=1` remains the right request when the relay's own chain is unknown or broken.
</details>
