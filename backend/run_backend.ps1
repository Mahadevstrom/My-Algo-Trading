$ErrorActionPreference = "Stop"

$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvActivate = Join-Path $BackendDir ".venv\Scripts\Activate.ps1"

if (-not (Test-Path -LiteralPath $VenvActivate)) {
    Write-Error "Virtual environment not found. Run: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt"
}

Set-Location $BackendDir

$PortInUse = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($PortInUse) {
    Write-Host "Port 8000 is already in use." -ForegroundColor Yellow
    Write-Host "To run manually on port 8010:" -ForegroundColor Yellow
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  uvicorn app.main:app --reload --host 127.0.0.1 --port 8010"
    Write-Host "See README.md for port check and stop-process commands."
    exit 1
}

. $VenvActivate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
