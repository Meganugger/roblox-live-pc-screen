@echo off
rem Prints the frame-service token (created on first use, stored in %APPDATA%\rlps\config.json). Starts nothing.
cd /d "%~dp0..\..\desktop" || exit /b 1
if not exist ".venv\Scripts\python.exe" ( echo Run scripts\windows\setup.bat first. & pause & exit /b 1 )
".venv\Scripts\python.exe" -m rlps.app --token-only %*
pause
