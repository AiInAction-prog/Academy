# =====================================================================
#  MES VWAP Trend-Pullback
#
#  PRACTICE ACCOUNT ONLY. Not trading advice. Educational example code
#  for the AI in Action course; the strategy isn't profitable as written.
#  Run it only on your TopStep Practice account. The bot refuses any
#  other account.
#
#  WHAT THIS IS: only trades WITH the trend (ADX >= 30), buying pullbacks
#  to session VWAP in an uptrend and selling rallies in a downtrend, with
#  a 1.5R target and a stop beyond VWAP.
#
#  Run (paper first):
#     $env:ACCOUNT_ID='YOUR_PRACTICE_ACCOUNT_ID'
#     powershell -ExecutionPolicy Bypass -File ES_Strategy\run_es_vwaptrend.ps1
# =====================================================================

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Py = if (Test-Path $VenvPy) { $VenvPy } else { 'python' }

# --- Account + instrument ---
if (-not $env:ACCOUNT_ID) {
    Write-Host 'ERROR: set ACCOUNT_ID to your Practice account, e.g. $env:ACCOUNT_ID=''YOUR_PRACTICE_ACCOUNT_ID''' -ForegroundColor Red
    Write-Host 'Find it with: python discover-accounts.py' -ForegroundColor Red
    exit 1
}
$env:SYMBOL_ROOT = 'MES'
$env:CONTRACT_ID = ''                # blank -> auto-resolve MES front month
$env:TSX_ENV     = 'live'            # TopstepX gateway, where the Practice account lives

# --- Execution: starts in paper. 'false' sends orders to your Practice account.
if (-not $env:PAPER_MODE) { $env:PAPER_MODE = 'true' }

# --- Strategy: VWAP trend-pullback ---
$env:STRATEGY                    = 'vwap_trend'
$env:POLL_INTERVAL_SECONDS       = '10'
$env:VWAP_TREND_ADX_MIN          = '30'
$env:VWAP_TREND_TARGET_R         = '1.5'
$env:VWAP_STOP_MODE              = 'band'
$env:VWAP_STOP_BUFFER            = '4.0'
$env:VWAP_TREND_COOLDOWN_SECONDS = '120'
$env:VWAP_TREND_MAX_TRADES       = '10'
$env:VWAP_REQUIRE_REJECTION      = 'true'
$env:ADX_PERIOD                  = '14'
$env:MIN_HOLD_SECONDS            = '30'
$env:MAX_HOLD_SECONDS            = '0'
$env:SKIP_FIRST_MINUTES          = '0'
$env:ALLOW_LONG                  = 'true'
$env:ALLOW_SHORT                 = 'true'

# --- Session (CME RTH = 08:30-15:00 CT) ---
$env:SESSION_TZ               = 'America/Chicago'
$env:SESSION_OPEN            = '08:30'
$env:SESSION_CLOSE           = '15:00'
$env:FLATTEN_BEFORE_CLOSE_MIN = '5'

# --- Risk caps: the bot halts for the day when any of these is hit ---
$env:MAX_CONTRACTS_PER_TRADE = '5'
$env:DAILY_LOSS_LIMIT        = '900'
$env:TRAILING_DRAWDOWN       = '1800'
$env:MAX_TRADES_PER_DAY      = '10'
$env:MAX_CONSECUTIVE_LOSSES  = '4'
$env:DAILY_PROFIT_TARGET     = '0'
# Absolute account-balance floor: halts + flattens if the balance reaches
# this, across restarts. Set it from your own Practice account balance.
if (-not $env:MIN_ACCOUNT_EQUITY) { $env:MIN_ACCOUNT_EQUITY = '48200' }

# --- Isolated logs + journal ---
$env:LOG_DIR      = 'logs/es_vwaptrend'
$env:JOURNAL_FILE = 'data/es_vwaptrend.csv'
$env:LOG_LEVEL    = 'INFO'

Write-Host 'PRACTICE ACCOUNT ONLY. Not trading advice.' -ForegroundColor Yellow
Write-Host "=== MES VWAP Trend-Pullback (R1.5) | acct $($env:ACCOUNT_ID) | MES x$($env:MAX_CONTRACTS_PER_TRADE) ===" -ForegroundColor Cyan
Write-Host "Python: $Py" -ForegroundColor DarkGray
Write-Host "PAPER_MODE=$($env:PAPER_MODE)" -ForegroundColor Yellow

& $Py run_bot.py --non-interactive
