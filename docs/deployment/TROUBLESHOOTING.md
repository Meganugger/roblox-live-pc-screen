# Troubleshooting

Start with two places that tell you what the system thinks is happening:

* **PC:** the status lines of the sharing window (`sharing`, `frames`, `roblox server: last poll … ago`, `served`).
  "never polled" means no Roblox server has reached your PC yet.
* **Roblox:** the attributes of `ServerScriptService.Rlps.RlpsServer` while playing (Studio: select it during a playtest
  in the *Server* view; live: Developer Console F9 ⟩ Server ⟩ Log shows `[RLPS]` warnings): `Status`, `StatusDetail`,
  `LastError`, `Containers` (polls answered), `ForwardedBytes`, `Dropped`.

The TV text tells you which branch below applies.

| TV shows | Meaning |
| --- | --- |
| *Connecting to the shared screen…* | the client has not heard from the server yet (first second after joining) |
| *Screen sharing is off* | the frame service answered: you are not sharing (normal until you press Start) |
| *Waiting for the first frame…* | sharing is on, the first picture is on its way |
| picture + ● LIVE | working |
| *Screen unavailable* + reason | server cannot get frames, or the client cannot draw — the reason is printed |

## TV stays black / shows nothing at all

* No text at all means the client script did not attach a screen: check that `StarterPlayer.StarterPlayerScripts.RlpsClient`
  exists and that the TV part is tagged `RlpsScreen` (or is `Workspace.RlpsTV.Screen`). The text is on the part's
  **Front** face; set the attribute `RlpsFace` on the part if your TV faces the other way.
* You are farther than 300 studs from the screen: the picture is not redrawn far away (frames are still received).

## "Screen unavailable — FrameServiceUrl is not set to an https:// URL"

Set the `FrameServiceUrl` attribute (INSTALL C.2). It must start with `https://`; plain `http://` and `localhost` are
rejected on purpose: a Roblox game server cannot reach your PC's localhost, and Roblox only allows ports 80/443 and
≥ 1024 (except 1194).

## "Screen unavailable — secret 'rlps_token' is not available"

* Studio playtest: add a **Local Secret** (Experience Settings ⟩ Security ⟩ Local Secrets).
* Published: create the secret on the Creator Dashboard (INSTALL C.3). The name must equal the `SecretName` attribute.
* The secret's **domain** must match the tunnel host (`*.trycloudflare.com` for quick tunnels).

## "Screen unavailable — … set the domain of secret 'rlps_token' to …" / "This secret cannot be used for a specified domain"

Roblox refuses to attach the secret to the request because the secret's **domain** does not match the host of
`FrameServiceUrl`. Nothing reached your PC. Fix the secret's domain (the TV and the `RlpsServer` attribute `LastError`
name the host it must allow):

* Enter the **host only**: `*.trycloudflare.com` — not `https://…`, no path, no trailing `/`, no port.
* `trycloudflare.com` without `*.` does **not** match `word-word-word.trycloudflare.com`. Quick-tunnel hosts change on
  every `start-tunnel.bat`, so use the wildcard `*.trycloudflare.com` rather than the exact host.
* Tailscale: `<machine>.<tailnet>.ts.net` (or `*.<tailnet>.ts.net`); named tunnel: your exact host, e.g.
  `screen.example.com`.
* Where: Studio playtests use **File ⟩ Experience Settings ⟩ Security ⟩ Local Secrets**; published servers use the
  **Creator Dashboard ⟩ Secrets** entry. Both need the right domain. Edit the entry (or delete and recreate it), then
  **stop and start the playtest** / start a new server — a running server keeps the secret it read.
* `FrameServiceUrl` must be the same host: `https://word-word-word.trycloudflare.com` with the current tunnel name.

## "Screen unavailable — frame service rejected the token (HTTP 401)"

The Roblox secret differs from the PC token. Run `show-token.bat`, copy the value again into the secret (no spaces, no
quotes). If you rotated the token, the secret must be updated too. Repeated wrong tokens are rate-limited (HTTP 429)
for a few seconds.

## "Screen unavailable — request failed: … HttpError …" / "HTTP 5xx"

| Detail | Cause and fix |
| --- | --- |
| `Http requests are not enabled` | Experience Settings ⟩ Security ⟩ **Allow HTTP Requests** ON |
| `DnsResolve`, `ConnectFail`, `HTTP 502/530` | the tunnel is down or the URL changed: restart `start-tunnel.bat`, put the new URL into `FrameServiceUrl` |
| `HTTP 502` from the tunnel while the tunnel runs | the RLPS app is not running (start `start-sharing.bat`) or listens on another port (`--port`) |
| `TimedOut` | the poll took longer than Roblox's request timeout; the server halves its long-poll wait automatically (warning `long-poll wait lowered`). Lower `PollWaitMs` permanently if it repeats |
| `Number of requests exceeded limit` | another script in your game also uses HttpService; raise `MinPollInterval` (0.2 s = 300 requests/min of the 500/min budget) |
| `HTTP 429` | too many requests or failed logins against the frame service; it recovers by itself |
| `HTTP 503 too many concurrent polls` | more than 8 game servers poll at once (many simultaneous servers of a public game); keep the experience small or private |

The server retries with exponential backoff (2, 4, 8 … 30 s) and the picture comes back on its own after the cause is
fixed (verified in the live pipeline test, E2E-11/12).

## "cannot draw the screen image: the owner must enable Allow Mesh / Image APIs … ID-verified owner"

The experience runs without EditableImage permission: Roblox lets the image be created but refuses every write.
Turn on **Allow Mesh / Image APIs** (INSTALL C.1) — only possible when the experience owner (group owner for a group
experience) is 13+ and ID-verified. The client retries every 30 s, so the TV recovers on its own once it is enabled
(new servers pick up the setting).

## "Screen sharing is off (hidden by a moderator)"

A moderator (`ModeratorUserIds`, or the experience owner) pressed **⛔ Hide screen for everyone**, or `Hidden` was set
on `RlpsServer`. Nothing is pulled from the PC meanwhile. A moderator presses **▶ Show screen for everyone** (top of
their window, anywhere in the game) or you set `Hidden` to false; the picture returns from a fresh keyframe. The server
Output logs who did it.

## "cannot create the screen image … published games need Allow Mesh / Image APIs"

* Published game: enable **Allow Mesh / Image APIs** (Studio Experience Settings ⟩ Security, or Creator Dashboard ⟩
  Configure ⟩ Settings ⟩ Enable Mesh / Image APIs). `EditableImage` fails by default in published games.
* "image memory budget exhausted": the device has no editable-image memory left (other EditableImages in the game, or
  a low-end device). Use `--profile low` (320×180) on the PC. The client retries every 5 s.

## Picture is upside down, mirrored or squashed

The pipeline keeps the top-left origin end to end (verified byte-for-byte in E2E-05). If the picture looks wrong, the
part's face orientation is the cause: set `RlpsFace` on the screen part to the face that points at the players, and
keep the screen part's size 16:9 (the image is letterboxed with `ScaleType.Fit`, never stretched).

## The picture lags behind the desktop

Quick tunnels (`trycloudflare.com`) route through a shared relay and some users report them "slow sometimes". Compare:
the delay in Studio with `FrameServiceUrl` = your tunnel URL vs. the delay with Tailscale Funnel or a named Cloudflare
tunnel (INSTALL A.3). `RlpsServer.LagMs` measures the delay after the Roblox server, not the tunnel hop.

## Slow, blurry or jerky updates

Look at three numbers:

* **`RlpsServer.RateBps`** (bytes/s the stream may use). It grows while most viewers keep up and shrinks when the
  median viewer falls behind (`LagMs`; `MaxLagMs` is the worst viewer). Low and not growing → most viewers' connections
  (or Roblox replication) are the limit. `LaggingViewers` > 0 → that many viewers cannot keep up: each is *held* (its
  backlog stays within about one second of its own speed) and catches up or jumps to the next keyframe — it sees a
  slideshow, the others are unaffected. Raise `MinBytesPerSecond` only if all viewers have fast connections.
* **`RlpsServer.FpsCap`** (frames/s the median viewer decodes). Low → most viewers' PCs are slow to decode
  (`RlpsClient.DecodeMsPerFrame`); moving content (DCT tiles) is the expensive part. Use `--profile high` (768×432).
* **The sharing window's `encode … ms`** — above ~33 ms the PC cannot encode 30 fps at this profile: use `--profile
  high`, a region, or close CPU-heavy programs. `skipped … (over budget)` rising means the budget, not the PC, limits.

Blurry while moving is expected (DCT tiles at the quality the rate allows); still content sharpens to pixel-exact
within a few frames. Text that stays blurry while still → the budget is so low that refinement waits: raise
`StartBytesPerSecond`/`MinBytesPerSecond` or use `--profile lossless` for pure text work.

## `BodyMode` is `base64`

Normal fallback: the probe showed that binary response bodies do not arrive unchanged on this server (or a raw body
once failed to parse). Everything works; the HTTP bodies are 33 % larger.

## "Oversized payload" / Dropped counter rising

`Dropped` counts containers the server refused because they did not extend its frame chain (e.g. after a restart of
the app). It asks for a keyframe and recovers; a steadily rising value with a working picture is harmless. Parts are
capped at 96 KiB (decompressed) by the encoder, 256 KiB by both decoders; a container is capped at 4 MiB, a response
at `max` bytes (≈ 1.5 s of stream).

## Works in Studio, not when published

Check, in this order: Creator Dashboard secret (not just the Local Secret) with the right domain; **Enable Mesh / Image
APIs** on the dashboard; Allow HTTP Requests; the tunnel URL in the *published* version of the place (republish after
changing the attribute). Studio playtests run on your PC; published servers run in Roblox's data centres and can only
reach your public HTTPS URL.

## Corrupt frames / "zstd decode failed" / desync

Every part is validated before anything is drawn and the client only draws complete frames, so corruption shows up as
a short freeze, not as garbage. A client that loses the chain asks the server for a re-sync automatically. If it keeps
happening, update both sides to the same release (the wire format is versioned: `docs/PROTOCOL.md`).

## Sharing a window or tab: "paused", "minimized", black picture

* **"paused: the window no longer shows '…'"** (status line of the sharing window) — tab mode: the browser shows
  another tab, or the page changed its title. Switch back, or share with a shorter title text (`--tab YouTube`).
* **"the shared window is minimized"** — restore it; the TV keeps the last picture meanwhile.
* **"no window matches '…'"** — `python -m rlps.app --list-windows` lists what can be shared (title, process, hwnd).
* **Black picture / other windows show up in it** — the app renders black for window capture (exclusive full-screen
  games, DRM video); the app falls back to the window's screen area. Share the monitor instead, or turn off hardware
  acceleration in that app.

## Viewer modes (full screen / cinema / mini player)

* **No buttons near the TV** — the picture must be live, the player within ~45 studs of a screen, and `ViewerModes`
  (RlpsServer attribute) not empty. The keys F / C / M do nothing while typing in chat.
* **Cinema camera stays after leaving** — it returns to the default camera (`CameraType` Custom, subject = the
  character); a custom camera script of your game may need to re-apply its own settings when `ViewMode` (RlpsClient
  attribute) goes back to `none`.

## The capture app stopped / crashed

* Closing the window or Ctrl+C stops sharing first. After a crash nothing is left behind (frames only exist in memory);
  the TV shows "Screen unavailable" until the app runs again.
* `cannot listen on 127.0.0.1:8787` — the app is already running (look for its window) or another program uses the
  port: start with `--port 8788` and point the tunnel at the same port.
* `capture interrupted: …` in the status line — the desktop was locked, a UAC prompt or a full-screen exclusive game
  took the screen; capture resumes automatically (backoff up to 5 s).

## Server overload

One game server polls once for all of its players and forwards the same compressed parts to each viewer, so server CPU
is small; outbound traffic grows linearly with viewers (`viewers × stream rate`). Restrict viewers with `ViewerUserIds`
or lower `MaxBytesPerSecond` for large audiences.
