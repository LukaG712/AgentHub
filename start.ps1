# start.ps1 - Start the Agent Hub server (Windows)
# On first run, automatically sets up the environment (venv, dependencies, config, API key).
# Usage: .\start.ps1

$ErrorActionPreference = 'Stop'

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $SCRIPT_DIR

# -- Colours -----------------------------------------------------------
$GREEN = 'Green'; $YELLOW = 'Yellow'; $RED = 'Red'

# -- Auto-setup if needed -----------------------------------------------
$needsSetup = $false
$VENV_PYTHON = Join-Path (Join-Path (Join-Path $SCRIPT_DIR '.venv') 'Scripts') 'python.exe'
$ENV_FILE = Join-Path $SCRIPT_DIR '.env'

if (-not (Test-Path $VENV_PYTHON)) {
    $needsSetup = $true
}
if (-not (Test-Path $ENV_FILE)) {
    $needsSetup = $true
}

if ($needsSetup) {
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor $GREEN
    Write-Host "  Agent Hub - First-time setup" -ForegroundColor $GREEN
    Write-Host "=========================================" -ForegroundColor $GREEN
    Write-Host ""

    # -- 1. Check Python 3.11+ ------------------------------------------
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Host "X Python is not installed. Install it from https://www.python.org/downloads/" -ForegroundColor $RED
        Write-Host "   Make sure to check 'Add Python to PATH' during installation." -ForegroundColor $RED
        exit 1
    }

    $pyVer = python --version 2>&1
    $pyMajor = (python -c "import sys; print(sys.version_info.major)").Trim()
    $pyMinor = (python -c "import sys; print(sys.version_info.minor)").Trim()

    if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 11)) {
        Write-Host "X Python $pyVer is too old. Agent Hub needs Python 3.11 or newer." -ForegroundColor $RED
        exit 1
    }

    Write-Host "V Python $pyVer - good." -ForegroundColor $GREEN

    # -- 2. Check Junie CLI (non-blocking warning) ----------------------
    $junie = Get-Command junie -ErrorAction SilentlyContinue

    # Fallback: search JetBrains installation directories for Junie CLI
    if (-not $junie) {
        $jetbrainsPaths = @(
            Join-Path $env:LOCALAPPDATA 'JetBrains'
            'C:\Program Files\JetBrains'
        )
        foreach ($baseDir in $jetbrainsPaths) {
            if (Test-Path $baseDir) {
                $junieBat = Get-ChildItem -Path $baseDir -Recurse -Depth 4 -Filter 'junie.bat' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                if ($junieBat) {
                    $junie = $junieBat
                    break
                }
            }
        }
    }

    if (-not $junie) {
        Write-Host ""
        Write-Host "! Junie CLI not found on PATH - agents won't run until it's installed." -ForegroundColor $YELLOW
        Write-Host "   Install from https://junie.jetbrains.com" -ForegroundColor $YELLOW
    } else {
        # Determine the path to execute: Get-Command returns .Source, Get-ChildItem returns .FullName
        $juniePath = if ($junie.Source) { $junie.Source } elseif ($junie.FullName) { $junie.FullName } else { $junie }
        $junieVer = $null
        $oldErrorAction = $ErrorActionPreference
        $ErrorActionPreference = 'SilentlyContinue'
        $result = cmd /c "$juniePath --version 2>nul"
        $ErrorActionPreference = $oldErrorAction
        if ($result) {
            $junieVer = ($result | Where-Object { $_ -match 'Junie' } | Select-Object -First 1).ToString().Trim()
        }
        if (-not $junieVer) { $junieVer = '(version unknown)' }
        Write-Host "V Junie CLI found ($junieVer)." -ForegroundColor $GREEN
    }

    Write-Host ""

    # -- 3. Create virtual environment ----------------------------------
    $venvPath = Join-Path $SCRIPT_DIR '.venv'
    if (-not (Test-Path $venvPath)) {
        Write-Host "Creating virtual environment (.venv)..."
        python -m venv .venv
        Write-Host "V Virtual environment created." -ForegroundColor $GREEN
    } else {
        Write-Host "V Virtual environment already exists." -ForegroundColor $GREEN
    }

    # -- 4. Install Python dependencies ---------------------------------
    Write-Host "Installing Python packages..."
    & (Join-Path $venvPath 'Scripts\python.exe') -m pip install --upgrade pip -q
    & (Join-Path $venvPath 'Scripts\python.exe') -m pip install -r requirements.txt -q
    Write-Host "V Packages installed." -ForegroundColor $GREEN

    Write-Host ""

    # -- 5. Copy hub.example.yaml => hub.yaml (never overwrite) ---------
    $hubYaml = Join-Path $SCRIPT_DIR 'hub.yaml'
    if (-not (Test-Path $hubYaml)) {
        Copy-Item hub.example.yaml hub.yaml
        Write-Host "V Created hub.yaml from hub.example.yaml." -ForegroundColor $GREEN
    } else {
        Write-Host "V hub.yaml already exists." -ForegroundColor $GREEN
    }

    Write-Host ""

    # -- 6. Generate API key & .env file --------------------------------
    if (-not (Test-Path $ENV_FILE)) {
        $apiKey = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 43 | ForEach-Object {[char]$_})
        "HUB_API_KEY=$apiKey" | Set-Content -Path .env -Encoding UTF8
        Write-Host "V Generated API key and saved it in .env." -ForegroundColor $GREEN
        Write-Host ""
        Write-Host "  +----------------------------------------------------------+"
        Write-Host "  |  Your API key (save it somewhere safe!):                 |"
        Write-Host "  |  $apiKey"
        Write-Host "  +----------------------------------------------------------+"
    } else {
        Write-Host "V .env file already exists." -ForegroundColor $GREEN
    }

    Write-Host ""
    Write-Host "=========================================" -ForegroundColor $GREEN
    Write-Host "  Setup complete!" -ForegroundColor $GREEN
    Write-Host "=========================================" -ForegroundColor $GREEN
    Write-Host ""
}

# -- Load environment variables from .env -------------------------------
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
            }
        }
    }
    Write-Host "Environment variables loaded." -ForegroundColor Green
} else {
    Write-Host "Error: .env file not found. Something went wrong during setup." -ForegroundColor Red
    exit 1
}

# -- Check for required environment variables ---------------------------
if (-not $env:HUB_API_KEY) {
    Write-Host "Error: HUB_API_KEY not set in .env." -ForegroundColor Red
    exit 1
}

# -- Parse optional flags -----------------------------------------------
$host = "0.0.0.0"
$production = $false
$argsList = $args
$i = 0
while ($i -lt $argsList.Count) {
    switch ($argsList[$i]) {
        "--host" { $host = $argsList[++$i]; }
        "--no-reload" { $production = $true; }
        "--production" { $host = "0.0.0.0"; $production = $true; }
    }
    $i++
}

# -- Get port from environment or default to 8080 -----------------------
$port = if ($env:HUB_PORT) { [int]$env:HUB_PORT } else { 8080 }

# -- What's next (first run only) ---------------------------------------
if ($needsSetup) {
    Write-Host "  Next: edit hub.yaml to configure your agents, then restart."
    Write-Host ""
}

Write-Host ""
if ($production) {
    Write-Host "Starting Agent Hub in production mode..." -ForegroundColor Green
} else {
    Write-Host "Starting Agent Hub with auto-reload..." -ForegroundColor Green
}
Write-Host "Dashboard: http://localhost:$port" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor Green
Write-Host ""

# -- Auto-open browser --------------------------------------------------
Start-Process "http://localhost:$port"

# -- Start uvicorn ------------------------------------------------------
if ($production) {
    & $VENV_PYTHON -m uvicorn hub.api:app --host $host --port $port
} else {
    & $VENV_PYTHON -m uvicorn hub.api:app --host $host --port $port --reload
}
