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

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [System.IO.File]::OpenRead($Path)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($stream)
        return ([System.BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$DefaultValue = ""
    )

    if (-not (Test-Path $envPath)) {
        return $DefaultValue
    }

    $escapedName = [regex]::Escape($Name)
    $value = $null
    foreach ($line in Get-Content -Encoding UTF8 $envPath) {
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

function ConvertTo-Boolean {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$Value,
        [bool]$DefaultValue
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $DefaultValue
    }

    switch ($Value.Trim().ToLowerInvariant()) {
        { $_ -in @("1", "true", "yes", "on") } { return $true }
        { $_ -in @("0", "false", "no", "off") } { return $false }
        default { throw "$Name must be true or false in .env." }
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

function Get-OllamaStatus {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
    } catch {
        return $null
    }
}

function Wait-ForOllama {
    param([Parameter(Mandatory = $true)][string]$Executable)

    $status = Get-OllamaStatus
    if (-not $status) {
        Write-Host "Starting Ollama..."
        Start-Process -FilePath $Executable -ArgumentList @("serve") -WindowStyle Hidden | Out-Null
    }

    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $status = Get-OllamaStatus
        if ($status) {
            return $status
        }
        if ($attempt % 5 -eq 0) {
            Write-Host "Waiting for Ollama... $attempt/30 seconds"
        }
        Start-Sleep -Seconds 1
    }

    throw "Ollama did not start within 30 seconds. Open Ollama manually and run 'Start BushfireReadyGPT.bat' again."
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

function Test-PythonEnvironment {
    param([Parameter(Mandatory = $true)][string]$Python)

    & $Python -m pip check | Out-Host
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    & powershell -NoProfile -ExecutionPolicy Bypass -File .\start_app.ps1 -PreflightOnly -PythonPath $Python | Out-Host
    return $LASTEXITCODE -eq 0
}

function Get-RagIndexState {
    param([Parameter(Mandatory = $true)][string]$Python)

    $output = @(
        & $Python -c "from dotenv import load_dotenv; load_dotenv(); from src.rag.service import inspect_rag_index; print(inspect_rag_index()['state'])"
    )
    if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) {
        return "invalid"
    }
    return [string]$output[-1].Trim()
}

$envPath = Join-Path $projectRoot ".env"
$virtualPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$stateDirectory = Join-Path $projectRoot "chat_history"
$statePath = Join-Path $stateDirectory "bushfire_ready_setup_state.json"
$lockPath = Join-Path $projectRoot "poetry.lock"
$modelfilePath = Join-Path $projectRoot "Modelfile"
$setupState = $null
$repairPerformed = $false

if (Test-Path $statePath) {
    try {
        $setupState = Get-Content -Raw -Encoding UTF8 $statePath | ConvertFrom-Json
    } catch {
        Write-Host "The previous setup record is invalid; checking the environment again."
    }
}

$environmentCreated = $false
if (-not (Test-Path $virtualPython)) {
    $basePython = Resolve-BasePython
    if (-not $basePython) {
        throw "Python 3.11-3.13 is required. Install Python from https://www.python.org/downloads/windows/ and run 'Start BushfireReadyGPT.bat' again."
    }

    Write-Host "Creating the local Python environment..."
    if ((Split-Path -Leaf $basePython).ToLowerInvariant() -eq "py.exe") {
        Invoke-Checked -Command { & $basePython -3.13 -m venv .venv } -FailureMessage "Could not create .venv with Python 3.13. Install Python 3.11-3.13 and retry."
    } else {
        Invoke-Checked -Command { & $basePython -m venv .venv } -FailureMessage "Could not create the .venv environment."
    }
    $environmentCreated = $true
    $repairPerformed = $true
}

$lockHash = Get-FileSha256 -Path $lockPath
$recordedLockHash = if ($setupState -and $setupState.poetry_lock_sha256) {
    [string]$setupState.poetry_lock_sha256
} else {
    ""
}
$dependenciesReady = $false

if (-not $environmentCreated -and ($recordedLockHash -eq "" -or $recordedLockHash -eq $lockHash)) {
    Write-Host "Checking the existing Python environment..."
    $dependenciesReady = Test-PythonEnvironment -Python $virtualPython
}

if (-not $dependenciesReady) {
    if ($recordedLockHash -and $recordedLockHash -ne $lockHash) {
        Write-Host "poetry.lock changed; updating the local dependencies..."
    } else {
        Write-Host "Installing or repairing the locked project dependencies..."
    }
    Invoke-Checked -Command { & $virtualPython -m pip install --upgrade pip } -FailureMessage "Could not update pip. Check the internet connection and retry."
    Invoke-Checked -Command { & $virtualPython -m pip install poetry==2.3.4 } -FailureMessage "Could not install Poetry 2.3.4."
    $previousPoetrySetting = $env:POETRY_VIRTUALENVS_CREATE
    try {
        $env:POETRY_VIRTUALENVS_CREATE = "false"
        Invoke-Checked -Command { & $virtualPython -m poetry install --with dev --no-root } -FailureMessage "Could not install the locked project dependencies."
    } finally {
        $env:POETRY_VIRTUALENVS_CREATE = $previousPoetrySetting
    }
    $repairPerformed = $true
    if (-not (Test-PythonEnvironment -Python $virtualPython)) {
        throw "The Python environment is still incomplete after dependency repair."
    }
} else {
    Write-Host "Python dependencies are ready; installation skipped."
}

if (-not (Test-Path $envPath)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".env.example") -Destination $envPath
    Write-Host "Created .env from the safe local defaults."
    $repairPerformed = $true
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
        $repairPerformed = $true
    }
}

$provider = (Get-DotEnvValue -Name "LLM_PROVIDER" -DefaultValue "ollama").ToLowerInvariant()
$ollamaModel = Get-DotEnvValue -Name "OLLAMA_MODEL" -DefaultValue "bushfire-ready-qwen"
$ragEnabledValue = Get-DotEnvValue -Name "BUSHFIRE_RAG_ENABLED" -DefaultValue "true"
$ragEnabled = ConvertTo-Boolean -Name "BUSHFIRE_RAG_ENABLED" -Value $ragEnabledValue -DefaultValue $true
$ragModel = Get-DotEnvValue -Name "BUSHFIRE_RAG_EMBED_MODEL" -DefaultValue "embeddinggemma"
$needsOllama = (($provider -eq "ollama") -and -not $SkipModels) -or ($ragEnabled -and -not $SkipRag)
$ollama = $null
$ollamaStatus = $null

if ($needsOllama) {
    $ollama = Resolve-OllamaExecutable
    if (-not $ollama) {
        throw "Ollama is required for the configured local features. Install it from https://ollama.com/download/windows and run 'Start BushfireReadyGPT.bat' again."
    }

    $ollamaStatus = Wait-ForOllama -Executable $ollama
}

$recordedModelfileHash = if ($setupState -and $setupState.modelfile_sha256) {
    [string]$setupState.modelfile_sha256
} else {
    ""
}
$modelfileHash = Get-FileSha256 -Path $modelfilePath
$savedModelfileHash = $recordedModelfileHash

if (-not $SkipModels -and $provider -eq "ollama") {
    if ($ollamaModel -eq "bushfire-ready-qwen") {
        $aliasAvailable = Test-OllamaModelAvailable -Status $ollamaStatus -Model $ollamaModel
        $aliasNeedsUpdate = (-not $aliasAvailable) -or (
            $recordedModelfileHash -and $recordedModelfileHash -ne $modelfileHash
        )
        if ($aliasNeedsUpdate) {
            if (-not (Test-OllamaModelAvailable -Status $ollamaStatus -Model "qwen2.5:7b")) {
                Write-Host "Downloading the missing report base model: qwen2.5:7b"
                Invoke-Checked -Command { & $ollama pull qwen2.5:7b } -FailureMessage "Could not install Ollama model 'qwen2.5:7b'."
            }
            Write-Host "Creating or updating the project-specific 16K report model..."
            Invoke-Checked -Command { & $ollama create bushfire-ready-qwen -f .\Modelfile } -FailureMessage "Could not create the project-specific Ollama model."
            $repairPerformed = $true
        } else {
            Write-Host "The report model is ready; model creation skipped."
        }
        $savedModelfileHash = $modelfileHash
    } elseif (-not (Test-OllamaModelAvailable -Status $ollamaStatus -Model $ollamaModel)) {
        Write-Host "Downloading the configured report model: $ollamaModel"
        Invoke-Checked -Command { & $ollama pull $ollamaModel } -FailureMessage "Could not install Ollama model '$ollamaModel'."
        $repairPerformed = $true
    } else {
        Write-Host "The configured report model is ready; download skipped."
    }
}

if (-not $SkipModels -and -not $SkipRag -and $ragEnabled) {
    if (-not (Test-OllamaModelAvailable -Status $ollamaStatus -Model $ragModel)) {
        Write-Host "Downloading the missing RAG embedding model: $ragModel"
        Invoke-Checked -Command { & $ollama pull $ragModel } -FailureMessage "Could not install Ollama model '$ragModel'."
        $repairPerformed = $true
    } else {
        Write-Host "The RAG embedding model is ready; download skipped."
    }
}

if (-not $SkipRag -and $ragEnabled) {
    $ragState = Get-RagIndexState -Python $virtualPython
    if ($ragState -ne "ready") {
        Write-Host "The RAG index is '$ragState'; building it now..."
        Invoke-Checked -Command { & $virtualPython scripts\build_rag_index.py --download } -FailureMessage "Could not build the local RAG index. Ensure Ollama and the configured embedding model are available."
        $repairPerformed = $true
    } else {
        Write-Host "The RAG index is ready; rebuild skipped."
    }
} elseif (-not $SkipRag) {
    Write-Host "RAG is disabled in .env; index checks skipped."
}

$statePayload = [ordered]@{
    schema_version = 1
    poetry_lock_sha256 = $lockHash
    modelfile_sha256 = $savedModelfileHash
    checked_at_utc = [DateTime]::UtcNow.ToString("o")
}
$stateJson = $statePayload | ConvertTo-Json
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
[System.IO.File]::WriteAllText($statePath, $stateJson, [System.Text.UTF8Encoding]::new($false))

if ($repairPerformed) {
    Write-Host "BushfireReadyGPT environment check and repair completed successfully."
} else {
    Write-Host "BushfireReadyGPT environment is ready; no installation was needed."
}
