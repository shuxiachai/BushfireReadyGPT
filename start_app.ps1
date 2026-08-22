param(
    [switch]$PreflightOnly,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$python = if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    Join-Path $projectRoot ".venv\Scripts\python.exe"
} else {
    $PythonPath
}
if (-not (Test-Path $python)) {
    throw "Python environment not found: $python`nRun 'Start BushfireReadyGPT.bat' to create it."
}

$envFile = Join-Path $projectRoot ".env"
$runtimeDir = Join-Path $projectRoot "chat_history"
$portMarker = Join-Path $runtimeDir "bushfire_ready_port.txt"

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$DefaultValue = ""
    )

    if (-not (Test-Path $envFile)) {
        return $DefaultValue
    }

    $escapedName = [regex]::Escape($Name)
    $value = $null
    foreach ($line in Get-Content -Encoding UTF8 $envFile) {
        if ($line -match "^\s*$escapedName\s*=\s*(.*?)\s*$") {
            $value = $matches[1].Trim()
        }
    }

    if ([string]::IsNullOrWhiteSpace($value)) {
        return $DefaultValue
    }

    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
        ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        return $value.Substring(1, $value.Length - 2)
    }

    return $value
}

function Get-OllamaStatus {
    param([Parameter(Mandatory = $true)][string]$TagsUrl)

    try {
        return Invoke-RestMethod -Uri $TagsUrl -TimeoutSec 2
    } catch {
        return $null
    }
}

function Resolve-OllamaExecutable {
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $installedPath = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $installedPath) {
        return $installedPath
    }

    return $null
}

function Test-OllamaModelAvailable {
    param(
        [Parameter(Mandatory = $true)]$Status,
        [Parameter(Mandatory = $true)][string]$Model
    )

    $expectedNames = @($Model)
    if (-not $Model.Contains(":")) {
        $expectedNames += "${Model}:latest"
    }
    $availableNames = @(
        $Status.models | ForEach-Object {
            if ($_.name) { $_.name }
            elseif ($_.model) { $_.model }
        }
    )
    return @($expectedNames | Where-Object { $availableNames -contains $_ }).Count -gt 0
}

& $python -c "import bs4, defusedxml, docx, openai, pydeck, pypdf, qdrant_client, reportlab, requests, streamlit, yaml; from src.data_artifacts import validate_data_manifest; from src.rag.corpus import load_source_catalog; from src.data_paths import get_data_paths; p=get_data_paths(); validate_data_manifest(p.manifest, data_dir=p.data_dir); load_source_catalog(p.rag_sources, rag_dir=p.rag_dir)"
if ($LASTEXITCODE -ne 0) {
    throw "Application dependencies or bundled data failed validation. Run 'Start BushfireReadyGPT.bat' to repair the environment."
}

if ($PreflightOnly) {
    Write-Host "BushfireReadyGPT preflight passed: Python dependencies, bundled data and RAG catalog are valid."
    exit 0
}

if (Test-Path $portMarker) {
    $markedPort = (Get-Content -Encoding UTF8 $portMarker -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($markedPort -match '^\d+$') {
        try {
            $health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$markedPort/_stcore/health" -TimeoutSec 2
            if ($health.StatusCode -eq 200 -and $health.Content.Trim().ToLowerInvariant() -eq "ok") {
                Write-Host "BushfireReadyGPT is already running at http://localhost:$markedPort"
                exit 0
            }
        } catch {
            # The marker is stale and will be replaced below.
        }
    }
    Remove-Item -LiteralPath $portMarker -Force -ErrorAction SilentlyContinue
}

$provider = (Get-DotEnvValue -Name "LLM_PROVIDER" -DefaultValue "ollama").ToLowerInvariant()

if ($provider -eq "ollama") {
    $ollamaBaseUrl = Get-DotEnvValue -Name "OLLAMA_BASE_URL" -DefaultValue "http://127.0.0.1:11434/v1"
    $ollamaModel = Get-DotEnvValue -Name "OLLAMA_MODEL" -DefaultValue "bushfire-ready-qwen"
    $configuredOllamaUri = [Uri]$ollamaBaseUrl
    if ($configuredOllamaUri.Host -eq "localhost") {
        $normalizedOllamaUri = [UriBuilder]$configuredOllamaUri
        $normalizedOllamaUri.Host = "127.0.0.1"
        $ollamaBaseUrl = $normalizedOllamaUri.Uri.AbsoluteUri.TrimEnd('/')
    }
    $env:OLLAMA_BASE_URL = $ollamaBaseUrl
    $ollamaRoot = $ollamaBaseUrl.TrimEnd('/') -replace '/v1$', ''
    $tagsUrl = "$ollamaRoot/api/tags"
    $ollamaStatus = Get-OllamaStatus -TagsUrl $tagsUrl

    if (-not $ollamaStatus) {
        $ollamaUri = [Uri]$ollamaRoot
        $parsedAddress = $null
        $isIpAddress = [System.Net.IPAddress]::TryParse($ollamaUri.Host, [ref]$parsedAddress)
        $isLocalEndpoint = ($ollamaUri.Host -eq "localhost") -or (
            $isIpAddress -and [System.Net.IPAddress]::IsLoopback($parsedAddress)
        )
        if (-not $isLocalEndpoint) {
            throw "Configured Ollama endpoint is unavailable: $ollamaRoot"
        }

        $ollamaExecutable = Resolve-OllamaExecutable
        if (-not $ollamaExecutable) {
            throw "Ollama is not installed or is not available on PATH. Install Ollama, then run: ollama pull $ollamaModel"
        }

        Write-Host "Ollama is not running. Starting the local service..."
        try {
            Start-Process -FilePath $ollamaExecutable -ArgumentList @("serve") -WindowStyle Hidden | Out-Null
        } catch {
            throw "Failed to start Ollama: $($_.Exception.Message)"
        }

        $maxAttempts = 30
        for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
            Start-Sleep -Seconds 1
            $ollamaStatus = Get-OllamaStatus -TagsUrl $tagsUrl
            if ($ollamaStatus) {
                break
            }
            if ($attempt % 5 -eq 0) {
                Write-Host "Waiting for Ollama... $attempt/$maxAttempts seconds"
            }
        }

        if (-not $ollamaStatus) {
            throw @"
Ollama did not become available at $ollamaRoot within $maxAttempts seconds.
Open a separate PowerShell terminal and run:
  & "$ollamaExecutable" serve
Then verify:
  Invoke-RestMethod $tagsUrl
"@
        }
    }

    if (-not (Test-OllamaModelAvailable -Status $ollamaStatus -Model $ollamaModel)) {
        throw "Configured Ollama model '$ollamaModel' is not installed.`nRun 'Start BushfireReadyGPT.bat' to install it."
    }

    Write-Host "Ollama is ready at $ollamaRoot with model $ollamaModel"
} else {
    Write-Host "LLM provider is '$provider'; skipping the local Ollama health check."
}

$ports = @(8501, 8502, 8503, 8504, 8505)
$selectedPort = $null

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

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
Set-Content -LiteralPath $portMarker -Value $selectedPort -Encoding UTF8
$streamlitExitCode = 0
try {
    & $python -m streamlit run src/wildfireChat.py `
        --server.port $selectedPort `
        --server.address 127.0.0.1 `
        --browser.gatherUsageStats false
    $streamlitExitCode = $LASTEXITCODE
} finally {
    if (Test-Path $portMarker) {
        $currentMarker = (Get-Content -Encoding UTF8 $portMarker -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($currentMarker -eq [string]$selectedPort) {
            Remove-Item -LiteralPath $portMarker -Force -ErrorAction SilentlyContinue
        }
    }
}
exit $streamlitExitCode
