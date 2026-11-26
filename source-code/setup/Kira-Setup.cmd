@echo off
rem Double-click this file. It downloads Kira when needed, installs it, and starts it.
setlocal
chcp 65001 >nul
set "HERE=%~dp0"
cd /d "%HERE%"

if not exist "%HERE%setup.ps1" (
  echo [kira] ERROR: setup.ps1 is missing beside this file.
  pause
  exit /b 1
)

where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%HERE%setup.ps1" %*
) else (
  where powershell >nul 2>nul
  if errorlevel 1 (
    echo [kira] ERROR: Windows PowerShell was not found.
    pause
    exit /b 1
  )
  powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%setup.ps1" %*
)

if errorlevel 1 (
  echo.
  echo [kira] Setup failed. Read the message above.
  pause
  exit /b 1
)
endlocal & exit /b 0
