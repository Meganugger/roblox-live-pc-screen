@echo off
rem Opens the RLPS sharing window and the local frame service on http://127.0.0.1:8787.
rem Nothing is captured until you press "Start sharing". Extra arguments are passed on, for example:
rem   start-sharing.bat --profile low        (low | balanced | high)
rem   start-sharing.bat --monitor 2          (see --list-monitors)
rem   start-sharing.bat --window "Notepad"   (one app window; see --list-windows)
rem   start-sharing.bat --tab "YouTube"      (one browser tab's page; pauses on other tabs)
rem   start-sharing.bat --no-gui             (console: start / stop / status / quit)
title RLPS-app
cd /d "%~dp0..\..\desktop" || exit /b 1
if not exist ".venv\Scripts\python.exe" ( echo Run scripts\windows\setup.bat first. & pause & exit /b 1 )
".venv\Scripts\python.exe" -m rlps.app %*
if errorlevel 1 pause
