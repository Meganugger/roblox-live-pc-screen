# PR #4 explainer: what the forums taught us, and the off switch they asked for

This PR has two halves:
- **research**: what Reddit, the Roblox Developer Forum and similar public projects say about streaming a screen
  into Roblox ([`docs/research/FORUM_FINDINGS.md`](../research/FORUM_FINDINGS.md));
- **changes** that follow from it: an in-game **moderator kill switch**, a **per-player Hide**, a clear message when
  the experience may not use EditableImage, **Sharp** pixels in full screen, and Roblox policy guidance in the docs.

## Context

### For newcomers

The owner's PC captures the desktop, encodes it into tiles and serves them over an authenticated HTTPS tunnel. One
Roblox game server polls that service (`RlpsServer`), checks the chain of frames (`RlpsRelayCore`), plays the frames
out at their capture spacing and fans them out to every player (`RlpsFanout`). Each client decodes the frames and
writes the pixels into an **EditableImage** on the TV (`RlpsClient`).

Until this PR, every control lived on the PC. Start and Stop happen there, and a visible indicator shows that sharing
is on. Inside the game nobody could do anything about what the TV showed, except leave.

> **Key concept: withholding vs. controlling.** A game control that *changes* what the PC shares would be a remote
> control surface into the owner's computer (SECURITY row 18 forbids it). A control that only *withholds* the picture
> (stops showing it, stops fetching it) cannot reach the PC at all. Everything in this PR is withholding.

### What the forums say (short version)

| Topic | What developers report | Where this project stands |
| --- | --- | --- |
| Throughput | almost everyone is stuck at ~8 fps: one HTTP request per frame, 500 requests per minute | bundles of frames per poll, tile deltas, COPY tiles: 30 fps at 1024×576 |
| WebSockets | wanted, but **Studio-only** (official); live games block them | long-poll stays the right transport |
| Drawing | Parts / Frames per pixel collapse; EditableImage works if written **once per frame** | one image, dirty rectangles, once per Heartbeat |
| Moderation | the most discussed topic: games taken down, code kept private "because people could show inappropriate images" | **new**: kill switch, per-player hide, policy guidance |
| ID verification | EditableImage needs a **13+ ID-verified owner** (official); creation succeeds anyway, only writes fail | **new**: one-pixel probe and a clear message |
| Audio | the most requested missing feature; Roblox has no raw-sample audio API | designed (T-0028), not built; a policy question first |

The official piece that shaped the changes is Roblox's EditableImage announcement (DevForum 3267293, Trust and
Safety). Experiences that show **unmoderated 2D content** must declare it in the Content Labels questionnaire, and
become *Moderate (13+)*. Roblox also advises making such content **attributable and removable**. A shared desktop is
exactly unmoderated 2D content. "Removable" is what this project lacked inside the game.

## Intuition

### The kill switch is a valve before the relay

Picture the server's pipeline as a series of pipes:

```
PC ──poll──▶ relay (chain check) ──▶ playout queue ──▶ fan-out ──▶ clients (EditableImage)
```

Hiding closes the valve at the very start and drains everything downstream:

| Step | What `Hidden = true` does | Why |
| --- | --- | --- |
| poll loop | stops polling (checks every 0.5 s) | nothing more leaves the owner's PC |
| an in-flight poll | its answer — frames *or* an error — is discarded | a long-poll can return up to 15 s later |
| playout queue | cleared | frames already fetched must not appear |
| relay | `suspend`: chain forgotten, status `stopped` with "hidden by a moderator" | the next fetch must start from a keyframe |
| fan-out | the `stopped` status clears its played history | a player joining now gets no old picture |
| clients | `stopped` → decoder reset, EditableImage destroyed | no pixel of the screen stays in memory |

Example: Alice (a moderator) presses ⛔ at t = 0 while Bob watches. At t ≈ 0.1 s both TVs say "Screen sharing is off
(hidden by a moderator)" and both EditableImages are gone. For the next 2 s the server makes **0** HTTP requests
(E2E-29 measures exactly this).

Showing again first sets the status to `connecting`, then polls for a keyframe. That order matters (see *Code*).

### Per-player hide: tell the server to forget you

Hiding the picture only locally would still cost the player bandwidth and decode time. So the client sends `leave`
and the server simply forgets that viewer (`fan:remove`). Showing again is an ordinary `sync`, like joining late. In
E2E-28, Alice received **0 bytes** while hidden, even though Bob's TV kept updating.

### The probe: test the write, not the creation

In an experience without *Allow Mesh / Image APIs*, `AssetService:CreateEditableImage` **succeeds**, and every
`WritePixelsBuffer` fails. bruvie-fr's video player found this the hard way. So the client writes one transparent
pixel right after creating the image. If that fails, the TV says what to do and the client waits 30 s before trying
again, instead of failing on every frame forever.

## Code

### Server (`roblox/src/server/RlpsServer.server.luau`)

Two new attributes, `ModeratorUserIds` and `Hidden`. Moderators are the listed UserIds plus the owner of a user-owned
experience. The check runs on the server; the replicated `RlpsModerator` player attribute only decides whether the
client draws the button.

```lua
local function isModerator(player: Player): boolean
	if game.CreatorType == Enum.CreatorType.User and game.CreatorId > 0 and player.UserId == game.CreatorId then
		return true
	end
	for id in string.gmatch(tostring(attr("ModeratorUserIds", "")), "%d+") do
		if tonumber(id) == player.UserId then
			return true
		end
	end
	return false
end
```

Applying `Hidden` (also triggered by setting the attribute from the server console):

```lua
local function applyHidden()
	local hidden = isHidden()
	frames:SetAttribute("Hidden", hidden)
	if hidden then
		table.clear(playout)
		lastDue = 0
		broadcastNow(relay:suspend(HIDDEN_DETAIL))
	elseif relay.status == "stopped" and relay.detail == HIDDEN_DETAIL then
		setServerStatus("connecting", nil)
	end
end
```

> **Edge case: showing again while sharing is off.** After `suspend`, the relay's status is `stopped`, and a stopped
> relay polls with `idle=1`: the PC holds such a poll for up to `PollWaitMs` (15 s) until Start. Without the
> `connecting` step, the TVs kept saying "hidden by a moderator" for up to 15 s after the moderator had shown the
> screen again. Found in review; E2E-29 now covers it. With the `connecting` line removed, the test times out (the TVs
> still show the moderator message after 10 s). With it, "Screen sharing is off" appears after 0.6 s.

Client messages gain two kinds, both bounded and type-checked:

```lua
elseif kind == "leave" then
	fan:remove(player)
elseif kind == "moderate" and (a == "hide" or a == "show") then
	if isModerator(player) and isHidden() ~= (a == "hide") then
		warn(string.format("[RLPS] screen %s for everyone by moderator %s (%d)", ...))
		script:SetAttribute("Hidden", a == "hide")
	end
end
```

The poll loop skips polling while hidden. `pollOnce` drops whatever an in-flight request returns once `Hidden` is set.

### Relay (`RlpsRelayCore.luau`)

```lua
function RelayCore.suspend(self: Relay, detail: string): { Message }
	clearChain(self)
	local out: { Message } = {}
	setStatus(self, out, "stopped", detail)
	return out
end
```

### Client (`RlpsClient.client.luau`)

- **Hide (H)**: drops the queue, the decoder state and the image, sends `leave`, and ignores every non-status message
  while hidden. Showing again resets the processed-byte counter (the server counts from zero for a new viewer) and
  sends `sync`.
- **Moderator panel**: a separate `ScreenGui` with **⛔ Hide screen for everyone** / **▶ Show screen for everyone**,
  shown to moderators wherever they are in the game (a kill switch must not depend on walking to the TV).
- **Probe**: one `WritePixelsBuffer` of 1×1 after `CreateEditableImage`. On failure the TV shows
  "the owner must enable Allow Mesh / Image APIs (Game Settings > Security; needs a 13+ ID-verified owner)".
- **Sharp**: the full-screen overlay toggles `ResampleMode` between `Default` and `Pixelated`. When the picture is
  enlarged, text stays crisp instead of being smoothed.
- A `stopped` status with a reason now shows it: "Screen sharing is off (hidden by a moderator)".

### Emulator and tests (`tests/e2e/`)

The Lune emulator learned what the new code touches: `game.CreatorId` / `CreatorType`, player attributes replicated
from server to client, `PlayerAdded`, `ResamplerMode`, key H, a mode where EditableImage writes fail
(`RLPS_EMU_IMAGE_API_DISABLED`), and a command to fire forged client messages (`fire-<player>-modhide`).

### Documentation

INSTALL C.1 (ID verification) and the new C.1b (Content Labels, private audiences, moderators, personal information);
TROUBLESHOOTING (the two new TV messages, tunnel latency); SECURITY (row 16, policy); D-0012; F-0041…F-0048;
S-0040…S-0050; KI-0010 (a Roblox rendering bug above ~3.7 MB of rewrites per frame; we stay at 2.36 MB on keyframes).

## Verification

- **Luau specs** (`RlpsRelayCore.spec` 11b): `suspend` reports `stopped` with the reason, forgets the chain (next poll
  asks for a keyframe), is silent the second time, and a keyframe afterwards restarts the stream. Total 6,661 / 0.
- **Live pipeline test** (real Xvfb capture → real frame service → the unmodified Roblox scripts under emulation):
  - **E2E-28**: Alice hides the screen; her picture and pixels are dropped; she receives 0 bytes while Bob's TV
    follows a desktop change; showing again gives her the exact current picture.
  - **E2E-29**: only Alice (listed) gets the moderator button; Bob's forged `moderate` request changes nothing; Alice
    hides it → both TVs drop their pixels, **0 polls** in 2 s; she shows it → exact picture; hidden again, the owner
    stops sharing, she shows it → "Screen sharing is off" after **0.6 s**; Start → exact picture.
  - **E2E-30** (scenario `imageapi`): creation succeeds, writes fail → the TV explains the owner setting and ID
    verification; at most one more creation attempt in the next 2 s.
  - **E2E-25** now also presses Sharp (`ResampleMode` becomes `Pixelated`).
- Full suite: ruff clean, Python 93 passed + 2 Windows-only, Luau 6,661 / 0, Rojo build + luau-lsp strict OK, live
  pipeline 35 / 35 checks (TR-0016). CI results are recorded in `TEST_RESULTS.md`.
- **Not verified here**: real Roblox servers and clients. In particular, whether `game.CreatorId` is the owner in
  Team Create test servers, and how the buttons look on phones.

### Manual QA

1. In Studio, set `RlpsServer` ⟩ `ModeratorUserIds` to your UserId and play with two test players (Test ⟩ Clients and
   Servers ⟩ 2 players).
2. Player 1 sees **⛔ Hide screen for everyone** at the top; player 2 does not. Press it: both TVs say "Screen sharing
   is off (hidden by a moderator)"; the server Output shows `[RLPS] screen hidden for everyone by moderator …`;
   `RlpsServer.Hidden` is `true`.
3. Press **▶ Show screen for everyone**: both TVs show the desktop again within about a second.
4. Hide again, press Stop on the PC, show again: the TVs say "Screen sharing is off" right away. Start: the picture
   returns.
5. Player 2 walks to the TV and presses **H**: "You hid the screen". Press **H** again: the picture returns.
6. Open full screen (F) and press **Sharp** while small text is shown: the letters get hard pixel edges.
7. In a test place with *Allow Mesh / Image APIs* off (published game), the TV shows the owner-setting message.

## Alternatives

### A. A Frame-grid fallback for owners without ID verification

bruvie-fr draws up to 192×108 `Frame`s when EditableImage is unavailable.

| Pros | Cons |
| --- | --- |
| Works for owners who cannot or will not ID-verify | Roblox gates EditableImage behind ID verification *because* it shows unmoderated imagery; a renderer built to bypass that gate defeats the safety measure (D-0012) |
| No dependency on the Mesh / Image API switch | 20,000 GUI objects, coarse picture, heavy client CPU |

### B. Moderation by allowlisting viewers only (no kill switch)

| Pros | Cons |
| --- | --- |
| Already exists (`ViewerUserIds`); no new code | Nobody in the game can react to something unwanted that appears on screen |
| Simplest trust model | Doesn't meet Roblox's "removable" guidance for public or friends-only servers |

## People to talk to

- **Sivalmagic** (GitHub `Meganugger`), the owner, wrote parts of `RlpsServer`, `RlpsRelayCore` and `RlpsClient`
  before session 28. They know who will moderate their game (`ModeratorUserIds`), whether the experience is user- or
  group-owned (group owners must list themselves), and how they answer the Content Labels questionnaire.
- Every other commit on these files comes from AI sessions; no other human has touched them.

## Quiz

<details><summary>1. A moderator presses ⛔ while a 15-second long-poll is in flight. What happens to that poll's answer?</summary>

- A. Its frames are shown once, then the screen goes off.
- B. It is discarded, frames or error alike, because `pollOnce` checks `Hidden` right after the request returns.
- C. The poll is cancelled on the PC.

**Answer: B.** Roblox cannot cancel an in-flight `RequestAsync` (C). Showing its frames (A) would undo the kill
switch, and showing its error would replace the "hidden by a moderator" message.
</details>

<details><summary>2. Why does a player's Hide send <code>leave</code> to the server instead of only hiding the picture?</summary>

- A. So the server stops sending that player data: no bandwidth and no decoding while hidden.
- B. Because EditableImage cannot be hidden.
- C. To hide the screen for everyone.

**Answer: A.** The fan-out forgets the viewer, and E2E-28 measured 0 bytes. Showing again is an ordinary `sync`. It
only affects that player (C is the moderator's switch).
</details>

<details><summary>3. Why does showing the screen again first set the status to <code>connecting</code>?</summary>

- A. To make the TVs blink.
- B. A `stopped` relay polls with `idle=1`, which the PC holds until Start (up to 15 s). Without `connecting`, the
  "hidden by a moderator" text would stay that long when sharing is off.
- C. Because `RlpsFanout` requires it.

**Answer: B.** With `connecting` the next poll is not idle and returns at once, either a keyframe (live) or a stop
container ("Screen sharing is off"). E2E-29 measured 0.6 s.
</details>

<details><summary>4. A published game has <em>Allow Mesh / Image APIs</em> off. What does the client observe, and what does it do?</summary>

- A. `CreateEditableImage` throws; the client retries every frame.
- B. Creation succeeds but the first write fails; the client destroys the image, explains the owner requirement
  (13+, ID-verified) and retries after 30 s.
- C. The TV shows a grey square.

**Answer: B.** This is the behaviour bruvie-fr documented; E2E-30 emulates it.
</details>

<details><summary>5. Why was music through voice chat rejected as the audio path?</summary>

- A. Voice chat has too much latency.
- B. Roblox's voice moderation strikes music (warnings, 5-minute suspensions); a quoted appeal answer calls streaming
  audio a policy violation; voice also needs ≤ 50-player servers and voice-enabled listeners.
- C. The Audio API cannot route a microphone to a part.

**Answer: B.** C is false: the new Audio API can wire an `AudioDeviceInput` to any emitter. Latency (A) was not the
deciding factor.
</details>
