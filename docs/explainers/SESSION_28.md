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
