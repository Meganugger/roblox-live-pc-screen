@echo off
rem Publishes the local frame service over HTTPS with a Cloudflare quick tunnel (free, no account).
rem The https://<random>.trycloudflare.com URL changes every time this starts: put it into the FrameServiceUrl
rem attribute of ServerScriptService.Rlps.RlpsServer (see docs\deployment\INSTALL.md for stable-URL options).
title RLPS-tunnel
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo cloudflared was not found. Install it with:
  echo     winget install --id Cloudflare.cloudflared
  echo then close this window and run start-tunnel.bat again.
  pause
  exit /b 1
)
echo Forwarding https://*.trycloudflare.com  -^>  http://127.0.0.1:8787  (only /v1/frames answers, token required)
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8787
pause
