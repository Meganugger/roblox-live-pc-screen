@echo off
rem Emergency stop: closes the RLPS sharing app and the tunnel windows started by start-sharing.bat / start-tunnel.bat.
rem Normal way to stop sharing: the "Stop sharing" button (or Esc) in the sharing window - the TV then shows
rem "Screen sharing is off". After a forced stop the TV shows "Screen unavailable" instead; no frames survive either way
rem (they only ever exist in memory).
taskkill /FI "WINDOWTITLE eq RLPS-app*" /T /F >nul 2>nul && echo RLPS app stopped. || echo RLPS app was not running.
taskkill /FI "WINDOWTITLE eq RLPS-tunnel*" /T /F >nul 2>nul && echo Tunnel stopped. || echo Tunnel was not running.
