$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found: $python"
}

try {
    Invoke-WebRequest -UseBasicParsing "http://localhost:11434/api/tags" -TimeoutSec 3 | Out-Null
} catch {
    Start-Process -FilePath "ollama" -ArgumentList @("serve") -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

$ports = @(8501, 8502, 8503, 8504, 8505)
$selectedPort = $null

foreach ($port in $ports) {
    $running = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($running) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing "http://localhost:$port" -TimeoutSec 2
            if ($response.Content -match "BushfireReadyGPT") {
                $selectedPort = $port
                break
            }
            Write-Host "Port $port is already in use by another app. Trying next port..."
            continue
        } catch {
            Write-Host "Port $port is busy but did not respond as BushfireReadyGPT. Trying next port..."
            continue
        }
    }
}

if ($selectedPort) {
    Write-Host "BushfireReadyGPT is already running at http://localhost:$selectedPort"
    exit 0
}

foreach ($port in $ports) {
    $running = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $running) {
        $selectedPort = $port
        break
    }
}

if (-not $selectedPort) {
    throw "No available Streamlit port found in: $($ports -join ', ')"
}

Write-Host "Starting BushfireReadyGPT at http://localhost:$selectedPort"
Write-Host "Keep this terminal open while using the app. Press Ctrl+C or close this terminal to stop Streamlit."

& $python -m streamlit run src/wildfireChat.py --server.port $selectedPort
