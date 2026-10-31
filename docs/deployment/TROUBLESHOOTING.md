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

## "cannot create the screen image … published games need Allow Mesh / Image APIs"

* Published game: enable **Allow Mesh / Image APIs** (Studio Experience Settings ⟩ Security, or Creator Dashboard ⟩
  Configure ⟩ Settings ⟩ Enable Mesh / Image APIs). `EditableImage` fails by default in published games.
* "image memory budget exhausted": the device has no editable-image memory left (other EditableImages in the game, or
  a low-end device). Use `--profile low` (320×180) on the PC. The client retries every 5 s.

## Picture is upside down, mirrored or squashed

The pipeline keeps the top-left origin end to end (verified byte-for-byte in E2E-05). If the picture looks wrong, the
part's face orientation is the cause: set `RlpsFace` on the screen part to the face that points at the players, and
keep the screen part's size 16:9 (the image is letterboxed with `ScaleType.Fit`, never stretched).

## Slow or jerky updates

* Expected limits: balanced = 480×270, ≤ 4 captures/s; text and window moves are cheap, but video or games produce
  large deltas and the server deliberately lowers the frame rate to stay within `MaxBytesPerSecond` (48 KB/s by
  default). Full-screen video reaches well under 1 frame/s at that budget — see [`../../PERFORMANCE.md`](../../PERFORMANCE.md).
* Faster: share a smaller region (`--region`), use `--profile low`, or raise `MaxBytesPerSecond` if every viewer has a
  good connection (Roblox's official guidance is to keep remote traffic around 50 KB/s per client).
* The sharing window shows `ms/frame`; above ~200 ms the PC itself is the bottleneck (very large monitors): use a region.

## "Oversized payload" / Dropped counter rising

`Dropped` counts containers the server refused because they did not extend its frame chain (e.g. after a restart of
the app). It asks for a keyframe and recovers; a steadily rising value with a working picture is harmless. Parts are
capped at 32 KiB (decompressed) by the encoder, 256 KiB by both decoders; a container is capped at 4 MiB.

## Works in Studio, not when published

Check, in this order: Creator Dashboard secret (not just the Local Secret) with the right domain; **Enable Mesh / Image
APIs** on the dashboard; Allow HTTP Requests; the tunnel URL in the *published* version of the place (republish after
changing the attribute). Studio playtests run on your PC; published servers run in Roblox's data centres and can only
reach your public HTTPS URL.

## Corrupt frames / "zstd decode failed" / desync

Every part is validated before anything is drawn and the client only draws complete frames, so corruption shows up as
a short freeze, not as garbage. A client that loses the chain asks the server for a re-sync automatically. If it keeps
happening, update both sides to the same release (the wire format is versioned: `docs/PROTOCOL.md`).

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
