# start.ps1 — Start the Agent Hub server (Windows)
# Auto-runs setup.ps1 if this is the first time.
# Usage: .\start.ps1

$ErrorActionPreference = 'Stop'

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $SCRIPT_DIR

# ── Auto-setup if needed ─────────────────────────────────────────────
$needsSetup = $false
$VENV_PYTHON = Join-Path $SCRIPT_DIR '.venv' 'Scripts' 'python.exe'
$ENV_FILE = Join-Path $SCRIPT_DIR '.env'

if (-not (Test-Path $VENV_PYTHON)) {
    $needsSetup = $true
}
if (-not (Test-Path $ENV_FILE)) {
    $needsSetup = $true
}

if ($needsSetup) {
    Write-Host ""
    Write-Host "First time running Agent Hub? Running setup..." -ForegroundColor Yellow
    Write-Host ""
    $setupScript = Join-Path $SCRIPT_DIR 'setup.ps1'
    if (Test-Path $setupScript) {
        & $setupScript
    } else {
        Write-Host "Error: setup.ps1 not found. Run setup manually." -ForegroundColor Red
        exit 1
    }
    Write-Host ""
    Write-Host "Setup complete. Starting server..." -ForegroundColor Green
    Write-Host ""
}

# ── Load environment variables from .env ─────────────────────────────
if (Test-Path $ENV_FILE) {
    Write-Host "Loading .env file..." -ForegroundColor Green
    Get-Content $ENV_FILE | ForEach-Object {
        $line = $_.Trim()
        if ($line -and $line -notlike '#*' -and $line -match '=?') {
            $key, $value = $line.Split('=', 2)
            $key = $key.Trim()
            $value = $value.Trim().Trim('"').Trim("'")
            if ($key) {
                [Environment]::SetEnvironmentVariable($key, $value, 'Process')
                $env:$key = $value
            }
        }
    }
    Write-Host "Environment variables loaded." -ForegroundColor Green
} else {
    Write-Host "Error: .env file not found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

# ── Check for required environment variables ─────────────────────────
if (-not $env:HUB_API_KEY) {
    Write-Host "Error: HUB_API_KEY not set in .env." -ForegroundColor Red
    exit 1
}

# ── Get port from environment or default to 8080 ─────────────────────
$port = if ($env:HUB_PORT) { [int]$env:HUB_PORT } else { 8080 }

Write-Host ""
Write-Host "Starting Agent Hub on port $port..." -ForegroundColor Green
Write-Host "Dashboard: http://localhost:$port" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor Green
Write-Host ""

# ── Auto-open browser ────────────────────────────────────────────────
Start-Process "http://localhost:$port"

# ── Start uvicorn ────────────────────────────────────────────────────
& $VENV_PYTHON -m uvicorn hub.api:app --host 0.0.0.0 --port $port --reload
