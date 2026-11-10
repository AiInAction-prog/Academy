# =====================================================================
#  Morning MNQ Mean-Reversion  (single script for an 8am-3pm ET day)
#
#  PRACTICE ACCOUNT ONLY. Not trading advice. Educational example code
#  for the AI in Action course; the strategy isn't profitable as written.
#  Run it only on your TopStep Practice account. The bot refuses any
#  other account.
#
#  WHAT THIS IS: a z-score mean-reversion example on MNQ micros
#  ($2/pt, 1/10th of NQ), with ATR-scaled stops. New entries are gated
#  to the morning via ENTRY_END; the bot then only manages/flattens and
#  is flat by the close.
#
#  TIME MAP (your 8am-3pm ET window, in America/Chicago):
#    08:00 ET (07:00 CT)  launch -> idles until the open
#    09:30 ET (08:30 CT)  SESSION_OPEN -> entries begin
#    14:30 ET (13:30 CT)  ENTRY_END    -> no NEW entries (manage only)
#    16:00 ET (15:00 CT)  SESSION_CLOSE-> auto-flat 5 min before
#
#  Run it (from anywhere):
#     $env:ACCOUNT_ID='YOUR_PRACTICE_ACCOUNT_ID'
#     powershell -ExecutionPolicy Bypass -File Run_Library\run_meanrev_morning_mnq.ps1
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
$env:SYMBOL_ROOT = 'MNQ'             # micros: $2/pt (1/10th of NQ)
$env:CONTRACT_ID = ''                # blank -> auto-resolve MNQ front month
$env:TSX_ENV     = 'live'            # TopstepX gateway, where the Practice account lives

# --- Execution: 'false' sends orders to your Practice account ---
$env:PAPER_MODE  = 'false'

# --- Strategy: mean reversion (z2.0, lb80, ATR stops, trend filter off) ---
$env:STRATEGY              = 'mean_reversion'
$env:POLL_INTERVAL_SECONDS = '10'
$env:MR_LOOKBACK           = '80'
$env:MR_Z_ENTRY            = '2.0'
$env:STOP_MODE             = 'atr'    # volatility-scaled stops
$env:ATR_PERIOD            = '14'
$env:STOP_ATR_MULT         = '2.5'    # stop  = 2.5 x ATR
$env:TARGET_ATR_MULT       = '2.0'    # target = 2.0 x ATR
$env:STOP_POINTS           = '15'     # (unused in atr mode; kept as fixed-mode fallback)
$env:TARGET_POINTS         = '40'     # (unused in atr mode)
$env:COOLDOWN_SECONDS      = '60'
$env:MIN_HOLD_SECONDS      = '30'
$env:MAX_HOLD_SECONDS      = '0'
$env:TREND_FILTER          = 'false'
$env:SKIP_FIRST_MINUTES    = '0'
$env:ALLOW_LONG            = 'true'
$env:ALLOW_SHORT           = 'true'

# --- Session ---
$env:SESSION_TZ              = 'America/Chicago'
$env:SESSION_OPEN            = '08:30'  # 09:30 ET cash open
$env:ENTRY_END               = '13:30'  # 14:30 ET: no NEW entries after this
$env:SESSION_CLOSE           = '15:00'  # 16:00 ET
$env:FLATTEN_BEFORE_CLOSE_MIN = '5'

# --- Risk caps: the bot halts for the day when any of these is hit ---
$env:MAX_CONTRACTS_PER_TRADE = '2'
$env:MAX_TRADES_PER_DAY      = '8'
$env:DAILY_LOSS_LIMIT        = '800'
$env:TRAILING_DRAWDOWN       = '1800'
$env:MAX_CONSECUTIVE_LOSSES  = '5'
$env:DAILY_PROFIT_TARGET     = '700'
# Absolute account-balance floor: halts + flattens if the balance reaches
# this level, across restarts. Set it from your own Practice account balance.
if (-not $env:MIN_ACCOUNT_EQUITY) { $env:MIN_ACCOUNT_EQUITY = '48200' }

# --- Isolated logs + trade journal ---
$env:LOG_DIR      = 'logs/morning_mnq_meanrev'
$env:JOURNAL_FILE = 'data/morning_mnq_meanrev.csv'
$env:LOG_LEVEL    = 'INFO'

Write-Host 'PRACTICE ACCOUNT ONLY. Not trading advice.' -ForegroundColor Yellow
Write-Host "=== MNQ Mean-Reversion (ATR stops 2.5x/2.0x, trend OFF) | acct $($env:ACCOUNT_ID) | MNQ x$($env:MAX_CONTRACTS_PER_TRADE) ===" -ForegroundColor Cyan
Write-Host "Python: $Py" -ForegroundColor DarkGray
Write-Host 'Entries 08:30-13:30 CT (09:30-14:30 ET); flat by 15:00 CT.' -ForegroundColor DarkGray
Write-Host 'PAPER_MODE=false -> orders on your Practice account.' -ForegroundColor Yellow

& $Py run_bot.py --non-interactive
