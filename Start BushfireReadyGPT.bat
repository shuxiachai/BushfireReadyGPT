@echo off
setlocal

cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
    echo PowerShell was not found on this computer.
    echo Please install PowerShell or run start_app.ps1 from a PowerShell terminal.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_app.ps1"
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
    echo.
    echo BushfireReadyGPT stopped with exit code %EXIT_CODE%.
    pause
    exit /b %EXIT_CODE%
)

endlocal
