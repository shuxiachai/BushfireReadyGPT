@echo off
setlocal

cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
    echo PowerShell was not found on this computer.
    echo Please install PowerShell and run this launcher again.
    pause
    exit /b 1
)

set "PREFLIGHT_ONLY="
if /I "%~1"=="--preflight" set "PREFLIGHT_ONLY=1"

echo Checking the local environment...
if defined PREFLIGHT_ONLY (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -SkipModels -SkipRag
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
)
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo BushfireReadyGPT could not repair the local environment.
    if not defined PREFLIGHT_ONLY pause
    exit /b %EXIT_CODE%
)

if defined PREFLIGHT_ONLY (
    echo BushfireReadyGPT launcher preflight passed.
    exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_app.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo BushfireReadyGPT stopped with exit code %EXIT_CODE%.
    pause
    exit /b %EXIT_CODE%
)

endlocal
