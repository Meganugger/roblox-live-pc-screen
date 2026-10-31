# Installation and deployment guide (Windows + Roblox)

This guide takes you from a fresh Windows PC to your desktop showing on the TV in your own published Roblox
experience. Part A–C is the same for testing and for production; Part D is Studio testing; Part E is publishing.
If something fails, see [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

```
your PC                                            Cloudflare / Tailscale            Roblox
┌────────────────────────────┐  http://127.0.0.1   ┌──────────────┐   HTTPS + token   ┌────────────────────────────┐
│ RLPS app (start-sharing)   │◄────────────────────│ tunnel agent │◄──────────────────│ game server: RlpsServer    │
│  capture → frame service   │      :8787          │ (on your PC) │   GET /v1/frames  │  → RemoteEvent → clients   │
└────────────────────────────┘                     └──────────────┘                   │  → EditableImage on the TV │
                                                                                      └────────────────────────────┘
```

Three things must be running on your PC while people watch: the **RLPS app** (with sharing started), the **tunnel**,
and of course the PC itself. Nothing is captured until you press **Start sharing**.

## What you need

| Software | Why | Where |
| --- | --- | --- |
| Windows 10 or 11 | the desktop to share | — |
| Python 3.10+ (64-bit, python.org installer, default options incl. "tcl/tk") | runs the RLPS app | <https://www.python.org/downloads/windows/> — tick **Add python.exe to PATH** |
| `cloudflared` (free, no account) **or** Tailscale (free account, stable URL) | public HTTPS address for the frame service | `winget install --id Cloudflare.cloudflared` / <https://tailscale.com/download> |
| Roblox Studio | open, configure and publish the place | <https://create.roblox.com/> |
| The RLPS files | this repository | release ZIP (`rlps-release-*.zip`) or `git clone` |
| Optional: Rojo 7.7.1 | rebuild the place from source / live sync | <https://github.com/rojo-rbx/rojo/releases/tag/v7.7.1> |

Cost: nothing. Cloudflare quick tunnels and Tailscale Funnel are free; a paid domain is only needed if you want a
Cloudflare *named* tunnel on your own hostname (optional, see A.3).

## A. Desktop side

### A.1 Install

1. Unzip the release (or clone the repository) to a folder without special permissions, e.g. `C:\rlps`.
2. Double-click `scripts\windows\setup.bat`. It creates `desktop\.venv` and installs `numpy`, `zstandard`, `mss`,
   `opencv-python-headless` (`desktop\requirements.txt`) and, optionally, `dxcam` (DXGI Desktop Duplication: faster
   capture that also sees hardware-accelerated video; the app falls back to `mss` without it).

**Recommended PC** (stream encoder at 1024×576 @ 30 fps): a 4-core CPU from the last ~8 years; the encoder needed
< 33 ms per frame on a 2.1 GHz cloud vCPU. Upload bandwidth: the stream adapts, but 2–8 Mbit/s lets moving content
stay sharp. Players' PCs decode the picture in Luau: the frame rate and quality adapt to what most viewers keep up
with; a player with a much slower PC or connection gets fewer pictures instead of slowing everyone down.

### A.2 Create the token

Double-click `scripts\windows\show-token.bat`. On first use it creates a random token (43 characters) in
`%APPDATA%\rlps\config.json` and prints it. This token is the only thing that lets a Roblox server read your frames:

* never paste it into a script, a Roblox attribute, chat or a commit — only into the Roblox **secrets store** (C.3);
* to revoke it: `desktop\.venv\Scripts\python.exe -m rlps.app --rotate-token --token-only` (run inside `desktop\`),
  then update the Roblox secret.

### A.3 Start the app and the tunnel

1. Double-click `scripts\windows\start-sharing.bat`. A small window opens: grey **Not sharing**, buttons
   **Start sharing** / **Stop sharing**, a quality menu, and a status line. The frame service now listens on
   `127.0.0.1:8787` (loopback only). Options: `start-sharing.bat --profile max|high|balanced|low|lossless` (default
   `max` = 1024×576 @ 30 fps), `--max-rate 8` (MB/s cap of the stream), `--backend auto|mss|dxgi`, `--monitor 2`
   (list with `--list-monitors`), `--region left,top,width,height`, `--no-gui` (console). The window's status shows the
   stream budget the Roblox server reports, the DCT quality of the last frame and the encode time.
2. Publish it over HTTPS — pick one:

   **Option 1 — Cloudflare quick tunnel (no account; URL changes every start).** Double-click
   `scripts\windows\start-tunnel.bat`. It prints a line like `https://word-word-word.trycloudflare.com`. Copy that URL.
   Every restart gives a new URL, which you must put into the place (C.2) again.

   **Option 2 — Tailscale Funnel (free account; stable URL).** Install Tailscale, sign in, enable Funnel for your
   tailnet in the admin console, then in a terminal: `tailscale funnel --bg 8787`. Your URL is
   `https://<machine-name>.<tailnet-name>.ts.net` and stays the same. Stop it with `tailscale funnel --https=443 off`.

   **Option 3 — Cloudflare named tunnel on your own domain (stable).** Requires a domain on Cloudflare:
   `cloudflared tunnel login`, `cloudflared tunnel create rlps`,
   `cloudflared tunnel route dns rlps screen.example.com`, then
   `cloudflared tunnel run --url http://127.0.0.1:8787 rlps`.

3. Check the tunnel from any PowerShell window (replace the URL; `curl.exe` ships with Windows):

   ```powershell
   curl.exe -i https://word-word-word.trycloudflare.com/v1/frames
   # expected: HTTP/1.1 401 ... "unauthorized"  (the tunnel works and the token is enforced)
   curl.exe -s -H "Authorization: Bearer <token>" "https://word-word-word.trycloudflare.com/v1/frames?wait=0"
   # expected: a short line of base64 text, e.g. UkxQUwEAAAAAAAA...  (a STOPPED container while not sharing)
   ```

The tunnel exposes only `/v1/frames` (GET, token required, rate-limited); every other path answers 404. See
[`../../SECURITY.md`](../../SECURITY.md).

## B. Get the Roblox place

* **Easiest:** open `RlpsDemo.rbxlx` from the release ZIP (or the `RlpsDemo-place` artifact of a CI run) in Roblox
  Studio (**File ⟩ Open from File**).
* **From source:** `rojo build default.project.json -o RlpsDemo.rbxlx` (Rojo 7.7.1), or `scripts/check_roblox.sh` on
  Linux/macOS (also type-checks every script).
* **Into an existing place:** run `rojo serve` in the repository and connect with the Rojo Studio plugin, or copy the
  objects from `RlpsDemo.rbxlx`: `ReplicatedStorage.Rlps` (3 modules), `ServerScriptService.Rlps` (server script + 5
  modules), `StarterPlayer.StarterPlayerScripts.RlpsClient`, `Workspace.RlpsTV`. Any `BasePart` tagged `RlpsScreen`
  becomes a screen (attribute `RlpsFace` = `Front`/`Back`/… picks the face).

What is in the place: a baseplate, a spawn, and the TV (`Workspace.RlpsTV`: a 16×9-stud screen part tagged
`RlpsScreen` with a bezel and stand, 30 studs in front of the spawn).

## C. Configure the place (once per experience)

### C.1 Security settings — Studio: **File ⟩ Experience Settings ⟩ Security** (if Studio asks you to publish the place
before it lets you change these settings, do E.1 first and come back)

* **Allow HTTP Requests: ON** — the game server polls the frame service.
* **Allow Mesh / Image APIs: ON** — `EditableImage` fails in published games without it. (Same switch on the Creator
  Dashboard: experience ⟩ **Configure ⟩ Settings ⟩ Enable Mesh / Image APIs**.)

### C.2 Frame service URL

Select **ServerScriptService ⟩ Rlps ⟩ RlpsServer**, scroll to **Attributes** in the Properties panel:

| Attribute | Value |
| --- | --- |
| `FrameServiceUrl` | your tunnel URL, e.g. `https://word-word-word.trycloudflare.com` (no trailing path) |
| `SecretName` | `rlps_token` (default; must match the secret's name) |
| `ViewerUserIds` | optional: comma-separated UserIds allowed to see the screen, e.g. `12345678, 87654321`; empty = everyone |
| `MaxBytesPerSecond` | 8000000 — upper bound of the adaptive stream rate (per viewer; every viewer gets the same stream) |
| `StartBytesPerSecond`, `MinBytesPerSecond` | 1000000, 100000 — where the rate starts and how low it may go |
| `TargetLagSeconds` | 0.35 — acceptable delay of the median viewer (the rate follows most viewers; slower ones are held and caught up, never slowing the others) |
| `BatchMs`, `ClientDecodeBudgetMs` | 150, 10 — frames per HTTP response window; decode time per client frame |
| `PollWaitMs`, `MinPollInterval`, `StoppedPollInterval` | leave the defaults (15000, 0.15, 1) |

The script also *writes* read-only diagnostics there while running: `Status`, `StatusDetail`, `Containers`,
`ForwardedBytes`, `Dropped`, `LastError`, `RateBps` (current stream rate), `FpsCap`, `ForwardFps`, `LagMs` (delay of
the median viewer), `MaxLagMs`, `Viewers`, `LaggingViewers` (held or waiting for a keyframe), `BodyMode` (`raw` or
`base64`). Each client's `RlpsClient` script shows `State`, `Seq`,
`DecodeMsPerFrame`, `QueueLength`, `Desyncs`, `LastError` (Explorer while playing, or the F9 console).

### C.3 The token secret

* **For published servers:** Creator Dashboard ⟩ your experience ⟩ **Secrets ⟩ Create Secret**: name `rlps_token`,
  secret = the token from A.2, domain = your tunnel host: `*.trycloudflare.com` (quick tunnels),
  `<machine>.<tailnet>.ts.net` (Tailscale) or `screen.example.com` (named tunnel). Only owners can see secrets; game
  scripts can only attach them to requests for that domain.
* **For Studio playtests:** Studio ⟩ **File ⟩ Experience Settings ⟩ Security ⟩ Local Secrets**: add the same name, value
  and domain. (The live secrets store is not available to local playtests — official docs, F-0011.)

## D. Test in Studio

1. On the PC: app running, tunnel running, **not** sharing yet.
2. Studio: **Test ⟩ Play**. Walk to the TV (straight ahead of the spawn). It shows **"Screen sharing is off"**.
   (Output window: no `[RLPS]` warnings. `RlpsServer` attribute `Status` = `stopped`.)
3. Press **Start sharing** on the PC: the window turns red (**● SHARING YOUR SCREEN**, always on top). Within about a
   second the TV shows your desktop with a red **● LIVE** badge.
4. Move a window, scroll a page, play a video: the TV follows (max profile: up to 1024×576 @ 30 fps; the quality of
   moving content adapts to the bandwidth, and every still part becomes pixel-exact within a few frames — see
   [`../../PERFORMANCE.md`](../../PERFORMANCE.md)). In Studio watch `RlpsServer` attributes `RateBps` and `FpsCap`.
5. Press **Stop sharing** (or Esc in the sharing window): the TV returns to **"Screen sharing is off"** within a fraction of
   a second, and every client discards the picture.
6. Multi-client check: **Test ⟩ Clients and Servers ⟩ 2 players ⟩ Start**: both players see the same picture; a player
   who joins later gets the current picture immediately.

## E. Publish

1. **File ⟩ Publish to Roblox** (new or existing experience). For a private test keep the experience private or
   friends-only (Creator Dashboard ⟩ Configure ⟩ Audience / Access).
2. Make sure C.1 is ON for the *published* experience (Creator Dashboard settings) and that the published secret (C.3)
   exists with the right domain.
3. Join the experience from the Roblox app while the PC app + tunnel run, and repeat D.2–D.5.
4. Quick-tunnel users: when the tunnel URL changes, update `FrameServiceUrl` in Studio and publish again (or switch to
   a stable URL, A.3 options 2/3).

## F. Daily use

1. `start-sharing.bat` and `start-tunnel.bat` (or your stable tunnel).
2. Press **Start sharing** only when you want people to see your screen; **Stop sharing** when done.
3. Close the sharing window to quit (sharing stops first). Emergency: `scripts\windows\stop-all.bat` closes both the
   app and the quick tunnel.

**While sharing, everything visible on the shared monitor is visible to every authorized player** — close password
managers, messages, e-mail and anything personal first, or share a second monitor (`--monitor 2`) or a region
(`--region`). You are responsible for what you show under the Roblox Terms of Use and Community Standards (do not show
other people's personal information or content you have no right to share).

## Local development without Roblox

* Python tests: `cd desktop && python -m pytest -q`.
* Luau specs: `python roblox/tests/run_luau_tests.py --analyze` (needs the Luau CLI on PATH).
* Static Roblox checks: `scripts/check_roblox.sh` (Rojo build + luau-lsp with the Roblox API definitions).
* Full pipeline without Roblox (real capture → frame service → the real Roblox scripts under an engine emulation):
  `python tests/e2e/run_e2e.py` (Linux needs `Xvfb` + `pip install python-xlib`; Windows uses your real desktop; both
  need Lune 0.10.4). See [`../testing/E2E.md`](../testing/E2E.md).
