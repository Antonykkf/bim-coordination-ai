# Bootstrap this project on a new machine (Windows).
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "Setting up BIM Coordination AI in $ProjectRoot"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11+ is required. Install it from https://www.python.org/downloads/"
}

python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Next steps:"
Write-Host "  1. Open this folder in Cursor (same account as your other laptop)."
Write-Host "  2. Activate: .\.venv\Scripts\Activate.ps1"
Write-Host "  3. Run API:  uvicorn bim_coordination_ai.main:app --reload"
Write-Host "  4. Open docs: http://localhost:8000/docs"
