@echo off
rem Double-click to start Kira. Needs Python 3.9+ on PATH (only to bootstrap; the
rem engine then uses its own .venv with Python 3.12).
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run_kira.py %*
  goto end
)

where python >nul 2>nul
if %errorlevel%==0 (
  python run_kira.py %*
  goto end
)

echo [kira] ERROR: no Python found on PATH. Install Python 3.12 from python.org,
echo        tick "Add to PATH", then double-click this file again.
pause

:end
endlocal
