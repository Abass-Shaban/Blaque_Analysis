# BLAQUE ANALYSIS — one-command local start (PowerShell)
#
#   .\run.ps1                # install deps if needed, sync once, start server
#   .\run.ps1 -SkipSync      # start without the initial provider sync
#   .\run.ps1 -Port 8001     # use a different port

param(
    [int]$Port = 8000,
    [switch]$SkipSync,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Green
    python -m venv .venv
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}

Write-Host "Installing dependencies..." -ForegroundColor Green
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r requirements.txt --quiet

if (-not $SkipSync) {
    Write-Host "Syncing real fixtures from ESPN (first run can take a few minutes)..." -ForegroundColor Green
    & $python -m backend.app.cli sync --months-back 15 --months-ahead 1 --workers 1
}

Write-Host "Starting BLAQUE ANALYSIS at http://localhost:$Port" -ForegroundColor Green
$uvicornArgs = @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$Port")
if ($Reload) { $uvicornArgs += "--reload" }
& $python @uvicornArgs
