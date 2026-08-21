param(
    [switch]$SkipModels,
    [switch]$SkipRag
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Resolve-BasePython {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        return $launcher.Source
    }

    return $null
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

function Wait-ForOllama {
    param([Parameter(Mandatory = $true)][string]$Executable)

    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
        return
    } catch {
        Write-Host "Starting Ollama..."
        Start-Process -FilePath $Executable -ArgumentList @("serve") -WindowStyle Hidden | Out-Null
    }

    for ($attempt = 1; $attempt -le 30; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
            return
        } catch {
            if ($attempt % 5 -eq 0) {
                Write-Host "Waiting for Ollama... $attempt/30 seconds"
            }
        }
    }

    throw "Ollama did not start within 30 seconds. Open Ollama manually and rerun setup."
}

$virtualPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $virtualPython)) {
    $basePython = Resolve-BasePython
    if (-not $basePython) {
        throw "Python 3.11-3.13 is required. Install Python from https://www.python.org/downloads/windows/ and rerun setup."
    }

    Write-Host "Creating the local Python environment..."
    if ((Split-Path -Leaf $basePython).ToLowerInvariant() -eq "py.exe") {
        Invoke-Checked -Command { & $basePython -3.13 -m venv .venv } -FailureMessage "Could not create .venv with Python 3.13. Install Python 3.11-3.13 and retry."
    } else {
        Invoke-Checked -Command { & $basePython -m venv .venv } -FailureMessage "Could not create the .venv environment."
    }
}

Write-Host "Installing verified project dependencies..."
Invoke-Checked -Command { & $virtualPython -m pip install --upgrade pip } -FailureMessage "Could not update pip. Check the internet connection and retry."
Invoke-Checked -Command { & $virtualPython -m pip install poetry==2.3.4 } -FailureMessage "Could not install Poetry 2.3.4."
$previousPoetrySetting = $env:POETRY_VIRTUALENVS_CREATE
try {
    $env:POETRY_VIRTUALENVS_CREATE = "false"
    Invoke-Checked -Command { & $virtualPython -m poetry install --with dev --no-root } -FailureMessage "Could not install the locked project dependencies."
} finally {
    $env:POETRY_VIRTUALENVS_CREATE = $previousPoetrySetting
}

$envPath = Join-Path $projectRoot ".env"
if (-not (Test-Path $envPath)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".env.example") -Destination $envPath
    Write-Host "Created .env from the safe local defaults."
} else {
    $envContent = [System.IO.File]::ReadAllText($envPath)
    $updatedEnvContent = [regex]::Replace(
        $envContent,
        '(?m)^OLLAMA_MODEL=qwen2\.5:7b\s*$',
        'OLLAMA_MODEL=bushfire-ready-qwen'
    )
    if ($updatedEnvContent -ne $envContent) {
        [System.IO.File]::WriteAllText(
            $envPath,
            $updatedEnvContent,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "Updated the legacy model setting to the project-specific 16384-token model."
    }
}

if (-not $SkipModels) {
    $ollama = Resolve-OllamaExecutable
    if (-not $ollama) {
        throw "Ollama is required for the default local setup. Install it from https://ollama.com/download/windows and rerun setup."
    }

    Wait-ForOllama -Executable $ollama
    foreach ($model in @("qwen2.5:7b", "embeddinggemma")) {
        Write-Host "Ensuring Ollama model is available: $model"
        Invoke-Checked -Command { & $ollama pull $model } -FailureMessage "Could not install Ollama model '$model'."
    }
    Write-Host "Creating the project model with a 16384-token context window..."
    Invoke-Checked -Command { & $ollama create bushfire-ready-qwen -f .\Modelfile } -FailureMessage "Could not create the project-specific Ollama model."
}

if (-not $SkipRag) {
    Write-Host "Building the local official-guidance RAG index..."
    Invoke-Checked -Command { & $virtualPython scripts\build_rag_index.py --download } -FailureMessage "Could not build the local RAG index. Ensure Ollama and embeddinggemma are available."
}

Invoke-Checked -Command { & powershell -NoProfile -ExecutionPolicy Bypass -File .\start_app.ps1 -PreflightOnly } -FailureMessage "The final application preflight failed."
Write-Host "BushfireReadyGPT setup completed successfully."
