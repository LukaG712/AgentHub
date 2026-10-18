# AgentHub Windows Startup Script
# Usage: .\start.ps1
# Prerequisites: Python 3.10+, .venv created (see setup instructions)

$ErrorActionPreference = 'Stop'

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $SCRIPT_DIR

# Load environment variables from .env file if it exists
$ENV_FILE = Join-Path $SCRIPT_DIR '.env'
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
    Write-Host "No .env file found. Using current environment." -ForegroundColor Yellow
}

# Activate virtual environment
$VENV_PYTHON = Join-Path $SCRIPT_DIR '.venv' 'Scripts' 'python.exe'
if (Test-Path $VENV_PYTHON) {
    Write-Host "Using virtual environment: .venv" -ForegroundColor Green
} else {
    Write-Host "WARNING: Virtual environment not found at .venv" -ForegroundColor Yellow
    Write-Host "Create it first: python -m venv .venv && .\.venv\Scripts\activate && pip install -r requirements.txt" -ForegroundColor Yellow
}

# Check for required environment variables
if (-not $env:HUB_API_KEY) {
    Write-Host "WARNING: HUB_API_KEY not set. Set it in .env or your environment." -ForegroundColor Yellow
    Write-Host "Generate one: python -c ""import secrets; print(secrets.token_urlsafe(32))""" -ForegroundColor Yellow
}

# Get port from environment or default to 8080
$port = $env:HUB_PORT if ($env:HUB_PORT) else 8080

Write-Host "Starting AgentHub on port $port..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor Green
Write-Host ""

# Start uvicorn
$python = if (Test-Path $VENV_PYTHON) { $VENV_PYTHON } else { 'python' }
& $python -m uvicorn hub.api:app --host 0.0.0.0 --port $port --reload
