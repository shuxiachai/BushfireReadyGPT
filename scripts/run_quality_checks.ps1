param()

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
$localPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$auditCacheDirectory = Join-Path $projectRoot "tmp\pip-audit-cache"

$poetryCommand = Get-Command poetry -ErrorAction SilentlyContinue
if (-not $poetryCommand -and -not (Test-Path $localPython)) {
    throw "Poetry is unavailable. Run 'Start BushfireReadyGPT.bat --preflight' first."
}

function Invoke-PoetryCommand {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if ($poetryCommand) {
        & poetry @Arguments
    } else {
        & $localPython -m poetry @Arguments
    }
}

function Invoke-QualityCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

$previousPythonUtf8 = [Environment]::GetEnvironmentVariable("PYTHONUTF8", "Process")
try {
    # Python's UTF-8 mode prevents pip-audit from failing when the checkout path
    # contains characters outside the active Windows console code page.
    $env:PYTHONUTF8 = "1"
    New-Item -ItemType Directory -Path $auditCacheDirectory -Force | Out-Null

    Invoke-QualityCommand "Poetry lock validation" { Invoke-PoetryCommand @("check", "--lock") }
    Invoke-QualityCommand "Installed dependency validation" {
        Invoke-PoetryCommand @("run", "python", "-m", "pip", "check")
    }
    Invoke-QualityCommand "Ruff lint" { Invoke-PoetryCommand @("run", "ruff", "check", "src", "tests", "scripts") }
    Invoke-QualityCommand "Ruff format validation" {
        Invoke-PoetryCommand @("run", "ruff", "format", "--check", "src", "tests", "scripts")
    }
    Invoke-QualityCommand "Bandit security scan" {
        Invoke-PoetryCommand @("run", "bandit", "-q", "-r", "src", "scripts", "-x", "src/legacy")
    }
    Invoke-QualityCommand "Dependency vulnerability audit" {
        Invoke-PoetryCommand @(
            "run",
            "pip-audit",
            "--local",
            "--skip-editable",
            "--cache-dir",
            $auditCacheDirectory
        )
    }

    Write-Host "All static, dependency and security checks passed."
} finally {
    if ($null -eq $previousPythonUtf8) {
        Remove-Item Env:\PYTHONUTF8 -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONUTF8 = $previousPythonUtf8
    }
}
