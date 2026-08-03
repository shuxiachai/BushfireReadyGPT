$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found: $python`nCreate it with: python -m venv .venv"
}

$envFile = Join-Path $projectRoot ".env"

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

$provider = (Get-DotEnvValue -Name "LLM_PROVIDER" -DefaultValue "ollama").ToLowerInvariant()

if ($provider -eq "ollama") {
    $ollamaBaseUrl = Get-DotEnvValue -Name "OLLAMA_BASE_URL" -DefaultValue "http://localhost:11434/v1"
    $ollamaModel = Get-DotEnvValue -Name "OLLAMA_MODEL" -DefaultValue "qwen2.5:7b"
    $ollamaRoot = $ollamaBaseUrl.TrimEnd('/') -replace '/v1$', ''
    $tagsUrl = "$ollamaRoot/api/tags"
    $ollamaStatus = Get-OllamaStatus -TagsUrl $tagsUrl

    if (-not $ollamaStatus) {
        $ollamaUri = [Uri]$ollamaRoot
        $isLocalEndpoint = $ollamaUri.Host -in @("localhost", "127.0.0.1", "::1")
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

    $availableModels = @(
        $ollamaStatus.models | ForEach-Object {
            if ($_.name) { $_.name }
            elseif ($_.model) { $_.model }
        }
    )
    if ($availableModels -notcontains $ollamaModel) {
        $ollamaExecutable = Resolve-OllamaExecutable
        $pullCommand = if ($ollamaExecutable) { "& `"$ollamaExecutable`" pull $ollamaModel" } else { "ollama pull $ollamaModel" }
        throw "Configured Ollama model '$ollamaModel' is not installed.`nInstall it with:`n  $pullCommand"
    }

    Write-Host "Ollama is ready at $ollamaRoot with model $ollamaModel"
} else {
    Write-Host "LLM provider is '$provider'; skipping the local Ollama health check."
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
