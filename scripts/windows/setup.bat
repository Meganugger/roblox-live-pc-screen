@echo off
rem RLPS one-time setup: creates desktop\.venv and installs the pinned dependencies (numpy, zstandard, mss).
setlocal
cd /d "%~dp0..\..\desktop" || exit /b 1
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/windows/
  echo and tick "Add python.exe to PATH" ^(the default installer includes Tk, used for the sharing window^).
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 ( pause & exit /b 1 )
echo.
echo Setup complete.
echo   1. scripts\windows\show-token.bat   - prints the token to store as the Roblox secret "rlps_token"
echo   2. scripts\windows\start-tunnel.bat - public HTTPS URL for the frame service
echo   3. scripts\windows\start-sharing.bat - sharing window (press "Start sharing" when you want to share)
pause
