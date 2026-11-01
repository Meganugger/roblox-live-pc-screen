# PR #5 explainer: why the TV fell behind, and how it now keeps up

The owner reported that the stream "lags way more and has a lot more delay than the previous one". This PR does four
things:
- adds a test that **measures** the delay from the PC's screen to the players' TVs;
- fixes the regression it found;
- removes the delays that were built into the design;
- makes clients spend far less CPU on moving pictures.

## Context

### For newcomers

A frame travels like this:

```
PC: capture → encode (tiles) → ring of frames ──HTTP long-poll via tunnel──▶ Roblox game server
    → relay (chain check) → playout (pacing) → fan-out (per player) ──RemoteEvent──▶ client
    → decode queue (on Heartbeat, time-budgeted) → EditableImage on the TV
```

Every arrow can add delay. Three facts matter for this PR:

1. **Roblox queues instead of dropping.** A reliable RemoteEvent always arrives. If the server sends a player more
   than that player's connection carries, the bytes wait in Roblox's send queue. Developers cite a soft budget of
   about 50 KB/s per player (F-0049). Sending too fast does not lose frames; it **delays** them.
2. **Clients decode interpreted Luau.** Roblox compiles `--!native` scripts to machine code only on servers (S-0039).
   On a client, one 16×16 DCT tile took 0.3 ms to decode, so a full 1024×576 frame of motion took 0.7 s (F-0050).
3. **A half-assembled frame is never drawn.** A frame can span several parts. While its parts are still being
   applied, the picture in memory is a mix of two frames, so the client waits for the last part before writing the
   EditableImage.

> **Key concept — glass-to-glass delay.** The time from a pixel changing on the owner's monitor to the same pixel
> appearing on a player's TV. This is what people experience as "lag". Frame rate and quality are separate questions.

### What was there before

- **Drawing.** PR #3 moved drawing to the end of each Heartbeat, so it happens once per game frame instead of once per
  decoded frame. But the decode loop simply ran until its 10 ms budget was used. With a steady stream it usually
  stopped part-way into the next frame. Drawing was then skipped, because the next frame was half-assembled, and the
  frame that *was* complete never reached the screen.
- **Polls.** After the first new frame, a poll waited another 150 ms (`BatchMs`) to collect more frames.
- **Playout.** The server spread the frames of one response over their original capture spacing, with up to 1 s of
  backlog allowed.
- **Rate control.** The rate reacted when the age of the oldest unacknowledged frame passed 0.35 s. But the base
  delay alone (network, decode, ack interval) is already close to that. The rate started at 1 MB/s, and each
  player's backlog window was 128 KiB or 1 s. Roblox's queue filled before anything backed off.
- **Saved tuning.** The place file stored the defaults as attributes. A new script version therefore kept the old
  numbers.

## Intuition

### Measure first

The painter draws a 16-bit counter as 16 black or white blocks in a corner of the real screen. The emulator reads the
same blocks back from each client's EditableImage after every write and logs when each value first appears. Every
counter value thus gets a delay measured end to end, across the real capture, the real frame service, and the
unmodified Roblox scripts.

The tests use three network models:

| Model | RemoteEvent delay | Player link | Tunnel round trip |
| --- | --- | --- | --- |
| studio | 5 ms | unlimited | 20 ms |
| online | 60 ms | 400 kB/s, queueing | 150 ms |
| weak | as online | as online | as online, plus clients that can decode only 3 ms per game frame |

The first measurement reproduced the report. With two players online, video delay was 1.1–1.3 s at the median and
1.9–2.1 s at p90. PR #2 measured 0.5 s and 1.2 s under the same conditions.

### Stop at a frame boundary

When a frame completes, decoding continues only if **all parts of the next frame are already queued** and less than
half the budget is used. Otherwise the loop stops and the completed frame is drawn in the same Heartbeat. Example
with 30 ms frames and a 10 ms budget:

| Heartbeat | Before | After |
| --- | --- | --- |
| 1 | finishes frame 7, starts frame 8 → no draw | finishes frame 7 → **draws 7** |
| 2 | still inside frame 8 → no draw | starts frame 8 |
| 3 | finishes 8, starts 9 → no draw | finishes frame 8 → **draws 8** |

### Do not wait on purpose

- **Polls** now answer the moment a frame exists (`BatchMs` 0). Frames captured while the next poll is travelling
  still come back together in one response. So the 500 requests/min limit is never reached: about 6.7 polls/s.
- **Playout** is compressed. A response whose frames span 180 ms is replayed in 100 ms (`PlayoutMs`). Motion keeps
  its rhythm, and no frame waits more than 100 ms for its turn.

### Watch the queue, not the age

Each ack yields a delay sample: when the server sent the message, minus when the client finished processing it,
minus how long the ack itself waited (`ageMs`). Over the last 10 s, the smallest sample is the path with **no queue**.
Anything above it is **queueing delay**. The client also reports how long parts waited in its own decode queue
(`waitMs`). That time is a CPU problem, not a network one, so it is subtracted and handled by the frame-rate cap
instead.

Example, one player on a 400 kB/s link:

| Moment | Delay sample | Base | Queueing | Rate decision |
| --- | --- | --- | --- | --- |
| steady, 250 kB/s | 0.09 s | 0.09 s | 0 | grow ×1.12 |
| rate passes the link | 0.25 s | 0.09 s | 0.16 s | ×0.9 |
| a burst | 0.45 s | 0.09 s | 0.36 s (> 3 × 100 ms) | drain: 0.85 × measured delivery rate |

The rate also never grows beyond 1.25 × what players were seen to receive. Otherwise a stream that sat below its
budget during video could burst to the full budget once the picture stops moving and refinement starts, and that
burst would fill the queue.

### Do a quarter of the work for video

In a large moving area (≥ 6 % of the frame), every complete, aligned 2×2 group of moving tiles is sent as **one** DCT
macroblock of the area scaled down to half size (`TILE_MODE_DCT2`). The client decodes one macroblock instead of four
and writes each pixel as a 2×2 square. When the motion stops, the usual lossless refinement makes the picture exact
again.

## Code

### Client — `roblox/src/client/RlpsClient.client.luau`

```lua
if m.kind == "part" and renderPending and core.pendingSeq == 0 then
	-- a frame is complete: draw it this Heartbeat, unless a whole newer frame is already queued
	if os.clock() - started >= budget * 0.5 or not nextFrameQueued() then
		break
	end
elseif os.clock() - started >= budget then
	break
end
```

`nextFrameQueued` reads `partIndex`, `partCount` and `seq` straight from the queued part headers. Acks are sent up to
20 times a second and carry `waitMs` and `ageMs`. Each queued message records its arrival time.

### Server — `RlpsServer.server.luau`, `RlpsFanout.luau`

- `schedule` compresses the playout schedule: `k = min(1, PlayoutMs / span)`.
- In `Fanout`, `noteProcessed` keeps per-viewer delay samples (`baseDelay`, `queueDelay`). `stats()` returns the lower
  medians of network queueing delay, decode wait and delivery rate. Held viewers count, because they are held
  *because* they are queued.
- `control()` is a delay-based AIMD controller, using `TargetQueueMs` 100 and `TargetLagSeconds` 0.6 as a hard limit.
  The decode wait lowers the fps cap.
- If the place carries exactly the four old values (`BatchMs` 150, `StartBytesPerSecond` 1000000, `MinBytesPerSecond`
  100000, `TargetLagSeconds` 0.35), they are replaced for the run, with a warning in the Output.
- The window is 64 KiB or 0.5 s. The replay-versus-keyframe decision keeps a 128 KiB floor, so late joiners still get
  the history.

### Decoder — `RlpsDct.luau`, `RlpsDecoder.luau`, `dct.py`, `codec.py`

- The IDCT skips groups of four zero coefficients with two `readu32` calls. Its second pass visits only the columns
  that are actually used, accumulating into eight locals. All intermediates are exact integers below 2⁵³, so the
  summation order cannot change a pixel: the output is bit-identical to before. The Luau vectors (CRC per frame)
  prove it.
- `TILE_MODE_DCT2 = 3`: validation (the 32×32 area must lie inside the frame), `Dct.decodeTile2x`, and dirty cells
  for 32×32. Python's `upscale2` and `downscale2` mirror these.

### Encoder — `hybrid.py`, `server.py`

- `_groups()` finds complete, aligned 2×2 groups. The DCT path codes singles and groups together in one quality
  search, and the encoder's reconstruction uses the doubled pixels.
- The token bucket is 0.25 s deep (`BURST_S`, previously 0.5 s).

### Tests and emulator

The emulator now models one-way delay, a queueing link per player, and a tunnel round trip (`RLPS_EMU_LATENCY_MS`,
`RLPS_EMU_LINK_BPS`, `RLPS_EMU_HTTP_RTT_MS`), and logs the marker readback (`RLPS_EMU_MARKER`). The painter has a
`clock` command. `run_e2e.py --scenario latency` covers E2E-31 to E2E-34; `--scripts DIR` runs another checkout's
Roblox scripts for comparisons.

## Verification

- **Luau specs** 6,779 / 0:
  - a new DCT2 vector sequence (bit-identical pixels, dirty rectangles);
  - the faster IDCT on every existing DCT vector;
  - Fanout D: base delay, ack age ignored, queueing seen, decode wait separated.
- **Python** 96 passed (+2 Windows-only): DCT2 chosen for large motion and exact after refinement; none for small
  areas or when disabled; DCT2 outside the frame rejected.
- **Live pipeline** E2E-01 to E2E-34, all passing.

Glass-to-glass delay, same harness, sandbox at 2.1 GHz:

| | single change (median) | video median | video p90 | changes shown |
| --- | ---: | ---: | ---: | ---: |
| studio, before (PR #4) | 0.236 s | 0.253 s | 0.279 s | 99 % |
| studio, after | **0.07–0.08 s** | 0.21–0.22 s | 0.25–0.26 s | 99–100 % |
| online, 2 players, before (3 runs) | 0.37 s | 0.56 / 0.75 / 0.99 s | 1.12 / 1.88 / 1.63 s | 71–93 % |
| online, 2 players, after (3 runs) | **0.21 s** | 0.47 / 0.48 / 0.49 s | **0.56 / 0.58 / 0.63 s** | 92–95 % |

DCT tile decode: 0.306 → 0.170 ms. A DCT2 group costs about one tile for four tiles of area.

**Not verified here:** real Roblox clients (CPU speed, the real per-player send budget) and the owner's tunnel.
`QueueMs`, `DecodeWaitMs`, `RateBps` and `FpsCap` on `RlpsServer` show what the controller sees in a real game.

### Manual QA

1. Use the new place from the release ZIP, or set the attributes from INSTALL C.2 in your existing place. The Output
   says "this place has the old tuning" if it still has the old values.
2. Share the screen and open a stopwatch website. Hold a phone camera so that the PC monitor and the Roblox TV are in
   the same picture, and take a photo. The difference between the two stopwatch readings is your glass-to-glass
   delay.
3. Play a video. In the Explorer, `RlpsServer.QueueMs` should mostly stay below about 150 and `LagMs` below about
   400; `RlpsClient.DecodeMsPerFrame` should stay low.
4. Pause the video. The picture becomes sharp within a second or two, and `QueueMs` does not jump.

## Alternatives

### A. Two HTTP polls in flight (pipelining)

| Pros | Cons |
| --- | --- |
| A poll is always waiting at the PC: frames would leave at once instead of waiting up to one round trip | Both polls carry the same `after`, so the service would have to split frames between them |
| Saves on average half a tunnel round trip | Twice the requests: 500/min is reached at the tunnel's round-trip rate |

### B. Decoding on the server with native code

| Pros | Cons |
| --- | --- |
| Native code runs about 5× faster (measured 0.06 vs 0.3 ms per tile) | EditableImage pixels do not replicate: the server would have to send decoded pixels, many times the bytes |
| One decode for everyone | Every player's link would carry raw pixels; with queueing links, the delay would grow |

## People to talk to

- **Sivalmagic** (GitHub `Meganugger`), the owner, wrote the first versions of `RlpsServer`, `RlpsClient` and
  `RlpsRelayCore`. They can measure the real delay with the stopwatch method above, and decide whether lower delay
  (`PlayoutMs`, `TargetQueueMs`) or more quality matters more in their game.
- Every other commit on these files comes from AI sessions.

## Quiz

<details><summary>1. Why did PR #3's single redraw per Heartbeat make the TV fall behind?</summary>

- A. Writing the EditableImage once per Heartbeat is slower than writing it after every frame.
- B. The decode loop often stopped half-way into the next frame; a half-assembled frame is never drawn, so the
  complete one waited.
- C. The server sent fewer frames.

**Answer: B.** Drawing once per Heartbeat is fine (A) as long as each Heartbeat ends on a frame boundary, which is the
fix. The server side (C) was unchanged by PR #3.
</details>

<details><summary>2. A player's acks show 0.09 s delay for a while, then 0.30 s. The client reports <code>waitMs</code> 200. What does the rate control conclude?</summary>

- A. 0.21 s of network queue: cut the rate.
- B. Roughly 0.01 s of network queue: the bytes are not waiting in the network, the client's CPU is; the frame-rate
  cap goes down, the byte rate does not.
- C. Nothing, because 0.30 s is below `TargetLagSeconds`.

**Answer: B.** Queueing = 0.30 − 0.09 = 0.21 s, minus 0.20 s of decode wait. Cutting the byte rate would make moving
content lossier and *more* expensive to decode.
</details>

<details><summary>3. Why is <code>BatchMs</code> 0 safe with the 500 requests/min limit?</summary>

- A. Roblox doesn't count long-polls.
- B. Polls are at least `MinPollInterval` (0.15 s) apart, about 400 per minute, and every response carries all frames
  captured since the previous one.
- C. The frame service caches responses.

**Answer: B.** Batching only made the first frame after a quiet period wait 150 ms longer.
</details>

<details><summary>4. A response holds 6 frames captured over 200 ms. With <code>PlayoutMs</code> 100, when is the newest one forwarded?</summary>

- A. Immediately, together with all the others.
- B. 200 ms after arrival.
- C. 100 ms after arrival; the frames are paced 20 ms apart instead of 40 ms.

**Answer: C.** k = 100/200 = 0.5, so the spacing is halved. A (no pacing) would look like about 6 fps; B was the old
behaviour.
</details>

<details><summary>5. What does a <code>DCT2</code> entry at tile index i draw, and why is it cheaper?</summary>

- A. The tile i at a lower quality.
- B. The 32×32 area of tiles i, i+1, i+tx, i+tx+1, from one 16×16 macroblock with every pixel doubled: one IDCT for
  four tiles, and a quarter of the bytes.
- C. A copy of the previous picture.

**Answer: B.** The three neighbours are not listed. Still content is refined back to exact full-resolution tiles.
</details>
