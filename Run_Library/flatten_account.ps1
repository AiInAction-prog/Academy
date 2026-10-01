# =====================================================================
#  Flatten open positions on one TopstepX account.
#
#  Run once per account:
#     $env:ACCOUNT_ID='YOUR_ACCOUNT_ID'
#     powershell -ExecutionPolicy Bypass -File Run_Library\flatten_account.ps1
# =====================================================================

$ErrorActionPreference = 'Continue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not $env:ACCOUNT_ID) {
    Write-Host 'ERROR: set ACCOUNT_ID first, e.g. $env:ACCOUNT_ID=''12345678''' -ForegroundColor Red
    exit 1
}

$VenvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Py = if (Test-Path $VenvPy) { $VenvPy } else { 'python' }

$env:TSX_ENV = if ($env:TSX_ENV) { $env:TSX_ENV } else { 'live' }

Write-Host "Flattening account $($env:ACCOUNT_ID) ..." -ForegroundColor Yellow
& $Py run_bot.py --flatten --non-interactive
Write-Host 'Flatten complete.' -ForegroundColor Cyan
