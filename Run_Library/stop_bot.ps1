# =====================================================================
#  Cleanly STOP the trading bot and optionally flatten one account.
#
#  Run:
#     powershell -ExecutionPolicy Bypass -File Run_Library\stop_bot.ps1
#     $env:ACCOUNT_ID='12345678'; powershell ... stop_bot.ps1   # also flatten
# =====================================================================

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Py = if (Test-Path $VenvPy) { $VenvPy } else { 'python' }

Write-Host '=== Stopping trading bot ===' -ForegroundColor Cyan

$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'run_bot\.py' }

if (-not $procs) {
    Write-Host 'No running bot processes found.' -ForegroundColor DarkGray
} else {
    foreach ($p in $procs) {
        Write-Host ("Killing PID {0}: {1}" -f $p.ProcessId, $p.CommandLine) -ForegroundColor Yellow
        taskkill /PID $p.ProcessId /T /F | Out-Null
    }
    Start-Sleep -Seconds 2
    $still = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'run_bot\.py' }
    if ($still) {
        Write-Host 'WARNING: some bot processes survived:' -ForegroundColor Red
        $still | Select-Object ProcessId, CommandLine | Format-List
    } else {
        Write-Host 'All bot processes terminated.' -ForegroundColor Green
    }
}

if ($env:ACCOUNT_ID) {
    $env:TSX_ENV = if ($env:TSX_ENV) { $env:TSX_ENV } else { 'live' }
    Write-Host "Flattening account $($env:ACCOUNT_ID) ..." -ForegroundColor Cyan
    & $Py run_bot.py --flatten --non-interactive
} else {
    Write-Host 'No ACCOUNT_ID set — skipped flatten. Run flatten_account.ps1 per account.' -ForegroundColor DarkGray
}

Write-Host '=== Done ===' -ForegroundColor Green
