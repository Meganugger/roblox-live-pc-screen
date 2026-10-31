# SECURITY.md — Privacy and security model

The system transmits the owner's real desktop, so the design starts from one rule: **pixels exist only while the owner
has explicitly pressed Start, only in memory, and only reach Roblox servers that present the owner's token.**

## Trust boundaries

| Zone | Holds | Trusts |
| --- | --- | --- |
| Owner's PC: RLPS app (`desktop/rlps/`) | the token, the current frames (RAM only) | nothing outside the PC; listens on 127.0.0.1 only |
| Tunnel (cloudflared / Tailscale) | TLS termination, forwards to 127.0.0.1:8787 | operated by the provider the owner chose |
| Roblox game server (`RlpsServer`) | the token as a non-printable `Secret` (server-only, domain-bound) | the frame service, after validating every byte |
| Roblox clients (`RlpsClient`) | decoded frames while sharing | nothing: they never see the token and cannot make HTTP requests |

## The 20 mandatory safeguards (`PROJECT_SPEC.md` §8) → code → evidence

| # | Safeguard | Enforced by | Evidence |
| --- | --- | --- | --- |
| 1 | No silent start | `SharingController.start` is only called by the Start button, the console `start` command or the explicit `--start` flag (`app.py`); the app starts *not* sharing | `test_app.py`; E2E-01 (TV shows "sharing is off" and the service holds no frame before Start) |
| 2 | Explicit user action | same as 1 | same |
| 3 | Visible active-sharing indicator | Tk window turns red "● SHARING YOUR SCREEN", title "● SHARING — RLPS", forced always-on-top while sharing; console prints a banner; on Roblox the TV shows a red ● LIVE badge | ● LIVE badge: E2E-03 (`badge_visible`). Tk window: code review only — no display with Tk in the sandbox (**not executed**) |
| 4 | Immediate stop | `FrameStore.stop` drops every frame and wakes all held polls → STOPPED; the capture thread never publishes after stop; clients `reset()` and destroy the EditableImage | `test_server.py::test_stop_wakes_waiters_and_drops_frames`; E2E-13 (both TVs off in 0.2 s, no frames left) |
| 5 | No webcam / microphone | no such code; dependencies are `numpy`, `zstandard`, `mss` (screen only) | `desktop/requirements.txt` |
| 6 | No keylogging / hidden surveillance | no input hooks; capture only while the indicator is red | code review |
| 7–10 | No remote mouse, keyboard, command execution or general remote desktop | the frame service has exactly one route, `GET /v1/frames`; request bodies are rejected; no other method or path | `test_server.py::test_routes_methods_and_params` |
| 11 | No stored captures | frames live in an 8-frame RAM ring, cleared on stop; nothing is written to disk (only the token config); `.gitignore` excludes `captures/` | code review; E2E-13 |
| 12 | No undisclosed endpoints | the desktop app makes **no outbound connections**; the Roblox server requests only `FrameServiceUrl` (owner-set attribute, must be `https://`) and the secret only attaches to its domain | `RlpsServer.server.luau` `pollOnce`; F-0011 |
| 13 | No credentials in client-visible code | token only in `%APPDATA%\rlps\config.json` and in the Roblox secrets store; `GetSecret` is server-only; clients receive frames, never the token | E2E-15 (wrong token → client gets no image, no pixel bytes) |
| 14 | Authenticated endpoint | `Authorization: Bearer`, `hmac.compare_digest`; token ≥ 24 chars (`secrets.token_urlsafe(32)` = 43) | `test_server.py::test_auth_required`, `test_short_token_refused` |
| 15 | Validation + rate limits | strict query parser (unknown/repeated/oversized params → 400); token buckets 20/s (ok) and 0.5/s (failed auth); ≤ 8 concurrent polls; long-poll ≤ 25 s; both decoders validate every header, length, index, tile mode, DCT quality, COPY source rectangle and zstd content size before writing a pixel; bundles and response sizes bounded; client acks type-checked and bounded on the server | `test_server.py`, `test_hybrid.py`, Luau specs (5,984 checks), `test_codec.py` |
| 16 | Controls restricted to authorized users | sharing is controlled only on the PC; no in-game control surface; optional `ViewerUserIds` allowlist enforced by the server for fan-out *and* sync | E2E-17 (non-listed player: "not authorized", no pixel data) |
| 17 | No access to local files | no file routes; the service never reads files | code review |
| 18 | No generic proxy | the Roblox server builds one URL shape from the owner's attribute; players cannot influence it (the only client→server message is `"sync"`, rate-limited) | `RlpsServer.server.luau` |
| 19 | Reliable cleanup | `controller.stop()` + `service.close()` in `finally`; capture thread joins; clients destroy EditableImages on STOPPED; a crash of the capture loop stops sharing | `test_app.py`, E2E-13, E2E-14 |
| 20 | Config protected, secrets out of git | config created with mode 0600 (POSIX; per-user `%APPDATA%` on Windows); request logging never includes headers; `.gitignore` excludes configs and `.env` | `test_app.py` (0600 on POSIX) |

## Residual risks the owner accepts by sharing

* **Everything on the shared monitor is visible to every authorized viewer.** Close private windows or share a region /
  second monitor. Notifications that pop up are captured too.
* **Binary bodies**: used only after `/v1/probe` (authenticated, fixed content) proved bytes arrive unchanged; any body
  that fails to parse switches the server back to base64 for good. No new route exposes anything else.
* **The tunnel URL is public.** Without the token it only returns 401 (rate-limited); a leaked token lets anyone read
  the frames while sharing is on → rotate it (`--rotate-token`) and update the Roblox secret.
* **Tunnel provider**: TLS terminates at Cloudflare/Tailscale, which can technically see the (compressed) frames.
  Use a named tunnel on infrastructure you trust if that matters.
* **Roblox**: frames pass through Roblox game servers and clients; Roblox moderation rules apply to what you show
  (Terms of Use / Community Standards — T-0016: the official pages could not be fetched from the agent sandbox, the owner
  must review them).
