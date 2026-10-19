# setup.ps1 — One-time setup for Agent Hub on Windows
# Safe to run more than once.  Run it in PowerShell from the Agent Hub folder.

$ErrorActionPreference = 'Stop'

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $SCRIPT_DIR

# ── Colours ──────────────────────────────────────────────────────────
$GREEN = 'Green'; $YELLOW = 'Yellow'; $RED = 'Red'

$info  = "✓"
$warn  = "⚠"
$fail  = "✗"

Write-Host ""
Write-Host "=========================================" -ForegroundColor $GREEN
Write-Host "  Agent Hub — Setup (Windows)" -ForegroundColor $GREEN
Write-Host "=========================================" -ForegroundColor $GREEN
Write-Host ""

# ── 1. Check Python 3.11+ ───────────────────────────────────────────
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "$fail Python is not installed. Install it from https://www.python.org/downloads/" -ForegroundColor $RED
    Write-Host "   Make sure to check 'Add Python to PATH' during installation." -ForegroundColor $RED
    exit 1
}

$pyVer = python --version 2>&1
$pyMajor = (python -c "import sys; print(sys.version_info.major)").Trim()
$pyMinor = (python -c "import sys; print(sys.version_info.minor)").Trim()

if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 11)) {
    Write-Host "$fail Python $pyVer is too old. Agent Hub needs Python 3.11 or newer." -ForegroundColor $RED
    exit 1
}

Write-Host "$info Python $pyVer — good." -ForegroundColor $GREEN

# ── 2. Check Junie CLI ──────────────────────────────────────────────
$junie = Get-Command junie -ErrorAction SilentlyContinue
if (-not $junie) {
    Write-Host ""
    Write-Host "$warn The 'junie' command was not found on your PATH." -ForegroundColor $YELLOW
    Write-Host "   Agent Hub needs Junie CLI to run agents." -ForegroundColor $YELLOW
    Write-Host "   Install it from https://junie.jetbrains.com and make sure 'junie' is on your PATH." -ForegroundColor $YELLOW
    Write-Host ""
    Write-Host "   You can still start the hub without junie, but agents won't run." -ForegroundColor $YELLOW
    Write-Host "   Press Enter to continue anyway, or Ctrl+C to abort." -ForegroundColor $YELLOW
    Read-Host
} else {
    $junieVer = junie --version 2>&1 | Select-Object -First 1
    Write-Host "$info Junie CLI found ($junieVer)." -ForegroundColor $GREEN
}

Write-Host ""

# ── 3. Create virtual environment ───────────────────────────────────
$venvPath = Join-Path $SCRIPT_DIR '.venv'
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment (.venv) …"
    python -m venv .venv
    Write-Host "$info Virtual environment created." -ForegroundColor $GREEN
} else {
    Write-Host "$info Virtual environment already exists." -ForegroundColor $GREEN
}

# ── 4. Install Python dependencies ──────────────────────────────────
Write-Host "Installing Python packages …"
& (Join-Path $venvPath 'Scripts\python.exe') -m pip install --upgrade pip -q
& (Join-Path $venvPath 'Scripts\python.exe') -m pip install -r requirements.txt -q
Write-Host "$info Packages installed." -ForegroundColor $GREEN

Write-Host ""

# ── 5. Copy hub.example.yaml → hub.yaml (never overwrite) ───────────
$hubYaml = Join-Path $SCRIPT_DIR 'hub.yaml'
if (-not (Test-Path $hubYaml)) {
    Copy-Item hub.example.yaml hub.yaml
    Write-Host "$info Created hub.yaml from hub.example.yaml." -ForegroundColor $GREEN
    Write-Host "     Edit hub.yaml to set project_dir and other settings." -ForegroundColor $GREEN
} else {
    Write-Host "$info hub.yaml already exists (not overwritten)." -ForegroundColor $GREEN
}

Write-Host ""

# ── 6. Generate API key & .env file ─────────────────────────────────
$envFile = Join-Path $SCRIPT_DIR '.env'
if (-not (Test-Path $envFile)) {
    $apiKey = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 43 | ForEach-Object {[char]$_})
    "HUB_API_KEY=$apiKey" | Set-Content -Path .env -Encoding UTF8
    Write-Host "$info Generated API key and saved it in .env." -ForegroundColor $GREEN
    Write-Host ""
    Write-Host "  ┌──────────────────────────────────────────────────────────┐"
    Write-Host "  │  Your API key (save it somewhere safe!):                 │"
    Write-Host "  │  $apiKey"
    Write-Host "  └──────────────────────────────────────────────────────────┘"
} else {
    Write-Host "$info .env file already exists (not overwritten)." -ForegroundColor $GREEN
    Write-Host "     Your API key is stored in .env." -ForegroundColor $GREEN
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor $GREEN
Write-Host "  Setup complete!" -ForegroundColor $GREEN
Write-Host "=========================================" -ForegroundColor $GREEN
Write-Host ""
Write-Host "What's next:" -ForegroundColor $GREEN
Write-Host ""
Write-Host "  1. Edit hub.yaml — set project_dir for each agent."
Write-Host "  2. Start the server:"
Write-Host "     .\start.ps1"
Write-Host "  3. Open http://localhost:8080 in your browser."
Write-Host "     Enter the API key from .env when prompted."
Write-Host ""
