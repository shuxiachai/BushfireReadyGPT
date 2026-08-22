param(
    [switch]$PreflightOnly,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$envFile = Join-Path $projectRoot ".env"
$virtualPython = if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    Join-Path $projectRoot ".venv\Scripts\python.exe"
} else {
    $PythonPath
}
$stateDirectory = Join-Path $projectRoot "chat_history"
$statePath = Join-Path $stateDirectory "bushfire_ready_setup_state.json"
$lockPath = Join-Path $projectRoot "poetry.lock"
$modelfilePath = Join-Path $projectRoot "Modelfile"
$portMarker = Join-Path $stateDirectory "bushfire_ready_port.txt"
$skipModels = $PreflightOnly
$skipRag = $PreflightOnly

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
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
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
    param([Parameter(Mandatory = $true)][string]$TagsUrl)

    try {
        return Invoke-RestMethod -Uri $TagsUrl -TimeoutSec 2
    } catch {
        return $null
    }
}

function Wait-ForOllama {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$TagsUrl
    )

    $status = Get-OllamaStatus -TagsUrl $TagsUrl
    if (-not $status) {
        Write-Host "Ollama is not running. Starting the local service..."
        Start-Process -FilePath $Executable -ArgumentList @("serve") -WindowStyle Hidden | Out-Null
    }

    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $status = Get-OllamaStatus -TagsUrl $TagsUrl
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

function Test-ApplicationPreflight {
    param([Parameter(Mandatory = $true)][string]$Python)

    & $Python -m pip check | Out-Host
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    & $Python -c "import bs4, defusedxml, docx, openai, pydeck, pypdf, qdrant_client, reportlab, requests, streamlit, yaml; from src.data_artifacts import validate_data_manifest; from src.rag.corpus import load_source_catalog; from src.data_paths import get_data_paths; p=get_data_paths(); validate_data_manifest(p.manifest, data_dir=p.data_dir); load_source_catalog(p.rag_sources, rag_dir=p.rag_dir)" | Out-Host
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

function Open-AppBrowser {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        Start-Process -FilePath $Url | Out-Null
        Write-Host "Opened BushfireReadyGPT in the default browser: $Url"
    } catch {
        Write-Warning "The browser could not be opened automatically. Open this address manually: $Url"
    }
}

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
    if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
        throw "Python environment not found: $virtualPython"
    }

    $basePython = Resolve-BasePython
    if (-not $basePython) {
        throw "Python 3.11-3.13 is required. Install Python from https://www.python.org/downloads/windows/ and run 'Start BushfireReadyGPT.bat' again."
    }

    Write-Host "Creating the local Python environment..."
    if ((Split-Path -Leaf $basePython).ToLowerInvariant() -eq "py.exe") {
        Invoke-Checked -Command { & $basePython -3 -m venv .venv } -FailureMessage "Could not create .venv. Install Python 3.11-3.13 and retry."
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
    $dependenciesReady = Test-ApplicationPreflight -Python $virtualPython
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
    if (-not (Test-ApplicationPreflight -Python $virtualPython)) {
        throw "The Python environment is still incomplete after dependency repair."
    }
} else {
    Write-Host "Python dependencies are ready; installation skipped."
}

if (-not (Test-Path $envFile)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".env.example") -Destination $envFile
    Write-Host "Created .env from the safe local defaults."
    $repairPerformed = $true
} else {
    $envContent = [System.IO.File]::ReadAllText($envFile)
    $updatedEnvContent = [regex]::Replace(
        $envContent,
        '(?m)^OLLAMA_MODEL=qwen2\.5:7b\s*$',
        'OLLAMA_MODEL=bushfire-ready-qwen'
    )
    if ($updatedEnvContent -ne $envContent) {
        [System.IO.File]::WriteAllText(
            $envFile,
            $updatedEnvContent,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "Updated the legacy model setting to the project-specific 8K report model."
        $repairPerformed = $true
    }
}

$provider = (Get-DotEnvValue -Name "LLM_PROVIDER" -DefaultValue "ollama").ToLowerInvariant()
$ollamaModel = Get-DotEnvValue -Name "OLLAMA_MODEL" -DefaultValue "bushfire-ready-qwen"
$ollamaBaseUrl = Get-DotEnvValue -Name "OLLAMA_BASE_URL" -DefaultValue "http://127.0.0.1:11434/v1"
$configuredOllamaUri = [Uri]$ollamaBaseUrl
if ($configuredOllamaUri.Host -eq "localhost") {
    $normalizedOllamaUri = [UriBuilder]$configuredOllamaUri
    $normalizedOllamaUri.Host = "127.0.0.1"
    $ollamaBaseUrl = $normalizedOllamaUri.Uri.AbsoluteUri.TrimEnd('/')
}
$env:OLLAMA_BASE_URL = $ollamaBaseUrl
$ollamaRoot = $ollamaBaseUrl.TrimEnd('/') -replace '/v1$', ''
$tagsUrl = "$ollamaRoot/api/tags"
$ragEnabledValue = Get-DotEnvValue -Name "BUSHFIRE_RAG_ENABLED" -DefaultValue "true"
$ragEnabled = ConvertTo-Boolean -Name "BUSHFIRE_RAG_ENABLED" -Value $ragEnabledValue -DefaultValue $true
$ragModel = Get-DotEnvValue -Name "BUSHFIRE_RAG_EMBED_MODEL" -DefaultValue "embeddinggemma"
$needsOllama = (($provider -eq "ollama") -and -not $skipModels) -or ($ragEnabled -and -not $skipRag)
$ollama = $null
$ollamaStatus = $null

if ($needsOllama) {
    $ollamaUri = [Uri]$ollamaRoot
    $parsedAddress = $null
    $isIpAddress = [System.Net.IPAddress]::TryParse($ollamaUri.Host, [ref]$parsedAddress)
    $isLocalEndpoint = ($ollamaUri.Host -eq "localhost") -or (
        $isIpAddress -and [System.Net.IPAddress]::IsLoopback($parsedAddress)
    )
    if (-not $isLocalEndpoint) {
        throw "Automatic model setup requires a local Ollama endpoint; configured endpoint: $ollamaRoot"
    }

    $ollama = Resolve-OllamaExecutable
    if (-not $ollama) {
        throw "Ollama is required for the configured local features. Install it from https://ollama.com/download/windows and run 'Start BushfireReadyGPT.bat' again."
    }

    $ollamaStatus = Wait-ForOllama -Executable $ollama -TagsUrl $tagsUrl
}

$recordedModelfileHash = if ($setupState -and $setupState.modelfile_sha256) {
    [string]$setupState.modelfile_sha256
} else {
    ""
}
$modelfileHash = Get-FileSha256 -Path $modelfilePath
$savedModelfileHash = $recordedModelfileHash

if (-not $skipModels -and $provider -eq "ollama") {
    if ($ollamaModel -eq "bushfire-ready-qwen") {
        $aliasAvailable = Test-OllamaModelAvailable -Status $ollamaStatus -Model $ollamaModel
        $aliasNeedsUpdate = (-not $aliasAvailable) -or ($recordedModelfileHash -ne $modelfileHash)
        if ($aliasNeedsUpdate) {
            if (-not (Test-OllamaModelAvailable -Status $ollamaStatus -Model "qwen2.5:7b")) {
                Write-Host "Downloading the missing report base model: qwen2.5:7b"
                Invoke-Checked -Command { & $ollama pull qwen2.5:7b } -FailureMessage "Could not install Ollama model 'qwen2.5:7b'."
            }
            Write-Host "Creating or updating the project-specific 8K report model..."
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

if (-not $skipModels -and -not $skipRag -and $ragEnabled) {
    if (-not (Test-OllamaModelAvailable -Status $ollamaStatus -Model $ragModel)) {
        Write-Host "Downloading the missing RAG embedding model: $ragModel"
        Invoke-Checked -Command { & $ollama pull $ragModel } -FailureMessage "Could not install Ollama model '$ragModel'."
        $repairPerformed = $true
    } else {
        Write-Host "The RAG embedding model is ready; download skipped."
    }
}

if (-not $skipRag -and $ragEnabled) {
    $ragState = Get-RagIndexState -Python $virtualPython
    if ($ragState -ne "ready") {
        Write-Host "The RAG index is '$ragState'; building it now..."
        Invoke-Checked -Command { & $virtualPython scripts\build_rag_index.py --download } -FailureMessage "Could not build the local RAG index. Ensure Ollama and the configured embedding model are available."
        $repairPerformed = $true
    } else {
        Write-Host "The RAG index is ready; rebuild skipped."
    }
} elseif (-not $skipRag) {
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
                $runningUrl = "http://localhost:$markedPort"
                Write-Host "BushfireReadyGPT is already running at $runningUrl"
                Open-AppBrowser -Url $runningUrl
                exit 0
            }
        } catch {
            # The marker is stale and will be replaced below.
        }
    }
    Remove-Item -LiteralPath $portMarker -Force -ErrorAction SilentlyContinue
}

if ($provider -eq "ollama") {
    $ollamaStatus = Get-OllamaStatus -TagsUrl $tagsUrl
    if (-not $ollamaStatus) {
        throw "Configured Ollama endpoint is unavailable after setup: $ollamaRoot"
    }
    if (-not (Test-OllamaModelAvailable -Status $ollamaStatus -Model $ollamaModel)) {
        throw "Configured Ollama model '$ollamaModel' is not installed. Run 'Start BushfireReadyGPT.bat' again to repair it."
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

New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
Set-Content -LiteralPath $portMarker -Value $selectedPort -Encoding UTF8
$appUrl = "http://localhost:$selectedPort"
$healthUrl = "http://127.0.0.1:$selectedPort/_stcore/health"
$streamlitProcess = $null
$streamlitExitCode = 0
try {
    $streamlitProcess = Start-Process -FilePath $virtualPython `
        -ArgumentList @(
            "-m", "streamlit", "run", "src/wildfireChat.py",
            "--server.port", $selectedPort,
            "--server.address", "127.0.0.1",
            "--browser.gatherUsageStats", "false",
            "--server.headless", "true"
        ) `
        -WorkingDirectory $projectRoot `
        -NoNewWindow `
        -PassThru

    $serverReady = $false
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        if ($streamlitProcess.HasExited) {
            break
        }
        try {
            $health = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 1
            if ($health.StatusCode -eq 200 -and $health.Content.Trim().ToLowerInvariant() -eq "ok") {
                $serverReady = $true
                break
            }
        } catch {
            # Streamlit is still starting.
        }
        Start-Sleep -Milliseconds 250
    }

    if (-not $serverReady) {
        if ($streamlitProcess.HasExited) {
            throw "Streamlit stopped during startup with exit code $($streamlitProcess.ExitCode)."
        }
        Stop-Process -Id $streamlitProcess.Id -Force -ErrorAction SilentlyContinue
        throw "Streamlit did not become ready at $appUrl within 30 seconds."
    }

    Open-AppBrowser -Url $appUrl
    $streamlitProcess.WaitForExit()
    $streamlitExitCode = $streamlitProcess.ExitCode
} finally {
    if ($streamlitProcess) {
        $streamlitProcess.Dispose()
    }
    if (Test-Path $portMarker) {
        $currentMarker = (Get-Content -Encoding UTF8 $portMarker -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($currentMarker -eq [string]$selectedPort) {
            Remove-Item -LiteralPath $portMarker -Force -ErrorAction SilentlyContinue
        }
    }
}
exit $streamlitExitCode
